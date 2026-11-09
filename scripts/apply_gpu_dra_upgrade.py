#!/usr/bin/env python3
"""Check or apply the reviewed GPU allocator transition; never stops workloads."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from prepare_gpu_dra_upgrade import TARGET, upgrade_command, verify_bundle
from testlib import ROOT, Run


def gpu_resources(value):
    """Find GPU scalar requirements in nested workload Pod templates."""
    if isinstance(value, dict):
        if any((k == 'nvidia.com/gpu' or k.startswith('nvidia.com/mig-'))
               and str(v) not in ('0', '0.0') for k, v in value.items()):
            return True
        return any(gpu_resources(v) for v in value.values())
    if isinstance(value, list):
        return any(gpu_resources(v) for v in value)
    return False


def workload_blockers(snapshot):
    blockers = []
    for resource, objects in snapshot.items():
        for obj in objects['items']:
            meta = obj['metadata']
            identity = f'{resource}/{meta.get("namespace", "")}/{meta["name"]}'
            if resource == 'pods' and obj.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
                continue
            if resource in ('resourceclaims', 'dynamographdeployments', 'computedomain'):
                blockers.append(identity)
            elif gpu_resources(obj.get('spec', {})):
                blockers.append(identity)
    return blockers


def snapshot_workloads(run):
    return {resource: run.get('get', resource, '-A') for resource in
            ('pods', 'deployments', 'daemonsets', 'statefulsets', 'jobs', 'cronjobs',
             'replicasets', 'dynamographdeployments', 'resourceclaims', 'computedomain')}


def active_device_plugins(run):
    pods = run.get('get', 'pods', '-A')['items']
    return [p['metadata']['name'] for p in pods
            if 'nvidia-device-plugin' in p['metadata']['name']
            and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]


def poll(check, description, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(5)
    raise RuntimeError(f'Timed out waiting for {description}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--apply', action='store_true',
                        help='Apply only after approval of the cluster-wide change')
    args = parser.parse_args()
    lock = json.loads((TARGET / 'gpu-dra-upgrade-lock.json').read_text())
    verify_bundle(lock)
    run = Run(args.run)
    run.command([str(ROOT / 'scripts/kubecon-tunnel.sh'), 'start'])
    helm = ['helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    installed = json.loads(run.command(helm + ['list', '-A', '-o', 'json']).stdout)
    for name, spec in lock['releases'].items():
        release = next(r for r in installed if r['name'] == spec['release']
                       and r['namespace'] == spec['namespace'])
        if (str(release['revision']) != str(spec['before_revision']) or
                release['chart'] != spec['chart'] or release['status'] != 'deployed'):
            raise ValueError(f'{name} release changed since review; prepare a fresh bundle')
        values = json.loads(run.command(helm + ['get', 'values', spec['release'],
            '-n', spec['namespace'], '--all', '-o', 'json']).stdout)
        current_hash = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        if current_hash != spec['baseline_values_sha256']:
            raise ValueError(f'{name} values changed since review')
        chart, target = ROOT / spec['chart_path'], ROOT / spec['values_path']
        run.command(upgrade_command(helm, name, chart, target) +
                    ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
    nodes = run.get('get', 'nodes')['items']
    expected_nodes = {n['metadata']['name'] for n in nodes}
    baseline_nodes = json.loads((ROOT / lock['review_run'] / 'before-nodes.json').read_text())['items']
    if expected_nodes != {n['metadata']['name'] for n in baseline_nodes}:
        raise ValueError('Workshop node identities changed since review')
    if len(nodes) != 3 or not all('H100' in n['metadata'].get('labels', {}).get('nvidia.com/gpu.product', '')
                                and any(c['type'] == 'Ready' and c['status'] == 'True'
                                        for c in n['status']['conditions']) for n in nodes):
        raise ValueError('Expected the three Ready H100 workshop nodes')
    workloads = snapshot_workloads(run)
    (run.path / 'before-workloads.json').write_text(json.dumps(workloads, indent=2) + '\n')
    blockers = workload_blockers(workloads)
    run.result('gpu-dra-upgrade-readiness', 'blocked' if blockers else 'passed',
               blockers=blockers, applied=False)
    if blockers:
        raise ValueError('Stop GPU workloads/controllers and remove their claims first: ' + ', '.join(blockers))
    if not args.apply:
        print('Checks passed; no cluster changes. --apply executes the reviewed transition after approval.')
        return
    # No automatic rollback across releases: DRA must be stopped before the old
    # allocator can return. Failure leaves diagnostics and does not enable both.
    try:
        for name in ('gpu-operator', 'gpu-dra'):
            spec = lock['releases'][name]
            if name == 'gpu-dra':
                if active_device_plugins(run):
                    raise ValueError('Competing GPU device plugin is still running')
                fresh_blockers = workload_blockers(snapshot_workloads(run))
                if fresh_blockers:
                    raise ValueError(f'GPU workload appeared during transition: {fresh_blockers}')
            command = upgrade_command(helm, name, ROOT / spec['chart_path'], ROOT / spec['values_path'])
            applied = run.command(command + ['-o', 'json'], timeout=660)
            (run.path / f'applied-{name}.json').write_text(applied.stdout)
            if name == 'gpu-operator':
                poll(lambda: not active_device_plugins(run), 'all GPU device-plugin Pods to stop')
                policy = run.get('get', 'clusterpolicies')['items']
                if len(policy) != 1 or policy[0]['spec']['devicePlugin']['enabled']:
                    raise ValueError('ClusterPolicy did not disable the GPU device plugin')
        def ready_inventory():
            slices = run.get('get', 'resourceslices')['items']
            devices = {}
            for s in slices:
                if s['spec']['driver'] == 'gpu.nvidia.com':
                    devices.setdefault(s['spec'].get('nodeName'), set()).update(
                        d['name'] for d in s['spec'].get('devices', []))
            plugins = run.get('get', 'pods', '-n', 'nvidia-dra-driver')['items']
            ready_nodes = {p['spec'].get('nodeName') for p in plugins
                           if any(c['name'] == 'gpus' and c.get('ready')
                                  for c in p.get('status', {}).get('containerStatuses', []))}
            return (set(devices) == expected_nodes and all(len(d) == 8 for d in devices.values())
                    and expected_nodes <= ready_nodes and not active_device_plugins(run))
        poll(ready_inventory, 'three Ready GPU DRA plugins advertising eight devices each', timeout=300)
        run.get('get', 'deviceclass', 'gpu.nvidia.com')
        run.result('gpu-dra-upgrade', 'passed', applied=True,
                   scope='Allocator rollout/inventory only; CUDA, shared-claim and feature retests still required')
    except Exception as exc:
        run.result('gpu-dra-upgrade', 'blocked', error=str(exc), applied='possibly-partial',
                   note='No automatic rollback; inspect saved receipts before restoring either allocator')
        raise


if __name__ == '__main__':
    main()
