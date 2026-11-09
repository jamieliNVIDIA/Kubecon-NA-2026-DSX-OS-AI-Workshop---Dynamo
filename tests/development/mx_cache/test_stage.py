"""CPU native-stream and frozen graph contract checks without cluster access."""
from tests.support import ROOT
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import scripts.development.mx_cache.stage as staging
import scripts.development.mx_cache.workflow as cache


def fixture_spec():
    payloads = {'config.json': b'{"model_type":"test"}',
                'assets/vocab.json': b'{"v":1}', 'model.safetensors': b'trusted weight bytes',
                'model.safetensors.index.json': b'{"weight_map":{"layer":"model.safetensors"}}'}
    spec = {'schema': 1, 'id': 'stage-test', 'model': 'example/model', 'revision': 'a' * 40,
            'server_address': '192.168.0.1:8001', 'server_pod_uid': 'producer-uid',
            'seed_receipt_sha256': 'b' * 64, 'cache_limit_bytes': 96 * 1024**3,
            'files': {n: {'bytes': len(p), 'sha256': hashlib.sha256(p).hexdigest(),
                          'weight': n.endswith('.safetensors')} for n, p in payloads.items()}}
    rows, source_files = [], {}
    for name, data in payloads.items():
        git = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        row = {'type': 'file', 'path': name, 'size': len(data), 'oid': git}
        source = dict(spec['files'][name], hf_git_oid=git, hf_xet_storage_key=None)
        if source['weight']:
            sha = source['sha256']
            xet = hashlib.sha256(b'xet:' + data).hexdigest()
            row.update(lfs={'oid': sha, 'size': len(data)}, xetHash=xet)
            source.update(hf_data_hash_kind='sha256-lfs', hf_data_hash=sha,
                          hf_xet_storage_key=xet, source_blob_id=xet)
        else:
            source.update(hf_data_hash_kind='sha1-git-blob', hf_data_hash=git, source_blob_id=git)
        rows.append(row)
        source_files[name] = source
    tree_raw = json.dumps(rows)
    tree_sha = hashlib.sha256(tree_raw.encode()).hexdigest()
    seed = {'schema': 1, 'status': 'passed', 'model': spec['model'], 'revision': spec['revision'],
            'hf_manifest_sha256': tree_sha, 'hf_manifest_entries': len(rows), 'files': source_files,
            'hf_manifest_url': 'https://huggingface.co/api/models/' + spec['model'] + '/tree/' + spec['revision'] + '?recursive=true&expand=false&limit=1000'}
    seed_raw = json.dumps(seed)
    spec.update(seed_source_receipt_json=seed_raw, hf_manifest_json=tree_raw, hf_manifest_sha256=tree_sha,
                seed_receipt_sha256=hashlib.sha256(seed_raw.encode()).hexdigest())
    return spec, payloads


class FakeClient:
    def __init__(self, spec, payloads):
        self.spec, self.payloads = spec, payloads
        self.wrong_revision = False
        self.extra_manifest = False

    def ensure_downloaded(self, model, **kwargs):
        return 'c' * 40 if self.wrong_revision else self.spec['revision']

    def list_files(self, model, **kwargs):
        result = {n: len(p) for n, p in self.payloads.items()}
        if self.extra_manifest: result['unexpected'] = 1
        return result

    def _stream_into(self, model, provider, paths, expected, sink, **kwargs):
        for name in paths:
            sink.begin_file(name)
            sink.write(self.payloads[name])
            sink.end_file()
        return self.spec['revision']


def producer_pod():
    return {'metadata': {'namespace': 'dynamo-ft-cache', 'name': 'server', 'uid': 'producer-uid'},
            'spec': {'nodeName': 'node', 'containers': [{'name': 'server', 'image': cache.SERVER_IMAGE}]},
            'status': {'phase': 'Running', 'podIP': '192.168.0.1',
                       'conditions': [{'type': 'Ready', 'status': 'True'}],
                       'containerStatuses': [{'name': 'server', 'ready': True, 'containerID': 'containerd://server-1',
                                              'imageID': cache.SERVER_IMAGE, 'state': {'running': {'startedAt': 'now'}}}],
                       'initContainerStatuses': [{'name': 'seed', 'containerID': 'containerd://seed-1',
                                                  'state': {'terminated': {'exitCode': 0}}}]}}


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.spec, self.payloads = fixture_spec()

    def run_stage(self, client=None, target='hf'):
        with contextlib.redirect_stdout(io.StringIO()):
            return staging.stage(self.spec, self.path / target,
                                 client or FakeClient(self.spec, self.payloads), 0, resource_gate=lambda *_: {})

    def test_complete_stream_has_exact_all_file_hashes_and_internal_links(self):
        result = self.run_stage()
        self.assertEqual(result['files'], self.spec['files'])
        self.assertFalse(result['cuda_initialized'])
        for name, payload in self.payloads.items():
            target = self.path / 'hf/hub/models--example--model/snapshots' / self.spec['revision'] / name
            self.assertEqual(target.read_bytes(), payload)
            self.assertTrue(target.resolve().is_relative_to((self.path / 'hf').resolve()))
        with self.assertRaisesRegex(ValueError, 'not fresh'): self.run_stage()

    def test_wrong_revision_extra_manifest_and_bad_bytes_never_publish(self):
        for case in ('revision', 'manifest', 'bytes'):
            with self.subTest(case=case):
                client = FakeClient(self.spec, dict(self.payloads))
                if case == 'revision': client.wrong_revision = True
                if case == 'manifest': client.extra_manifest = True
                if case == 'bytes': client.payloads['model.safetensors'] = b'wrongxx weight bytes'
                with self.assertRaises(ValueError): self.run_stage(client, case)
                self.assertFalse((self.path / case / 'hub/models--example--model').exists())
                self.assertFalse((self.path / case / 'mx-dev-cache-stage.json').exists())

    def test_unsafe_paths_and_bad_weight_type_rejected(self):
        for name in ('../escape', '/absolute', 'a/../b', './relative'):
            spec = copy.deepcopy(self.spec)
            spec['files'][name] = dict(next(iter(spec['files'].values())))
            with self.assertRaises(ValueError): staging.validate_spec(spec)
        spec = copy.deepcopy(self.spec)
        spec['files']['config.json']['weight'] = 1
        with self.assertRaises(ValueError): staging.validate_spec(spec)

    def qualification(self):
        cpu = self.run_stage()
        image = 'runtime@sha256:' + 'f' * 64
        source_hash = cache.digest(ROOT / 'scripts/development/mx_cache/stage.py')
        producer = cache.producer_identity(producer_pod())
        plan = {'stage_spec': self.spec, 'producer': producer, 'runtime_image': image,
                'stage_source_sha256': source_hash, 'namespace': 'dynamo-ft-stage', 'node': 'node'}
        main = cache.stage_init(self.spec, image, '/local-hf')
        main['name'] = 'stage'
        cm = cache.stage_config_map('dynamo-ft-stage', self.spec)
        cm['metadata']['uid'] = 'cm-uid'
        pod = {'metadata': {'namespace': 'dynamo-ft-stage', 'name': 'stage', 'uid': 'cpu-uid',
                            'labels': {'mx-development-run': self.spec['id']}},
               'spec': {'nodeName': 'node', 'containers': [main], 'restartPolicy': 'Never',
                        'automountServiceAccountToken': False, 'volumes': cache.stage_volumes(cm)},
               'status': {'phase': 'Succeeded', 'containerStatuses': [{'name': 'stage', 'containerID': 'containerd://cpu',
                          'imageID': image, 'restartCount': 0, 'state': {'terminated': {'exitCode': 0}}}]}}
        return {'schema': 1, 'kind': 'mx-dev-cache-qualification', 'status': 'passed',
                'stage_spec': self.spec, 'producer': producer,
                'stage_source_sha256': source_hash, 'cpu_probe_plan': plan, 'cpu_stage_pod': pod,
                'cpu_bootstrap': cm, 'cpu_bootstrap_identity': cache.cpu_bootstrap_identity(plan, cm),
                'cpu_stage_identity': cache.cpu_stage_identity(plan, pod),
                'cpu_stage_receipt_sha256': 'd' * 64, 'cpu_stage_receipt_canonical_sha256': cache.canonical_digest(cpu),
                'cpu_stage_receipt': cpu, 'cpu_probe_plan_sha256': 'e' * 64}

    def graph(self):
        return {'metadata': {'namespace': 'dynamo-ft-shadow'}, 'spec': {'components': [
            {'name': 'frontend', 'type': 'frontend', 'podTemplate': {'spec': {'containers': [{'name': 'main'}]}}},
            {'name': 'agg', 'type': 'worker', 'podTemplate': {'spec': {
                'volumes': [{'name': 'source', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}],
                'containers': [{'name': 'main', 'image': 'runtime@sha256:test',
                                'args': ['--model', self.spec['model'], '--revision', self.spec['revision'], '--load-format', 'gms'],
                                'env': [{'name': 'HF_HOME', 'value': cache.HF_HOME}],
                                'resources': {'requests': {'memory': '128Gi', 'nvidia.com/gpu': '2'},
                                              'limits': {'memory': '256Gi', 'nvidia.com/gpu': '2'}},
                                'volumeMounts': [{'name': 'source', 'mountPath': '/model-cache'}]}]}}}]}}

    def test_frozen_graph_roundtrip_and_long_candidate_id(self):
        qualification = self.qualification()
        qpath = self.path / 'qualification.json'
        qpath.write_text(json.dumps(qualification))
        baseline = self.graph()
        original = copy.deepcopy(baseline)
        candidate = 'overnight-shadow-super-vl-20261105-full-a3'
        graph, config_map, receipt = cache.apply_candidate_cache(baseline, qpath, candidate_id=candidate)
        self.assertEqual(baseline, original)
        self.assertEqual(graph['spec']['components'][0], baseline['spec']['components'][0])
        self.assertLessEqual(len(receipt['id']), 36)
        worker = graph['spec']['components'][1]['podTemplate']['spec']['containers'][0]
        self.assertEqual(worker['args'], baseline['spec']['components'][1]['podTemplate']['spec']['containers'][0]['args'])
        self.assertEqual(worker['resources']['requests']['nvidia.com/gpu'], '2')
        result = cache.validate_candidate_cache(graph, qpath, config_map, receipt, candidate_id=candidate)
        self.assertEqual(result['status'], 'verified')
        for case in ('bootstrap', 'graph', 'receipt', 'producer', 'cpu'):
            g, cm, r = copy.deepcopy(graph), copy.deepcopy(config_map), copy.deepcopy(receipt)
            q = copy.deepcopy(qualification)
            if case == 'bootstrap': cm['data']['stage.py'] += '\n# changed'
            if case == 'graph': g['spec']['components'][1]['podTemplate']['spec']['containers'][0]['args'].append('--bad')
            if case == 'receipt': r['file_inventory']['config.json']['sha256'] = 'f' * 64
            if case == 'producer': q['producer']['uid'] = 'other'
            if case == 'cpu': q['cpu_stage_receipt']['server_address'] = '192.168.1.9:8001'
            qpath.write_text(json.dumps(q))
            with self.subTest(case=case), self.assertRaises(ValueError):
                cache.validate_candidate_cache(g, qpath, cm, r, candidate_id=candidate)
        qpath.write_text(json.dumps(qualification))

    def test_current_producer_generation_fence(self):
        qualification = self.qualification()
        pod = producer_pod()
        cache.validate_producer_snapshot(qualification, pod)
        for case in ('uid', 'container', 'ip', 'unready'):
            changed = copy.deepcopy(pod)
            if case == 'uid': changed['metadata']['uid'] = 'other'
            if case == 'container': changed['status']['containerStatuses'][0]['containerID'] = 'containerd://other'
            if case == 'ip': changed['status']['podIP'] = '192.168.1.1'
            if case == 'unready': changed['status']['containerStatuses'][0]['ready'] = False
            with self.subTest(case=case), self.assertRaises(ValueError): cache.validate_producer_snapshot(qualification, changed)

    def test_stage_receipt_matches_target_patch_not_only_pass_flag(self):
        qualification = self.qualification()
        graph, cm, patch = cache.apply_candidate_cache(self.graph(), qualification, candidate_id='long-full-candidate-id')
        spec = json.loads(cm['data']['stage-spec.json'])
        with contextlib.redirect_stdout(io.StringIO()):
            target = staging.stage(spec, self.path / 'target', FakeClient(spec, self.payloads), 0, resource_gate=lambda *_: {})
        cache.validate_stage_receipt(target, patch)
        target['files']['assets/vocab.json']['sha256'] = 'f' * 64
        with self.assertRaises(ValueError): cache.validate_stage_receipt(target, patch)


if __name__ == '__main__':
    unittest.main()
