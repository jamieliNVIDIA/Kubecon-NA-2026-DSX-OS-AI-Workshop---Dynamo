#!/usr/bin/env python3
"""Read-only artifact bytes and phase timings for this run's Snapshot content."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
import uuid
from snapshot_tests import COMPONENT, GRAPH
from testlib import Run


def measure(run, snapshot_name=None, source_uid=None):
    if snapshot_name is None:
        graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
        if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('DGD is not owned')
        name = graph['status']['checkpoints'][COMPONENT]['checkpointName']
    else:
        if not source_uid:
            raise ValueError('Direct Snapshot measurement needs the recorded owned source UID')
        name = snapshot_name
    snapshot = run.get('get', 'podsnapshot', name, '-n', run.ns)
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    reference = content['spec']['snapshotRef']
    if reference['namespace'] != run.ns or reference['uid'] != snapshot['metadata']['uid']:
        raise ValueError('Snapshot content identity mismatch')
    if source_uid and content['spec']['source']['podRef']['uid'] != source_uid:
        raise ValueError('Snapshot source UID differs from the owned source')
    content_id = str(uuid.UUID(content['metadata']['uid']))
    agents = [p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
              if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
              and p['spec'].get('nodeName') == content['spec']['source']['nodeName']]
    if len(agents) != 1:
        raise ValueError('Expected exactly one agent on the capture node')
    agent = agents[0]['metadata']['name']
    root = '/checkpoints/artifacts/' + content_id
    result = run.k('exec', '-n', 'dynamo-system', agent, '-c', 'agent', '--',
                   'sh', '-c', 'find "$1" -maxdepth 8 -type f -printf "%s\\n" | '
                   'awk \'{bytes += $1; count++} END {printf "%.0f %.0f\\n", count, bytes}\'; '
                   'du -sk "$1"', 'measure-owned-artifact', root, timeout=45)
    lines = result.stdout.splitlines()
    file_count, logical_bytes = map(int, lines[0].split())
    allocated_bytes = int(lines[1].split()[0]) * 1024
    logs = run.k('logs', '-n', 'dynamo-system', agent, '-c', 'agent', '--timestamps', '--tail=2000').stdout
    summaries = []
    for line in logs.splitlines():
        if 'Checkpoint timing summary' not in line and 'Restore timing summary' not in line:
            continue
        record = json.loads(line[line.index('{'):])
        # Keep only this content's timings, not timings for unrelated workloads.
        if record.get('content') == content['metadata']['name'] or record.get('content_uid') == content_id:
            summaries.append({'at': line.split()[0], 'details': record})
    ready = any(c['type'] == 'Ready' and c['status'] == 'True' for c in snapshot['status'].get('conditions', []))
    content_ready = any(c['type'] == 'Ready' and c['status'] == 'True'
                        for c in content.get('status', {}).get('conditions', []))
    evidence = {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'artifact': name, 'content_uid': content_id, 'ready': ready,
                'content_ready': content_ready,
                'snapshot_conditions': snapshot['status'].get('conditions', []),
                'content_conditions': content.get('status', {}).get('conditions', []),
                'file_count': file_count, 'logical_bytes': logical_bytes,
                'allocated_bytes': allocated_bytes, 'agent_timing_summaries': summaries,
                'scope': 'Single observed artifact; staged files included until Ready; not a capacity minimum'}
    (run.path / f'snapshot-measurements-{time.time_ns()}.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (run.path / 'snapshot-measurements-latest.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    measure(Run(parser.parse_args().run))
