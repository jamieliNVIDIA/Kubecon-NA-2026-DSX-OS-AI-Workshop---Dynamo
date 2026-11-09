"""Full adapter keeps journals/health outside pending Run and never repeats a fault."""
from tests.support import ROOT
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.source_paths import source_path
import demos.shadow.full_remote as transport
import demos.shadow.full_remote_controller as controller
import demos.shadow.composed as composed
import scripts.development.mx_cache.workflow as dev_cache
from tests.shadow.test_writer_remote import fixture as writer_fixture, write
import tests.development.mx_cache.test_stage as cache_stage_tests


def fixture(root):
    run, health, baseline, image, state, spec = writer_fixture(root)
    (root / transport.CONTROLLER).write_text('# full controller\n')
    for name in transport.INPUTS - set(spec['inputs']): (run / name).write_text('{}\n')
    config = root / 'configs/dgd/workshop-shadow-composed' / run.name / 'deployment.yaml'
    config.parent.mkdir(parents=True);config.write_text('kind: DynamoGraphDeployment\n')
    basis = run / 'writer-basis/state.json'
    write(basis, {'namespace': 'dynamo-ft-original-writer', 'checks': {'shadow-writer-cleanup': {'status': 'passed'}}})
    spec.update(profile=transport.PROFILE, reader_enabled=True, reader_adapter_revision=transport.REVISION,
        inputs={name: transport.sha(run / name) for name in transport.INPUTS},
        writer_basis_receipts={'state.json': transport.sha(basis)}, source_writer_namespace='dynamo-ft-original-writer',
        config_manifest=str(config), config_manifest_sha256=transport.sha(config))
    write(run / 'full-spec.json', spec)
    state.update(shadow_full_profile=transport.PROFILE, shadow_full_spec_sha256=transport.sha(run / 'full-spec.json'))
    write(run / 'state.json', state)
    write(run / 'demo.json', {'namespace': state['namespace'], 'profile': transport.PROFILE,
        'rehearsal': False, 'prepared': True})
    lease = root / '.local' / (state['namespace'] + '-shadow.gpu-lease') / 'owner.json'
    write(lease, {'owner': transport.OWNER, 'run': str(run), 'node': transport.NODE,
        'gpu_uuids': transport.UUIDS, 'acquired_at': '2026-11-05T00:00:00+00:00'})
    return run, health, baseline, image, lease, state, spec


def tree(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}


def cache_fixture(root):
    values = fixture(root)
    run, _, _, _, _, state, spec = values
    for name in transport.CACHE_SOURCES:
        source = source_path(name, root=root)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('# frozen cache helper\n')
        target = run / 'source-snapshot' / name;target.write_bytes(source.read_bytes())
        spec['source_snapshot'][name] = transport.sha(source)
    for name in transport.CACHE_INPUTS:
        write(run / name, {'kind': name, 'producer_uid': 'qualified-original'})
        spec['inputs'][name] = transport.sha(run / name)
    spec['dev_cache'] = {'schema': 1, 'candidate_id': run.name,
        'qualification_sha256': spec['inputs']['dev-cache-qualification.json'],
        'bootstrap_sha256': spec['inputs']['dev-cache-bootstrap.json'],
        'receipt_sha256': spec['inputs']['dev-cache-receipt.json'],
        'source_sha256': {name: spec['source_snapshot'][name] for name in transport.CACHE_SOURCES}}
    write(run / 'full-spec.json', spec)
    state['shadow_full_spec_sha256'] = transport.sha(run / 'full-spec.json');write(run / 'state.json', state)
    return values


class Packaging(unittest.TestCase):
    def context(self, root):
        stack = contextlib.ExitStack()
        for module in (transport, transport.common, transport.writer_transport):
            stack.enter_context(patch.object(module, 'ROOT', root))
        return stack

    def test_build_borrows_exact_lease_and_never_writes_inside_full_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, lease, _, _ = fixture(root)
            (run / 'command-secret.json').write_text('credential-value')
            (run / 'manifest-secret.json').write_text('credential-value')
            before, owner = tree(run), lease.read_bytes()
            with self.context(root):
                result = transport.build(run, health, baseline, image)
                _, control, prep, _, _ = transport.package(run)
                plan = json.loads((prep / 'plan.json').read_text())
                self.assertEqual(transport.validate_plan(plan, root), run)
            self.assertEqual(tree(run), before)
            self.assertEqual(lease.read_bytes(), owner)
            self.assertNotIn(run, control.parents)
            self.assertFalse(result['lease_acquired_or_changed'])
            self.assertIn('writer-basis/state.json', plan['immutable_run_sha256'])
            self.assertNotIn('state.json', plan['immutable_run_sha256'])
            self.assertNotIn('demo.json', plan['immutable_run_sha256'])
            manifest = json.loads((prep / 'payload-manifest.json').read_text())
            self.assertFalse(any('command-secret' in name or 'manifest-secret' in name or '.local' in name for name in manifest['files']))

    def test_old_reader_prior_fault_or_foreign_lease_refused_without_side_effects(self):
        for kind in ('reader', 'fault', 'lease'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, health, baseline, image, lease, state, spec = fixture(root)
                if kind == 'reader':
                    spec['reader_adapter_revision'] = 'old-reader';write(run / 'full-spec.json', spec)
                    state['shadow_full_spec_sha256'] = transport.sha(run / 'full-spec.json');write(run / 'state.json', state)
                elif kind == 'fault': write(run / 'shadow-fault-intent.json', {})
                else: write(lease, {'owner': 'foreign'})
                before, owner = tree(run), lease.read_bytes()
                with self.context(root), self.assertRaises(ValueError): transport.build(run, health, baseline, image)
                self.assertEqual(tree(run), before);self.assertEqual(lease.read_bytes(), owner)
                self.assertFalse(run.with_name(run.name + '-remote-control').exists())

    def test_bootstrap_is_full_scoped_and_image_provenance_is_outside_run(self):
        value = transport.bootstrap()
        compile(value, '<full-bootstrap>', 'exec')
        compile(transport.STATUS, '<full-status>', 'exec')
        compile(transport.COLLECT, '<full-collector>', 'exec')
        self.assertIn("plan['reservation']['owner']!='workshop-demo-shadow'", value)
        self.assertIn("run_path=plan['control']", value)
        for module in ('demos.shadow.composed', 'demos.shadow.full_remote_controller', 'demos.common.capture'):
            self.assertIn(module, value)
        self.assertIn("'recording-private':w/plan['control']", transport.COLLECT)

    def test_optional_cache_preserves_qualification_and_exact_source_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, lease, _, spec = cache_fixture(root)
            before, owner = tree(run), lease.read_bytes()
            with self.context(root), patch.object(composed, 'validate_candidate_cache', return_value=spec['dev_cache'], create=True) as validated:
                transport.build(run, health, baseline, image)
                _, _, prep, manifest, _ = transport.package(run)
                plan = json.loads((prep / 'plan.json').read_text())
                transport.validate_plan(plan, root)
            self.assertGreaterEqual(validated.call_count, 1)
            self.assertEqual(plan['dev_cache'], spec['dev_cache'])
            self.assertEqual(tree(run), before);self.assertEqual(lease.read_bytes(), owner)
            for name in transport.CACHE_INPUTS:
                self.assertEqual(plan['immutable_run_sha256'][name], spec['inputs'][name])
                self.assertIn(str(run.relative_to(root) / name), manifest['files'])
            for name in transport.CACHE_SOURCES:
                self.assertIn('source-snapshot/' + name, plan['immutable_run_sha256'])

    def test_cache_inputs_cannot_expand_default_or_substitute_qualification_sources(self):
        for case in ('no-binding', 'extra-file', 'candidate', 'qualification', 'source-fence', 'source-omitted', 'bool-schema'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, health, baseline, image, lease, state, spec = cache_fixture(root)
                if case == 'no-binding': spec.pop('dev_cache')
                elif case == 'extra-file':
                    write(run / 'unapproved-cache.json', {});spec['inputs']['unapproved-cache.json'] = transport.sha(run / 'unapproved-cache.json')
                elif case == 'candidate': spec['dev_cache']['candidate_id'] = 'different-full-run'
                elif case == 'qualification':
                    write(run / 'dev-cache-qualification.json', {'producer_uid': 'replaced-producer'})
                    spec['inputs']['dev-cache-qualification.json'] = transport.sha(run / 'dev-cache-qualification.json')
                elif case == 'source-fence': spec['dev_cache']['source_sha256']['mx_dev_cache_stage.py'] = 'f' * 64
                elif case == 'source-omitted': spec['source_snapshot'].pop('mx_dev_cache_stage.py')
                else: spec['dev_cache']['schema'] = True
                write(run / 'full-spec.json', spec)
                state['shadow_full_spec_sha256'] = transport.sha(run / 'full-spec.json');write(run / 'state.json', state)
                before, owner = tree(run), lease.read_bytes()
                with self.context(root), patch.object(composed, 'validate_candidate_cache', create=True) as validated, self.assertRaises(ValueError):
                    transport.build(run, health, baseline, image)
                validated.assert_not_called()
                self.assertEqual(tree(run), before);self.assertEqual(lease.read_bytes(), owner)
                self.assertFalse(run.with_name(run.name + '-remote-control').exists())

    def test_cache_qualification_validator_refusal_blocks_transport_before_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, lease, _, _ = cache_fixture(root)
            before, owner = tree(run), lease.read_bytes()
            with self.context(root), patch.object(composed, 'validate_candidate_cache',
                    side_effect=ValueError('producer/image or stage receipt fence failed'), create=True) as validated, \
                    self.assertRaisesRegex(ValueError, 'producer/image'):
                transport.build(run, health, baseline, image)
            validated.assert_called_once()
            self.assertEqual(tree(run), before);self.assertEqual(lease.read_bytes(), owner)
            self.assertFalse(run.with_name(run.name + '-remote-control').exists())

    def test_real_cache_validator_rejects_producer_substitution_after_hash_rebinding(self):
        stage = cache_stage_tests.StageTests();stage.setUp();self.addCleanup(stage.doCleanups)
        qualification = stage.qualification()  # Bounded fake stream with real all-file hash receipts; no GPU/RPC.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _, _, lease, state, spec = fixture(root)
            for name in transport.CACHE_SOURCES:
                source = source_path(name, root=ROOT)
                target = source_path(name, root=root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
                (run / 'source-snapshot' / name).write_bytes(source.read_bytes())
                spec['source_snapshot'][name] = transport.sha(source)
            qualification_path = run / 'dev-cache-qualification.json';write(qualification_path, qualification)
            with patch.object(dev_cache, 'ROOT', root):
                graph, bootstrap, receipt = dev_cache.apply_candidate_cache(stage.graph(), qualification_path, candidate_id=run.name)
            write(run / 'deployment.json', graph)
            write(run / 'dev-cache-bootstrap.json', bootstrap)
            write(run / 'dev-cache-receipt.json', receipt)
            spec['inputs']['deployment.json'] = transport.sha(run / 'deployment.json')
            spec['inputs'].update({name: transport.sha(run / name) for name in transport.CACHE_INPUTS})
            spec['dev_cache'] = {'schema': 1, 'candidate_id': run.name,
                'qualification_sha256': spec['inputs']['dev-cache-qualification.json'],
                'bootstrap_sha256': spec['inputs']['dev-cache-bootstrap.json'],
                'receipt_sha256': spec['inputs']['dev-cache-receipt.json'],
                'source_sha256': {name: spec['source_snapshot'][name] for name in transport.CACHE_SOURCES}}
            write(run / 'full-spec.json', spec)
            state['shadow_full_spec_sha256'] = transport.sha(run / 'full-spec.json');write(run / 'state.json', state)
            owner = lease.read_bytes()
            with self.context(root), patch.object(composed, 'ROOT', root), patch.object(dev_cache, 'ROOT', root):
                transport.frozen(run)  # Real composed/cache validators accept the exact frozen artifacts.
                qualification['producer']['uid'] = 'replacement-producer'
                write(qualification_path, qualification)
                digest = transport.sha(qualification_path)
                spec['inputs']['dev-cache-qualification.json'] = spec['dev_cache']['qualification_sha256'] = digest
                write(run / 'full-spec.json', spec)
                state['shadow_full_spec_sha256'] = transport.sha(run / 'full-spec.json');write(run / 'state.json', state)
                with self.assertRaises(ValueError): transport.frozen(run)
            self.assertEqual(lease.read_bytes(), owner)
            self.assertFalse(run.with_name(run.name + '-remote-control').exists())


class Lifecycle(unittest.TestCase):
    def test_single_fault_capture_lifecycle_and_failures_preserve_attempt(self):
        failures = (None, 'wait', 'capture-pending', 'pending-proof', 'post-fault-health', 'finalize', 'capture-finalize', 'cleanup')
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, _, _, _, lease, _, _ = fixture(root)
                control = run.with_name(run.name + '-remote-control');control.mkdir()
                plan = {'run': str(run.relative_to(root)), 'control': str(control.relative_to(root)),
                    'recording': 'demos/transcripts/live/08-shadow-engine-composed/' + run.name,
                    'raw_recording': str(control.relative_to(root) / 'private-recording'),
                    'health_before': 'results/health.json', 'reservation': json.loads(lease.read_text()),
                    'reservation_directory': lease.parent.name}
                instance = controller.Controller(root, plan)
                calls, commands = [], {}

                def command(phase, arguments, timeout):
                    calls.append(phase);commands[phase] = arguments
                    if phase == failure: raise RuntimeError('failed ' + phase)
                    if phase == 'cleanup':
                        value = json.loads((run / 'demo.json').read_text());value['cleaned_at'] = 'now';write(run / 'demo.json', value)
                        lease.unlink();lease.parent.rmdir()

                def health(phase):
                    instance.health_attempts.add(phase)
                    command(phase, [], 300)
                    path = control / 'health' / phase / 'receipt.json';write(path, {'health': 'external'})
                    return path

                def pending(*_):
                    if failure == 'pending-proof': raise ValueError('pending seal changed')
                    return {'sealed': True}

                with patch.object(instance, 'command', side_effect=command), patch.object(instance, 'health', side_effect=health), \
                        patch.object(controller, 'ready_proof', return_value={'ready': True}), \
                        patch.object(controller, 'pending_proof', side_effect=pending), \
                        patch.object(controller, 'final_proof', return_value={'same_first_fault': True}), contextlib.redirect_stdout(io.StringIO()):
                    result = instance.execute()
                self.assertEqual(result, 0 if failure is None else 1)
                self.assertEqual(calls[-1], 'cleanup')
                self.assertLessEqual(calls.count('deploy'), 1)
                self.assertLessEqual(calls.count('capture-pending'), 1)
                if 'capture-pending' in commands:
                    self.assertIn('--defer-qualification', commands['capture-pending'])
                    index = commands['capture-pending'].index('--pre-fault-health')
                    self.assertNotIn(run, Path(commands['capture-pending'][index + 1]).parents)
                if failure in ('wait', 'capture-pending', 'pending-proof', 'post-fault-health'):
                    self.assertNotIn('finalize', calls)
                    self.assertNotIn('capture-finalize', calls)
                if failure is None:
                    self.assertEqual(calls, ['deploy', 'wait', 'pre-fault-health', 'capture-pending',
                        'post-fault-health', 'finalize', 'capture-finalize', 'cleanup'])
                    self.assertIn('--finalize-pending', commands['capture-finalize'])
                self.assertFalse((run / 'full-remote-exit.json').exists())
                self.assertTrue((control / 'full-remote-exit.json').exists())

    def test_phase_journals_and_health_are_outside_the_pending_full_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, baseline, _, lease, _, _ = fixture(root)
            control = run.with_name(run.name + '-remote-control');control.mkdir()
            plan = {'run': str(run.relative_to(root)), 'control': str(control.relative_to(root)),
                'recording': 'demos/transcripts/live/08-shadow-engine-composed/' + run.name,
                'raw_recording': str(control.relative_to(root) / 'private-recording'),
                'health_baseline': str(baseline.relative_to(root)), 'node': transport.NODE}
            instance = controller.Controller(root, plan);instance.folder.mkdir()
            before = tree(run)

            def command(phase, args, timeout):
                destination = Path(args[args.index('--run') + 1])
                self.assertNotIn(run, destination.parents)
                write(destination / 'snapshot-gpu-health-1.json', {'health': True})
                instance.heartbeat(phase)
                write(instance.folder / phase / 'command.json', {'args': args})

            with patch.object(instance, 'command', side_effect=command):
                path = instance.health('post-fault-health')
            self.assertEqual(tree(run), before)
            self.assertIn(control, path.parents)
            with self.assertRaisesRegex(ValueError, 'Never replay'): instance.health('post-fault-health')


if __name__ == '__main__': unittest.main()
