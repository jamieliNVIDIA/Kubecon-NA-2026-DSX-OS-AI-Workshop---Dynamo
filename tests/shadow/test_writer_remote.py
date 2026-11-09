"""Writer-only packaging, ownership and bounded failure lifecycle; no network."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import demos.shadow.writer_remote as transport
import demos.shadow.writer_remote_controller as controller


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


def fixture(root):
    run = root / 'results/fresh-writer';run.mkdir(parents=True)
    source = root / 'scripts/critical.py';source.parent.mkdir();source.write_text('# frozen\n')
    (root / transport.CONTROLLER).parent.mkdir(parents=True, exist_ok=True)
    (root / transport.CONTROLLER).write_text('# controller\n')
    namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(run).encode()).hexdigest()[:8] + '-demo'
    model = root / 'configs/super-vl-tp2-lock.json';write(model, {'model': 'model'})
    config = root / 'configs/dgd/workshop-shadow-descriptor-writer' / run.name / 'deployment.yaml'
    config.parent.mkdir(parents=True);config.write_text('kind: DynamoGraphDeployment\n')
    for name in transport.INPUTS:
        (run / name).write_text('{}\n')
    (run / 'model-lock.json').write_text('{}\n')
    snapshot = run / 'source-snapshot/critical.py';snapshot.parent.mkdir();snapshot.write_bytes(source.read_bytes())
    contract = run / 'runtime-contract-sources/module.py';contract.parent.mkdir();contract.write_text('# installed\n')
    spec = {'profile': transport.PROFILE, 'namespace': namespace, 'node': transport.NODE,
        'gpu_uuids': transport.UUIDS, 'reader_enabled': False, 'intentional_fault': False,
        'inputs': {name: transport.sha(run / name) for name in transport.INPUTS},
        'source_snapshot': {'critical.py': transport.sha(source)},
        'runtime_contract_hashes': {'module.py': transport.sha(contract)},
        'config_manifest': str(config), 'config_manifest_sha256': transport.sha(config),
        'model_lock_sha256': transport.sha(model)}
    write(run / 'descriptor-writer-spec.json', spec)
    state = {'namespace': namespace, 'owner': 'kubecon-dynamo-feature-tests',
        'shadow_writer_profile': transport.PROFILE,
        'shadow_descriptor_spec_sha256': transport.sha(run / 'descriptor-writer-spec.json'),
        'checks': {key: {'status': 'passed', 'updated_at': '2026-11-05T00:00:00+00:00'} for key in transport.GATES}}
    state['checks']['shadow-writer-cuda'].update(node=transport.NODE, arithmetic='passed', gpu_uuids=transport.UUIDS)
    write(run / 'state.json', state)
    write(root / transport.GUARD, {'cleaned_at': '2026-11-04T00:00:00+00:00'})
    health = root / 'results/fresh-health/health.json'
    write(health, {'node': transport.NODE, 'changed_conditions': [],
        'observed_at': '2026-11-05T00:01:00+00:00',
        'outputs': {key: {'file': key + '.log', 'exit_code': 0} for key in ('kernel', 'kernel-xids', 'nvidia-smi')}})
    for key in ('kernel', 'kernel-xids', 'nvidia-smi'):
        (health.parent / (key + '.log')).write_text('old evidence\n')
    baseline = root / 'results/baseline';write(baseline / 'nodes.json', {'items': []})
    image = root / 'results/existing-image';folder = image / 'controller-image';folder.mkdir(parents=True)
    (folder / 'Dockerfile').write_text('FROM ' + transport.common.IMAGE + '\n')
    write(folder / 'packages.json', {'curl': '7.88.1'})
    write(image / 'controller-image.json', {'schema': 1, 'status': 'built', 'base_image': transport.common.IMAGE,
        'image_id': transport.IMAGE_ID, 'base_image_id': 'sha256:' + 'a' * 64, 'tag': 'owned:existing',
        'curl_version': 'curl 7.88.1', 'dockerfile_sha256': transport.sha(folder / 'Dockerfile'),
        'packages_sha256': transport.sha(folder / 'packages.json')})
    (root / '.local').mkdir()
    return run, health, baseline, image, state, spec


class Packaging(unittest.TestCase):
    def context(self, root):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(transport, 'ROOT', root))
        stack.enter_context(patch.object(transport.common, 'ROOT', root))
        return stack

    def test_safe_bundle_reservation_and_no_secrets_or_old_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, state, _ = fixture(root)
            (run / 'command-secret.json').write_text('credential-value')
            (run / 'manifest-secret.json').write_text('credential-value')
            (root / '.local/kubeconfig').write_text('credential-value')
            with self.context(root):
                result = transport.build(run, health, baseline, image)
                _, prep, manifest, _ = transport.package(run)
                plan = json.loads((prep / 'plan.json').read_text())
                self.assertEqual(transport.validate_plan(plan, root), run)
                with self.assertRaisesRegex(ValueError, 'exists'):
                    transport.build(run, health, baseline, image)
            self.assertEqual(result['controller_name'], manifest['name'])
            owner = json.loads(Path(result['reservation']).read_text())
            self.assertEqual(owner['namespace'], state['namespace'])
            self.assertEqual(owner['gpu_uuids'], transport.UUIDS)
            names = set(manifest['files'])
            self.assertIn(str(transport.GUARD), names)
            self.assertFalse(any('.local' in name or 'command-secret' in name or 'manifest-secret' in name for name in names))
            with tarfile.open(prep / 'payload.tar.gz') as archive:
                self.assertFalse(any(b'credential-value' in archive.extractfile(member).read() for member in archive.getmembers()))

    def test_missing_gates_started_run_wrong_pair_and_stale_health_refuse_before_lease(self):
        for kind in ('gate', 'deployed', 'pair', 'health'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, health, baseline, image, state, spec = fixture(root)
                if kind == 'gate': state['checks']['shadow-writer-cuda']['status'] = 'failed'
                if kind == 'deployed': state['writer_apply_started_at'] = 'already'
                if kind == 'pair':
                    spec['gpu_uuids'] = ['GPU-foreign', 'GPU-other']
                    write(run / 'descriptor-writer-spec.json', spec)
                    state['shadow_descriptor_spec_sha256'] = transport.sha(run / 'descriptor-writer-spec.json')
                if kind == 'health':
                    value = json.loads(health.read_text());value['observed_at'] = '2025-01-01';write(health, value)
                write(run / 'state.json', state)
                with self.context(root), self.assertRaises(ValueError):
                    transport.build(run, health, baseline, image)
                self.assertEqual(list((root / '.local').iterdir()), [])

    def test_changed_source_or_reservation_blocks_launch_before_network(self):
        for kind in ('source', 'lease'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, health, baseline, image, _, _ = fixture(root)
                with self.context(root):
                    result = transport.build(run, health, baseline, image)
                    if kind == 'source': (root / 'scripts/critical.py').write_text('# changed\n')
                    else: write(Path(result['reservation']), {'agent': 'foreign'})
                    with patch.object(transport.subprocess, 'run', side_effect=AssertionError('No network')), \
                            self.assertRaises(ValueError):
                        transport.launch(run)
                self.assertTrue(Path(result['reservation']).exists())

    def test_symlink_contract_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, _, _ = fixture(root)
            contract = run / 'runtime-contract-sources/module.py';contract.unlink()
            contract.symlink_to(root / 'scripts/critical.py')
            with self.context(root), self.assertRaisesRegex(ValueError, 'symlink'):
                transport.build(run, health, baseline, image)

    def test_uncertain_launch_is_never_replayed_and_retains_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, health, baseline, image, _, _ = fixture(root)
            with self.context(root):
                package = transport.build(run, health, baseline, image)
                result = subprocess.CompletedProcess([], 255, b'', b'connection interrupted')
                with patch.object(transport.subprocess, 'run', return_value=result) as network:
                    with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                        transport.launch(run)
                    with self.assertRaises(FileExistsError):
                        transport.launch(run)
                self.assertEqual(network.call_count, 1)
            self.assertTrue(Path(package['reservation']).exists())
            self.assertEqual(json.loads((run / 'writer-remote-package/launch-result.json').read_text())['exit_code'], 255)

    def test_bootstrap_reuses_cpu_image_mounts_but_only_writer_scope(self):
        program = transport.bootstrap()
        compile(program, '<bootstrap>', 'exec')
        compile(transport.COLLECT, '<collector>', 'exec')
        self.assertIn("plan['reservation_directory']", program)
        self.assertIn(transport.OWNER, program)
        self.assertNotIn('import demos.snapshot.dgd_demo as workshop_snapshot_dgd_demo,', program)
        self.assertIn('import demos.shadow.descriptor_writer as workshop_shadow_descriptor_writer,', program)
        self.assertIn('NVIDIA_VISIBLE_DEVICES=void', program)
        self.assertIn('src=/home/ubuntu/.kube/config', program)
        self.assertNotIn("plan['recording']", transport.COLLECT)
        self.assertNotIn('capture.json', transport.COLLECT)


class Lifecycle(unittest.TestCase):
    def test_success_failure_and_cleanup_failure_never_run_reader_or_retry(self):
        for failure in (None, 'deploy', 'verify', 'post-health', 'finalize', 'cleanup'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, _, _, _, state, _ = fixture(root)
                plan = {'run': str(run.relative_to(root)), 'health_before': 'results/health.json', 'reservation': {'agent': transport.OWNER}}
                instance = controller.Controller(root, plan)
                calls = []

                def command(phase, arguments, timeout):
                    calls.append(phase)
                    self.assertGreater(timeout, 0)
                    if phase == failure: raise RuntimeError('failed ' + phase)
                    if phase == 'finalize': state['checks']['shadow-writer-qualification'] = {'status': 'passed'}
                    if phase == 'cleanup': state['checks']['shadow-writer-cleanup'] = {'status': 'passed'}
                    write(run / 'state.json', state)

                def health():
                    instance.health_attempted = True
                    calls.append('post-health')
                    if failure == 'post-health': raise RuntimeError('failed post-health')
                    return run / 'post-health.json'

                with patch.object(instance, 'command', side_effect=command), patch.object(instance, 'health', side_effect=health), \
                        patch.object(controller, 'serving_proof', return_value={'responses': 3}), contextlib.redirect_stdout(io.StringIO()):
                    code = instance.execute()
                expected = ['deploy'] + ([] if failure == 'deploy' else ['verify']) + ['post-health']
                if failure not in ('deploy', 'verify', 'post-health'): expected.append('finalize')
                self.assertEqual(calls, expected + ['cleanup'])
                self.assertEqual(code, 0 if failure is None else 1)
                value = json.loads((run / 'writer-remote-exit.json').read_text())
                self.assertFalse(value['reader_enabled'])
                self.assertFalse(value['intentional_fault'])
                self.assertFalse(value['local_reservation_released'])
                self.assertTrue(value['remote_mirror_retained'])


if __name__ == '__main__':
    unittest.main()
