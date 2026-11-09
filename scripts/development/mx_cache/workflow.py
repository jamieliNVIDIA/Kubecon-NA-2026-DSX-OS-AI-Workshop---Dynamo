#!/usr/bin/env python3
"""Offline binding/rendering for the development-only MX RAM cache.

No Kubernetes calls. Root collects current producer JSON and applies resources.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re

import yaml

from scripts.development.mx_cache.stage import validate_spec

ROOT = Path(__file__).resolve().parents[3]
HF_HOME = '/model-cache/feature-tests/20261015-super-vl-tp2/hf'
SERVER_IMAGE = 'nvcr.io/nvidia/ai-dynamo/modelexpress-server@sha256:0f8456cfc29c02547d6c62d1e640f98dc691e0326523c15fa05987d8bc491a77'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_spec_producer(spec, producer):
    ip = ipaddress.ip_address(producer['pod_ip'])
    qualified_address = ('[' + str(ip) + ']' if ip.version == 6 else str(ip)) + ':8001'
    if (spec['server_address'] != qualified_address or spec['server_pod_uid'] != producer['uid'] or
            producer['image'] != SERVER_IMAGE or not producer['container_id'] or not producer['seed_container_id'] or
            not exact_image_id(producer['image_id'], SERVER_IMAGE) or
            not re.fullmatch(r'[a-f0-9]{64}', spec['seed_receipt_sha256'])):
        raise ValueError('Stage address is not the exact qualified producer Pod IP/generation.')
    return qualified_address


def validate_seed_provenance(spec):
    """Separate authoritative file digests from declared HF/Xet storage keys."""
    raw = spec.get('seed_source_receipt_json')
    tree_raw = spec.get('hf_manifest_json')
    if (not isinstance(raw, str) or not isinstance(tree_raw, str) or
            hashlib.sha256(raw.encode()).hexdigest() != spec['seed_receipt_sha256'] or
            hashlib.sha256(tree_raw.encode()).hexdigest() != spec.get('hf_manifest_sha256')):
        raise ValueError('Frozen seed/HF manifest provenance bytes/hash differ.')
    seed, rows = json.loads(raw), json.loads(tree_raw)
    tree = {row['path']: row for row in rows}
    if (len(tree) != len(rows) or type(seed.get('schema')) is not int or seed['schema'] != 1 or
            seed.get('status') != 'passed' or seed.get('model') != spec['model'] or seed.get('revision') != spec['revision'] or
            seed.get('hf_manifest_sha256') != spec['hf_manifest_sha256'] or
            seed.get('hf_manifest_entries') != len(rows) or
            set(seed['files']) != set(spec['files']) or set(tree) != set(spec['files'])):
        raise ValueError('Seed/HF manifest identity or complete file inventory differs.')
    expected_url = ('https://huggingface.co/api/models/' + spec['model'] + '/tree/' + spec['revision'] +
                    '?recursive=true&expand=false&limit=1000')
    if seed.get('hf_manifest_url') != expected_url:
        raise ValueError('Seed HF manifest is not the exact model revision.')
    for name, expected in spec['files'].items():
        source, row = seed['files'][name], tree[name]
        allowed = {row['oid']}
        if 'xetHash' in row: allowed.add(row['xetHash'])
        if 'lfs' in row: allowed.add(row['lfs']['oid'])
        kind = 'sha256-lfs' if 'lfs' in row else 'sha1-git-blob'
        content_hash = row['lfs']['oid'] if 'lfs' in row else row['oid']
        if (canonical_digest({key: source[key] for key in ('bytes', 'sha256', 'weight')}) != canonical_digest(expected) or
                type(row.get('size')) is not int or row['size'] != expected['bytes'] or
                source.get('hf_data_hash_kind') != kind or source.get('hf_data_hash') != content_hash or
                source.get('hf_git_oid') != row['oid'] or source.get('hf_xet_storage_key') != row.get('xetHash') or
                not isinstance(source.get('source_blob_id'), str) or source['source_blob_id'] not in allowed or
                ('lfs' in row and (row['lfs']['size'] != row['size'] or content_hash != expected['sha256']))):
            raise ValueError('Seed file content/storage provenance differs: ' + name)
    return {'hf_manifest_sha256': spec['hf_manifest_sha256'], 'files': len(tree),
            'seed_receipt_sha256': spec['seed_receipt_sha256']}


def cpu_stage_identity(plan, pod):
    metadata, status = pod['metadata'], pod['status']
    spec = pod['spec']
    main = next(c for c in spec['containers'] if c['name'] == 'stage')
    container = next(c for c in status['containerStatuses'] if c['name'] == 'stage')
    terminated = container.get('state', {}).get('terminated', {})
    expected_main = stage_init(plan['stage_spec'], plan['runtime_image'], '/local-hf')
    expected_main['name'] = 'stage'
    cm = stage_config_map(plan['namespace'], plan['stage_spec'])
    expected_volumes = stage_volumes(cm)
    if (metadata.get('deletionTimestamp') or status.get('phase') != 'Succeeded' or
            len(spec['containers']) != 1 or spec.get('initContainers') or spec.get('resourceClaims') or
            spec.get('restartPolicy') != 'Never' or spec.get('automountServiceAccountToken') is not False or
            canonical_digest(spec.get('volumes')) != canonical_digest(expected_volumes) or
            any(canonical_digest(main.get(key)) != canonical_digest(value) for key, value in expected_main.items()) or
            metadata['namespace'] != plan['namespace'] or spec['nodeName'] != plan['node'] or
            metadata.get('labels', {}).get('mx-development-run') != plan['stage_spec']['id'] or
            main['image'] != plan['runtime_image'] or not exact_image_id(container.get('imageID'), plan['runtime_image']) or
            type(terminated.get('exitCode')) is not int or terminated['exitCode'] != 0 or
            type(container.get('restartCount')) is not int or container['restartCount'] != 0 or not container.get('containerID') or
            any('gpu' in key for group in main.get('resources', {}).values() for key in group) or
            any('persistentVolumeClaim' in volume for volume in spec.get('volumes', [])) or
            not any(env['name'] == 'NVIDIA_VISIBLE_DEVICES' and env.get('value') == 'void' for env in main.get('env', []))):
        raise ValueError('CPU stage lacks exact completed zero-GPU/private-cache Pod provenance.')
    return {'namespace': metadata['namespace'], 'name': metadata['name'], 'uid': metadata['uid'],
            'node': spec['nodeName'], 'container_id': container['containerID'],
            'image': main['image'], 'image_id': container['imageID'], 'exit_code': 0,
            'gpu_requests': 0, 'shared_source_mounted': False}


def load(path):
    return json.loads(Path(path).read_text())


def as_record(value):
    return value if isinstance(value, dict) else load(value)


def exact_image_id(actual, expected):
    return actual in (expected, 'docker-pullable://' + expected)


def cpu_bootstrap_identity(plan, config_map):
    expected = stage_config_map(plan['namespace'], plan['stage_spec'])
    if (config_map.get('kind') != 'ConfigMap' or config_map.get('immutable') is not True or
            config_map['metadata']['name'] != expected['metadata']['name'] or
            config_map['metadata']['namespace'] != expected['metadata']['namespace'] or
            not config_map['metadata'].get('uid') or
            canonical_digest(config_map.get('data')) != canonical_digest(expected['data'])):
        raise ValueError('CPU stage bootstrap is not the exact immutable native-stage source/spec.')
    return {'namespace': config_map['metadata']['namespace'], 'name': config_map['metadata']['name'],
            'uid': config_map['metadata']['uid'], 'immutable': True,
            'data_sha256': canonical_digest(config_map['data'])}


def producer_identity(pod):
    metadata = pod['metadata']
    status = pod['status']
    if (metadata.get('deletionTimestamp') or status.get('phase') != 'Running' or
            not any(c['type'] == 'Ready' and c['status'] == 'True' for c in status.get('conditions', []))):
        raise ValueError('MX producer is not a current Ready running Pod.')
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'server')
    container = next(c for c in status['containerStatuses'] if c['name'] == 'server')
    seed = next(c for c in status['initContainerStatuses'] if c['name'] == 'seed')
    if (main['image'] != SERVER_IMAGE or container.get('ready') is not True or
            not container.get('state', {}).get('running') or not container.get('containerID') or
            not exact_image_id(container.get('imageID'), SERVER_IMAGE) or
            type(seed.get('state', {}).get('terminated', {}).get('exitCode')) is not int or
            seed['state']['terminated']['exitCode'] != 0 or not seed.get('containerID')):
        raise ValueError('MX producer or its seed container generation/image is unqualified.')
    return {'namespace': metadata['namespace'], 'name': metadata['name'], 'uid': metadata['uid'],
            'node': pod['spec']['nodeName'], 'pod_ip': status['podIP'], 'container_id': container['containerID'],
            'image': main['image'], 'image_id': container['imageID'],
            'seed_container_id': seed['containerID']}


def validate_producer_snapshot(qualification, pod):
    """Accept only the same currently running seeded server generation."""
    expected = as_record(qualification)['producer']
    current = producer_identity(pod)
    if current != expected:
        raise ValueError('MX producer changed; requalify this cache before GPU intent/deploy.')
    return current


def validate_stage_receipt(receipt, binding):
    """Verify all target bytes against a qualification or graph-patch receipt."""
    receipt, binding = as_record(receipt), as_record(binding)
    if binding.get('kind') == 'mx-dev-cache-qualification':
        spec = binding['stage_spec']
        validate_spec_producer(spec, binding['producer'])
        expected_hash, files = canonical_digest(spec), spec['files']
        identity = spec
    elif binding.get('kind') == 'mx-dev-cache-graph-patch':
        expected_hash, files, identity = binding['stage_spec_sha256'], binding['file_inventory'], binding
    else:
        raise ValueError('Unknown staging receipt binding.')
    weights = {name for name, row in files.items() if row['weight']}
    if (type(receipt.get('schema')) is not int or receipt['schema'] != 1 or receipt.get('status') != 'passed' or
            receipt.get('id') != identity['id'] or
            receipt.get('stage_spec_sha256') != expected_hash or canonical_digest(receipt.get('files')) != canonical_digest(files) or
            any(type(receipt.get(key)) is not int for key in ('file_count', 'weight_files', 'weight_bytes', 'logical_bytes')) or
            receipt.get('file_count') != len(files) or receipt.get('weight_files') != len(weights) or
            receipt.get('weight_bytes') != sum(files[name]['bytes'] for name in weights) or
            receipt.get('logical_bytes') != sum(row['bytes'] for row in files.values()) or
            receipt.get('server_address') != identity['server_address'] or
            receipt.get('server_pod_uid') != binding['producer']['uid'] or
            receipt.get('seed_receipt_sha256') != identity['seed_receipt_sha256'] or
            receipt.get('model') != identity['model'] or receipt.get('revision') != identity['revision'] or
            receipt.get('cuda_initialized') is not False):
        raise ValueError('Full CPU stage result differs from its exact trusted inventory/identity.')
    return {'status': 'verified', 'file_count': len(files), 'weight_files': len(weights),
            'weight_bytes': receipt['weight_bytes'], 'stage_spec_sha256': expected_hash,
            'server_pod_uid': receipt['server_pod_uid']}


def build_stage_spec(seed_path, producer_path, address, candidate_id):
    seed = load(seed_path)
    lock = load(ROOT / 'configs/super-vl-tp2-lock.json')
    baseline = load(ROOT / 'results/20261015-super-vl-tp2/state.json')['checks']['model-staging']
    producer = producer_identity(load(producer_path))
    if (seed.get('schema') != 1 or seed.get('status') != 'passed' or
            (seed['model'], seed['revision']) != (lock['model'], lock['revision']) or
            seed['weight_files'] != baseline['weight_files'] or seed['weight_bytes'] != baseline['weight_bytes']):
        raise ValueError('RAM seed is not the exact qualified SuperVL snapshot.')
    ip = ipaddress.ip_address(producer['pod_ip'])
    qualified_address = ('[' + str(ip) + ']' if ip.version == 6 else str(ip)) + ':8001'
    if address != qualified_address:
        raise ValueError('Use the qualified producer Pod IP:8001 directly; DNS service routing is not qualified.')
    for name, expected in lock['model_metadata_sha256'].items():
        if seed['files'][name]['sha256'] != expected:
            raise ValueError('RAM seed metadata differs: ' + name)
    files = {name: {key: row[key] for key in ('bytes', 'sha256', 'weight')}
             for name, row in seed['files'].items()}
    if (len(files) != seed['file_count'] or sum(row['bytes'] for row in files.values()) != seed['logical_bytes'] or
            sum(row['weight'] is True for row in files.values()) != seed['weight_files'] or
            sum(row['bytes'] for row in files.values() if row['weight']) != seed['weight_bytes']):
        raise ValueError('RAM seed inventory totals differ.')
    spec = {'schema': 1, 'id': candidate_id, 'model': seed['model'], 'revision': seed['revision'],
            'server_address': address, 'server_pod_uid': producer['uid'],
            'seed_receipt_sha256': digest(seed_path), 'cache_limit_bytes': 96 * 1024 ** 3, 'files': files}
    tree_path = ROOT / 'results/mx-dev-source-hf-tree-20261105-a1/tree.json'
    spec.update(seed_source_receipt_json=Path(seed_path).read_text(), hf_manifest_json=tree_path.read_text(),
                hf_manifest_sha256=digest(tree_path))
    validate_spec(spec)
    validate_spec_producer(spec, producer)
    validate_seed_provenance(spec)
    return spec, producer


def stage_config_map(namespace, spec):
    name = spec['id'] + '-mx-stage'
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True, 'metadata': {
        'name': name, 'namespace': namespace,
        'labels': {'app.kubernetes.io/managed-by': 'kubecon-dynamo-feature-tests',
                   'feature-test-run': namespace, 'mx-development-run': spec['id']}},
        'data': {'stage.py': (ROOT / 'scripts/development/mx_cache/stage.py').read_text(),
                 'stage-spec.json': json.dumps(spec, sort_keys=True)}}


def stage_init(spec, image, mount_path=HF_HOME):
    return {'name': 'mx-dev-cache-stage', 'image': image,
            'command': ['python3', '/mx-dev-bootstrap/stage.py'],
            'args': ['--spec', '/mx-dev-bootstrap/stage-spec.json', '--hf-home', mount_path,
                     '--timeout-seconds', '1200', '--rpc-timeout', '900'],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                    {'name': 'HF_HUB_OFFLINE', 'value': '1'}],
            'resources': {'requests': {'cpu': '2', 'memory': '96Gi'},
                          'limits': {'cpu': '4', 'memory': '112Gi'}},
            'volumeMounts': [{'name': 'mx-dev-cache', 'mountPath': mount_path},
                             {'name': 'mx-dev-bootstrap', 'mountPath': '/mx-dev-bootstrap', 'readOnly': True}]}


def stage_volumes(config_map):
    return [{'name': 'mx-dev-cache', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '96Gi'}},
            {'name': 'mx-dev-bootstrap', 'configMap': {'name': config_map['metadata']['name'], 'defaultMode': 420}}]


def render_cpu_probe(seed_path, producer_path, address, candidate_id, namespace, node):
    spec, producer = build_stage_spec(seed_path, producer_path, address, candidate_id)
    if not re.fullmatch(r'dynamo-ft-[a-z0-9-]+', namespace):
        raise ValueError('Use an owned feature namespace.')
    config_map = stage_config_map(namespace, spec)
    lock = load(ROOT / 'configs/super-vl-tp2-lock.json')
    container = stage_init(spec, lock['runtime_image'], '/local-hf')
    container['name'] = 'stage'
    labels = config_map['metadata']['labels']
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {
        'name': candidate_id + '-stage', 'namespace': namespace, 'labels': labels},
        'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 1500, 'template': {
            'metadata': {'labels': labels}, 'spec': {'restartPolicy': 'Never',
                'automountServiceAccountToken': False, 'nodeSelector': {'kubernetes.io/hostname': node},
                'imagePullSecrets': [{'name': 'common-runtime-pull'}],
                'containers': [container], 'volumes': stage_volumes(config_map)}}}}
    plan = {'schema': 1, 'kind': 'mx-dev-cache-stage-plan', 'stage_spec': spec, 'producer': producer,
            'stage_source_sha256': hashlib.sha256(config_map['data']['stage.py'].encode()).hexdigest(),
            'gpu_requests': 0, 'namespace': namespace, 'node': node, 'runtime_image': lock['runtime_image']}
    return config_map, job, plan


def qualify_cache(plan_path, stage_receipt_path, current_producer_path, cpu_pod_path, cpu_bootstrap_path):
    plan, stage = load(plan_path), load(stage_receipt_path)
    spec = plan['stage_spec']
    validate_spec(spec)
    validate_spec_producer(spec, plan['producer'])
    validate_seed_provenance(spec)
    validate_producer_snapshot(plan, load(current_producer_path))
    cpu_identity = cpu_stage_identity(plan, load(cpu_pod_path))
    bootstrap_identity = cpu_bootstrap_identity(plan, load(cpu_bootstrap_path))
    if (stage.get('status') != 'passed' or stage.get('schema') != 1 or
            stage.get('stage_spec_sha256') != canonical_digest(spec) or stage.get('files') != spec['files'] or
            stage.get('server_address') != spec['server_address'] or
            stage.get('server_pod_uid') != spec['server_pod_uid'] or
            stage.get('seed_receipt_sha256') != spec['seed_receipt_sha256'] or
            stage.get('model') != spec['model'] or stage.get('revision') != spec['revision'] or
            stage.get('cuda_initialized') is not False):
        raise ValueError('CPU all-file stream result is not bound to this exact cache plan/producer.')
    if plan['stage_source_sha256'] != digest(ROOT / 'scripts/development/mx_cache/stage.py'):
        raise ValueError('Qualified CPU stage program changed; repeat the CPU gate.')
    validate_stage_receipt(stage, {'kind': 'mx-dev-cache-qualification', 'stage_spec': spec,
                                   'producer': plan['producer']})
    return {'schema': 1, 'kind': 'mx-dev-cache-qualification', 'status': 'passed',
            'stage_spec': spec, 'producer': plan['producer'],
            'stage_source_sha256': plan['stage_source_sha256'],
            'cpu_stage_receipt_sha256': digest(stage_receipt_path),
            'cpu_stage_receipt_canonical_sha256': canonical_digest(stage),
            'cpu_stage_identity': cpu_identity, 'cpu_stage_pod_sha256': digest(cpu_pod_path),
            'cpu_stage_pod': load(cpu_pod_path), 'cpu_probe_plan': plan,
            'cpu_bootstrap': load(cpu_bootstrap_path), 'cpu_bootstrap_identity': bootstrap_identity,
            'cpu_stage_receipt': stage, 'cpu_probe_plan_sha256': digest(plan_path),
            'scope': 'Development-only CPU file cache; no GMS-MX/P2P composition or speedup claim.'}


def apply_candidate_cache(graph, qualification_path, *, candidate_id):
    """Narrow offline graph delta. Caller must recheck producer before intent."""
    qualification = as_record(qualification_path)
    if (type(qualification.get('schema')) is not int or qualification['schema'] != 1 or qualification.get('status') != 'passed' or
            qualification.get('kind') != 'mx-dev-cache-qualification' or
            qualification.get('stage_source_sha256') != digest(ROOT / 'scripts/development/mx_cache/stage.py')):
        raise ValueError('Full passed CPU cache qualification with unchanged stage source is required.')
    qualified_spec = qualification['stage_spec']
    validate_spec(qualified_spec)
    validate_seed_provenance(qualified_spec)
    plan = qualification['cpu_probe_plan']
    if (canonical_digest(plan['stage_spec']) != canonical_digest(qualified_spec) or
            canonical_digest(plan['producer']) != canonical_digest(qualification['producer']) or
            plan['stage_source_sha256'] != qualification['stage_source_sha256'] or
            canonical_digest(cpu_stage_identity(plan, qualification['cpu_stage_pod'])) != canonical_digest(qualification['cpu_stage_identity']) or
            canonical_digest(cpu_bootstrap_identity(plan, qualification['cpu_bootstrap'])) != canonical_digest(qualification['cpu_bootstrap_identity'])):
        raise ValueError('Qualified CPU Pod/source provenance differs from its embedded plan.')
    cpu = qualification['cpu_stage_receipt']
    if canonical_digest(cpu) != qualification.get('cpu_stage_receipt_canonical_sha256'):
        raise ValueError('Qualified all-file CPU gate is incomplete.')
    validate_stage_receipt(cpu, qualification)
    patched = copy.deepcopy(graph)
    namespace = patched['metadata']['namespace']
    stage_id = 'shadow-mx-' + hashlib.sha256(candidate_id.encode()).hexdigest()[:12]
    spec = dict(qualified_spec, id=stage_id)
    validate_spec(spec)
    config_map = stage_config_map(namespace, spec)
    workers = [c for c in patched['spec']['components'] if c['type'] == 'worker']
    if len(workers) != 1:
        raise ValueError('Development cache patch expects one aggregated Shadow worker component.')
    pod = workers[0]['podTemplate']['spec']
    main = pod['containers'][0]
    if (main['name'] != 'main' or main['args'][main['args'].index('--load-format') + 1] != 'gms' or
            not any(e['name'] == 'HF_HOME' and e.get('value') == HF_HOME for e in main['env']) or
            any(e['name'] == 'MX_ENABLED' and e.get('value') != '0' for e in main['env'])):
        raise ValueError('Cache patch needs unchanged native GMS loader with MX disabled and pinned HF_HOME.')
    model_arg = main['args'][main['args'].index('--model') + 1]
    revision_arg = main['args'][main['args'].index('--revision') + 1]
    expected_local = HF_HOME + '/hub/models--' + spec['model'].replace('/', '--') + '/snapshots/' + spec['revision']
    if model_arg not in (spec['model'], expected_local) or revision_arg != spec['revision']:
        raise ValueError('Graph and cache model/revision differ.')
    resources = main['resources']
    if resources['requests']['memory'] != '128Gi' or resources['limits']['memory'] != '256Gi':
        raise ValueError('Unknown worker resource basis; do not silently alter its budget.')
    existing_volumes = {v['name'] for v in pod['volumes']}
    if existing_volumes & {'mx-dev-cache', 'mx-dev-bootstrap'} or any(m['mountPath'] == HF_HOME for m in main['volumeMounts']):
        raise ValueError('Cache patch was already applied or HF_HOME mount conflicts.')
    base_graph_sha256 = canonical_digest(graph)
    original_init_key = 'initContainers' in pod
    original_args, original_env = copy.deepcopy(main['args']), copy.deepcopy(main['env'])
    pod['volumes'].extend(stage_volumes(config_map))
    pod.setdefault('initContainers', []).append(stage_init(spec, main['image']))
    main['volumeMounts'].append({'name': 'mx-dev-cache', 'mountPath': HF_HOME, 'readOnly': True})
    resources['requests']['memory'], resources['limits']['memory'] = '224Gi', '352Gi'
    assert main['args'] == original_args and main['env'] == original_env
    receipt = {'schema': 1, 'kind': 'mx-dev-cache-graph-patch', 'id': stage_id, 'candidate_id': candidate_id,
               'qualification_sha256': None if isinstance(qualification_path, dict) else digest(qualification_path),
               'qualification_canonical_sha256': canonical_digest(qualification),
               'stage_spec_sha256': canonical_digest(spec), 'producer': qualification['producer'],
               'server_address': spec['server_address'], 'seed_receipt_sha256': spec['seed_receipt_sha256'],
               'model': spec['model'], 'revision': spec['revision'], 'file_inventory': spec['files'],
               'config_map_name': config_map['metadata']['name'], 'config_map_sha256': canonical_digest(config_map),
               'stage_source_sha256': qualification['stage_source_sha256'], 'hf_home': HF_HOME,
               'base_graph_sha256': base_graph_sha256, 'patched_graph_sha256': canonical_digest(patched),
               'base_init_containers_key_present': original_init_key,
               'gpu_requests_changed': False, 'engine_args_changed': False, 'engine_env_changed': False,
               'ram_cache_gib': 96, 'engine_memory_request_gib': 224, 'engine_memory_limit_gib': 352,
               'two_engine_pod_request_gib': 448, 'two_engine_pod_limit_gib': 704,
               'budget_note': 'DGD operator clones main resources to both engines. The96Gi cache exists once;192Gi extra request conservatively reserves it without operator overrides.',
               'required_deploy_gate': 'Query current source Pod before GPU intent/deploy and call validate_producer_snapshot(qualification,pod).',
               'scope': 'CPU file staging only. Full stage hashes required before engines start. No GMS-MX/P2P composition claim.'}
    return patched, config_map, receipt


def validate_candidate_cache(graph, qualification_path, config_map, receipt, *, candidate_id):
    """Validate self-contained frozen cache data and the exact bounded graph delta."""
    qualification, config_map, receipt = (as_record(qualification_path), as_record(config_map), as_record(receipt))
    if canonical_digest(graph) != receipt.get('patched_graph_sha256'):
        raise ValueError('Frozen patched graph hash differs.')
    if receipt.get('candidate_id') != candidate_id:
        raise ValueError('Frozen cache candidate identity differs.')
    baseline = copy.deepcopy(graph)
    workers = [c for c in baseline['spec']['components'] if c['type'] == 'worker']
    if len(workers) != 1:
        raise ValueError('Frozen cache graph worker count differs.')
    pod = workers[0]['podTemplate']['spec']
    main = pod['containers'][0]
    pod['volumes'] = [v for v in pod['volumes'] if v['name'] not in ('mx-dev-cache', 'mx-dev-bootstrap')]
    main['volumeMounts'] = [m for m in main['volumeMounts'] if m['name'] != 'mx-dev-cache']
    pod['initContainers'] = [c for c in pod.get('initContainers', []) if c['name'] != 'mx-dev-cache-stage']
    if not receipt['base_init_containers_key_present']:
        if pod['initContainers']:
            raise ValueError('Unexpected preexisting init containers.')
        del pod['initContainers']
    main['resources']['requests']['memory'] = '128Gi'
    main['resources']['limits']['memory'] = '256Gi'
    if canonical_digest(baseline) != receipt.get('base_graph_sha256'):
        raise ValueError('Frozen cache delta changes the baseline outside the allowed graph patch.')
    # This revalidates complete embedded CPU evidence and current reviewed source.
    expected_graph, expected_cm, expected_receipt = apply_candidate_cache(
        baseline, qualification_path, candidate_id=candidate_id)
    if any(canonical_digest(a) != canonical_digest(b) for a, b in
           ((expected_graph, graph), (expected_cm, config_map), (expected_receipt, receipt))):
        raise ValueError('Frozen cache graph/ConfigMap/receipt are not the exact reviewed rendering.')
    return {'status': 'verified', 'candidate_id': candidate_id, 'stage_id': receipt['id'],
            'file_count': len(receipt['file_inventory']), 'producer': receipt['producer'],
            'qualification_sha256': receipt['qualification_sha256'],
            'config_map_sha256': receipt['config_map_sha256']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    render = sub.add_parser('render-probe')
    for name in ('seed-receipt', 'producer', 'address', 'id', 'namespace', 'node', 'output'):
        render.add_argument('--' + name, required=True)
    qualify = sub.add_parser('qualify')
    for name in ('plan', 'stage-receipt', 'producer', 'cpu-pod', 'cpu-bootstrap', 'output'):
        qualify.add_argument('--' + name, required=True)
    a = p.parse_args()
    if a.command == 'render-probe':
        cm, job, plan = render_cpu_probe(a.seed_receipt, a.producer, a.address, a.id, a.namespace, a.node)
        output = Path(a.output)
        output.mkdir(parents=True, exist_ok=False)
        (output / 'probe.yaml').write_text(yaml.safe_dump({'apiVersion': 'v1', 'kind': 'List', 'items': [cm, job]}, sort_keys=False))
        (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        print(json.dumps(plan, indent=2))
    else:
        result = qualify_cache(a.plan, a.stage_receipt, a.producer, a.cpu_pod, a.cpu_bootstrap)
        with Path(a.output).open('x') as out:
            out.write(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'scope': result['scope']}))


if __name__ == '__main__':
    main()
