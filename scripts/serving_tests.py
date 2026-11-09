#!/usr/bin/env python3
"""Pinned Nemotron model staging and bounded serving tests from upstream DGDs."""
import argparse
import contextlib
import copy
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import yaml
from feature_tests import BASE_IMAGE
from storage_tests import prepare
from testlib import ROOT, Run


def lock_model(run):
    if (run.path / 'model-lock.json').exists():
        lock = json.loads((run.path / 'model-lock.json').read_text())
    elif run.state.get('model_lock'):
        lock = run.state['model_lock']
    else:
        lock = json.loads((ROOT / 'configs/model-lock.json').read_text())
    if 'model_lock' in run.state and run.state['model_lock'] != lock:
        raise ValueError('Model/source lock changed; create a new run')
    run.state['model_lock'] = lock
    run.save()
    return lock


def model_cache_home(run):
    source = run.state.get('model_cache_run_id', run.state['run_id'])
    if Path(source).name != source or source in ('.', '..'):
        raise ValueError('Invalid model cache run identifier')
    return f'/model-cache/feature-tests/{source}/hf'


def download(run):
    prepare(run)
    lock = lock_model(run)
    deadline = 7200 if lock.get('tensor_parallel_size', 1) > 1 else 1800
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'model-download'},
        'data': {'download.py': (ROOT / 'scripts/model_download.py').read_text(),
                 'model-lock.json': json.dumps(lock)}}])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'model-download'},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': deadline,
            'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0198'},
            'containers': [{'name': 'download', 'image': BASE_IMAGE,
                'command': ['python3', '/tests/download.py'],
                'env': [{'name': 'TEST_RUN', 'value': run.state['run_id']}],
                'resources': {'requests': {'cpu': '2', 'memory': '8Gi'},
                              'limits': {'cpu': '4', 'memory': '16Gi'}},
                'securityContext': {'runAsUser': 0},
                'volumeMounts': [{'name': 'efs', 'mountPath': '/efs'},
                                 {'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]}],
            'volumes': [{'name': 'efs', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                        {'name': 'tests', 'configMap': {'name': 'model-download'}}]}}
    run.apply([pod])
    try:
        completed = run.wait_pod('model-download', completed=True, timeout=deadline + 100)
        logs = run.k('logs', 'model-download', '-n', run.ns).stdout
        (run.path / 'model-download.log').write_text(logs)
        report = json.loads(logs.strip().splitlines()[-1])
        report['image_id'] = completed['status']['containerStatuses'][0].get('imageID')
        run.state['model_download'] = report
        run.save()
        run.result('model-staging', 'passed', **report)
    finally:
        run.k('delete', 'pod', 'model-download', '-n', run.ns, '--wait=false', '--ignore-not-found', check=False)


def worker_args(model, revision, role, *, tp=1):
    args = ['--model', model, '--revision', revision, '--served-model-name', model,
            '--trust-remote-code', '--tensor-parallel-size', str(tp),
            '--max-model-len', '4096', '--max-num-seqs', '8',
            '--max-num-batched-tokens', '8192', '--gpu-memory-utilization', '0.65',
            '--enable-prefix-caching', '--block-size', '64',
            '--mamba-backend', 'flashinfer', '--mamba-ssm-cache-dtype', 'float16',
            '--mamba-cache-mode', 'align', '--reasoning-parser', 'nemotron_v3',
            '--kv-events-config', '{"publisher":"zmq","topic":"kv-events","endpoint":"tcp://*:20080","enable_kv_cache_events":true}',
            '--disaggregation-mode', role]
    if role in {'prefill', 'decode'}:
        args += ['--kv-transfer-config', json.dumps({'kv_connector': 'NixlConnector',
                 'kv_role': 'kv_producer' if role == 'prefill' else 'kv_consumer',
                 'kv_connector_extra_config': {'backends': ['LIBFABRIC']}})]
    if model == 'nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4':
        for flag, value in (('--max-model-len', '8192'), ('--max-num-seqs', '4'),
                            ('--gpu-memory-utilization', '0.85')):
            args[args.index(flag) + 1] = value
        args += ['--limit-mm-per-prompt', '{"image":1,"video":0}']
    return args


def worker_resources(lock):
    tp = lock.get('tensor_parallel_size', 1)
    return {'requests': {'cpu': '8' if tp > 1 else '4',
                         'memory': '128Gi' if tp > 1 else '64Gi', 'nvidia.com/gpu': str(tp)},
            'limits': {'memory': '256Gi' if tp > 1 else '128Gi', 'nvidia.com/gpu': str(tp)}}


def render(run, topology):
    lock = lock_model(run)
    if run.state.get('checks', {}).get('model-staging', {}).get('status') != 'passed':
        raise ValueError('Run model staging first')
    suffix = 'agg-h100-dspark-kv-router' if topology == 'agg' else 'disagg-h100-dspark'
    source = ROOT / f'configs/upstream/recipes/nemotron-3.5-lightning/vllm/{suffix}/deploy.yaml'
    documents = list(yaml.safe_load_all(source.read_text()))
    graph = next(d for d in documents if d and d['kind'] == 'DynamoGraphDeployment')
    graph = copy.deepcopy(graph)
    graph['metadata'] = {'name': f'ft-{topology}', 'namespace': run.ns, 'labels': run.labels()}
    components = graph['spec']['components']
    nodes = [n['metadata']['name'] for n in run.get('get', 'nodes')['items']]
    cache_home = model_cache_home(run)
    for component in components:
        component['podTemplate'].setdefault('metadata', {}).setdefault('labels', {}).update(run.labels())
        if lock.get('runtime_version_override'):
            component['runtimeVersionOverride'] = lock['runtime_version_override']
        spec = component['podTemplate']['spec']
        spec.pop('imagePullSecrets', None)
        if lock.get('image_pull_secret'):
            spec['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
        component['replicas'] = 1 if component['type'] != 'worker' else 2
        spec['volumes'] = [{'name': 'shared-model-cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                           {'name': 'dshm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}}]
        container = spec['containers'][0]
        container['image'] = lock['runtime_image']
        container['volumeMounts'] = [{'name': 'shared-model-cache', 'mountPath': '/model-cache'},
                                     {'name': 'dshm', 'mountPath': '/dev/shm'}]
        container['env'] = [{'name': 'HF_HOME', 'value': cache_home},
                            {'name': 'HF_HUB_OFFLINE', 'value': '1'},
                            {'name': 'HF_MODULES_CACHE', 'value': '/tmp/hf_modules'},
                            {'name': 'PYTHONHASHSEED', 'value': '0'},
                            {'name': 'NCCL_IB_DISABLE', 'value': '1'}]
        spec['activeDeadlineSeconds'] = 3600
        if component['type'] == 'frontend':
            container['command'] = ['python3', '-m', 'dynamo.frontend']
            container['args'] = ['--router-mode', 'kv', '--kv-cache-block-size', '64', '--trust-remote-code']
            container['resources'] = {'requests': {'cpu': '1', 'memory': '4Gi'}, 'limits': {'memory': '8Gi'}}
            if lock.get('common_runtime'):
                container['env'].append({'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'})
        else:
            role = 'agg' if topology == 'agg' else component['type']
            container['command'] = ['python3', '-m', 'dynamo.vllm']
            container['args'] = worker_args(lock['model'], lock['revision'], role, tp=lock.get('tensor_parallel_size', 1))
            component['sharedMemorySize'] = '16Gi'
            container['resources'] = {'requests': {'cpu': '4', 'memory': '64Gi', 'nvidia.com/gpu': '1'},
                                     'limits': {'memory': '128Gi', 'nvidia.com/gpu': '1'}}
            if lock.get('tensor_parallel_size', 1) > 1:
                container['resources'] = {'requests': {'cpu': '8', 'memory': '128Gi', 'nvidia.com/gpu': str(lock['tensor_parallel_size'])},
                                         'limits': {'memory': '256Gi', 'nvidia.com/gpu': str(lock['tensor_parallel_size'])}}
            if lock.get('common_runtime'):
                container['env'].append({'name': 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT', 'value': '180'})
            if topology == 'agg':
                spec.setdefault('affinity', {})['podAntiAffinity'] = {'requiredDuringSchedulingIgnoredDuringExecution': [
                    {'labelSelector': {'matchLabels': {'feature-test-role': 'agg'}}, 'topologyKey': 'kubernetes.io/hostname'}]}
                component['podTemplate'].setdefault('metadata', {}).setdefault('labels', {})['feature-test-role'] = 'agg'
            else:
                spec['nodeSelector'] = {'kubernetes.io/hostname': nodes[0 if role == 'prefill' else 1]}
                for resource_map in container['resources'].values():
                    resource_map['vpc.amazonaws.com/efa'] = str(4 * lock.get('tensor_parallel_size', 1))
                container['env'] += [{'name': key, 'value': value} for key, value in {
                    'FI_PROVIDER': 'efa', 'FI_EFA_USE_DEVICE_RDMA': '1', 'FI_EFA_FORK_SAFE': '1',
                    'FI_EFA_ENABLE_SHM_TRANSFER': '0', 'FI_HMEM_CUDA_USE_DMABUF': '1',
                    'NIXL_LIBFABRIC_USE_DEVICE_RDMA': '1', 'VLLM_SSM_CONV_STATE_LAYOUT': 'DS',
                    'NIXL_LOG_LEVEL': 'INFO', 'NIXL_TELEMETRY_ENABLE': 'y',
                    'NIXL_TELEMETRY_EXPORTER': 'prometheus_mp' if lock.get('tensor_parallel_size', 1) > 1 else 'prometheus',
                    'NIXL_TELEMETRY_PROMETHEUS_PORT': '19090',
                    **({'NIXL_TELEMETRY_MULTIPROC_DIR': '/tmp/nixl-metrics'} if lock.get('tensor_parallel_size', 1) > 1 else {})}.items()]
                container['command'] = ['bash', '/efa/entrypoint.sh']
                container['args'] = ['python3', '-m', 'dynamo.vllm'] + container['args']
                spec['volumes'].append({'name': 'efa', 'configMap': {'name': 'efa-userspace'}})
                container['volumeMounts'].append({'name': 'efa', 'mountPath': '/efa', 'readOnly': True})
    directory = ROOT / 'configs/dgd' / lock.get('manifest_directory', 'common-runtime' if lock.get('common_runtime') else '')
    destination = directory / f'nemotron-{topology}-functionality.yaml'
    destination.parent.mkdir(parents=True, exist_ok=True)
    run.write_manifest(destination, [graph])
    run.state.setdefault('graphs', {})[topology] = {'name': graph['metadata']['name'], 'template': str(source),
                                                 'manifest': str(destination)}
    run.save()
    return graph


def deploy(run, topology):
    graph = render(run, topology)
    if topology == 'disagg':
        code = (ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh').read_text()
        wrapper = '''#!/usr/bin/env bash
set -euo pipefail
export EFA_INSTALLER_VERSION=1.49.0
export EFA_INSTALLER_SHA256=cf2e9281a2328a243c76f911a490faed43ca0fecfe4733c25e34b2e92a32c309
export DEBIAN_FRONTEND=noninteractive
apt-get update
bash /efa/check-efa-userspace.sh install
export PATH=/opt/amazon/efa/bin:$PATH
export LD_LIBRARY_PATH=/opt/amazon/efa/lib:/opt/amazon/efa/lib64:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}
exec "$@"
'''
        if lock_model(run).get('common_runtime'):
            wrapper = (ROOT / 'scripts/efa-entrypoint.sh').read_text().replace('/tests/check-efa-userspace.sh', '/efa/check-efa-userspace.sh')
        run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'efa-userspace'},
                    'data': {'check-efa-userspace.sh': code, 'entrypoint.sh': wrapper}}])
    run.k('apply', '--dry-run=client', '-f', '-', input_text=json.dumps(graph))
    run.apply([graph])
    run.result(f'{topology}-deployment', 'created', name=graph['metadata']['name'],
               image=run.state['model_lock']['runtime_image'], gpu_count=2 * run.state['model_lock'].get('tensor_parallel_size', 1),
               note='Bounded functionality configuration; speculative decoding disabled to isolate features')


def status(run, brief=False):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    (run.path / 'owned-pods-status.json').write_text(json.dumps(pods, indent=2) + '\n')
    events = run.get('get', 'events', '-n', run.ns)
    (run.path / 'owned-events.json').write_text(json.dumps(events, indent=2) + '\n')
    graphs = run.get('get', 'dgd', '-n', run.ns)
    (run.path / 'graphs-status.json').write_text(json.dumps(graphs, indent=2) + '\n')
    summary={'namespace': run.ns, 'pods': [{'name': p['metadata']['name'],
        'node': p['spec'].get('nodeName'), 'phase': p.get('status', {}).get('phase'),
        'containers': [{'name': c['name'], 'ready': c['ready'], 'restarts': c['restartCount'],
                        'state': c.get('state'), 'image_id': c.get('imageID')}
                       for c in p.get('status', {}).get('initContainerStatuses', []) + p.get('status', {}).get('containerStatuses', [])]} for p in pods],
        'graph_status': [g.get('status', {}) for g in graphs['items']]}
    if brief:
        summary={'namespace':run.ns,'pods':[
            {'name':p['metadata']['name'],'phase':p.get('status',{}).get('phase'),
             'ready':[c.get('ready') for c in p.get('status',{}).get('containerStatuses',[])],
             'restarts':[c.get('restartCount') for c in p.get('status',{}).get('containerStatuses',[])]}
            for p in pods],
            'graphs':{g['metadata']['name']:g.get('status',{}).get('state') for g in graphs['items']}}
    print(json.dumps(summary,indent=2),flush=True)
    for p in pods:
        for c in p['spec'].get('initContainers', []) + p['spec'].get('containers', []):
            logs = run.k('logs', p['metadata']['name'], '-n', run.ns, '-c', c['name'], '--tail=300', check=False)
            (run.path / f'latest-{p["metadata"]["name"]}-{c["name"]}.log').write_text(logs.stdout + logs.stderr)


@contextlib.contextmanager
def frontend(run, topology):
    services = run.get('get', 'services', '-n', run.ns)['items']
    service = next(s for s in services if f'ft-{topology}' in s['metadata']['name']
                   and any(p['port'] == 8000 for p in s['spec'].get('ports', [])))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    log = (run.path / f'port-forward-{topology}.log').open('w')
    process = subprocess.Popen(run.kbase + ['port-forward', '-n', run.ns,
        f'service/{service["metadata"]["name"]}', f'{port}:8000', '--address=127.0.0.1'], stdout=log, stderr=log)
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('Frontend port-forward failed')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1):
                    break
            except OSError:
                time.sleep(1)
        else:
            raise TimeoutError('Frontend port-forward did not open')
        yield f'http://127.0.0.1:{port}'
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


def request(url, payload=None, headers=None):
    content = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=content, headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


def smoke(run, topology):
    lock = lock_model(run)
    model = lock['model']
    startup_timeout = 2400 if lock.get('tensor_parallel_size', 1) > 1 else 900
    run.k('wait', '--for=condition=Ready', f'dgd/ft-{topology}', '-n', run.ns,
          f'--timeout={startup_timeout}s', timeout=startup_timeout + 30)
    if lock.get('gpu_allocation') == 'dra':
        from gpu_claims import verify_allocation
        for pod in run.get('get', 'pods', '-n', run.ns)['items']:
            labels = pod['metadata'].get('labels', {})
            if (labels.get('nvidia.com/dynamo-graph-deployment-name') == 'ft-' + topology
                    and labels.get('nvidia.com/dynamo-component-type') != 'frontend'
                    and not pod['metadata'].get('deletionTimestamp')):
                verify_allocation(run, pod, pod['spec']['containers'][0], lock.get('tensor_parallel_size', 1))
    with frontend(run, topology) as base:
        models = request(base + '/v1/models')
        if model not in [x['id'] for x in models['data']]:
            raise ValueError('Expected model absent from /v1/models')
        response = request(base + '/v1/chat/completions', {'model': model,
            'messages': [{'role': 'user', 'content': 'Reply with the word READY.'}],
            'max_tokens': 128, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
        assert response['choices'] and response['usage']['completion_tokens'] > 0
        message = response['choices'][0]['message']
        assert message.get('content') or message.get('reasoning_content'), 'Empty generated response'
        if lock.get('tensor_parallel_size', 1) > 1:
            assert message.get('content', '').strip().strip('.') == 'READY', message
        (run.path / f'{topology}-smoke.json').write_text(json.dumps(response, indent=2) + '\n')
    run.result(f'{topology}-inference', 'passed', model=model, usage=response['usage'], message=message,
               scope='Model registration and inference only; transfer and routing require separate evidence')


def cleanup(run):
    run.ensure_namespace()
    for graph in run.get('get', 'dgd', '-n', run.ns)['items']:
        if graph['metadata'].get('labels', {}).get('feature-test-run') == run.ns:
            run.k('delete', 'dgd', graph['metadata']['name'], '-n', run.ns, '--wait=false')
    run.result('serving-cleanup', 'requested', note='Owned graphs deleted; model cache and receipts retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['download', 'agg', 'disagg', 'smoke', 'status', 'cleanup'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--topology', choices=['agg', 'disagg', 'sidecar', 'kvcr', 'mx-target'], default='agg')
    parser.add_argument('--brief', action='store_true', help='Print compact status while retaining full evidence')
    args = parser.parse_args()
    run = Run(args.run)
    try:
        if args.action == 'download': download(run)
        elif args.action in {'agg', 'disagg'}: deploy(run, args.action)
        elif args.action == 'smoke': smoke(run, args.topology)
        elif args.action == 'status': status(run,args.brief)
        else: cleanup(run)
    except Exception as exc:
        run.result(args.action, 'blocked', error=str(exc))
        raise


if __name__ == '__main__':
    main()
