#!/usr/bin/env python3
"""Prepare/apply the authorized Snapshot-only development upgrade in its existing release."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time
import yaml

from prepare_dynamo_upgrade import resources
from testlib import ROOT, Run

SHA = 'd752d982738883e3575de7bbce0689e2443fa2c2'
SOURCE = ROOT / '.local' / ('snapshot-' + SHA[:12])
BUNDLE = ROOT / 'configs/snapshot-upgrade-20261022'
HELM = ['/opt/homebrew/bin/helm', f'--kubeconfig={ROOT / ".local/kubeconfig"}']
RELEASE, NS = 'dynamo-platform', 'dynamo-system'
NODE = 'kubecon-nke-site-cp-0124'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def idle(run):
    if run.get('get', 'dgd', '-A')['items'] or run.get('get', 'resourceclaims', '-A')['items']:
        raise ValueError('Requires no active DGDs or GPU claims')
    pods = run.get('get', 'pods', '-A')['items']
    if any(p['metadata']['namespace'].startswith('dynamo-ft-') and
           p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in pods):
        raise ValueError('Active feature-test Pod exists')


def prepare(run):
    idle(run)
    BUNDLE.mkdir(exist_ok=True)
    deployed = next(r for r in json.loads(run.command(HELM + ['list', '-n', NS, '-o', 'json']).stdout) if r['name'] == RELEASE)
    if deployed['chart'] != 'dynamo-platform-1.5.1':
        raise ValueError('Requires the reviewed platform baseline')
    for name, cmd in {'values.json': ['get', 'values', RELEASE, '-n', NS, '-o', 'json'],
                      'manifest.yaml': ['get', 'manifest', RELEASE, '-n', NS],
                      'history.json': ['history', RELEASE, '-n', NS, '-o', 'json']}.items():
        (run.path / ('before-' + name)).write_text(run.command(HELM + cmd).stdout)
    for kind in ('podsnapshots', 'podsnapshotcontents', 'snapshotjobs'):
        (run.path / ('before-' + kind + '.json')).write_text(json.dumps(run.get('get', kind, '-A'), indent=2))
    baseline = ROOT / 'results/20261013t050322z-features/dynamo-platform-1.5.1.tgz'
    if digest(baseline) != 'b220d4ccc6b8c1dd25df80b471469380721432a32413ee58920d7fb0c0d38e41':
        raise ValueError('Base platform chart differs')
    stage = run.path / ('chart-' + str(time.time_ns()))
    stage.mkdir()
    with tarfile.open(baseline) as tf:
        for member in tf.getmembers():
            rel = Path(member.name)
            if rel.is_absolute() or '..' in rel.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe platform archive')
        tf.extractall(stage)
    platform = stage / 'dynamo-platform'
    nested = platform / 'charts/snapshot'
    if not nested.is_dir():
        raise ValueError('Expected the bundled Snapshot dependency')
    shutil.rmtree(nested)
    shutil.copytree(SOURCE / 'charts/snapshot', nested)
    shutil.copyfile(SOURCE / 'LICENSE', nested / 'LICENSE')
    pins = ROOT / 'configs/snapshot-cuinterpose-images.json'
    records = json.loads(pins.read_text())
    by_name = {r['tag'].split('/')[-1].split(':')[0]: r for r in records}
    # Upstream couples the PageBroker tag to the agent tag. Preserve the
    # matching source build while allowing each image's own immutable digest.
    template = nested / 'templates/daemonset.yaml'
    original = template.read_text()
    old = 'image: "{{ .Values.image.pageBroker.repository }}:{{ .Values.image.agent.tag | default .Chart.AppVersion }}"'
    if original.count(old) != 1:
        raise ValueError('PageBroker image template changed upstream')
    replacement = 'image: "{{ .Values.image.pageBroker.repository }}@{{ .Values.image.pageBroker.digest }}"'
    template.write_text(original.replace(old, replacement))
    (BUNDLE / 'pagebroker-digest-template-change.json').write_text(json.dumps({'source_sha': SHA, 'before': old, 'after': replacement}, indent=2))
    chart = BUNDLE / 'dynamo-platform-1.5.1-snapshot-dev.tgz'
    with tarfile.open(chart, 'w:gz') as tf:
        tf.add(platform, arcname='dynamo-platform')
    values = json.loads((run.path / 'before-values.json').read_text())
    snapshot = copy.deepcopy(values['snapshot'])
    for name in ('operator', 'agent'):
        snapshot['image'][name]['tag'] = 'v0.0.0-g' + SHA[:8] + '@' + by_name[name]['digest']
    snapshot['image']['pageBroker'] = {'repository': 'ghcr.io/ai-dynamo/snapshot/pagebroker',
                                     'digest': by_name['pagebroker']['digest'], 'pullPolicy': 'IfNotPresent'}
    snapshot['storage']['pvc'] = {'create': False, 'name': 'snapshot-artifacts-cuinterpose'}
    snapshot['daemonset']['nodeSelector'] = {'kubernetes.io/hostname': NODE, 'nvidia.com/gpu.present': 'true'}
    snapshot['daemonset']['snapshotLogLevel'] = 'debug'
    snapshot['daemonset']['resources'] = {'requests': {'cpu': '2', 'memory': '16Gi'}, 'limits': {'cpu': '8', 'memory': '384Gi'}}
    snapshot['pageBroker'] = {'restoreMode': 'direct', 'staging': {'sizeLimit': '320Gi'},
        'resources': {'requests': {'cpu': '4', 'memory': '40Gi'}, 'limits': {'cpu': '16', 'memory': '384Gi'}}}
    values['snapshot'] = snapshot
    values_path = BUNDLE / 'values.yaml'
    values_path.write_text(yaml.safe_dump(values, sort_keys=False))
    (BUNDLE / 'rollback-values.yaml').write_text((run.path / 'before-values.json').read_text())
    (BUNDLE / 'images.json').write_bytes(pins.read_bytes())
    command = HELM + ['upgrade', RELEASE, str(chart), '-n', NS, '--reset-values', '-f', str(values_path),
        '--wait', '--timeout', '10m']
    rendered = json.loads(run.command(command + ['--dry-run=server', '--hide-secret', '-o', 'json'], timeout=180).stdout)
    (run.path / 'rendered.yaml').write_text(rendered['manifest'])
    before = resources((run.path / 'before-manifest.yaml').read_text())
    after = resources(rendered['manifest'])
    changed = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]
    if any('snapshot' not in k[2] for k in changed):
        raise ValueError('Unexpected non-Snapshot resource changes: ' + str(changed))
    ds = next(o for o in after.values() if o['kind'] == 'DaemonSet' and o['metadata']['name'].endswith('snapshot-agent'))
    if ds['spec']['template']['spec']['nodeSelector'].get('kubernetes.io/hostname') != NODE:
        raise ValueError('Single-node agent scope lost')
    if {c['name'] for c in ds['spec']['template']['spec']['containers']} != {'agent', 'pagebroker'}:
        raise ValueError('Expected matching agent and PageBroker')
    for o in after.values():
        if o['kind'] not in ('Deployment', 'DaemonSet') or 'snapshot' not in o['metadata']['name']:
            continue
        for c in o['spec']['template']['spec'].get('containers', []) + o['spec']['template']['spec'].get('initContainers', []):
            if c['image'].startswith('ghcr.io/ai-dynamo/snapshot/') and c['image'].split('@')[-1] not in {r['digest'] for r in records}:
                raise ValueError('Unpinned Snapshot image')
    crds = []
    for path in sorted((nested / 'crds').glob('*.yaml')):
        obj = yaml.safe_load(path.read_text());name = obj['metadata']['name']
        (run.path / ('before-crd-' + name + '.json')).write_text(json.dumps(run.get('get', 'crd', name), indent=2))
        run.k('apply', '--server-side', '--force-conflicts', '--dry-run=server', '-f', str(path))
        crds.append(str(path))
    source = run.get('get', 'pv', 'dynamo-shared-pv')
    csi = copy.deepcopy(source['spec']['csi'])
    if csi['driver'] != 'efs.csi.aws.com' or ':' in csi['volumeHandle']:
        raise ValueError('Expected existing root EFS filesystem')
    artifact_subdir = f'/feature-tests/{run.state["run_id"]}/snapshot-artifacts'
    csi['volumeHandle'] += ':' + artifact_subdir
    storage = [{'apiVersion': 'v1', 'kind': 'PersistentVolume',
        'metadata': {'name': 'dynamo-workshop-snapshot-cuinterpose', 'labels': run.labels()},
        'spec': {'capacity': {'storage': '1Ti'}, 'accessModes': ['ReadWriteMany'], 'storageClassName': '',
            'persistentVolumeReclaimPolicy': 'Retain',
            'claimRef': {'namespace': NS, 'name': 'snapshot-artifacts-cuinterpose'}, 'csi': csi}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
        'metadata': {'name': 'snapshot-artifacts-cuinterpose', 'namespace': NS, 'labels': run.labels()},
        'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '',
            'volumeName': 'dynamo-workshop-snapshot-cuinterpose', 'resources': {'requests': {'storage': '1Ti'}}}}]
    storage_path = BUNDLE / 'storage.yaml';storage_path.write_text(yaml.safe_dump_all(storage, sort_keys=False))
    run.k('apply', '--dry-run=server', '-f', str(storage_path))
    review = {'source_sha': SHA, 'before_revision': deployed['revision'], 'agent_node': NODE,
        'artifact_subdirectory': artifact_subdir, 'command': command, 'crds': crds,
        'changed_resources': [list(k) for k in sorted(changed)], 'applied': False,
        'files': {str(p): digest(p) for p in (chart, values_path, storage_path, BUNDLE / 'images.json')},
        'retention': 'Old PVC/export and Snapshot objects retained; new empty EFS subdirectory used'}
    (run.path / 'snapshot-install-review.json').write_text(json.dumps(review, indent=2))
    (BUNDLE / 'review.json').write_text(json.dumps(review, indent=2))
    run.result('snapshot-multigpu-upgrade-review', 'passed', **review)


def apply(run):
    review = json.loads((run.path / 'snapshot-install-review.json').read_text())
    if review['applied']:
        raise ValueError('Already applied')
    idle(run)
    for path, expected in review['files'].items():
        if digest(Path(path)) != expected:
            raise ValueError('Reviewed file changed: ' + path)
    deployed = next(r for r in json.loads(run.command(HELM + ['list', '-n', NS, '-o', 'json']).stdout) if r['name'] == RELEASE)
    if str(deployed['revision']) != str(review['before_revision']):
        raise ValueError('Helm revision changed after review')
    current = json.loads(run.command(HELM + ['get', 'values', RELEASE, '-n', NS, '-o', 'json']).stdout)
    if current != json.loads((run.path / 'before-values.json').read_text()):
        raise ValueError('Helm values changed after review')
    for check in ('snapshot-artifact-directory', 'snapshot-artifact-subpath'):
        if run.state.get('checks', {}).get(check, {}).get('status') != 'passed':
            raise ValueError('Missing artifact directory/I/O check')
    run.k('apply', '-f', str(BUNDLE / 'storage.yaml'))
    run.k('wait', 'pvc/snapshot-artifacts-cuinterpose', '-n', NS, '--for=jsonpath={.status.phase}=Bound', '--timeout=120s', timeout=135)
    run.command(review['command'], timeout=660)
    for target in ('deployment/dynamo-platform-snapshot-operator', 'daemonset/dynamo-platform-snapshot-agent'):
        run.k('rollout', 'status', target, '-n', NS, '--timeout=300s', timeout=315)
    review['applied'] = True
    (run.path / 'snapshot-install-review.json').write_text(json.dumps(review, indent=2))
    run.result('snapshot-multigpu-upgrade', 'passed', source_sha=SHA, scope='Existing release; Snapshot components only; one node; new EFS artifact store')


def status(run):
    for pod in run.get('get', 'pods', '-n', NS)['items']:
        if not pod['metadata']['name'].startswith(('dynamo-platform-snapshot-agent-', 'dynamo-platform-snapshot-operator-')):
            continue
        print(pod['metadata']['name'], pod['status'].get('phase'),
              json.dumps(pod['status'].get('containerStatuses', [])), flush=True)
        for c in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
            result = run.k('logs', pod['metadata']['name'], '-n', NS, '-c', c['name'], '--tail=30', check=False)
            (run.path / f'rollout-{pod["metadata"]["name"]}-{c["name"]}-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
            print(c['name'], result.stdout[-2200:] + result.stderr[-500:], flush=True)


def io(run):
    agent = next(p for p in run.get('get', 'pods', '-n', NS)['items']
        if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-') and p['spec'].get('nodeName') == NODE)
    script = '''for pid in $(pgrep -x pagebroker); do
 echo "PAGEBROKER $pid"; cat /proc/$pid/io
 ps -L -p "$pid" -o pid,tid,stat,wchan:32,comm
 for fd in /proc/$pid/fd/*; do printf '%s ' "$fd"; readlink "$fd"; done
 for tid in $(ps -L -p "$pid" -o tid=,stat= | awk '$2 ~ /D/ {print $1}' | head -3); do
  echo "BLOCKED THREAD $tid"; cat /proc/$pid/task/$tid/stack; cat /proc/$pid/task/$tid/syscall
 done
 echo "NFS MOUNTSTATS"
 awk '/mounted on \\/checkpoints with fstype nfs/ {capture=1} capture {print} capture && /^$/ {exit}' /proc/$pid/mountstats
done
echo "NFS KERNEL MESSAGES"
dmesg --time-format iso | awk '/nfs: server|NFS:|nfs4|efs-proxy/' | tail -30
'''
    result = run.k('exec', agent['metadata']['name'], '-n', NS, '-c', 'agent', '--', 'sh', '-c', script,
                   timeout=30, check=False)
    text = result.stdout + result.stderr
    (run.path / f'pagebroker-io-{time.time_ns()}.log').write_text(text)
    print(text, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'apply', 'status', 'io'))
    p.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    globals()[a.action](Run(a.run))


if __name__ == '__main__':
    main()
