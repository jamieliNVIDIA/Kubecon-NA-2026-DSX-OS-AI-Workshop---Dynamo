#!/usr/bin/env python3
"""Summarize saved cgroup high-water observations; no cluster access."""
import argparse
import json
from pathlib import Path
import re
from testlib import Run


def summarize(run):
    restore = json.loads((run.path / 'snapshot-restored-pod.json').read_text())
    diagnostic = json.loads((run.path / 'snapshot-diagnostics-latest.json').read_text())
    content = next(c for c in diagnostic['podsnapshotcontents']['items']
                   if c['metadata']['name'] == json.loads((run.path / 'snapshot-artifact.json').read_text())
                   ['status']['boundSnapshotContentName'])
    agent = next(p for p in diagnostic['infrastructure'] if '-snapshot-agent-' in p['metadata']['name']
                 and p['spec'].get('nodeName') == restore['spec']['nodeName'])
    roles = {'capture_worker': content['spec']['source']['podRef']['uid'],
             'restored_worker': restore['metadata']['uid'], 'agent': agent['metadata']['uid']}
    summary = {}
    for role, uid in roles.items():
        observations = []
        for path in sorted(run.path.glob('snapshot-cgroup-resources-*.log')):
            for block in path.read_text().split('/sys/fs/cgroup/'):
                if f'pod{uid.replace("-", "_")}.slice\n' not in block:
                    continue
                peak = re.search(r'\nmemory.peak\n(\d+)\n', block)
                if peak:
                    observations.append({'file': path.name, 'memory_peak_bytes': int(peak[1]),
                                         'oom': int(re.search(r'\noom (\d+)\n', block)[1]),
                                         'oom_kill': int(re.search(r'\noom_kill (\d+)\n', block)[1])})
        if not observations:
            raise RuntimeError(f'No saved cgroup observations for {role}')
        summary[role] = {'pod_uid': uid, 'max_observed_memory_peak_bytes': max(o['memory_peak_bytes'] for o in observations),
                         'max_observed_oom': max(o['oom'] for o in observations),
                         'max_observed_oom_kill': max(o['oom_kill'] for o in observations),
                         'observations': observations}
    (run.path / 'snapshot-resource-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: {field: value for field, value in v.items() if field != 'observations'}
                      for k, v in summary.items()}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    summarize(Run(parser.parse_args().run))
