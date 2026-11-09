#!/usr/bin/env python3
"""Prepare a digest-pinned single-node Snapshot installation; dry-run only."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tarfile
import yaml
from prepare_dynamo_upgrade import resources, images
from testlib import ROOT, Run


def prepare(run, node):
    helm = ['/opt/homebrew/bin/helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
    release, namespace = 'dynamo-platform', 'dynamo-system'
    installed = next(r for r in json.loads(run.command(helm + ['list', '-n', namespace, '-o', 'json']).stdout)
                     if r['name'] == release)
    if installed['chart'] != 'dynamo-platform-1.5.1':
        raise ValueError('Requires the installed 1.5.1 platform')
    for kind in ('deployments', 'daemonsets'):
        for item in run.get('get', kind, '-A')['items']:
            if any(s in item['metadata']['name'] for s in ('snapshot-agent', 'snapshot-operator')):
                raise ValueError('Snapshot already installed; review existing ownership instead')
    nodes = run.get('get', 'nodes')['items']
    selected = next(n for n in nodes if n['metadata']['name'] == node)
    if 'H100' not in selected['metadata']['labels'].get('nvidia.com/gpu.product', ''):
        raise ValueError('Choose an existing H100 node')
    runtime_classes = run.get('get', 'runtimeclasses')['items']
    if 'nvidia' not in {r['metadata']['name'] for r in runtime_classes}:
        raise ValueError('Bundled Snapshot agent requires RuntimeClass nvidia')
    for filename, arguments in {
        'snapshot-before-values.json': ['get', 'values', release, '-n', namespace, '-o', 'json'],
        'snapshot-before-manifest.yaml': ['get', 'manifest', release, '-n', namespace],
        'snapshot-before-history.json': ['history', release, '-n', namespace, '-o', 'json'],
    }.items():
        (run.path / filename).write_text(run.command(helm + arguments).stdout)
    values = json.loads((run.path / 'snapshot-before-values.json').read_text()) or {}
    chart = ROOT / 'results/20261013t050322z-features/dynamo-platform-1.5.1.tgz'
    if hashlib.sha256(chart.read_bytes()).hexdigest() != 'b220d4ccc6b8c1dd25df80b471469380721432a32413ee58920d7fb0c0d38e41':
        raise ValueError('Qualified platform chart hash changed')
    pins = json.loads((ROOT / 'configs/snapshot-0.1.0-images.json').read_text())
    override = {'global': {'snapshot': {'install': True}},
        'dynamo-operator': {'checkpoint': {'enabled': True}},
        'snapshot': {'storage': {'pvc': {'create': False, 'name': 'snapshot-artifacts'}},
            'daemonset': {'nodeSelector': {'kubernetes.io/hostname': node, 'nvidia.com/gpu.present': 'true'},
                         'resources': {'requests': {'cpu': '2', 'memory': '1Gi'},
                                       'limits': {'cpu': '4', 'memory': '16Gi'}}},
            'image': {name: {'repository': pin['tag'].rsplit(':', 1)[0],
                            'tag': 'v0.1.0@' + pin['digest']}
                      for name, pin in zip(('operator', 'agent'), pins)}}}
    override_path = ROOT / 'configs/snapshot-install-values.yaml'
    override_path.write_text(yaml.safe_dump(override, sort_keys=False))
    (run.path / 'snapshot-install-values.yaml').write_text(override_path.read_text())
    source = run.get('get', 'pv', 'dynamo-shared-pv')
    csi = copy.deepcopy(source['spec']['csi'])
    filesystem = csi['volumeHandle']
    if csi['driver'] != 'efs.csi.aws.com' or ':' in filesystem:
        raise ValueError('Requires the verified root EFS filesystem handle')
    # Never expose the filesystem root to Snapshot's orphan-artifact cleanup.
    artifact_subdir = f'/feature-tests/{run.state["run_id"]}/snapshot-artifacts'
    csi['volumeHandle'] = filesystem + ':' + artifact_subdir
    pv_name = 'dynamo-workshop-snapshot-artifacts'
    storage = [{'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': pv_name, 'labels': run.labels()},
        'spec': {'capacity': {'storage': '256Gi'}, 'accessModes': ['ReadWriteMany'],
                 'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '',
                 'claimRef': {'namespace': namespace, 'name': 'snapshot-artifacts'}, 'csi': csi}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
         'metadata': {'name': 'snapshot-artifacts', 'namespace': namespace, 'labels': run.labels()},
         'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '', 'volumeName': pv_name,
                  'resources': {'requests': {'storage': '256Gi'}}}}]
    storage_path = ROOT / 'configs/snapshot-artifact-storage.yaml'
    storage_path.write_text(yaml.safe_dump_all(storage, sort_keys=False))
    (run.path / 'snapshot-artifact-storage.yaml').write_text(storage_path.read_text())
    # This only validates the objects; no privileged/system resources are created.
    run.k('apply', '--dry-run=server', '-f', str(storage_path))
    upgrade = helm + ['upgrade', release, str(chart), '-n', namespace,
        '--reset-then-reuse-values', '-f', str(override_path), '--wait', '--timeout', '10m']
    dry = run.command(upgrade + ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180)
    (run.path / 'snapshot-helm-dry-run.json').write_text(dry.stdout)
    manifest = json.loads(dry.stdout)['manifest']
    (run.path / 'snapshot-rendered-manifest.yaml').write_text(manifest)
    before, after = resources((run.path / 'snapshot-before-manifest.yaml').read_text()), resources(manifest)
    before_images, after_images = images(before), images(after)
    changed_images = {name: {'before': before_images.get(name), 'after': after_images.get(name)}
        for name in before_images.keys() | after_images.keys() if before_images.get(name) != after_images.get(name)}
    if any('snapshot' not in name for name in changed_images):
        raise ValueError('Unexpected non-Snapshot image changes')
    agent = next(o for o in after.values() if o['kind'] == 'DaemonSet' and o['metadata']['name'].endswith('snapshot-agent'))
    if agent['spec']['template']['spec']['nodeSelector'].get('kubernetes.io/hostname') != node:
        raise ValueError('Agent node restriction lost')
    crd_records = []
    existing_snapshots = {}
    with tarfile.open(chart) as archive:
        for member in archive.getmembers():
            if '/charts/snapshot/crds/' not in member.name or not member.name.endswith('.yaml'):
                continue
            target = yaml.safe_load(archive.extractfile(member).read())
            name = target['metadata']['name']
            old = run.k('get', 'crd', name, '-o', 'json', check=False)
            live = json.loads(old.stdout) if old.returncode == 0 else None
            if live:
                objects = run.get('get', name, '-A')
                (run.path / f'snapshot-before-objects-{name}.json').write_text(json.dumps(objects, indent=2))
                existing_snapshots[name] = len(objects['items'])
                if objects['items']:
                    raise ValueError(f'Existing {name} objects need compatibility review before changing their controller/CRD')
            (run.path / f'snapshot-before-{name}.json').write_text(json.dumps(live, indent=2))
            proposed = run.path / (name + '.yaml')
            proposed.write_text(yaml.safe_dump(target, sort_keys=False))
            # Match the chart's CRD upgrader ownership operation, but only dry-run.
            run.k('apply', '--server-side', '--force-conflicts', '--dry-run=server',
                  '--field-manager=snapshot-review', '-f', str(proposed))
            crd_records.append({'name': name, 'exists': bool(live),
                                'spec_changed': live is None or live['spec'] != target['spec'],
                                'stored_versions': live.get('status', {}).get('storedVersions') if live else [],
                                'target_storage': [v['name'] for v in target['spec']['versions'] if v.get('storage')]})
    summary = {'applied': False, 'status': 'server-dry-run-passed', 'platform_version': '1.5.1',
        'snapshot_version': '0.1.0', 'before_helm_revision': installed['revision'],
        'chart_sha256': hashlib.sha256(chart.read_bytes()).hexdigest(), 'agent_node': node,
        'values_sha256': hashlib.sha256(override_path.read_bytes()).hexdigest(),
        'artifact_manifest_sha256': hashlib.sha256(storage_path.read_bytes()).hexdigest(),
        'images': pins, 'images_changed': changed_images,
        'resources_added': sorted('/'.join(k) for k in after.keys() - before.keys()),
        'resources_removed': sorted('/'.join(k) for k in before.keys() - after.keys()),
        'crds': crd_records, 'existing_snapshot_counts': existing_snapshots,
        'artifact_subdirectory': artifact_subdir, 'artifact_pv': pv_name,
        'artifact_capacity': '256Gi advisory; EFS has no PV quota',
        'host_changes': ['Privileged hostPID/hostIPC/hostNetwork agent on one node',
                         'Write /var/lib/kubelet/seccomp/profiles/block-iouring.json',
                         'Runtime socket and cgroup/PID access'],
        'apply_command': upgrade,
        'rollback': 'Stop owned Snapshot tests, disable checkpoint, Helm rollback to recorded revision; CRD updates, seccomp profile, Retain PV/PVC/artifacts persist and require separate review',
        'authorization': 'Not applied: shared privileged infrastructure requires explicit approval under the no-major-changes constraint'}
    (run.path / 'snapshot-install-review.json').write_text(json.dumps(summary, indent=2) + '\n')
    run.result('snapshot-install-review', **summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--node', default='kubecon-nke-site-cp-0124')
    args = parser.parse_args()
    prepare(Run(args.run), args.node)


if __name__ == '__main__':
    main()
