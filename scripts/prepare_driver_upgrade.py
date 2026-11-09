#!/usr/bin/env python3
"""Back up live releases and server-dry-run a version-only GPU driver upgrade."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import yaml
from testlib import ROOT, Run

TARGET_VERSION = '610.57.04'
CLIENT_LABEL = 'nvidia.com/gpu.deploy.client'
SKIP_LABEL = 'nvidia.com/gpu-driver-upgrade.skip'
SENTINEL_LABEL = 'k8saas.nvidia.com/ManagedByNVSentinel'
RELEASES = {
    'gpu-operator': {'namespace': 'gpu-operator', 'chart': 'gpu-operator-v26.7.0',
        'url': 'https://helm.ngc.nvidia.com/nvidia/charts/gpu-operator-v26.7.0.tgz'},
    'nvidia-dra-driver-gpu': {'namespace': 'nvidia-dra-driver', 'chart': 'dra-driver-nvidia-gpu-0.5.0',
        'url': 'oci://registry.k8s.io/dra-driver-nvidia/charts/dra-driver-nvidia-gpu', 'version': '0.5.0'},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def value_hash(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def helm_base():
    return ['helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']


def command(name, chart, values):
    return helm_base() + ['upgrade', name, str(chart), '-n', RELEASES[name]['namespace'],
        '--reset-values', '-f', str(values),
        # Helm 4 waits for custom ClusterPolicy readiness as well. The policy
        # cannot become Ready while explicit canary skip labels hold nodes.
        *([] if name == 'gpu-operator' else ['--wait']), '--timeout', '10m']


def desired(name, before):
    after = copy.deepcopy(before)
    if name == 'gpu-operator':
        after['driver']['version'] = TARGET_VERSION
        policy = after['driver']['upgradePolicy']
        if not policy['autoUpgrade'] or policy['maxParallelUpgrades'] != 1:
            raise ValueError('Expected the existing one-node automatic upgrade policy')
        if after['devicePlugin']['enabled']:
            raise ValueError('GPU device plugin must remain disabled with DRA allocation')
    else:
        # GPU Operator 26.7 toggles this client label during module reload.
        # Wiring the standalone DRA plugin into it prevents NVML holding the old driver.
        selector = after.setdefault('kubeletPlugin', {}).setdefault('nodeSelector', {})
        selector[CLIENT_LABEL] = 'true'
    return after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    args = parser.parse_args()
    run = Run(args.run)
    bundle = args.bundle.resolve()
    if (bundle / 'lock.json').exists():
        raise ValueError('Bundle already exists; preserve it and prepare a fresh path')
    bundle.mkdir(parents=True, exist_ok=True)
    releases = json.loads(run.command(helm_base() + ['list', '-A', '-o', 'json']).stdout)
    lock = {'target_driver': TARGET_VERSION, 'run': str(run.path.relative_to(ROOT)),
            'releases': {}, 'status': 'preparing', 'nodes': {}}
    for name, spec in RELEASES.items():
        release = next(r for r in releases if r['name'] == name and r['namespace'] == spec['namespace'])
        if release['chart'] != spec['chart'] or release['status'] != 'deployed':
            raise ValueError(f'Unexpected release: {release}')
        before = json.loads(run.command(helm_base() + ['get', 'values', name,
            '-n', spec['namespace'], '--all', '-o', 'json']).stdout)
        for suffix, flags in [('manifest.yaml', ['manifest']), ('user-values.yaml', ['values'])]:
            result = run.command(helm_base() + ['get', *flags, name, '-n', spec['namespace']])
            (run.path / f'{name}-before-{suffix}').write_text(result.stdout)
        (bundle / f'{name}-before-values.yaml').write_text(yaml.safe_dump(before, sort_keys=False))
        after = desired(name, before)
        values = bundle / f'{name}-values.yaml'
        values.write_text('# Complete values exported from the live release; driver upgrade bundle.\n'
                          + yaml.safe_dump(after, sort_keys=False))
        run.command(helm_base() + ['pull', spec['url'],
            *(['--version', spec['version']] if 'version' in spec else []),
            '--destination', str(run.path)], timeout=180)
        chart = run.path / (spec['chart'] + '.tgz')
        result = run.command(command(name, chart, values) +
            ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
        (run.path / f'{name}-driver-server-dry-run.json').write_text(result.stdout)
        rendered = json.loads(result.stdout)['manifest']
        (run.path / f'{name}-driver-rendered.yaml').write_text(rendered)
        if name == 'gpu-operator':
            current = list(yaml.safe_load_all((run.path / f'{name}-before-manifest.yaml').read_text()))
            target = list(yaml.safe_load_all(rendered))
            get_policy = lambda objects: next(x['spec'] for x in objects if x and x.get('kind') == 'ClusterPolicy')
            old_spec, new_spec = get_policy(current), get_policy(target)
            old_spec['driver']['version'] = TARGET_VERSION
            if old_spec != new_spec:
                raise ValueError('Rendered ClusterPolicy changes more than the driver version')
        lock['releases'][name] = {'revision': str(release['revision']), 'chart_name': spec['chart'],
            'chart_path': str(chart.relative_to(ROOT)), 'chart_sha256': sha(chart),
            'values_path': str(values.relative_to(ROOT)), 'values_sha256': sha(values),
            'before_values_hash': value_hash(before)}
    for resource in ('nodes', 'pods', 'daemonsets', 'deployments', 'resourceclaims',
                     'resourceslices', 'clusterpolicies', 'dynamographdeployments'):
        obj = run.get('get', resource, *([] if resource in ('nodes', 'resourceslices', 'clusterpolicies') else ['-A']))
        (run.path / f'driver-baseline-{resource}.json').write_text(json.dumps(obj, indent=2) + '\n')
        if resource == 'nodes':
            for node in obj['items']:
                meta = node['metadata']
                if 'H100' not in meta['labels'].get('nvidia.com/gpu.product', ''):
                    raise ValueError('Expected only the workshop H100 nodes')
                lock['nodes'][meta['name']] = {'uid': meta['uid'],
                    'unschedulable': node['spec'].get('unschedulable', False),
                    'labels': {key: meta['labels'].get(key) for key in (SKIP_LABEL, SENTINEL_LABEL, CLIENT_LABEL)}}
    lock['status'] = 'server-dry-run-passed'
    (bundle / 'lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    run.result('driver-upgrade-review', 'passed', bundle=str(bundle.relative_to(ROOT)),
               target=TARGET_VERSION, scope='Dry-run only; no shared cluster mutation')
    print(json.dumps(lock, indent=2))


if __name__ == '__main__':
    main()
