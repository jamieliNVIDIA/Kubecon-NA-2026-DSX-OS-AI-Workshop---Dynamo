"""Independent negative review of the scoped full Shadow remote adapter.

All transport is mocked. PTYs, where used, print synthetic unit-test text.
No SSH, Kubernetes, Docker or GPU actions are performed.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.full_remote as transport
import demos.shadow.full_remote_controller as controller
import tests.shadow.test_remote as author
import tests.shadow.test_capture_composed as captured
import demos.common.capture as capture


class FullRemoteReviewTests(unittest.TestCase):
    @contextlib.contextmanager
    def packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run, health, baseline, image, lease, state, spec = author.fixture(root)
            with author.Packaging().context(root):
                before, owner = author.tree(run), lease.read_bytes()
                transport.build(run, health, baseline, image)
                run, control, prep, manifest, digest = transport.package(run)
                plan = json.loads((prep / 'plan.json').read_text())
                yield SimpleNamespace(root=root, run=run, control=control, prep=prep, lease=lease,
                    before=before, owner=owner, plan=plan, manifest=manifest)

    def test_plan_rejects_path_scope_lease_and_exact_fault_count_changes(self):
        with self.packaged() as f:
            for case in ('inside-control', 'other-control', 'raw-in-run', 'other-recording', 'other-namespace',
                    'lease-name', 'owner-run', 'owner-node', 'owner-gpus', 'node', 'gpu-uuids', 'bool-fault-count'):
                with self.subTest(case=case):
                    plan = copy.deepcopy(f.plan)
                    if case == 'inside-control': plan['control'] = plan['run'] + '/controller'
                    elif case == 'other-control': plan['control'] = 'results/other-control'
                    elif case == 'raw-in-run': plan['raw_recording'] = plan['run'] + '/raw'
                    elif case == 'other-recording': plan['recording'] += '-other'
                    elif case == 'other-namespace': plan['namespace'] += '-other'
                    elif case == 'lease-name': plan['reservation_directory'] = 'other.gpu-lease'
                    elif case == 'owner-run': plan['reservation']['run'] += '-other'
                    elif case == 'owner-node': plan['reservation']['node'] = 'other'
                    elif case == 'owner-gpus': plan['reservation']['gpu_uuids'] = list(reversed(transport.UUIDS))
                    elif case == 'node': plan['node'] = 'other'
                    elif case == 'gpu-uuids': plan['gpu_uuids'] = ['GPU-other']
                    elif case == 'bool-fault-count': plan['fault_count'] = True
                    with self.assertRaises(ValueError): transport.validate_plan(plan, f.root)
            self.assertEqual(author.tree(f.run), f.before)
            self.assertEqual(f.lease.read_bytes(), f.owner)

    def test_borrowing_rejects_symlinked_owner_or_lease_ancestor(self):
        for case in ('owner', 'ancestor'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                run, health, baseline, image, lease, state, spec = author.fixture(root)
                if case == 'owner':
                    target = root / 'owner-copy.json'; target.write_bytes(lease.read_bytes())
                    lease.unlink(); lease.symlink_to(target)
                else:
                    target = root / 'lease-copy'
                    lease.parent.rename(target)
                    lease.parent.symlink_to(target, target_is_directory=True)
                before = lease.read_bytes()
                with author.Packaging().context(root), self.assertRaises(ValueError):
                    transport.build(run, health, baseline, image)
                self.assertEqual(lease.read_bytes(), before)
                self.assertFalse(run.with_name(run.name + '-remote-control').exists())

    def test_per_phase_checks_bind_nested_writer_state_sources_and_exact_owner(self):
        for case in ('basis', 'source', 'owner'):
            with self.subTest(case=case), self.packaged() as f:
                instance = controller.Controller(f.root, f.plan)
                instance.unchanged()
                if case == 'basis': (f.run / 'writer-basis/state.json').write_text('{}')
                elif case == 'source':
                    source = next(name for name in f.plan['source_sha256'] if name.startswith('scripts/'))
                    (f.root / source).write_text('changed')
                else:
                    value = json.loads(f.lease.read_text()); value['acquired_at'] = 'another-generation'
                    f.lease.write_text(json.dumps(value))
                with self.assertRaises(ValueError): instance.unchanged()

    def test_source_or_lease_drift_blocks_launch_before_transport_and_intent(self):
        for case in ('source', 'lease'):
            with self.subTest(case=case), self.packaged() as f:
                if case == 'source':
                    source = next(name for name in f.plan['source_sha256'] if name.startswith('scripts/'))
                    (f.root / source).write_text('changed source')
                else: f.lease.write_text('{}')
                with patch.object(transport.subprocess, 'run') as network, self.assertRaises(ValueError): transport.launch(f.run)
                network.assert_not_called()
                self.assertFalse((f.prep / 'launch-intent.json').exists())

    def test_uncertain_launch_cannot_repeat_and_keeps_root_lease(self):
        with self.packaged() as f:
            failed = SimpleNamespace(returncode=1, stderr=b'synthetic uncertain transport', stdout=b'')
            with patch.object(transport.subprocess, 'run', return_value=failed) as network:
                with self.assertRaisesRegex(RuntimeError, 'never replay'): transport.launch(f.run)
                with self.assertRaises(FileExistsError): transport.launch(f.run)
            self.assertEqual(network.call_count, 1)
            self.assertEqual(f.lease.read_bytes(), f.owner)
            self.assertEqual(author.tree(f.run), f.before)

    def test_failed_source_guard_preserves_reservation_when_safe_cleanup_cannot_run(self):
        with self.packaged() as f:
            instance = controller.Controller(f.root, f.plan)
            source = next(name for name in f.plan['source_sha256'] if name.startswith('scripts/'))
            (f.root / source).write_text('changed source')
            with patch.object(controller, 'ready_proof', side_effect=AssertionError('No readiness after guard failure')), \
                    patch.object(controller.BoundedController, 'stop_child'), \
                    patch.object(subprocess, 'Popen') as child, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(instance.execute(), 1)
            child.assert_not_called()
            result = json.loads((f.control / 'full-remote-exit.json').read_text())
            self.assertEqual(result['status'], 'failed_preserved_for_root_audit')
            self.assertIn('cleanup_error', result)
            self.assertFalse(result['local_reservation_released'])
            self.assertEqual(f.lease.read_bytes(), f.owner)

    def pending(self, f):
        args = captured.ComposedCaptureTests().pending(f)
        return args, controller.pending_proof(f.run, args.output, args.raw_output)

    def test_real_pending_seal_and_each_private_binding_are_required(self):
        for case in ('seal', 'timeline', 'before', 'health', 'source', 'evidence', 'current-run'):
            with self.subTest(case=case), captured.fixture() as f:
                args, proof = self.pending(f)
                if case == 'seal': path = args.raw_output / 'pending-receipt.json'
                elif case == 'timeline': path = args.raw_output / 'timeline.jsonl'
                elif case == 'before': path = args.raw_output / 'demo-before.json'
                elif case == 'health': path = args.raw_output / 'pre-fault-health-source.json'
                elif case == 'source': path = next((args.raw_output / 'sources').glob('*.py'))
                elif case == 'evidence': path = args.raw_output / 'evidence/shadow-fault.json'
                else: path = f.run / 'shadow-fault.json'
                path.chmod(0o600);path.write_text('{}')
                with self.assertRaises((ValueError, OSError)):
                    controller.pending_proof(f.run, args.output, args.raw_output)

    def test_final_proof_requires_same_recording_and_pending_provenance(self):
        with captured.fixture() as f:
            args, pending = self.pending(f)
            captured.qualify(f)
            args.defer_qualification, args.finalize_pending = False, True
            self.assertEqual(capture.capture(args), 0)
            self.assertEqual(controller.final_proof(f.run, args.output, args.raw_output, pending)['provenance'], pending['provenance'])
            path = args.output / 'capture.json'
            receipt = json.loads(path.read_text())
            for case in ('output', 'provenance'):
                value = copy.deepcopy(receipt)
                if case == 'output': value['output'] += '-other'
                else: value['startup_provenance']['dgd_uid'] = 'other'
                path.write_text(json.dumps(value))
                with self.subTest(case=case), self.assertRaises(ValueError):
                    controller.final_proof(f.run, args.output, args.raw_output, pending)
            path.write_text(json.dumps(receipt))
            changed = copy.deepcopy(pending); changed['provenance']['dgd_uid'] = 'different-first-capture'
            with self.assertRaises(ValueError): controller.final_proof(f.run, args.output, args.raw_output, changed)


if __name__ == '__main__': unittest.main()
