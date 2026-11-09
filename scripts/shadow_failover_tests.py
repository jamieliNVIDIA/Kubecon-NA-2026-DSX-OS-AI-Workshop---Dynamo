#!/usr/bin/env python3
"""Guarded intra-Pod vLLM Shadow Engine failover; no shared infrastructure changes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import yaml
from serving_tests import frontend, lock_model, model_cache_home, status, worker_args, worker_resources
from testlib import ROOT, OWNER, Run

GRAPH = 'ft-shadow'
METRIC = 'dynamo_component_engine_failover'


def write(run, name, value):
    (run.path / name).write_text(json.dumps(value, indent=2) + '\n')


def preflight(run):
    report = {}
    report['version'] = json.loads(run.k('version', '-o', 'json').stdout)['serverVersion']
    report['deviceclasses'] = run.get('get', 'deviceclasses')['items']
    report['resourceslices'] = run.get('get', 'resourceslices')['items']
    nodes = run.get('get', 'nodes')['items']
    report['nodes'] = [{'name': n['metadata']['name'], 'labels': n['metadata'].get('labels', {}),
                        'info': n['status']['nodeInfo'], 'conditions': n['status']['conditions']}
                       for n in nodes]
    report['dra_helm_values'] = json.loads(run.command([
        '/opt/homebrew/bin/helm', '--kubeconfig', str(ROOT / '.local/kubeconfig'),
        'get', 'values', 'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json']).stdout)
    deployments = run.get('get', 'deployments', '-A')['items']
    daemonsets = run.get('get', 'daemonsets', '-A')['items']
    pods = run.get('get', 'pods', '-A')['items']
    report['infrastructure'] = [{'name': o['metadata']['name'], 'namespace': o['metadata']['namespace'],
        'status': o.get('status', {}), 'containers': o['spec']['template']['spec'].get('containers', [])}
        for o in deployments + daemonsets if any(s in o['metadata']['name']
                                                for s in ('dynamo-operator', 'dra-driver', 'device-plugin'))]
    crd = run.get('get', 'crd', 'dynamographdeployments.nvidia.com')
    schema = next(v for v in crd['spec']['versions'] if v['name'] == 'v1beta1')['schema']['openAPIV3Schema']
    experimental = schema['properties']['spec']['properties']['components']['items']['properties']['experimental']['properties']
    report['experimental_fields'] = sorted(experimental)
    blockers = []
    version = report['version']
    if (int(version['major']), int(re.sub(r'\D', '', version['minor']))) < (1, 34):
        blockers.append('Kubernetes >=1.34 is required')
    for field in ('failover', 'gpuMemoryService'):
        if field not in experimental:
            blockers.append(f'Installed DGD CRD lacks experimental.{field}')
    if not report['dra_helm_values'].get('resources', {}).get('gpus', {}).get('enabled'):
        blockers.append('NVIDIA DRA resources.gpus.enabled=false (ComputeDomain-only installation)')
    if not report['dra_helm_values'].get('gpuResourcesEnabledOverride'):
        blockers.append('NVIDIA DRA gpuResourcesEnabledOverride=false; experimental GPU allocation is not enabled')
    if 'gpu.nvidia.com' not in {d['metadata']['name'] for d in report['deviceclasses']}:
        blockers.append('Missing gpu.nvidia.com DeviceClass')
    gpu_slices = [s for s in report['resourceslices'] if s['spec']['driver'] == 'gpu.nvidia.com']
    if not any(s['spec'].get('devices') for s in gpu_slices):
        blockers.append('No GPU devices advertised by gpu.nvidia.com ResourceSlices')
    ready_nodes = {n['metadata']['name'] for n in nodes
                   if any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions'])
                   and 'H100' in n['metadata'].get('labels', {}).get('nvidia.com/gpu.product', '')}
    advertised = {s['spec'].get('nodeName') for s in gpu_slices if s['spec'].get('devices')}
    device_plugin_nodes = {p['spec'].get('nodeName') for p in pods
                          if 'nvidia-device-plugin' in p['metadata']['name']
                          and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')}
    gpu_plugin_ready_nodes = {p['spec'].get('nodeName') for p in pods
        if 'dra-driver' in p['metadata']['name'] and any(c['name'] == 'gpus' and c.get('ready')
            for c in p.get('status', {}).get('containerStatuses', []))}
    report['gpu_plugin_ready_nodes'] = sorted(n for n in gpu_plugin_ready_nodes if n)
    report['device_plugin_nodes'] = sorted(n for n in device_plugin_nodes if n)
    # The two allocators do not coordinate GPU ownership. Fail closed until an
    # administrator gives the test node a single allocator.
    report['eligible_nodes'] = sorted((ready_nodes & advertised & gpu_plugin_ready_nodes) - device_plugin_nodes)
    if not report['eligible_nodes']:
        blockers.append('No Ready H100 test node with a Ready GPU DRA plugin/inventory and without a competing NVIDIA device plugin')
    if not any('dynamo-operator' in o['name'] for o in report['infrastructure']):
        blockers.append('No Dynamo operator deployment found')
    for obj in report['infrastructure']:
        if 'dynamo-operator' in obj['name'] and obj['status'].get('readyReplicas', 0) < 1:
            blockers.append('Dynamo operator is not Ready')
    report['blockers'] = blockers
    write(run, 'shadow-preflight.json', report)
    run.result('shadow-preflight', 'blocked' if blockers else 'present',
               blockers=blockers, eligible_nodes=report['eligible_nodes'],
               scope='Infrastructure presence and allocator isolation only; runtime/model and actual DRA allocation still need qualification')
    return report


def render(run, node=None):
    lock = lock_model(run)
    sources = json.loads((ROOT / 'configs/shadow-source.json').read_text())
    relative = 'examples/backends/vllm/deploy/agg_failover.yaml'
    path = ROOT / 'configs/upstream/shadow' / sources['revision'] / relative
    digest = next(f['sha256'] for f in sources['files'] if f['path'] == relative)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Pinned upstream failover template changed')
    graph = copy.deepcopy(yaml.safe_load(path.read_text()))
    graph['metadata'].update(name=GRAPH, namespace=run.ns, labels=run.labels())
    graph['spec']['backendFramework'] = 'vllm'
    for component in graph['spec']['components']:
        component['runtimeVersionOverride'] = lock['runtime_release']
        spec = component['podTemplate']['spec']
        spec['volumes'] = [
            {'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
            {'name': 'dshm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}}]
        spec['activeDeadlineSeconds'] = 3600
        component['podTemplate'].setdefault('metadata', {}).setdefault('labels', {}).update(run.labels())
        container = spec['containers'][0]
        container.pop('envFrom', None)
        container['image'] = lock['runtime_image']
        if lock.get('image_pull_secret'):
            spec['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
        container['volumeMounts'] = [{'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True},
                                     {'name': 'dshm', 'mountPath': '/dev/shm'}]
        container['env'] = [{'name': k, 'value': v} for k, v in {
            'HF_HOME': model_cache_home(run), 'HF_HUB_OFFLINE': '1', 'HF_MODULES_CACHE': '/tmp/hf_modules',
            'VLLM_CACHE_ROOT': '/tmp/vllm-cache', 'TRITON_CACHE_DIR': '/tmp/triton-cache',
            'NCCL_IB_DISABLE': '1', 'PYTHONHASHSEED': '0'}.items()]
        if component['type'] == 'frontend':
            if lock.get('common_runtime'):
                container['env'].append({'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'})
            container['command'] = ['python3', '-m', 'dynamo.frontend']
            container['args'] = ['--router-mode', 'round-robin', '--trust-remote-code']
            container['resources'] = {'requests': {'cpu': '1', 'memory': '4Gi'}, 'limits': {'memory': '8Gi'}}
        else:
            patch = run.state.get('shadow_compat_patch')
            if patch:
                patch_source = ROOT / patch['path']
                if hashlib.sha256(patch_source.read_bytes()).hexdigest() != patch['sha256']:
                    raise ValueError('Shadow compatibility overlay changed')
                spec['volumes'].append({'name': 'shadow-gms-compat',
                                        'configMap': {'name': patch['configmap']}})
                container['volumeMounts'].append({'name': 'shadow-gms-compat',
                    'mountPath': '/usr/local/lib/python3.12/dist-packages/gpu_memory_service/integrations/vllm/patches.py',
                    'subPath': 'patches.py', 'readOnly': True})
                component['podTemplate']['metadata'].setdefault('annotations', {})[
                    'workshop.nvidia.com/shadow-gms-compat-sha256'] = patch['sha256']
            component['sharedMemorySize'] = '16Gi'
            component['experimental'] = {'gpuMemoryService': {}, 'failover': {}}
            container['args'] = worker_args(lock['model'], lock['revision'], 'agg', tp=lock.get('tensor_parallel_size', 1))
            # Both engines need transient private warm-up/context headroom.
            container['args'][container['args'].index('--gpu-memory-utilization') + 1] = '0.65'
            if lock.get('tensor_parallel_size', 1) > 1:
                # This image hit FlashAttention illegal access after GMS remap.
                # Keep the bounded recovery check on eager FlashInfer attention.
                container['args'] += ['--attention-backend', 'FLASHINFER', '--enforce-eager']
            if lock.get('shadow_control_model'):
                for flag in ('--mamba-backend', '--mamba-ssm-cache-dtype', '--mamba-cache-mode', '--reasoning-parser'):
                    index = container['args'].index(flag)
                    del container['args'][index:index + 2]
                for flag, value in (('--max-model-len', '1024'), ('--max-num-seqs', '4'),
                                    ('--max-num-batched-tokens', '1024'), ('--gpu-memory-utilization', '0.25')):
                    container['args'][container['args'].index(flag) + 1] = value
            # The failover operator staggers KV-event ports; an explicit shared
            # ZMQ endpoint would override that and collide across containers.
            index = container['args'].index('--kv-events-config')
            del container['args'][index:index + 2]
            container['args'] += ['--load-format', 'gms', '--enable-sleep-mode']
            container['resources'] = worker_resources(lock)
            # Cloned into two engines; leave HBM headroom for two contexts/graphs.
            container['env'].append({'name': 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT', 'value': '180'})
            spec['affinity'] = {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {
                'nodeSelectorTerms': [{'matchExpressions': [{'key': 'nvidia.com/gpu.product',
                    'operator': 'In', 'values': ['NVIDIA-H100-80GB-HBM3']}]}]}}}
            if node:
                spec['nodeSelector'] = {'kubernetes.io/hostname': node}
    directory = ROOT / 'configs/dgd' / lock.get('manifest_directory', 'common-runtime' if lock.get('common_runtime') else '')
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('qwen-shadow-control.yaml' if lock.get('shadow_control_model') else 'nemotron-shadow-failover.yaml')
    run.write_manifest(destination, [graph])
    write(run, 'shadow-manifest.json', graph)
    run.state.setdefault('graphs', {})['shadow'] = {'name': GRAPH, 'manifest': str(destination)}
    run.save()
    return graph


def dry_run(run):
    graph = render(run)
    run.ensure_namespace()
    content = json.dumps(graph)
    run.k('apply', '--dry-run=client', '-f', '-', input_text=content)
    # Admission validation must not be confused with controller reconciliation.
    run.k('apply', '--dry-run=server', '-f', '-', input_text=content)
    run.result('shadow-manifest', 'passed', scope='Client and server admission dry-run only; no DGD created')


def deploy(run):
    infra = preflight(run)
    if infra['blockers']:
        run.result('shadow-deployment', 'blocked', blockers=infra['blockers'])
        run.result('shadow-failover', 'blocked', blockers=infra['blockers'], fault_injected=False)
        return
    if run.state.get('checks', {}).get('model-staging', {}).get('status') != 'passed':
        raise ValueError('Verify/stage the locked model cache before deploying')
    if run.state.get('checks', {}).get('shadow-runtime', {}).get('status') != 'present':
        raise ValueError('Inspect the frozen runtime entrypoints with the runtime action before deploying')
    graph = render(run, infra['eligible_nodes'][0])
    run.apply([graph])
    run.result('shadow-deployment', 'created', name=GRAPH, physical_gpus=lock_model(run).get('tensor_parallel_size', 1),
               engine_containers=2, node=infra['eligible_nodes'][0], model=run.state['model_lock']['model'])


def runtime(run):
    lock = lock_model(run)
    run.ensure_namespace()
    program = '''import hashlib,importlib.metadata,json
from pathlib import Path
packages={p:importlib.metadata.version(p) for p in ('ai-dynamo','ai-dynamo-runtime','vllm')}
root=Path(importlib.metadata.distribution('ai-dynamo').locate_file(''))
paths=('gpu_memory_service/integrations/vllm/worker.py',
       'gpu_memory_service/integrations/vllm/patches.py',
       'gpu_memory_service/failover_lock/failover_metrics.py',
       'gpu_memory_service/common/protocol/messages.py',
       'dynamo/vllm/args.py','dynamo/vllm/main.py')
files={p:{'present':(root/p).is_file(),'sha256':hashlib.sha256((root/p).read_bytes()).hexdigest() if (root/p).is_file() else None} for p in paths}
text='\\n'.join(p.read_text() for p in (root/'dynamo/vllm').rglob('*.py'))
signals={s:s in text for s in ('DYN_VLLM_GMS_SHADOW_MODE','create_failover_metrics','gms_shadow_mode')}
print(json.dumps({'packages':packages,'files':files,'shadow_entrypoints':signals}))
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'shadow-runtime-inspect'},
           'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180, 'automountServiceAccountToken': False,
                    'containers': [{'name': 'inspect', 'image': lock['runtime_image'], 'command': ['python3', '-c', program],
                                    'resources': {'requests': {'cpu': '1', 'memory': '1Gi'}, 'limits': {'memory': '2Gi'}}}]}}
    if lock.get('image_pull_secret'):
        pod['spec']['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
    if lock.get('common_runtime'):
        pod['spec']['containers'][0]['env'] = [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}]
    run.apply([pod])
    try:
        complete = run.wait_pod('shadow-runtime-inspect', timeout=240, completed=True)
        report = json.loads(run.k('logs', 'shadow-runtime-inspect', '-n', run.ns).stdout)
        report['image_id'] = complete['status']['containerStatuses'][0]['imageID']
        write(run, 'shadow-runtime.json', report)
        present = all(f['present'] for f in report['files'].values()) and all(report['shadow_entrypoints'].values())
        run.result('shadow-runtime', 'present' if present else 'blocked', **report,
                   scope='CPU-only inspection of pinned runtime entrypoints; does not prove H100/Nemotron GMS startup or failover')
    finally:
        run.k('delete', 'pod', 'shadow-runtime-inspect', '-n', run.ns, '--wait=true', '--timeout=60s', check=False)


def owned_pod(run):
    ns = run.get('get', 'namespace', run.ns)
    if ns['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER:
        raise ValueError('Namespace is not owned')
    graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
    if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('DGD is not owned')
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    candidates = [p for p in pods if {c['name'] for c in p['spec'].get('containers', [])} >= {'engine-0', 'engine-1'}
                  and p['metadata'].get('labels', {}).get('feature-test-run') == run.ns
                  and p['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == GRAPH]
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one owned shadow worker Pod, found {len(candidates)}')
    pod = candidates[0]
    if pod['spec'].get('shareProcessNamespace'):
        raise ValueError('Refusing fault injection with shared process namespaces')
    return pod


def exec_probe(run, pod, container, action, *args):
    result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', container,
                   '--', 'python3', '-c', (ROOT / 'scripts/shadow_probe.py').read_text(), action, *args,
                   timeout=35)
    return json.loads(result.stdout.strip().splitlines()[-1])


def counter(metrics, suffix, **labels):
    values = []
    for line in metrics.splitlines():
        if line.startswith(f'{METRIC}_{suffix}' + '{'):
            text, value = line.rsplit(' ', 1)
            if all(f'{key}="{val}"' in text for key, val in labels.items()):
                values.append(float(value))
    if len(values) != 1:
        raise RuntimeError(f'Expected one failover metric {suffix} {labels}, found {values}')
    return values[0]


def snapshot(run):
    pod = owned_pod(run)
    spec = pod['spec']
    containers = {c['name']: c for c in spec['containers'] + spec.get('initContainers', [])}
    statuses = {c['name']: c for c in pod['status'].get('containerStatuses', []) + pod['status'].get('initContainerStatuses', [])}
    selected = ['engine-0', 'engine-1', 'gms-server']
    if not all(n in containers and n in statuses and 'running' in statuses[n]['state'] for n in selected):
        raise RuntimeError('Both engines and GMS must be running')
    claims = [c['resources'].get('claims') for n, c in containers.items() if n in selected]
    if not claims[0] or not all(c == claims[0] for c in claims):
        raise RuntimeError('Engines/GMS are not consuming the same GPU claim')
    claim_name = claims[0][0]['name']
    actual_name = next(c['resourceClaimName'] for c in pod['status']['resourceClaimStatuses'] if c['name'] == claim_name)
    claim = run.get('get', 'resourceclaim', actual_name, '-n', run.ns)
    allocations = claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', [])
    tp = lock_model(run).get('tensor_parallel_size', 1)
    if len(allocations) != tp or any(a['driver'] != 'gpu.nvidia.com' for a in allocations):
        raise RuntimeError(f'Expected {tp} allocated NVIDIA GPUs for the shadow test')
    observations = {n: exec_probe(run, pod, n, 'engine') for n in selected[:2]}
    if len(set(observations['engine-0']['gpu_uuids'])) != tp or observations['engine-0']['gpu_uuids'] != observations['engine-1']['gpu_uuids']:
        raise RuntimeError(f'Engines do not see exactly the same ordered {tp} physical GPUs')
    states = {}
    for name, report in observations.items():
        states[name] = next(s for s in ('init', 'standby', 'waking', 'active')
                            if counter(report['metrics'], 'state', state=s, engine_id=report['engine_id']) == 1)
    gms = exec_probe(run, pod, 'gms-server', 'gms')
    for suffix in ('_weights.sock', '_kv_cache.sock'):
        if sum(name.endswith(suffix) for name in gms) != tp:
            raise RuntimeError(f'Expected {tp} GMS device sockets for {suffix}')
    result = {'pod_name': pod['metadata']['name'], 'pod_uid': pod['metadata']['uid'],
              'node': spec['nodeName'], 'container_statuses': {n: statuses[n] for n in selected},
              'claim': claim, 'engines': observations, 'states': states, 'gms': gms}
    write(run, f'shadow-observation-{time.time_ns()}.json', result)
    return result


def completion(base, model, timeout=15):
    deadline = time.monotonic() + timeout
    payload = {'model': model, 'messages': [{'role': 'user', 'content': 'Reply with exactly READY.'}],
               'temperature': 0, 'max_tokens': 32, 'chat_template_kwargs': {'enable_thinking': False},
               'stream': True, 'stream_options': {'include_usage': True},
               'nvext': {'extra_fields': ['worker_id']}}
    req = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        chunks = []
        for line in response:
            if time.monotonic() > deadline:
                raise TimeoutError('Completion stream exceeded its request deadline')
            text = line.decode().strip()
            if text.startswith('data: ') and text[6:] != '[DONE]':
                chunks.append(json.loads(text[6:]))
    content = ''.join(c['choices'][0].get('delta', {}).get('content', '') or '' for c in chunks if c.get('choices'))
    worker = next((c['nvext']['worker_id'] for c in reversed(chunks) if c.get('nvext', {}).get('worker_id')), None)
    result = {'chunks': chunks, 'content': content, 'worker': worker}
    if not chunks or any(c.get('error') for c in chunks) or chunks[0].get('model') != model or content.strip().strip('.') != 'READY' or not worker:
        raise RuntimeError(f'Unexpected model or response: {result}')
    return result


def verify(run, timeout, eligible_nodes):
    if any((run.path / name).exists() for name in ('shadow-fault-intent.json', 'shadow-fault.json')):
        raise ValueError('A fault was already attempted in this run; use a fresh run')
    before = snapshot(run)
    if before['node'] not in eligible_nodes:
        raise RuntimeError('The target Pod is not on a node with verified allocator isolation')
    if sorted(before['states'].values()) != ['active', 'standby']:
        raise RuntimeError('Require exactly one active engine and one warmed, parked standby before injection')
    active = next(n for n, s in before['states'].items() if s == 'active')
    standby = next(n for n, s in before['states'].items() if s == 'standby')
    aid, sid = before['engines'][active]['engine_id'], before['engines'][standby]['engine_id']
    for report in before['engines'].values():
        if not report['lock_held'] or report['lock_owner'] != f'engine-{aid}':
            raise RuntimeError('Failover lock does not match observed active engine')
    success0 = counter(before['engines'][standby]['metrics'], 'switch_success_total', engine_id=sid)
    attempt0 = counter(before['engines'][standby]['metrics'], 'switch_attempts_total', engine_id=sid)
    model = lock_model(run)['model']
    with frontend(run, 'shadow') as base:
        with urllib.request.urlopen(base + '/v1/models', timeout=10) as response:
            models = json.load(response)
        if model not in {m['id'] for m in models['data']}:
            raise RuntimeError('Locked model not registered')
        baseline = completion(base, model)
        write(run, 'shadow-baseline-response.json', baseline)
        write(run, 'shadow-worker-metadata-before.json', run.get('get', 'dynamoworkermetadatas', '-n', run.ns))
        pod = owned_pod(run)
        if pod['metadata']['uid'] != before['pod_uid']:
            raise RuntimeError('Pod changed before injection')
        # Check the target runtime is unchanged at the mutation boundary.
        observed = {c['name']: c for c in pod['status']['containerStatuses']}
        if observed[active]['containerID'] != before['container_statuses'][active]['containerID']:
            raise RuntimeError('Active container changed before injection')
        current_infra = preflight(run)
        if current_infra['blockers'] or pod['spec']['nodeName'] not in current_infra['eligible_nodes']:
            raise RuntimeError('Allocator isolation changed before injection')
        # Persist before exec: a fast container exit can make exec's outcome ambiguous.
        write(run, 'shadow-fault-intent.json', {'pod_uid': before['pod_uid'], 'container': active,
            'container_id': observed[active]['containerID'], 'engine_id': aid,
            'signal': 'SIGKILL', 'target': 'the single verified active EngineCore'})
        fault_started = time.monotonic()
        fault = exec_probe(run, pod, active, 'kill', '--expected-engine', aid)
        write(run, 'shadow-fault.json', fault)
        failures = []
        deadline = fault_started + timeout
        while time.monotonic() < deadline:
            try:
                response = completion(base, model, timeout=min(10, max(1, deadline - time.monotonic())))
                if response['worker']['decode_worker_id'] == baseline['worker']['decode_worker_id']:
                    raise RuntimeError('Frontend response still names the original worker')
            except (OSError, ValueError, KeyError, RuntimeError) as error:
                failures.append({'elapsed_seconds': time.monotonic() - fault_started, 'error': str(error)[-1000:]})
                time.sleep(0.5)
                continue
            elapsed = time.monotonic() - fault_started
            write(run, 'shadow-recovered-response.json', response)
            break
        else:
            write(run, 'shadow-request-failures.json', failures)
            raise TimeoutError(f'No verified recovered response within {timeout}s')
    write(run, 'shadow-request-failures.json', failures)
    write(run, 'shadow-worker-metadata-after.json', run.get('get', 'dynamoworkermetadatas', '-n', run.ns))
    # The restarted former active may still be initializing; wait for it to
    # park, without allowing a second failure injection or an unbounded loop.
    deadline = time.monotonic() + 900
    after = None
    while time.monotonic() < deadline:
        pod_now = owned_pod(run)
        if pod_now['metadata']['uid'] != before['pod_uid']:
            raise RuntimeError('Pod replaced during recovery')
        current_status = {c['name']: c for c in pod_now['status'].get('containerStatuses', []) + pod_now['status'].get('initContainerStatuses', [])}
        for name in (standby, 'gms-server'):
            if name not in current_status or current_status[name].get('containerID') != before['container_statuses'][name]['containerID']:
                raise RuntimeError(f'{name} disappeared/restarted during recovery')
        try:
            after = snapshot(run)
        except (RuntimeError, KeyError, StopIteration):
            time.sleep(5)
            continue
        if after['states'] == {active: 'standby', standby: 'active'}:
            break
        time.sleep(5)
    else:
        raise TimeoutError('Former active did not restart and park as the new standby within 900s')
    if before['pod_uid'] != after['pod_uid']:
        raise RuntimeError('Pod was replaced; this is not intra-Pod recovery')
    for name in (standby, 'gms-server'):
        old, new = before['container_statuses'][name], after['container_statuses'][name]
        if old['containerID'] != new['containerID'] or old['restartCount'] != new['restartCount']:
            raise RuntimeError(f'{name} restarted; cannot qualify shadow promotion')
    if after['container_statuses'][active]['restartCount'] <= before['container_statuses'][active]['restartCount']:
        raise RuntimeError('Killed active container has not restarted')
    sm = after['engines'][standby]['metrics']
    if not after['engines'][standby]['lock_held'] or after['engines'][standby]['lock_owner'] != f'engine-{sid}':
        raise RuntimeError('Promoted standby does not hold the failover lock')
    if counter(sm, 'switch_success_total', engine_id=sid) != success0 + 1 or counter(sm, 'switch_attempts_total', engine_id=sid) != attempt0 + 1:
        raise RuntimeError('No exactly-one successful standby promotion in failover metrics')
    for name, old in before['gms'].items():
        new = after['gms'].get(name)
        if not new:
            raise RuntimeError('GMS GPU/socket changed')
        if name.endswith('_weights.sock'):
            if not old['state']['memory_layout_hash'] or old['state']['memory_layout_hash'] != new['state']['memory_layout_hash']:
                raise RuntimeError('Committed weight layout changed')
            old_events, new_events = old['events']['events'], new['events']['events']
            if [e['kind'] for e in old_events] != ['rw_connected', 'committed'] or new_events != old_events:
                raise RuntimeError('Weights were republished instead of reused')
        elif name.endswith('_kv_cache.sock'):
            extra = new['events']['events'][len(old['events']['events']):]
            if not any(e['kind'] == 'allocations_cleared' and e['allocation_count'] > 0 for e in extra):
                raise RuntimeError('No evidence that failed engine KV backing was reclaimed')
    run.result('shadow-failover', 'passed', model=model, physical_gpus=lock_model(run).get('tensor_parallel_size', 1), active_before=active,
               active_after=standby, pod_uid=before['pod_uid'],
               fault_command_to_first_verified_response_seconds=elapsed,
               worker_before=baseline['worker'], worker_after=response['worker'],
               tensor_parallel_size=lock_model(run).get('tensor_parallel_size', 1),
               scope='EngineCore process failure at the locked TP size; timing includes kubectl exec overhead; no node/hardware failure, KV continuity, or throughput claim',
               failed_requests=len(failures), new_standby_confirmed=True)


def cleanup(run):
    graph = run.k('get', 'dgd', GRAPH, '-n', run.ns, '-o', 'json', check=False)
    if graph.returncode:
        if 'NotFound' not in graph.stderr:
            raise RuntimeError(graph.stderr)
        return
    if json.loads(graph.stdout)['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Refusing to delete unowned DGD')
    run.k('delete', 'dgd', GRAPH, '-n', run.ns, '--wait=true', '--timeout=90s', timeout=100)
    run.result('shadow-cleanup', 'passed', scope='Owned shadow DGD only; retain model cache/PVC')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'runtime', 'render', 'dry-run', 'deploy', 'status', 'verify', 'cleanup'))
    parser.add_argument('--run', type=Path)
    parser.add_argument('--recovery-timeout', type=int, default=120)
    args = parser.parse_args()
    if not 10 <= args.recovery_timeout <= 300:
        parser.error('--recovery-timeout must be 10..300 seconds')
    run = Run(args.run)
    print(f'Run: {run.path}', flush=True)
    if args.action == 'preflight':
        preflight(run)
    elif args.action == 'render':
        render(run)
    elif args.action == 'dry-run':
        dry_run(run)
    elif args.action == 'deploy':
        deploy(run)
    elif args.action == 'runtime':
        runtime(run)
    elif args.action == 'status':
        status(run, brief=True)
    elif args.action == 'cleanup':
        cleanup(run)
    else:
        infra = preflight(run)
        if infra['blockers']:
            raise RuntimeError('Infrastructure preflight is blocked; no failure injected')
        try:
            verify(run, args.recovery_timeout, infra['eligible_nodes'])
        except Exception as error:
            run.result('shadow-failover', 'failed', error=str(error))
            status(run, brief=True)
            raise


if __name__ == '__main__':
    main()
