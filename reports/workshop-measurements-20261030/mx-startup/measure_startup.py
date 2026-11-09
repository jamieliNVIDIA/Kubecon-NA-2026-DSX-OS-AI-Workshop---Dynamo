#!/usr/bin/env python3
"""Bounded, source-pinned storage/P2P startup comparison for Super VL."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import yaml
from testlib import Run
from storage_tests import prepare as prepare_storage
from common_runtime_tests import pull_secret, efa
from gpu_claims import verify_allocation

OWNER = '/root/mx_startup'
LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
REPORT = Path(__file__).resolve().parent
TEMPLATES = ROOT / 'configs/dgd/super-vl-r610-d906a5f1/mx'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def status(message):
    (REPORT / 'LIVE_STATUS.json').write_text(json.dumps({'updated_at': now(), 'message': message}, indent=2) + '\n')
    print(message, flush=True)


def setup_run(path):
    run = Run(path)
    if not run.state.get('mx_startup_initialized'):
        run.state['namespace'] = 'dynamo-ft-mxstartup-' + hashlib.sha256(run.state['run_id'].encode()).hexdigest()[:10]
        run.ns = run.state['namespace']
        run.state['mx_startup_initialized'] = True
        run.state['model_lock'] = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())
        run.state['model_cache_run_id'] = '20261015-super-vl-tp2'
        run.save()
        (run.path / 'model-lock.json').write_text(json.dumps(run.state['model_lock'], indent=2) + '\n')
    return run


def frozen_spec(run):
    spec = {
        'schema': 1,
        'model_lock': run.state['model_lock'],
        'model_lock_source_sha256': digest(ROOT / 'configs/super-vl-tp2-lock.json'),
        'source_template': str(TEMPLATES / 'nemotron-modelexpress.yaml'),
        'source_template_sha256': digest(TEMPLATES / 'nemotron-modelexpress.yaml'),
        'target_template': str(TEMPLATES / 'nemotron-modelexpress-target.yaml'),
        'target_template_sha256': digest(TEMPLATES / 'nemotron-modelexpress-target.yaml'),
        'script_sha256': digest(__file__),
        'source_node': 'kubecon-nke-site-cp-0124',
        'target_node': 'kubecon-nke-site-cp-0198',
        'sequence': ['source-mx-storage-bootstrap', 'target-native-storage', 'target-mx-p2p'],
        'replicates_this_batch': 1,
        'startup_timeout_seconds': 2400,
        'pod_active_deadline_seconds': 10800,
        'context_length': 8192,
        'max_num_seqs': 4,
        'max_num_batched_tokens': 8192,
        'gpu_memory_utilization': 0.85,
        'tensor_parallel_size': 2,
        'artifact_transfer': False,
        'source_load': 'idle apart from engine health/canary requests',
        'storage': 'preexisting exact-revision EFS checkpoint; host page cache uncontrolled, never globally flushed',
        'engine_compile_caches': 'private fresh per-Pod filesystem directories, not persistent across target Pods',
        'readiness_probe_request': {'purpose': 'correctness/readiness only, not AgentX throughput benchmark',
            'messages': [{'role': 'user', 'content': 'Reply with the word READY.'}],
            'max_tokens': 128, 'temperature': 0,
            'chat_template_kwargs': {'enable_thinking': False}},
    }
    target = run.path / 'spec.json'
    serialized = json.dumps(spec, indent=2, sort_keys=True) + '\n'
    if target.exists() and target.read_text() != serialized:
        raise ValueError('Frozen spec changed; create a fresh run instead')
    target.write_text(serialized)
    (run.path / 'spec.sha256').write_text(digest(target) + '\n')
    return spec


def relabel(value, ns):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'feature-test-run':
                value[key] = ns
            elif key == 'namespace' and isinstance(child, str) and child.startswith('dynamo-ft-'):
                value[key] = ns
            else:
                relabel(child, ns)
    elif isinstance(value, list):
        for child in value:
            relabel(child, ns)


def manifests(run, role, native=False):
    filename = 'nemotron-modelexpress.yaml' if role == 'source' else 'nemotron-modelexpress-target.yaml'
    items = copy.deepcopy(yaml.safe_load((TEMPLATES / filename).read_text())['items'])
    relabel(items, run.ns)
    for item in items:
        item['metadata']['namespace'] = run.ns
        if item['kind'] != 'DynamoGraphDeployment':
            continue
        for component in item['spec']['components']:
            spec = component['podTemplate']['spec']
            spec['activeDeadlineSeconds'] = 10800
            container = spec['containers'][0]
            assert container['image'] == run.state['model_lock']['runtime_image']
            # Preserve the original effective string. Kubernetes' YAML decoder
            # treats an unquoted `y` as boolean, so manifests below use JSON.
            for env in container.get('env', []):
                if env['name'] == 'NIXL_TELEMETRY_ENABLE':
                    env['value'] = 'y'
                elif 'value' in env and not isinstance(env['value'], str):
                    raise ValueError(f'Non-string environment value: {env["name"]}')
            if component['type'] != 'worker':
                continue
            args = container['args']
            if native:
                idx = args.index('--load-format')
                del args[idx:idx + 2]
            added = {
                'VLLM_CACHE_ROOT': '/tmp/workshop-vllm-cache',
                'TRITON_CACHE_DIR': '/tmp/workshop-triton-cache',
                'DG_JIT_CACHE_DIR': '/tmp/workshop-deepgemm-cache',
                'FLASHINFER_WORKSPACE_BASE': '/tmp/workshop-flashinfer-cache',
            }
            container['env'] = [e for e in container['env'] if e['name'] not in added]
            container['env'] += [{'name': k, 'value': v} for k, v in added.items()]
            assert args[args.index('--max-model-len') + 1] == '8192'
            assert args[args.index('--max-num-seqs') + 1] == '4'
    return items


def prepare(run):
    frozen_spec(run)
    run.ensure_namespace()
    prepare_storage(run)
    pull_secret(run)
    efa(run)
    for key, args in {
        'nodes': ('get', 'nodes'), 'pods-before': ('get', 'pods', '-A'),
        'resourceclaims-before': ('get', 'resourceclaims', '-A'),
    }.items():
        (run.path / f'{key}.json').write_text(json.dumps(run.get(*args), indent=2) + '\n')
    for role, native in [('source', False), ('target', True), ('target', False)]:
        tag = 'source' if role == 'source' else 'target-native' if native else 'target-p2p'
        items = manifests(run, role, native)
        target = run.path / f'{tag}.json'
        target.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=2) + '\n')
        run.k('apply', '--dry-run=client', '-f', str(target))
        run.k('apply', '--dry-run=server', '-f', str(target))
    program = '''import importlib.metadata as m,hashlib,json,os
from pathlib import Path
root=Path('/model-cache/feature-tests/20261015-super-vl-tp2/hf/hub/models--nvidia--NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4/snapshots/8a115b9d966adce8c059a7bcf47f49a1e57957d8')
expected=json.loads(Path('/probe/model-lock.json').read_text())
required={name:value for name,value in expected['model_metadata_sha256'].items() if name!='README.md'}
checks={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in required}
assert checks==required, checks
index=json.loads((root/'model.safetensors.index.json').read_text())
files=sorted(set(index['weight_map'].values()))
assert len(files)==88 and all((root/f).is_file() for f in files)
pkgs={p:m.version(p) for p in ['modelexpress','vllm','ai-dynamo','nixl']}
mxroot=Path(m.distribution('modelexpress').locate_file('modelexpress'))
sources={}
for p in mxroot.rglob('*.py'):
 text=p.read_text(errors='replace')
 if any(s in text for s in ['MX_ARTIFACT_TRANSFER','compile_config_digest','artifact_lifecycle','torch_compile_cache']):
  sources[str(p.relative_to(mxroot))]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':text}
print(json.dumps({'model':expected['model'],'revision':expected['revision'],'snapshot':str(root),'metadata_hashes':checks,'weight_file_count':len(files),'weight_file_bytes':sum((root/f).stat().st_size for f in files),'packages':pkgs,'modelexpress_sources':sources}))
'''
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'mx-startup-probe'},
        'data': {'probe.py': program, 'model-lock.json': json.dumps(run.state['model_lock'])}}])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'mx-startup-probe'},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 300,
            'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0942'},
            'imagePullSecrets': [{'name': 'common-runtime-pull'}],
            'containers': [{'name': 'inspect', 'image': run.state['model_lock']['runtime_image'],
                'command': ['python3', '/probe/probe.py'],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'memory': '4Gi'}},
                'volumeMounts': [{'name': 'probe', 'mountPath': '/probe', 'readOnly': True},
                    {'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True}]}],
            'volumes': [{'name': 'probe', 'configMap': {'name': 'mx-startup-probe'}},
                {'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    try:
        completed = run.wait_pod('mx-startup-probe', completed=True, timeout=360)
        output = run.k('logs', 'mx-startup-probe', '-n', run.ns).stdout
        (run.path / 'runtime-capabilities.json').write_text(output)
        data = json.loads(output)
        data['modelexpress_source_files'] = list(data.pop('modelexpress_sources'))
        data['image_id'] = completed['status']['containerStatuses'][0]['imageID']
        run.result('mx-startup-preparation', 'passed', **data)
    finally:
        run.k('delete', 'pod', 'mx-startup-probe', '-n', run.ns, '--wait=true', '--timeout=60s', '--ignore-not-found', check=False)
    status(f'Prepared startup run {run.path.name}; namespace {run.ns}; no GPU workload launched')


def acquire(run):
    LEASE.mkdir()
    (LEASE / 'owner.json').write_text(json.dumps({'agent': OWNER, 'workstream': 'MX startup', 'run': str(run.path), 'acquired_at': now()}, indent=2) + '\n')
    status(f'GPU lease acquired: {run.path.name}')


def release(run):
    owner = json.loads((LEASE / 'owner.json').read_text())
    if owner['agent'] != OWNER or owner['run'] != str(run.path):
        raise ValueError('Refusing to release another owner\'s lease')
    remaining = run.get('get', 'pods', '-n', run.ns)['items']
    active = [p['metadata']['name'] for p in remaining if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
        and any(c.get('resources', {}).get('claims') for c in p['spec'].get('containers', []))]
    if active:
        raise ValueError(f'GPU Pods still active: {active}')
    (LEASE / 'owner.json').unlink()
    LEASE.rmdir()
    status('GPU lease released; owned GPU workloads cleaned')


def get_pods(run, graph):
    return [p for p in run.get('get', 'pods', '-n', run.ns)['items']
        if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == graph
        and not p['metadata'].get('deletionTimestamp')]


def collect(run, tag):
    directory = run.path / tag
    directory.mkdir(exist_ok=True)
    pods = run.get('get', 'pods', '-n', run.ns)
    (directory / 'pods.json').write_text(json.dumps(pods, indent=2) + '\n')
    (directory / 'events.json').write_text(json.dumps(run.get('get', 'events', '-n', run.ns), indent=2) + '\n')
    (directory / 'graphs.json').write_text(json.dumps(run.get('get', 'dgd', '-n', run.ns), indent=2) + '\n')
    for pod in pods['items']:
        for c in pod['spec'].get('initContainers', []) + pod['spec'].get('containers', []):
            result = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', c['name'], '--timestamps=true', check=False)
            (directory / f'{pod["metadata"]["name"]}-{c["name"]}.log').write_text(result.stdout + result.stderr)
    return directory


def stop_graph(run, graph):
    found = run.k('get', 'dgd', graph, '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        obj = json.loads(found.stdout)
        assert obj['metadata']['labels']['feature-test-run'] == run.ns
        run.k('delete', 'dgd', graph, '-n', run.ns, '--wait=true', '--timeout=180s', timeout=210)
    end = time.monotonic() + 180
    while time.monotonic() < end:
        pods = [p for p in run.get('get', 'pods', '-n', run.ns)['items']
            if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == graph]
        if not pods:
            return
        time.sleep(3)
    raise TimeoutError(f'Owned Pods for {graph} did not terminate')


def endpoint(run, graph):
    services = run.get('get', 'services', '-n', run.ns)['items']
    service = next(s for s in services if graph in s['metadata']['name'] and any(p['port'] == 8000 for p in s['spec'].get('ports', [])))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    path = run.path / f'port-forward-{graph}-{time.time_ns()}.log'
    handle = path.open('w')
    proc = subprocess.Popen(run.kbase + ['port-forward', '-n', run.ns, f'service/{service["metadata"]["name"]}', f'{port}:8000', '--address=127.0.0.1'], stdout=handle, stderr=handle)
    for _ in range(60):
        if proc.poll() is not None:
            handle.close(); raise RuntimeError('Port-forward exited')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return proc, handle, f'http://127.0.0.1:{port}'
        except OSError:
            time.sleep(1)
    proc.terminate(); handle.close(); raise TimeoutError('Port-forward did not open')


def http(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def run_arm(run, tag, role, native=False):
    spec = frozen_spec(run)
    graph = 'ft-mx' if role == 'source' else 'ft-mx-target'
    start = now(); mono = time.monotonic()
    status(f'Starting {tag}: {graph}')
    run.apply(manifests(run, role, native))
    observations = []
    end = mono + spec['startup_timeout_seconds']
    last = None
    while time.monotonic() < end:
        pods = get_pods(run, graph)
        current = [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'],
            'node': p['spec'].get('nodeName'), 'phase': p.get('status', {}).get('phase'),
            'conditions': p.get('status', {}).get('conditions', []),
            'containers': p.get('status', {}).get('containerStatuses', [])} for p in pods]
        observations.append({'observed_at': now(), 'elapsed_seconds': time.monotonic() - mono, 'pods': current})
        brief = [(p['name'], p['phase'], [(c['name'], c.get('ready'), c.get('restartCount')) for c in p['containers']]) for p in current]
        if brief != last:
            status(f'{tag}: {brief}'); last = brief
        if any(p['phase'] == 'Failed' or any(c.get('restartCount', 0) > 0 for c in p['containers']) for p in current):
            raise RuntimeError(f'{tag}: Pod failed or restarted; retain failed attempt')
        if len(pods) >= 2 and all(any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', [])) for p in pods):
            ready = now(); ready_elapsed = time.monotonic() - mono
            break
        time.sleep(5)
    else:
        raise TimeoutError(f'{tag}: did not become Ready within {spec["startup_timeout_seconds"]}s')
    directory = collect(run, tag)
    (directory / 'observations.json').write_text(json.dumps(observations, indent=2) + '\n')
    worker = next(p for p in pods if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component-type') != 'frontend')
    allocation = verify_allocation(run, worker, worker['spec']['containers'][0], 2)
    (directory / 'gpu-allocation.json').write_text(json.dumps(allocation, indent=2) + '\n')
    gpu = run.k('exec', worker['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'nvidia-smi', '--query-gpu=index,uuid,name,memory.total,driver_version', '--format=csv,noheader', check=False)
    (directory / 'gpu-visible.csv').write_text(gpu.stdout + gpu.stderr)
    proc, handle, base = endpoint(run, graph)
    try:
        models = http(base + '/v1/models')
        assert run.state['model_lock']['model'] in [m['id'] for m in models['data']]
        payload = copy.deepcopy(spec['readiness_probe_request']); payload.pop('purpose')
        payload['model'] = run.state['model_lock']['model']
        request_start = now(); request_mono = time.monotonic()
        response = http(base + '/v1/chat/completions', payload)
        assert response.get('choices') and response.get('usage', {}).get('completion_tokens', 0) > 0
        assert 'READY' in response['choices'][0]['message'].get('content', '')
        report = {'arm': tag, 'apply_started_at': start, 'pods_ready_observed_at': ready,
            'apply_to_ready_observed_seconds': ready_elapsed,
            'first_correctness_request_started_at': request_start,
            'first_correctness_request_seconds': time.monotonic() - request_mono,
            'apply_to_first_correctness_response_seconds': time.monotonic() - mono,
            'target_pod': worker['metadata']['name'], 'pod_uid': worker['metadata']['uid'],
            'node': worker['spec']['nodeName'], 'models': models, 'response': response,
            'scope': 'Fresh startup with preexisting EFS weights and fresh per-Pod compiler caches; idle source; correctness request is not an AgentX throughput test'}
        (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        handle.close()
    logs = '\n'.join(p.read_text() for p in directory.glob('*.log') if worker['metadata']['name'] in p.name)
    if role == 'target' and not native:
        transfers = re.findall(r'Transfer complete: (\d+) tensors, ([0-9.]+) GB in ([0-9.]+)s', logs)
        assert len(transfers) == 2, transfers
        assert 'Trying strategy: default' not in logs, 'MX target fell back to storage'
        report['per_rank_transfers'] = transfers
        (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    run.result('mx-startup-' + tag, 'passed', **{k: v for k, v in report.items() if k not in ('models', 'response')})
    return report


def batch(run):
    if run.state.get('checks', {}).get('mx-startup-preparation', {}).get('status') != 'passed':
        raise ValueError('Complete preparation before the GPU batch')
    frozen_spec(run)
    acquire(run)
    try:
        run_arm(run, 'source-bootstrap', 'source')
        run.apply([{'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'mx-source'},
            'spec': {'selector': {'mx-role': 'source'}, 'ports': [{'name': f'mx-{rank}', 'port': 6555 + rank, 'targetPort': 6555 + rank} for rank in range(2)]}}])
        first = run_arm(run, 'native-storage', 'target', native=True)
        stop_graph(run, 'ft-mx-target')
        second = run_arm(run, 'mx-p2p', 'target')
        summary = {'storage': first, 'p2p': second,
            'ready_speedup': first['apply_to_ready_observed_seconds'] / second['apply_to_ready_observed_seconds'],
            'scope': 'One paired trial; no distribution or peak-capacity claim'}
        (run.path / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps({k: v for k, v in summary.items() if k not in ('storage', 'p2p')}, indent=2), flush=True)
    except Exception as error:
        collect(run, 'failed-attempt')
        run.result('mx-startup-batch', 'blocked', error=str(error))
        raise
    finally:
        stop_graph(run, 'ft-mx-target')
        stop_graph(run, 'ft-mx')
        collect(run, 'after-cleanup')
        release(run)
        hashes = {str(p.relative_to(run.path)): digest(p) for p in run.path.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'}
        (run.path / 'evidence-sha256.json').write_text(json.dumps(hashes, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'batch', 'cleanup'])
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    run = setup_run(args.run)
    try:
        if args.action == 'prepare': prepare(run)
        elif args.action == 'batch': batch(run)
        else:
            stop_graph(run, 'ft-mx-target'); stop_graph(run, 'ft-mx')
            if LEASE.exists(): release(run)
    except Exception as error:
        run.result('mx-startup-' + args.action, 'blocked', error=str(error))
        status(f'{args.action} failed in {run.path.name}: {error}')
        raise


if __name__ == '__main__':
    main()
