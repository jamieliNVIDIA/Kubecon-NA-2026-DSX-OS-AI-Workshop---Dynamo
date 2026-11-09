"""Keep the new descriptor writer composition within the qualified controls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.demo as shadow
import demos.shadow.descriptor_writer as recipe


class DescriptorRecipeTests(unittest.TestCase):
    def setUp(self):
        self.template, _ = shadow.render('old', shadow.ui.read_json(shadow.ui.MODEL_LOCK), overlay='old')
        self.identity = {'candidate': 'new', 'tensor_parallel_size': 2}

    def test_new_writer_has_shared_manifest_directory_and_no_reader_or_shape_overlay(self):
        graph = recipe.render_graph(self.template, 'new', 'new-overlay', self.identity)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(worker['experimental'], {'gpuMemoryService': {'deviceClassName': 'new-shadow'}})
        spec = worker['podTemplate']['spec']
        main = spec['containers'][0]
        self.assertIn({'name': 'runtime-descriptors', 'emptyDir': {'sizeLimit': '64Mi'}}, spec['volumes'])
        self.assertIn({'name': 'runtime-descriptors', 'mountPath': recipe.MOUNT}, main['volumeMounts'])
        names = {m.get('subPath') for m in main['volumeMounts'] if m['name'] == 'writer-runtime'}
        self.assertEqual(names, {'model_loader.py', 'workshop_humming.py', 'patches.py', 'workshop_descriptors.py',
                                'workshop_parameter_inventory.py'})
        self.assertNotIn('module.py', names)
        env = {e['name']: e.get('value') for e in main['env']}
        self.assertEqual(json.loads(env['DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY']), self.identity)

    def test_model_engine_arguments_placement_and_original_template_are_preserved(self):
        before = copy.deepcopy(self.template)
        graph = recipe.render_graph(self.template, 'new', 'new-overlay', self.identity)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        old = next(c for c in self.template['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(worker['podTemplate']['spec']['containers'][0]['args'],
                         old['podTemplate']['spec']['containers'][0]['args'])
        self.assertEqual(worker['podTemplate']['spec']['nodeSelector'], {'kubernetes.io/hostname': recipe.NODE})
        self.assertEqual(self.template, before)

    def test_shadow_and_scratch_flags_are_refused(self):
        worker = next(c for c in self.template['spec']['components'] if c['type'] == 'worker')
        worker['podTemplate']['spec']['containers'][0]['env'].append(
            {'name': 'DYN_VLLM_GMS_SHADOW_MODE', 'value': '1'})
        with self.assertRaisesRegex(ValueError, 'must not enable Shadow'):
            recipe.render_graph(self.template, 'new', 'new-overlay', self.identity)

    def test_foreign_node_is_refused(self):
        worker = next(c for c in self.template['spec']['components'] if c['type'] == 'worker')
        worker['podTemplate']['spec']['nodeSelector']['kubernetes.io/hostname'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'assigned node'):
            recipe.render_graph(self.template, 'new', 'new-overlay', self.identity)

    def cpu_fixture(self, directory):
        path = Path(directory)
        (path / 'workshop_descriptors.py').write_text('frozen descriptor')
        (path / 'workshop_parameter_inventory.py').write_text('frozen inventory')
        run = SimpleNamespace(path=path, ns='test',
            state={'checks': {'shadow-writer-preparation': {'status': 'passed'}}})
        def record(name, status, **values):
            run.state['checks'][name] = dict(status=status, **values)
        run.result = record
        spec = {'descriptor_cpu_program_sha256': hashlib.sha256(recipe.CPU_PROGRAM.encode()).hexdigest(),
                'routing_bias_source_hashes': {'role-source': 'fixed'}}
        report = {'cuda_initialized': False, 'parameter_inventory_real_torch_meta_cpu': 'passed',
            'descriptor_source_sha256': recipe.ui.digest(path / 'workshop_descriptors.py'),
            'parameter_inventory_source_sha256': recipe.ui.digest(path / 'workshop_parameter_inventory.py')}
        report.update(routing_bias_roles_real_meta_stock_cpu=40, routing_bias_source_hashes=spec['routing_bias_source_hashes'],
                      stock_shape_dtype_guard='unchanged strict rejection')
        return run, spec, report

    def test_frozen_actual_image_cpu_is_one_attempt_and_gates_gpu_start(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, report = self.cpu_fixture(directory)
            with patch('snapshot_tp2_workflow.cpu_probe', return_value=report) as probe:
                recipe.inspect_descriptors(run, spec)
                recipe.require_descriptor_cpu(run, spec)
                with self.assertRaises(FileExistsError):
                    recipe.inspect_descriptors(run, spec)
            self.assertEqual(probe.call_count, 1)
            environment = {row['name']: row['value'] for row in probe.call_args.args[3]}
            self.assertEqual(environment['DESCRIPTOR_SOURCE_SHA256'], report['descriptor_source_sha256'])
            self.assertEqual(environment['PARAMETER_INVENTORY_SOURCE_SHA256'], report['parameter_inventory_source_sha256'])
            self.assertTrue((run.path / 'descriptor-cpu-intent.json').exists())
            self.assertTrue((run.path / 'descriptor-cpu-result.json').exists())
            (run.path / 'workshop_parameter_inventory.py').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'before any diagnostic GPU'):
                recipe.require_descriptor_cpu(run, spec)

    def test_failed_cpu_preserves_intent_and_cannot_satisfy_gpu_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, report = self.cpu_fixture(directory)
            with patch('snapshot_tp2_workflow.cpu_probe', side_effect=RuntimeError('actual CPU failure')):
                with self.assertRaisesRegex(RuntimeError, 'actual CPU failure'):
                    recipe.inspect_descriptors(run, spec)
            self.assertTrue((run.path / 'descriptor-cpu-intent.json').exists())
            self.assertEqual(run.state['checks']['shadow-writer-descriptor-cpu']['status'], 'failed')
            with self.assertRaisesRegex(ValueError, 'before any diagnostic GPU'):
                recipe.require_descriptor_cpu(run, spec)

    def test_cpu_response_with_cuda_or_wrong_source_cannot_pass(self):
        for field, value in [('cuda_initialized', True), ('descriptor_source_sha256', 'wrong')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                run, spec, report = self.cpu_fixture(directory)
                report[field] = value
                with patch('snapshot_tp2_workflow.cpu_probe', return_value=report):
                    with self.assertRaisesRegex(ValueError, 'incomplete source/metadata/no-CUDA'):
                        recipe.inspect_descriptors(run, spec)
                self.assertFalse((run.path / 'descriptor-cpu-result.json').exists())

    def capture_fixture(self, directory):
        proof = {'status': 'passed', 'worker_pod': 'worker', 'worker_uid': 'pod-uid',
                 'gpu_uuids': list(recipe.UUIDS),
                 'container_ids': {'main': 'writer-generation-1', 'gms-server': 'gms-generation-1'}}
        claim = {'metadata': {'name': 'claim', 'uid': 'claim-uid'},
                 'status': {'allocation': {'devices': {'results': [{'device': 'gpu4'}, {'device': 'gpu5'}]}}}}
        gms = {'gms_' + gpu + '_weights.sock': {'state': {'committed': True,
            'memory_layout_hash': 'a' * 64}, 'events': {'events': [{'kind': 'committed'}]}}
            for gpu in recipe.UUIDS}
        pod = {'metadata': {'name': 'worker', 'uid': 'pod-uid', 'labels': {'feature-test-run': 'test'}},
               'spec': {'nodeName': recipe.NODE}}
        spec = {'descriptor_identity': {'candidate': 'new'}}
        manifests = {str(rank): {'version': recipe.VERSION,
            'identity': dict(spec['descriptor_identity'], tp_rank=rank),
            'gms_memory_layout_hash': 'a' * 64, 'counts': {},
            'reader_ready': True, 'unhandled_modules': {}} for rank in (0, 1)}
        run = SimpleNamespace(path=Path(directory), ns='test',
            state={'checks': {'shadow-writer-serving': proof}},
            get=lambda *args: copy.deepcopy(pod), result=lambda *args, **kwargs: None)
        run.k = unittest.mock.Mock(return_value=SimpleNamespace(stdout=json.dumps(manifests)))
        recipe.write(run.path / 'worker-gpu-claim.json', claim)
        recipe.write(run.path / 'gms-after.json', gms)
        allocation = {'gpu_uuids': list(recipe.UUIDS), 'container_ids': proof['container_ids']}
        def checked(checked_run, pod):
            recipe.write(checked_run.path / 'worker-gpu-claim.json', claim)
            return copy.deepcopy(allocation)
        return run, spec, claim, gms, allocation, checked

    def test_capture_revalidates_both_generations_and_preserves_original_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
            original = (run.path / 'worker-gpu-claim.json').read_bytes()
            with patch.object(recipe.writer, 'verify_worker', side_effect=checked) as verify, \
                    patch.object(recipe.writer, 'gms_state', return_value=gms) as state:
                recipe.capture(run, spec)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(state.call_count, 2)
            self.assertEqual((run.path / 'worker-gpu-claim.json').read_bytes(), original)
            self.assertTrue((run.path / 'descriptor-capture-provenance.json').exists())

    def test_same_pod_writer_or_gms_restart_before_read_refuses_stale_emptydir(self):
        for changed_container in ('main', 'gms-server'):
            with self.subTest(container=changed_container), tempfile.TemporaryDirectory() as directory:
                run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
                allocation['container_ids'] = dict(allocation['container_ids'], **{changed_container: 'replacement'})
                with patch.object(recipe.writer, 'verify_worker', side_effect=checked):
                    with self.assertRaisesRegex(ValueError, 'container generation'):
                        recipe.capture(run, spec)
                run.k.assert_not_called()
                self.assertFalse((run.path / 'descriptor-capture.json').exists())

    def test_gms_layout_change_during_read_refuses_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
            changed = copy.deepcopy(gms)
            next(iter(changed.values()))['state']['memory_layout_hash'] = 'b' * 64
            with patch.object(recipe.writer, 'verify_worker', side_effect=checked), \
                    patch.object(recipe.writer, 'gms_state', side_effect=[gms, changed]):
                with self.assertRaisesRegex(ValueError, 'GMS layout or generation'):
                    recipe.capture(run, spec)
            self.assertFalse((run.path / 'rank-manifests').exists())

    def test_same_pod_writer_restart_during_read_refuses_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
            calls = []
            def restarted(checked_run, pod):
                value = checked(checked_run, pod)
                if calls: value['container_ids']['main'] = 'replacement'
                calls.append(True)
                return value
            with patch.object(recipe.writer, 'verify_worker', side_effect=restarted), \
                    patch.object(recipe.writer, 'gms_state', return_value=gms):
                with self.assertRaisesRegex(ValueError, 'container generation'):
                    recipe.capture(run, spec)
            self.assertFalse((run.path / 'rank-manifests').exists())

    def test_unchanged_containers_with_stale_manifest_layout_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
            manifests = json.loads(run.k.return_value.stdout)
            manifests['0']['gms_memory_layout_hash'] = 'b' * 64
            run.k.return_value.stdout = json.dumps(manifests)
            with patch.object(recipe.writer, 'verify_worker', side_effect=checked), \
                    patch.object(recipe.writer, 'gms_state', return_value=gms):
                with self.assertRaisesRegex(ValueError, 'current committed GMS layout'):
                    recipe.capture(run, spec)
            self.assertFalse((run.path / 'descriptor-capture.json').exists())

    def test_claim_replacement_with_same_physical_gpu_pair_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            run, spec, claim, gms, allocation, checked = self.capture_fixture(directory)
            def replacement(checked_run, pod):
                value = checked(checked_run, pod)
                changed = copy.deepcopy(claim)
                changed['metadata']['uid'] = 'replacement-claim'
                recipe.write(checked_run.path / 'worker-gpu-claim.json', changed)
                return value
            with patch.object(recipe.writer, 'verify_worker', side_effect=replacement):
                with self.assertRaisesRegex(ValueError, 'ResourceClaim identity'):
                    recipe.capture(run, spec)
            run.k.assert_not_called()


if __name__ == '__main__': unittest.main()
