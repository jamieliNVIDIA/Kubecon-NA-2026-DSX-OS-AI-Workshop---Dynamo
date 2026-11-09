#!/usr/bin/env python3
"""Back up and server-dry-run a Dynamo Helm upgrade; never apply it."""
import argparse
import hashlib
import json
from pathlib import Path
import yaml
from testlib import ROOT, Run


def resources(manifest):
    return {(obj['kind'], obj.get('metadata', {}).get('namespace', ''), obj['metadata']['name']): obj
            for obj in yaml.safe_load_all(manifest) if isinstance(obj, dict) and obj.get('kind')}


def images(objects):
    return {key[2]: [container['image'] for container in
                    obj['spec']['template']['spec'].get('initContainers', []) +
                    obj['spec']['template']['spec'].get('containers', [])]
            for key, obj in objects.items() if obj['kind'] in ('Deployment', 'DaemonSet', 'StatefulSet', 'Job')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='1.5.1')
    parser.add_argument('--run', type=Path)
    args = parser.parse_args()
    if args.version != '1.5.1':
        raise ValueError('Only the reviewed 1.5.1 target is supported by this proposal')
    run = Run(args.run)
    print(f'Upgrade review: {run.path}', flush=True)
    release, namespace = 'dynamo-platform', 'dynamo-system'
    helm = ['helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    deployed = json.loads(run.command(helm + ['list', '-n', namespace, '-o', 'json']).stdout)
    installed = next(item for item in deployed if item['name'] == release)
    if installed['chart'] != 'dynamo-platform-1.4.2':
        raise ValueError(f'Installed chart differs from the reviewed baseline: {installed["chart"]}')
    for name, command in {
        'helm-user-values.json': ['get', 'values', release, '-n', namespace, '-o', 'json'],
        'helm-computed-values.json': ['get', 'values', release, '-n', namespace, '--all', '-o', 'json'],
        'helm-manifest.yaml': ['get', 'manifest', release, '-n', namespace],
        'helm-history.json': ['history', release, '-n', namespace, '-o', 'json'],
    }.items():
        (run.path / name).write_text(run.command(helm + command).stdout)
    values = json.loads((run.path / 'helm-user-values.json').read_text()) or {}
    for resource in ('dynamographdeployments', 'dynamocomponentdeployments',
                     'dynamocheckpoints', 'podsnapshots'):
        (run.path / f'before-{resource}.json').write_text(json.dumps(run.get('get', resource, '-A'), indent=2))
    crds = run.get('get', 'crds')
    (run.path / 'before-crds.json').write_text(json.dumps(crds, indent=2))
    chart_url = f'https://helm.ngc.nvidia.com/nvidia/ai-dynamo/charts/dynamo-platform-{args.version}.tgz'
    run.command(helm + ['pull', chart_url, '--destination', str(run.path)], timeout=180)
    chart = run.path / f'dynamo-platform-{args.version}.tgz'
    upgrade = helm + ['upgrade', release, str(chart), '-n', namespace,
                      '--reset-then-reuse-values', '--set', 'global.snapshot.install=false',
                      '--set', 'dynamo-operator.checkpoint.enabled=false',
                      '--wait', '--timeout', '10m']
    (run.path / 'upgrade-command.json').write_text(json.dumps(upgrade, indent=2) + '\n')
    dry = run.command(upgrade + ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
    (run.path / 'dry-run.json').write_text(dry.stdout)
    rendered = json.loads(dry.stdout)
    manifest = rendered['manifest']
    (run.path / 'rendered-manifest.yaml').write_text(manifest)
    before = resources((run.path / 'helm-manifest.yaml').read_text())
    after = resources(manifest)
    before_images, after_images = images(before), images(after)
    changes = {name: {'before': before_images.get(name), 'after': after_images.get(name)}
               for name in before_images.keys() | after_images.keys()
               if before_images.get(name) != after_images.get(name)}
    legacy = json.loads((run.path / 'before-dynamocheckpoints.json').read_text())['items']
    dgds = json.loads((run.path / 'before-dynamographdeployments.json').read_text())['items']
    summary = {
        'status': 'server-dry-run-passed', 'applied': False, 'release': release,
        'namespace': namespace, 'before_chart': installed['chart'], 'before_revision': installed['revision'],
        'target_version': args.version, 'chart_url': chart_url,
        'chart_sha256': hashlib.sha256(chart.read_bytes()).hexdigest(),
        'user_global_values': values.get('global', {}),
        'snapshot_install': False, 'checkpoint_enabled': False,
        'images_changed': changes,
        'resources_added': sorted('/'.join(key) for key in after.keys() - before.keys()),
        'resources_removed': sorted('/'.join(key) for key in before.keys() - after.keys()),
        'active_dgds': [f'{obj["metadata"]["namespace"]}/{obj["metadata"]["name"]}' for obj in dgds],
        'legacy_checkpoint_count': len(legacy),
        'crd_versions': {obj['metadata']['name']: {
            'stored': obj.get('status', {}).get('storedVersions', []),
            'served': [v['name'] for v in obj['spec']['versions'] if v.get('served')],
            'storage': [v['name'] for v in obj['spec']['versions'] if v.get('storage')],
        } for obj in crds['items'] if obj['metadata']['name'].startswith('dynamo')},
        'rollback_limits': 'Helm rollback does not reverse CRD migration; preserve CRDs and stored objects before applying',
    }
    (run.path / 'upgrade-review.json').write_text(json.dumps(summary, indent=2) + '\n')
    run.result('dynamo-upgrade-review', **summary)


if __name__ == '__main__':
    main()
