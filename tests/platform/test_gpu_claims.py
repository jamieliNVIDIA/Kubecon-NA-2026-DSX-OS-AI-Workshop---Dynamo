"""Allocation regressions: TP2, distinct workers, and operator-shared Shadow GPUs."""
from tests.support import ROOT
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gpu_claims import prepare
from serving_tests import worker_args, worker_resources
from testlib import Run

LOCK = {'gpu_allocation': 'dra', 'tensor_parallel_size': 2}
MODEL = 'nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'


def graph(shared=False):
    component = {'name': 'worker', 'podTemplate': {'spec': {
        'containers': [{'name': 'main', 'resources': worker_resources(LOCK)}],
        'initContainers': [{'name': 'sidecar', 'resources': {'requests': {'cpu': '1'}}}]}}}
    if shared:
        component['experimental'] = {'gpuMemoryService': {}, 'failover': {}}
    return {'apiVersion': 'nvidia.com/v1beta1', 'kind': 'DynamoGraphDeployment',
            'metadata': {'name': 'ft-agg'}, 'spec': {'components': [component]}}


class ClaimTests(unittest.TestCase):
    def test_tp2_claim_preserves_cpu_sidecar_and_original(self):
        original = graph()
        converted, templates = prepare([original], LOCK)
        spec = converted[0]['spec']['components'][0]['podTemplate']['spec']
        self.assertEqual(templates[0]['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
        self.assertNotIn('nvidia.com/gpu', spec['containers'][0]['resources']['limits'])
        self.assertEqual(spec['containers'][0]['resources']['requests']['memory'], '128Gi')
        self.assertNotIn('claims', spec['initContainers'][0]['resources'])
        self.assertEqual(original['spec']['components'][0]['podTemplate']['spec']['containers'][0]['resources']['limits']['nvidia.com/gpu'], '2')

    def test_shared_shadow_keeps_operator_gpu_input(self):
        original = graph(shared=True)
        converted, templates = prepare([original], LOCK)
        self.assertEqual(converted, [original])
        self.assertEqual(templates, [])

    def test_explicit_and_scalar_allocation_is_rejected(self):
        original = graph()
        original['spec']['components'][0]['podTemplate']['spec']['containers'][0]['resources']['claims'] = [{'name': 'other'}]
        with self.assertRaisesRegex(ValueError, 'mixed scalar'):
            prepare([original], LOCK)

    def test_two_gpu_containers_get_distinct_claims(self):
        pod = {'kind': 'Pod', 'metadata': {'name': 'pair'}, 'spec': {'containers': [
            {'name': name, 'resources': worker_resources(LOCK)} for name in ('a', 'b')]}}
        converted, templates = prepare([pod], LOCK)
        self.assertEqual(len(templates), 2)
        self.assertNotEqual(*[t['metadata']['name'] for t in templates])
        self.assertEqual(len(converted[0]['spec']['resourceClaims']), 2)

    def test_legacy_run_stays_scalar(self):
        original = graph()
        self.assertEqual(prepare([original], {}), ([original], []))

    def test_saved_manifest_contains_allocatable_claims(self):
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            run = Run(Path(directory) / 'fixture')
            run.state['model_lock'] = LOCK
            output = Path(directory) / 'effective.yaml'
            run.write_manifest(output, [graph()])
            bundle = yaml.safe_load(output.read_text())
            self.assertEqual([o['kind'] for o in bundle['items']], ['ResourceClaimTemplate', 'DynamoGraphDeployment'])
            self.assertTrue(all(o['metadata']['namespace'] == run.ns for o in bundle['items']))

    def test_model_flags_retain_feature_transport_and_tp(self):
        args = worker_args(MODEL, 'a' * 40, 'decode', tp=2)
        for flag, value in [('--tensor-parallel-size', '2'), ('--max-model-len', '8192')]:
            self.assertEqual(args[args.index(flag) + 1], value)
        transfer = json.loads(args[args.index('--kv-transfer-config') + 1])
        self.assertEqual(transfer['kv_connector_extra_config']['backends'], ['LIBFABRIC'])
        self.assertNotIn('--speculative-config', args)

    def test_all_serving_renderers_use_tp2_and_preserve_shadow_sharing(self):
        import serving_tests
        import sidecar_tests
        import snapshot_tests
        import shadow_failover_tests
        import modelexpress_tests
        import kvcr_tests
        import yaml
        root = ROOT

        class OfflineRun(Run):
            def get(self, *args):
                self_outer.assertEqual(args, ('get', 'nodes'))
                return {'items': [{'metadata': {'name': 'fixture-node-' + str(i)}} for i in range(3)]}
            def k(self, *args, **kwargs):
                self_outer.assertEqual(args[0], 'wait')  # MX target's source readiness gate is simulated only here.
            def apply(self, objects, **kwargs):
                self.objects.extend(copy.deepcopy(objects))
            def result(self, *args, **kwargs):
                pass

        self_outer = self
        with tempfile.TemporaryDirectory() as directory:
            run = OfflineRun(Path(directory) / 'fixture')
            lock = json.loads((root / 'configs/super-vl-tp2-lock.json').read_text())
            lock['manifest_directory'] = str(Path(directory) / 'manifests')
            run.state['model_lock'] = lock
            run.state['checks']['model-staging'] = {'status': 'passed'}
            run.objects = []
            for topology in ('agg', 'disagg'):
                run.objects.append(serving_tests.render(run, topology))
            sidecar_tests.deploy(run)
            snapshot = snapshot_tests.render(run)
            run.objects.append(snapshot)
            run.objects.append(shadow_failover_tests.render(run))
            modelexpress_tests.deploy(run)
            modelexpress_tests.deploy(run, target=True)
            kvcr_tests.deploy(run)
            import super_vl_tests
            with patch.object(serving_tests, 'smoke'), patch.object(super_vl_tests, 'vision'):
                super_vl_tests.image_smoke(run)
            graphs = [g for g in run.objects if g['kind'] == 'DynamoGraphDeployment']
            self.assertEqual(len(graphs), 9)
            for graph in graphs:
                for component in graph['spec']['components']:
                    spec = component['podTemplate']['spec']
                    main = spec['containers'][0]
                    if component['type'] == 'frontend':
                        self.assertNotIn('nvidia.com/gpu', main['resources']['limits'])
                    else:
                        self.assertEqual(main['resources']['limits']['nvidia.com/gpu'], '2')
                        if graph['metadata']['name'] != 'ft-kvcr':
                            self.assertEqual(main['args'][main['args'].index('--tensor-parallel-size') + 1], '2')
                        if graph['metadata']['name'] in ('ft-shadow', 'ft-snapshot'):
                            self.assertEqual(main['args'][main['args'].index('--gpu-memory-utilization') + 1], '0.65')
                        if graph['metadata']['name'] in ('ft-disagg', 'ft-mx', 'ft-mx-target'):
                            env = {e['name']: e.get('value') for e in main['env']}
                            self.assertEqual(env['NIXL_TELEMETRY_EXPORTER'], 'prometheus_mp')
                            self.assertEqual(env['NIXL_TELEMETRY_MULTIPROC_DIR'], '/tmp/nixl-metrics')
                converted, templates = prepare([graph], lock)
                if graph['metadata']['name'] == 'ft-shadow':
                    self.assertEqual(templates, [])
                else:
                    self.assertTrue(templates)
                    self.assertTrue(all(t['spec']['spec']['devices']['requests'][0]['exactly']['count'] == 2 for t in templates))
            sidecar = next(g for g in graphs if g['metadata']['name'] == 'ft-sidecar')
            worker = next(c for c in sidecar['spec']['components'] if c['type'] != 'frontend')
            args = worker['podTemplate']['spec']['containers'][0]['args']
            self.assertEqual(args[args.index('--grpc-port') + 1], '50051')
            services = [o for o in run.objects if o['kind'] == 'Service']
            self.assertTrue(services)
            self.assertEqual([p['port'] for p in services[0]['spec']['ports']], [6555, 6556])
            mx = next(g for g in graphs if g['metadata']['name'] == 'ft-mx')
            source = next(c for c in mx['spec']['components'] if c['type'] != 'frontend')
            env = {e['name']: e.get('value') for e in source['podTemplate']['spec']['containers'][0]['env']}
            self.assertEqual(env['MX_K8S_SERVICE_PATTERN'], 'mx-source')
            image = next(g for g in graphs if g['metadata']['name'] == 'ft-image')
            image_worker = next(c for c in image['spec']['components'] if c['type'] != 'frontend')
            self.assertEqual(image_worker['replicas'], 1)
            self.assertIn('--enable-multimodal', image_worker['podTemplate']['spec']['containers'][0]['args'])
            for path in (Path(directory) / 'manifests').glob('*.yaml'):
                saved = yaml.safe_load(path.read_text())
                if saved.get('kind') == 'List':
                    self.assertTrue(any(o['kind'] == 'ResourceClaimTemplate' for o in saved['items']))


if __name__ == '__main__':
    unittest.main()
