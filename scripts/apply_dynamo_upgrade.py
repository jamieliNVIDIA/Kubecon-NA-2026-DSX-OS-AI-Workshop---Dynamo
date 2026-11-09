#!/usr/bin/env python3
"""Apply the reviewed, explicitly authorized 1.5.1 platform upgrade and verify it."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from testlib import ROOT, Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', required=True)
    args = parser.parse_args()
    run = Run(args.review)
    summary = json.loads((run.path / 'upgrade-review.json').read_text())
    if summary['status'] != 'server-dry-run-passed' or summary['target_version'] != '1.5.1':
        raise ValueError('Requires the successful reviewed 1.5.1 proposal')
    chart = run.path / 'dynamo-platform-1.5.1.tgz'
    if hashlib.sha256(chart.read_bytes()).hexdigest() != summary['chart_sha256']:
        raise ValueError('Chart changed since review')
    helm = ['helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    installed = next(item for item in json.loads(run.command(
        helm + ['list', '-n', summary['namespace'], '-o', 'json']).stdout)
        if item['name'] == summary['release'])
    if installed['revision'] != summary['before_revision'] or installed['chart'] != summary['before_chart']:
        raise ValueError('Helm release changed since review')
    for resource in ('dynamographdeployments', 'dynamocomponentdeployments', 'dynamocheckpoints'):
        if run.get('get', resource, '-A')['items']:
            raise ValueError(f'{resource} appeared since review; review before applying')
    upgrade = json.loads((run.path / 'upgrade-command.json').read_text())
    run.result('dynamo-upgrade', 'applying', target_version='1.5.1',
               authorization='User explicitly approved Apply 1.5.1 and run retests')
    try:
        applied = run.command(upgrade + ['-o', 'json'], timeout=660)
        (run.path / 'applied-release.json').write_text(applied.stdout)
        run.k('rollout', 'status', 'deployment/dynamo-platform-dynamo-operator-controller-manager',
              '-n', 'dynamo-system', '--timeout=300s', timeout=330)
        deadline = time.monotonic() + 180
        while True:
            crds = [run.get('get', 'crd', name) for name in
                    ('dynamographdeployments.nvidia.com', 'dynamocomponentdeployments.nvidia.com')]
            versions = {obj['metadata']['name']: {
                'stored': obj.get('status', {}).get('storedVersions', []),
                'storage': [v['name'] for v in obj['spec']['versions'] if v.get('storage')],
            } for obj in crds}
            if all(v['storage'] == ['v1beta1'] and v['stored'] == ['v1beta1'] for v in versions.values()):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f'CRD migration incomplete: {versions}')
            time.sleep(5)
        nodes = run.get('get', 'nodes')['items']
        assert len(nodes) == 3 and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                                        for c in node['status']['conditions']) for node in nodes)
        releases = json.loads(run.command(helm + ['list', '-A', '-o', 'json']).stdout)
        (run.path / 'after-helm.json').write_text(json.dumps(releases, indent=2) + '\n')
        run.result('dynamo-upgrade', 'passed', target_version='1.5.1', applied=True,
                   crd_versions=versions, ready_nodes=[node['metadata']['name'] for node in nodes],
                   note='Rollout/migration only; inference and feature retests follow')
    except Exception as error:
        run.result('dynamo-upgrade', 'blocked', error=str(error),
                   note='No automatic CRD rollback; inspect saved release/CRD state')
        raise


if __name__ == '__main__':
    main()
