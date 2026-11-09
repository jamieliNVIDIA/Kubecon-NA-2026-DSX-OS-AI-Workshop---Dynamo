"""Node/resource isolation, source provenance, and strict recovery evidence."""
import json
import copy
import hashlib
import http.client
import io
from urllib.error import HTTPError
from pathlib import Path
import subprocess
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.kvcr.guard as guard
import kvcr_guard_bootstrap as bootstrap
import kvcr_guard_runtime as runtime


class GuardTests(unittest.TestCase):
    def test_recorded_handback_baseline_refuses_an_additional_source_restart(self):
        def pod(name):
            return {'metadata': {'uid': name}, 'status': {'containerStatuses': [
                {'name': role, 'containerID': name + role, 'restartCount': int(name == 'a' and role == 'main'),
                 'ready': True} for role in ('main', 'kvcr-services')]}}
        baseline = {'a': pod('a'), 'b': pod('b')}
        changed = copy.deepcopy(baseline)
        changed['a']['status']['containerStatuses'][0]['restartCount'] += 1
        run = SimpleNamespace(ns='owned', get=mock.Mock(return_value={'items': []}), k=mock.Mock())
        with mock.patch.object(guard, 'require_lease'), \
                mock.patch.object(guard, 'peers', return_value=changed), self.assertRaises(ValueError):
            guard.wait(run, 10, phase='handback', previous_workers={'a': 'old-a', 'b': 'b'},
                       baseline_pods=baseline, previous_engine={'start_ticks': '1'})
        run.k.assert_not_called()

    def test_common_namespace_overrides_operator_frontend_prefix(self):
        with mock.patch.dict(runtime.os.environ, {
                'KVCR_DYNAMO_NAMESPACE': 'owned-guard',
                'DYN_NAMESPACE': 'operator-graph',
                'DYN_NAMESPACE_PREFIX': 'operator-graph',
                'DYN_NAMESPACE_WORKER_SUFFIX': 'operator-suffix'}, clear=True):
            env = runtime.environment()
        self.assertEqual(env['DYN_NAMESPACE'], 'owned-guard')
        self.assertEqual(env['DYN_NAMESPACE_PREFIX'], 'owned-guard')
        self.assertNotIn('DYN_NAMESPACE_WORKER_SUFFIX', env)

    def test_sticky_pod_readiness_does_not_complete_handback(self):
        pods = []
        for role, peer in [('frontend', None), ('worker', 'a'), ('worker', 'b')]:
            labels = {'workshop-role': role}
            if peer:
                labels['kvcr-peer'] = peer
            pods.append({'metadata': {'name': role + str(peer), 'labels': labels},
                         'spec': {'nodeName': guard.NODE},
                         'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}})
        run = SimpleNamespace(path=Path('/owned'), ns='owned',
                              get=mock.Mock(return_value={'items': pods}), save=mock.Mock(),
                              k=mock.Mock(return_value=SimpleNamespace(stdout='', stderr='')))
        for source in (None, 'old-a'):
            current = {'b': 'survivor-b', **({'a': source} if source else {})}
            with self.subTest(source=source), \
                    mock.patch.object(guard, 'require_lease'), \
                    mock.patch.object(guard.support, 'healthy'), \
                    mock.patch.object(guard, 'peers', return_value={'a': {}}), \
                    mock.patch.object(guard, 'worker_ids', return_value=current), \
                    mock.patch.object(guard, 'inspect_engine', return_value={
                        'pid': 2, 'command': 'VLLM::EngineCore', 'start_ticks': '1'}), \
                    mock.patch.object(guard.time, 'sleep', side_effect=RuntimeError('still waiting')), \
                    mock.patch.object(guard.ui, 'write_json', side_effect=AssertionError('premature readiness receipt')), \
                    mock.patch.object(Path, 'write_text'):
                with self.assertRaisesRegex(RuntimeError, 'still waiting'):
                    guard.wait(run, 10, phase='handback',
                               previous_workers={'a': 'old-a', 'b': 'survivor-b'},
                               previous_engine={'pid': 2, 'command': 'VLLM::EngineCore', 'start_ticks': '1'})
                run.save.assert_not_called()

    def test_handback_uses_engine_incarnation_instead_of_endpoint_id(self):
        old = {'pid': 20, 'command': 'VLLM::EngineCore', 'start_ticks': '123'}
        self.assertFalse(guard.replacement_engine(old, old))
        self.assertFalse(guard.replacement_engine(old, {**old, 'pid': 21}))
        self.assertFalse(guard.replacement_engine(old, {**old, 'command': 'other', 'start_ticks': '124'}))
        self.assertTrue(guard.replacement_engine(old, {**old, 'start_ticks': '124'}))

    def test_response_preserves_http_errors_and_rejects_error_plus_done(self):
        class Stream(io.BytesIO):
            status=200
        with tempfile.TemporaryDirectory() as directory:
            run=SimpleNamespace(path=Path(directory),state={'model_lock':{'model':'model'}})
            error=HTTPError('http://localhost',503,'unavailable',{},io.BytesIO(b'{"error":"unavailable"}'))
            with mock.patch('urllib.request.urlopen',side_effect=error), self.assertRaises(ValueError):
                guard.response(run,'http://localhost','http-error','prompt','1')
            self.assertEqual((run.path/'http-error/response.sse').read_bytes(),b'{"error":"unavailable"}')
            raw=b'data: {"error":{"message":"failed"}}\n\ndata: [DONE]\n\n'
            with mock.patch('urllib.request.urlopen',return_value=Stream(raw)), self.assertRaises(ValueError):
                guard.response(run,'http://localhost','sse-error','prompt','1')
            value=json.loads((run.path/'sse-error/response.json').read_text())
            self.assertTrue(value['errors'])
            self.assertTrue(value['done'])

    def test_response_requires_actual_expected_worker_and_terminal_success(self):
        class Stream(io.BytesIO):
            status=200
        chunk={'id':'one','model':'model','nvext':{'worker_id':{'decode_worker_id':1}},
               'choices':[{'delta':{'content':'READY'},'finish_reason':'stop'}],
               'usage':{'prompt_tokens_details':{'cached_tokens':64}}}
        raw=('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            run=SimpleNamespace(path=Path(directory),state={'model_lock':{'model':'model'}})
            with mock.patch('urllib.request.urlopen',return_value=Stream(raw)):
                self.assertEqual(guard.response(run,'http://localhost','valid','prompt','1')['content'],'READY')
            with mock.patch('urllib.request.urlopen',return_value=Stream(raw)), self.assertRaises(ValueError):
                guard.response(run,'http://localhost','wrong-worker','prompt','2')

    def test_transfer_requires_nonempty_guard_exact_receipts_and_actual_transport_evidence(self):
        source = ('using provider=efa\n'
                  'KVCR_EVENT guard_promoted guard=0 recovered_blocks=6 agent=guard-a control=1.2.3.4:23280\n'
                  'KVCR_EVENT source_transfer_completed op=9 source_op=2 target=b blocks=6 bytes=1234 result=success\n')
        target = ('KVCR_EVENT target_transfer_completed scope=remote_deliver request_id=request '
                  'op=9 source=tcp://1.2.3.4:23280 blocks=6 bytes=1234 result=success\n')
        proof = guard.transfer_proof(source, target, '1.2.3.4', 6, 1234, target_transport_log='using provider=efa')
        self.assertEqual(proof['bytes'], 1234)
        cases = [(source.replace('recovered_blocks=6','recovered_blocks=0'),target),
                 (source,target.replace('1.2.3.4','1.2.3.5')),
                 (source,target.replace('bytes=1234','bytes=1235')),
                 (source,target.replace('result=success','result=partial')),
                 (source.replace('provider=efa','provider=tcp'),target),
                 (source.replace('op=9 source_op=2','op=2 source_op=9'),target),
                 (source + 'KVCR pool recovery disabled\n',target),
                 (source,target + target)]
        for left, right in cases:
            with self.subTest(left=left,right=right), self.assertRaises(ValueError):
                guard.transfer_proof(left,right,'1.2.3.4',6,1234,target_transport_log='using provider=efa')

    def test_metric_deltas_support_prometheus_counter_names_and_refuse_resets(self):
        name='vllm:kvcr_transfer_blocks'
        before='vllm:kvcr_transfer_blocks_total{operation="remote_deliver"} 6\n'
        after='vllm:kvcr_transfer_blocks_total{operation="remote_deliver"} 12\n'
        self.assertEqual(guard.delta(before,after,name,{'operation':'remote_deliver'}),6)
        with self.assertRaises(ValueError):
            guard.delta(after,before,name,{'operation':'remote_deliver'})

    def test_guard_and_survivor_identities_must_remain_healthy(self):
        def pod(name):
            return {'metadata':{'uid':name},'status':{'containerStatuses':[
                {'name':role,'containerID':name+role,'restartCount':0,'ready':True}
                for role in ('main','kvcr-services')]}}
        before={'a':pod('a'),'b':pod('b')}
        after=copy.deepcopy(before);after['a']['status']['containerStatuses'][0]['ready']=False
        guard.stable_containers(before,after)
        for role,field,value in [('kvcr-services','restartCount',1),('kvcr-services','containerID','other'),('main','ready',False)]:
            bad=copy.deepcopy(before)
            next(x for x in bad['b']['status']['containerStatuses'] if x['name']==role)[field]=value
            with self.assertRaises(ValueError):
                guard.stable_containers(before,bad)

    def test_owned_exec_refuses_replaced_or_foreign_node_pods(self):
        pod={'metadata':{'name':'a','uid':'old','labels':{'feature-test-run':'dynamo-ft-owned'}},
             'spec':{'nodeName':guard.NODE}}
        run=SimpleNamespace(path=Path('/owned'),ns='dynamo-ft-owned',k=mock.Mock())
        for mutation in ('uid','node'):
            wrong=copy.deepcopy(pod)
            if mutation=='uid':wrong['metadata']['uid']='replacement'
            else:wrong['spec']['nodeName']='kubecon-nke-site-cp-0198'
            run.get=mock.Mock(return_value=wrong)
            with mock.patch.object(ui,'lease_owned',return_value=True), self.assertRaises(ValueError):
                guard.owned_exec(run,pod,'main','python3','-c','pass')
            run.k.assert_not_called()

    def test_two_engines_have_distinct_claims_and_preserve_reserved_nodes(self):
        model = ui.read_json(ui.MODEL_LOCK)
        candidate = {'configmap': 'source', 'bundle_sha256': 'frozen'}
        graph, claims = guard.render('dynamo-ft-owned', model, candidate, 'runtime')
        workers = [c for c in graph['spec']['components'] if c['type'] == 'worker']
        self.assertEqual(len(workers), 2)
        self.assertEqual(len({c['metadata']['name'] for c in claims}), 2)
        self.assertEqual(sum(c['spec']['spec']['devices']['requests'][0]['exactly']['count'] for c in claims), 4)
        for component in graph['spec']['components']:
            spec = component['podTemplate']['spec']
            self.assertEqual(spec['nodeSelector'], {'kubernetes.io/hostname': guard.NODE})
            self.assertNotIn('hostPID', spec)
            self.assertNotIn('shareProcessNamespace', spec)
            for container in spec['containers']:
                self.assertEqual(container['image'], model['runtime_image'])
                env_names=[e['name'] for e in container['env']]
                self.assertEqual(len(env_names),len(set(env_names)))
            if component['type'] != 'worker':
                self.assertIn('/candidate/bootstrap.py', spec['containers'][0]['command'])
                self.assertIn({'name': 'candidate', 'mountPath': '/candidate', 'readOnly': True},
                              spec['containers'][0]['volumeMounts'])
                continue
            main, sidecar = spec['containers']
            self.assertEqual(spec['runtimeClassName'],'nvidia-legacy')
            self.assertEqual({e['name']:e.get('value') for e in main['env']}['NVIDIA_VISIBLE_DEVICES'],'void')
            self.assertEqual({e['name']:e.get('value') for e in sidecar['env']}['NVIDIA_VISIBLE_DEVICES'],'none')
            self.assertIn('claims', main['resources'])
            self.assertNotIn('claims', sidecar['resources'])
            self.assertNotIn('nvidia.com/gpu', sidecar['resources']['limits'])
            self.assertNotIn('livenessProbe', sidecar)
            self.assertNotIn('startupProbe', sidecar)
            self.assertIn('readinessProbe', sidecar)
            self.assertNotIn('/dev/shm/kvcr', [v['mountPath'] for v in main['volumeMounts']])
            self.assertIn('/dev/shm/kvcr', [v['mountPath'] for v in sidecar['volumeMounts']])

    def test_stable_cache_owners_and_identical_model_geometry(self):
        model = ui.read_json(ui.MODEL_LOCK)
        argv = []
        for peer in ('a', 'b'):
            env = {'KVCR_PEER': peer, 'KVCR_MODEL': model['model'], 'KVCR_MODEL_REVISION': model['revision'],
                   'POD_IP': '127.0.0.1', 'KVCR_COMPATIBILITY_DIGEST': 'frozen-layout'}
            args = runtime.engine_args(env)
            config = json.loads(args[args.index('--kv-transfer-config') + 1])['kv_connector_extra_config']
            self.assertEqual(args[args.index('--tensor-parallel-size') + 1], '2')
            self.assertEqual(args[args.index('--revision') + 1], model['revision'])
            tier = config['secondary_tiers'][0]
            self.assertEqual(tier['remote_fw_dram_backend'], 'LIBFABRIC')
            self.assertEqual(tier['compatibility_digest'], 'frozen-layout')
            argv.append(config['dynamo_state_agent']['cache_owner_ids']['0'])
        self.assertNotEqual(*argv)
        with self.assertRaises(ValueError):
            runtime.engine_args({'KVCR_PEER': 'foreign'})

    def test_source_bundle_identity_is_reproducible_and_foreign_configmap_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name in ('kvcr', 'adapter', 'build-wheels'):
                (path / 'sources' / name).mkdir(parents=True)
                (path / 'sources' / name / 'payload').write_text(name)
            calls = []
            def execute(*args, **kwargs):
                calls.append(args)
                return subprocess.CompletedProcess(args, 1, '', 'NotFound') if args[0] == 'get' else subprocess.CompletedProcess(args, 0, '', '')
            run = SimpleNamespace(path=path, ns='dynamo-ft-owned', labels=lambda: {'feature-test-run': 'dynamo-ft-owned'}, k=execute)
            first = guard.source_candidate(run)
            second = guard.source_candidate(run)
            self.assertEqual(first['identity'], second['identity'])
            metadata = path / 'sources/runtime-meta'
            metadata.mkdir()
            nightly = {'version': 'nightly', 'wheels': [{'sha256': 'pinned'}]}
            (metadata / 'runtime-sources.json').write_text(json.dumps(nightly))
            wheel_directory = path / 'sources/runtime-wheels'
            wheel_directory.mkdir()
            (wheel_directory / 'large.whl').write_bytes(b'wheel artifact must stay outside ConfigMap')
            with_nightly = guard.source_candidate(run)
            self.assertNotEqual(first['identity'], with_nightly['identity'])
            self.assertEqual(with_nightly['dynamo_nightly'], nightly)
            with tarfile.open(with_nightly['bundle']) as bundle:
                self.assertIn('runtime-meta/runtime-sources.json', bundle.getnames())
                self.assertFalse(any(name.endswith('.whl') and name.startswith('runtime-wheels/')
                                     for name in bundle.getnames()))
            foreign = {'metadata': {'labels': {'feature-test-run': 'other'}}}
            run.k = mock.Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(foreign), ''))
            with self.assertRaises(ValueError):
                guard.source_candidate(run)
            run.k.assert_called_once()

    def test_foreign_reservation_refuses_gpu_actions_before_any_cluster_call(self):
        run = SimpleNamespace(path=Path('/foreign'), state={})
        with mock.patch.object(ui, 'lease_owned', return_value=False):
            for operation in (guard.deploy, lambda r: guard.wait(r, 1)):
                with self.assertRaises(RuntimeError):
                    operation(run)


class BootstrapDownloadTests(unittest.TestCase):
    @staticmethod
    def response(outcome):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        if isinstance(outcome, BaseException):
            response.read.side_effect = outcome
        else:
            response.read.return_value = outcome
        return response

    def test_cut_off_wheel_download_is_retried_in_place_and_hash_checked(self):
        data = b'pinned wheel'
        record = {'filename': 'ai_dynamo_runtime.whl', 'url': 'https://wheels.invalid/ai_dynamo_runtime.whl',
                  'sha256': hashlib.sha256(data).hexdigest()}
        attempts = [self.response(http.client.IncompleteRead(b'partial', 54617191)), self.response(data)]
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', side_effect=attempts) as urlopen, \
                mock.patch.object(bootstrap.time, 'sleep') as sleep, \
                mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(bootstrap.fetch(record), data)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2)
        failed = [json.loads(line.split(' ', 1)[1]) for line in output.getvalue().splitlines()
                  if line.startswith('KVCR_DOWNLOAD_FAILED ')]
        self.assertEqual([(f['attempt'], f['error'].split(':')[0]) for f in failed], [(1, 'IncompleteRead')])

    def test_persistently_bad_wheel_fails_after_bounded_attempts(self):
        record = {'filename': 'ai_dynamo.whl', 'url': 'https://wheels.invalid/ai_dynamo.whl',
                  'sha256': hashlib.sha256(b'pinned wheel').hexdigest()}
        attempts = [HTTPError(record['url'], 503, 'unavailable', {}, None),
                    self.response(b'tampered'), self.response(b'tampered')]
        with mock.patch.object(bootstrap.urllib.request, 'urlopen', side_effect=attempts) as urlopen, \
                mock.patch.object(bootstrap.time, 'sleep') as sleep, \
                mock.patch('sys.stdout', new_callable=io.StringIO), \
                self.assertRaisesRegex(ValueError, 'failed 3 downloads; last: hash mismatch'):
            bootstrap.fetch(record, attempts=3)
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_source_lock_pins_the_current_bootstrap(self):
        lock = json.loads((ui.ROOT / 'demos/kvcr/source-lock.json').read_text())
        self.assertEqual(lock['bootstrap_sha256'], ui.digest(guard.BOOTSTRAP))


if __name__ == '__main__':
    unittest.main()
