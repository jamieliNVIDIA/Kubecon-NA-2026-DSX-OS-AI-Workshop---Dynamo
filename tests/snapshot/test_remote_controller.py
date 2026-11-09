"""Durable Snapshot qualification preserves source, storage and phase gates."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import demos.snapshot.remote_controller as subject


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def plan_fixture(root):
    run = root / 'results/fresh-snapshot'
    run.mkdir(parents=True)
    source = root / 'scripts/controller.py';source.parent.mkdir();source.write_text('fixed source')
    frozen = run / 'deployment.json';frozen.write_text('{"immutable":true}')
    dump(run / 'snapshot-dgd-spec.json', {'spec': 'fixed'})
    dump(run / 'state.json', {'namespace': 'dynamo-ft-fresh', 'checks': {'model-staging': {'status': 'passed'}}})
    dump(run / 'demo.json', {'namespace': 'dynamo-ft-fresh', 'prepared': True, 'rehearsal': False,
                           'storage': 'nvme', 'inputs': {'deployment.json': subject.digest(frozen)}})
    reservation = {'agent': subject.OWNER, 'run': str(run), 'acquired_at': 'fixed'}
    dump(root / '.local/workshop-measurements-20261030.gpu-lease/owner.json', reservation)
    plan = {'schema': 1, 'run': str(run.relative_to(root)), 'logical_root': str(root), 'mode': 'full',
        'reservation': reservation, 'prime_timeout_seconds': 5400,
        'source_sha256': {'scripts/controller.py': subject.digest(source)},
        'run_input_sha256': {'deployment.json': subject.digest(frozen)},
        'recording': 'demos/transcripts/live/04-snapshot-dgd/' + run.name}
    return run, plan


class Plan(unittest.TestCase):
    def test_only_cpu_prepared_never_deployed_run_with_exact_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);run, plan = plan_fixture(root)
            self.assertEqual(subject.validate_plan(plan, root)[0], run)
            state = subject.read(run / 'state.json');state['snapshot_dgd_uid'] = 'already-used'
            dump(run / 'state.json', state)
            with self.assertRaisesRegex(ValueError, 'never-deployed'):
                subject.validate_plan(plan, root)

    def test_source_hash_wrong_lease_and_escaping_paths_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);run, plan = plan_fixture(root)
            changed = copy.deepcopy(plan);changed['recording'] = '../../outside'
            with self.assertRaises(ValueError):subject.validate_plan(changed, root)
            changed = copy.deepcopy(plan);changed['run'] = '/outside'
            with self.assertRaises(ValueError):subject.validate_plan(changed, root)
            lease = root / '.local/workshop-measurements-20261030.gpu-lease/owner.json'
            dump(lease, {'agent': 'other', 'run': str(run)})
            with self.assertRaisesRegex(ValueError, 'reservation'):
                subject.validate_plan(plan, root)
            dump(lease, plan['reservation'])
            (root / 'scripts/controller.py').write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                subject.validate_plan(plan, root)

    def test_fixed_executable_inputs_rechecked_between_phases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);run, plan = plan_fixture(root)
            controller = subject.Controller(root, plan, run, root / plan['recording'])
            controller.unchanged()
            (run / 'deployment.json').write_text('different serving settings')
            with self.assertRaisesRegex(ValueError, 'executable input changed'):
                controller.unchanged()


def prime_fixture(run):
    identity = {'dgd_uid': 'dgd', 'worker_uid': 'worker', 'source_uid': 'capture', 'frontend_uid': 'frontend',
        'service_uid': 'service', 'content_uid': 'content', 'node': 'node', 'gpu_uuids': ['A', 'B'],
        'response_worker': {'decode_worker_id': 12}}
    content = 'def add(a, b):\n    return a + b'
    chunks = {'model': 'model', 'choices': [{'delta': {'content': content}, 'finish_reason': 'stop'}],
              'nvext': {'worker_id': {'decode_worker_id': 12}}}
    response = {'content': content, 'worker': {'decode_worker_id': 12}, 'request': {'model': 'model'},
                'sse': 'data: ' + json.dumps(chunks) + '\ndata: [DONE]\n'}
    manifest = run / 'nvme-artifact-files.sha256';manifest.write_text('verified file manifest')
    state = {'snapshot_dgd_uid': 'dgd', 'nvme_overlay': True, 'workshop_snapshot_nvme': {
        'staged': True, 'overlay_verified': True, 'source': {'artifact_uid': 'content'},
        'expected_files': 1, 'expected_bytes': 100, 'hash_manifest_sha256': subject.digest(manifest)}}
    demo = {'rehearsal': False, 'ready_observed_at': 'observed', 'initial_identity': identity, 'model': 'model'}
    for name, value in [('state.json', state), ('demo.json', demo), ('initial-identity.json', identity),
                        ('initial-request.json', response), ('request.json', response['request']),
                        ('snapshot-dgd-spec.json', {'settings': {'node': 'node', 'gpu_uuids': ['A', 'B']}})]:
        dump(run / name, value)


class PrimeProof(unittest.TestCase):
    def test_finished_stream_and_verified_live_nvme_required(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp);prime_fixture(run)
            self.assertEqual(subject.prime_proof(run)['content_uid'], 'content')
            response = subject.read(run / 'initial-request.json');response['sse'] = response['sse'].replace('data: [DONE]', '')
            dump(run / 'initial-request.json', response)
            with self.assertRaises(ValueError):subject.prime_proof(run)

    def test_readiness_alone_cannot_replace_storage_and_inference_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp);prime_fixture(run)
            state = subject.read(run / 'state.json');state['workshop_snapshot_nvme']['staged'] = False
            dump(run / 'state.json', state)
            with self.assertRaisesRegex(ValueError, 'storage/identity/inference'):
                subject.prime_proof(run)

    def test_changed_manifest_or_request_shape_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp);prime_fixture(run)
            (run / 'nvme-artifact-files.sha256').write_text('changed manifest')
            with self.assertRaises(ValueError):subject.prime_proof(run)
            prime_fixture(run)
            response = subject.read(run / 'initial-request.json');response['request']['model'] = 'other'
            dump(run / 'initial-request.json', response)
            with self.assertRaises(ValueError):subject.prime_proof(run)


class Pipeline(unittest.TestCase):
    def execute_fake(self, root, *, failed_phase=None, reject_proof=False, fail_cleanup=False):
        run, plan = plan_fixture(root)
        recording = root / plan['recording']
        controller = subject.Controller(root, plan, run, recording)
        calls = []
        def command(phase, argv, timeout):
            calls.append(phase)
            (controller.folder / phase).mkdir()
            if phase == failed_phase:raise RuntimeError('actual phase failed')
        def proof(*args):
            if reject_proof:raise ValueError('completion proof absent despite exit0')
            return {'verified': True}
        with patch.object(controller, 'command', side_effect=command), patch.object(controller, 'diagnostics'), \
                patch.object(subject, 'prime_proof', side_effect=proof), patch.object(subject, 'capture_proof', return_value={'verified': True}), \
                patch.object(subject, 'cleanup_proof', side_effect=ValueError('lease retained') if fail_cleanup else lambda *a: {'passed': True}), \
                patch('sys.stdout'):
            code = controller.execute()
        return code, calls, subject.read(run / 'remote-controller-exit.json')

    def test_full_success_includes_cleanup_but_requires_independent_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            code, calls, result = self.execute_fake(Path(temp))
            self.assertEqual(code, 0)
            self.assertEqual(calls, ['prime', 'capture', 'cleanup'])
            self.assertEqual(result['status'], 'qualified_and_cleaned_pending_root_audit')

    def test_prime_failure_never_injects_a_presenter_fault_and_still_scopes_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            code, calls, result = self.execute_fake(Path(temp), failed_phase='prime')
            self.assertEqual(code, 1);self.assertEqual(calls, ['prime', 'cleanup'])
            self.assertEqual(result['status'], 'failed')

    def test_zero_exit_without_prime_evidence_never_reaches_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            code, calls, result = self.execute_fake(Path(temp), reject_proof=True)
            self.assertEqual(code, 1);self.assertEqual(calls, ['prime', 'cleanup'])
            self.assertIn('proof absent', result['error'])

    def test_cleanup_proof_failure_prevents_qualified_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            code, calls, result = self.execute_fake(Path(temp), fail_cleanup=True)
            self.assertEqual(code, 1)
            self.assertEqual(result['status'], 'failed_cleanup_incomplete')


if __name__ == '__main__':
    unittest.main()
