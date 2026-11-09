"""Independent cache-provenance negatives and tiny native-stream doubles."""
import contextlib
import copy
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import scripts.development.mx_cache.stage as stage
import scripts.development.mx_cache.workflow as cache
import tests.development.mx_cache.test_stage as author
import demos.shadow.composed as full
import tests.shadow.test_dev_cache as composed_author


class CacheReviewTests(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self):
        fixture = author.StageTests()
        fixture.setUp()
        try:
            with contextlib.redirect_stdout(io.StringIO()): qualification = fixture.qualification()
            yield fixture, qualification
        finally: fixture.doCleanups()

    def test_cpu_identity_rejects_claims_extra_containers_init_and_source_access(self):
        for case in ('claim', 'extra-gpu', 'init-gpu', 'hostpath', 'command', 'args', 'malformed-image'):
            with self.subTest(case=case), self.fixture() as (fixture, qualification):
                pod = copy.deepcopy(qualification['cpu_stage_pod'])
                plan = qualification['cpu_probe_plan']
                spec = pod['spec']; container = spec['containers'][0]
                if case == 'claim': spec['resourceClaims'] = [{'name': 'unexpected'}]
                elif case == 'extra-gpu': spec['containers'].append({'name': 'unexpected', 'resources': {'limits': {'nvidia.com/gpu': 1}}})
                elif case == 'init-gpu': spec['initContainers'] = [{'name': 'unexpected', 'resources': {'limits': {'nvidia.com/gpu': 1}}}]
                elif case == 'hostpath': spec.setdefault('volumes', []).append({'name': 'source', 'hostPath': {'path': '/source'}})
                elif case == 'command': container['command'] = ['python3', '-c', 'print("forged success")']
                elif case == 'args': container['args'] = ['--hf-home', '/shared-cache']
                elif case == 'malformed-image': pod['status']['containerStatuses'][0]['imageID'] = 'not-an-image-' + plan['runtime_image'].split('@')[-1]
                with self.assertRaises(ValueError): cache.cpu_stage_identity(plan, pod)

    def test_producer_address_and_generation_must_match_direct_qualified_pod(self):
        with self.fixture() as (fixture, qualification):
            for case in ('dns', 'other-ip', 'uid', 'container', 'seed-container', 'image-id'):
                with self.subTest(case=case):
                    q = copy.deepcopy(qualification)
                    if case == 'dns': q['stage_spec']['server_address'] = 'some-service.dynamo-ft.svc:8001'
                    elif case == 'other-ip': q['stage_spec']['server_address'] = '192.168.0.2:8001'
                    elif case == 'uid': q['stage_spec']['server_pod_uid'] = 'other'
                    elif case == 'container': q['producer']['container_id'] = ''
                    elif case == 'seed-container': q['producer']['seed_container_id'] = ''
                    elif case == 'image-id': q['producer']['image_id'] = 'not-an-image-' + cache.SERVER_IMAGE.split('@')[-1]
                    with self.assertRaises(ValueError): cache.validate_spec_producer(q['stage_spec'], q['producer'])
            old = qualification['producer']
            changed = author.producer_pod(); changed['status']['podIP'] = '192.168.0.2'
            with self.assertRaises(ValueError): cache.validate_producer_snapshot(qualification, changed)
            self.assertEqual(qualification['producer'], old)

    def test_cpu_and_producer_terminal_counts_require_exact_integer_zero(self):
        with self.fixture() as (fixture, qualification):
            for field in ('exitCode', 'restartCount'):
                pod = copy.deepcopy(qualification['cpu_stage_pod'])
                status = pod['status']['containerStatuses'][0]
                if field == 'exitCode': status['state']['terminated'][field] = False
                else: status[field] = False
                with self.subTest(field=field), self.assertRaises(ValueError):
                    cache.cpu_stage_identity(qualification['cpu_probe_plan'], pod)
            pod = author.producer_pod()
            pod['status']['initContainerStatuses'][0]['state']['terminated']['exitCode'] = False
            with self.assertRaises(ValueError): cache.producer_identity(pod)

    def test_composed_target_stage_rejects_boolean_status_and_malformed_image(self):
        for case in ('exit', 'restart', 'image'):
            with self.subTest(case=case):
                owner = composed_author.CacheIntegrationTests()
                try:
                    fixture = owner.fixture()
                    status = fixture.pod['status']['initContainerStatuses'][0]
                    if case == 'exit': status['state']['terminated']['exitCode'] = False
                    elif case == 'restart': status['restartCount'] = False
                    else: status['imageID'] = 'not-an-image-' + status['imageID'].split('@')[-1]
                    with self.assertRaises(ValueError): fixture.demo.collect_cache_stage(fixture.pod)
                    self.assertNotIn('shadow-full-dev-cache-stage', fixture.state['checks'])
                finally: owner.doCleanups()

    def test_prepared_composed_bootstrap_must_remain_immutable_and_owned(self):
        for case in ('mutable', 'uid', 'namespace', 'owner-label'):
            with self.subTest(case=case):
                owner = composed_author.CacheIntegrationTests()
                try:
                    fixture = owner.fixture()
                    if case == 'mutable': fixture.current_cm['immutable'] = False
                    elif case == 'uid': fixture.current_cm['metadata']['uid'] = 'replaced'
                    elif case == 'namespace': fixture.current_cm['metadata']['namespace'] = 'other'
                    else: fixture.current_cm['metadata']['labels']['feature-test-run'] = 'other'
                    with self.assertRaises(ValueError): fixture.demo.cache_bootstrap(require_existing=True)
                    self.assertFalse(any(call[0] == 'apply' or (call[0] == 'k' and call[1][0] == 'delete') for call in fixture.calls))
                finally: owner.doCleanups()

    def test_qualification_revalidates_all_cpu_fields_even_if_summary_hash_is_recomputed(self):
        for case in ('model', 'revision', 'address', 'pod', 'spec', 'seed', 'files', 'file-count', 'cuda'):
            with self.subTest(case=case), self.fixture() as (fixture, qualification):
                q = copy.deepcopy(qualification)
                cpu = q['cpu_stage_receipt']
                if case == 'model': cpu['model'] = 'other/model'
                elif case == 'revision': cpu['revision'] = 'f' * 40
                elif case == 'address': cpu['server_address'] = '192.168.0.2:8001'
                elif case == 'pod': cpu['server_pod_uid'] = 'other'
                elif case == 'spec': cpu['stage_spec_sha256'] = 'f' * 64
                elif case == 'seed': cpu['seed_receipt_sha256'] = 'f' * 64
                elif case == 'files': cpu['files']['config.json']['bytes'] = float(cpu['files']['config.json']['bytes'])
                elif case == 'file-count': cpu['file_count'] = float(cpu['file_count'])
                elif case == 'cuda': cpu['cuda_initialized'] = 0
                q['cpu_stage_receipt_canonical_sha256'] = cache.canonical_digest(cpu)
                with self.assertRaises(ValueError): cache.apply_candidate_cache(fixture.graph(), q, candidate_id='full-review')

    def test_embedded_seed_tree_and_resealed_storage_key_or_hash_kind_tampering_is_refused(self):
        for case in ('seed-bytes', 'tree-bytes', 'hash-kind', 'null-storage-key', 'unknown-storage-key'):
            with self.subTest(case=case), self.fixture() as (fixture, qualification):
                spec = copy.deepcopy(qualification['stage_spec'])
                source = json.loads(spec['seed_source_receipt_json'])
                rows = json.loads(spec['hf_manifest_json'])
                git_name = next(row['path'] for row in rows if 'xetHash' not in row)
                if case == 'seed-bytes': spec['seed_source_receipt_json'] += ' '
                elif case == 'tree-bytes': spec['hf_manifest_json'] += ' '
                else:
                    row = source['files'][git_name]
                    if case == 'hash-kind': row['hf_data_hash_kind'] = 'sha256-lfs'
                    elif case == 'null-storage-key': row['source_blob_id'] = None
                    elif case == 'unknown-storage-key': row['source_blob_id'] = 'f' * 64
                    spec['seed_source_receipt_json'] = json.dumps(source)
                    spec['seed_receipt_sha256'] = hashlib.sha256(spec['seed_source_receipt_json'].encode()).hexdigest()
                with self.assertRaises(ValueError): cache.validate_seed_provenance(spec)

    def test_exact_graph_patch_rejects_resealed_bootstrap_memory_gpu_env_and_source_changes(self):
        with self.fixture() as (fixture, qualification):
            path = fixture.path / 'qualification.json'; path.write_text(json.dumps(qualification))
            graph, cm, receipt = cache.apply_candidate_cache(fixture.graph(), path, candidate_id='full-review')
            for case in ('bootstrap', 'memory', 'gpu', 'args', 'env', 'readonly'):
                with self.subTest(case=case):
                    g, bootstrap, proof = copy.deepcopy(graph), copy.deepcopy(cm), copy.deepcopy(receipt)
                    main = g['spec']['components'][1]['podTemplate']['spec']['containers'][0]
                    if case == 'bootstrap': bootstrap['data']['stage.py'] += '\n# changed source\n'
                    elif case == 'memory': main['resources']['requests']['memory'] = '1Gi'
                    elif case == 'gpu': main['resources']['limits']['nvidia.com/gpu'] = '8'
                    elif case == 'args': main['args'].append('--unexpected')
                    elif case == 'env': main['env'].append({'name': 'MX_ENABLED', 'value': '1'})
                    elif case == 'readonly': main['volumeMounts'][-1]['readOnly'] = False
                    proof['patched_graph_sha256'] = cache.canonical_digest(g)
                    proof['config_map_sha256'] = cache.canonical_digest(bootstrap)
                    with self.assertRaises(ValueError): cache.validate_candidate_cache(g, path, bootstrap, proof, candidate_id='full-review')

    def test_stream_missing_duplicate_overflow_wrong_commit_and_cuda_never_publish(self):
        for case in ('missing', 'duplicate', 'overflow', 'commit', 'cuda'):
            with self.subTest(case=case), self.fixture() as (fixture, qualification):
                client = author.FakeClient(fixture.spec, fixture.payloads)
                def stream(model, provider, paths, expected, sink, **kwargs):
                    names = paths[:-1] if case == 'missing' else paths
                    for name in names:
                        sink.begin_file(name)
                        payload = fixture.payloads[name]
                        sink.write(payload + b'x' if case == 'overflow' else payload)
                        sink.end_file()
                        if case == 'duplicate': sink.begin_file(name)
                    return 'f' * 40 if case == 'commit' else fixture.spec['revision']
                client._stream_into = stream
                target = fixture.path / ('negative-' + case)
                cuda = [{'cuda_initialized': False}, {'cuda_initialized': True}] if case == 'cuda' else None
                context = patch.object(stage, 'cuda_state', side_effect=cuda) if cuda else contextlib.nullcontext()
                with context, contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                    stage.stage(fixture.spec, target, client, 0, resource_gate=lambda *_: {})
                self.assertFalse((target / 'mx-dev-cache-stage.json').exists())
                self.assertFalse((target / 'hub/models--example--model').exists())

    def test_optional_composed_metadata_requires_exact_three_files_and_source_binding(self):
        with self.fixture() as (fixture, qualification):
            path = fixture.path / 'full-review'; path.mkdir()
            spec = {'inputs': {}, 'source_snapshot': {}}
            self.assertIsNone(full.validate_candidate_cache(path, spec))
            spec['inputs'][full.DEV_CACHE_INPUTS[0]] = 'f' * 64
            with self.assertRaises(ValueError): full.validate_candidate_cache(path, spec)
            for case in ('missing-file', 'wrong-candidate', 'extra-metadata', 'source-hash'):
                with self.subTest(case=case):
                    value = {'inputs': {name: 'f' * 64 for name in full.DEV_CACHE_INPUTS}, 'source_snapshot': {},
                        'dev_cache': {'schema': 1, 'candidate_id': path.name,
                            'qualification_sha256': 'f' * 64, 'bootstrap_sha256': 'f' * 64,
                            'receipt_sha256': 'f' * 64, 'source_sha256': {}}}
                    if case == 'missing-file': value['inputs'].pop(full.DEV_CACHE_INPUTS[1])
                    elif case == 'wrong-candidate': value['dev_cache']['candidate_id'] = 'other'
                    elif case == 'extra-metadata': value['dev_cache']['unexpected'] = True
                    elif case == 'source-hash':
                        for name in full.DEV_CACHE_INPUTS: (path / name).write_text('{}')
                        for name, key in zip(full.DEV_CACHE_INPUTS, ('qualification_sha256','bootstrap_sha256','receipt_sha256')):
                            value['inputs'][name] = value['dev_cache'][key] = full.ui.digest(path / name)
                    with self.assertRaises((ValueError, OSError)): full.validate_candidate_cache(path, value)


if __name__ == '__main__': unittest.main()
