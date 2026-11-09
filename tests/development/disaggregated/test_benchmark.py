from tests.support import ROOT
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location('workshop_disagg_benchmark', ROOT / 'scripts/development/disaggregated/benchmark.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
analysis_spec = importlib.util.spec_from_file_location('analyze_workshop_disagg', ROOT / 'scripts/development/disaggregated/analyze.py')
analysis = importlib.util.module_from_spec(analysis_spec)
analysis_spec.loader.exec_module(analysis)
recovery_spec = importlib.util.spec_from_file_location('recover_workshop_disagg_cpu', ROOT / 'scripts/development/disaggregated/recover_client.py')
recovery = importlib.util.module_from_spec(recovery_spec)
recovery_spec.loader.exec_module(recovery)
forensic_spec = importlib.util.spec_from_file_location('inspect_workshop_disagg_cpu', ROOT / 'scripts/development/disaggregated/inspect_client.py')
forensic = importlib.util.module_from_spec(forensic_spec)
forensic_spec.loader.exec_module(forensic)
controller_spec = importlib.util.spec_from_file_location('overnight_disagg_controller', ROOT / 'scripts/development/disaggregated/controller.py')
controller = importlib.util.module_from_spec(controller_spec)
controller_spec.loader.exec_module(controller)
handoff_spec = importlib.util.spec_from_file_location('workshop_disagg_handoff', ROOT / 'scripts/development/disaggregated/handoff.py')
handoff = importlib.util.module_from_spec(handoff_spec)
handoff_spec.loader.exec_module(handoff)


class FakeRun:
    ns = bench.NAMESPACE

    def __init__(self, path):
        self.path = path
        self.state = {'model_lock': json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())}

    def labels(self):
        return {'app.kubernetes.io/managed-by': 'kubecon-dynamo-feature-tests', 'feature-test-run': self.ns}


class DisaggBenchmarkGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = FakeRun(Path(self.temporary.name))
        self.original_gpus = copy.deepcopy(bench.c.GPUS)
        self.original_cpu = bench.c.CPU_NODE
        bench.c.GPUS = copy.deepcopy(bench.GPUS)
        bench.c.CPU_NODE = 'kubecon-nke-site-cp-0942'
        self.addCleanup(setattr, bench.c, 'GPUS', self.original_gpus)
        self.addCleanup(setattr, bench.c, 'CPU_NODE', self.original_cpu)
        # Keep these contract inputs independent of ignored measurement runs.
        probes = {
            'startupProbe': {'httpGet': {'path': '/live', 'port': 9090}, 'periodSeconds': 2,
                             'timeoutSeconds': 20, 'failureThreshold': 1800},
            'readinessProbe': {'httpGet': {'path': '/ready', 'port': 9090}, 'periodSeconds': 2,
                               'timeoutSeconds': 20, 'failureThreshold': 3}}
        (self.run.path / 'expected-probes.json').write_text(json.dumps(probes))

    def workers(self, topology):
        value = bench.manifest(self.run, topology)
        graph = next(v for v in value['items'] if v['kind'] == 'DynamoGraphDeployment')
        return value, [v for v in graph['spec']['components'] if v['type'] != 'frontend']

    def test_equal_four_gpu_budget_and_frozen_uuids(self):
        for topology in bench.ARMS:
            value, workers = self.workers(topology)
            self.assertEqual(sum(v['replicas'] * 2 for v in workers), 4)
            for claim in [v for v in value['items'] if v['kind'] == 'ResourceClaimTemplate']:
                exact = claim['spec']['spec']['devices']['requests'][0]['exactly']
                self.assertEqual(exact['count'], 2)
                expression = exact['selectors'][0]['cel']['expression']
                uuids = json.loads(expression.split(' in ', 1)[1])
                self.assertTrue(set(uuids).issubset({u for pair in bench.GPUS.values() for u in pair}))
                self.assertIn(len(uuids), (2, 4))

    def test_same_native_context_batching_and_model(self):
        controls = ('--model', '--revision', '--tensor-parallel-size', '--max-num-seqs',
                    '--max-num-batched-tokens', '--gpu-memory-utilization', '--block-size')
        all_controls = []
        for topology in bench.ARMS:
            _, workers = self.workers(topology)
            for worker in workers:
                main = worker['podTemplate']['spec']['containers'][0]
                args = main['args']
                self.assertNotIn('--max-model-len', args)
                self.assertIn('--language-model-only', args)
                self.assertEqual(args[args.index('--max-num-seqs') + 1], '128')
                all_controls.append({flag: args[args.index(flag) + 1] for flag in controls})
        self.assertTrue(all(v == all_controls[0] for v in all_controls))

    def test_disagg_roles_use_distinct_frozen_nodes(self):
        _, workers = self.workers('disaggregated')
        self.assertEqual([v['type'] for v in workers], ['prefill', 'decode'])
        for worker, node in zip(workers, bench.GPUS):
            pod = worker['podTemplate']
            self.assertEqual(pod['spec']['nodeSelector'], {'kubernetes.io/hostname': node})
            main = pod['spec']['containers'][0]
            args = main['args']
            self.assertEqual(args[args.index('--disaggregation-mode') + 1], worker['type'])
            transfer = json.loads(args[args.index('--kv-transfer-config') + 1])
            self.assertEqual(transfer['kv_connector'], 'NixlConnector')
            self.assertEqual(transfer['kv_connector_extra_config']['backends'], ['LIBFABRIC'])

    def test_reject_non_tp2_claim_and_unknown_topology(self):
        claim = {'spec': {'spec': {'devices': {'requests': [{'exactly': {'count': 1}}]}}}}
        with self.assertRaises(ValueError):
            bench.select_claim(claim, [])
        with self.assertRaises(ValueError):
            bench.manifest(self.run, 'unmatched')


class AnalysisGuards(unittest.TestCase):
    def valid(self):
        return {'is_complete': True, 'was_cancelled': False, 'metadata': {'submission_valid': True},
                'request_count': {'avg': 10}, 'total_osl': {'avg': 10000},
                'output_token_throughput': {'avg': 5}, 'benchmark_duration': {'avg': 2100}}

    def test_keep_throughput_denominator_distinct_from_admission(self):
        result = analysis.derive_metrics(self.valid(), 4)
        self.assertEqual(result['output_tokens_per_second_per_gpu'], 1.25)
        self.assertEqual(result['exported_throughput_denominator_seconds'], 2000)
        self.assertEqual(result['benchmark_duration_metric_seconds'], 2100)

    def test_reject_invalid_or_error_profiles(self):
        for key, value in [('was_cancelled', True), ('is_complete', False),
                           ('error_request_count', {'avg': 1}), ('context_overflow_count', {'avg': 1}),
                           ('runtime_submission_invalid_reasons', ['bad primer'])]:
            data = self.valid()
            data[key] = value
            with self.assertRaises(ValueError):
                analysis.derive_metrics(data, 4)

    def test_reject_unmatched_gpu_budget_and_empty_requests(self):
        with self.assertRaises(ValueError):
            analysis.derive_metrics(self.valid(), 8)
        data = self.valid()
        data['request_count'] = {'avg': 0}
        with self.assertRaises(ValueError):
            analysis.derive_metrics(data, 4)


class CpuRecoveryGuards(unittest.TestCase):
    def receipt(self):
        return {'status': 'prepared', 'profile_sha256': 'profile', 'helper_sha256': 'helper',
                'seed': 20261030, 'cache_files': {'mmap': {'bytes': 10, 'sha256': 'cache'}},
                'cgroup_after': {'memory.events': 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n'}}

    def test_accept_unchanged_original_terminal_receipt(self):
        recovery.validate(self.receipt(), 'profile', 'helper', 'prepared')

    def test_reject_different_profile_helper_failure_and_oom(self):
        for field, value in [('profile_sha256', 'wrong'), ('helper_sha256', 'wrong'),
                             ('seed', 1), ('status', 'running'), ('cache_files', {}),
                             ('cgroup_after', {'memory.events': 'oom 1\noom_kill 1\n'})]:
            receipt = self.receipt()
            receipt[field] = value
            with self.assertRaises(ValueError):
                recovery.validate(receipt, 'profile', 'helper', 'prepared')

    def test_reject_expired_original_pod_without_exec_or_cache_adoption(self):
        expected = {'uid': 'original', 'node': 'node'}
        pod = {'metadata': {'uid': 'original', 'labels': {'feature-test-run': 'owned'}},
               'spec': {'nodeName': 'node'}, 'status': {'phase': 'Failed', 'reason': 'DeadlineExceeded',
               'containerStatuses': [{'imageID': 'image@sha256:abc', 'restartCount': 0,
                                      'state': {'terminated': {'exitCode': 0}}}]}}
        with self.assertRaisesRegex(ValueError, 'no longer running'):
            recovery.validate_original_pod(pod, expected, 'owned', 'image@sha256:abc')


class CpuForensicGuards(unittest.TestCase):
    def test_only_exact_source_and_read_only_observer_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            run = FakeRun(Path(directory))
            (run.path / 'client-identity.json').write_text(json.dumps({'uid': 'source', 'node': 'node'}))
            client = {'metadata': {'namespace': run.ns, 'name': 'rr-loadgen', 'uid': 'source'},
                      'spec': {'nodeName': 'node'}, 'status': {'containerStatuses': [
                          {'containerID': 'containerd://' + 'a' * 64, 'restartCount': 0}]}}
            observer = {'metadata': {'namespace': 'gpu-operator', 'name': 'nvidia-container-toolkit-daemonset-test',
                                    'uid': 'observer'}, 'spec': {'nodeName': 'node', 'containers': [
                {'name': 'nvidia-container-toolkit-ctr', 'volumeMounts': [{'mountPath': '/host', 'readOnly': True}]}]}}
            inventory = run.path / 'inventory.json'
            inventory.write_text(json.dumps({'items': [client, observer]}))
            _, cid, _ = forensic.source(inventory, run)
            self.assertEqual(cid, 'a' * 64)
            for changed in ('uid', 'readOnly'):
                bad_client, bad_observer = copy.deepcopy(client), copy.deepcopy(observer)
                if changed == 'uid':
                    bad_client['metadata']['uid'] = 'foreign'
                else:
                    bad_observer['spec']['containers'][0]['volumeMounts'][0]['readOnly'] = False
                inventory.write_text(json.dumps({'items': [bad_client, bad_observer]}))
                with self.assertRaises(ValueError):
                    forensic.source(inventory, run)


class ControllerWindowGuards(unittest.TestCase):
    def test_deadline_requires_timezone_and_preserves_equivalent_instant(self):
        with self.assertRaisesRegex(ValueError, 'timezone'):
            controller.parse_deadline('2026-11-05T10:00:00')
        self.assertEqual(controller.parse_deadline('2026-11-05T10:00:00-08:00'),
                         controller.parse_deadline('2026-11-05T18:00:00Z'))

    def test_wrong_execution_wrapper_hash_rejected_before_controller_start(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'campaign.json').write_text(json.dumps({'profile_seconds': 900, 'grace_seconds': 300,
                'execution_entrypoint': 'scripts/development/disaggregated/handoff.py', 'execution_entrypoint_sha256': 'wrong'}))
            argv = ['controller', '--run', str(run), '--attempt', 'test', '--deadline', '2099-01-01T00:00:00Z',
                    '--entrypoint', str(ROOT / 'scripts/development/disaggregated/handoff.py')]
            with mock.patch('sys.argv', argv):
                with self.assertRaisesRegex(ValueError, 'immutable campaign'):
                    controller.main()
            self.assertFalse((run / 'controller-test-start.json').exists())


class CpuHandoffGuards(unittest.TestCase):
    def values(self):
        probe = {'namespace': handoff.SOURCE_NAMESPACE, 'uid': handoff.SOURCE_UID, 'node': 'node'}
        qualification = {'passed': True, 'active_benchmark_processes': [], 'source_pod_uid': handoff.SOURCE_UID,
                         'source_namespace': handoff.SOURCE_NAMESPACE, 'files': {'cache': {}},
                         'pinned_source_members_verified': 1}
        acknowledgment = {'status': 'exclusive_cpu_client_use_handed_off', 'live_executor': '/root',
            'to_agent': '/root/disagg_comparison', 'client': {'namespace': handoff.SOURCE_NAMESPACE,
            'uid': handoff.SOURCE_UID, 'node': 'node'}, 'old_routing_controller': {'retired_for_future_execution': True}}
        return probe, qualification, acknowledgment

    def test_require_exact_handoff_and_idle_qualified_client(self):
        probe, qualification, acknowledgment = self.values()
        handoff.validate_handoff(probe, qualification, acknowledgment)
        for kind in ('identity', 'active', 'retired'):
            p, q, a = copy.deepcopy(probe), copy.deepcopy(qualification), copy.deepcopy(acknowledgment)
            if kind == 'identity':
                a['client']['uid'] = 'foreign'
            elif kind == 'active':
                q['active_benchmark_processes'] = [{'pid': 1}]
            else:
                a['old_routing_controller']['retired_for_future_execution'] = False
            with self.assertRaises(ValueError):
                handoff.validate_handoff(p, q, a)

    def test_gpu_cleanup_retains_borrowed_cpu(self):
        with tempfile.TemporaryDirectory() as directory:
            run = FakeRun(Path(directory))
            with mock.patch.object(handoff.b, 'LEASE', run.path / 'absent-lease'), \
                 mock.patch.object(handoff.b.c, 'cleanup_gpu') as gpu_cleanup, \
                 mock.patch.object(handoff, 'check_client', return_value={'metadata': {'uid': handoff.SOURCE_UID}}):
                handoff.cleanup(run)
            gpu_cleanup.assert_called_once_with(run)
            receipt = json.loads((run.path / 'cleanup-final.json').read_text())
            self.assertTrue(receipt['borrowed_cpu_retained'])
            self.assertIn('PVC', receipt['retained'])


if __name__ == '__main__':
    unittest.main()
