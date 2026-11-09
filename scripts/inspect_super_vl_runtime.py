#!/usr/bin/env python3
"""Collect bounded owned-worker logs, health and allocation details for TP2 blockers."""
import argparse
import json
from pathlib import Path
import time
from testlib import OWNER, Run


def collect(run, prefix):
    if not prefix.startswith('ft-') and prefix not in ('snapshot-runtime-probe', 'checkpoint-'):
        raise ValueError('Only owned feature graph prefixes may be inspected')
    namespace = run.get('get', 'namespace', run.ns)
    if namespace['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER:
        raise ValueError('Namespace is not owned')
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    reports = []
    for pod in pods:
        name = pod['metadata']['name']
        if not name.startswith(prefix):
            continue
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            graph = pod['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name')
            checkpoint_owner_uid = None
            if not graph and prefix == 'checkpoint-':
                owner = next(o for o in pod['metadata'].get('ownerReferences', []) if o['kind'] == 'Job')
                job = run.get('get', 'job', owner['name'], '-n', run.ns)
                if job['metadata']['uid'] != owner['uid']:
                    raise ValueError('Capture Job UID mismatch')
                owner = next(o for o in job['metadata'].get('ownerReferences', []) if o['kind'] == 'SnapshotJob')
                checkpoint = run.get('get', 'snapshotjob', owner['name'], '-n', run.ns)
                if checkpoint['metadata']['uid'] != owner['uid']:
                    raise ValueError('SnapshotJob UID mismatch')
                graph = checkpoint['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name')
                checkpoint_owner_uid = checkpoint['metadata'].get('annotations', {}).get('nvidia.com/dynamo-checkpoint-owner-uid')
                if not checkpoint_owner_uid:
                    raise ValueError('Capture has no DGD owner UID')
            if not graph:
                raise ValueError('Pod has no owned graph identity')
            parent = run.get('get', 'dgd', graph, '-n', run.ns)
            if parent['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                raise ValueError('Pod graph is not owned by this test run')
            if checkpoint_owner_uid and parent['metadata']['uid'] != checkpoint_owner_uid:
                raise ValueError('Capture DGD UID mismatch')
        output = run.path / 'diagnostics' / name
        output.mkdir(parents=True, exist_ok=True)
        (output / 'pod.json').write_text(json.dumps(pod, indent=2) + '\n')
        for container in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
            for previous in (False, True):
                result = run.k('logs', name, '-n', run.ns, '-c', container['name'], '--tail=500',
                               *(['--previous'] if previous else []), check=False)
                suffix = 'previous' if previous else 'current'
                content = result.stdout + result.stderr
                (output / f'{container["name"]}-{suffix}-{time.time_ns()}.log').write_text(content)
                if result.returncode == 0 and not result.stdout.startswith('unable to retrieve'):
                    (output / f'{container["name"]}-{suffix}.log').write_text(content)
            if container.get('resources', {}).get('claims'):
                commands = {'processes': ['ps', '-eo', 'pid,ppid,stat,etime,pcpu,rss,args'],
                            'gpu': ['nvidia-smi', '--query-gpu=uuid,memory.used,utilization.gpu', '--format=csv,noheader']}
                for label, command in commands.items():
                    result = run.k('exec', name, '-n', run.ns, '-c', container['name'], '--', *command, check=False)
                    (output / f'{container["name"]}-{label}.txt').write_text(result.stdout + result.stderr)
        reports.append({'name': name, 'phase': pod.get('status', {}).get('phase'),
                        'node': pod['spec'].get('nodeName'),
                        'containers': pod.get('status', {}).get('containerStatuses', [])})
    events = run.get('get', 'events', '-n', run.ns)
    (run.path / 'diagnostics/events.json').parent.mkdir(exist_ok=True)
    (run.path / 'diagnostics/events.json').write_text(json.dumps(events, indent=2) + '\n')
    print(json.dumps(reports, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    collect(Run(args.run), args.prefix)
