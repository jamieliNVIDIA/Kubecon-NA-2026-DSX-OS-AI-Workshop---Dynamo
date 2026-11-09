#!/usr/bin/env python3
"""Probe CUDA job-file creation without model loading, GPU allocation or driver changes."""
import argparse
import json
import time
from pathlib import Path
from testlib import Run


def probe(run, refresh_agent=False):
    agents = [p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
              if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
              and p['spec'].get('nodeName') == 'kubecon-nke-site-cp-0124']
    if len(agents) != 1:
        raise ValueError('Expected the installed Snapshot agent on cp-0124')
    agent = agents[0]
    if refresh_agent:
        # Existing runtime-injected binary/library bind mounts keep old driver
        # inodes after a module upgrade. Recreate only the idle agent Pod.
        if run.get('get', 'dynamographdeployments', '-A')['items']:
            raise ValueError('Stop model DGDs before refreshing the Snapshot agent')
        active = [p for p in run.get('get', 'pods', '-A')['items']
                  if 'nvidia.com/snapshot-job' in p['metadata'].get('labels', {})
                  and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
        if active:
            raise ValueError('An active Snapshot capture Pod prevents agent refresh')
        owners = agent['metadata'].get('ownerReferences', [])
        if not any(o['kind'] == 'DaemonSet' and o['name'] == 'dynamo-platform-snapshot-agent' for o in owners):
            raise ValueError('Unexpected agent owner')
        (run.path / f'snapshot-agent-before-refresh-{time.time_ns()}.json').write_text(json.dumps(agent, indent=2))
        run.k('delete', 'pod', agent['metadata']['name'], '-n', 'dynamo-system', '--wait=true', '--timeout=90s', timeout=105)
        run.k('rollout', 'status', 'daemonset/dynamo-platform-snapshot-agent', '-n', 'dynamo-system', '--timeout=180s', timeout=195)
        return probe(run)
    commands = {
        'driver': ['cat', '/proc/driver/nvidia/version'],
        'help': ['/usr/local/sbin/cuda-checkpoint', '--help'],
        'launch': ['/usr/local/sbin/cuda-checkpoint', '--launch-job', '/bin/sh', '-c',
            'if [ -n "${CUDA_CHECKPOINT_JOB_FILE:-}" ] && [ -s "$CUDA_CHECKPOINT_JOB_FILE" ]; '
            'then printf "CUDA_JOB_FILE_PRESENT\\n"; '
            'else printf "CUDA_JOB_FILE_MISSING\\n"; exit 42; fi'],
    }
    report = {'node': agent['spec']['nodeName'], 'agent_uid': agent['metadata']['uid'],
              'agent_images': [c['imageID'] for c in agent['status']['containerStatuses']],
              'scope': 'Existing-agent child-process launch only; no model, GPU allocation, capture or restore'}
    for name, command in commands.items():
        result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent',
                       '--', *command, timeout=45, check=False)
        report[name] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    report['job_file_created'] = (report['launch']['exit_code'] == 0 and
                                  'CUDA_JOB_FILE_PRESENT' in report['launch']['stdout'])
    content = json.dumps(report, indent=2) + '\n'
    (run.path / f'snapshot-launch-probe-{time.time_ns()}.json').write_text(content)
    (run.path / 'snapshot-launch-probe.json').write_text(content)
    run.result('snapshot-launch-job', 'passed' if report['job_file_created'] else 'blocked', **report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--refresh-agent', action='store_true', help='Recreate the idle agent to refresh driver bind mounts')
    args = parser.parse_args()
    probe(Run(args.run), refresh_agent=args.refresh_agent)
