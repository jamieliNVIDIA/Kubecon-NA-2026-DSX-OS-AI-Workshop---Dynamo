#!/usr/bin/env python3
"""Apply only a reviewed Snapshot installation after explicit user approval."""
import argparse
import hashlib
import json
from pathlib import Path
import yaml
from testlib import ROOT, OWNER, Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--runtime-run', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Use only after the user approves this reviewed privileged infrastructure change')
    args = parser.parse_args()
    run = Run(args.review)
    review = json.loads((run.path / 'snapshot-install-review.json').read_text())
    if not args.apply:
        print('Review only; no changes. Apply requires explicit user approval and --apply.')
        return
    runtime = json.loads((args.runtime_run / 'state.json').read_text())
    check = runtime['checks']['snapshot-runtime-preparation']
    if runtime['owner'] != OWNER or check['status'] != 'passed' or not check['communicator_checkpoint_hooks']:
        raise ValueError('Requires an owned passing exact-model native preparation test')
    if review['applied'] or review['status'] != 'server-dry-run-passed':
        raise ValueError('Requires an unapplied passing installation review')
    if any(run.state['checks'].get(name, {}).get('status') != 'passed'
           for name in ('snapshot-artifact-directory', 'snapshot-artifact-subpath')):
        raise ValueError('Verify both the owned artifact directory and its exact CSI export first')
    for name, key in (('snapshot-install-values.yaml', 'values_sha256'),
                      ('snapshot-artifact-storage.yaml', 'artifact_manifest_sha256')):
        for path in (ROOT / 'configs' / name, run.path / name):
            if hashlib.sha256(path.read_bytes()).hexdigest() != review[key]:
                raise ValueError(f'Reviewed manifest changed: {path}')
    command = review['apply_command']
    chart = Path(command[command.index('dynamo-platform') + 1])
    if hashlib.sha256(chart.read_bytes()).hexdigest() != review['chart_sha256']:
        raise ValueError('Reviewed chart changed')
    helm = ['/opt/homebrew/bin/helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    deployed = next(i for i in json.loads(run.command(helm + ['list', '-n', 'dynamo-system', '-o', 'json']).stdout)
                    if i['name'] == 'dynamo-platform')
    if str(deployed['revision']) != str(review['before_helm_revision']) or deployed['chart'] != 'dynamo-platform-1.5.1':
        raise ValueError('Platform revision changed; prepare a new review')
    current_values = json.loads(run.command(helm + ['get', 'values', 'dynamo-platform', '-n', 'dynamo-system', '-o', 'json']).stdout)
    if current_values != json.loads((run.path / 'snapshot-before-values.json').read_text()):
        raise ValueError('Shared platform settings changed after review')
    for resource in ('deployments', 'daemonsets'):
        if any('snapshot-operator' in i['metadata']['name'] or 'snapshot-agent' in i['metadata']['name']
               for i in run.get('get', resource, '-A')['items']):
            raise ValueError('Snapshot already managed; do not install a competing controller')
    for name in review['existing_snapshot_counts']:
        if run.get('get', name, '-A')['items']:
            raise ValueError('Snapshot objects appeared after review')
    for crd in review['crds']:
        result = run.k('get', 'crd', crd['name'], '-o', 'json', check=False)
        if not crd['exists']:
            if result.returncode == 0 or 'NotFound' not in result.stderr:
                raise ValueError('Snapshot API state changed after review')
        else:
            before = json.loads((run.path / f'snapshot-before-{crd["name"]}.json').read_text())
            if result.returncode or json.loads(result.stdout)['spec'] != before['spec']:
                raise ValueError('Snapshot schema changed after review')
    objects = list(yaml.safe_load_all((run.path / 'snapshot-artifact-storage.yaml').read_text()))
    for obj in objects:
        scope = [] if obj['kind'] == 'PersistentVolume' else ['-n', 'dynamo-system']
        result = run.k('get', obj['kind'], obj['metadata']['name'], *scope, '-o', 'json', check=False)
        if result.returncode == 0:
            old = json.loads(result.stdout)
            if old['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                raise ValueError('Refusing to change an unowned storage object')
        elif 'NotFound' not in result.stderr:
            raise RuntimeError(result.stderr)
    content = json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects})
    run.k('apply', '--dry-run=server', '-f', '-', input_text=content)
    run.command(command + ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
    # The explicit approval covers these reviewed system-namespace/cluster
    # resources; generic test Run.apply intentionally does not allow this scope.
    run.k('apply', '-f', '-', input_text=content)
    run.k('wait', 'pvc/snapshot-artifacts', '-n', 'dynamo-system', '--for=jsonpath={.status.phase}=Bound', '--timeout=120s', timeout=135)
    run.command(command, timeout=660)
    for target in ('deployment/dynamo-platform-snapshot-operator',
                   'daemonset/dynamo-platform-snapshot-agent',
                   'deployment/dynamo-platform-dynamo-operator-controller-manager'):
        run.k('rollout', 'status', target, '-n', 'dynamo-system', '--timeout=300s', timeout=315)
    run.result('snapshot-infrastructure', 'installed', agent_node=review['agent_node'],
               scope='Reviewed Snapshot 0.1.0 infrastructure only; actual capture/restore still requires the feature test')


if __name__ == '__main__':
    main()
