#!/usr/bin/env python3
"""Qualify KVCR-Guard between independent engines, with frozen overlays and scoped faults."""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import re
import tarfile
import time

from testlib import ROOT, Run
import demos.common.runtime as ui
import demos.common.support as support
from serving_tests import frontend

OWNER = 'workshop-kvcr-guard'
NODE = 'kubecon-nke-site-cp-0124'
GRAPH = 'ft-kvcr-guard'
BOOTSTRAP = ROOT / 'scripts/kvcr_guard_bootstrap.py'
RUNTIME = ROOT / 'scripts/kvcr_guard_runtime.py'


def require_lease(run):
    if not ui.lease_owned(run.path, OWNER):
        raise RuntimeError('This qualification does not own its GPU reservation.')


def source_candidate(run):
    sources = run.path / 'sources'
    temporary = sources / ('bundle-' + str(time.time_ns()) + '.tar.gz')
    with temporary.open('wb') as stream, gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name in ('kvcr', 'adapter', 'build-wheels', 'runtime-meta'):
                for file in sorted((sources / name).rglob('*')):
                    if file.is_file():
                        info = archive.gettarinfo(str(file), arcname=str(file.relative_to(sources)))
                        info.mtime = 0
                        info.uid = info.gid = 0
                        info.uname = info.gname = ''
                        info.pax_headers = {}
                        with file.open('rb') as data:
                            archive.addfile(info, data)
    bundle_sha = ui.digest(temporary)
    bundle = sources / ('bundle-' + bundle_sha + '.tar.gz')
    temporary.rename(bundle)
    bootstrap = BOOTSTRAP.read_text()
    identity = hashlib.sha256((bundle_sha + bootstrap).encode()).hexdigest()[:12]
    name = 'kvcr-guard-source-' + identity
    obj = {'apiVersion': 'v1', 'kind': 'ConfigMap',
           'metadata': {'name': name, 'namespace': run.ns, 'labels': run.labels()}, 'immutable': True,
           'data': {'bootstrap.py': bootstrap},
           'binaryData': {'bundle.tar.gz': base64.b64encode(bundle.read_bytes()).decode()}}
    body = json.dumps(obj)
    if len(body.encode()) >= 1000000:
        raise ValueError('Candidate exceeds the source ConfigMap budget.')
    record = {'identity': identity, 'configmap': name, 'bundle': str(bundle), 'bundle_sha256': bundle_sha,
              'bootstrap_sha256': ui.digest(BOOTSTRAP),
              'kvcr_revision': 'dd5df02c076dfee4bb2cdc39bef11164f9dcaec5',
              'adapter_revision': 'a5db4c9ff58a0ec4dc20594ba5cea9f776dcd693',
              'base_image': ui.read_json(ui.MODEL_LOCK)['runtime_image']}
    nightly = sources / 'runtime-meta/runtime-sources.json'
    if nightly.exists():
        record['dynamo_nightly'] = ui.read_json(nightly)
    ui.write_json(run.path / ('candidate-' + identity + '.json'), record)
    ui.write_json(run.path / ('source-configmap-' + identity + '.json'), obj)
    existing = run.k('get', 'configmap', name, '-n', run.ns, '-o', 'json', check=False)
    if existing.returncode == 0:
        found = json.loads(existing.stdout)
        if (found['metadata'].get('labels', {}).get('feature-test-run') != run.ns or
                found.get('data') != obj['data'] or found.get('binaryData') != obj['binaryData']):
            raise ValueError('Source ConfigMap identity/ownership mismatch.')
    elif 'NotFound' in existing.stderr:
        # create avoids the 256 KiB last-applied annotation limit for source bundles.
        run.k('create', '--dry-run=server', '-f', '-', input_text=body)
        run.k('create', '-f', '-', input_text=body)
    else:
        raise RuntimeError(existing.stderr)
    return record


def render(namespace, model, candidate, runtime_configmap):
    graph, original_claim = ui.render(namespace, model, enable_mx=False)
    graph['metadata'] = {'name': GRAPH, 'namespace': namespace, 'annotations': {
        'nvidia.com/dynamo-discovery-backend': 'kubernetes', 'nvidia.com/dynamo-kube-discovery-mode': 'container'}}
    frontend = next(c for c in graph['spec']['components'] if c['type'] == 'frontend')
    worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
    components = [frontend] + [copy.deepcopy(worker) for _ in ('a', 'b')]
    claims = []
    namespace_runtime = namespace + '-guard'
    for index, component in enumerate(components):
        peer = None if index == 0 else ('a' if index == 1 else 'b')
        component['name'] = 'Frontend' if peer is None else 'engine-' + peer
        component['replicas'] = 1
        pod = component['podTemplate']
        pod['metadata'] = {'labels': {'feature-test-run': namespace, 'workshop-kvcr-guard': 'true',
                                      'workshop-role': 'frontend' if peer is None else 'worker',
                                      **({'kvcr-peer': peer} if peer else {})}}
        spec = pod['spec']
        spec['nodeSelector'] = {'kubernetes.io/hostname': NODE}
        spec.pop('affinity', None)
        spec['terminationGracePeriodSeconds'] = 45
        main = spec['containers'][0]
        main['env'] += [{'name': 'KVCR_DYNAMO_NAMESPACE', 'value': namespace_runtime},
                        {'name': 'CONTAINER_NAME', 'value': 'main'},
                        {'name': 'DYN_MIGRATION_LIMIT', 'value': '0'}]
        spec['volumes'].append({'name': 'guard-runtime', 'configMap': {'name': runtime_configmap}})
        main['volumeMounts'].append({'name': 'guard-runtime', 'mountPath': '/guard-runtime', 'readOnly': True})
        if peer is None:
            # Frontend and workers must load the same private Dynamo overlay.
            spec['volumes'].append({'name': 'candidate', 'configMap': {'name': candidate['configmap']}})
            main['volumeMounts'].append({'name': 'candidate', 'mountPath': '/candidate', 'readOnly': True})
            main['env'].append({'name': 'KVCR_BUNDLE_SHA256', 'value': candidate['bundle_sha256']})
            main['securityContext'] = {'runAsUser': 0}
            main['command'] = ['python3', '/candidate/bootstrap.py', 'python3', '/guard-runtime/runtime.py', 'frontend']
            main['args'] = []
            continue
        spec['runtimeClassName'] = 'nvidia-legacy'
        claim = copy.deepcopy(original_claim)
        claim['metadata'] = {'name': GRAPH + '-' + peer + '-gpus', 'namespace': namespace}
        claims.append(claim)
        spec['resourceClaims'][0]['resourceClaimTemplateName'] = claim['metadata']['name']
        spec['volumes'] += [{'name': 'candidate', 'configMap': {'name': candidate['configmap']}},
                            {'name': 'guard-socket', 'emptyDir': {}},
                            {'name': 'guard-memory', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '5Gi'}},
                            {'name': 'efa', 'configMap': {'name': 'efa-userspace'}}]
        env = [e for e in main['env'] if e['name'] != 'NVIDIA_VISIBLE_DEVICES'] + [
            {'name': name, 'value': value} for name, value in {
                'KVCR_PEER': peer, 'KVCR_MODEL': model['model'], 'KVCR_MODEL_REVISION': model['revision'],
                # DRA/CDI supplies only the allocated GPU pair. Disable legacy
                # device selection so the image's default "all" cannot leak GPUs.
                'NVIDIA_VISIBLE_DEVICES': 'void',
                'KVCR_BUNDLE_SHA256': candidate['bundle_sha256'],
                'KVCR_COMPATIBILITY_DIGEST': 'super-vl-tp2-guard-dd5df02c-block64-v1',
                'PYTHONHASHSEED': '0', 'VLLM_KV_EVENTS_USE_INT_BLOCK_HASHES': '1',
                'VLLM_LOGGING_LEVEL': 'INFO', 'KVCR_LOG_LEVEL': 'DEBUG', 'NIXL_LOG_LEVEL': 'INFO',
                'FI_PROVIDER': 'efa', 'FI_EFA_USE_DEVICE_RDMA': '1', 'FI_EFA_FORK_SAFE': '1',
                'FI_EFA_ENABLE_SHM_TRANSFER': '0', 'FI_HMEM_CUDA_USE_DMABUF': '1',
            }.items()]
        env += [{'name': name, 'valueFrom': {'fieldRef': {'fieldPath': field}}} for name, field in {
            'POD_IP': 'status.podIP', 'POD_NAME': 'metadata.name',
            'POD_NAMESPACE': 'metadata.namespace', 'POD_UID': 'metadata.uid'}.items()]
        common_mounts = [{'name': name, 'mountPath': path, 'readOnly': True} for name, path in
                         [('candidate', '/candidate'), ('guard-runtime', '/guard-runtime'), ('efa', '/efa')]]
        common_mounts += [{'name': 'guard-socket', 'mountPath': '/run/kvcr'}]
        main['env'] = env
        main['volumeMounts'] = [v for v in main['volumeMounts'] if v['name'] != 'guard-runtime'] + common_mounts
        main['command'] = ['bash', '/efa/entrypoint.sh']
        main['args'] = ['python3', '/candidate/bootstrap.py', 'python3', '/guard-runtime/runtime.py', 'engine']
        main['resources']['requests']['vpc.amazonaws.com/efa'] = '8'
        main['resources']['limits']['vpc.amazonaws.com/efa'] = '8'
        service_env = [e for e in env if e['name'] not in ('CONTAINER_NAME', 'DYN_SYSTEM_PORT', 'NVIDIA_VISIBLE_DEVICES')]
        service_env += [{'name': 'CONTAINER_NAME', 'value': 'kvcr-services'},
                        {'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'none'},
                        {'name': 'NVIDIA_DRIVER_CAPABILITIES', 'value': 'compute,utility'},
                        {'name': 'DYN_SYSTEM_PORT', 'value': '9091'},
                        {'name': 'DYN_DISCOVERY_BACKEND', 'value': 'kubernetes'}]
        spec['containers'].append({'name': 'kvcr-services', 'image': model['runtime_image'],
            'command': ['bash', '/efa/entrypoint.sh'],
            'args': ['python3', '/candidate/bootstrap.py', 'python3', '/guard-runtime/runtime.py', 'service'],
            'env': service_env, 'securityContext': {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK']}},
            'resources': {'requests': {'cpu': '2', 'memory': '6Gi', 'vpc.amazonaws.com/efa': '1'},
                          'limits': {'memory': '8Gi', 'vpc.amazonaws.com/efa': '1'}},
            'readinessProbe': {'httpGet': {'path': '/ready', 'port': 9092},
                               'periodSeconds': 5, 'timeoutSeconds': 2, 'failureThreshold': 3},
            'volumeMounts': common_mounts + [{'name': 'guard-memory', 'mountPath': '/dev/shm/kvcr'}]})
    graph['spec']['components'] = components
    return graph, claims


def deploy(run):
    require_lease(run)
    if run.state.get('guard_deployed_at'):
        raise ValueError('A deployment already started in this run; inspect it before any new action.')
    node = run.get('get', 'node', NODE)
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']):
        raise ValueError('The reserved node is not Ready.')
    for claim in run.get('get', 'resourceclaims', '-A')['items']:
        devices = claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', [])
        if any(d.get('pool') == NODE for d in devices) and claim['metadata'].get('namespace') != run.ns:
            raise ValueError('A foreign GPU claim is active on cp-0124; preserve it.')
    candidate = run.state['kvcr_guard_candidate']
    native_gate = ui.read_json(run.path / 'native-runtime-compatibility.json')
    native_pod = ui.read_json(run.path / 'native-runtime-ready-pod.json')
    if (not native_gate.get('passed') or native_gate.get('runtime_class') != 'nvidia-legacy' or
            native_gate.get('engine_visible_devices') != 'void' or native_gate.get('guard_visible_devices') != 'none' or
            native_pod['metadata']['namespace'] != run.ns or native_pod['spec'].get('nodeName') != NODE or
            native_pod['status']['phase'] != 'Succeeded' or
            any(s['imageID'].split('@')[-1] != candidate['base_image'].split('@')[-1]
                for s in native_pod['status']['containerStatuses'])):
        raise ValueError('The exact driver-only/DRA native-runtime gate must pass before model loading.')
    receipt = ui.read_json(run.path / ('cpu-' + candidate['identity'] + '.json'))
    if receipt['status'] != 'passed' or ui.digest(BOOTSTRAP) != candidate['bootstrap_sha256']:
        raise ValueError('The exact bootstrap must pass its CPU gate before deployment.')
    if 'dynamo_nightly' in candidate:
        expected_version = candidate['dynamo_nightly']['version']
        if any(receipt['result']['packages'][name] != expected_version
               for name in ('ai-dynamo', 'ai-dynamo-runtime')):
            raise ValueError('Both nightly Dynamo packages must pass the same version gate.')
    code = RUNTIME.read_text()
    runtime_name = 'kvcr-guard-runtime-' + hashlib.sha256(code.encode()).hexdigest()[:12]
    graph, claims = render(run.ns, ui.read_json(ui.MODEL_LOCK), candidate, runtime_name)
    for obj in [graph, *claims]:
        obj['metadata']['labels'] = run.labels()
    runtime = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': runtime_name},
               'immutable': True, 'data': {'runtime.py': code}}
    directory = ROOT / 'configs/dgd/workshop-kvcr-guard' / run.path.name
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {'apiVersion': 'v1', 'kind': 'List', 'items': [*claims, graph]}
    support.write_yaml(directory / 'deployment.yaml', manifest)
    ui.write_json(run.path / 'deployment.json', manifest)
    ui.write_json(run.path / 'runtime-configmap.json', runtime)
    run.k('apply', '--dry-run=client', '-f', str(run.path / 'deployment.json'))
    run.k('apply', '--dry-run=server', '-f', str(run.path / 'deployment.json'))
    run.apply([runtime, *claims])
    run.state.update(guard_deployed_at=ui.now(), guard_runtime_sha256=ui.digest(RUNTIME),
                     guard_native_runtime_gate_sha256=ui.digest(run.path / 'native-runtime-compatibility.json'),
                     guard_manifest_sha256=ui.digest(run.path / 'deployment.json'))
    run.save()
    run.apply([graph])
    print('Submitted two TP2 engines on cp-0124 with separate Guard-owned pools.', flush=True)


def replacement_engine(previous, current):
    # Kubernetes container discovery can retain the endpoint ID across a main
    # container restart. Prove a new EngineCore incarnation, not a new endpoint.
    return (current.get('command', '').startswith('VLLM::EngineCore') and
            bool(current.get('start_ticks')) and current['start_ticks'] != previous['start_ticks'])


def wait(run, timeout, phase='initial', previous_workers=None, baseline_pods=None, previous_engine=None):
    require_lease(run)
    if phase == 'handback' and (not previous_workers or not previous_engine):
        raise ValueError('Handback readiness requires the pre-fault worker and engine identities.')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pods = run.get('get', 'pods', '-n', run.ns, '-l', 'workshop-kvcr-guard=true')['items']
        if baseline_pods is None:
            support.healthy(pods)
        else:
            if phase != 'handback':
                raise ValueError('A recorded container baseline is only valid for handback.')
            # A separately scoped diagnostic may have admitted a recorded
            # source-main restart. Require every identity and restart count to
            # remain unchanged from that baseline, including both Guards.
            stable_containers(baseline_pods, peers(run))
            support.healthy([p for p in pods if p['metadata']['labels']['workshop-role'] != 'worker'])
        for pod in pods:
            if pod['spec'].get('nodeName') and pod['spec']['nodeName'] != NODE:
                raise ValueError('An owned Pod escaped the cp-0124 node scope.')
            for container in ('main', 'kvcr-services') if pod['metadata']['labels']['workshop-role'] == 'worker' else ('main',):
                log = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', container,
                            '--timestamps=true', '--tail=160', check=False)
                (run.path / (pod['metadata']['name'] + '-' + container + '.log')).write_text(log.stdout + log.stderr)
        ready = (len(pods) == 3 and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                                          for c in p.get('status', {}).get('conditions', [])) for p in pods))
        if ready and phase == 'handback':
            # The main container supervises the engine. Its startup probe stays
            # successful after the child dies, so Pod Ready alone is insufficient.
            current_pods = peers(run)
            current = worker_ids(run, current_pods)
            if current.get('b') != previous_workers['b']:
                raise ValueError('Surviving worker identity changed during handback.')
            ready = False
            if current.get('a'):
                try:
                    current_engine = inspect_engine(run, current_pods['a'])
                except (ValueError, RuntimeError):
                    # No EngineCore yet, even if Pod readiness is still sticky.
                    pass
                else:
                    ready = replacement_engine(previous_engine, current_engine)
        if ready:
            from gpu_claims import verify_allocation
            expected = ui.read_json(ui.MODEL_LOCK)['runtime_image'].split('@')[-1]
            for pod in pods:
                for status in pod['status']['containerStatuses']:
                    if status['imageID'].split('@')[-1] != expected:
                        raise ValueError('Observed image differs from the locked base image.')
                if pod['metadata']['labels']['workshop-role'] == 'worker':
                    verify_allocation(run, pod, pod['spec']['containers'][0], 2)
            ui.write_json(run.path / ('ready-pods.json' if phase == 'initial' else phase + '-ready-pods.json'), {'items': pods})
            run.state['guard_ready_at' if phase == 'initial' else 'guard_' + phase + '_ready_at'] = ui.now()
            run.save()
            print('Two engines and their Guard services are Ready on the expected base image and node.', flush=True)
            return
        print('Waiting for Guard/engine readiness: ' + str(round(timeout - (deadline - time.monotonic()))) + 's', flush=True)
        time.sleep(10)
    raise TimeoutError('Guard workers did not become Ready.')


def peers(run):
    pods = run.get('get', 'pods', '-n', run.ns, '-l', 'workshop-kvcr-guard=true')['items']
    result = {p['metadata']['labels']['kvcr-peer']: p for p in pods
              if p['metadata']['labels']['workshop-role'] == 'worker'}
    if set(result) != {'a', 'b'}:
        raise ValueError('Expected exactly the two owned engine Pods.')
    for pod in result.values():
        if (pod['metadata'].get('namespace') != run.ns or pod['spec'].get('nodeName') != NODE or
                pod['metadata']['labels'].get('feature-test-run') != run.ns or
                pod['spec'].get('hostPID') or pod['spec'].get('shareProcessNamespace')):
            raise ValueError('Pod ownership, node or process isolation changed.')
    return result


def owned_exec(run, pod, container, *command, **kwargs):
    require_lease(run)
    actual = run.get('get', 'pod', pod['metadata']['name'], '-n', run.ns)
    if (actual['metadata']['uid'] != pod['metadata']['uid'] or
            actual['metadata'].get('labels', {}).get('feature-test-run') != run.ns or
            actual['spec'].get('nodeName') != NODE or actual['spec'].get('hostPID') or
            actual['spec'].get('shareProcessNamespace')):
        raise ValueError('Refusing process/container access after identity or isolation changed.')
    return run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', container, '--', *command, **kwargs)


def worker_ids(run, pods):
    items = run.get('get', 'dynamoworkermetadatas', '-n', run.ns)['items']
    result = {}
    for peer, pod in pods.items():
        entries = [x for x in items if x['metadata']['name'] == pod['metadata']['name']]
        if not entries:
            continue
        item = entries[0]
        if not any(o.get('kind') == 'Pod' and o.get('uid') == pod['metadata']['uid']
                   for o in item['metadata'].get('ownerReferences', [])):
            raise ValueError('Stale worker metadata does not match the owned Pod UID.')
        ids = {str(e['instance_id']) for e in item['spec']['data'].get('endpoints', {}).values()
               if e.get('component') == 'backend' and e.get('endpoint') == 'generate'}
        if len(ids) == 1:
            result[peer] = next(iter(ids))
    return result


def snapshot(run, label):
    pods = peers(run)
    folder = run.path / label
    folder.mkdir(exist_ok=False)
    ui.write_json(folder / 'pods.json', pods)
    ui.write_json(folder / 'metadata.json', run.get('get', 'dynamoworkermetadatas', '-n', run.ns))
    values = {}
    program = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9090/metrics',timeout=5).read().decode())"
    for peer, pod in pods.items():
        for container in ('main', 'kvcr-services'):
            logs = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', container,
                         '--timestamps=true', '--limit-bytes=10000000', check=False)
            (folder / (peer + '-' + container + '.log')).write_text(logs.stdout + logs.stderr)
        response = owned_exec(run, pod, 'main', 'python3', '-c', program, check=False)
        values[peer] = response.stdout if response.returncode == 0 else ''
        (folder / (peer + '-metrics.txt')).write_text(response.stdout + response.stderr)
    return values


def metric(text, name, labels):
    total = 0.0
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        series = line.rsplit(' ', 1)
        if len(series) != 2:
            continue
        actual = series[0].split('{', 1)[0]
        if actual.removesuffix('_total') == name.removesuffix('_total') and all(
                f'{key}="{value}"' in series[0] for key, value in labels.items()):
            total += float(series[1])
    return total


def delta(before, after, name, labels):
    value = metric(after, name, labels) - metric(before, name, labels)
    if value < 0:
        raise ValueError('A metric counter reset across the qualification interval.')
    return value


def response(run, base, label, prompt, expected_worker, *, pin=True):
    body = {'model': run.state['model_lock']['model'], 'messages': [{'role': 'user', 'content': prompt}],
            'max_completion_tokens': 16, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False},
            'stream': True, 'stream_options': {'include_usage': True},
            'nvext': {'extra_fields': ['worker_id', 'timing']}}
    folder = run.path / label
    folder.mkdir(exist_ok=False)
    ui.write_json(folder / 'request.json', body)
    # Pinning is only for controlled placement. Request migration is disabled.
    headers = {'x-dynamo-worker-instance-id': expected_worker, 'x-dynamo-dp-rank': '0'} if pin else {}
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    chunks, raw = [], bytearray()
    request = Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json', **headers})
    started = time.monotonic()
    events = []
    done = False
    status, read_error = None, None
    try:
        with urlopen(request, timeout=180) as stream:
            status = stream.status
            for line in stream:
                raw.extend(line)
                data = line.decode().strip()
                if data == 'data: [DONE]':
                    done = True
                    events.append({'seconds': time.monotonic() - started, 'done': True})
                elif data.startswith('data: '):
                    if done:
                        raise ValueError('Received more stream data after DONE.')
                    chunk = json.loads(data[6:])
                    chunks.append(chunk)
                    events.append({'seconds': time.monotonic() - started, 'chunk': chunk})
    except HTTPError as error:
        status = error.code
        raw.extend(error.read())
        read_error = str(error)
    except Exception as error:
        read_error = type(error).__name__ + ': ' + str(error)
    finally:
        (folder / 'response.sse').write_bytes(raw)
        ui.write_json(folder / 'events.json', events)
        ui.write_json(folder / 'http.json', {'status': status, 'headers': headers,
                                           'read_error': read_error, 'request_count': 1})
    errors = [c['error'] for c in chunks if c.get('error')]
    finishes = [x.get('finish_reason') for c in chunks for x in c.get('choices', []) if x.get('finish_reason')]
    observed = {str(c['nvext']['worker_id']['decode_worker_id']) for c in chunks
                if c.get('nvext', {}).get('worker_id', {}).get('decode_worker_id') is not None}
    ids = {c['id'] for c in chunks if c.get('id')}
    content = ''.join(x.get('delta', {}).get('content') or '' for c in chunks for x in c.get('choices', []))
    usage = next((c['usage'] for c in reversed(chunks) if c.get('usage')), None)
    wrong_model = any(c.get('model') != body['model'] for c in chunks if c.get('choices'))
    proof = {'http_requests': 1, 'status': status, 'done': done, 'errors': errors, 'read_error': read_error, 'finishes': finishes,
             'workers': sorted(observed), 'response_ids': sorted(ids), 'content': content, 'usage': usage,
             'sse_sha256': ui.digest(folder / 'response.sse')}
    ui.write_json(folder / 'response.json', proof)
    if (status != 200 or not done or errors or read_error or not finishes or any(f not in ('stop', 'length') for f in finishes)
            or wrong_model or observed != {expected_worker} or len(ids) != 1 or 'READY' not in content):
        raise ValueError('Request did not finish successfully on its expected worker: ' + label)
    return proof


def inspect_engine(run, pod, action='inspect', expected=None):
    program = (ROOT / 'demos/request_continuity/probe.py').read_text()
    command = ['python3', '-c', program, action]
    if expected:
        command.append(json.dumps(expected))
    result = owned_exec(run, pod, 'main', *command, timeout=35)
    rows = [x[len('RESULT_JSON='):] for x in result.stdout.splitlines() if x.startswith('RESULT_JSON=')]
    if len(rows) != 1:
        raise ValueError('Engine probe did not return one guarded identity/receipt.')
    return json.loads(rows[0])


def assert_engine_absent(run, pod):
    program = """import json
from pathlib import Path
found=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdecimal():continue
 try:command=(proc/'cmdline').read_bytes().split(b'\\0')[0].decode(errors='replace')
 except OSError:continue
 if command.startswith('VLLM::EngineCore'):found.append({'pid':proc.name,'command':command})
print(json.dumps(found))
"""
    found = json.loads(owned_exec(run, pod, 'main', 'python3', '-c', program).stdout)
    if found:
        raise ValueError('Source engine is alive during the Guard-only interval.')


def stable_containers(before, after):
    for peer in ('a', 'b'):
        old, new = before[peer], after[peer]
        if old['metadata']['uid'] != new['metadata']['uid']:
            raise ValueError('A worker Pod was replaced instead of retaining its Guard.')
        for previous in old['status']['containerStatuses']:
            current = next(x for x in new['status']['containerStatuses'] if x['name'] == previous['name'])
            if (current['containerID'] != previous['containerID'] or
                    current['restartCount'] != previous['restartCount']):
                raise ValueError('An engine supervisor or Guard container restarted.')
            if peer == 'b' and current['name'] == 'main' and not current['ready']:
                raise ValueError('The surviving engine is not Ready.')
        guard = next(x for x in new['status']['containerStatuses'] if x['name'] == 'kvcr-services')
        if not guard['ready']:
            raise ValueError('A Guard service is not Ready.')


def event_fields(text, event):
    ansi = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
    result = []
    for line in ansi.sub('', text).splitlines():
        if 'KVCR_EVENT ' + event + ' ' in line:
            values = dict(re.findall(r'([\w_]+)=([^\s]+)', line))
            result.append({**values, 'line': line})
    return result


def transfer_proof(source_log, target_log, source_ip, expected_blocks, expected_bytes, *, target_transport_log=None):
    promotions = event_fields(source_log, 'guard_promoted')
    if len(promotions) != 1 or int(promotions[0]['recovered_blocks']) <= 0:
        raise ValueError('Expected one nonempty Guard promotion.')
    promoted_at = source_log.index('KVCR_EVENT guard_promoted ')
    source_events = event_fields(source_log[promoted_at:], 'source_transfer_completed')
    target_events = [e for e in event_fields(target_log, 'target_transfer_completed')
                     if e.get('scope') == 'remote_deliver' and e.get('source') == f'tcp://{source_ip}:23280']
    if not target_events or any(e['result'] != 'success' for e in target_events):
        raise ValueError('Target did not complete a successful transfer from the Guard endpoint.')
    matched = []
    for target in target_events:
        # Source `op` is the requesting target's wire handle. `source_op`
        # is a different, source-local operation id (remote_ops.py).
        sources = [s for s in source_events if s.get('op') == target['op']]
        if len(sources) != 1 or any(sources[0].get(key) != target.get(key) for key in ('blocks', 'bytes', 'result')):
            raise ValueError('Source/target transfer receipts do not match.')
        matched.append({'source': sources[0], 'target': target})
    blocks = sum(int(e['blocks']) for e in target_events)
    size = sum(int(e['bytes']) for e in target_events)
    if blocks != expected_blocks or size != expected_bytes or blocks <= 0 or size <= 0:
        raise ValueError('Transfer logs and target metric deltas disagree.')
    transport_log = target_log if target_transport_log is None else target_transport_log
    if 'using provider=efa' not in source_log or 'using provider=efa' not in transport_log:
        raise ValueError('Missing native EFA provider evidence.')
    if 'KVCR pool recovery disabled' in source_log:
        raise ValueError('Guard recovery was disabled during this run.')
    return {'promotion': promotions[0], 'matched_transfers': matched, 'blocks': blocks, 'bytes': size,
            'transport_evidence': {'source': [l for l in source_log.splitlines() if 'using provider=efa' in l],
                                   'target': [l for l in transport_log.splitlines() if 'using provider=efa' in l]},
            'scope': 'Inter-engine LIBFABRIC/EFA transfer on one node; no cross-node qualification.'}


def verify(run):
    require_lease(run)
    if (run.path / 'fault-intent.json').exists() or run.state.get('guard_verified_at'):
        raise ValueError('A fault already started/completed in this run; do not replay it.')
    if ui.digest(RUNTIME) != run.state['guard_runtime_sha256']:
        raise ValueError('Runtime source changed after deployment.')
    initial = peers(run)
    support.healthy(list(initial.values()))
    from gpu_claims import verify_allocation
    allocations = {}
    for peer, pod in initial.items():
        claim = verify_allocation(run, pod, pod['spec']['containers'][0], 2)
        if not any(o.get('kind') == 'Pod' and o.get('uid') == pod['metadata']['uid']
                   for o in claim['metadata'].get('ownerReferences', [])):
            raise ValueError('GPU claim does not belong to its current worker Pod.')
        allocations[peer] = claim
    devices = [{(d['pool'], d['device']) for d in c['status']['allocation']['devices']['results']}
               for c in allocations.values()]
    if devices[0] & devices[1] or any(pool != NODE for group in devices for pool, _ in group):
        raise ValueError('Workers must own separate GPU pairs within cp-0124.')
    ui.write_json(run.path / 'qualified-gpu-claims.json', allocations)
    identities = worker_ids(run, initial)
    if set(identities) != {'a', 'b'}:
        raise ValueError('Both current engine endpoints must be registered before testing.')
    engine = inspect_engine(run, initial['a'])
    ui.write_json(run.path / 'qualification-identities.json', {'pods': initial, 'worker_ids': identities, 'engine': engine})
    tag = str(time.time_ns())
    prefix = lambda label: 'Repository context ' + label + ' ' + tag + '. ' + ' apple' * 6000 + '\nReply with READY.'
    with frontend(run, run.state.get('guard_frontend_topology', 'kvcr-guard')) as base:
        from urllib.request import urlopen
        for _ in range(30):
            try:
                with urlopen(base + '/v1/models', timeout=3) as stream:
                    models = json.load(stream)
                ui.write_json(run.path / 'models-last.json', models)
                if run.state['model_lock']['model'] in [m.get('id') for m in models.get('data', [])]:
                    ui.write_json(run.path / 'models.json', models)
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise ValueError('Frontend did not advertise the exact expected model.')
        normal = prefix('ordinary-peer-reuse')
        response(run, base, 'ordinary-source', normal, identities['a'])
        time.sleep(15)
        ordinary_before = snapshot(run, 'ordinary-before')
        ordinary = response(run, base, 'ordinary-target', normal, identities['b'])
        time.sleep(15)
        ordinary_after = snapshot(run, 'ordinary-after')
        if delta(ordinary_before['b'], ordinary_after['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'}) <= 0:
            raise ValueError('Ordinary peer reuse did not pass before fault injection.')
        cached = ordinary['usage'].get('prompt_tokens_details', {}).get('cached_tokens', 0)
        if cached <= 0:
            raise ValueError('Ordinary peer request did not reuse cached input tokens.')
        print(f'Ordinary peer reuse passed: {cached} cached input tokens on engine B.', flush=True)
        critical = prefix('guard-only-recovery')
        before_seed = snapshot(run, 'before-seed')
        seeded = response(run, base, 'guard-source-seed', critical, identities['a'])
        time.sleep(15)
        before_fault = snapshot(run, 'before-fault')
        if (delta(before_seed['a'], before_fault['a'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) <= 0 or
                delta(before_seed['a'], before_fault['a'], 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'}) <= 0):
            raise ValueError('No committed writes to the source Guard-owned pool.')
        if (delta(before_seed['b'], before_fault['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) != 0 or
                delta(before_seed['b'], before_fault['b'], 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'}) != 0):
            raise ValueError('Target was seeded during source-only cache preparation.')
        stable_containers(initial, peers(run))
        print('Unique recovery prefix committed on A; B has not been seeded. Injecting the owned engine fault.', flush=True)
        intent = {'at': ui.now(), 'pod_uid': initial['a']['metadata']['uid'], 'engine': engine,
                  'worker_id': identities['a'], 'verifier_sha256': ui.digest(Path(__file__))}
        with (run.path / 'fault-intent.json').open('x') as stream:
            stream.write(json.dumps(intent, indent=2) + '\n')
        owned_exec(run, initial['a'], 'kvcr-services', 'python3', '-c',
                   "from pathlib import Path;Path('/run/kvcr/hold-engine').open('x').close()")
        signal_receipt = inspect_engine(run, initial['a'], 'kill', engine)
        if not signal_receipt.get('signal_sent'):
            raise ValueError('Fault send was not acknowledged.')
        ui.write_json(run.path / 'fault-signal.json', signal_receipt)
        print('Source EngineCore kill acknowledged; holding its replacement down.', flush=True)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            logs = run.k('logs', initial['a']['metadata']['name'], '-n', run.ns, '-c', 'kvcr-services',
                         '--timestamps=true').stdout
            promotions = event_fields(logs, 'guard_promoted')
            if promotions:
                if int(promotions[-1]['recovered_blocks']) <= 0:
                    raise ValueError('Guard promoted without any recoverable blocks.')
                assert_engine_absent(run, initial['a'])
                print('Guard promoted with ' + promotions[-1]['recovered_blocks'] + ' preserved blocks.', flush=True)
                break
            time.sleep(2)
        else:
            raise TimeoutError('Guard did not promote after EngineCore death.')
        stable_containers(initial, peers(run))
        before_retrieval = snapshot(run, 'guard-only-before')
        retrieved = response(run, base, 'guard-target-retrieval', critical, identities['b'], pin=False)
        print('Surviving engine completed the Guard-only request; checking cache-transfer evidence.', flush=True)
        if retrieved['content'].strip() != seeded['content'].strip():
            raise ValueError('Recovered request output differs from its source baseline.')
        time.sleep(15)
        after_retrieval = snapshot(run, 'guard-only-after')
        assert_engine_absent(run, initial['a'])
        stable_containers(initial, peers(run))
        count = delta(before_retrieval['b'], after_retrieval['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'})
        size = delta(before_retrieval['b'], after_retrieval['b'], 'vllm:kv_offload_tiering_read_bytes', {'tier': '1:kvcr'})
        tokens = delta(before_retrieval['b'], after_retrieval['b'], 'vllm:prompt_tokens_by_source', {'source': 'external_kv_transfer'})
        if count <= 0 or size <= 0 or tokens <= 0:
            raise ValueError('Guard retrieval did not produce positive transfer bytes/blocks and external KV tokens.')
        for outcome in ('failed', 'partial'):
            if delta(before_retrieval['b'], after_retrieval['b'], 'vllm:kvcr_duration_seconds_count',
                     {'scope': 'remote_deliver', 'result': outcome}) != 0:
                raise ValueError('Guard retrieval had failed/partial deliveries.')
        source_log = (run.path / 'guard-only-after/a-kvcr-services.log').read_text()
        old_target = (run.path / 'guard-only-before/b-main.log').read_text()
        target_log = (run.path / 'guard-only-after/b-main.log').read_text()
        new_target = target_log[len(old_target):] if target_log.startswith(old_target) else target_log
        # Keep the transport-selection header as well as the isolated transfer interval.
        proof = transfer_proof(source_log, new_target, initial['a']['status']['podIP'], count, size,
                               target_transport_log=target_log)
        proof.update(status='passed', external_kv_tokens=tokens, source_worker=identities['a'], target_worker=identities['b'],
                     source_engine_absent=True, guards_and_pods_unchanged=True, at=ui.now())
        ui.write_json(run.path / 'guard-recovery-proof.json', proof)
        run.result('kvcr-guard-recovery', 'passed', blocks=count, bytes=size, external_tokens=tokens,
                   scope=proof['scope'])
        print('PASS: Guard served preserved cache while source EngineCore remained absent.\n' +
              json.dumps({k:v for k,v in proof.items() if k not in ('promotion','matched_transfers')}, indent=2), flush=True)
        owned_exec(run, initial['a'], 'kvcr-services', 'python3', '-c',
                   "from pathlib import Path;Path('/run/kvcr/hold-engine').unlink()")
        wait(run, 2700, phase='handback', previous_workers=identities, previous_engine=engine)
        current = worker_ids(run, peers(run))
        replacement = inspect_engine(run, peers(run)['a'])
        if not current.get('a') or current.get('b') != identities['b'] or not replacement_engine(engine, replacement):
            raise ValueError('Replacement/survivor worker identities did not match the handback scenario.')
        handback = response(run, base, 'source-handback', critical, current['a'])
        stable_containers(initial, peers(run))
        ui.write_json(run.path / 'handback-proof.json', {'status': 'passed', 'at': ui.now(),
                      'old_worker': identities['a'], 'new_worker': current['a'],
                      'original_engine': engine, 'replacement_engine': replacement, 'response': handback})
    run.state['guard_verified_at'] = ui.now()
    run.save()


def cleanup(run):
    require_lease(run)
    # A CPU-only qualification frontend can bypass an operator-injected
    # namespace-prefix mismatch without rolling either loaded engine.
    if run.state.get('guard_frontend_topology') == 'kvcr-guard-qualified':
        name = 'ft-kvcr-guard-qualified-frontend'
        for kind in ('pod', 'service'):
            found = run.k('get', kind, name, '-n', run.ns, '-o', 'json', check=False)
            if found.returncode == 0:
                obj = json.loads(found.stdout)
                if obj['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                    raise ValueError('Qualification frontend is not owned by this run.')
                if kind == 'pod':
                    logs = run.k('logs', name, '-n', run.ns, '-c', 'main', '--timestamps=true', check=False)
                    (run.path / 'final-qualified-frontend.log').write_text(logs.stdout + logs.stderr)
                run.k('delete', kind, name, '-n', run.ns, '--wait=true', '--timeout=60s', timeout=75)
            elif 'NotFound' not in found.stderr:
                raise RuntimeError(found.stderr)
    from common_runtime_tests import stop
    stop(run, [GRAPH])
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        pods = run.get('get', 'pods', '-n', run.ns)['items']
        claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
        graphs = run.get('get', 'dgd', '-n', run.ns)['items']
        if not pods and not claims and not graphs:
            proof = {'status': 'passed', 'at': ui.now(), 'namespace': run.ns,
                     'pods': [], 'claims': [], 'graphs': [], 'scope': 'Owned namespace only; routing reservation/workloads preserved.'}
            ui.write_json(run.path / 'cleanup-proof.json', proof)
            run.result('kvcr-guard-cleanup', 'passed', **{k:v for k,v in proof.items() if k!='status'})
            support.release(run.path, OWNER)
            print('Verified zero owned Pods/claims/DGDs; own lease released.', flush=True)
            return
        time.sleep(3)
    raise RuntimeError('Cleanup incomplete; preserve the GPU reservation.')


def cpu(run):
    require_lease(run)
    candidate = source_candidate(run)
    identity = candidate['identity']
    result_file = run.path / ('cpu-' + identity + '.json')
    if result_file.exists():
        raise ValueError('Candidate already has a CPU receipt; inspect it rather than replay it.')
    name = 'kvcr-cpu-' + identity
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 300,
        'automountServiceAccountToken': False, 'imagePullSecrets': [{'name': 'common-runtime-pull'}],
        'nodeSelector': {'kubernetes.io/hostname': NODE},
        'containers': [{'name': 'probe', 'image': candidate['base_image'],
            'command': ['python3', '/candidate/bootstrap.py', 'check'],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                    {'name': 'KVCR_BUNDLE_SHA256', 'value': candidate['bundle_sha256']}],
            'securityContext': {'runAsUser': 0},
            'resources': {'requests': {'cpu': '1', 'memory': '4Gi'}, 'limits': {'memory': '8Gi'}},
            'volumeMounts': [{'name': 'candidate', 'mountPath': '/candidate', 'readOnly': True}]}],
        'volumes': [{'name': 'candidate', 'configMap': {'name': candidate['configmap']}}]}}
    run.apply([pod])
    receipt = {'status': 'failed', 'candidate': candidate, 'started_at': ui.now()}
    try:
        finished = run.wait_pod(name, completed=True, timeout=360)
        image = finished['status']['containerStatuses'][0]['imageID'].split('@')[-1]
        if image != candidate['base_image'].split('@')[-1]:
            raise ValueError('Probe ran an unexpected image.')
        logs = run.k('logs', name, '-n', run.ns).stdout
        result = json.loads(logs.strip().splitlines()[-1])
        if result.get('status') != 'passed':
            raise ValueError('CPU compatibility did not pass.')
        receipt.update(status='passed', result=result, observed_image=image)
        run.state['kvcr_guard_candidate'] = candidate
        run.save()
        print(json.dumps(result, indent=2), flush=True)
    except Exception as error:
        receipt['error'] = str(error)
        raise
    finally:
        logs = run.k('logs', name, '-n', run.ns, check=False)
        log_file = run.path / (name + '.log')
        log_file.write_text(logs.stdout + logs.stderr)
        receipt.update(finished_at=ui.now(), log_sha256=ui.digest(log_file))
        ui.write_json(result_file, receipt)
        run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=60s', timeout=75)
        if receipt['status'] != 'passed':
            print(logs.stdout[-3500:] + logs.stderr[-500:], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['cpu', 'deploy', 'wait', 'verify', 'cleanup'])
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=2700)
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'cpu':
        cpu(run)
    elif args.action == 'deploy':
        deploy(run)
    elif args.action == 'wait':
        wait(run, args.timeout)
    elif args.action == 'verify':
        verify(run)
    else:
        cleanup(run)


if __name__ == '__main__':
    main()
