"""Owned cache lifecycle and complete init evidence in the Shadow composition."""
from tests.support import ROOT
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.source_paths import source_path
import demos.shadow.composed as full
import scripts.development.mx_cache.workflow as cache
import tests.development.mx_cache.test_stage as cache_fixtures


class CacheIntegrationTests(unittest.TestCase):
    def fixture(self):
        fixture = cache_fixtures.StageTests(); fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        qualification = fixture.qualification()
        path = fixture.path / 'overnight-shadow-super-vl-20261105-full-a3'
        path.mkdir()
        qpath = path / full.DEV_CACHE_INPUTS[0]
        qpath.write_text(json.dumps(qualification))
        graph, cm, receipt = cache.apply_candidate_cache(fixture.graph(), qpath, candidate_id=path.name)
        full.write(path / 'deployment.json', graph)
        full.write(path / full.DEV_CACHE_INPUTS[1], cm)
        full.write(path / full.DEV_CACHE_INPUTS[2], receipt)
        sources = {name: full.ui.digest(source_path(name, root=ROOT)) for name in full.DEV_CACHE_SOURCES}
        spec = {'inputs': {name: full.ui.digest(path / name) for name in full.DEV_CACHE_INPUTS},
            'source_snapshot': sources,
            'dev_cache': {'schema': 1, 'candidate_id': path.name, 'source_sha256': sources,
                **{key: full.ui.digest(path / name) for name, key in zip(full.DEV_CACHE_INPUTS,
                    ('qualification_sha256', 'bootstrap_sha256', 'receipt_sha256'))}}}
        demo = object.__new__(full.ComposedShadowDemo)
        demo.path, demo.ns, demo.spec = path, cm['metadata']['namespace'], spec
        image = qualification['cpu_probe_plan']['runtime_image']
        state = {'checks': {}, 'model_lock': {'runtime_image': image}, 'shadow_dev_cache_bootstrap_uid': 'bootstrap-uid'}
        current_cm = copy.deepcopy(cm); current_cm['metadata']['uid'] = 'bootstrap-uid'
        calls = []
        def result(name, status, **details): state['checks'][name] = dict(status=status, **details)
        def get(*args):
            calls.append(('get', args))
            if args[1] == 'pod': return cache_fixtures.producer_pod()
            if args[1] in ('pods', 'resourceclaims'): return {'items': []}
            if args[1] == 'configmap': return copy.deepcopy(current_cm)
            raise AssertionError(args)
        run = SimpleNamespace(state=state, result=result, get=get, save=lambda: None,
            apply=lambda objects: calls.append(('apply', objects)))
        demo.run = run
        binding = (qualification, cm, receipt)
        demo.cache_binding = lambda: binding
        target = copy.deepcopy(qualification['cpu_stage_receipt'])
        target.update(id=receipt['id'], stage_spec_sha256=receipt['stage_spec_sha256'], hf_home=receipt['hf_home'])
        pod = {'metadata': {'name': 'worker', 'uid': 'worker-uid'},
            'spec': {'initContainers': [{'name': 'mx-dev-cache-stage', 'image': image}]},
            'status': {'initContainerStatuses': [{'name': 'mx-dev-cache-stage', 'containerID': 'containerd://init',
                'imageID': image, 'restartCount': 0, 'state': {'terminated': {'exitCode': 0}}}]}}
        def k(*args, **kwargs):
            calls.append(('k', args))
            if args[0] == 'logs':
                return SimpleNamespace(returncode=0, stderr='', stdout='progress\nMX_DEV_CACHE_STAGE=' + json.dumps(target) + '\n')
            if args[0] == 'get': return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(current_cm))
            if args[0] == 'delete': return SimpleNamespace(returncode=0, stderr='', stdout='deleted')
            raise AssertionError(args)
        run.k = k
        return SimpleNamespace(**locals())

    def test_static_frozen_binding_is_read_only_and_rejects_hash_metadata_source_or_optional_drift(self):
        fixture = self.fixture()
        result = full.validate_candidate_cache(fixture.path, fixture.spec)
        self.assertEqual(result['status'], 'verified')
        for case in ('missing-metadata', 'missing-input', 'extra-metadata', 'source', 'candidate', 'bytes'):
            spec = copy.deepcopy(fixture.spec)
            with self.subTest(case=case):
                if case == 'missing-metadata': del spec['dev_cache']
                elif case == 'missing-input': del spec['inputs'][full.DEV_CACHE_INPUTS[0]]
                elif case == 'extra-metadata': spec['dev_cache']['unknown'] = True
                elif case == 'source': spec['source_snapshot'][full.DEV_CACHE_SOURCES[0]] = 'changed'
                elif case == 'candidate': spec['dev_cache']['candidate_id'] = 'other'
                else: (fixture.path / full.DEV_CACHE_INPUTS[1]).write_text('{}')
                with patch.object(full, 'Run', side_effect=AssertionError('Static gate may not construct Run')):
                    with self.assertRaises(ValueError): full.validate_candidate_cache(fixture.path, spec)
        self.assertIsNone(full.validate_candidate_cache(fixture.path, {'inputs': {}}))

    def test_complete_once_only_init_receipt_binds_pod_image_files_and_unchanged_source(self):
        fixture = self.fixture()
        self.assertTrue(fixture.demo.collect_cache_stage(fixture.pod))
        proof = fixture.state['checks']['shadow-full-dev-cache-stage']
        self.assertEqual(proof['status'], 'passed')
        self.assertEqual(proof['pod_uid'], 'worker-uid')
        self.assertEqual(proof['source_producer'], fixture.qualification['producer'])
        self.assertTrue((fixture.path / 'dev-cache-init.log').is_file())
        self.assertEqual(json.loads((fixture.path / 'dev-cache-stage-result.json').read_text())['files'],
                         fixture.qualification['stage_spec']['files'])
        self.assertTrue(fixture.demo.collect_cache_stage(fixture.pod))
        replaced = copy.deepcopy(fixture.pod); replaced['metadata']['uid'] = 'new-worker'
        with self.assertRaises(ValueError): fixture.demo.collect_cache_stage(replaced)

    def test_incomplete_corrupt_restarted_or_different_source_never_qualifies_stage(self):
        for case in ('running', 'bad-byte-hash', 'wrong-home', 'exit', 'restart', 'image', 'source', 'no-marker'):
            with self.subTest(case=case):
                fixture = self.fixture()
                status = fixture.pod['status']['initContainerStatuses'][0]
                if case == 'running': status['state'] = {'running': {}}
                elif case == 'bad-byte-hash': fixture.target['files']['config.json']['sha256'] = '0' * 64
                elif case == 'wrong-home': fixture.target['hf_home'] = '/wrong'
                elif case == 'exit': status['state']['terminated']['exitCode'] = 1
                elif case == 'restart': status['restartCount'] = 1
                elif case == 'image': status['imageID'] = 'other-image'
                elif case == 'source':
                    changed = cache_fixtures.producer_pod(); changed['metadata']['uid'] = 'other-producer'
                    fixture.run.get = lambda *_: changed
                else:
                    fixture.run.k = lambda *_, **__: SimpleNamespace(returncode=0, stderr='', stdout='no full receipt\n')
                if case == 'running': self.assertFalse(fixture.demo.collect_cache_stage(fixture.pod))
                else:
                    with self.assertRaises(ValueError): fixture.demo.collect_cache_stage(fixture.pod)
                    self.assertTrue((fixture.path / 'dev-cache-init.log').is_file())
                self.assertNotIn('shadow-full-dev-cache-stage', fixture.state['checks'])

    def test_prepared_bootstrap_cannot_be_recreated_replaced_or_change_data(self):
        for case in ('valid', 'missing', 'uid', 'data'):
            with self.subTest(case=case):
                fixture = self.fixture()
                if case == 'missing':
                    fixture.run.k = lambda *_, **__: SimpleNamespace(returncode=1, stderr='NotFound', stdout='')
                elif case == 'uid': fixture.current_cm['metadata']['uid'] = 'replacement'
                elif case == 'data': fixture.current_cm['data']['stage.py'] += '\n# changed'
                if case == 'valid': fixture.demo.cache_bootstrap(require_existing=True)
                else:
                    with self.assertRaises(ValueError): fixture.demo.cache_bootstrap(require_existing=True)
                self.assertFalse(any(call[0] == 'apply' for call in fixture.calls))

    def test_bad_cache_gate_creates_no_run_or_config(self):
        fixture = self.fixture()
        fixture.qualification['status'] = 'failed'
        qpath = fixture.path / full.DEV_CACHE_INPUTS[0]
        qpath.write_text(json.dumps(fixture.qualification))
        full.write(fixture.path / 'runtime-overlay.json', {'data': {'workshop_descriptors.py': 'old'}})
        full.write(fixture.path / 'deployment.json', fixture.graph)
        candidate = fixture.path / 'new-candidate'
        with patch.object(full, 'qualified_basis', return_value=(SimpleNamespace(path=fixture.path),
                {'descriptor_identity': {}, 'overlay_sha256': 'old-overlay'}, {}, {})), \
                patch.object(full, 'reader_delta_inputs', return_value=('reviewed-reader', {}, {})), \
                patch.object(full, 'render_graph', return_value=fixture.graph), \
                patch.object(full, 'Run', side_effect=AssertionError('Run preceded cache validation')):
            with self.assertRaisesRegex(ValueError, 'Full passed CPU cache qualification'):
                full.freeze(candidate, fixture.path, dev_cache_qualification=qpath)
        self.assertFalse(candidate.exists())

    def test_live_producer_gate_precedes_gpu_intent_and_deployment(self):
        fixture = self.fixture()
        fixture.state['checks']['shadow-writer-cuda'] = {'status': 'passed', 'updated_at': 'earlier'}
        fixture.demo.args = SimpleNamespace(health_before=Path('health.json'))
        fixture.demo.check_inputs = lambda: None
        fixture.demo.source_released = lambda: None
        fixture.demo.acquire = lambda: None
        fixture.demo.cache_bootstrap = lambda **kwargs: None
        fixture.demo.cache_producer = lambda phase: (_ for _ in ()).throw(ValueError('Producer changed'))
        with patch.object(full.writer, 'health_copy', return_value={'observed_at': 'later'}):
            with self.assertRaisesRegex(ValueError, 'Producer changed'): fixture.demo.deploy()
        self.assertFalse((fixture.path / 'full-gpu-intent.json').exists())
        self.assertFalse(any(call[0] == 'apply' for call in fixture.calls))

    def test_cache_cleanup_happens_after_workloads_and_before_parent_lease_release(self):
        fixture = self.fixture()
        events = []
        fixture.demo.stop = lambda: events.append('stop')
        fixture.demo.cache_bootstrap = lambda **kwargs: events.append(('bootstrap', kwargs))
        with patch.object(full.presenter.ShadowDemo, 'cleanup', side_effect=lambda: events.append('parent-release')):
            fixture.demo.cleanup()
        self.assertEqual(events, ['stop', ('bootstrap', {'delete': True}), 'parent-release'])
        fixture = self.fixture(); events = []
        fixture.demo.stop = lambda: events.append('stop')
        fixture.demo.cache_bootstrap = lambda **kwargs: events.append('bootstrap')
        fixture.run.get = lambda *_: {'items': [object()]}
        with patch.object(full.time, 'monotonic', side_effect=[0.0, 181.0]), \
                patch.object(full.presenter.ShadowDemo, 'cleanup', side_effect=lambda: events.append('parent-release')):
            with self.assertRaises(RuntimeError): fixture.demo.cleanup()
        self.assertEqual(events, ['stop'])


if __name__ == '__main__': unittest.main()
