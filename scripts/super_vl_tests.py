#!/usr/bin/env python3
"""Fresh, model-pinned TP2 Super VL workshop feature qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from testlib import ROOT, Run

MODEL = 'nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'


def fetch(url):
    token = os.environ.get('HF_TOKEN')
    token_path = Path.home() / '.cache/huggingface/token'
    if not token and token_path.is_file():
        token = token_path.read_text().strip()
    headers = {'User-Agent': 'dynamo-workshop-feature-tests'}
    if token and url.startswith('https://huggingface.co/'):
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return response.read()


def metadata(run):
    meta = json.loads(fetch(f'https://huggingface.co/api/models/{MODEL}'))
    revision = meta['sha']
    if len(revision) != 40:
        raise ValueError('Expected an immutable checkpoint revision')
    directory = run.path / 'model-metadata'
    directory.mkdir(exist_ok=True)
    (directory / 'api.json').write_text(json.dumps(meta, indent=2) + '\n')
    files = {}
    for name in ('config.json', 'tokenizer_config.json', 'model.safetensors.index.json', 'README.md'):
        data = fetch(f'https://huggingface.co/{MODEL}/resolve/{revision}/{name}')
        (directory / name).write_bytes(data)
        files[name] = hashlib.sha256(data).hexdigest()
    config = json.loads((directory / 'config.json').read_text())
    index = json.loads((directory / 'model.safetensors.index.json').read_text())
    base = json.loads((ROOT / 'configs/common-runtime-qualified.json').read_text())
    lock = {key: value for key, value in base.items() if key != 'qualification'}
    lock.update(model=MODEL, revision=revision, architecture=config.get('architectures'),
                tensor_parallel_size=2, gpu_allocation='dra',
                manifest_directory='super-vl-tp2', model_metadata_sha256=files,
                checkpoint_weight_bytes=index.get('metadata', {}).get('total_size'),
                checkpoint_weight_files=len(set(index['weight_map'].values())))
    destination = run.path / 'model-lock.json'
    if destination.exists() and json.loads(destination.read_text()) != lock:
        raise ValueError('Model/runtime identity changed; use a fresh run')
    destination.write_text(json.dumps(lock, indent=2) + '\n')
    from serving_tests import lock_model
    lock_model(run)
    run.result('super-vl-metadata', 'passed', model=MODEL, revision=revision,
               architecture=config.get('architectures'), weight_bytes=lock['checkpoint_weight_bytes'],
               weight_files=lock['checkpoint_weight_files'], tensor_parallel_size=2)


def runtime_source(run):
    """Inspect the actual pinned image on Kubernetes, without allocating GPUs."""
    from serving_tests import lock_model
    lock = lock_model(run)
    run.ensure_namespace()
    from common_runtime_tests import pull_secret
    pull_secret(run)
    program = """import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file('vllm'))
registry=(root/'model_executor/models/registry.py').read_text()
args=Path(m.distribution('ai-dynamo').locate_file('dynamo/vllm/backend_args.py'))
text=args.read_text() if args.is_file() else ''
print(json.dumps({'packages':{p:m.version(p) for p in ['vllm','ai-dynamo','gpu-memory-service','kvcr']},
 'architecture_registered':'NemotronH_Omni_Reasoning_V3' in registry,
 'multimodal_flag_present':'--enable-multimodal' in text,
 'native_engine':(root/'vllm-rs').is_file()}))
"""
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'super-vl-runtime-source'},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
            'automountServiceAccountToken': False,
            'imagePullSecrets': [{'name': lock['image_pull_secret']}],
            'containers': [{'name': 'inspect', 'image': lock['runtime_image'],
                'command': ['python3', '-c', program],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                'resources': {'requests': {'cpu': '1', 'memory': '1Gi'}, 'limits': {'memory': '2Gi'}}}]}}
    run.apply([pod])
    try:
        finished = run.wait_pod(pod['metadata']['name'], completed=True, timeout=240)
        report = json.loads(run.k('logs', pod['metadata']['name'], '-n', run.ns).stdout)
        report['image_id'] = finished['status']['containerStatuses'][0]['imageID']
        if report['image_id'].split('@')[-1] != lock['runtime_image'].split('@')[-1]:
            raise ValueError('Inspected image digest differs from the pinned runtime')
        (run.path / 'runtime-source-check.json').write_text(json.dumps(report, indent=2) + '\n')
        run.result('super-vl-runtime-source', 'present' if report['architecture_registered'] else 'blocked',
                   **report, scope='CPU-only installed registry inspection; no model loading or GPU qualification')
    finally:
        run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


def telemetry_probe(run):
    from serving_tests import lock_model
    lock = lock_model(run)
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'nixl-mp-probe'},
                'data': {'probe.py': (ROOT / 'scripts/nixl_mp_probe.py').read_text()}}])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'nixl-mp-probe'},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
            'automountServiceAccountToken': False, 'imagePullSecrets': [{'name': lock['image_pull_secret']}],
            'containers': [{'name': 'probe', 'image': lock['runtime_image'], 'command': ['python3', '/tests/probe.py'],
                'env': [{'name': k, 'value': v} for k, v in {
                    'NVIDIA_VISIBLE_DEVICES': 'void', 'UCX_TLS': 'tcp,self,sm,cuda_copy', 'NIXL_TELEMETRY_ENABLE': 'y',
                    'NIXL_TELEMETRY_EXPORTER': 'prometheus_mp', 'NIXL_TELEMETRY_MULTIPROC_DIR': '/tmp/nixl-metrics',
                    'NIXL_TELEMETRY_PROMETHEUS_PORT': '19090'}.items()],
                'resources': {'requests': {'cpu': '2', 'memory': '2Gi'}, 'limits': {'memory': '4Gi'}},
                'volumeMounts': [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]}],
            'volumes': [{'name': 'tests', 'configMap': {'name': 'nixl-mp-probe'}}]}}
    run.apply([pod])
    try:
        finished = run.wait_pod('nixl-mp-probe', completed=True, timeout=240)
        logs = run.k('logs', 'nixl-mp-probe', '-n', run.ns).stdout
        (run.path / 'nixl-mp-probe.log').write_text(logs)
        report = json.loads(next(line.split(' ', 1)[1] for line in logs.splitlines() if line.startswith('NIXL_MP_RESULT ')))
        report['image_id'] = finished['status']['containerStatuses'][0]['imageID']
        run.result('nixl-mp-telemetry', 'passed', **report)
    except Exception as error:
        run.result('nixl-mp-telemetry', 'blocked', error=str(error))
        raise
    finally:
        logs = run.k('logs', 'nixl-mp-probe', '-n', run.ns, check=False)
        (run.path / 'nixl-mp-probe.log').write_text(logs.stdout + logs.stderr)
        run.k('delete', 'pod', 'nixl-mp-probe', '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=60s', check=False)


def feature(run, name):
    """One bounded feature, with cleanup even when its verifier fails."""
    from serving_tests import lock_model
    from common_runtime_tests import test, stop, stop_grove
    lock = lock_model(run)
    if lock['model'] != MODEL or lock.get('tensor_parallel_size') != 2:
        raise ValueError('Requires this exact Super VL TP2 run')
    graphs = {'agg': ['ft-agg'], 'disagg': ['ft-disagg'], 'sidecar': ['ft-sidecar'],
              'kvcr': ['ft-kvcr'], 'mx': ['ft-mx-target', 'ft-mx'], 'image-smoke': ['ft-image']}
    try:
        if name == 'image-smoke':
            image_smoke(run)
        elif name == 'snapshot-runtime':
            from snapshot_runtime_tests import test as preparation
            preparation(run)
        elif name == 'shadow':
            shadow(run)
        else:
            test(run, name)
        run.result('super-vl-' + name, 'passed', model=MODEL, tensor_parallel_size=2)
    except Exception as error:
        run.result('super-vl-' + name, 'blocked', error=str(error), model=MODEL, tensor_parallel_size=2)
        if name in graphs or name in ('snapshot', 'shadow'):
            from inspect_super_vl_runtime import collect
            try:
                collect(run, 'ft-' + ('mx' if name == 'mx' else 'image' if name == 'image-smoke' else name))
            except Exception as diagnostic_error:
                run.result('super-vl-diagnostics-' + name, 'blocked', error=str(diagnostic_error))
        raise
    finally:
        if name in graphs:
            stop(run, graphs[name])
        elif name == 'grove':
            stop_grove(run)
        elif name == 'snapshot':
            from snapshot_tests import cleanup
            cleanup(run)


def shadow(run):
    """Reuse the source-hashed compatibility overlay only on its original runtime."""
    from shadow_failover_tests import runtime, preflight, deploy, verify
    from shadow_live_tests import wait_standby, finish_cleanup
    if any((run.path / name).exists() for name in ('shadow-fault-intent.json', 'shadow-fault.json')):
        raise ValueError('A fault was already injected in this run; use a fresh run')
    runtime(run)
    infra = preflight(run)
    if infra['blockers']:
        raise RuntimeError(infra['blockers'])
    prior = json.loads((ROOT / 'configs/patches/shadow-gms-vllm031/manifest.json').read_text())
    patch = prior['patch']
    path = ROOT / patch['path']
    current = run.state['checks']['shadow-runtime']
    if run.state['model_lock']['runtime_image'] != prior['runtime_image']:
        raise ValueError('Compatibility overlay was verified against a different image')
    source = current['files']['gpu_memory_service/integrations/vllm/patches.py']
    if source['sha256'] != patch['original_sha256'] or hashlib.sha256(path.read_bytes()).hexdigest() != patch['sha256']:
        raise ValueError('Compatibility overlay source/hash mismatch')
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': patch['configmap']},
                'immutable': True, 'data': {'patches.py': path.read_text()}}])
    run.state['shadow_compat_patch'] = patch
    run.save()
    run.result('shadow-compat-patch', 'prepared', **patch,
               scope='Source/image-verified test-local request_memory overlay; no shared image change')
    try:
        deploy(run)
        wait_standby(run, 1200)
        verify(run, 120, infra['eligible_nodes'])
    except Exception:
        from inspect_super_vl_runtime import collect
        collect(run, 'ft-shadow')
        raise
    finally:
        finish_cleanup(run)


def status(run):
    from serving_tests import status as serving_status
    serving_status(run, brief=True)
    download = run.k('get', 'pod', 'model-download', '-n', run.ns, '-o', 'json', check=False)
    if download.returncode == 0:
        logs = run.k('logs', 'model-download', '-n', run.ns, '--tail=12', check=False)
        print(logs.stdout[-3000:], flush=True)
        (run.path / 'model-download-progress.log').write_text(logs.stdout + logs.stderr)
        if json.loads(download.stdout).get('status', {}).get('phase') == 'Running':
            program = '''import json,os
from pathlib import Path
root=Path('/efs/feature-tests')/os.environ['TEST_RUN']/'hf/hub'
sizes=[]
for p in root.rglob('*'):
 try:
  if p.is_file() and not p.is_symlink(): sizes.append((p.name,p.stat().st_size))
 except FileNotFoundError: pass
print(json.dumps({'cache_regular_bytes':sum(s for _,s in sizes),
 'incomplete_files':sum(n.endswith('.incomplete') for n,_ in sizes),
 'regular_files':len(sizes)}))
'''
            progress = run.k('exec', 'model-download', '-n', run.ns, '--', 'python3', '-c', program, check=False)
            print(progress.stdout or progress.stderr[-1000:], flush=True)
            (run.path / 'model-download-progress.json').write_text(progress.stdout)


def idle(run):
    import time
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        pods = run.get('get', 'pods', '-n', run.ns)['items']
        claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
        active = [p['metadata']['name'] for p in pods if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
        if not active and not claims:
            run.result('super-vl-idle', 'passed', active_pods=0, remaining_claims=0)
            return
        time.sleep(5)
    raise RuntimeError({'active_owned_pods': active,
                        'remaining_claims': [c['metadata']['name'] for c in claims]})


def vision(run, topology='agg'):
    """Actual image request, kept separate from the text feature receipts."""
    import base64
    import struct
    import zlib
    from serving_tests import frontend, request
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 128, 128, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * 128) * 128)) + chunk(b'IEND', b'')
    (run.path / 'vision-red.png').write_bytes(png)
    url = 'data:image/png;base64,' + base64.b64encode(png).decode()
    with frontend(run, topology) as base:
        import urllib.error
        try:
            response = request(base + '/v1/chat/completions', {'model': MODEL,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': url}},
                    {'type': 'text', 'text': 'What is the dominant color of this image? Reply with one word.'}]}],
                'temperature': 0, 'max_tokens': 32, 'chat_template_kwargs': {'enable_thinking': False}})
        except urllib.error.HTTPError as error:
            body = error.read().decode()
            (run.path / 'vision-error.json').write_text(json.dumps({'status': error.code, 'body': body}, indent=2) + '\n')
            raise RuntimeError(f'Image request HTTP {error.code}: {body[:2500]}') from error
    (run.path / 'vision-response.json').write_text(json.dumps(response, indent=2) + '\n')
    assert response['choices'][0]['message']['content'].strip().strip('.').lower() == 'red'
    run.result('super-vl-image', 'passed', model=MODEL, tensor_parallel_size=2,
               topology=topology, scope='One synthetic image on an aggregated worker; no video or image-aware routing qualification')


def image_smoke(run):
    from serving_tests import render, smoke
    graph = render(run, 'agg')
    graph['metadata']['name'] = 'ft-image'
    for component in graph['spec']['components']:
        if component['type'] != 'frontend':
            component['replicas'] = 1
            spec = component['podTemplate']['spec']
            spec.pop('affinity', None)
            spec['nodeSelector'] = {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'}
            spec['containers'][0]['args'].append('--enable-multimodal')
    directory = ROOT / 'configs/dgd' / run.state['model_lock']['manifest_directory']
    run.write_manifest(directory / 'nemotron-image-smoke.yaml', [graph])
    run.apply([graph])
    smoke(run, 'image')
    vision(run, 'image')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('metadata', 'download', 'runtime-source', 'telemetry-probe', 'feature', 'status', 'vision', 'idle'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--feature', choices=('probe', 'agg', 'sidecar', 'kvcr', 'disagg', 'mx', 'grove',
                                             'shadow-runtime', 'shadow', 'snapshot-runtime', 'snapshot', 'image-smoke'))
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'metadata':
        metadata(run)
    elif args.action == 'runtime-source':
        runtime_source(run)
    elif args.action == 'telemetry-probe':
        telemetry_probe(run)
    elif args.action == 'feature':
        if args.feature is None:
            parser.error('feature requires --feature')
        feature(run, args.feature)
    elif args.action == 'status':
        status(run)
    elif args.action == 'vision':
        vision(run)
    elif args.action == 'idle':
        idle(run)
    else:
        from serving_tests import download
        from common_runtime_tests import pull_secret, efa
        download(run)
        pull_secret(run)
        efa(run)


if __name__ == '__main__':
    main()
