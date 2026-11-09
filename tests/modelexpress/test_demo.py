"""Validate the MX demo's matching, evidence gates and offline presenter flow."""
from tests.support import ROOT
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import demos.common.runtime as ui
import demos.modelexpress.demo as mx
from demos.common import dependencies, weights


class ModelExpressTests(unittest.TestCase):
    @contextlib.contextmanager
    def live_demo(self):
        """Use a file-bound first replica while all cluster calls remain mocked."""
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory).resolve()
            parent, child, lease = root / 'first replica', root / 'new replica', root / 'lease'
            parent.mkdir()
            lease.mkdir()
            ui.write_json(parent / 'demo.json', {
                'schema': 2, 'profile': ui.PROFILE, 'prepared': True,
                'rehearsal': False, 'namespace': 'dynamo-ft-source'})
            ui.write_json(lease / 'owner.json', {'agent': ui.OWNER, 'run': str(parent)})
            source_graph, _ = ui.render('dynamo-ft-source', ui.read_json(ui.MODEL_LOCK))
            baseline = {'simulated': False, 'engine_signature': weights.engine_signature(source_graph),
                        'source_uid': 'first-worker', 'worker_uid': 'first-worker',
                        'node': 'kubecon-nke-site-cp-0124', 'ready_seconds': 500,
                        'model_loading_seconds': 120, 'engine_init_seconds': 75}
            binding = {'run': str(parent), 'namespace': 'dynamo-ft-source',
                       'worker_uid': 'first-worker', 'node': baseline['node'], 'baseline': baseline}
            identity = {'uid': 'first-worker', 'node': baseline['node'], 'graph_uid': 'first-graph',
                        'frontend_uid': 'first-frontend', 'claim_uid': 'first-claim',
                        'gpu_devices': ['gpu-a', 'gpu-b'], 'service_uid': 'first-service'}
            snapshot = stack.enter_context(mock.patch.object(mx.source_binding, 'snapshot', return_value=binding))
            stack.enter_context(mock.patch.object(mx.source_binding, 'validate_files'))
            stack.enter_context(mock.patch.object(mx.source_binding, 'identity', return_value=identity))
            stack.enter_context(mock.patch.object(ui, 'LEASE', lease))
            args = SimpleNamespace(run=child, source_run=parent, action='prepare',
                                   rehearsal=False, preview=False, auto=True)
            instance = mx.ModelExpressDemo(args)
            for method in ('apply', 'k', 'get', 'command'):
                stack.enter_context(mock.patch.object(instance.run, method))
            yield SimpleNamespace(demo=instance, parent=parent, child=child, lease=lease,
                                  snapshot=snapshot, args=args,
                                  parent_bytes=(parent / 'demo.json').read_bytes(),
                                  lease_bytes=(lease / 'owner.json').read_bytes())

    def assert_source_unchanged(self, fixture):
        self.assertEqual((fixture.parent / 'demo.json').read_bytes(), fixture.parent_bytes)
        self.assertEqual((fixture.lease / 'owner.json').read_bytes(), fixture.lease_bytes)

    def test_first_and_new_replicas_use_same_model_express_engine(self):
        lock = ui.read_json(ui.MODEL_LOCK)
        source, _ = ui.render('dynamo-ft-test', lock)
        peer, claim = mx.render('dynamo-ft-test', lock, node='second-node')
        self.assertEqual(mx.engine_signature(peer), mx.engine_signature(source))
        self.assertEqual(mx.engine_signature(peer), weights.engine_signature(source))
        for graph in (source, peer):
            worker = mx.worker_config(graph)
            self.assertEqual(worker['image'], lock['runtime_image'])
            self.assertIn('--enforce-eager', worker['args'])
            env = {e['name']: e.get('value') for e in worker['env']}
            self.assertEqual(env['MX_ARTIFACT_TRANSFER'], '0')
            self.assertEqual(env['MX_METADATA_BACKEND'], 'k8s-service')
            self.assertNotIn('MODEL_EXPRESS_URL', env)
            self.assertEqual(worker['resources']['limits']['vpc.amazonaws.com/efa'], '8')
        self.assertIn('--load-format', mx.worker_config(source)['args'])
        self.assertIn('--load-format', mx.worker_config(peer)['args'])
        self.assertEqual(claim['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
        self.assertEqual(peer['metadata']['name'], 'demo-mx-target')
        peer_spec = next(c for c in peer['spec']['components'] if c['type'] == 'worker')['podTemplate']['spec']
        self.assertEqual(peer_spec['nodeSelector'], {'kubernetes.io/hostname': 'second-node'})
        self.assertEqual(peer_spec['resourceClaims'][0]['resourceClaimTemplateName'], claim['metadata']['name'])
        for arm in ('source', 'native'):
            with self.subTest(arm=arm), self.assertRaises(ValueError):
                mx.render('dynamo-ft-test', lock, arm)

    def test_engine_signature_binds_loader_and_transport_settings(self):
        lock = ui.read_json(ui.MODEL_LOCK)
        graph, _ = ui.render('dynamo-ft-test', lock)
        signature = mx.engine_signature(graph)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        args = worker['podTemplate']['spec']['containers'][0]['args']
        args[args.index('--load-format') + 1] = 'auto'
        self.assertNotEqual(mx.engine_signature(graph), signature)

    def test_peer_proof_requires_both_ranks_transport_and_no_fallback(self):
        proof = mx.verify_peer(mx.SAMPLE_PEER_LOG, 2)
        self.assertEqual([r['rank'] for r in proof['transfers']], [0, 1])
        self.assertAlmostEqual(proof['gigabytes_total'], 80.54)
        invalid = [mx.SAMPLE_PEER_LOG + '\nTrying strategy: default',
                   '\n'.join(line for line in mx.SAMPLE_PEER_LOG.splitlines() if 'Worker_TP1' not in line),
                   mx.SAMPLE_PEER_LOG.replace('provider=efa', 'provider=tcp'),
                   mx.SAMPLE_PEER_LOG.replace('40.27 GB', '0.00 GB')]
        for logs in invalid:
            with self.subTest(logs=logs[-100:]), self.assertRaises(RuntimeError):
                mx.verify_peer(logs, 2)

    def test_comparison_rejects_changed_config_source_or_same_node(self):
        storage = {'engine_signature': 'same', 'node': 'first-node', 'source_uid': 'first-worker',
                   'worker_uid': 'first-worker', 'simulated': False, 'ready_seconds': 500}
        peer = {**storage, 'node': 'second-node', 'worker_uid': 'new-worker', 'ready_seconds': 250}
        observed = mx.comparison(storage, peer)
        self.assertEqual(observed['observed_readiness_ratio'], 2)
        self.assertNotIn('ready_speedup', observed)
        for key, value in (('engine_signature', 'different'), ('node', 'first-node'),
                           ('source_uid', 'replacement-source'), ('simulated', True)):
            changed = {**peer, key: value}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                mx.comparison(storage, changed)
        with self.assertRaises(RuntimeError):
            mx.comparison({**storage, 'worker_uid': 'another-worker'}, peer)

    def test_comparison_does_not_invent_a_ratio_from_unknown_or_zero_timings(self):
        storage = {'engine_signature': 'same', 'node': 'first-node', 'source_uid': 'first-worker',
                   'worker_uid': 'first-worker', 'simulated': True, 'ready_seconds': None}
        peer = {**storage, 'node': 'second-node', 'worker_uid': 'new-worker'}
        for first, second in ((None, None), (0, 250), (500, 0), (500, None)):
            with self.subTest(first=first, second=second):
                result = mx.comparison({**storage, 'ready_seconds': first}, {**peer, 'ready_seconds': second})
                self.assertIsNone(result['observed_readiness_ratio'])

    def test_transfer_summary_reports_each_rank_and_path_without_identities(self):
        proof = {'transfers': [{'rank': 0, 'tensors': 1413, 'gigabytes': 39.22, 'seconds': 4.23},
                               {'rank': 1, 'tensors': 1413, 'gigabytes': 39.22, 'seconds': 6.2}],
                 'backend': 'LIBFABRIC', 'provider': 'efa', 'gigabytes_total': 78.44, 'slowest_rank_copy_seconds': 6.2,
                 'simulated': False, 'source': {'uid': 'first-worker', 'node': 'kubecon-nke-site-cp-0124',
                                                'gpu_devices': ['GPU-a', 'GPU-b']},
                 'target_node': 'kubecon-nke-site-cp-0198',
                 'target_gpus': {'pod_uid': 'new-worker', 'gpu_uuids': ['GPU-c', 'GPU-d']}}
        self.assertEqual(mx.transfer_summary(proof), [
            'TP0: 39.22 GB in 4.23s',
            'TP1: 39.22 GB in 6.20s',
            'NIXL LIBFABRIC over EFA, kubecon-nke-site-cp-0124 -> kubecon-nke-site-cp-0198; no fallback to storage.'])
        rehearsal = {'simulated': True, 'backend': 'LIBFABRIC', 'provider': 'efa', 'transfers': [],
                     'note': 'Rehearsal only; no GPU bytes or transfer time measured.'}
        self.assertEqual(mx.transfer_summary(rehearsal), [rehearsal['note']])

    def test_comparison_table_nests_the_measured_peer_copy_under_model_loading(self):
        storage = {'simulated': False, 'engine_signature': 'same', 'source_uid': 'first-worker', 'worker_uid': 'first-worker',
                   'node': 'kubecon-nke-site-cp-0124', 'ready_seconds': 492.980123,
                   'model_loading_seconds': 290.701028, 'engine_init_seconds': 83.98}
        peer = {**storage, 'node': 'kubecon-nke-site-cp-0198', 'worker_uid': 'new-worker', 'ready_seconds': 247.010246,
                'model_loading_seconds': 50.147238, 'engine_init_seconds': 82.57}
        with tempfile.TemporaryDirectory() as directory:
            demo = SimpleNamespace(data={'arms': {'storage': storage, 'peer': peer}}, path=Path(directory),
                                   args=SimpleNamespace(rehearsal=False))

            def table():
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    mx.ModelExpressDemo.compare(demo)
                lines = out.getvalue().splitlines()
                loading = next(i for i, line in enumerate(lines) if line.startswith('Model loading'))
                return lines, lines[loading].split()[-2:], lines[loading + 1].split()

            ui.write_json(Path(directory) / 'peer-proof.json', {'slowest_rank_copy_seconds': 6.2})
            lines, loading, copy_row = table()
            self.assertIn('First replica versus new replica · eager profile', lines)
            self.assertEqual(loading, ['290.7s', '50.1s'])
            self.assertEqual(copy_row, ['peer', 'copy,', 'slowest', 'rank', '—', '6.2s'])
            self.assertIn('Observed readiness ratio: 2.00x (first / second replica)', lines)
            (Path(directory) / 'peer-proof.json').unlink()
            self.assertEqual(table()[2][-2:], ['not', 'measured'])

    def test_rehearsal_is_offline_and_compares_before_user_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'MX run with spaces'
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'modelexpress',
                                     '--rehearsal', '--plain', '--auto', '--run', str(path)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NO CLUSTER CALLS', result.stdout)
            self.assertNotIn('Enter or Space', result.stdout)
            self.assertLess(result.stdout.index('First replica versus new replica'), result.stdout.index('Request body:'))
            self.assertTrue(ui.read_json(path / 'comparison.json')['simulated'])
            self.assertIsNone(ui.read_json(path / 'comparison.json')['observed_readiness_ratio'])
            self.assertTrue(ui.read_json(path / 'peer-proof.json')['simulated'])
            self.assertTrue(ui.read_json(path / 'response.json')['simulated'])
            receipts = [ui.read_json(p) for p in path.glob('command-*.json')]
            self.assertTrue(receipts)
            self.assertTrue(all(r['args'][0] == 'cat' for r in receipts))
            self.assertIn('-m demos modelexpress cleanup', result.stdout)

    def test_edited_frozen_input_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run'
            args = [sys.executable, '-B', '-m', 'demos', 'modelexpress', '--preview', '--run', str(path)]
            first = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stderr)
            with (path / 'peer.yaml').open('a') as handle:
                handle.write('\n# edited after preparation\n')
            second = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('prepared MX input changed', second.stderr)

    def test_replaced_worker_cannot_reuse_old_transfer_proof(self):
        instance = object.__new__(mx.ModelExpressDemo)
        instance.args = SimpleNamespace(rehearsal=False)
        instance.path, instance.ns = Path('/some/run'), 'dynamo-ft-example'
        instance.data = {'arms': {'peer': {'worker_uid': 'old-worker', 'node': 'target-node'}},
                         'pod_selector': 'workshop-mx-run=target-token'}
        pods = [{'metadata': {'uid': 'replacement', 'labels': {'workshop-role': role}},
                 'spec': {'nodeName': 'target-node'},
                 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
                for role in ('worker', 'frontend')]
        instance.run = SimpleNamespace(get=lambda *args: {'items': pods})
        with (mock.patch.object(instance, 'source_identity'),
              mock.patch.object(instance, 'target_graph'), self.assertRaisesRegex(RuntimeError, 'replaced')):
            instance.check_peer_identity()

    def test_prepare_reuses_first_replica_without_launching_source_or_native_baseline(self):
        with self.live_demo() as fixture, mock.patch.object(ui, 'acquire') as acquire:
            instance = fixture.demo
            instance.prepare()
            instance.prime()
            self.assertTrue(instance.data['mx_prepared'])
            instance.run.apply.assert_called_once()
            objects = instance.run.apply.call_args.args[0]
            self.assertEqual([(obj['kind'], obj['metadata']['name']) for obj in objects],
                             [('ResourceClaimTemplate', mx.TARGET_GRAPH + '-gpus')])
            self.assertEqual(instance.run.k.call_args_list, [
                mock.call('apply', '--dry-run=client', '-f', str(instance.path / 'peer.yaml')),
                mock.call('apply', '--dry-run=server', '-f', str(instance.path / 'peer.yaml'))])
            acquire.assert_not_called()
            self.assertFalse((fixture.child / 'source.yaml').exists())
            self.assertFalse((fixture.child / 'native.yaml').exists())
            self.assertEqual(ui.read_json(fixture.parent / dependencies.RECORD)['child_run'], str(fixture.child))
            self.assert_source_unchanged(fixture)

    def test_prepare_refuses_a_source_that_lost_its_lease_before_any_apply(self):
        with self.live_demo() as fixture:
            ui.write_json(fixture.lease / 'owner.json', {'agent': 'foreign', 'run': str(fixture.parent)})
            with self.assertRaisesRegex(RuntimeError, 'no longer owns'):
                fixture.demo.prepare()
            fixture.demo.run.apply.assert_not_called()
            fixture.demo.run.k.assert_not_called()

    def test_second_preparation_cannot_overwrite_an_existing_mx_target_claim(self):
        with self.live_demo() as fixture:
            fixture.demo.prepare()
            args = SimpleNamespace(**vars(fixture.args))
            args.run = fixture.child.with_name('another MX run')
            other = mx.ModelExpressDemo(args)
            with (mock.patch.object(other.run, 'apply') as apply,
                  mock.patch.object(other.run, 'k') as kubectl,
                  self.assertRaisesRegex(RuntimeError, 'already has an MX dependent')):
                other.prepare()
            apply.assert_not_called()
            kubectl.assert_not_called()
            self.assertEqual(ui.read_json(fixture.parent / dependencies.RECORD)['child_run'], str(fixture.child))
            self.assert_source_unchanged(fixture)

    def test_start_registers_dependency_before_applying_only_the_peer(self):
        with self.live_demo() as fixture:
            instance = fixture.demo
            def apply(objects):
                self.assertTrue((fixture.parent / dependencies.RECORD).exists())
                self.assertEqual([(obj['kind'], obj['metadata']['name']) for obj in objects],
                                 [('DynamoGraphDeployment', mx.TARGET_GRAPH)])
                self.assert_source_unchanged(fixture)
            instance.run.apply.side_effect = apply
            with (mock.patch.object(instance, 'show_command'),
                  mock.patch.object(instance, 'target_graph', side_effect=[None, {'metadata': {'uid': 'target-uid'}}]),
                  mock.patch.object(instance, 'wait', side_effect=RuntimeError('startup interrupted')),
                  self.assertRaisesRegex(RuntimeError, 'startup interrupted')):
                instance.start_arm()
            instance.run.apply.assert_called_once()
            self.assertEqual(instance.data['target_graph_uid'], 'target-uid')
            self.assertIn('peer', instance.data['arm_intents'])
            self.assertTrue((fixture.parent / dependencies.RECORD).exists())
            self.assert_source_unchanged(fixture)

    def test_resume_preserves_timestamp_and_never_reapplies(self):
        with self.live_demo() as fixture:
            instance = fixture.demo
            original = '2026-11-07T02:39:11+00:00'
            instance.data['arm_intents']['peer'] = {'apply_started_at': original}
            with (mock.patch.object(instance, 'target_graph', return_value={'metadata': {'uid': 'target-uid'}}),
                  mock.patch.object(instance, 'wait', side_effect=RuntimeError('startup interrupted')),
                  self.assertRaisesRegex(RuntimeError, 'startup interrupted')):
                instance.start_arm()
            self.assertEqual(instance.data['apply_started_at'], original)
            instance.run.apply.assert_not_called()
            self.assertTrue((fixture.parent / dependencies.RECORD).exists())
            self.assert_source_unchanged(fixture)

    def test_missing_interrupted_target_is_not_recreated_and_keeps_dependency(self):
        with self.live_demo() as fixture:
            instance = fixture.demo
            instance.data['arm_intents']['peer'] = {'apply_started_at': 'original-timestamp'}
            with (mock.patch.object(instance, 'target_graph', return_value=None),
                  self.assertRaisesRegex(RuntimeError, 'interrupted peer graph is missing')):
                instance.start_arm()
            instance.run.apply.assert_not_called()
            self.assertTrue((fixture.parent / dependencies.RECORD).exists())
            self.assert_source_unchanged(fixture)

    def test_cleanup_deletes_only_peer_and_retains_source_claim_and_lease(self):
        with self.live_demo() as fixture, mock.patch('common_runtime_tests.stop') as stop:
            instance = fixture.demo
            instance.source_identity()
            with dependencies.parent_lock(fixture.parent):
                dependencies.register(fixture.parent, fixture.child)
            def inventory(*args):
                if args[1] == 'pods':
                    self.assertEqual(args[-1], instance.data['pod_selector'])
                    return {'items': []}
                self.assertEqual(args[1], 'resourceclaims')
                return {'items': [{'metadata': {'name': 'demo-inference-first-gpu-claim', 'uid': 'first-claim'}}]}
            instance.run.get.side_effect = inventory
            with mock.patch.object(instance, 'target_graph', return_value={'metadata': {'uid': 'target-uid'}}):
                instance.cleanup()
            stop.assert_called_once_with(instance.run, [mx.TARGET_GRAPH])
            self.assertFalse((fixture.parent / dependencies.RECORD).exists())
            self.assertTrue(instance.data['cleaned_at'])
            self.assert_source_unchanged(fixture)

    def test_unexpected_claim_blocks_cleanup_and_keeps_source_dependency_and_reservation(self):
        with self.live_demo() as fixture, mock.patch.object(mx.time, 'sleep'):
            instance = fixture.demo
            instance.source_identity()
            with dependencies.parent_lock(fixture.parent):
                dependencies.register(fixture.parent, fixture.child)
            instance.run.get.side_effect = lambda *args: {'items': [] if args[1] == 'pods' else [
                {'metadata': {'name': 'arbitrary-claim-name', 'uid': 'unexpected-claim-uid'}}]}
            with (mock.patch.object(instance, 'target_graph', return_value=None),
                  self.assertRaisesRegex(RuntimeError, 'cleanup is incomplete')):
                instance.cleanup()
            self.assertTrue((fixture.parent / dependencies.RECORD).exists())
            self.assertNotIn('cleaned_at', instance.data)
            self.assert_source_unchanged(fixture)

    def test_default_target_chooses_another_node_but_explicit_same_node_is_rejected(self):
        with self.live_demo() as fixture:
            binding = fixture.snapshot.return_value
            fixture.snapshot.return_value = {
                **binding, 'node': mx.DEFAULT_TARGET_NODE,
                'baseline': {**binding['baseline'], 'node': mx.DEFAULT_TARGET_NODE}}
            args = SimpleNamespace(**vars(fixture.args))
            args.run = fixture.child.with_name('fallback target')
            alternate = mx.ModelExpressDemo(args)
            self.assertNotEqual(alternate.data['target_node'], mx.DEFAULT_TARGET_NODE)
            args.run = fixture.child.with_name('invalid target')
            args.target_node = mx.DEFAULT_TARGET_NODE
            with self.assertRaisesRegex(ValueError, 'different node from the first replica'):
                mx.ModelExpressDemo(args)
            self.assert_source_unchanged(fixture)

    def test_foreign_or_replaced_target_graph_is_never_deleted(self):
        with self.live_demo() as fixture, mock.patch('common_runtime_tests.stop') as stop:
            instance = fixture.demo
            instance.data['target_graph_uid'] = 'owned-target-uid'
            good_labels = {'feature-test-run': instance.ns, 'workshop-mx-run': instance.data['target_token']}
            invalid = [({'feature-test-run': instance.ns, 'workshop-mx-run': 'foreign-token'}, 'owned-target-uid'),
                       (good_labels, 'replacement-target-uid')]
            for labels, uid in invalid:
                with self.subTest(labels=labels, uid=uid):
                    instance.run.k.return_value = SimpleNamespace(
                        returncode=0, stdout=json.dumps({'metadata': {'uid': uid, 'labels': labels}}))
                    with self.assertRaises(RuntimeError):
                        instance.cleanup()
                    stop.assert_not_called()
                    instance.run.get.assert_not_called()
                    self.assert_source_unchanged(fixture)

    def test_missing_peer_graph_cannot_reuse_ready_pods_or_cached_proof(self):
        with self.live_demo() as fixture:
            instance = fixture.demo
            with (mock.patch.object(instance, 'target_graph', return_value=None),
                  self.assertRaisesRegex(RuntimeError, 'proven peer graph is missing')):
                instance.check_peer_identity()
            instance.run.get.assert_not_called()
            self.assert_source_unchanged(fixture)

    def test_peer_gpu_identity_is_disjoint_owned_and_stable(self):
        with self.live_demo() as fixture:
            instance = fixture.demo
            instance.source_identity()
            worker = {'metadata': {'uid': 'peer-worker'}, 'spec': {'nodeName': 'second-node'},
                      'status': {'resourceClaimStatuses': [{'resourceClaimName': 'peer-claim'}]}}
            claim = {'metadata': {'uid': 'peer-claim-uid',
                                  'ownerReferences': [{'kind': 'Pod', 'uid': 'peer-worker'}]},
                     'status': {'allocation': {'devices': {'results': [
                         {'driver': 'gpu.nvidia.com', 'pool': 'second-node', 'device': 'gpu-' + str(i)}
                         for i in range(2)]}}}}
            slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'second-node',
                                         'pool': {'name': 'second-node'}, 'devices': [
                                             {'name': 'gpu-' + str(i), 'attributes': {'uuid': {'string': uuid}}}
                                             for i, uuid in enumerate(('gpu-c', 'gpu-d'))]}}]}
            instance.run.get.side_effect = lambda *args: claim if args[1] == 'resourceclaim' else slices
            instance.verify_target_gpus(worker)
            original = (instance.path / 'allocated-gpus.json').read_bytes()
            self.assertEqual(ui.read_json(instance.path / 'allocated-gpus.json')['gpu_uuids'], ['gpu-c', 'gpu-d'])
            claim['metadata']['uid'] = 'replacement-claim'
            with self.assertRaisesRegex(RuntimeError, 'allocation changed'):
                instance.verify_target_gpus(worker)
            self.assertEqual((instance.path / 'allocated-gpus.json').read_bytes(), original)
            claim['metadata']['uid'] = 'peer-claim-uid'
            slices['items'][0]['spec']['devices'][0]['attributes']['uuid']['string'] = 'gpu-a'
            with self.assertRaisesRegex(RuntimeError, 'distinct from the first replica'):
                instance.verify_target_gpus(worker)
            claim['metadata']['ownerReferences'][0]['uid'] = 'foreign-worker'
            with self.assertRaisesRegex(RuntimeError, 'not owned by the target worker'):
                instance.verify_target_gpus(worker)
            self.assert_source_unchanged(fixture)

    def test_resume_keeps_bound_source_when_default_selection_changes(self):
        with self.live_demo() as fixture:
            args = SimpleNamespace(**vars(fixture.args))
            args.action, args.source_run = 'run', None
            fixture.snapshot.reset_mock()
            with mock.patch.object(ui, 'current_run', return_value=Path('/another/first-replica')):
                resumed = mx.ModelExpressDemo(args)
            fixture.snapshot.assert_not_called()
            self.assertEqual(resumed.source_path, fixture.parent)
            args.source_run = Path('/another/first-replica')
            with self.assertRaisesRegex(ValueError, 'bound first replica changed'):
                mx.ModelExpressDemo(args)
            self.assert_source_unchanged(fixture)

    def test_rejected_source_does_not_create_a_new_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new-run'
            args = SimpleNamespace(run=path, source_run=Path('/old/native-run'),
                                   action='prepare', rehearsal=False, preview=False, auto=True)
            with (mock.patch.object(mx.source_binding, 'snapshot', side_effect=ValueError('source is incompatible')),
                  mock.patch.object(ui.Demo, '__init__') as initialize,
                  self.assertRaisesRegex(ValueError, 'source is incompatible')):
                mx.ModelExpressDemo(args)
            initialize.assert_not_called()
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
