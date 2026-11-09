"""Independent Full-only Helm transport review; no Docker/SSH/cluster calls."""
from tests.support import ROOT
import ast
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.full_remote as full

A4 = ROOT / 'results/shadow-full-a4-remote-collected-20261105-a1'
OLD = A4 / 'recording-private/private-recording/sources/workshop_shadow_full_remote.py'


class HelmTransportReviewTests(unittest.TestCase):
    def test_binding_rejects_missing_extra_typed_or_changed_paths_hash_and_version(self):
        full.validate_helm_binding(copy.deepcopy(full.HELM))
        for value in (None, [], dict(full.HELM, schema=True), dict(full.HELM, host_path='/tmp/helm'),
                dict(full.HELM, container_path='/usr/bin/helm'), dict(full.HELM, sha256='0' * 64),
                dict(full.HELM, version='other'), dict(full.HELM, unexpected=True)):
            with self.subTest(value=value), self.assertRaises(ValueError): full.validate_helm_binding(value)

    def test_real_temporary_host_file_must_be_regular_exact_readable_and_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'helm'; path.write_bytes(b'qualified Linux fixture'); path.chmod(0o700)
            binding = dict(full.HELM, host_path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.object(full, 'HELM', binding):
                full.verify_host_helm(binding)
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError): full.verify_host_helm(binding)
                path.write_bytes(b'qualified Linux fixture'); path.chmod(0o600)
                with self.assertRaises(ValueError): full.verify_host_helm(binding)
            link = path.with_name('link'); link.symlink_to(path)
            binding = dict(binding, host_path=str(link))
            with patch.object(full, 'HELM', binding), self.assertRaises(ValueError): full.verify_host_helm(binding)

    def test_probe_command_is_same_image_cpu_only_with_both_readonly_mounts(self):
        command = full.helm_probe_command(full.HELM, full.IMAGE_ID, '/workspace/.local/kubeconfig')
        self.assertIn('--pull=never', command)
        self.assertIn('NVIDIA_VISIBLE_DEVICES=void', command)
        self.assertNotIn('--gpus', command)
        self.assertIn('type=bind,src=' + full.HELM['host_path'] + ',dst=' + full.HELM['container_path'] + ',readonly', command)
        self.assertIn('type=bind,src=/home/ubuntu/.kube/config,dst=/workspace/.local/kubeconfig,readonly', command)
        self.assertEqual(command[command.index('--entrypoint') + 2], full.IMAGE_ID)
        with self.assertRaises(ValueError): full.helm_probe_command(full.HELM, 'foreign-image', '/workspace/config')
        with self.assertRaises(ValueError): full.helm_probe_program(full.HELM, 'relative/config')

    def execute_probe_body(self, case):
        data = b'qualified bytes'
        binding = dict(full.HELM, sha256=hashlib.sha256(data).hexdigest())
        with patch.object(full, 'HELM', binding): program = full.helm_probe_program(binding, '/workspace/.local/kubeconfig')
        tree = ast.parse(program)
        # Execute every generated metadata statement, replacing only stdlib I/O
        # imports with explicit doubles; this never executes a host binary.
        tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
        calls = []
        driver = {'resources': {'gpus': {'enabled': True}}, 'gpuResourcesEnabledOverride': True}
        if case == 'boolean-coercion': driver['resources']['gpus']['enabled'] = 1
        if case == 'disabled': driver['gpuResourcesEnabledOverride'] = False
        class BoundPath:
            def is_file(self): return case != 'missing'
            def read_bytes(self): return b'changed' if case == 'hash' else data
            def __str__(self): return binding['container_path']
        def subprocess_run(command, **options):
            calls.append((command, options))
            if command[1:] == ['version', '--short']:
                return SimpleNamespace(returncode=0, stderr='', stdout=('wrong' if case == 'version' else binding['version']) + '\n')
            self.assertEqual(command, [binding['container_path'], '--kubeconfig', '/workspace/.local/kubeconfig',
                'get', 'values', 'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json'])
            return SimpleNamespace(returncode=1 if case == 'query-failure' else 0, stderr='query failed',
                stdout='not JSON' if case == 'json' else json.dumps(driver))
        namespace = {'hashlib': hashlib, 'json': json, 'Path': lambda _: BoundPath(),
            'os': SimpleNamespace(R_OK=4, X_OK=1, access=lambda *_: case != 'permissions'),
            'subprocess': SimpleNamespace(run=subprocess_run)}
        with redirect_stdout(io.StringIO()) as output:
            exec(compile(tree, 'reviewed-generated-helm-probe-body', 'exec'), namespace)
        return json.loads(output.getvalue()), calls

    def test_generated_probe_really_checks_version_query_values_and_bytes(self):
        report, calls = self.execute_probe_body('success')
        self.assertEqual(report['status'], 'passed')
        self.assertEqual([row[1]['timeout'] for row in calls], [10, 35])
        for case in ('missing', 'permissions', 'hash', 'version', 'query-failure', 'json', 'disabled', 'boolean-coercion'):
            with self.subTest(case=case), self.assertRaises((ValueError, RuntimeError)):
                self.execute_probe_body(case)

    def test_outer_receipt_rejects_failed_or_forged_native_result_before_controller(self):
        values = {'resources': {'gpus': {'enabled': True}}, 'gpuResourcesEnabledOverride': True}
        result = {'status': 'passed', 'helm': dict(full.HELM), 'helm_version': full.HELM['version'],
            'command': [full.HELM['container_path'], '--kubeconfig', '/workspace/config', 'get', 'values',
                        'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json'],
            'driver_values': values, 'driver_values_sha256': hashlib.sha256(json.dumps(values).encode()).hexdigest()}
        for case in ('success', 'exit', 'json', 'binding', 'command', 'version', 'enabled', 'override'):
            native = copy.deepcopy(result)
            if case == 'binding': native['helm']['host_path'] = '/other'
            elif case == 'command': native['command'][3] = 'delete'
            elif case == 'version': native['helm_version'] = 'other'
            elif case == 'enabled': native['driver_values']['resources']['gpus']['enabled'] = 1
            elif case == 'override': native['driver_values']['gpuResourcesEnabledOverride'] = False
            process = SimpleNamespace(returncode=1 if case == 'exit' else 0, stderr='failure',
                stdout='not JSON' if case == 'json' else json.dumps(native))
            with self.subTest(case=case), patch.object(full, 'verify_host_helm') as host, \
                    patch.object(full.subprocess, 'run', return_value=process) as run:
                receipt = full.run_helm_probe(full.HELM, full.IMAGE_ID, '/workspace/config')
                self.assertEqual(receipt['status'], 'passed' if case == 'success' else 'failed')
                self.assertEqual(receipt['gpu_requests'], 0)
                self.assertIs(receipt['cluster_mutation'], False)
                host.assert_called_once_with(full.HELM)
                self.assertEqual(run.call_args.kwargs['timeout'], 60)

    def test_bootstrap_has_probe_receipt_and_fresh_hash_check_before_controller_detach(self):
        source = full.bootstrap(); compile(source, 'full-helm-bootstrap', 'exec')
        probe = source.index(" helm_receipt=run_helm_probe(plan['helm'],manifest['image'],logical+'/.local/kubeconfig')")
        receipt = source.index("/'helm-preflight.json').open('x')", probe)
        gate = source.index("if helm_receipt['status']!='passed'", receipt)
        rehash = source.index("verify_host_helm(plan['helm'])", gate)
        imports = source.index('result=subprocess.run(command,capture_output=True,text=True,timeout=45)', rehash)
        self.assertLess(probe, receipt); self.assertLess(receipt, gate); self.assertLess(gate, rehash); self.assertLess(rehash, imports)
        self.assertIn("'--mount','type=bind,src='+plan['helm']['host_path']+',dst='+plan['helm']['container_path']+',readonly'", source)
        self.assertIn("validate_helm_binding(manifest.get('helm'))", source)

    @unittest.skipUnless(OLD.is_file(), 'Retained a4 transport source is local evidence')
    def test_archived_a4_sources_and_closed_package_remain_self_consistent(self):
        # Archived qualification is bound to its own captured sources. Moving
        # current code must not rewrite that evidence to claim a new validation.
        capture = json.loads((A4 / 'recording/capture.json').read_text())
        private = A4 / 'recording-private/private-recording/sources'
        for name, expected in capture['source_sha256'].items():
            self.assertEqual(hashlib.sha256((private / name).read_bytes()).hexdigest(), expected, name)
        spec = json.loads((A4 / 'run/full-spec.json').read_text())
        for name, expected in spec['source_snapshot'].items():
            archived = A4 / 'run/source-snapshot' / name
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), expected, name)
        run = ROOT / 'results/overnight-shadow-super-vl-20261105-full-a4'
        _, _, _, manifest, _ = full.package(run)
        self.assertNotIn('helm', manifest, 'Old failed package must remain unmodified and readable')



if __name__ == '__main__': unittest.main()
