#!/usr/bin/env python3
"""Fresh, immutable text-only AgentX RR/KV campaign on four scoped H100s."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = HERE.parent / 'round-robin'
AGENTX = HERE.parent / 'agentx-workload'
sys.path[:0] = [str(OLD), str(ROOT / 'scripts'), str(HERE)]
import execute_pair as e
import cluster
import discovery
import qualify_client
from storage_tests import prepare as prepare_storage
from gpu_claims import verify_allocation

LEASE = ROOT / '.local/workshop-rrkv-20261104.gpu-lease'
OWNER = '/root/rrkv'
NAMESPACE = 'dynamo-ft-rrkv-20261104-a1'
GPUS = {
    'kubecon-nke-site-cp-0198': ['GPU-3aea3e1e-63c3-41cd-43be-4e379ed995b5', 'GPU-08dc0ef4-2e92-4cc2-6adc-b735980a1326'],
    'kubecon-nke-site-cp-0942': ['GPU-c15ae016-71f1-03bc-0228-624adbb1b4e8', 'GPU-4aacb1e1-a109-70bb-6b72-8071d736ba75'],
}
CPU_NODE = 'kubecon-nke-site-cp-0942'
ORIGINAL_SEAL_PROFILE = e.seal_profile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def spec(run):
    return json.loads((run.path / 'campaign.json').read_text())


def status(run, stage, **details):
    value = {'at': e.now(), 'stage': stage, 'namespace': run.ns, **details}
    write(run.path / 'LIVE_STATUS.json', value)
    print(json.dumps(value), flush=True)


def setup(path):
    run = e.Run(path)
    if not run.state.get('rrkv_initialized'):
        assert not (run.path / 'model-lock.json').exists()
        lock = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())
        run.ns = NAMESPACE
        run.state.update(namespace=NAMESPACE, model_lock=lock,
            model_cache_run_id='20261015-super-vl-tp2', rrkv_initialized=True)
        write(run.path / 'model-lock.json', lock)
        run.save()
    assert run.ns == NAMESPACE
    e.LEASE = cluster.LEASE = LEASE
    e.OWNER = cluster.OWNER = OWNER
    e.status = status
    return run


def generated(run, mode):
    source = OLD / 'router-extension-candidates' / ('two-worker-' + mode + '-template.yaml')
    content = yaml.safe_load(source.read_text())
    old_ns = next(o['metadata']['namespace'] for o in content['items'])
    content = json.loads(json.dumps(content).replace(old_ns, run.ns))
    uuids = [uuid for pair in GPUS.values() for uuid in pair]
    for obj in content['items']:
        if obj['kind'] == 'ResourceClaimTemplate':
            request = obj['spec']['spec']['devices']['requests'][0]['exactly']
            request['selectors'] = [{'cel': {'expression':
                'device.driver == "gpu.nvidia.com" && has(device.attributes["gpu.nvidia.com"].uuid) && '
                'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids)}}]
        if obj['kind'] != 'DynamoGraphDeployment':
            continue
        for component in obj['spec']['components']:
            pod = component['podTemplate']['spec']
            pod['activeDeadlineSeconds'] = 14400
            container = pod['containers'][0]
            for env in container.get('env', []):
                if env['name'] == 'NIXL_TELEMETRY_ENABLE':
                    env['value'] = 'y'
            if component['type'] == 'frontend':
                pod['nodeSelector'] = {'kubernetes.io/hostname': CPU_NODE}
                continue
            terms = pod['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
            for term in terms:
                for expression in term['matchExpressions']:
                    if expression['key'] == 'kubernetes.io/hostname':
                        expression['values'] = list(GPUS)
            container['args'].append('--language-model-only')
            container['startupProbe'].update(periodSeconds=2, failureThreshold=1800)
            container['readinessProbe'] = copy.deepcopy(json.loads((run.path / 'expected-probes.json').read_text())['readinessProbe'])
            settings = {'DYN_CANARY_WAIT_TIME': '1', 'VLLM_CACHE_ROOT': '/tmp/workshop-vllm-cache',
                'TRITON_CACHE_DIR': '/tmp/workshop-triton-cache', 'DG_JIT_CACHE_DIR': '/tmp/workshop-deepgemm-cache',
                'FLASHINFER_WORKSPACE_BASE': '/tmp/workshop-flashinfer-cache'}
            container['env'] = [v for v in container['env'] if v['name'] not in settings]
            container['env'] += [{'name': key, 'value': value} for key, value in settings.items()]
    return content


def freeze(run):
    if (run.path / 'inputs-sha256.json').exists():
        verify(run)
        return
    assert not (run.path / 'campaign.json').exists(), 'Preserve partial freeze; choose a fresh campaign'
    reference = ROOT / 'results/workshop-mx-startup-20261104-baseline03/expected-effective-probes.json'
    write(run.path / 'expected-probes.json', json.loads(reference.read_text()))
    c4 = ROOT / 'results/workshop-c4-closeout-20261104-a1/verified/results/workshop-rr-20261103-resume02/state.json'
    cache_bytes = json.loads(c4.read_text())['checks']['model-staging']['weight_bytes']
    frozen = {'schema': 1, 'model_lock': run.state['model_lock'], 'namespace': run.ns,
        'model_cache_run_id': '20261015-super-vl-tp2', 'checkpoint_weight_bytes': cache_bytes,
        'model_cache_reference_sha256': sha(c4), 'dataset_revision': e.DATASET_REV, 'dataset_sha256': e.DATASET_SHA,
        'aiperf_commit': 'e2c149ee29d3b64798d8ba2176e9f42e0aa89280',
        'sequence': [{'concurrency': c, 'mode': mode, 'arm': f'routing-c{c}-{mode}-a1'}
                     for c in [1, 4] for mode in ['round-robin', 'kv']],
        'gpu_uuids_by_node': GPUS, 'cpu_node': CPU_NODE, 'replicas': 2, 'tp': 2,
        'native_context': 1048576, 'max_num_seqs': 4, 'max_num_batched_tokens': 8192,
        'gpu_memory_utilization': .85, 'text_only': True, 'compile': True,
        'seed': 20261030, 'profile_seconds': 900, 'grace_seconds': 300,
        'warmup': 'unchanged canonical AgentX snapshot primer', 'repetitions': 1,
        'routing_tuning': 'defaults; no weight tuning; only frontend router mode differs',
        'initial_cache': 'fresh worker processes before bounded smoke and canonical primer',
        'concurrent_work': 'Snapshot reserved on cp-0124; all routing Pods stay on cp-0198/cp-0942',
        'pull_secret_source_namespace': 'dynamo-ft-r610-1ec4908b-rr',
        'lease': str(LEASE.relative_to(ROOT)), 'lease_owner': OWNER}
    write(run.path / 'campaign.json', frozen)
    for mode in ['round-robin', 'kv']:
        write(run.path / ('deployment-' + mode + '.json'), generated(run, mode))
    paths = [Path(__file__), HERE / 'discovery.py', HERE / 'PLAN.md', ROOT / 'tests/routing/test_discovery.py',
        ROOT / 'configs/super-vl-tp2-lock.json', AGENTX / 'source-location.json',
        AGENTX / 'aiperf-dataset-revision.patch', AGENTX / 'prepare_agentx_cache.py',
        AGENTX / 'profile-c1.yaml', AGENTX / 'profile-c4.yaml']
    paths += [OLD / name for name in ['execute_pair.py', 'execute_router_pair.py', 'cluster.py',
        'qualify_client.py', 'analyze.py', 'PLAN.md', 'KV_EXTENSION_PLAN.md']]
    paths += list((OLD / 'router-extension-candidates').glob('two-worker-*-template.yaml'))
    paths += [ROOT / 'scripts' / name for name in ['testlib.py', 'storage_tests.py', 'serving_tests.py',
        'feature_tests.py', 'common_runtime_tests.py', 'common_runtime_build.py', 'gpu_claims.py']]
    location = json.loads((AGENTX / 'source-location.json').read_text())
    archive = Path(location['pinned_source_archive'])
    assert sha(archive) == location['pinned_source_sha256']
    paths += [archive]
    paths += [run.path / name for name in ['campaign.json', 'expected-probes.json', 'model-lock.json',
        'deployment-round-robin.json', 'deployment-kv.json']]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in paths})
    (run.path / 'campaign.sha256').write_text(sha(run.path / 'campaign.json') + '\n')
    verify(run)
    status(run, 'Frozen offline; no cluster resources created')


def verify(run):
    for name, expected in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert sha(ROOT / name) == expected, 'Frozen input changed: ' + name
    assert sha(run.path / 'campaign.json') == (run.path / 'campaign.sha256').read_text().strip()
    assert spec(run)['model_lock'] == run.state['model_lock'] and spec(run)['gpu_uuids_by_node'] == GPUS
    rr = json.loads((run.path / 'deployment-round-robin.json').read_text())
    kv = json.loads((run.path / 'deployment-kv.json').read_text())
    frontend = next(c for o in rr['items'] if o['kind'] == 'DynamoGraphDeployment'
                    for c in o['spec']['components'] if c['type'] == 'frontend')
    args = frontend['podTemplate']['spec']['containers'][0]['args']
    assert args[args.index('--router-mode') + 1] == 'round-robin'
    args[args.index('--router-mode') + 1] = 'kv'
    assert rr == kv, 'Deployment arms differ beyond frontend routing mode'


def copy_pull_secret(run):
    source = spec(run)['pull_secret_source_namespace']
    for ns in [source, run.ns]:
        obj = run.get('get', 'namespace', ns)
        assert obj['metadata']['labels']['app.kubernetes.io/managed-by'] == 'kubecon-dynamo-feature-tests'
    # Never persist the raw Secret through Run.command or a local payload.
    result = subprocess.run(run.kbase + ['get', 'secret', 'common-runtime-pull', '-n', source, '-o', 'json'],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Cannot read owned source image-pull credential (body not logged)')
    old = json.loads(result.stdout)
    assert old['type'] == 'kubernetes.io/dockerconfigjson'
    assert old['metadata']['labels']['feature-test-run'] == source
    found = run.k('get', 'secret', 'common-runtime-pull', '-n', run.ns,
                  '-o', 'jsonpath={.metadata.labels.feature-test-run}', check=False)
    assert found.returncode != 0 or found.stdout == run.ns
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'common-runtime-pull',
        'namespace': run.ns, 'labels': run.labels()}, 'type': old['type'], 'data': old['data']}
    for dry_run in [True, False]:
        run.k('apply', *(['--dry-run=server'] if dry_run else []), '-f', '-', input_text=json.dumps(obj))
    write(run.path / 'pull-secret-metadata.json', {'source_namespace': source,
        'source_uid': old['metadata']['uid'], 'target_namespace': run.ns, 'body_persisted': False})


def prepare(run):
    verify(run)
    assert not run.state['checks'].get('rrkv-cpu-prepared'), 'CPU preparation already attempted'
    prepare_storage(run)
    copy_pull_secret(run)
    for mode in ['round-robin', 'kv']:
        path = run.path / ('deployment-' + mode + '.json')
        run.k('apply', '--dry-run=client', '-f', str(path))
        run.k('apply', '--dry-run=server', '-f', str(path))
    program = '''import hashlib,importlib.metadata as m,json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK']);home=Path(os.environ['HF_HOME'])
model=home/'hub'/('models--'+lock['model'].replace('/','--'));root=model/'snapshots'/lock['revision']
assert (model/'refs/main').read_text().strip()==lock['revision'],'Offline model ref differs from pinned revision'
checks={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['config.json','tokenizer_config.json','model.safetensors.index.json']}
assert all(checks[name]==lock['model_metadata_sha256'][name] for name in checks)
files=set(json.loads((root/'model.safetensors.index.json').read_text())['weight_map'].values())
assert len(files)==88 and sum((root/name).stat().st_size for name in files)==int(os.environ['WEIGHT_BYTES'])
print(json.dumps({'metadata_sha256':checks,'weight_files':len(files),'weight_bytes':sum((root/name).stat().st_size for name in files),'offline_main_ref':lock['revision'],'packages':{name:m.version(name) for name in ['ai-dynamo','vllm','torch','transformers']}}))
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'rrkv-model-check'}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 300, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': CPU_NODE}, 'imagePullSecrets': [{'name': 'common-runtime-pull'}],
        'containers': [{'name': 'check', 'image': run.state['model_lock']['runtime_image'],
            'command': ['python3', '-c', program],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                {'name': 'HF_HOME', 'value': '/model-cache/feature-tests/20261015-super-vl-tp2/hf'},
                {'name': 'MODEL_LOCK', 'value': json.dumps(run.state['model_lock'])},
                {'name': 'WEIGHT_BYTES', 'value': str(spec(run)['checkpoint_weight_bytes'])}],
            'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'cpu': '2', 'memory': '4Gi'}},
            'volumeMounts': [{'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True}]}],
        'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    try:
        result = run.wait_pod('rrkv-model-check', completed=True, timeout=360)
        value = json.loads(run.k('logs', 'rrkv-model-check', '-n', run.ns).stdout)
        value['image_id'] = result['status']['containerStatuses'][0]['imageID']
        assert value['image_id'].endswith(run.state['model_lock']['runtime_image'].split('@')[1])
        write(run.path / 'runtime-inspection.json', value)
    finally:
        run.k('delete', 'pod', 'rrkv-model-check', '-n', run.ns, '--wait=true', '--timeout=90s')
    cluster.loadgen(run)
    client = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    write(run.path / 'client-identity.json', {'uid': client['metadata']['uid'], 'node': client['spec']['nodeName']})
    run.result('rrkv-cpu-prepared', 'passed', scope='Model/image/cache and admission checks; fresh CPU-only client')


def qualify_cpu(run):
    verify(run)
    assert run.state['checks']['rrkv-cpu-prepared']['status'] == 'passed'
    assert not run.state['checks'].get('rr-cpu-client-qualified'), 'Do not replay CPU qualification'
    previous = sys.argv
    sys.argv = [str(OLD / 'qualify_client.py'), '--run', str(run.path), '--attempt', 'a1']
    try:
        qualify_client.main()
    finally:
        sys.argv = previous
    run.state = json.loads((run.path / 'state.json').read_text())
    assert run.state['checks']['rr-cpu-client-qualified']['status'] == 'passed'


def lease_owned(run):
    value = json.loads((LEASE / 'owner.json').read_text())
    assert value['agent'] == OWNER and value['run'] == str(run.path) and value['namespace'] == run.ns


def allocation_available(run, arm):
    wanted = {uuid for pair in GPUS.values() for uuid in pair}
    slices = run.get('get', 'resourceslices')['items']
    identities = {}
    for item in slices:
        value = item['spec']
        if value.get('driver') != 'gpu.nvidia.com':
            continue
        for device in value.get('devices', []):
            attrs = device.get('attributes', device.get('basic', {}).get('attributes', {}))
            uuid = attrs.get('uuid', {}).get('string')
            if uuid in wanted:
                assert value['nodeName'] in GPUS and uuid in GPUS[value['nodeName']]
                identities[(value['pool']['name'], device['name'])] = uuid
    assert set(identities.values()) == wanted, 'Frozen GPUs are absent from current DRA inventory'
    claims = run.get('get', 'resourceclaims', '-A')['items']
    conflicts = []
    for claim in claims:
        for device in claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', []):
            uuid = identities.get((device.get('pool'), device.get('device')))
            if device.get('driver') == 'gpu.nvidia.com' and uuid:
                conflicts.append({'gpu_uuid': uuid, 'namespace': claim['metadata']['namespace'],
                                  'claim': claim['metadata']['name']})
    write(run.path / arm / 'allocation-preflight.json', {'at': e.now(), 'wanted_gpu_uuids': sorted(wanted),
        'conflicts': conflicts, 'scope': 'Only routing GPUs; unrelated Snapshot allocations are allowed'})
    assert not conflicts, 'A frozen routing GPU is already allocated: ' + repr(conflicts)


def verify_workers(run, arm, mode, pods):
    expected_items = json.loads((run.path / ('deployment-' + mode + '.json')).read_text())['items']
    expected = next(c for o in expected_items if o['kind'] == 'DynamoGraphDeployment'
                    for c in o['spec']['components'] if c['type'] == 'worker')['podTemplate']['spec']['containers'][0]
    probes = json.loads((run.path / 'expected-probes.json').read_text())
    seen = {}
    for pod in pods:
        verify_allocation(run, pod, pod['spec']['containers'][0], 2)
        name = pod['metadata']['name'];container = pod['spec']['containers'][0]
        assert container['args'] == expected['args'] and container['image'] == expected['image']
        assert all(container.get(key) == value for key, value in probes.items())
        assert all(v['restartCount'] == 0 and v['imageID'].endswith(spec(run)['model_lock']['runtime_image'].split('@')[1])
                   for v in pod['status']['containerStatuses'])
        logs = (run.path / arm / (name + '.log')).read_text()
        assert 'running in text-only mode' in logs
        assert sorted(set(re.findall(r'canary_wait_time_secs=(\d+)', logs))) == ['1']
        assert re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)', logs)
        node = pod['spec']['nodeName'];assert node in GPUS
        result = run.k('exec', name, '-n', run.ns, '-c', 'main', '--', 'nvidia-smi',
            '--query-gpu=index,uuid,name,memory.total,driver_version', '--format=csv,noheader')
        (run.path / arm / ('gpu-visible-' + name + '.csv')).write_text(result.stdout)
        uuids = sorted(line.split(',')[1].strip() for line in result.stdout.strip().splitlines())
        assert uuids == sorted(GPUS[node]) and all('H100' in line for line in result.stdout.splitlines())
        seen[node] = uuids
    assert set(seen) == set(GPUS)
    write(run.path / arm / 'worker-qualification.json', {'passed': True, 'gpu_uuids_by_node': seen,
        'worker_uids': [p['metadata']['uid'] for p in pods], 'text_only': True, 'native_context': 1048576,
        'effective_probes': probes, 'campaign_sha256': sha(run.path / 'campaign.json')})


def qualify_discovery(run, arm, mode, pods, smoke_ids):
    all_pods = json.loads((run.path / arm / 'pods.json').read_text())['items']
    frontend = next(p for p in all_pods if p['metadata']['name'].startswith('ft-agg-') and
                    p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component-type') == 'frontend')
    path = run.path / arm / (frontend['metadata']['name'] + '.log')
    proof = discovery.inspect(path.read_text(), [p['status']['podIP'] for p in pods], smoke_ids, mode)
    proof.update(frontend_uid=frontend['metadata']['uid'], current_frontend_log=str(path), log_sha256=sha(path))
    write(run.path / arm / 'discovery-qualification.json', proof)
    assert proof['passed'], proof['errors']


def seal_profile(run, base, pods, concurrency, arm, mode):
    value = ORIGINAL_SEAL_PROFILE(run, base, pods, concurrency, 2, arm, router_mode=mode,
        initial_gpu_cache='fresh worker processes before bounded smoke and canonical AgentX primer')
    value.update(campaign_sha256=sha(run.path / 'campaign.json'), text_only=True,
        gpu_uuids_by_node=GPUS, worker_configuration='qualified text-only/fast-health; unchanged batching/cache/kernel flags',
        policy_harness_sha256={p.name: sha(p) for p in [Path(__file__), HERE / 'discovery.py', HERE / 'PLAN.md']})
    write(run.path / arm / 'spec.json', value)
    return value


def cleanup_gpu(run, receipt=None):
    if not LEASE.exists():
        assert not e.workers(run) and not run.get('get', 'resourceclaims', '-n', run.ns)['items']
        return
    lease_owned(run)
    e.cleanup_gpu(run)
    objects = {kind: run.get('get', kind, '-n', run.ns)['items'] for kind in ['pods', 'resourceclaims', 'dgd']}
    workers = [p['metadata']['name'] for p in objects['pods'] if p['metadata']['name'].startswith('ft-agg-')]
    assert not workers and not objects['resourceclaims'] and not objects['dgd'] and not LEASE.exists()
    if receipt:
        write(run.path / receipt, {'at': e.now(), 'verified': True, 'worker_pods': [], 'resourceclaims': [],
            'graphs': [], 'scoped_lease_absent': True, 'scope': 'Only this routing namespace/reservation; Snapshot untouched'})


def batch(run, concurrency):
    verify(run)
    assert run.state['checks']['rr-cpu-client-qualified']['status'] == 'passed'
    intent = run.path / f'pair-c{concurrency}-started.json'
    with intent.open('x') as stream:
        json.dump({'at': e.now(), 'order': ['round-robin', 'kv'], 'campaign_sha256': sha(run.path / 'campaign.json')}, stream)
    for mode in ['round-robin', 'kv']:
        arm = f'routing-c{concurrency}-{mode}-a1'
        (run.path / arm).mkdir(exist_ok=False)
        e.acquire(run, 10800)
        try:
            assert not e.workers(run) and not run.get('get', 'resourceclaims', '-n', run.ns)['items']
            allocation_available(run, arm)
            path = run.path / ('deployment-' + mode + '.json')
            (run.path / arm / 'deployment.json').write_bytes(path.read_bytes())
            status(run, 'Starting fresh routing-policy workers', arm=arm)
            run.apply(json.loads(path.read_text())['items'])
            pods = e.wait_serving(run, 2, arm)
            e.collect_workers(run, arm)
            verify_workers(run, arm, mode, pods)
            base = e.endpoint(run)
            ids = e.smoke(run, base, 2, arm, require_distribution=mode == 'round-robin')
            e.collect_workers(run, arm)
            qualify_discovery(run, arm, mode, pods, ids)
            seal_profile(run, base, pods, concurrency, arm, mode)
            e.collect_frontend_metrics(run, base, arm, 'before')
            e.telemetry_start(run, pods, arm)
            try:
                e.launch_profile(run, arm)
                outcome = e.poll_profile(run, arm)
            finally:
                e.telemetry_stop(run, arm)
            e.collect_workers(run, arm)
            e.collect_frontend_metrics(run, base, arm, 'after')
            e.collect_profile(run, arm)
            assert outcome['exit_code'] == 0, outcome
            e.validate_profile(run, arm)
            run.result('policy-' + arm, 'passed', **outcome)
        except Exception as error:
            e.collect_workers(run, arm)
            run.result('policy-' + arm, 'failed', error=repr(error))
            raise
        finally:
            cleanup_gpu(run, 'after-' + arm + '-cleanup.json')
            folder = run.path / arm
            write(folder / 'integrity-final.json', {'sha256': {str(p.relative_to(folder)): sha(p)
                for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'}})
    previous = sys.argv
    sys.argv = [str(OLD / 'analyze.py'), '--run', str(run.path), '--concurrency', str(concurrency), '--attempt', 'a1', '--routing']
    try:
        runpy.run_path(str(OLD / 'analyze.py'), run_name='__main__')
    finally:
        sys.argv = previous
    run.result(f'rrkv-pair-c{concurrency}', 'passed', analysis=f'routing-c{concurrency}-a1-analysis.json')


def finalize(run):
    verify(run)
    assert all(run.state['checks'][f'rrkv-pair-c{c}']['status'] == 'passed' for c in [1, 4])
    cleanup_gpu(run)
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    identity = json.loads((run.path / 'client-identity.json').read_text())
    assert pod['metadata']['uid'] == identity['uid'] and pod['metadata']['labels']['feature-test-run'] == run.ns
    run.k('delete', 'pod', 'rr-loadgen', '-n', run.ns, '--wait=true', '--timeout=120s', timeout=150)
    for kind in ['pods', 'resourceclaims', 'dgd']:
        assert not run.get('get', kind, '-n', run.ns)['items'], kind
    write(run.path / 'qualification.json', {'passed': True, 'scope': 'One matched RR/KV pair at each of C1/C4',
        'campaign_sha256': sha(run.path / 'campaign.json'), 'cleanup_verified': True, 'scoped_lease_absent': not LEASE.exists()})
    status(run, 'Both routing-policy pairs complete, accepted and cleaned')
    write(run.path / 'evidence-sha256.json', {str(p.relative_to(run.path)): sha(p)
        for p in run.path.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'verify', 'prepare', 'qualify-cpu', 'batch-c1', 'batch-c4', 'cleanup', 'finalize'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = setup(args.run)
    if args.action == 'freeze':
        freeze(run)
        return
    verify(run)
    if args.action == 'verify':
        status(run, 'Frozen campaign inputs verified')
    elif args.action == 'prepare':
        prepare(run)
    elif args.action == 'qualify-cpu':
        qualify_cpu(run)
    elif args.action.startswith('batch-c'):
        batch(run, int(args.action[-1]))
    elif args.action == 'finalize':
        finalize(run)
    else:
        cleanup_gpu(run)


if __name__ == '__main__':
    main()
