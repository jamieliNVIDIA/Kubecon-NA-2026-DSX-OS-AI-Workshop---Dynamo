#!/usr/bin/env python3
"""Qualify operator-managed, same-node Snapshot recovery through one Dynamo frontend.

render/status/dry-run do not allocate GPUs. prepare creates CPU prerequisites;
deploy/verify/replace/cleanup require the caller's existing exclusive lease.
The caller owns lease acquisition/release and all shared-platform preparation.
"""
from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

import yaml

from testlib import ROOT, Run
from serving_tests import frontend, model_cache_home

GRAPH = 'ft-snapshot'
COMPONENT = 'VllmSnapshotWorker'
LEASE_OWNER = 'workshop-snapshot-dgd'
TEMPLATE = ROOT / 'configs/dgd/snapshot-super-vl-tp2-r610/nemotron-snapshot.yaml'
DEFAULT_MODULE = '/usr/local/lib/python3.12/dist-packages/dynamo/vllm/snapshot.py'
SPEC_FILE = 'snapshot-dgd-spec.json'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def condition(obj, name):
    return next((c for c in obj.get('status', {}).get('conditions', [])
                 if c.get('type') == name and c.get('status') == 'True'), None)


def timestamp(value):
    # Kubernetes timestamps may have nanosecond precision on a Python 3.9 host.
    value = re.sub(r'(\.\d{6})\d+', r'\1', value)
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def elapsed(start, end):
    return (timestamp(end) - timestamp(start)).total_seconds()


def owned(obj, namespace):
    labels = obj.get('metadata', {}).get('labels', {})
    if labels.get('feature-test-run') != namespace:
        raise ValueError('Refusing an unowned resource: ' + obj.get('metadata', {}).get('name', '?'))
    return obj


def owned_checkpoint_job(run, job):
    """Retain-mode SnapshotJobs use an owner-UID annotation, not run labels."""
    metadata = job['metadata']
    labels = metadata.get('labels', {})
    owner_uid = metadata.get('annotations', {}).get('nvidia.com/dynamo-checkpoint-owner-uid')
    controlled = any(o.get('uid') == run.state.get('snapshot_dgd_uid')
                     for o in metadata.get('ownerReferences', []))
    if (metadata.get('namespace') != run.ns or labels.get('nvidia.com/dynamo-graph-deployment-name') != GRAPH
            or labels.get('nvidia.com/dynamo-component') != COMPONENT
            or not run.state.get('snapshot_dgd_uid')
            or (owner_uid != run.state['snapshot_dgd_uid'] and not controlled)):
        raise ValueError('SnapshotJob does not belong to the recorded DGD UID.')
    recorded = run.state.get('snapshot_job_uid')
    if recorded and metadata['uid'] != recorded:
        raise ValueError('Operator SnapshotJob identity changed.')
    return job


def require_lease(run):
    from demos.common.runtime import LEASE
    try:
        owner = json.loads((LEASE / 'owner.json').read_text())
    except (FileNotFoundError, ValueError):
        raise RuntimeError('Caller must acquire the workshop-snapshot-dgd GPU lease first.')
    if owner.get('agent') != LEASE_OWNER or owner.get('run') != str(run.path.resolve()):
        raise RuntimeError('Foreign GPU lease; no GPU action is authorized by this harness.')


def render_objects(namespace, lock, settings, template=None):
    """Pure renderer: no writes, Run methods, cluster queries or lease changes."""
    if lock.get('tensor_parallel_size') != 2 or lock.get('gpu_allocation') != 'dra':
        raise ValueError('This qualification requires the pinned TP2 DRA runtime.')
    uuids = settings['gpu_uuids']
    if len(uuids) != 2 or len(set(uuids)) != 2 or not all(re.fullmatch(r'GPU-[a-fA-F0-9-]+', u) for u in uuids):
        raise ValueError('Supply exactly two distinct physical GPU UUIDs.')
    if not re.fullmatch(r'[a-f0-9]{64}', settings['patch_sha256']):
        raise ValueError('An exact snapshot.py SHA256 is required.')
    source = copy.deepcopy(template) if template is not None else yaml.safe_load(TEMPLATE.read_text())
    graph = next(o for o in source['items'] if o['kind'] == 'DynamoGraphDeployment')
    labels = {'app.kubernetes.io/managed-by': 'kubecon-dynamo-feature-tests', 'feature-test-run': namespace}
    graph['metadata'] = {'name': GRAPH, 'namespace': namespace, 'labels': labels,
                         'annotations': {'nvidia.com/enable-grove': 'false'}}
    claim_name = GRAPH + '-snapshot-gpus'
    for component in graph['spec']['components']:
        component['replicas'] = 1
        component['runtimeVersionOverride'] = lock['runtime_version_override']
        pod = component['podTemplate']
        pod['metadata'] = {'labels': copy.deepcopy(labels)}
        spec = pod['spec']
        spec.pop('activeDeadlineSeconds', None)
        spec.pop('resourceClaims', None)
        spec['nodeSelector'] = {'kubernetes.io/hostname': settings['node']}
        spec['volumes'] = [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                           {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}}]
        main = spec['containers'][0]
        spec['containers'] = [main]
        main['image'] = lock['runtime_image']
        main['volumeMounts'] = [{'name': 'cache', 'mountPath': '/model-cache'},
                               {'name': 'shm', 'mountPath': '/dev/shm'}]
        env = {'HF_HOME': settings['cache_home'], 'HF_HUB_OFFLINE': '1',
               'HF_HUB_DISABLE_XET': '1', 'HF_MODULES_CACHE': '/tmp/hf_modules',
               'VLLM_CACHE_ROOT': '/tmp/vllm', 'TRITON_CACHE_DIR': '/tmp/triton',
               'NCCL_IB_DISABLE': '1', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT': '180'}
        if component['type'] == 'frontend':
            main['command'] = ['python3', '-m', 'dynamo.frontend']
            main['args'] = ['--router-mode', 'round-robin', '--trust-remote-code']
            env['NVIDIA_VISIBLE_DEVICES'] = 'void'
        else:
            component['name'] = COMPONENT
            component['experimental'] = {'checkpoint': {'enabled': True,
                'startupPolicy': 'WaitForCheckpoint', 'deletionPolicy': 'Retain'}}
            pod['metadata']['annotations'] = {'nvidia.com/snapshot-multi-gpu': 'enabled'}
            main['command'] = ['python3', '-m', 'dynamo.vllm']
            main['args'] = ['--model', lock['model'], '--revision', lock['revision'],
                '--served-model-name', lock['model'], '--trust-remote-code', '--tensor-parallel-size', '2',
                '--max-model-len', '8192', '--max-num-seqs', '4', '--max-num-batched-tokens', '8192',
                '--gpu-memory-utilization', '0.65', '--enable-prefix-caching', '--block-size', '64',
                '--mamba-backend', 'flashinfer', '--mamba-ssm-cache-dtype', 'float16',
                '--mamba-cache-mode', 'align', '--reasoning-parser', 'nemotron_v3',
                '--disaggregation-mode', 'agg', '--language-model-only']
            env.update(VLLM_WORKER_MULTIPROC_METHOD='spawn', NCCL_RAS_ENABLE='0',
                TORCH_NCCL_ENABLE_MONITORING='0', TORCH_NCCL_DUMP_ON_TIMEOUT='0', VLLM_NO_USAGE_STATS='1')
            main['resources'] = {'requests': {'cpu': '8', 'memory': '256Gi'},
                'limits': {'memory': '512Gi'}, 'claims': [{'name': 'gpu-main'}]}
            main['volumeMounts'].append({'name': 'snapshot-runtime', 'mountPath': settings['module_path'],
                'subPath': 'snapshot.py', 'readOnly': True})
            spec['volumes'].append({'name': 'snapshot-runtime', 'configMap': {'name': settings['patch_configmap']}})
            spec['resourceClaims'] = [{'name': 'gpu-main', 'resourceClaimTemplateName': claim_name}]
            spec.setdefault('securityContext', {})['seccompProfile'] = {
                'type': 'Localhost', 'localhostProfile': 'profiles/block-iouring.json'}
            # The pinned operator copies only main from the serving template.
            # Add this CPU helper through the explicit capture-Job override,
            # so it survives source publication and never appears in serving Pods.
            helper = {'name': 'capture-keepalive', 'image': lock['runtime_image'],
                'command': ['/bin/sh', '-c',
                    "trap 'exit 0' TERM INT; while [ ! -f /tmp/finish-source ]; do sleep 2 & wait \"$!\"; done"],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                    {'name': 'SNAPSHOT_JOB_NAME', 'valueFrom': {'fieldRef': {
                        'fieldPath': "metadata.labels['nvidia.com/snapshot-job']"}}}],
                'resources': {'requests': {'cpu': '25m', 'memory': '16Mi'}, 'limits': {'memory': '64Mi'}}}
            component['experimental']['checkpoint']['job'] = {
                'podTemplate': {'spec': {'containers': [helper]}}}
        main['env'] = [{'name': name, 'value': value} for name, value in env.items()]
    # Both the source capture and every serving replacement use this selector.
    expression = ('device.driver == "gpu.nvidia.com" && '
                  'has(device.attributes["gpu.nvidia.com"].uuid) && '
                  'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids))
    claim = {'apiVersion': 'resource.k8s.io/v1', 'kind': 'ResourceClaimTemplate',
        'metadata': {'name': claim_name, 'namespace': namespace, 'labels': copy.deepcopy(labels)},
        'spec': {'spec': {'devices': {'requests': [{'name': 'gpu', 'exactly': {
            'deviceClassName': 'gpu.nvidia.com', 'count': 2, 'selectors': [{'cel': {'expression': expression}}]}}]}}}}
    return [claim, graph]


def load_spec(run):
    spec = json.loads((run.path / SPEC_FILE).read_text())
    if spec['namespace'] != run.ns or spec['model_lock'] != run.state['model_lock']:
        raise ValueError('Frozen namespace/model lock changed.')
    if sha256(TEMPLATE.read_bytes()) != spec['template_sha256']:
        raise ValueError('Source template changed; use a fresh run.')
    raw = (run.path / 'deployment.json').read_bytes()
    if sha256(raw) != spec['manifest_sha256']:
        raise ValueError('Frozen deployment changed; use a fresh run.')
    return spec


def freeze(run, settings):
    objects = render_objects(run.ns, run.state['model_lock'], settings)
    body = (json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}, indent=2) + '\n').encode()
    value = {'schema': 1, 'namespace': run.ns, 'model_lock': run.state['model_lock'], 'settings': settings,
             'template_sha256': sha256(TEMPLATE.read_bytes()), 'manifest_sha256': sha256(body)}
    if (run.path / SPEC_FILE).exists():
        previous = load_spec(run)
        if previous != value:
            raise ValueError('Settings changed; use a fresh run.')
        return previous
    (run.path / 'deployment.json').write_bytes(body)
    (run.path / 'deployment.yaml').write_text(yaml.safe_dump(json.loads(body), sort_keys=False))
    write_json(run.path / SPEC_FILE, value)
    run.state.setdefault('graphs', {})['snapshot'] = {'name': GRAPH, 'manifest': str(run.path / 'deployment.yaml')}
    run.save()
    return value


def check_patch(run, spec):
    settings = spec['settings']
    config = owned(run.get('get', 'configmap', settings['patch_configmap'], '-n', run.ns), run.ns)
    if not config.get('immutable') or sha256(config.get('data', {}).get('snapshot.py', '').encode()) != settings['patch_sha256']:
        raise ValueError('Need the exact immutable runtime patch ConfigMap.')
    return config


def cache_probe_program():
    """Run the pinned runtime's actual metadata resolver in the CPU-only probe."""
    return '''import asyncio,hashlib,json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK'])
assert os.environ.get('HF_HUB_OFFLINE')=='1','Metadata preflight must run offline'
model_root=Path(os.environ['HF_HOME'])/'hub'/('models--'+lock['model'].replace('/','--'))
root=model_root/'snapshots'/lock['revision']
ref_path=model_root/'refs/main'
if not ref_path.is_file():
 raise RuntimeError('Missing metadata refs/main; prepare and review the owned cache before deployment')
metadata_ref=ref_path.read_text().strip()
if metadata_ref!=lock['revision']:
 raise RuntimeError('Metadata refs/main differs from locked revision: '+metadata_ref)
index=json.loads((root/'model.safetensors.index.json').read_text())
weights=sorted(set(index['weight_map'].values()))
sizes={n:(root/n).stat().st_size for n in weights}
assert len(sizes)==lock['checkpoint_weight_files'] and all(sizes.values())
assert sum(sizes.values())==int(os.environ['EXPECTED_BYTES'])
for n in ('config.json','tokenizer_config.json','model.safetensors.index.json'):
 assert hashlib.sha256((root/n).read_bytes()).hexdigest()==lock['model_metadata_sha256'][n],n
# The engine loads an explicit revision, but registration calls this resolver
# without one. Verify its real behavior rather than just inspecting shard files.
from dynamo.common.model_fetch import fetch_model
resolved=Path(asyncio.run(fetch_model(lock['model']))).resolve()
if resolved!=root.resolve():
 raise RuntimeError('Offline metadata resolver selected an unexpected snapshot: '+str(resolved))
print(json.dumps({'weight_files':len(sizes),'weight_bytes':sum(sizes.values()),
 'model':lock['model'],'revision':lock['revision'],'metadata_ref':metadata_ref,
 'metadata_ref_path':str(ref_path),'resolved_model_path':str(resolved),
 'offline':'1','metadata_resolver':'dynamo.common.model_fetch.fetch_model'}))
'''


def validate_cache_receipt(receipt, lock, cache_home):
    expected = str(Path(cache_home) / 'hub' / ('models--' + lock['model'].replace('/', '--')) / 'snapshots' / lock['revision'])
    if (receipt.get('status') != 'passed' or receipt.get('model') != lock['model']
            or receipt.get('revision') != lock['revision'] or receipt.get('metadata_ref') != lock['revision']
            or receipt.get('resolved_model_path') != expected or receipt.get('offline') != '1'
            or receipt.get('metadata_resolver') != 'dynamo.common.model_fetch.fetch_model'):
        raise ValueError('Pass CPU preparation with exact offline metadata resolution before GPU deployment.')


def prepare(run, spec, baseline):
    """CPU-only namespace, checkpoint mount, registry auth and model-cache verification."""
    from storage_tests import prepare as storage
    from common_runtime_tests import pull_secret
    from snapshot_tp2_workflow import cpu_probe
    old = json.loads((baseline / 'state.json').read_text())
    lock = run.state['model_lock']
    for key in ('model', 'revision', 'runtime_image', 'tensor_parallel_size'):
        if old['model_lock'][key] != lock[key]:
            raise ValueError('Cache baseline identity differs: ' + key)
    if old.get('checks', {}).get('model-staging', {}).get('status') != 'passed':
        raise ValueError('Cache baseline has no passing staging receipt.')
    cache_source = old.get('model_cache_run_id', old['run_id'])
    expected_home = '/model-cache/feature-tests/' + cache_source + '/hf'
    if expected_home != spec['settings']['cache_home']:
        raise ValueError('Frozen cache path differs from baseline.')
    run.state['model_cache_run_id'] = cache_source
    run.save()
    storage(run)
    pull_secret(run)
    report = cpu_probe(run, 'snapshot-dgd-cache-check', cache_probe_program(),
        [{'name': 'MODEL_LOCK', 'value': json.dumps(lock)},
         {'name': 'EXPECTED_BYTES', 'value': str(old['checks']['model-staging']['weight_bytes'])},
         {'name': 'HF_HOME', 'value': expected_home}, {'name': 'HF_HUB_OFFLINE', 'value': '1'}], cache=True)
    validate_cache_receipt({'status': 'passed', **report}, lock, expected_home)
    run.result('model-staging', 'passed', **report, cache_source=cache_source,
               scope='CPU-only exact shards/metadata/ref and actual offline Dynamo metadata resolution; no cache repair or model download')


def dry_run(run, spec):
    body = (run.path / 'deployment.json').read_text()
    run.k('apply', '--dry-run=client', '-f', '-', input_text=body)
    run.k('apply', '--dry-run=server', '-f', '-', input_text=body)
    run.result('snapshot-dgd-admission', 'passed', scope='Admission only; no GPU allocation or DGD created')


def deploy(run, spec):
    require_lease(run)
    check_patch(run, spec)
    validate_cache_receipt(run.state.get('checks', {}).get('model-staging', {}),
                           spec['model_lock'], spec['settings']['cache_home'])
    if run.state.get('snapshot_dgd_submitted_at'):
        raise ValueError('Deployment was already submitted; inspect/resume verification, never replay startup.')
    existing = run.k('get', 'dgd', GRAPH, '-n', run.ns, '-o', 'json', check=False)
    if existing.returncode == 0:
        raise ValueError('Graph already exists; do not adopt or overwrite a deployment.')
    if 'NotFound' not in existing.stderr:
        raise RuntimeError(existing.stderr)
    dry_run(run, spec)
    run.state['snapshot_dgd_submitted_at'] = now()
    run.save()
    run.apply(json.loads((run.path / 'deployment.json').read_text())['items'])
    graph = owned(run.get('get', 'dgd', GRAPH, '-n', run.ns), run.ns)
    run.state['snapshot_dgd_uid'] = graph['metadata']['uid']
    run.save()
    run.result('snapshot-dgd-deployment', 'submitted', uid=graph['metadata']['uid'])


def inventory(run):
    data = {'observed_at': now()}
    for kind in ('dgd', 'pods', 'services', 'deployments', 'replicasets', 'snapshotjobs', 'podsnapshots', 'resourceclaims'):
        data[kind] = run.get('get', kind, '-n', run.ns)
    write_json(run.path / ('inventory-' + str(time.time_ns()) + '.json'), data)
    return data


def collect_logs(run, data=None, phase='diagnostic'):
    """Save actual workload/controller logs before explicit workload cleanup."""
    if data is None:
        data = inventory(run)
    for pod in data['pods']['items']:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            continue
        for container in pod['spec'].get('containers', []):
            result = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', container['name'],
                           '--timestamps=true', check=False, timeout=90)
            name = phase + '-' + pod['metadata']['uid'] + '-' + container['name'] + '.log'
            (run.path / name).write_text(result.stdout + result.stderr)
    system = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    for pod in system:
        name = pod['metadata']['name']
        if not ('snapshot-agent' in name or 'snapshot-operator' in name or 'dynamo-operator' in name):
            continue
        if 'snapshot-agent' in name and pod['spec'].get('nodeName') != run.state.get('snapshot_dgd_node'):
            continue
        for container in pod['spec'].get('containers', []):
            result = run.k('logs', name, '-n', 'dynamo-system', '-c', container['name'],
                           '--timestamps=true', '--tail=3000', check=False, timeout=90)
            (run.path / (phase + '-' + name + '-' + container['name'] + '.log')).write_text(result.stdout + result.stderr)


def checkpoint_state(run, data, before_source_release=None):
    if run.state.get('snapshot_dgd_storage_gate') == 'nvme' and before_source_release is None:
        raise ValueError('This run requires its NVMe staging callback before source release.')
    graph = owned(next(g for g in data['dgd']['items'] if g['metadata']['name'] == GRAPH), run.ns)
    if graph['metadata']['uid'] != run.state['snapshot_dgd_uid']:
        raise ValueError('DGD identity changed.')
    entry = graph.get('status', {}).get('checkpoints', {}).get(COMPONENT, {})
    name = entry.get('checkpointName')
    if not name:
        return graph, None, None
    job = next((j for j in data['snapshotjobs']['items'] if j['metadata']['name'] == name), None)
    if job:
        owned_checkpoint_job(run, job)
        if not run.state.get('snapshot_job_uid'):
            run.state['snapshot_job_uid'] = job['metadata']['uid']
            run.state['snapshot_job_name'] = job['metadata']['name']
            run.save()
    if job and condition(job, 'Failed'):
        raise RuntimeError('Operator checkpoint capture failed: ' + json.dumps(job['status']))
    if job:
        validate_capture_layout(job)
        for pod in data['pods']['items']:
            if pod['metadata'].get('labels', {}).get('nvidia.com/snapshot-job') == name:
                if len([c for c in pod['spec'].get('containers', []) if c['name'] == 'capture-keepalive']) != 1:
                    raise ValueError('Operator source Pod lacks its capture-only keepalive helper; stop before capture.')
    snapshot = next((s for s in data['podsnapshots']['items'] if s['metadata']['name'] == name), None)
    if not snapshot or not condition(snapshot, 'Ready'):
        return graph, None, None
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    if not condition(content, 'Ready'):
        return graph, None, None
    # Keep the capture helper's GPU reservation until optional storage staging
    # finishes. Raising here prevents an unqualified first restore.
    if before_source_release is not None:
        before_source_release(run, snapshot, content)
    if job:
        if not run.state.get('capture_logs_saved'):
            collect_logs(run, data, phase='capture')
            run.state['capture_logs_saved'] = now()
            run.save()
        finish_source(run, data, job, snapshot)
    if not entry.get('ready'):
        return graph, None, None
    write_json(run.path / 'captured-snapshot.json', snapshot)
    write_json(run.path / 'captured-content.json', content)
    return graph, snapshot, content


def validate_capture_layout(job):
    """Fail early if the operator dropped the capture-only publication helper."""
    if job['spec'].get('podSnapshotTemplate', {}).get('targetContainers') != ['main']:
        raise ValueError('Operator SnapshotJob must capture only main, excluding the keepalive helper.')
    helpers = [c for c in job['spec'].get('podTemplate', {}).get('spec', {}).get('containers', [])
               if c['name'] == 'capture-keepalive']
    if len(helpers) != 1:
        raise ValueError('Operator SnapshotJob lacks its capture-only keepalive helper; stop before capture.')
    helper = helpers[0]
    resources = helper.get('resources', {})
    if resources.get('claims') or any(k == 'nvidia.com/gpu' for group in ('requests', 'limits')
                                     for k in resources.get(group, {})):
        raise ValueError('Capture keepalive must be CPU-only.')


def finish_source(run, data, job, snapshot):
    """Release only the owned CPU helper after the durable artifact is Ready."""
    if not condition(snapshot, 'Ready'):
        raise ValueError('Cannot finish a source before durable snapshot readiness.')
    if condition(job, 'Completed'):
        return
    for pod in data['pods']['items']:
        if pod['metadata'].get('labels', {}).get('nvidia.com/snapshot-job') != job['metadata']['name']:
            continue
        owned(pod, run.ns)
        if pod.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
            continue
        if not any(o.get('kind') == 'Job' and o.get('uid') == job.get('status', {}).get('sourceJobUID')
                   for o in pod['metadata'].get('ownerReferences', [])):
            raise ValueError('Source Pod does not belong to this checkpoint source Job.')
        containers = {c['name']: c for c in pod.get('status', {}).get('containerStatuses', [])}
        helper = containers.get('capture-keepalive', {})
        if helper.get('state', {}).get('terminated'):
            continue
        if not helper.get('state', {}).get('running'):
            raise ValueError('Source helper is not running after durable capture.')
        run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'capture-keepalive', '--',
              '/usr/bin/touch', '/tmp/finish-source')
        run.result('snapshot-dgd-source-helper', 'completed', pod_uid=pod['metadata']['uid'],
                   snapshot_uid=snapshot['metadata']['uid'], scope='Only CPU keepalive stopped after durable artifact Ready')


def serving_pods(data):
    pods = [p for p in data['pods']['items'] if not p['metadata'].get('deletionTimestamp')
            and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
            and 'nvidia.com/snapshot-job' not in p['metadata'].get('labels', {})]
    workers = [p for p in pods if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component') == COMPONENT]
    frontends = [p for p in pods if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component') == 'Frontend']
    services = [s for s in data['services']['items'] if s['metadata']['name'].startswith(GRAPH + '-')
                and any(p.get('port') == 8000 for p in s['spec'].get('ports', []))]
    if len(workers) != 1 or len(frontends) != 1 or len(services) != 1:
        return None
    return workers[0], frontends[0], services[0]


def allocated_uuids(run, pod):
    from gpu_claims import verify_allocation
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, pod, main, 2)
    write_json(run.path / ('claim-' + pod['metadata']['uid'] + '.json'), claim)
    slices = run.get('get', 'resourceslices')['items']
    devices = {}
    for item in slices:
        spec = item['spec']
        for device in spec.get('devices', []):
            attrs = device.get('attributes', {})
            value = next((v.get('string') for k, v in attrs.items() if k == 'uuid' or k.endswith('/uuid')), None)
            devices[(spec['driver'], spec['pool']['name'], device['name'])] = value
    results = claim['status']['allocation']['devices']['results']
    values = [devices.get((r['driver'], r['pool'], r['device'])) for r in results]
    if not all(values):
        raise ValueError('Cannot prove allocated physical GPU UUIDs from live ResourceSlices.')
    return sorted(values)


def controller_lineage(run, pod):
    """Prove the serving Pod is controlled by this DGD, retaining exact UIDs."""
    chain = []
    obj = pod
    for _ in range(6):
        owners = [o for o in obj['metadata'].get('ownerReferences', []) if o.get('controller')]
        if len(owners) != 1:
            raise ValueError('Serving Pod must have one unambiguous controller lineage.')
        owner = owners[0]
        chain.append({k: owner[k] for k in ('kind', 'name', 'uid')})
        if owner['kind'] == 'DynamoGraphDeployment':
            if owner['uid'] != run.state['snapshot_dgd_uid']:
                raise ValueError('Serving Pod belongs to another DGD UID.')
            return chain
        if owner['kind'] not in ('ReplicaSet', 'Deployment', 'DynamoComponentDeployment'):
            raise ValueError('Unexpected serving Pod controller: ' + owner['kind'])
        obj = run.get('get', owner['kind'], owner['name'], '-n', run.ns)
        if obj['metadata']['uid'] != owner['uid']:
            raise ValueError('Serving controller identity changed during verification.')
    raise ValueError('Serving controller lineage did not reach the recorded DGD.')


def validate_worker(run, spec, worker, snapshot, content, frontend_pod, service, baseline=None):
    for obj in (worker, frontend_pod):
        owned(obj, run.ns)
        if not condition(obj, 'Ready') or any(c.get('restartCount', 0) for c in obj['status']['containerStatuses']):
            raise ValueError('Need Ready worker/frontend with no container restarts.')
    uid = worker['metadata']['uid']
    source_uid = content['spec']['source']['podRef']['uid']
    if uid == source_uid or worker['metadata'].get('annotations', {}).get('nvidia.com/restore-from') != snapshot['metadata']['name']:
        raise ValueError('Serving worker must be a new Pod restored from the operator checkpoint.')
    if not condition(worker, 'nvidia.com/Restored'):
        raise ValueError('Serving worker lacks nvidia.com/Restored=True.')
    main = next(c for c in worker['status']['containerStatuses'] if c['name'] == 'main')
    if main['imageID'].split('@')[-1] != spec['model_lock']['runtime_image'].split('@')[-1]:
        raise ValueError('Restored runtime image changed.')
    if worker['spec']['nodeName'] != spec['settings']['node']:
        raise ValueError('Restore moved to another node.')
    uuids = allocated_uuids(run, worker)
    if uuids != sorted(spec['settings']['gpu_uuids']):
        raise ValueError('Restored physical GPU pair changed.')
    identity = {'dgd_uid': run.state['snapshot_dgd_uid'], 'worker_name': worker['metadata']['name'],
        'worker_uid': uid, 'frontend_uid': frontend_pod['metadata']['uid'], 'service_uid': service['metadata']['uid'],
        'service_name': service['metadata']['name'], 'checkpoint_name': snapshot['metadata']['name'],
        'checkpoint_uid': snapshot['metadata']['uid'], 'content_uid': content['metadata']['uid'],
        'source_uid': source_uid, 'node': worker['spec']['nodeName'], 'gpu_uuids': uuids,
        'pod_created_at': worker['metadata']['creationTimestamp'],
        'restored_at': condition(worker, 'nvidia.com/Restored')['lastTransitionTime'],
        'ready_at': condition(worker, 'Ready')['lastTransitionTime']}
    identity['controller_lineage'] = controller_lineage(run, worker)
    if baseline:
        for key in ('dgd_uid', 'frontend_uid', 'service_uid', 'checkpoint_name', 'checkpoint_uid', 'content_uid', 'source_uid', 'node', 'gpu_uuids'):
            if identity[key] != baseline[key]:
                raise ValueError('Recovery identity changed: ' + key)
        if uid == baseline['worker_uid']:
            raise ValueError('Replacement must have a different Pod UID.')
    return identity


def validate_coding_output(content):
    text = content.strip()
    if text.startswith('```') and text.endswith('```'):
        text = '\n'.join(text.splitlines()[1:-1])
    tree = ast.parse(text)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'add']
    if len(functions) != 1 or [a.arg for a in functions[0].args.args] != ['a', 'b']:
        raise ValueError('Expected a Python add(a, b) function.')
    returns = [n for n in ast.walk(functions[0]) if isinstance(n, ast.Return)]
    if len(returns) != 1 or ast.dump(returns[0].value) != ast.dump(ast.parse('a + b', mode='eval').body):
        raise ValueError('Expected add to return a + b.')
    return text


def coding_request(base, model, timeout=180):
    payload = {'model': model, 'messages': [{'role': 'user', 'content':
        'Write a short Python function add(a, b) that returns their sum. Reply with code only.'}],
        'temperature': 0, 'max_completion_tokens': 64, 'chat_template_kwargs': {'enable_thinking': False},
        'stream': True, 'stream_options': {'include_usage': True}, 'nvext': {'extra_fields': ['worker_id', 'timing']}}
    req = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    started = now()
    deadline = time.monotonic() + timeout
    chunks, lines, done = [], [], False
    with urllib.request.urlopen(req, timeout=timeout) as response:
        for raw in response:
            if time.monotonic() > deadline:
                raise TimeoutError('Coding request exceeded its total stream deadline.')
            line = raw.decode().strip()
            lines.append(line)
            if line == 'data: [DONE]':
                done = True
            elif line.startswith('data: '):
                chunks.append(json.loads(line[6:]))
    if not done or not chunks or any(c.get('error') for c in chunks):
        raise ValueError('Stream did not complete successfully.')
    if any(c.get('model') not in (None, model) for c in chunks):
        raise ValueError('Unexpected model in completion stream.')
    if not any(choice.get('finish_reason') == 'stop' for c in chunks for choice in c.get('choices', [])):
        raise ValueError('Expected successful stop finish reason.')
    content = ''.join(choice.get('delta', {}).get('content') or '' for c in chunks for choice in c.get('choices', []))
    worker = next((c['nvext']['worker_id'] for c in reversed(chunks) if c.get('nvext', {}).get('worker_id')), None)
    if not worker or not worker.get('decode_worker_id'):
        raise ValueError('Completion omitted Dynamo worker identity.')
    return {'started_at': started, 'completed_at': now(), 'request': payload, 'chunks': chunks,
        'sse': '\n'.join(lines), 'content': validate_coding_output(content), 'worker': worker}


def verify(run, spec, timeout=3600, baseline=None, before_source_release=None):
    require_lease(run)
    check_patch(run, spec)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = inventory(run)
        graph, snapshot, content = checkpoint_state(run, data, before_source_release)
        serving = serving_pods(data)
        if snapshot and serving and condition(graph, 'Ready') and all(condition(p, 'Ready') for p in serving[:2]):
            worker, front, service = serving
            if baseline and worker['metadata']['uid'] == baseline['worker_uid']:
                time.sleep(5)
                continue
            identity = validate_worker(run, spec, worker, snapshot, content, front, service, baseline)
            with frontend(run, 'snapshot') as base:
                with urllib.request.urlopen(base + '/v1/models', timeout=30) as response:
                    models = json.load(response)
                if spec['model_lock']['model'] not in [m['id'] for m in models.get('data', [])]:
                    raise ValueError('Expected restored model is not advertised by frontend.')
                request = coding_request(base, spec['model_lock']['model'])
            if baseline and request['worker']['decode_worker_id'] == baseline['response_worker']['decode_worker_id']:
                raise ValueError('Frontend response retained the previous worker identity.')
            identity['response_worker'] = request['worker']
            identity['first_success_at'] = request['completed_at']
            phase = 'replacement' if baseline else 'initial'
            write_json(run.path / (phase + '-identity.json'), identity)
            write_json(run.path / (phase + '-request.json'), request)
            collect_logs(run, data, phase=phase)
            if baseline:
                fault = run.state['replacement_intent']['requested_at']
                timing = {'fault_requested_at': fault, 'pod_created_at': identity['pod_created_at'],
                    'restored_at': identity['restored_at'], 'ready_at': identity['ready_at'],
                    'first_success_at': identity['first_success_at'],
                    'fault_to_first_success_seconds': elapsed(fault, identity['first_success_at']),
                    'pod_to_ready_seconds': elapsed(identity['pod_created_at'], identity['ready_at']),
                    'scope': 'Same-node replacement through unchanged Dynamo frontend; no in-flight request or prefix-cache recovery.'}
                write_json(run.path / 'replacement-timing.json', timing)
            run.result('snapshot-dgd-' + phase, 'passed', **identity)
            return identity
        time.sleep(5)
    raise TimeoutError('No fully restored Dynamo service within the bounded verification window.')


def replace(run, spec, timeout=1800, before_source_release=None):
    require_lease(run)
    baseline = json.loads((run.path / 'initial-identity.json').read_text())
    pending = run.state.get('replacement_intent')
    if not pending:
        worker = owned(run.get('get', 'pod', baseline['worker_name'], '-n', run.ns), run.ns)
        if worker['metadata']['uid'] != baseline['worker_uid']:
            raise ValueError('Original worker changed before deletion; refuse to delete another Pod.')
        graph = owned(run.get('get', 'dgd', GRAPH, '-n', run.ns), run.ns)
        if graph['metadata']['uid'] != baseline['dgd_uid']:
            raise ValueError('Original DGD identity changed.')
        # UID preconditions close the name-reuse race between inspection and delete.
        run.state['replacement_intent'] = {'requested_at': now(), 'pod_name': baseline['worker_name'],
            'pod_uid': baseline['worker_uid'], 'delete_submitted': False}
        run.save()
        options = {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                   'preconditions': {'uid': baseline['worker_uid']}}
        run.k('delete', '--raw', '/api/v1/namespaces/' + run.ns + '/pods/' + baseline['worker_name'],
              '-f', '-', input_text=json.dumps(options), timeout=90)
        run.state['replacement_intent']['delete_submitted'] = True
        run.save()
    elif (run.path / 'replacement-identity.json').exists():
        raise ValueError('Replacement already qualified; use a fresh run for another fault.')
    elif not pending['delete_submitted']:
        found = run.k('get', 'pod', pending['pod_name'], '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0 and json.loads(found.stdout)['metadata']['uid'] == pending['pod_uid']:
            raise RuntimeError('Deletion intent is uncertain and original Pod still exists; inspect before resuming.')
    return verify(run, spec, timeout=timeout, baseline=baseline,
                  before_source_release=before_source_release)


def cleanup_plan(run):
    """Persist source ownership before deleting any parent or orphaning children."""
    path = run.path / 'cleanup-plan.json'
    if path.exists():
        plan = json.loads(path.read_text())
        if plan['namespace'] != run.ns or plan['dgd_uid'] != run.state['snapshot_dgd_uid']:
            raise ValueError('Recorded cleanup plan belongs to another DGD/namespace.')
        return plan
    parents = []
    for job in run.get('get', 'snapshotjobs', '-n', run.ns)['items']:
        if job['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') != GRAPH:
            continue
        owned_checkpoint_job(run, job)
        parents.append(job)
    by_uid = {j['metadata']['uid']: j for j in parents}
    source_jobs = []
    for job in run.get('get', 'jobs', '-n', run.ns)['items']:
        references = [o for o in job['metadata'].get('ownerReferences', [])
                      if o.get('kind') == 'SnapshotJob' and o.get('uid') in by_uid]
        if not references:
            continue
        if len(references) != 1:
            raise ValueError('Source Job has ambiguous SnapshotJob ownership.')
        parent = by_uid[references[0]['uid']]
        expected = parent.get('status', {}).get('sourceJobUID')
        if expected and expected != job['metadata']['uid']:
            raise ValueError('Source Job UID differs from its SnapshotJob status.')
        source_jobs.append(job)
    known_sources = {j['metadata']['uid'] for j in source_jobs}
    live_jobs = {j['metadata']['uid']: j for j in run.get('get', 'jobs', '-n', run.ns)['items']}
    for parent in parents:
        expected = parent.get('status', {}).get('sourceJobUID')
        if expected in live_jobs and expected not in known_sources:
            raise ValueError('Cannot prove source Job ownership before cleanup; preserve the lease.')
    plan = {'schema': 1, 'recorded_at': now(), 'namespace': run.ns,
        'dgd_uid': run.state['snapshot_dgd_uid'], 'snapshot_jobs': parents, 'source_jobs': source_jobs}
    write_json(path, plan)
    return plan


def delete_recorded_job(run, recorded, resource, *, orphan=False):
    """UID-conditional deletion; recorded lineage remains proof after orphaning."""
    name, uid = recorded['metadata']['name'], recorded['metadata']['uid']
    found = run.k('get', resource, name, '-n', run.ns, '-o', 'json', check=False)
    if found.returncode:
        if 'NotFound' in found.stderr:
            return
        raise RuntimeError(found.stderr)
    if json.loads(found.stdout)['metadata']['uid'] != uid:
        raise ValueError('Cleanup resource name was reused by another UID: ' + name)
    api = recorded.get('apiVersion', 'batch/v1' if resource == 'job' else 'nvidia.com/v1alpha1')
    route = '/apis/' + api + '/namespaces/' + run.ns + '/' + ('jobs' if resource == 'job' else 'snapshotjobs') + '/' + name
    options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': uid},
               'propagationPolicy': 'Orphan' if orphan else 'Foreground'}
    run.k('delete', '--raw', route, '-f', '-', input_text=json.dumps(options), timeout=90)
    run.k('wait', '--for=delete', resource + '/' + name, '-n', run.ns, '--timeout=150s', timeout=165)


def cleanup(run, spec):
    require_lease(run)
    found = run.k('get', 'dgd', GRAPH, '-n', run.ns, '-o', 'json', check=False)
    graph = None
    if found.returncode == 0:
        graph = owned(json.loads(found.stdout), run.ns)
        if graph['metadata']['uid'] != run.state.get('snapshot_dgd_uid'):
            raise ValueError('Refusing changed DGD identity during cleanup.')
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    plan = cleanup_plan(run)
    # Save exact ancestry while it still exists. Deleting/orphaning a parent
    # removes ownerReferences, so reconstructing ownership afterwards is unsafe.
    if graph:
        run.k('delete', 'dgd', GRAPH, '-n', run.ns, '--wait=true', '--timeout=120s', timeout=135)
    for job in plan['source_jobs']:
        delete_recorded_job(run, job, 'job')
    for job in plan['snapshot_jobs']:
        # Source Jobs are gone before this orphan operation strips their refs.
        # Snapshot resources/artifacts remain preserved for inspection.
        delete_recorded_job(run, job, 'snapshotjob', orphan=True)
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Foreign Pod in qualification namespace; cleanup remains incomplete.')
        if pod.get('status', {}).get('phase') not in ('Succeeded', 'Failed'):
            run.k('wait', '--for=delete', 'pod/' + pod['metadata']['name'], '-n', run.ns, '--timeout=150s', timeout=165)
    remaining = run.get('get', 'pods', '-n', run.ns)['items']
    claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
    if any(p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in remaining) or claims:
        raise RuntimeError('Cleanup incomplete; preserve the lease for diagnosis.')
    run.result('snapshot-dgd-cleanup', 'passed', scope='Owned workloads/claims gone; snapshots, artifacts, storage and caller lease retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'render', 'dry-run', 'deploy', 'status', 'verify', 'replace', 'cleanup'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--patch-configmap')
    parser.add_argument('--patch-sha256')
    parser.add_argument('--snapshot-module-path')
    parser.add_argument('--gpu-uuid', action='append')
    parser.add_argument('--node')
    parser.add_argument('--cache-source')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'results/20261015-super-vl-tp2')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    run = Run(args.run)
    if (run.path / SPEC_FILE).exists():
        spec = load_spec(run)
        overrides = {'patch_configmap': args.patch_configmap, 'patch_sha256': args.patch_sha256,
                     'module_path': args.snapshot_module_path, 'gpu_uuids': args.gpu_uuid, 'node': args.node}
        if any(value is not None and value != spec['settings'][key] for key, value in overrides.items()):
            raise ValueError('Command-line settings differ from the frozen run; use a fresh run.')
        if args.cache_source is not None and '/model-cache/feature-tests/' + args.cache_source + '/hf' != spec['settings']['cache_home']:
            raise ValueError('Command-line cache source differs from the frozen run.')
    else:
        if args.action not in ('render', 'prepare'):
            raise ValueError('Render/freeze a fresh qualification first.')
        if not args.patch_configmap or not args.patch_sha256 or not args.gpu_uuid:
            parser.error('Initial render requires --patch-configmap, --patch-sha256 and two --gpu-uuid values.')
        lock_path = run.path / 'model-lock.json'
        lock = json.loads((lock_path if lock_path.exists() else ROOT / 'configs/super-vl-tp2-lock.json').read_text())
        if run.state.get('model_lock') and run.state['model_lock'] != lock:
            raise ValueError('Existing model/source lock changed.')
        run.state['model_lock'] = lock
        run.state['model_cache_run_id'] = args.cache_source or '20261015-super-vl-tp2'
        run.state['snapshot_dgd_node'] = args.node or 'kubecon-nke-site-cp-0124'
        run.save()
        if not lock_path.exists():
            write_json(lock_path, lock)
        spec = freeze(run, {'patch_configmap': args.patch_configmap, 'patch_sha256': args.patch_sha256,
            'module_path': args.snapshot_module_path or DEFAULT_MODULE, 'gpu_uuids': args.gpu_uuid,
            'node': args.node or 'kubecon-nke-site-cp-0124',
            'cache_home': model_cache_home(run)})
    if args.action == 'render':
        print((run.path / 'deployment.yaml').read_text())
    elif args.action == 'prepare':
        prepare(run, spec, args.baseline)
    elif args.action == 'dry-run':
        dry_run(run, spec)
    elif args.action == 'deploy':
        deploy(run, spec)
    elif args.action == 'status':
        data = inventory(run)
        print(json.dumps({'namespace': run.ns, 'pods': [(p['metadata']['name'], p.get('status', {}).get('phase'))
            for p in data['pods']['items']], 'graphs': data['dgd']['items']}, indent=2))
    elif args.action in ('verify', 'replace'):
        try:
            if args.action == 'verify':
                verify(run, spec, timeout=args.timeout)
            else:
                replace(run, spec, timeout=args.timeout)
        except Exception as exc:
            run.result('snapshot-dgd-' + args.action, 'failed', error=str(exc))
            try:
                collect_logs(run)
            except Exception as diagnostic_error:
                write_json(run.path / 'diagnostic-error.json', {'error': str(diagnostic_error), 'at': now()})
            raise
    else:
        cleanup(run, spec)


if __name__ == '__main__':
    main()
