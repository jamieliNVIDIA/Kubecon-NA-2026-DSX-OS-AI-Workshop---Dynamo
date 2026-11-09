#!/usr/bin/env python3
"""Save bounded Snapshot API, controller, agent and owned-workload evidence."""
import argparse
import json
from pathlib import Path
import time
import uuid
from testlib import Run


def collect_resources(run):
    """Observe current owned Pod cgroups while a capture/restore is in progress."""
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    agents = [p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
              if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')]
    for agent in agents:
        stamp = time.time_ns()
        node = agent['spec'].get('nodeName')
        pod_ids = [str(uuid.UUID(p['metadata']['uid'])).replace('-', '_')
                   for p in pods + [agent] if p['spec'].get('nodeName') == node]
        result = run.k('exec', '-n', 'dynamo-system', agent['metadata']['name'], '-c', 'agent',
                       '--', 'sh', '-c', 'for uid in "$@"; do '
                       'find /sys/fs/cgroup/kubepods.slice -maxdepth 4 -type d -name "*pod${uid}.slice" '
                       '| while IFS= read -r path; do echo "$path"; '
                       'for metric in memory.current memory.peak memory.events cpu.stat; do '
                       'echo "$metric"; cat "$path/$metric"; done; done; done',
                       'observe-owned-cgroups', *pod_ids, timeout=30, check=False)
        (run.path / f'snapshot-cgroup-resources-{stamp}.log').write_text(result.stdout + result.stderr)


def collect(run):
    observed = {}
    stamp = time.time_ns()
    for resource in ('dgd', 'dynamocomponentdeployments', 'deployments', 'replicasets',
                     'snapshotjobs', 'jobs', 'podsnapshots', 'podsnapshotcontents', 'events', 'pods'):
        scope = [] if resource == 'podsnapshotcontents' else ['-n', run.ns]
        result = run.k('get', resource, *scope, '-o', 'json', check=False)
        observed[resource] = json.loads(result.stdout) if result.returncode == 0 else {'error': result.stderr}
    system = run.get('get', 'pods', '-A')['items']
    infrastructure = [p for p in system if p['metadata']['name'].startswith(
        ('dynamo-platform-snapshot-', 'dynamo-platform-dynamo-operator-'))]
    observed['infrastructure'] = infrastructure
    observed['system_events'] = run.get('get', 'events', '-n', 'dynamo-system')
    observed['controller_deployments'] = [o for o in run.get('get', 'deployments', '-A')['items']
        if o['metadata']['name'].startswith(('dynamo-platform-snapshot-', 'dynamo-platform-dynamo-operator-'))]
    observed['default_events'] = run.get('get', 'events', '-n', 'default')
    for namespace in (run.ns, 'dynamo-system'):
        metrics = run.k('top', 'pod', '-n', namespace, '--containers', check=False)
        (run.path / f'snapshot-resources-{namespace}-{stamp}.log').write_text(metrics.stdout + metrics.stderr)
    for pod in infrastructure:
        if '-snapshot-agent-' not in pod['metadata']['name']:
            continue
        # Read-only, bounded inspection of the dedicated artifact export and
        # checkpoint processes. Do not scan the general model-cache filesystem.
        result = run.k('exec', '-n', pod['metadata']['namespace'], pod['metadata']['name'],
                       '-c', 'agent', '--', 'sh', '-c',
                       "ps -eo pid,ppid,stat,etime,wchan:32,comm | "
                       "awk 'NR == 1 || /snapshot|nsenter|nsrestore|criu|runc|containerd|vllm|python|agent|cuda|tar/' | head -180; "
                       "find /checkpoints -maxdepth 8 -type f -printf '%s %p\\n' | sort -nr | head -30; "
                       "find /checkpoints -maxdepth 8 -type f -printf '%s\\n' | "
                       "awk '{bytes += $1; count++} END {print \"artifact_files\",count,\"logical_bytes\",bytes}'; "
                       "find /checkpoints -maxdepth 8 -name dump.log -exec tail -70 {} \\;; "
                       "for pid in $(pgrep -x criu); do cat /proc/$pid/io; done; "
                       "df -h /checkpoints", timeout=45, check=False)
        (run.path / f'snapshot-agent-inspection-{stamp}.log').write_text(result.stdout + result.stderr)
        pod_ids = [str(uuid.UUID(p['metadata']['uid'])).replace('-', '_')
                   for p in observed.get('pods', {}).get('items', []) + [pod]]
        resources = run.k('exec', '-n', pod['metadata']['namespace'], pod['metadata']['name'],
                         '-c', 'agent', '--', 'sh', '-c',
                         'for uid in "$@"; do '
                         'find /sys/fs/cgroup/kubepods.slice -maxdepth 4 -type d -name "*pod${uid}.slice" '
                         '| while IFS= read -r path; do echo "$path"; '
                         'for metric in memory.current memory.peak memory.events cpu.stat; do '
                         'echo "$metric"; cat "$path/$metric"; done; done; '
                         'for pid in $(pgrep -x criu); do '
                         'case "$(cat /proc/$pid/cgroup)" in *pod${uid}*) '
                         'echo "Owned CRIU restore log pid=$pid"; '
                         'tail -70 /proc/$pid/root/var/criu-work/restore.log;; esac; done; done',
                         'inspect-owned-cgroups', *pod_ids, timeout=45, check=False)
        (run.path / f'snapshot-cgroup-resources-{stamp}.log').write_text(resources.stdout + resources.stderr)
    for obj in observed.get('pods', {}).get('items', []) + infrastructure:
        namespace, name = obj['metadata']['namespace'], obj['metadata']['name']
        for container in obj['spec'].get('containers', []) + obj['spec'].get('initContainers', []):
            for previous in (False, True):
                result = run.k('logs', name, '-n', namespace, '-c', container['name'], '--tail=1200', '--timestamps',
                               *(['--previous'] if previous else []), check=False)
                filename = f'snapshot-{namespace}-{name}-{container["name"]}-{stamp}-{"previous" if previous else "current"}.log'
                (run.path / filename).write_text(result.stdout + result.stderr)
    (run.path / f'snapshot-diagnostics-{stamp}.json').write_text(json.dumps(observed, indent=2) + '\n')
    (run.path / 'snapshot-diagnostics-latest.json').write_text(json.dumps(observed, indent=2) + '\n')
    summary = {key: [{'name': i['metadata']['name'],
                     'conditions': [(c['type'], c['status'], c.get('reason'), c.get('message'))
                                    for c in i.get('status', {}).get('conditions', [])]}
                    for i in observed.get(key, {}).get('items', [])]
               for key in ('dgd', 'snapshotjobs', 'podsnapshots')}
    summary['pods'] = [{'namespace': p['metadata']['namespace'], 'name': p['metadata']['name'],
        'node': p['spec'].get('nodeName'), 'phase': p.get('status', {}).get('phase'),
        'containers': [{'name': c['name'], 'ready': c.get('ready'), 'restarts': c.get('restartCount'),
                        'state': c.get('state')}
                       for c in p.get('status', {}).get('containerStatuses', []) + p.get('status', {}).get('initContainerStatuses', [])]}
        for p in observed.get('pods', {}).get('items', []) + infrastructure]
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    collect(Run(args.run))


if __name__ == '__main__':
    main()
