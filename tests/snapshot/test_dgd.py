"""DGD recovery qualification gates; all tests are offline."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import types
import unittest
from unittest.mock import patch

import demos.snapshot.dgd as subject


def inputs():
    lock = json.loads((subject.ROOT / 'configs/super-vl-tp2-lock.json').read_text())
    settings = {'gpu_uuids': ['GPU-11111111-1111-1111-1111-111111111111', 'GPU-22222222-2222-2222-2222-222222222222'],
        'node': 'kubecon-nke-site-cp-0124', 'patch_sha256': 'a' * 64,
        'patch_configmap': 'immutable-patch', 'module_path': subject.DEFAULT_MODULE,
        'cache_home': '/model-cache/feature-tests/20261015-super-vl-tp2/hf'}
    return lock, settings


class Render(unittest.TestCase):
    def test_pure_render_preserves_input_and_configures_capture_and_exact_gpu_pair(self):
        lock, settings = inputs()
        original = copy.deepcopy((lock, settings))
        claim, graph = subject.render_objects('dynamo-ft-unit-test', lock, settings)
        self.assertEqual((lock, settings), original)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        pod = worker['podTemplate']
        main = pod['spec']['containers'][0]
        self.assertEqual(main['command'], ['python3', '-m', 'dynamo.vllm'])
        self.assertIn('--language-model-only', main['args'])
        self.assertNotIn('--enforce-eager', main['args'])
        self.assertEqual(main['resources']['requests']['memory'], '256Gi')
        self.assertEqual(main['resources']['limits']['memory'], '512Gi')
        self.assertEqual(pod['metadata']['annotations']['nvidia.com/snapshot-multi-gpu'], 'enabled')
        env = {e['name']: e['value'] for e in main['env']}
        self.assertEqual(env['VLLM_WORKER_MULTIPROC_METHOD'], 'spawn')
        self.assertEqual(worker['experimental']['checkpoint']['startupPolicy'], 'WaitForCheckpoint')
        self.assertEqual(worker['experimental']['checkpoint']['deletionPolicy'], 'Retain')
        self.assertEqual(main['volumeMounts'][-1]['mountPath'], subject.DEFAULT_MODULE)
        self.assertEqual(main['volumeMounts'][-1]['subPath'], 'snapshot.py')
        self.assertNotIn('snapshot-bootstrap', json.dumps(graph))
        selector = claim['spec']['spec']['devices']['requests'][0]['exactly']
        self.assertEqual(selector['count'], 2)
        for uuid in settings['gpu_uuids']:
            self.assertIn(uuid, selector['selectors'][0]['cel']['expression'])
        self.assertEqual([c['name'] for c in pod['spec']['containers']], ['main'])
        helper = worker['experimental']['checkpoint']['job']['podTemplate']['spec']['containers'][0]
        self.assertEqual(helper['name'], 'capture-keepalive')
        self.assertNotIn('claims', helper['resources'])
        self.assertEqual(helper['env'][0]['value'], 'void')

    def test_capture_job_must_retain_helper_but_capture_main_only(self):
        helper = {'name': 'capture-keepalive', 'resources': {'requests': {'cpu': '25m'}}}
        job = {'spec': {'podSnapshotTemplate': {'targetContainers': ['main']},
                       'podTemplate': {'spec': {'containers': [{'name': 'main'}, helper]}}}}
        subject.validate_capture_layout(job)
        no_helper = copy.deepcopy(job)
        no_helper['spec']['podTemplate']['spec']['containers'] = [{'name': 'main'}]
        with self.assertRaisesRegex(ValueError, 'lacks.*helper'):
            subject.validate_capture_layout(no_helper)
        captures_helper = copy.deepcopy(job)
        captures_helper['spec']['podSnapshotTemplate']['targetContainers'].append('capture-keepalive')
        with self.assertRaisesRegex(ValueError, 'capture only main'):
            subject.validate_capture_layout(captures_helper)
        gpu_helper = copy.deepcopy(job)
        gpu_helper['spec']['podTemplate']['spec']['containers'][1]['resources']['claims'] = [{'name': 'gpu-main'}]
        with self.assertRaisesRegex(ValueError, 'CPU-only'):
            subject.validate_capture_layout(gpu_helper)

    def test_module_path_is_configurable(self):
        lock, settings = inputs()
        settings['module_path'] = '/another/runtime/snapshot.py'
        _, graph = subject.render_objects('dynamo-ft-unit-test', lock, settings)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(worker['podTemplate']['spec']['containers'][0]['volumeMounts'][-1]['mountPath'], settings['module_path'])

    def test_rejects_ambiguous_or_duplicate_gpu_identity(self):
        lock, settings = inputs()
        for uuids in (settings['gpu_uuids'][:1], settings['gpu_uuids'][:1] * 2, ['gpu-1', 'gpu-3']):
            with self.subTest(uuids=uuids), self.assertRaises(ValueError):
                subject.render_objects('dynamo-ft-unit-test', lock, {**settings, 'gpu_uuids': uuids})


class Guards(unittest.TestCase):
    def test_nvme_run_refuses_plain_verification_without_staging_callback(self):
        class Run:
            state = {'snapshot_dgd_storage_gate': 'nvme'}
        with self.assertRaisesRegex(ValueError, 'NVMe staging callback'):
            subject.checkpoint_state(Run(), {})

    def test_storage_gate_precedes_source_release_and_blocks_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            class Run:
                path = Path(temp)
                ns = 'dynamo-ft-unit-test'
                state = {'snapshot_dgd_uid': 'dgd', 'snapshot_job_uid': 'job',
                         'capture_logs_saved': 'already'}
                def get(self, *args):
                    return content
            ready = {'conditions': [{'type': 'Ready', 'status': 'True'}]}
            graph = {'metadata': {'name': subject.GRAPH, 'uid': 'dgd',
                'labels': {'feature-test-run': Run.ns}}, 'status': {'checkpoints': {
                subject.COMPONENT: {'checkpointName': 'capture', 'ready': True}}}}
            job = {'metadata': {'name': 'capture', 'uid': 'job'}}
            snapshot = {'metadata': {'name': 'capture'},
                'status': {**ready, 'boundSnapshotContentName': 'content'}}
            content = {'metadata': {'uid': 'content'}, 'status': ready}
            data = {'dgd': {'items': [graph]}, 'snapshotjobs': {'items': [job]},
                'pods': {'items': []}, 'podsnapshots': {'items': [snapshot]}}
            events = []
            def gate(*args):
                self.assertIs(args[1], snapshot)
                self.assertIs(args[2], content)
                events.append('storage')
            with patch.object(subject, 'owned_checkpoint_job'), patch.object(subject, 'validate_capture_layout'), \
                    patch.object(subject, 'finish_source', side_effect=lambda *a: events.append('release')):
                subject.checkpoint_state(Run(), data, gate)
                self.assertEqual(events, ['storage', 'release'])
                events.clear()
                def failed(*args):
                    raise ValueError('staging failed')
                with self.assertRaisesRegex(ValueError, 'staging failed'):
                    subject.checkpoint_state(Run(), data, failed)
                self.assertEqual(events, [])
                content['status'] = {}
                subject.checkpoint_state(Run(), data, gate)
                self.assertEqual(events, [])

    def test_criu_source_exit_137_does_not_preempt_pending_publication(self):
        class Run:
            ns = 'dynamo-ft-unit-test'
            state = {'snapshot_dgd_uid': 'dgd', 'snapshot_job_uid': 'job'}
        graph = {'metadata': {'name': subject.GRAPH, 'uid': 'dgd',
            'labels': {'feature-test-run': Run.ns}},
            'status': {'checkpoints': {subject.COMPONENT: {'checkpointName': 'capture'}}}}
        job = {'metadata': {'name': 'capture', 'uid': 'job'}}
        # Both the passing v3 source and this upstream source were killed by
        # CRIU at dump completion, before the durable EFS artifact became Ready.
        pod = {'metadata': {'name': 'source', 'uid': 'source-uid',
            'labels': {'nvidia.com/snapshot-job': 'capture'}},
            'spec': {'containers': [{'name': 'main'}, {'name': 'capture-keepalive'}]},
            'status': {'phase': 'Running', 'containerStatuses': [
                {'name': 'main', 'state': {'terminated': {'exitCode': 137, 'reason': 'Error'}}},
                {'name': 'capture-keepalive', 'state': {'running': {}}}]}}
        data = {'dgd': {'items': [graph]}, 'snapshotjobs': {'items': [job]},
            'pods': {'items': [pod]}, 'podsnapshots': {'items': []}}
        with patch.object(subject, 'owned_checkpoint_job'), patch.object(subject, 'validate_capture_layout'):
            self.assertEqual(subject.checkpoint_state(Run(), data), (graph, None, None))
            job['status'] = {'conditions': [{'type': 'Failed', 'status': 'True'}]}
            with self.assertRaisesRegex(RuntimeError, 'checkpoint capture failed'):
                subject.checkpoint_state(Run(), data)

    def test_foreign_lease_refuses_before_any_cluster_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            lease = Path(temp) / 'lease'; lease.mkdir()
            subject.write_json(lease / 'owner.json', {'agent': 'someone-else', 'run': temp})
            class Run:
                path = Path(temp)
                def k(self, *a, **kw):
                    raise AssertionError('No cluster calls with foreign lease')
            import demos.common.runtime as workshop_demo
            with patch.object(workshop_demo, 'LEASE', lease), self.assertRaisesRegex(RuntimeError, 'Foreign GPU lease'):
                subject.cleanup(Run(), {})
            self.assertTrue((lease / 'owner.json').exists())

    def test_patch_must_be_immutable_and_match_exact_source(self):
        lock, settings = inputs()
        settings['patch_sha256'] = subject.sha256(b'actual source')
        class Run:
            ns = 'dynamo-ft-unit-test'
            def get(self, *a):
                return {'metadata': {'name': 'patch', 'labels': {'feature-test-run': self.ns}},
                    'immutable': False, 'data': {'snapshot.py': 'actual source'}}
        with self.assertRaisesRegex(ValueError, 'immutable'):
            subject.check_patch(Run(), {'settings': settings})

    def test_helper_cannot_stop_before_durable_snapshot_ready(self):
        class Run:
            def k(self, *a, **kw):
                raise AssertionError('No mutation before Ready')
        with self.assertRaisesRegex(ValueError, 'durable'):
            subject.finish_source(Run(), {'pods': []}, {}, {'status': {}})

    def test_helper_finish_checks_source_job_ownership(self):
        class Run:
            ns = 'dynamo-ft-unit-test'
            def k(self, *a, **kw):
                raise AssertionError('Must not signal foreign owner')
        job = {'metadata': {'name': 'capture'}, 'status': {'sourceJobUID': 'expected'}}
        pod = {'metadata': {'name': 'source', 'uid': 'p', 'labels': {
            'feature-test-run': Run.ns, 'nvidia.com/snapshot-job': 'capture'},
            'ownerReferences': [{'kind': 'Job', 'uid': 'foreign'}]}, 'status': {'phase': 'Running'}}
        snapshot = {'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            subject.finish_source(Run(), {'pods': {'items': [pod]}}, job, snapshot)

    def test_retained_checkpoint_ownership_uses_exact_dgd_uid(self):
        class Run:
            ns = 'dynamo-ft-unit-test'
            state = {'snapshot_dgd_uid': 'dgd-uid'}
        job = {'metadata': {'name': 'checkpoint', 'namespace': Run.ns, 'uid': 'job-uid',
            'labels': {'nvidia.com/dynamo-graph-deployment-name': subject.GRAPH,
                       'nvidia.com/dynamo-component': subject.COMPONENT},
            'annotations': {'nvidia.com/dynamo-checkpoint-owner-uid': 'dgd-uid'}}}
        self.assertIs(subject.owned_checkpoint_job(Run(), job), job)
        changed = copy.deepcopy(job)
        changed['metadata']['annotations']['nvidia.com/dynamo-checkpoint-owner-uid'] = 'other-dgd'
        with self.assertRaisesRegex(ValueError, 'recorded DGD'):
            subject.owned_checkpoint_job(Run(), changed)

    def test_ownership_check_rejects_label_only_lookalike(self):
        with self.assertRaisesRegex(ValueError, 'unowned'):
            subject.owned({'metadata': {'name': 'worker', 'labels': {'feature-test-run': 'other'}}}, 'dynamo-ft-unit')

    def test_controller_lineage_requires_exact_owner_uids(self):
        pod = {'metadata': {'ownerReferences': [{'controller': True, 'kind': 'ReplicaSet', 'name': 'rs', 'uid': 'rs-uid'}]}}
        class Run:
            ns = 'dynamo-ft-unit-test'
            state = {'snapshot_dgd_uid': 'dgd-uid'}
            def get(self, *a):
                return {'metadata': {'uid': 'rs-uid', 'ownerReferences': [
                    {'controller': True, 'kind': 'DynamoGraphDeployment', 'name': subject.GRAPH, 'uid': 'dgd-uid'}]}}
        self.assertEqual(subject.controller_lineage(Run(), pod)[-1]['uid'], 'dgd-uid')
        changed = copy.deepcopy(pod)
        changed['metadata']['ownerReferences'][0]['uid'] = 'different-rs'
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            subject.controller_lineage(Run(), changed)

    def test_replace_refuses_a_reused_pod_name(self):
        with tempfile.TemporaryDirectory() as temp:
            subject.write_json(Path(temp) / 'initial-identity.json', {'worker_name': 'worker', 'worker_uid': 'old'})
            class Run:
                path = Path(temp)
                ns = 'dynamo-ft-unit-test'
                state = {}
                def get(self, *a):
                    return {'metadata': {'name': 'worker', 'uid': 'new', 'labels': {'feature-test-run': self.ns}}}
                def k(self, *a, **kw):
                    raise AssertionError('Must refuse deletion on name reuse')
            with patch.object(subject, 'require_lease'), self.assertRaisesRegex(ValueError, 'changed before deletion'):
                subject.replace(Run(), {})

    def test_recovery_rejects_changed_frontend_or_artifact(self):
        lock, settings = inputs()
        class Run:
            ns = 'dynamo-ft-unit-test'
            state = {'snapshot_dgd_uid': 'dgd-uid'}
        def pod(name, uid, worker=False):
            conditions = [{'type': 'Ready', 'status': 'True', 'lastTransitionTime': '2026-11-04T08:00:41Z'}]
            if worker:
                conditions.append({'type': 'nvidia.com/Restored', 'status': 'True', 'lastTransitionTime': '2026-11-04T08:00:37Z'})
            return {'metadata': {'name': name, 'uid': uid, 'creationTimestamp': '2026-11-04T08:00:00Z',
                'labels': {'feature-test-run': Run.ns}, 'annotations': {'nvidia.com/restore-from': 'checkpoint'}},
                'spec': {'nodeName': settings['node']}, 'status': {'conditions': conditions,
                    'containerStatuses': [{'name': 'main', 'imageID': lock['runtime_image'], 'restartCount': 0}]}}
        worker, front = pod('worker', 'first', True), pod('frontend', 'frontend')
        snapshot = {'metadata': {'name': 'checkpoint', 'uid': 'snapshot-uid'}}
        content = {'metadata': {'uid': 'content-uid'}, 'spec': {'source': {'podRef': {'uid': 'capture'}}}}
        service = {'metadata': {'name': 'service', 'uid': 'service-uid'}}
        with patch.object(subject, 'allocated_uuids', return_value=sorted(settings['gpu_uuids'])), \
                patch.object(subject, 'controller_lineage', return_value=[]):
            baseline = subject.validate_worker(Run(), {'settings': settings, 'model_lock': lock}, worker, snapshot, content, front, service)
            worker['metadata']['uid'] = 'replacement'
            changed = copy.deepcopy(front); changed['metadata']['uid'] = 'new-frontend'
            with self.assertRaisesRegex(ValueError, 'frontend_uid'):
                subject.validate_worker(Run(), {'settings': settings, 'model_lock': lock}, worker, snapshot, content, changed, service, baseline)
            altered = copy.deepcopy(content); altered['metadata']['uid'] = 'new-content'
            with self.assertRaisesRegex(ValueError, 'content_uid'):
                subject.validate_worker(Run(), {'settings': settings, 'model_lock': lock}, worker, snapshot, altered, front, service, baseline)


class Response(unittest.TestCase):
    def test_coding_result_checked_without_executing_it(self):
        self.assertIn('return a + b', subject.validate_coding_output('```python\ndef add(a, b):\n    return a + b\n```'))
        with self.assertRaises(ValueError):
            subject.validate_coding_output('def add(a, b):\n    return a - b')

    def test_nanosecond_timestamps_accept_python39_and_preserve_boundary(self):
        self.assertAlmostEqual(subject.elapsed('2026-11-04T08:00:00.123456789Z', '2026-11-04T08:00:41.123456999Z'), 41)

    def stream(self, error=False, done=True):
        chunks = [{'model': 'test-model', 'choices': [{'delta': {'content': 'def add(a, b):\n    return a + b'}, 'finish_reason': 'stop'}],
            'nvext': {'worker_id': {'decode_worker_id': 123}}}]
        if error:
            chunks.append({'error': {'message': 'failed'}})
        text = '\n'.join('data: ' + json.dumps(c) for c in chunks)
        if done:
            text += '\ndata: [DONE]\n'
        return io.BytesIO(text.encode())

    def test_stream_requires_finish_and_no_error_even_with_done(self):
        with patch.object(subject.urllib.request, 'urlopen', return_value=self.stream()):
            self.assertEqual(subject.coding_request('http://unused', 'test-model')['worker']['decode_worker_id'], 123)
        with patch.object(subject.urllib.request, 'urlopen', return_value=self.stream(error=True)), self.assertRaises(ValueError):
            subject.coding_request('http://unused', 'test-model')
        with patch.object(subject.urllib.request, 'urlopen', return_value=self.stream(done=False)), self.assertRaises(ValueError):
            subject.coding_request('http://unused', 'test-model')


class Cleanup(unittest.TestCase):
    def fake_run(self, path):
        class Run:
            ns = 'dynamo-ft-unit-test'
            state = {'snapshot_dgd_uid': 'dgd-uid', 'snapshot_job_uid': 'snapshot-job-uid'}
            def __init__(self):
                self.path = Path(path)
                self.events = []
                self.graph = {'metadata': {'name': subject.GRAPH, 'uid': 'dgd-uid', 'labels': {'feature-test-run': self.ns}}}
                self.snapshot = {'apiVersion': 'nvidia.com/v1alpha1', 'metadata': {
                    'name': 'capture', 'uid': 'snapshot-job-uid', 'namespace': self.ns,
                    'labels': {'nvidia.com/dynamo-graph-deployment-name': subject.GRAPH,
                               'nvidia.com/dynamo-component': subject.COMPONENT},
                    'annotations': {'nvidia.com/dynamo-checkpoint-owner-uid': 'dgd-uid'}},
                    'status': {'sourceJobUID': 'source-job-uid'}}
                self.source = {'apiVersion': 'batch/v1', 'metadata': {'name': 'source', 'uid': 'source-job-uid',
                    'ownerReferences': [{'kind': 'SnapshotJob', 'name': 'capture', 'uid': 'snapshot-job-uid'}]}}
            def get(self, *args):
                resource = args[1]
                values = {'snapshotjobs': [self.snapshot] if self.snapshot else [],
                          'jobs': [self.source] if self.source else [], 'pods': [], 'resourceclaims': []}
                return copy.deepcopy({'items': values[resource]})
            def k(self, *args, **kwargs):
                if args[0] == 'get':
                    obj = {'dgd': self.graph, 'job': self.source, 'snapshotjob': self.snapshot}[args[1]]
                    return subprocess.CompletedProcess(args, 0 if obj else 1, json.dumps(obj) if obj else '', '' if obj else 'NotFound')
                if args[0] == 'delete' and args[1] == 'dgd':
                    # Before any parent mutation the exact source ancestry must
                    # already be on disk, not reconstructed from orphaned refs.
                    plan = json.loads((self.path / 'cleanup-plan.json').read_text())
                    assert plan['source_jobs'][0]['metadata']['uid'] == 'source-job-uid'
                    self.events.append('delete-dgd'); self.graph = None
                elif args[0] == 'delete' and args[1] == '--raw':
                    options = json.loads(kwargs['input_text'])
                    if '/snapshotjobs/' in args[2]:
                        assert options['preconditions']['uid'] == self.snapshot['metadata']['uid']
                        assert options['propagationPolicy'] == 'Orphan'
                        self.events.append('orphan-snapshot')
                        # Model the actual Kubernetes behavior that caused a1's
                        # cleanup failure: orphaning strips the child ownerRef.
                        if self.source:
                            self.source['metadata']['ownerReferences'] = []
                        self.snapshot = None
                    else:
                        assert options['preconditions']['uid'] == self.source['metadata']['uid']
                        self.events.append('delete-source'); self.source = None
                elif args[0] != 'wait':
                    raise AssertionError(args)
                return subprocess.CompletedProcess(args, 0, '', '')
            def result(self, *args, **kwargs):
                self.events.append('passed')
        return Run()

    def test_cleanup_deletes_source_before_orphaning_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self.fake_run(temp)
            with patch.object(subject, 'require_lease'):
                subject.cleanup(run, {})
            self.assertLess(run.events.index('delete-source'), run.events.index('orphan-snapshot'))
            self.assertIsNone(run.source)
            plan = json.loads((Path(temp) / 'cleanup-plan.json').read_text())
            self.assertEqual(plan['source_jobs'][0]['metadata']['ownerReferences'][0]['uid'], 'snapshot-job-uid')

    def test_cleanup_resume_uses_recorded_ancestry_after_orphan_removed_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self.fake_run(temp)
            subject.cleanup_plan(run)
            run.graph = None
            # A parent deletion happened before an interruption. The source's
            # immutable UID is still the one proven in the saved cleanup plan.
            run.snapshot = None
            run.source['metadata']['ownerReferences'] = []
            with patch.object(subject, 'require_lease'):
                subject.cleanup(run, {})
            self.assertIsNone(run.source)
            self.assertIn('passed', run.events)

    def test_cleanup_saved_ancestry_does_not_authorize_a_reused_source_name(self):
        with tempfile.TemporaryDirectory() as temp:
            run = self.fake_run(temp)
            subject.cleanup_plan(run)
            run.graph = None
            run.snapshot = None
            run.source['metadata']['uid'] = 'foreign-new-uid'
            run.source['metadata']['ownerReferences'] = []
            with patch.object(subject, 'require_lease'), self.assertRaisesRegex(ValueError, 'reused'):
                subject.cleanup(run, {})
            self.assertIsNotNone(run.source)
            self.assertNotIn('delete-source', run.events)


class OfflineCachePreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.model_root = self.home / 'hub/models--example--Model'
        self.revision = '8a' * 20
        self.snapshot = self.model_root / 'snapshots' / self.revision
        self.snapshot.mkdir(parents=True)
        (self.snapshot / 'weights.safetensors').write_bytes(b'weights')
        for name, data in [('config.json', {}), ('tokenizer_config.json', {}),
                           ('model.safetensors.index.json', {'weight_map': {'tensor': 'weights.safetensors'}})]:
            (self.snapshot / name).write_text(json.dumps(data))
        self.lock = {'model': 'example/Model', 'revision': self.revision, 'checkpoint_weight_files': 1,
            'model_metadata_sha256': {name: subject.sha256((self.snapshot / name).read_bytes())
                for name in ('config.json', 'tokenizer_config.json', 'model.safetensors.index.json')}}
        self.calls = []

    def ref(self, revision=None):
        path = self.model_root / 'refs/main'
        path.parent.mkdir(exist_ok=True)
        path.write_text((revision or self.revision) + '\n')

    def run_probe(self, resolved=None, offline='1'):
        async def fetch_model(name):
            self.calls.append(name)
            return str(resolved or self.snapshot)
        dynamo = types.ModuleType('dynamo'); dynamo.__path__ = []
        common = types.ModuleType('dynamo.common'); common.__path__ = []
        resolver = types.ModuleType('dynamo.common.model_fetch'); resolver.fetch_model = fetch_model
        dynamo.common = common; common.model_fetch = resolver
        output = io.StringIO()
        with patch.dict(os.environ, {'HF_HOME': str(self.home), 'HF_HUB_OFFLINE': offline,
                'MODEL_LOCK': json.dumps(self.lock), 'EXPECTED_BYTES': '7'}), \
                patch.dict(sys.modules, {'dynamo': dynamo, 'dynamo.common': common,
                                        'dynamo.common.model_fetch': resolver}), \
                contextlib.redirect_stdout(output):
            exec(compile(subject.cache_probe_program(), '<offline-cache-probe>', 'exec'), {})
        return json.loads(output.getvalue())

    def test_missing_main_ref_fails_without_repair_or_resolver_call(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing metadata refs/main'):
            self.run_probe()
        self.assertFalse((self.model_root / 'refs/main').exists())
        self.assertEqual(self.calls, [])

    def test_wrong_main_ref_fails_even_when_locked_shards_are_present(self):
        self.ref('da5b' * 10)
        with self.assertRaisesRegex(RuntimeError, 'differs from locked revision'):
            self.run_probe()
        self.assertEqual(self.calls, [])

    def test_resolver_fallback_is_rejected_even_with_correct_main_ref(self):
        self.ref()
        alternate = self.model_root / 'snapshots' / ('da5b' * 10)
        alternate.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'unexpected snapshot'):
            self.run_probe(resolved=alternate)
        self.assertEqual(self.calls, [self.lock['model']])

    def test_passing_preflight_records_actual_offline_resolution(self):
        self.ref()
        receipt = {'status': 'passed', **self.run_probe()}
        self.assertEqual(receipt['metadata_ref'], self.revision)
        self.assertEqual(receipt['resolved_model_path'], str(self.snapshot))
        self.assertEqual(receipt['offline'], '1')
        self.assertEqual(self.calls, [self.lock['model']])
        subject.validate_cache_receipt(receipt, self.lock, str(self.home))

    def test_online_policy_is_rejected_before_metadata_resolver(self):
        self.ref()
        with self.assertRaisesRegex(AssertionError, 'must run offline'):
            self.run_probe(offline='0')
        self.assertEqual(self.calls, [])

    def test_old_shard_only_receipt_cannot_authorize_gpu_deployment(self):
        old = {'status': 'passed', 'model': self.lock['model'], 'revision': self.revision,
               'weight_files': 1, 'weight_bytes': 7}
        with self.assertRaisesRegex(ValueError, 'exact offline metadata resolution'):
            subject.validate_cache_receipt(old, self.lock, str(self.home))


if __name__ == '__main__':
    unittest.main()
