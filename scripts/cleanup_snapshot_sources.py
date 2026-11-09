#!/usr/bin/env python3
"""Remove terminal capture Pods from this run's recorded failed SnapshotJob; retain artifacts."""
import argparse
import json
from pathlib import Path
from testlib import OWNER, Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    run = Run(parser.parse_args().run)
    namespace = run.get('get', 'namespace', run.ns)
    if namespace['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER:
        raise ValueError('Namespace is not owned')
    failure = json.loads((run.path / 'snapshot-capture-failure.json').read_text())
    if failure['metadata']['namespace'] != run.ns or not any(
            c['type'] == 'Failed' and c['status'] == 'True' for c in failure['status']['conditions']):
        raise ValueError('Requires this namespace\'s recorded failed SnapshotJob')
    name = failure['metadata']['name']
    current = run.get('get', 'snapshotjob', name, '-n', run.ns)
    if current['metadata']['uid'] != failure['metadata']['uid']:
        raise ValueError('SnapshotJob UID changed')
    claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
    removed = []
    for pod in run.get('get', 'pods', '-n', run.ns, '-l', 'nvidia.com/snapshot-job=' + name)['items']:
        if pod['status'].get('phase') not in ('Succeeded', 'Failed'):
            raise ValueError('Refusing to delete a nonterminal capture Pod')
        if not any(o['kind'] == 'Job' and o['uid'] == failure['status']['sourceJobUID']
                   for o in pod['metadata'].get('ownerReferences', [])):
            raise ValueError('Capture Pod owner UID mismatch')
        if any(any(r.get('uid') == pod['metadata']['uid'] for r in c.get('status', {}).get('reservedFor', [])) for c in claims):
            raise ValueError('Capture Pod still has a reserved GPU claim')
        target = pod['metadata']['name']
        (run.path / f'{target}-cleanup-pod.json').write_text(json.dumps(pod, indent=2) + '\n')
        run.k('delete', 'pod', target, '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
        removed.append(target)
    run.result('snapshot-terminal-source-cleanup', 'passed', removed=removed,
               scope='Only terminal capture Pods from the UID-matched failed job; Snapshot objects/artifacts retained')


if __name__ == '__main__':
    main()
