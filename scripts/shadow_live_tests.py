#!/usr/bin/env python3
"""Qualify live GPU claims and the preferred-model common-image Shadow test."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from common_runtime_tests import pull_secret
from serving_tests import lock_model
from shadow_failover_tests import preflight, runtime, snapshot, owned_pod, counter, cleanup
from testlib import ROOT, Run
from upgrade_retests import cache
from serving_tests import download


def prepare(run):
    qualified = json.loads((ROOT / 'configs/common-runtime-qualified.json').read_text())
    source = ROOT / qualified['qualification']['run']
    lock = json.loads((source / 'model-lock.json').read_text())
    if lock['runtime_image'] != qualified['runtime_image'] or not lock['common_runtime']:
        raise ValueError('Common image identity mismatch')
    destination = run.path / 'model-lock.json'
    if destination.exists() and json.loads(destination.read_text()) != lock:
        raise ValueError('Run model/image identity changed')
    destination.write_text(json.dumps(lock, indent=2) + '\n')
    lock_model(run)
    cache(run, ROOT / 'results/20261013t023201z-features')
    pull_secret(run)
    runtime(run)


def prepare_control(run):
    evidence = ROOT / 'results/20261014-shadow-enabled-check'
    source_logs = list(evidence.glob('shadow-*-True.log'))
    signature = 'Shape/dtype mismatch for lm_head.weight'
    if not any(signature in p.read_text() for p in source_logs):
        raise ValueError('Alternate control requires recorded Nemotron GMS incompatibility evidence')
    common = json.loads((evidence / 'model-lock.json').read_text())
    lock = dict(common)
    lock.update(model='Qwen/Qwen3-0.6B', revision='c1899de289a04d12100db370d81485cdf75e47ca',
                architecture=['Qwen3ForCausalLM'], shadow_control_model=True,
                model_substitution_reason=signature,
                source_failure_run=str(evidence.relative_to(ROOT)))
    path = run.path / 'model-lock.json'
    if path.exists() and json.loads(path.read_text()) != lock:
        raise ValueError('Control identity changed; use a fresh run')
    path.write_text(json.dumps(lock, indent=2) + '\n')
    lock_model(run)
    download(run)
    pull_secret(run)
    runtime(run)
    destination = run.path / 'runtime-sources/gpu_memory_service/integrations/vllm/patches.py'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((evidence / 'runtime-sources/gpu_memory_service/integrations/vllm/patches.py').read_bytes())
    prepare_patch(run)


def claim_smoke(run):
    infra = preflight(run)
    if infra['blockers'] or len(infra['eligible_nodes']) != 3:
        raise ValueError('Require three eligible H100 GPU DRA nodes')
    lock = lock_model(run)
    template = 'shadow-gpu-smoke'
    claim_template = {'apiVersion': 'resource.k8s.io/v1', 'kind': 'ResourceClaimTemplate',
        'metadata': {'name': template}, 'spec': {'spec': {'devices': {'requests': [
            {'name': 'gpu', 'exactly': {'deviceClassName': 'gpu.nvidia.com', 'count': 1}}]}}}}
    run.apply([claim_template])
    reports = []
    program = '''import json,time,torch
assert torch.cuda.device_count()==1
x=torch.arange(4096,device='cuda',dtype=torch.float32)
assert (x+1).sum().item()==8390656.0
torch.cuda.synchronize()
print(json.dumps({'uuid':str(torch.cuda.get_device_properties(0).uuid),'cuda_count':torch.cuda.device_count(),'sum':(x+1).sum().item()}),flush=True)
# Kubernetes may garbage-collect the generated claim as soon as this Pod ends.
# Keep it alive briefly so the host harness can preserve the allocation receipt.
time.sleep(30)
'''
    try:
        for index, node in enumerate(infra['eligible_nodes']):
            name = f'shadow-gpu-smoke-{index}'
            pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name},
                'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
                    'automountServiceAccountToken': False,
                    'nodeSelector': {'kubernetes.io/hostname': node},
                    'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}],
                    'imagePullSecrets': [{'name': lock['image_pull_secret']}],
                    'resourceClaims': [{'name': 'gpu', 'resourceClaimTemplateName': template}],
                    'containers': [{'name': f'cuda-{i}', 'image': lock['runtime_image'],
                        'command': ['python3', '-c', program],
                        'resources': {'claims': [{'name': 'gpu'}],
                                      'requests': {'cpu': '1', 'memory': '2Gi'},
                                      'limits': {'memory': '4Gi'}}} for i in range(2)]}}
            run.apply([pod])
            try:
                running = run.wait_pod(name, timeout=240)
                claim_name = running['status']['resourceClaimStatuses'][0]['resourceClaimName']
                claim = run.get('get', 'resourceclaim', claim_name, '-n', run.ns)
                completed = run.wait_pod(name, completed=True, timeout=240)
                logs = [json.loads(run.k('logs', name, '-n', run.ns, '-c', f'cuda-{i}').stdout)
                        for i in range(2)]
                if logs[0]['uuid'] != logs[1]['uuid']:
                    raise ValueError('Containers received different GPUs')
                (run.path / f'{name}-pod.json').write_text(json.dumps(completed, indent=2) + '\n')
                allocations = claim['status']['allocation']['devices']['results']
                if len(allocations) != 1 or allocations[0]['driver'] != 'gpu.nvidia.com':
                    raise ValueError('Expected one allocated GPU')
                reports.append({'node': node, 'containers': logs, 'claim': claim})
            finally:
                run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=90s', timeout=105)
        run.result('shadow-claim-smoke', 'passed', reports=reports,
                   scope='Both containers share one H100 claim and execute CUDA arithmetic on each of three nodes')
    finally:
        run.k('delete', 'resourceclaimtemplate', template, '-n', run.ns, '--ignore-not-found', check=False)


def inspect(run):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    now = time.time_ns()
    (run.path / f'shadow-pods-{now}.json').write_text(json.dumps(pods, indent=2) + '\n')
    for pod in pods:
        for container in pod['spec'].get('initContainers', []) + pod['spec']['containers']:
            for previous in (False, True):
                log = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', container['name'],
                            '--tail=500', *(['--previous'] if previous else []), check=False)
                (run.path / f'shadow-{pod["metadata"]["name"]}-{container["name"]}-{now}-{previous}.log').write_text(log.stdout + log.stderr)
    for kind in ('events', 'resourceclaims', 'dynamoworkermetadatas', 'dynamographdeployments'):
        value = run.get('get', kind, '-n', run.ns)
        (run.path / f'shadow-{kind}-{now}.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps([{'name': p['metadata']['name'], 'phase': p.get('status', {}).get('phase'),
                       'containers': [{'name': c['name'], 'ready': c.get('ready'),
                                       'restarts': c.get('restartCount'), 'state': c.get('state')}
                                      for c in p.get('status', {}).get('containerStatuses', [])
                                      + p.get('status', {}).get('initContainerStatuses', [])]}
                      for p in pods], indent=2))


def sources(run):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    pod = next(p for p in pods if p['metadata']['name'].startswith('ft-shadow-')
               and '-frontend-' in p['metadata']['name'])
    if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Frontend is not owned')
    program = '''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
paths=['gpu_memory_service/integrations/vllm/patches.py','gpu_memory_service/integrations/vllm/worker.py',
       'gpu_memory_service/integrations/vllm/model_loader.py','vllm/v1/worker/gpu_worker.py',
       'vllm/v1/worker/utils.py']
print(json.dumps({p:(root/p).read_text() if (root/p).is_file() else None for p in paths}))
'''
    result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'python3', '-c', program)
    output = run.path / 'runtime-sources'
    output.mkdir(exist_ok=True)
    for path, value in json.loads(result.stdout).items():
        if value is not None:
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)


def prepare_patch(run):
    source = run.path / 'runtime-sources/gpu_memory_service/integrations/vllm/patches.py'
    before = source.read_text()
    signature = '    def patched_request_memory(init_snapshot, cache_config):'
    if before.count(signature) != 1:
        raise ValueError('Unexpected GMS request_memory source')
    after = before.replace(signature,
        '    def patched_request_memory(init_snapshot, cache_config, external_weight_memory=0):')
    anchor = '        logger.info(\n            "[GMS Patch] Shadow mode: bypassing memory check "'
    if after.count(anchor) != 1:
        raise ValueError('Unexpected GMS memory budget source')
    after = after.replace(anchor,
        '        requested_memory -= external_weight_memory\n'
        '        if requested_memory <= 0:\n'
        '            raise ValueError("External weights exceed the engine memory budget")\n' + anchor)
    compile(after, 'patches.py', 'exec')
    destination = ROOT / 'configs/patches/shadow-gms-vllm031/patches.py'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(after)
    checksum = hashlib.sha256(after.encode()).hexdigest()
    name = 'shadow-gms-compat-' + checksum[:12]
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name},
                'immutable': True, 'data': {'patches.py': after}}])
    run.state['shadow_compat_patch'] = {'configmap': name, 'sha256': checksum,
        'original_sha256': hashlib.sha256(before.encode()).hexdigest(),
        'path': str(destination.relative_to(ROOT))}
    run.save()
    run.result('shadow-compat-patch', 'prepared', **run.state['shadow_compat_patch'],
               scope='Test-local read-only module overlay for the vLLM 0.31 request_memory signature')


class ShadowStartupFatal(RuntimeError):
    pass


def wait_standby(run, timeout):
    deadline = time.monotonic() + timeout
    inspected_restarts = set()
    probe = '''import json,os,urllib.request
with urllib.request.urlopen('http://127.0.0.1:'+os.environ['DYN_SYSTEM_PORT']+'/metrics',timeout=3) as r:
 print(json.dumps({'engine_id':os.environ['ENGINE_ID'],'metrics':r.read().decode()}))
'''
    while time.monotonic() < deadline:
        try:
            pod = owned_pod(run)
            for container in pod['status'].get('containerStatuses', []):
                if container['name'] not in ('engine-0', 'engine-1') or not container.get('restartCount'):
                    continue
                identity = (pod['metadata']['uid'], container['name'], container['restartCount'])
                if identity in inspected_restarts:
                    continue
                logs = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', container['name'],
                             '--previous', '--tail=600', check=False)
                if logs.returncode != 0:
                    continue
                inspected_restarts.add(identity)
                signatures = [p for p in ('an illegal memory access was encountered', 'Shape/dtype mismatch for')
                              if p in logs.stdout]
                if signatures:
                    evidence = f'shadow-startup-fatal-{container["name"]}-{time.time_ns()}.log'
                    (run.path / evidence).write_text(logs.stdout + logs.stderr)
                    run.result('shadow-startup', 'blocked', container=container['name'],
                               signatures=signatures, evidence=evidence, fault_injected=False)
                    raise ShadowStartupFatal(f'Permanent Shadow startup failure: {signatures}; see {evidence}')
            states = {}
            for name in ('engine-0', 'engine-1'):
                response = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', name,
                                 '--', 'python3', '-c', probe, timeout=15)
                report = json.loads(response.stdout)
                states[name] = next(s for s in ('init', 'standby', 'waking', 'active')
                    if counter(report['metrics'], 'state', state=s, engine_id=report['engine_id']) == 1)
            print(json.dumps({'states': states, 'pod': pod['metadata']['name']}), flush=True)
            if sorted(states.values()) == ['active', 'standby']:
                run.result('shadow-active-standby', 'present', states=states,
                           pod_uid=pod['metadata']['uid'],
                           scope='Runtime metrics only; inference and recovery still require verify')
                return
        except ShadowStartupFatal:
            raise
        except (RuntimeError, KeyError, StopIteration, ValueError) as exc:
            print(f'Startup pending: {str(exc)[-180:]}', flush=True)
        time.sleep(10)
    inspect(run)
    raise TimeoutError('No active and parked standby within the bounded startup wait')


def record_blocker(run):
    logs = '\n'.join(p.read_text() for p in run.path.glob('shadow-*.log'))
    signals = [s for s in (
        'patched_request_memory() takes 2 positional arguments but 3 were given',
        'Shape/dtype mismatch for lm_head.weight',
        'an illegal memory access was encountered') if s in logs]
    if not signals or (run.path / 'shadow-fault.json').exists():
        raise ValueError('Requires preserved startup failure evidence and no injected fault')
    run.result('shadow-failover', 'blocked', model=lock_model(run)['model'],
               blockers=signals, fault_injected=False,
               runtime_image=lock_model(run)['runtime_image'],
               compatibility_overlay=run.state.get('shadow_compat_patch'),
               scope='Startup failed before active/parked standby; no inference/recovery qualification')


def finish_cleanup(run):
    cleanup(run)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        pods = [p for p in run.get('get', 'pods', '-n', run.ns)['items']
                if p['metadata']['name'].startswith('ft-shadow-')]
        claims = [c for c in run.get('get', 'resourceclaims', '-n', run.ns)['items']
                  if c['metadata']['name'].startswith('ft-shadow-')]
        if not pods and not claims:
            run.result('shadow-final-cleanup', 'passed', remaining_pods=0, remaining_claims=0,
                       scope='Owned Shadow Pods terminated and their GPU claims garbage-collected; cache retained')
            return
        print(json.dumps({'terminating_pods': [p['metadata']['name'] for p in pods],
                          'remaining_claims': [c['metadata']['name'] for c in claims]}), flush=True)
        time.sleep(5)
    raise TimeoutError('Owned test Pods/claims did not finish normal cleanup within 300s')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'prepare-control', 'claim-smoke', 'inspect', 'observe', 'sources', 'prepare-patch', 'wait', 'record-blocker', 'cleanup'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'prepare':
        prepare(run)
    elif args.action == 'prepare-control':
        prepare_control(run)
    elif args.action == 'claim-smoke':
        claim_smoke(run)
    elif args.action == 'inspect':
        inspect(run)
    elif args.action == 'sources':
        sources(run)
    elif args.action == 'prepare-patch':
        prepare_patch(run)
    elif args.action == 'wait':
        if not 30 <= args.timeout <= 1200:
            parser.error('--timeout must be 30..1200 seconds')
        wait_standby(run, args.timeout)
    elif args.action == 'record-blocker':
        record_blocker(run)
    elif args.action == 'cleanup':
        finish_cleanup(run)
    else:
        print(json.dumps(snapshot(run)['states'], indent=2))


if __name__ == '__main__':
    main()
