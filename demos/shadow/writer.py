#!/usr/bin/env python3
"""Bounded writer-only GMS experiment; no Shadow, reader or intentional fault."""
from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import time

from scripts.source_paths import source_path
import yaml
from testlib import ROOT, Run
import demos.common.runtime as ui
from demos.shadow.demo import NODE, UUIDS, device_class
from demos.shadow.humming import patch_writer_loader, KERNEL_MODULE, MOE_MODULE, WRAPPER_MODULE

GRAPH = 'ft-shadow-writer'
PROFILE = 'super-vl-gms-private-humming-locks-writer-v3'
SOURCE = ROOT / 'results/overnight-shadow-super-vl-20261104-a1'
RUNTIME = SOURCE / 'recovered-runtime-20261105-a1/sources'
EXTRA_RUNTIME = ROOT / 'results/overnight-shadow-super-vl-20261105-writer-a4/extra-runtime-sources'


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def freeze(path):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError('Freeze requires a fresh run; old attempts are never reused.')
    run = Run(path)
    suffix = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    run.ns = 'dynamo-ft-r610-' + suffix + '-demo'
    run.state['namespace'] = run.ns
    graph = copy.deepcopy(yaml.safe_load((SOURCE / 'deployment.yaml').read_text()))
    loader_path = RUNTIME / 'gpu_memory_service/integrations/vllm/model_loader.py'
    loader = patch_writer_loader(loader_path.read_text())
    hook = (ROOT / 'demos/shadow/humming.py').read_text()
    compatibility = (SOURCE / 'patched-patches.py').read_text()
    stock_patches = SOURCE / 'runtime-sources/patches.py'
    checksum = hashlib.sha256((loader + hook + compatibility).encode()).hexdigest()
    overlay = 'writer-humming-' + checksum[:12]
    graph['metadata'] = {'name': GRAPH, 'namespace': run.ns, 'labels': run.labels()}
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        pod['metadata']['labels'].update(run.labels())
        pod['metadata']['labels']['workshop-demo'] = 'shadow-writer'
        if component['type'] != 'worker':
            continue
        component['experimental'] = {'gpuMemoryService': {'deviceClassName': run.ns + '-shadow'}}
        spec = pod['spec']
        main = spec['containers'][0]
        main['args'] += ['--kv-cache-memory-bytes', str(2 * 1024 ** 3)]
        spec['volumes'] = [v for v in spec['volumes'] if v['name'] != 'shadow-runtime']
        main['volumeMounts'] = [v for v in main['volumeMounts'] if v['name'] != 'shadow-runtime']
        spec['volumes'].append({'name': 'writer-runtime', 'configMap': {'name': overlay}})
        for filename in ('model_loader.py', 'workshop_humming.py', 'patches.py'):
            main['volumeMounts'].append({'name': 'writer-runtime', 'subPath': filename, 'readOnly': True,
                'mountPath': '/usr/local/lib/python3.12/dist-packages/gpu_memory_service/integrations/vllm/' + filename})
        if spec['nodeSelector'] != {'kubernetes.io/hostname': NODE}:
            raise ValueError('Writer proposal changed the assigned node.')
        if any(e['name'] in ('DYN_VLLM_GMS_SHADOW_MODE', 'DYN_GMS_SCRATCH_KV_ENABLED') for e in main['env']):
            raise ValueError('Writer-only experiment must not enable Shadow/scratch mode.')
    cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': overlay, 'namespace': run.ns,
          'labels': run.labels()}, 'immutable': True, 'data': {'model_loader.py': loader,
          'workshop_humming.py': hook, 'patches.py': compatibility}}
    dc = device_class(run.ns, UUIDS)
    dc['metadata']['labels'].update(run.labels())
    for name, obj in [('deployment.json', graph), ('runtime-overlay.json', cm), ('device-class.json', dc)]:
        write(path / name, obj)
    (path / 'deployment.yaml').write_text(yaml.safe_dump(graph, sort_keys=False))
    (path / 'model_loader.py').write_text(loader)
    (path / 'workshop_humming.py').write_text(hook)
    (path / 'patches.py').write_text(compatibility)
    contract_sources = {
        KERNEL_MODULE.replace('.', '/') + '.py': RUNTIME,
        MOE_MODULE.replace('.', '/') + '.py': EXTRA_RUNTIME,
        WRAPPER_MODULE.replace('.', '/') + '.py': EXTRA_RUNTIME,
        'gpu_memory_service/client/torch/allocator.py': RUNTIME,
    }
    contracts = {}
    for name, directory in contract_sources.items():
        source = directory / name
        target = path / 'runtime-contract-sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        contracts[name] = ui.digest(target)
    critical = ('workshop_shadow_writer.py', 'workshop_shadow_humming.py', 'workshop_snapshot_dgd.py',
                'workshop_shadow_demo.py', 'shadow_probe.py', 'serving_tests.py',
                'r610_feature_retests.py', 'snapshot_tp2_workflow.py', 'testlib.py', 'gpu_claims.py')
    snapshots = path / 'source-snapshot'
    snapshots.mkdir()
    for name in critical:
        (snapshots / name).write_bytes((source_path(name, root=ROOT)).read_bytes())
    inputs = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()
              if p.is_file() and p.name not in ('state.json', '.state.lock')}
    spec = {'profile': PROFILE, 'graph': GRAPH, 'namespace': run.ns, 'node': NODE, 'gpu_uuids': UUIDS,
            'source_run': str(SOURCE), 'original_loader_sha256': ui.digest(loader_path),
            'original_patches_sha256': ui.digest(stock_patches),
            'retained_compatibility_sha256': hashlib.sha256(compatibility.encode()).hexdigest(),
            'kv_cache_memory_bytes': 2 * 1024 ** 3,
            'workspace_owner_kinds': ['linear', 'moe'], 'runtime_contract_hashes': contracts,
            'overlay_sha256': checksum, 'inputs': inputs,
            'model_lock_sha256': ui.digest(ui.MODEL_LOCK), 'source_snapshot': {
                name: ui.digest(snapshots / name) for name in critical},
            'intentional_fault': False, 'reader_enabled': False}
    write(path / 'writer-spec.json', spec)
    run.state.update(shadow_writer_profile=PROFILE, shadow_writer_spec_sha256=ui.digest(path / 'writer-spec.json'))
    run.save()
    print(json.dumps({'run': str(path), 'namespace': run.ns, 'overlay': checksum,
                      'scope': 'OFFLINE FROZEN; no cluster action or GPU qualification'}, indent=2))


def load(path):
    run = Run(path)
    spec_path = run.path / 'writer-spec.json'
    spec = json.loads(spec_path.read_text())
    if (run.state.get('shadow_writer_profile') != PROFILE or spec['profile'] != PROFILE or
            spec['namespace'] != run.ns or ui.digest(spec_path) != run.state['shadow_writer_spec_sha256']):
        raise ValueError('Writer run/spec identity changed.')
    for name, digest in spec['inputs'].items():
        if ui.digest(run.path / name) != digest:
            raise ValueError('Frozen writer input changed: ' + name)
    for name, digest in spec['source_snapshot'].items():
        if ui.digest(source_path(name, root=ROOT)) != digest:
            raise ValueError('Frozen writer implementation changed: ' + name)
    for name, digest in spec['runtime_contract_hashes'].items():
        if ui.digest(run.path / 'runtime-contract-sources' / name) != digest:
            raise ValueError('Frozen Humming runtime contract changed: ' + name)
    if ui.digest(ui.MODEL_LOCK) != spec['model_lock_sha256']:
        raise ValueError('Pinned model/runtime changed; use a fresh candidate.')
    return run, spec


def prepare(run, spec):
    if run.state['checks'].get('model-staging', {}).get('status') != 'passed':
        from r610_feature_retests import prepare as prepare_cache
        prepare_cache(run, run.path, 'demo')
    if run.ns != spec['namespace']:
        raise ValueError('Preparation changed the candidate namespace.')
    from snapshot_tp2_workflow import cpu_probe
    program = '''import hashlib,importlib.metadata as m,json,os
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
paths={'loader':'gpu_memory_service/integrations/vllm/model_loader.py',
'patches':'gpu_memory_service/integrations/vllm/patches.py'}
hashes={k:hashlib.sha256((root/v).read_bytes()).hexdigest() for k,v in paths.items()}
assert hashes['loader']==os.environ['EXPECTED_LOADER']
assert hashes['patches']==os.environ['EXPECTED_PATCHES']
contracts=json.loads(os.environ['EXPECTED_RUNTIME_CONTRACTS'])
contract_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in contracts}
assert contract_hashes==contracts
assert '--kv-cache-memory-bytes' in (root/'vllm/engine/arg_utils.py').read_text()
print(json.dumps({'source_hashes':hashes,'runtime_contract_hashes':contract_hashes,'fixed_kv_cache_flag':True}))
'''
    checked = cpu_probe(run, 'writer-runtime-check', program, [
        {'name': 'EXPECTED_LOADER', 'value': spec['original_loader_sha256']},
        {'name': 'EXPECTED_PATCHES', 'value': spec['original_patches_sha256']},
        {'name': 'EXPECTED_RUNTIME_CONTRACTS', 'value': json.dumps(spec['runtime_contract_hashes'])}])
    run.result('shadow-writer-runtime-preflight', 'passed', **checked)
    run.apply([json.loads((run.path / 'runtime-overlay.json').read_text())])
    dc = json.loads((run.path / 'device-class.json').read_text())
    existing = run.k('get', 'deviceclass', dc['metadata']['name'], '-o', 'json', check=False)
    if existing.returncode == 0:
        actual = json.loads(existing.stdout)
        if actual['metadata'].get('labels', {}).get('feature-test-run') != run.ns or actual['spec'] != dc['spec']:
            raise ValueError('Foreign/changed writer DeviceClass.')
    run.k('apply', '-f', '-', input_text=json.dumps(dc))
    for mode in ('client', 'server'):
        run.k('apply', '--dry-run=' + mode, '-f', str(run.path / 'deployment.yaml'))
    run.result('shadow-writer-preparation', 'passed', scope='CPU/cache/admission only; no GPU DGD applied')


def probe(run, spec):
    if run.state['checks'].get('shadow-writer-preparation', {}).get('status') != 'passed':
        raise ValueError('Prepare CPU prerequisites first.')
    name = 'writer-cuda-check'
    claim = {'apiVersion': 'resource.k8s.io/v1', 'kind': 'ResourceClaimTemplate', 'metadata': {'name': name},
             'spec': {'spec': {'devices': {'requests': [{'name': 'gpus', 'exactly': {
                 'deviceClassName': run.ns + '-shadow', 'count': 2}}]}}}}
    program = '''import json,os,torch
expected=set(json.loads(os.environ['EXPECTED_UUIDS']))
assert torch.cuda.device_count()==2
observed=[]
for i in range(2):
 value=str(torch.cuda.get_device_properties(i).uuid)
 observed.append(value if value.startswith('GPU-') else 'GPU-'+value)
 x=torch.arange(1048576,device=f'cuda:{i}',dtype=torch.float64)
 assert (x+1).sum().item()==549756338176.0
 torch.cuda.synchronize(i)
assert set(observed)==expected,(observed,expected)
print(json.dumps({'gpu_uuids':observed,'arithmetic':'passed'}))
'''
    lock = run.state['model_lock']
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 180, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': NODE},
        'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}],
        'imagePullSecrets': [{'name': lock['image_pull_secret']}],
        'resourceClaims': [{'name': 'gpu', 'resourceClaimTemplateName': name}],
        'containers': [{'name': 'cuda', 'image': lock['runtime_image'], 'command': ['python3', '-c', program],
                        'env': [{'name': 'EXPECTED_UUIDS', 'value': json.dumps(UUIDS)}],
                        'resources': {'claims': [{'name': 'gpu'}], 'requests': {'cpu': '1', 'memory': '2Gi'},
                                      'limits': {'memory': '4Gi'}}}]}}
    if (run.path / 'gpu-probe-intent.json').exists():
        raise ValueError('GPU smoke already attempted; do not repeat this candidate.')
    write(run.path / 'gpu-probe-intent.json', {'at': ui.now(), 'node': NODE, 'gpu_uuids': UUIDS})
    try:
        run.apply([claim, pod])
        finished = run.wait_pod(name, completed=True, timeout=240)
        report = json.loads(run.k('logs', name, '-n', run.ns, '-c', 'cuda').stdout)
        write(run.path / 'gpu-probe-pod.json', finished)
        run.result('shadow-writer-cuda', 'passed', **report, node=NODE,
                   scope='Exact two-GPU arithmetic; no reset or model qualification')
    finally:
        run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=90s', timeout=105)
        run.k('delete', 'resourceclaimtemplate', name, '-n', run.ns, '--ignore-not-found')


def health_copy(run, path, filename):
    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if value.get('node') != NODE or value.get('changed_conditions') or any(v['exit_code'] for v in value['outputs'].values()):
        raise ValueError('Node health capture is incomplete or changed.')
    xid_path = path.parent / value['outputs']['kernel-xids']['file']
    write(run.path / filename, {'source': str(path), 'receipt': value, 'xids': xid_path.read_text().splitlines(),
                               'source_sha256': ui.digest(path), 'xid_source_sha256': ui.digest(xid_path)})
    return value


def deploy(run, spec, health_before):
    if run.state['checks'].get('shadow-writer-cuda', {}).get('status') != 'passed':
        raise ValueError('Exact-pair CUDA smoke must pass before model startup.')
    if not json.loads((SOURCE / 'demo.json').read_text()).get('cleaned_at'):
        raise ValueError('Original failed Shadow run must be cleaned first.')
    if run.get('get', 'pods', '-n', run.ns)['items'] or run.get('get', 'resourceclaims', '-n', run.ns)['items']:
        raise ValueError('Expected an empty candidate namespace after GPU smoke.')
    if run.state.get('writer_apply_started_at'):
        raise ValueError('Writer startup already attempted; inspect, never reapply.')
    baseline = health_copy(run, health_before, 'health-before.json')
    if baseline['observed_at'] < run.state['checks']['shadow-writer-cuda']['updated_at']:
        raise ValueError('Health baseline must follow the CUDA smoke.')
    run.state['writer_apply_started_at'] = ui.now()
    run.save()
    run.apply([json.loads((run.path / 'deployment.json').read_text())])
    graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
    run.state['writer_dgd_uid'] = graph['metadata']['uid']
    run.state.setdefault('graphs', {})['shadow-writer'] = {'name': GRAPH}
    run.save()
    run.result('shadow-writer-deployment', 'created', dgd_uid=graph['metadata']['uid'],
               scope='Writer-only GMS; no reader, standby, promotion or fault')


def collect(run):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    write(run.path / 'current-pods.json', {'items': pods})
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Foreign writer Pod.')
        for c in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
            result = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', c['name'], '--timestamps=true', check=False)
            (run.path / (pod['metadata']['name'] + '-' + c['name'] + '.log')).write_text(result.stdout + result.stderr)
    return pods


def verify_worker(run, worker):
    from gpu_claims import verify_allocation
    main = next(c for c in worker['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, worker, main, 2)
    slices = run.get('get', 'resourceslices')['items']
    actual = []
    for allocation in claim['status']['allocation']['devices']['results']:
        devices = [d for s in slices if s['spec']['driver'] == allocation['driver']
                   and s['spec']['pool']['name'] == allocation['pool']
                   for d in s['spec']['devices'] if d['name'] == allocation['device']]
        if len(devices) != 1 or allocation['pool'] != NODE:
            raise ValueError('Unexpected physical writer GPU allocation.')
        attrs = devices[0].get('basic', devices[0]).get('attributes', {})
        key = next(k for k in ('uuid', 'gpu.nvidia.com/uuid') if k in attrs)
        actual.append(attrs[key]['string'])
    statuses = worker['status'].get('containerStatuses', []) + worker['status'].get('initContainerStatuses', [])
    for name in ('main', 'gms-server'):
        status = next(c for c in statuses if c['name'] == name)
        if status.get('restartCount') or status['imageID'].split('@')[-1] != run.state['model_lock']['runtime_image'].split('@')[-1]:
            raise ValueError('Writer/GMS image or restart identity changed.')
    if set(actual) != set(UUIDS):
        raise ValueError('Writer received a different physical GPU pair.')
    write(run.path / 'worker-gpu-claim.json', claim)
    return {'gpu_uuids': actual, 'container_ids': {s['name']: s['containerID'] for s in statuses
                                                if s['name'] in ('main', 'gms-server')}}


def gms_state(run, worker, name):
    result = run.k('exec', worker['metadata']['name'], '-n', run.ns, '-c', 'gms-server', '--',
                   'python3', '-c', (ROOT / 'scripts/shadow_probe.py').read_text(), 'gms', timeout=45)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    weights = {k: v for k, v in data.items() if k.endswith('_weights.sock')}
    if (set(weights) != {'gms_' + u + '_weights.sock' for u in UUIDS} or
            any(not x['state']['memory_layout_hash'] or not x['state']['committed'] for x in weights.values())):
        raise ValueError('Need committed GMS weights on the exact two assigned GPUs.')
    write(run.path / name, data)
    return weights


def stop(run):
    result = run.k('get', 'dgd', GRAPH, '-n', run.ns, '-o', 'json', check=False)
    if result.returncode:
        if 'NotFound' not in result.stderr:
            raise RuntimeError(result.stderr)
        return
    graph = json.loads(result.stdout)
    if (graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns or
            graph['metadata']['uid'] != run.state.get('writer_dgd_uid')):
        raise ValueError('Refusing to stop an unowned/replaced writer DGD.')
    run.k('delete', 'dgd', GRAPH, '-n', run.ns, '--wait=true', '--timeout=120s', timeout=135)


def validate_lock_proof(rows):
    paths = {'linear': 'quant_method.kernel.locks',
             'moe': 'quant_method.moe_kernel.fused_experts.locks'}
    copied = set()
    for row in rows:
        kind = row.get('kind')
        if kind not in paths or row.get('owner_path') != paths[kind] or type(row.get('tp_rank')) is not int:
            raise ValueError('Unexpected Humming lock owner/rank evidence.')
        if row.get('bytes') != 4096:
            raise ValueError('Unexpected Humming lock workspace size.')
        if row['already_private']:
            continue
        old, new, base = (int(row[k], 16) for k in ('old_pointer', 'new_pointer', 'gms_mapping'))
        limit = base + row['gms_mapping_size']
        if not (base <= old and old + 4096 <= limit) or (new < limit and base < new + 4096):
            raise ValueError('Humming private-copy range proof failed.')
        copied.add((row['tp_rank'], kind))
    expected = {(rank, kind) for rank in (0, 1) for kind in paths}
    if not expected <= copied:
        raise ValueError('Missing actual linear/MoE lock rebinding on both TP ranks: ' + str(sorted(expected - copied)))


def verify(run, spec, timeout):
    from serving_tests import frontend
    from demos.snapshot.dgd import coding_request
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            pods = collect(run)
            for pod in pods:
                for c in pod['status'].get('containerStatuses', []) + pod['status'].get('initContainerStatuses', []):
                    if c.get('restartCount', 0):
                        raise RuntimeError('Writer restarted; no recovery qualification.')
                log = run.path / (pod['metadata']['name'] + '-main.log')
                text = log.read_text() if log.exists() else ''
                if any(s in text for s in ('an illegal memory access was encountered', 'Shape/dtype mismatch',
                                           'torch.OutOfMemoryError', 'CUDA_ERROR_ILLEGAL_ADDRESS',
                                           'Engine core initialization failed', 'WorkerProc initialization failed',
                                           'Unexpected Humming GEMM lock contract', 'Humming GEMM lock copy is not outside GMS')):
                    raise RuntimeError('Fatal writer startup error; logs retained and DGD will stop.')
            workers = [p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'worker']
            if len(pods) == 2 and len(workers) == 1 and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in p['status'].get('conditions', [])) for p in pods):
                break
            time.sleep(5)
        else:
            raise TimeoutError('Writer did not become serving-ready in its bounded wait.')
        worker = workers[0]
        if worker['spec']['nodeName'] != NODE or {c['name'] for c in worker['spec']['containers']} != {'main'}:
            raise ValueError('Unexpected writer topology or placement.')
        allocation = verify_worker(run, worker)
        rows = []
        text = (run.path / (worker['metadata']['name'] + '-main.log')).read_text()
        for line in text.splitlines():
            marker = 'Private Humming GEMM locks: '
            if marker in line:
                rows.append(ast.literal_eval(line.split(marker, 1)[1]))
        validate_lock_proof(rows)
        before_gms = gms_state(run, worker, 'gms-before.json')
        with frontend(run, 'shadow-writer') as base:
            responses = [coding_request(base, run.state['model_lock']['model']) for _ in range(3)]
        after_pods = collect(run)
        same_worker = next(p for p in after_pods if p['metadata']['name'] == worker['metadata']['name'])
        if same_worker['metadata']['uid'] != worker['metadata']['uid'] or verify_worker(run, same_worker) != allocation:
            raise ValueError('Writer/GMS identity changed during coding verification.')
        after_gms = gms_state(run, same_worker, 'gms-after.json')
        if any(before_gms[k]['state']['memory_layout_hash'] != after_gms[k]['state']['memory_layout_hash'] or
               before_gms[k]['events'] != after_gms[k]['events'] for k in before_gms):
            raise ValueError('GMS weights were republished during writer verification.')
        write(run.path / 'coding-responses.json', responses)
        write(run.path / 'private-lock-proof.json', rows)
        run.result('shadow-writer-serving', 'passed', worker_pod=worker['metadata']['name'],
            worker_uid=worker['metadata']['uid'], responses=3, rebound_rows=len(rows), **allocation,
            scope='Writer-only correct coding and private-lock pointers; final GPU-health comparison still required')
    except Exception as error:
        run.result('shadow-writer-serving', 'failed', error=str(error), intentional_fault=False)
        stop(run)
        raise


def finalize(run, health_after):
    from r610_retest_audit import new_xids
    serving = run.state['checks'].get('shadow-writer-serving', {})
    if serving.get('status') != 'passed':
        raise ValueError('Writer coding verification must pass before final health.')
    after = health_copy(run, health_after, 'health-after.json')
    before = json.loads((run.path / 'health-before.json').read_text())
    current = json.loads((run.path / 'health-after.json').read_text())
    new = new_xids(before['xids'], current['xids'])
    if (new or after['observed_at'] < serving['updated_at'] or
            after['driver_pod_uid'] != before['receipt']['driver_pod_uid'] or
            after['node_status']['nodeInfo']['bootID'] != before['receipt']['node_status']['nodeInfo']['bootID']):
        raise ValueError('New GPU errors or health identity/timing mismatch: ' + str(new))
    run.result('shadow-writer-qualification', 'passed', responses=3, new_xids=[],
        reader_enabled=False, intentional_fault=False,
        scope='Experimental writer-only Humming lock fix on exact TP2 pair. No Shadow/RO/promotion/SLO qualification.')


def cleanup(run):
    stop(run)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if not run.get('get', 'pods', '-n', run.ns)['items'] and not run.get('get', 'resourceclaims', '-n', run.ns)['items']:
            break
        time.sleep(3)
    else:
        raise RuntimeError('Writer Pods/claims remain; preserve the slot.')
    found = run.k('get', 'deviceclass', run.ns + '-shadow', '-o', 'json', check=False)
    if found.returncode == 0:
        dc = json.loads(found.stdout)
        if dc['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Refusing foreign DeviceClass cleanup.')
        run.k('delete', 'deviceclass', run.ns + '-shadow')
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    run.result('shadow-writer-cleanup', 'passed', scope='Owned DGD, Pods, GPU claims and DeviceClass gone; cache/evidence retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'prepare', 'probe', 'deploy', 'verify', 'finalize', 'cleanup'])
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--health-before', type=Path)
    parser.add_argument('--health-after', type=Path)
    parser.add_argument('--timeout', type=int, default=1500)
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.run)
    else:
        run, spec = load(args.run)
        if args.action == 'deploy':
            if not args.health_before: parser.error('deploy needs --health-before captured after exact-pair smoke')
            deploy(run, spec, args.health_before)
        elif args.action == 'verify': verify(run, spec, args.timeout)
        elif args.action == 'finalize':
            if not args.health_after: parser.error('finalize needs --health-after captured after serving verification')
            finalize(run, args.health_after)
        elif args.action == 'cleanup': cleanup(run)
        else: globals()[args.action](run, spec)
