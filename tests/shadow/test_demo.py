"""Guard the Shadow demo's allocation, experimental patch and fault boundaries."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import yaml
import demos.shadow.demo as demo
from demos.shadow.runtime import singleton_meta_scale


class ShadowGuards(unittest.TestCase):
    def test_operator_claim_is_scoped_to_exact_pair(self):
        lock = demo.ui.read_json(demo.ui.MODEL_LOCK)
        graph, dc = demo.render('dynamo-ft-test-shadow', lock)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        self.assertNotIn('resourceClaims', worker['podTemplate']['spec'])
        self.assertNotIn('claims', worker['podTemplate']['spec']['containers'][0]['resources'])
        self.assertEqual(worker['experimental']['gpuMemoryService']['deviceClassName'], dc['metadata']['name'])
        expression = dc['spec']['selectors'][0]['cel']['expression']
        for uuid in demo.UUIDS:
            self.assertIn(uuid, expression)
        self.assertEqual(worker['podTemplate']['spec']['nodeSelector']['kubernetes.io/hostname'], demo.NODE)
        args = worker['podTemplate']['spec']['containers'][0]['args']
        self.assertEqual(args[args.index('--load-format') + 1], 'gms')
        self.assertIn('--language-model-only', args)
        self.assertIn('--enforce-eager', args)

    def test_wrong_physical_pair_refuses_fault_qualification(self):
        value = {'node': demo.NODE, 'engines': {n: {'gpu_uuids': list(demo.UUIDS)}
                                               for n in ('engine-0', 'engine-1')}}
        demo.validate_pair(value, demo.UUIDS)
        value['engines']['engine-1']['gpu_uuids'][1] = 'GPU-foreign'
        with self.assertRaisesRegex(ValueError, 'assigned GPU pair'):
            demo.validate_pair(value, demo.UUIDS)

    def test_patch_does_not_relax_nonmeta_or_vector_shape_checks(self):
        # Exercise the actual transformed conditional, without importing CUDA.
        source = '''def compatible(param, tensor, attr):
    if True:
        if True:
            if True:
                if param.shape != tensor.shape or param.dtype != tensor.dtype:
                    raise RuntimeError('mismatch')
    return True
'''
        namespace = {}
        exec(singleton_meta_scale(source), namespace)
        check = namespace['compatible']
        tensor = SimpleNamespace(shape=(), dtype='f32', numel=lambda: 1)
        param = SimpleNamespace(shape=(1,), dtype='f32', is_meta=True, numel=lambda: 1)
        self.assertTrue(check(param, tensor, 'input_scale'))
        for changes, name in [({'is_meta': False}, 'input_scale'), ({'dtype': 'f16'}, 'input_scale'),
                              ({'numel': lambda: 2}, 'input_scale'), ({}, 'weight')]:
            changed = copy.copy(param)
            changed.__dict__.update(changes)
            with self.assertRaises(RuntimeError):
                check(changed, tensor, name)

    def test_patch_refuses_unrecognized_source(self):
        with self.assertRaises(ValueError):
            singleton_meta_scale('def changed_api(): pass\n')

    def test_no_live_proof_means_no_presented_success(self):
        instance = object.__new__(demo.ShadowDemo)
        with tempfile.TemporaryDirectory() as directory:
            instance.path = Path(directory)
            with self.assertRaisesRegex(ValueError, 'No recovery proof'):
                instance.summary()

    def test_lease_cannot_be_reused_by_another_run(self):
        instance = object.__new__(demo.ShadowDemo)
        instance.data = {}
        with tempfile.TemporaryDirectory() as directory:
            instance.path = Path(directory) / 'mine'
            instance.lease = Path(directory) / 'lease'
            instance.lease.mkdir()
            demo.ui.write_json(instance.lease / 'owner.json', {
                'owner': demo.OWNER, 'run': str(Path(directory) / 'foreign'), 'gpu_uuids': demo.UUIDS})
            with self.assertRaisesRegex(ValueError, 'Foreign scoped'):
                instance.acquire()

    def test_wrong_pair_never_reaches_fault_verifier(self):
        instance = object.__new__(demo.ShadowDemo)
        instance.data = {}
        instance.args = SimpleNamespace(rehearsal=False, timeout=30)
        instance.path = Path('/unused-shadow-test')
        instance.run = SimpleNamespace()
        instance.show_command = lambda _: None
        instance.acquire = lambda: None
        instance.check_inputs = lambda: None
        observation = {'node': demo.NODE, 'engines': {n: {'gpu_uuids': ['GPU-foreign', demo.UUIDS[0]]}
                                                    for n in ('engine-0', 'engine-1')}}
        with patch.object(demo.control, 'snapshot', return_value=observation), \
                patch.object(demo.control, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'assigned GPU pair'):
                instance.failover()
            verify.assert_not_called()

    def test_coding_probe_is_restored_after_verifier_failure(self):
        instance = object.__new__(demo.ShadowDemo)
        instance.data = {}
        instance.args = SimpleNamespace(rehearsal=False, timeout=30)
        instance.path = Path('/unused-shadow-test')
        instance.run = SimpleNamespace()
        instance.show_command = lambda _: None
        instance.acquire = lambda: None
        instance.check_inputs = lambda: None
        instance.logs = lambda: None
        observation = {'node': demo.NODE, 'engines': {n: {'gpu_uuids': list(demo.UUIDS)}
                                                    for n in ('engine-0', 'engine-1')}}
        original = demo.control.completion
        with patch.object(demo.control, 'snapshot', return_value=observation), \
                patch.object(demo.control, 'preflight', return_value={'blockers': []}), \
                patch.object(demo.control, 'verify', side_effect=RuntimeError('simulated verifier failure')):
            with self.assertRaisesRegex(RuntimeError, 'simulated verifier failure'):
                instance.failover()
        self.assertIs(demo.control.completion, original)

    def test_teaching_excerpt_tracks_effective_shared_weight_and_frontend_flags(self):
        graph, _ = demo.render('dynamo-ft-test-shadow', demo.ui.read_json(demo.ui.MODEL_LOCK))
        original = copy.deepcopy(graph)
        excerpt = demo.settings_excerpt(graph)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(excerpt['experimental'], worker['experimental'])
        self.assertEqual(excerpt['engine_args'], [
            '--tensor-parallel-size', '2', '--load-format', 'gms', '--enable-sleep-mode'])
        self.assertEqual(excerpt['frontend_env'], {'DYN_MIGRATION_LIMIT': '0'})
        self.assertEqual(graph, original)
        worker['podTemplate']['spec']['containers'][0]['args'].remove('--enable-sleep-mode')
        self.assertNotIn('--enable-sleep-mode', demo.settings_excerpt(graph)['engine_args'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'excerpt.yaml'
            demo.support.write_yaml(path, excerpt)
            self.assertLessEqual(len(path.read_text().splitlines()), 30)
            self.assertNotIn('runtime-sources', path.read_text())

    def test_unprepared_or_unprimed_live_run_stops_before_the_first_screen(self):
        for prepared, expected in ((False, 'Prepare this run offstage'),
                                   (True, 'Prime and verify the active/standby pair offstage')):
            with self.subTest(prepared=prepared), tempfile.TemporaryDirectory() as directory:
                instance = demo.ShadowDemo(SimpleNamespace(
                    run=Path(directory), rehearsal=False, action='run', preview=False,
                    auto=True, timeout=30, port=18008))
                instance.data['prepared'] = prepared
                instance.save()
                output = io.StringIO()
                with patch.object(instance, 'prepare') as prepare, \
                        patch.object(instance, 'prime') as prime, \
                        patch.object(instance, 'run_steps') as steps, \
                        patch.object(instance.run, 'apply') as apply, \
                        contextlib.redirect_stdout(output):
                    with self.assertRaisesRegex(RuntimeError, expected) as error:
                        instance.guided()
                for operation in (prepare, prime, steps, apply):
                    operation.assert_not_called()
                self.assertNotIn('Dynamo workshop', output.getvalue())
                self.assertIn('-m demos shadow', str(error.exception))

    def test_edited_frozen_configuration_cannot_reach_the_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.ShadowDemo(SimpleNamespace(
                run=Path(directory), rehearsal=False, action='verify', preview=False,
                auto=True, timeout=30, port=18008))
            (instance.path / 'shadow-settings.yaml').write_text('edited frozen settings\n')
            with patch.object(instance, 'show_command') as command, \
                    patch.object(instance, 'acquire') as acquire, \
                    patch.object(demo.control, 'verify') as verify:
                with self.assertRaisesRegex(ValueError, 'Frozen Shadow input changed'):
                    instance.failover()
            command.assert_not_called()
            acquire.assert_not_called()
            verify.assert_not_called()

    def test_rehearsal_has_no_preparation_stage_or_live_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shadow-rehearsal'
            result = subprocess.run([
                sys.executable, '-B', '-m', 'demos', 'shadow', '--rehearsal',
                '--plain', '--auto', '--run', str(path)], cwd=demo.ui.ROOT,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NO CLUSTER CALLS', result.stdout)
            self.assertNotIn('Exact checkpoint', result.stdout)
            self.assertNotIn('Prepared active + standby', result.stdout)
            self.assertNotIn('Preparation\n', result.stdout)
            for title, _ in demo.STEPS:
                self.assertIn(title, result.stdout)
            proof = json.loads((path / 'recovery-proof.json').read_text())
            self.assertTrue(proof['rehearsal'])
            self.assertEqual(proof['status'], 'simulated')
            receipts = [json.loads(p.read_text()) for p in path.glob('command-*.json')]
            self.assertTrue(all(item['args'][0] == 'cat' for item in receipts))


class QwenVariant(unittest.TestCase):
    """New runs show promotion on the qualified Qwen TP1 control model; Super VL is an explicit choice."""

    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(demo.MODEL_ENV, None)

    def new(self, run, action='run', rehearsal=True):
        return demo.ShadowDemo(SimpleNamespace(run=Path(run), rehearsal=rehearsal, action=action, preview=False,
                                               auto=True, timeout=30, port=18008))

    def test_worker_container_matches_the_qualified_control(self):
        lock = demo.ui.read_json(demo.QWEN_LOCK)
        graph, dc = demo.render_qwen('dynamo-ft-test-shadow', lock, overlay=demo.ui.read_json(demo.GMS_COMPAT)['patch'])
        control = yaml.safe_load((demo.ui.ROOT / lock['control_manifest']).read_text())
        pick = lambda g, kind: next(c for c in g['spec']['components'] if c['type'] == kind)
        ours, theirs = pick(graph, 'worker')['podTemplate'], pick(control, 'worker')['podTemplate']
        main, expected = ours['spec']['containers'][0], theirs['spec']['containers'][0]
        for key in ('image', 'command', 'args', 'env', 'resources', 'workingDir'):
            self.assertEqual(main[key], expected[key], key)
        overlay = lambda container: [m for m in container['volumeMounts'] if m['name'] == 'shadow-gms-compat']
        self.assertEqual(overlay(main), overlay(expected))
        self.assertEqual(ours['metadata']['annotations'], theirs['metadata']['annotations'])
        self.assertNotIn('shadow-runtime', [v['name'] for v in ours['spec']['volumes']])
        frontend_env = pick(graph, 'frontend')['podTemplate']['spec']['containers'][0]['env']
        self.assertEqual(frontend_env, pick(control, 'frontend')['podTemplate']['spec']['containers'][0]['env'] +
                         [{'name': 'DYN_MIGRATION_LIMIT', 'value': '0'}])
        self.assertEqual(pick(graph, 'worker')['experimental'],
                         {'gpuMemoryService': {'deviceClassName': dc['metadata']['name']}, 'failover': {}})
        self.assertEqual(ours['spec']['nodeSelector'], {'kubernetes.io/hostname': demo.QWEN_NODE})
        self.assertTrue(dc['spec']['selectors'][0]['cel']['expression'].endswith(' in ' + json.dumps(demo.QWEN_UUIDS)))

    def test_new_runs_default_to_qwen_and_freeze_its_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = self.new(directory)
            self.assertEqual(instance.data['shadow_profile'], demo.QWEN_PROFILE)
            self.assertEqual(instance.placement, (demo.QWEN_NODE, demo.QWEN_UUIDS))
            self.assertEqual(demo.ui.read_json(instance.path / 'model-lock.json'), demo.ui.read_json(demo.QWEN_LOCK))
            self.assertEqual(demo.ui.read_json(instance.path / 'request.json')['model'], 'Qwen/Qwen3-0.6B')
            settings = yaml.safe_load((instance.path / 'shadow-settings.yaml').read_text())
            self.assertEqual(settings['model'], 'Qwen/Qwen3-0.6B')
            self.assertEqual(settings['engine_args'], ['--tensor-parallel-size', '1', '--load-format', 'gms',
                                                       '--enable-sleep-mode'])
            self.assertLessEqual(len((instance.path / 'shadow-settings.yaml').read_text().splitlines()), 30)
            (instance.path / 'model-lock.json').write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'Frozen Shadow input changed: model-lock.json'):
                instance.check_inputs()

    def test_super_vl_is_an_explicit_choice_kept_by_its_run(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ[demo.MODEL_ENV] = 'super-vl'
            instance = self.new(directory)
            self.assertEqual(instance.data['shadow_profile'], demo.PROFILE)
            self.assertEqual(instance.placement, (demo.NODE, demo.UUIDS))
            self.assertFalse((instance.path / 'model-lock.json').exists())
            os.environ[demo.MODEL_ENV] = 'qwen3-0.6b'
            with self.assertRaisesRegex(ValueError, 'uses super-vl'):
                self.new(directory)
            del os.environ[demo.MODEL_ENV]
            self.assertEqual(self.new(directory).data['shadow_profile'], demo.PROFILE)

    def test_unknown_model_choice_creates_no_run(self):
        with tempfile.TemporaryDirectory() as directory:
            os.environ[demo.MODEL_ENV] = 'llama'
            with self.assertRaisesRegex(ValueError, 'must be qwen3-0.6b or super-vl'):
                self.new(Path(directory) / 'run')
            self.assertFalse((Path(directory) / 'run').exists())

    def test_changed_qwen_lock_needs_a_fresh_run_but_allows_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            self.new(run)
            changed = Path(directory) / 'lock.json'
            changed.write_text(json.dumps(dict(demo.ui.read_json(demo.QWEN_LOCK), revision='other')))
            with patch.object(demo, 'QWEN_LOCK', changed):
                with self.assertRaisesRegex(ValueError, 'Qwen Shadow lock changed'):
                    self.new(run)
                self.new(run, action='cleanup')

    def test_placement_reaches_the_lease_and_the_allocation_check(self):
        instance = object.__new__(demo.ShadowDemo)
        instance.data = {'shadow_profile': demo.QWEN_PROFILE}
        with tempfile.TemporaryDirectory() as directory:
            instance.path = Path(directory) / 'mine'
            instance.lease = Path(directory) / 'lease'
            instance.acquire()
            owner = demo.ui.read_json(instance.lease / 'owner.json')
            self.assertEqual((owner['node'], owner['gpu_uuids']), (demo.QWEN_NODE, demo.QWEN_UUIDS))
        # PyTorch reports UUIDs without the GPU- prefix.
        observation = {'node': demo.QWEN_NODE, 'engines': {n: {'gpu_uuids': [demo.QWEN_UUIDS[0][4:]]}
                                                         for n in ('engine-0', 'engine-1')}}
        demo.validate_pair(observation, demo.QWEN_UUIDS, demo.QWEN_NODE)
        with self.assertRaisesRegex(ValueError, 'Unexpected Shadow node'):
            demo.validate_pair(observation, demo.QWEN_UUIDS)
        observation['engines']['engine-1']['gpu_uuids'] = [demo.UUIDS[0]]
        with self.assertRaisesRegex(ValueError, r'assigned GPU\.'):
            demo.validate_pair(observation, demo.QWEN_UUIDS, demo.QWEN_NODE)

    def test_failover_verifies_on_the_qwen_node_with_the_selected_request(self):
        from demos.snapshot.dgd import coding_request
        observation = {'node': demo.QWEN_NODE, 'engines': {n: {'gpu_uuids': list(demo.QWEN_UUIDS)}
                                                         for n in ('engine-0', 'engine-1')}}
        original = demo.control.completion
        for choice, expected in (('coding', coding_request), ('ready', original)):
            with self.subTest(choice=choice):
                seen = {}
                instance = object.__new__(demo.ShadowDemo)
                instance.data = {'shadow_profile': demo.QWEN_PROFILE}
                instance.args = SimpleNamespace(rehearsal=False, timeout=30)
                instance.path = Path('/unused-shadow-test')
                instance.run = SimpleNamespace(state={'checks': {'shadow-failover': {'status': 'passed'}}})
                instance.show_command = instance.acquire = instance.check_inputs = instance.logs = lambda *_: None
                with patch.object(demo, 'QWEN_RECOVERY_REQUEST', choice), \
                        patch.object(demo.control, 'snapshot', return_value=observation), \
                        patch.object(demo.control, 'preflight', return_value={'blockers': []}), \
                        patch.object(demo.control, 'verify', side_effect=lambda run, timeout, nodes: seen.update(
                            nodes=nodes, request=demo.control.completion)), \
                        patch.object(demo.ui, 'write_json'), contextlib.redirect_stdout(io.StringIO()):
                    instance.failover()
                self.assertEqual(seen, {'nodes': [demo.QWEN_NODE], 'request': expected})
                self.assertIs(demo.control.completion, original)

    def test_local_helm_rewrites_only_the_homebrew_path(self):
        calls = []
        run = SimpleNamespace(command=lambda args, *rest, **options: calls.append(list(args)))
        original = run.command
        with patch.object(demo.os.path, 'exists', return_value=False), \
                patch.object(demo.shutil, 'which', return_value='/usr/local/bin/helm'):
            with demo.local_helm(run):
                run.command([demo.HOMEBREW_HELM, 'get', 'values'])
                run.command(['kubectl', 'get', 'pods'])
        self.assertEqual(calls, [['/usr/local/bin/helm', 'get', 'values'], ['kubectl', 'get', 'pods']])
        self.assertIs(run.command, original)
        with patch.object(demo.os.path, 'exists', return_value=True), demo.local_helm(run):
            self.assertIs(run.command, original)

    def prepared(self, directory, *, installed=None, eligible=None):
        """Run the Qwen preparation against recorded cluster answers; return the run and the mocks."""
        instance = self.new(directory, rehearsal=False)
        compat = demo.ui.read_json(demo.GMS_COMPAT)['patch']

        def runtime(run):
            run.state['checks']['shadow-runtime'] = {'status': 'present', 'files': {
                'gpu_memory_service/integrations/vllm/patches.py': {'sha256': installed or compat['original_sha256']}}}
        infra = {'blockers': [], 'eligible_nodes': eligible or [demo.QWEN_NODE]}
        report = {'model': 'Qwen/Qwen3-0.6B', 'weight_files': 1, 'weight_bytes': 1503300328}
        mocks = SimpleNamespace(instance=instance, error=None)
        with patch('storage_tests.prepare') as mocks.storage, patch('common_runtime_tests.pull_secret'), \
                patch('snapshot_tp2_workflow.cpu_probe', return_value=report) as mocks.probe, \
                patch.object(demo.control, 'preflight', return_value=infra), \
                patch.object(demo.control, 'runtime', side_effect=runtime) as mocks.runtime, \
                patch.object(instance.run, 'apply') as mocks.apply, patch.object(instance, 'admit') as mocks.admit, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                instance.prepare_qwen()
            except (RuntimeError, ValueError) as error:
                mocks.error = error
        return mocks

    def test_prepare_mirrors_the_control_and_freezes_the_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            mocks = self.prepared(directory)
            self.assertIsNone(mocks.error)
            mocks.storage.assert_called_once_with(mocks.instance.run)
            compat = demo.ui.read_json(demo.GMS_COMPAT)['patch']
            source = (demo.ui.ROOT / compat['path']).read_text()
            mocks.apply.assert_called_once_with([{'apiVersion': 'v1', 'kind': 'ConfigMap',
                'metadata': {'name': compat['configmap']}, 'immutable': True, 'data': {'patches.py': source}}])
            environment = {e['name']: e['value'] for e in mocks.probe.call_args.args[3]}
            self.assertEqual(environment['HF_HOME'], '/model-cache/feature-tests/20261014-shadow-qwen-control/hf')
            instance = mocks.instance
            self.assertIn('patched-patches.py', instance.data['inputs'])
            self.assertEqual(list(instance.data['runtime_overlay']['patched_sources']), ['patched-patches.py'])
            mocks.admit.assert_called_once_with(demo.ui.read_json(instance.path / 'device-class.json'))
            instance.check_inputs()

    def test_prepare_refuses_an_overlay_for_different_installed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            mocks = self.prepared(directory, installed='0' * 64)
            self.assertIsInstance(mocks.error, ValueError)
            self.assertIn('does not match the installed runtime source', str(mocks.error))
            mocks.apply.assert_not_called()
            mocks.admit.assert_not_called()

    def test_prepare_refuses_an_ineligible_node_before_runtime_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            mocks = self.prepared(directory, eligible=[demo.NODE])
            self.assertIsInstance(mocks.error, RuntimeError)
            self.assertIn(demo.QWEN_NODE + ' is not eligible', str(mocks.error))
            mocks.runtime.assert_not_called()
            mocks.apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
