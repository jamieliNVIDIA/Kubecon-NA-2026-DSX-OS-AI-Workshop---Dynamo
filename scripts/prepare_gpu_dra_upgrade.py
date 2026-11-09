#!/usr/bin/env python3
"""Export complete Helm values and dry-run the dedicated demo GPU DRA transition."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import yaml
from testlib import ROOT, Run

TARGET = ROOT / 'configs/cluster-upgrade'
RELEASES = {
    'gpu-operator': {'release': 'gpu-operator', 'namespace': 'gpu-operator',
                     'chart': 'gpu-operator-v26.7.0',
                     'url': 'https://helm.ngc.nvidia.com/nvidia/charts/gpu-operator-v26.7.0.tgz'},
    'gpu-dra': {'release': 'nvidia-dra-driver-gpu', 'namespace': 'nvidia-dra-driver',
                'chart': 'dra-driver-nvidia-gpu-0.5.0', 'version': '0.5.0',
                'url': 'oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu'},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def desired_values(name, current):
    values = copy.deepcopy(current)
    if name == 'gpu-dra':
        values['gpuResourcesEnabledOverride'] = True
        values['nvidiaDriverRoot'] = '/run/nvidia/driver'
        values['resources']['gpus']['enabled'] = True
        values['resources']['computeDomains']['enabled'] = False
        values['kubeletPlugin']['nodeSelector'] = {}
    else:
        values['devicePlugin']['enabled'] = False
    return values


def upgrade_command(helm, name, chart, values):
    spec = RELEASES[name]
    return helm + ['upgrade', spec['release'], str(chart), '-n', spec['namespace'],
                   '--reset-values', '-f', str(values), '--wait', '--timeout', '10m']


def verify_bundle(lock):
    if lock['status'] != 'server-dry-run-passed' or lock['applied']:
        raise ValueError('Requires the unapplied server-dry-run review')
    for spec in lock['releases'].values():
        for key in ('chart', 'values'):
            if digest(ROOT / spec[f'{key}_path']) != spec[f'{key}_sha256']:
                raise ValueError(f'Reviewed {key} changed')
    review = ROOT / lock['review_run']
    operator = list(yaml.safe_load_all((review / 'gpu-operator-rendered.yaml').read_text()))
    policies = [o for o in operator if o and o.get('kind') == 'ClusterPolicy']
    if len(policies) != 1 or policies[0]['spec']['devicePlugin']['enabled']:
        raise ValueError('Rendered ClusterPolicy must disable the GPU device plugin')
    dra = [o for o in yaml.safe_load_all((review / 'gpu-dra-rendered.yaml').read_text()) if o]
    if not any(o.get('kind') == 'DeviceClass' and o['metadata']['name'] == 'gpu.nvidia.com' for o in dra):
        raise ValueError('Rendered chart lacks GPU DeviceClass')
    plugins = [o for o in dra if o.get('kind') == 'DaemonSet']
    if len(plugins) != 1 or [c['name'] for c in plugins[0]['spec']['template']['spec']['containers']] != ['gpus']:
        raise ValueError('Expected only the GPU resource plugin, without ComputeDomains')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true', help='Verify the saved bundle offline')
    args = parser.parse_args()
    if args.check_only:
        lock = json.loads((TARGET / 'gpu-dra-upgrade-lock.json').read_text())
        verify_bundle(lock)
        Run(args.run).result('gpu-dra-upgrade-review', **lock)
        return
    if (TARGET / 'gpu-dra-upgrade-lock.json').exists():
        raise ValueError('An existing reviewed bundle must be archived before preparing a replacement')
    run = Run(args.run)
    run.command([str(ROOT / 'scripts/kubecon-tunnel.sh'), 'start'])
    helm = ['helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    installed = json.loads(run.command(helm + ['list', '-A', '-o', 'json']).stdout)
    lock = {'kind': 'gpu-dra-demo-upgrade', 'applied': False, 'releases': {},
            'review_run': str(run.path.relative_to(ROOT))}
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, spec in RELEASES.items():
        release = next(r for r in installed if r['name'] == spec['release']
                       and r['namespace'] == spec['namespace'])
        if release['chart'] != spec['chart'] or release['status'] != 'deployed':
            raise ValueError(f'Unexpected installed release: {release}')
        computed = json.loads(run.command(helm + ['get', 'values', spec['release'],
            '-n', spec['namespace'], '--all', '-o', 'json']).stdout)
        user = run.command(helm + ['get', 'values', spec['release'],
            '-n', spec['namespace'], '-o', 'yaml']).stdout
        (run.path / f'{name}-before-user-values.yaml').write_text(user)
        (run.path / f'{name}-before-computed-values.yaml').write_text(yaml.safe_dump(computed, sort_keys=False))
        run.command(helm + ['pull', spec['url'],
            *(['--version', spec['version']] if 'version' in spec else []),
            '--destination', str(run.path)], timeout=180)
        chart = run.path / (spec['chart'] + '.tgz')
        values_file = TARGET / f'{name}-values.yaml'
        values_file.write_text('# Complete computed values from the installed release; proposed target.\n'
                               + yaml.safe_dump(desired_values(name, computed), sort_keys=False))
        command = upgrade_command(helm, name, chart, values_file)
        dry = run.command(command + ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
        (run.path / f'{name}-server-dry-run.json').write_text(dry.stdout)
        rendered = json.loads(dry.stdout)
        (run.path / f'{name}-rendered.yaml').write_text(rendered['manifest'])
        lock['releases'][name] = {'release': spec['release'], 'namespace': spec['namespace'],
            'chart': spec['chart'], 'before_revision': release['revision'],
            'chart_path': str(chart.relative_to(ROOT)), 'chart_sha256': digest(chart),
            'values_path': str(values_file.relative_to(ROOT)), 'values_sha256': digest(values_file),
            'baseline_values_sha256': hashlib.sha256(json.dumps(computed, sort_keys=True).encode()).hexdigest(),
            'dry_run': 'passed', 'chart_source': spec['url']}
    for resource in ('nodes', 'pods', 'daemonsets', 'deployments', 'resourceclaims', 'resourceslices',
                     'deviceclasses', 'clusterpolicies', 'dynamographdeployments', 'computedomain'):
        cluster_scoped = resource in ('nodes', 'resourceslices', 'deviceclasses', 'clusterpolicies')
        data = run.get('get', resource, *([] if cluster_scoped else ['-A']))
        (run.path / f'before-{resource}.json').write_text(json.dumps(data, indent=2) + '\n')
    lock['status'] = 'server-dry-run-passed'
    verify_bundle(lock)
    (TARGET / 'gpu-dra-upgrade-lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    run.result('gpu-dra-upgrade-review', **lock)


if __name__ == '__main__':
    main()
