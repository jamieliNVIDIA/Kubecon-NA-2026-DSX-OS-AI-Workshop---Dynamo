#!/usr/bin/env python3
"""Test existing Grove/KAI gang admission and reversible grouped GPU scaling."""
import argparse
import json
from pathlib import Path
import time
import yaml
from testlib import ROOT, Run


def snapshot(run, phase):
    result = {}
    for resource in ('podcliquesets', 'podcliques', 'podcliquescalinggroups', 'podgangs.scheduler.grove.io', 'pods'):
        result[resource] = run.get('get', resource, '-n', run.ns)
    (run.path / f'grove-{phase}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def wait(run, expected, timeout=300):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        pods = [p for p in run.get('get', 'pods', '-n', run.ns)['items']
                if p['metadata']['name'].startswith('ft-grove-') and not p['metadata'].get('deletionTimestamp')]
        ready = [p for p in pods if any(c['type'] == 'Ready' and c['status'] == 'True'
                                       for c in p.get('status', {}).get('conditions', []))]
        state = (len(pods), len(ready))
        if state != last:
            print(f'Grove pods: {state[1]}/{state[0]} Ready; expect {expected}', flush=True)
            last = state
        if len(pods) == len(ready) == expected:
            if any(p['spec']['schedulerName'] != 'kai-scheduler' for p in pods):
                raise ValueError('Workload did not use KAI Scheduler')
            if run.state.get('model_lock', {}).get('common_runtime'):
                complete = True
                for pod in pods:
                    name = pod['metadata']['name']
                    resources = pod['spec']['containers'][0]['resources']
                    gpu = resources.get('limits', {}).get('nvidia.com/gpu') or resources.get('claims')
                    marker = 'GROVE_GPU_READY' if gpu else 'GROVE_READY'
                    logs = run.k('logs', name, '-n', run.ns, '-c', 'test').stdout
                    (run.path / f'grove-startup-{name}.log').write_text(logs)
                    if marker not in logs:
                        complete = False
                if not complete:
                    time.sleep(5)
                    continue
            return pods
        time.sleep(5)
    snapshot(run, 'timeout')
    raise TimeoutError(f'Grove did not admit {expected} Ready pods in {timeout}s')


def test(run):
    run.ensure_namespace()
    from serving_tests import lock_model
    lock = lock_model(run)
    graph = yaml.safe_load((ROOT / 'configs/upstream/grove-simple1.yaml').read_text())
    graph['metadata'] = {'name': 'ft-grove', 'namespace': run.ns,
                         'labels': {'kai.scheduler/queue': 'dynamo', **run.labels()}}
    for clique in graph['spec']['template']['cliques']:
        clique['labels'] = {'kai.scheduler/queue': 'dynamo', **run.labels()}
        spec = clique['spec']
        spec['replicas'] = 1
        spec['minAvailable'] = 1
        spec.pop('autoScalingConfig', None)
        spec['podSpec'] = {'schedulerName': 'kai-scheduler', 'automountServiceAccountToken': False,
            'activeDeadlineSeconds': 900,
            'containers': [{'name': 'test', 'image': 'python:3.12-slim-bookworm',
                'command': ['python3', '-u', '-c', 'import time; print("GROVE_READY", flush=True); time.sleep(850)'],
                'resources': {'requests': {'cpu': '100m', 'memory': '64Mi'}, 'limits': {'memory': '256Mi'}}}]}
        if clique['name'] in {'pcb', 'pcc'}:
            for resources in spec['podSpec']['containers'][0]['resources'].values():
                resources['nvidia.com/gpu'] = str(lock.get('tensor_parallel_size', 1))
        if lock.get('common_runtime'):
            pod = spec['podSpec']
            pod['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
            container = pod['containers'][0]
            container['image'] = lock['runtime_image']
            if clique['name'] in {'pcb', 'pcc'}:
                container['resources']['requests']['memory'] = '4Gi'
                container['resources']['limits']['memory'] = '8Gi'
                tp = lock.get('tensor_parallel_size', 1)
                container['command'] = ['python3', '-u', '-c',
                    'import torch,time; assert torch.cuda.is_available(); '
                    f'assert torch.cuda.device_count()=={tp}; '
                    f'assert all(torch.arange(1024,device=f"cuda:{{i}}").sum().item()==523776 for i in range({tp})); '
                    'print("GROVE_GPU_READY",flush=True); time.sleep(850)']
            else:
                container['env'] = [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}]
    for group in graph['spec']['template']['podCliqueScalingGroups']:
        group.pop('scaleConfig', None)
    run.write_manifest(run.path / 'grove-manifest.yaml', [graph])
    run.apply([graph])
    try:
        initial = wait(run, 4)
        before = snapshot(run, 'initial')
        gangs = before['podgangs.scheduler.grove.io']['items']
        assert gangs, 'Grove did not create PodGang resources'
        groups = before['podcliquescalinggroups']['items']
        assert len(groups) == 1
        group_name = groups[0]['metadata']['name']
        run.k('scale', 'podcliquescalinggroup', group_name, '-n', run.ns, '--replicas=2')
        scaled = wait(run, 6)
        snapshot(run, 'scaled')
        run.k('scale', 'podcliquescalinggroup', group_name, '-n', run.ns, '--replicas=1')
        wait(run, 4)
        snapshot(run, 'restored')
        run.result('grove-kai', 'passed', initial_pods=len(initial), scaled_pods=len(scaled),
                   initial_gpu_count=2 * lock.get('tensor_parallel_size', 1),
                   scaled_gpu_count=4 * lock.get('tensor_parallel_size', 1), scheduler='kai-scheduler',
                   gpu_arithmetic_validated=bool(lock.get('common_runtime')),
                   scope='PodGang creation, GPU resource admission and coordinated scaling; not quota reclaim or topology qualification')
    finally:
        run.k('delete', 'podcliqueset', 'ft-grove', '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    run = Run(args.run)
    print(f'Run: {run.path}; namespace: {run.ns}', flush=True)
    try:
        test(run)
    except Exception as exc:
        run.result('grove-kai', 'blocked', error=str(exc))
        raise


if __name__ == '__main__':
    main()
