"""Full-only controller dependency checks; no Docker, network, Helm or GPUs."""
import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.full_remote as transport
import demos.snapshot.remote as common
import tests.shadow.test_remote as prior


VALUES = {'resources': {'gpus': {'enabled': True}}, 'gpuResourcesEnabledOverride': True}


def probe_output(kubeconfig, binding=None, **changes):
    binding = binding or transport.HELM
    result = {'status': 'passed', 'helm': binding, 'helm_version': binding['version'],
              'command': [binding['container_path'], '--kubeconfig', kubeconfig, 'get', 'values',
                          'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json'],
              'driver_values': VALUES, 'driver_values_sha256': hashlib.sha256(json.dumps(VALUES).encode()).hexdigest()}
    result.update(changes)
    return json.dumps(result)


class HelmContractTests(unittest.TestCase):
    def test_binding_rejects_path_hash_version_type_and_schema_drift(self):
        self.assertEqual(transport.validate_helm_binding(dict(transport.HELM)), transport.HELM)
        for key, value in (('host_path', '/tmp/helm'), ('container_path', '/tmp/helm'), ('sha256', '0' * 64),
                           ('version', 'other'), ('schema', True), ('extra', 'unreviewed')):
            changed = dict(transport.HELM, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError): transport.validate_helm_binding(changed)
        for changed in (None, {}, [], dict(transport.HELM, schema=1.0)):
            with self.subTest(value=changed), self.assertRaises(ValueError): transport.validate_helm_binding(changed)

    def test_host_file_must_be_regular_resolved_executable_and_hash_identical(self):
        raw = b'synthetic executable bytes'
        binding = dict(transport.HELM, sha256=hashlib.sha256(raw).hexdigest())
        for case in ('valid', 'symlink', 'missing', 'resolved', 'permission', 'bytes'):
            file = SimpleNamespace(is_symlink=lambda: case == 'symlink', is_file=lambda: case != 'missing',
                                   resolve=lambda: '/tmp/other' if case == 'resolved' else binding['host_path'],
                                   read_bytes=lambda: b'changed' if case == 'bytes' else raw)
            with self.subTest(case=case), patch.object(transport, 'HELM', binding), \
                    patch.object(transport, 'Path', return_value=file), \
                    patch.object(transport.os, 'access', return_value=case != 'permission'):
                if case == 'valid': transport.verify_host_helm(binding)
                else:
                    with self.assertRaises(ValueError): transport.verify_host_helm(binding)

    def test_cpu_command_has_exact_read_only_binds_image_and_no_gpu_or_mutation_flags(self):
        command = transport.helm_probe_command(transport.HELM, transport.IMAGE_ID, '/logical/.local/kubeconfig')
        self.assertIn('--network=host', command)
        self.assertEqual(command[command.index('--user') + 1], '1000:1000')
        self.assertIn('NVIDIA_VISIBLE_DEVICES=void', command)
        mounts = [command[index + 1] for index, value in enumerate(command) if value == '--mount']
        self.assertEqual(mounts, [
            'type=bind,src=/usr/local/bin/helm,dst=/opt/homebrew/bin/helm,readonly',
            'type=bind,src=/home/ubuntu/.kube/config,dst=/logical/.local/kubeconfig,readonly'])
        self.assertFalse(any(value in command for value in ('--gpus', '--device', '--privileged', '--detach')))
        compile(command[-1], '<helm-inner>', 'exec')
        with self.assertRaises(ValueError): transport.helm_probe_command(transport.HELM, 'other-image', '/config')
        with self.assertRaises(ValueError): transport.helm_probe_command(transport.HELM, transport.IMAGE_ID, 'relative')

    def test_actual_inner_program_runs_real_get_values_and_fails_on_capability_or_api_errors(self):
        raw = b'synthetic executable bytes'
        binding = dict(transport.HELM, sha256=hashlib.sha256(raw).hexdigest())
        class MountedFile:
            def is_file(self): return True
            def read_bytes(self): return raw
            def __str__(self): return binding['container_path']
        with patch.object(transport, 'HELM', binding):
            program = transport.helm_probe_program(binding, '/logical/.local/kubeconfig')
        for case in ('valid', 'version-exit', 'version-drift', 'values-exit', 'invalid-json', 'disabled-gpus', 'disabled-override'):
            calls = []
            def run(command, **options):
                calls.append(command)
                if command[1] == 'version':
                    return subprocess.CompletedProcess(command, int(case == 'version-exit'),
                                                       'wrong' if case == 'version-drift' else binding['version'], 'version error')
                values = copy.deepcopy(VALUES)
                if case == 'disabled-gpus': values['resources']['gpus']['enabled'] = False
                if case == 'disabled-override': values['gpuResourcesEnabledOverride'] = False
                return subprocess.CompletedProcess(command, int(case == 'values-exit'),
                                                   'not json' if case == 'invalid-json' else json.dumps(values), 'RBAC/API failed')
            with self.subTest(case=case), patch('pathlib.Path', return_value=MountedFile()), \
                    patch.object(transport.os, 'access', return_value=True), \
                    patch.object(subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()) as output:
                if case == 'valid':
                    exec(compile(program, '<actual-inner>', 'exec'), {})
                    self.assertEqual(json.loads(output.getvalue())['driver_values'], VALUES)
                else:
                    with self.assertRaises((ValueError, RuntimeError)): exec(compile(program, '<actual-inner>', 'exec'), {})
            if case not in ('version-exit', 'version-drift'):
                self.assertEqual(calls[-1], [binding['container_path'], '--kubeconfig', '/logical/.local/kubeconfig',
                                            'get', 'values', 'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json'])

    def test_outer_probe_rejects_failed_or_invalid_or_substituted_result(self):
        config = '/logical/.local/kubeconfig'
        cases = [subprocess.CompletedProcess([], 3, '', 'CPU failure'),
                 subprocess.CompletedProcess([], 0, 'invalid JSON', ''),
                 subprocess.CompletedProcess([], 0, probe_output(config, helm_version='wrong'), ''),
                 subprocess.CompletedProcess([], 0, probe_output(config, command=['other']), ''),
                 subprocess.CompletedProcess([], 0, probe_output(config, driver_values={}), '')]
        for result in cases:
            with self.subTest(result=result), patch.object(transport, 'verify_host_helm'), \
                    patch.object(transport.subprocess, 'run', return_value=result):
                self.assertEqual(transport.run_helm_probe(transport.HELM, transport.IMAGE_ID, config)['status'], 'failed')

    def test_outer_probe_timeout_and_missing_docker_produce_failed_cpu_receipts(self):
        for error, expected in ((subprocess.TimeoutExpired(['docker'], 60), 124), (FileNotFoundError('docker'), 127)):
            with self.subTest(error=error), patch.object(transport, 'verify_host_helm'), \
                    patch.object(transport.subprocess, 'run', side_effect=error):
                receipt = transport.run_helm_probe(transport.HELM, transport.IMAGE_ID, '/logical/config')
                self.assertEqual(receipt['status'], 'failed')
                self.assertEqual(receipt['exit_code'], expected)
                self.assertFalse(receipt['cluster_mutation'])


class HelmOrchestrationTests(unittest.TestCase):
    @contextlib.contextmanager
    def packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run, health, baseline, image, lease, _, _ = prior.fixture(root)
            with prior.Packaging().context(root):
                before, owner = prior.tree(run), lease.read_bytes()
                transport.build(run, health, baseline, image)
                _, control, prep, manifest, _ = transport.package(run)
                plan = json.loads((prep / 'plan.json').read_text())
                yield SimpleNamespace(root=root, run=run, control=control, prep=prep, manifest=manifest,
                                      plan=plan, lease=lease, before=before, owner=owner)

    def test_package_binds_helm_without_changing_run_lease_or_common_sources(self):
        before = (common.BOOTSTRAP, common.PREFLIGHT, transport.writer_transport.bootstrap())
        with self.packaged() as fixture:
            self.assertEqual(fixture.plan['helm'], transport.HELM)
            self.assertEqual(fixture.manifest['helm'], transport.HELM)
            for key in ('host_path', 'container_path', 'sha256', 'version', 'schema'):
                changed = copy.deepcopy(fixture.plan)
                changed['helm'][key] = True
                with self.subTest(key=key), self.assertRaises(ValueError): transport.validate_plan(changed, fixture.root)
            self.assertEqual(prior.tree(fixture.run), fixture.before)
            self.assertEqual(fixture.lease.read_bytes(), fixture.owner)
        self.assertEqual(before, (common.BOOTSTRAP, common.PREFLIGHT, transport.writer_transport.bootstrap()))

    def test_full_preflight_generated_program_includes_same_probe_without_detach(self):
        with self.packaged() as fixture:
            calls = []
            def ssh(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, '{}', '')
            with patch.object(transport.subprocess, 'run', side_effect=ssh): transport.preflight(fixture.run)
            program = shlex.split(calls[0][-1])[0]
            compile(program, '<full-preflight>', 'exec')
            self.assertIn('helm_receipt=run_helm_probe(HELM,IMAGE_ID,', program)
            self.assertIn(str(fixture.root) + '/.local/kubeconfig', program)
            self.assertNotIn('--detach', program)

    def bootstrap_tail(self):
        """Execute actual emitted pre-detach code, replacing only external effects."""
        program = ast.parse(transport.bootstrap())
        block = next(node for node in program.body if isinstance(node, ast.With))
        start = next(index for index, node in enumerate(block.body)
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'command' for target in node.targets))
        module = ast.Module(body=block.body[start:], type_ignores=[])
        return compile(ast.fix_missing_locations(module), '<actual-bootstrap-before-detach>', 'exec')

    def test_bootstrap_probe_precedes_detach_and_preserves_failed_cpu_receipt(self):
        for case in ('valid', 'cpu-exit', 'cpu-json', 'cpu-timeout', 'host-drift'):
            with self.subTest(case=case), self.packaged() as fixture:
                namespace = {}
                exec(transport.helm_support(), namespace)
                calls = []
                config = str(fixture.root) + '/.local/kubeconfig'
                def run(command, **options):
                    calls.append(command)
                    if '--network=none' in command:
                        return subprocess.CompletedProcess(command, 0, 'Full source imports', '')
                    if '--detach' in command:
                        self.assertEqual(json.loads((fixture.control / 'helm-preflight.json').read_text())['status'], 'passed')
                        return subprocess.CompletedProcess(command, 0, 'fake-controller-id', '')
                    self.assertIn('--network=host', command)
                    if case == 'cpu-timeout': raise subprocess.TimeoutExpired(command, 60)
                    if case == 'cpu-exit': return subprocess.CompletedProcess(command, 1, '', 'RBAC denied')
                    if case == 'cpu-json': return subprocess.CompletedProcess(command, 0, 'invalid JSON', '')
                    return subprocess.CompletedProcess(command, 0, probe_output(config), '')
                checks = []
                def verify(binding):
                    checks.append(binding)
                    if case == 'host-drift' and len(checks) == 2: raise ValueError('Host Helm changed')
                namespace.update(subprocess=SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired,
                    check_output=lambda *args, **kwargs: json.dumps([{'State': {'Running': True}, 'Image': transport.IMAGE_ID}])),
                    verify_host_helm=verify, w=fixture.root, logical=str(fixture.root), plan=fixture.plan,
                    manifest=fixture.manifest, verified={})
                with contextlib.redirect_stdout(io.StringIO()):
                    if case == 'valid': exec(self.bootstrap_tail(), namespace)
                    else:
                        with self.assertRaises((ValueError, RuntimeError)): exec(self.bootstrap_tail(), namespace)
                detached = [command for command in calls if '--detach' in command]
                self.assertEqual(len(detached), int(case == 'valid'))
                receipt = json.loads((fixture.control / 'helm-preflight.json').read_text())
                self.assertEqual(receipt['status'], 'failed' if case in ('cpu-exit', 'cpu-json', 'cpu-timeout') else 'passed')
                if detached:
                    self.assertIn('type=bind,src=/usr/local/bin/helm,dst=/opt/homebrew/bin/helm,readonly', detached[0])
                    self.assertIn('type=bind,src=/home/ubuntu/.kube/config,dst=' + config + ',readonly', detached[0])
                self.assertEqual(prior.tree(fixture.run), fixture.before)
                self.assertEqual(fixture.lease.read_bytes(), fixture.owner)

    def test_missing_plan_or_manifest_binding_blocks_launch_before_intent_and_ssh(self):
        with self.packaged() as fixture:
            for changed in ('plan', 'manifest'):
                plan, manifest = copy.deepcopy(fixture.plan), copy.deepcopy(fixture.manifest)
                (plan if changed == 'plan' else manifest).pop('helm')
                with patch.object(transport, 'package', return_value=(fixture.run, fixture.control, fixture.prep, manifest, 'digest')), \
                        patch.object(transport, 'read', return_value=plan), patch.object(transport.subprocess, 'run') as ssh:
                    with self.assertRaises(ValueError): transport.launch(fixture.run)
                    ssh.assert_not_called()
                self.assertFalse((fixture.prep / 'launch-intent.json').exists())


if __name__ == '__main__': unittest.main()
