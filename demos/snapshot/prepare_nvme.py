#!/usr/bin/env python3
"""Read-only NVMe inspection and complete single-node Snapshot proposal; never apply/format."""
import argparse
import copy
import json
from pathlib import Path
import yaml

from prepare_dynamo_upgrade import resources
from snapshot_multigpu_upgrade import BUNDLE, HELM, NODE, NS, RELEASE, digest
from snapshot_storage_compare import execute
from testlib import ROOT, Run

OUTPUT = ROOT / 'configs/snapshot-nvme-demo-20261022'
CLAIM = 'snapshot-artifacts-nvme-cp0124'


def prepare(run):
    OUTPUT.mkdir(exist_ok=False)
    raw = execute(run, 'set -eu; lsblk -J -b -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL; '
                  'echo "NVME0 SIGNATURES (READ ONLY)"; blkid -p /dev/nvme0n1 || test "$?" = 2; '
                  'wipefs --no-act /dev/nvme0n1; '
                  'echo "NVME0 HOLDERS"; ls -l /sys/class/block/nvme0n1/holders; '
                  'echo "PROPOSED DIRECTORY"; ls -ld /proc/1/root/mnt/dynamo-snapshot 2>/dev/null || true')
    (run.path / 'nvme-identity-inspection.log').write_text(raw.stdout)
    disks = json.JSONDecoder().raw_decode(raw.stdout)[0]
    disk = next(d for d in disks['blockdevices'] if d['name'] == 'nvme0n1')
    if disk['model'].strip() != 'Amazon EC2 NVMe Instance Storage':
        raise ValueError('Candidate is not EC2 instance storage')
    if disk.get('fstype') or any(disk.get('mountpoints', [])) or disk.get('children'):
        raise ValueError('Candidate now has a filesystem, mount or partitions; revise the proposal')
    values = json.loads(run.command(HELM + ['get', 'values', RELEASE, '-n', NS, '-o', 'json']).stdout)
    if values != yaml.safe_load((BUNDLE / 'values.yaml').read_text()):
        raise ValueError('Live Helm values drifted from the reviewed Snapshot build')
    rollback = copy.deepcopy(values)
    values['snapshot']['storage'].update(type='pvc', pvc={'create': False, 'name': CLAIM, 'basePath': '/checkpoints'})
    values['snapshot']['operator'] = {'nodeSelector': {'kubernetes.io/hostname': NODE}}
    assert values['snapshot']['daemonset']['nodeSelector']['kubernetes.io/hostname'] == NODE
    manifests = [
        {'apiVersion': 'storage.k8s.io/v1', 'kind': 'StorageClass',
         'metadata': {'name': 'snapshot-nvme-local'}, 'provisioner': 'kubernetes.io/no-provisioner',
         'volumeBindingMode': 'WaitForFirstConsumer'},
        {'apiVersion': 'v1', 'kind': 'PersistentVolume',
         'metadata': {'name': 'dynamo-workshop-snapshot-nvme-cp0124'},
         'spec': {'capacity': {'storage': '1Ti'}, 'volumeMode': 'Filesystem',
                  'accessModes': ['ReadWriteOnce'], 'persistentVolumeReclaimPolicy': 'Retain',
                  'storageClassName': 'snapshot-nvme-local', 'local': {'path': '/mnt/dynamo-snapshot'},
                  'nodeAffinity': {'required': {'nodeSelectorTerms': [{'matchExpressions': [
                      {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': [NODE]}]}]}}}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
         'metadata': {'name': CLAIM, 'namespace': NS},
         'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'snapshot-nvme-local',
                  'volumeName': 'dynamo-workshop-snapshot-nvme-cp0124',
                  'resources': {'requests': {'storage': '1Ti'}}}}
    ]
    (OUTPUT / 'storage.yaml').write_text(yaml.safe_dump_all(manifests, sort_keys=False))
    (OUTPUT / 'values.yaml').write_text(yaml.safe_dump(values, sort_keys=False))
    (OUTPUT / 'rollback-values.yaml').write_text(yaml.safe_dump(rollback, sort_keys=False))
    (run.path / 'storage-server-dry-run.log').write_text(run.k('apply', '--dry-run=server', '-f', str(OUTPUT / 'storage.yaml')).stdout)
    chart = BUNDLE / 'dynamo-platform-1.5.1-snapshot-dev.tgz'
    before = run.command(HELM + ['template', RELEASE, str(chart), '-n', NS, '-f', str(BUNDLE / 'values.yaml')], timeout=120).stdout
    after = run.command(HELM + ['template', RELEASE, str(chart), '-n', NS, '-f', str(OUTPUT / 'values.yaml')], timeout=120).stdout
    (run.path / 'rendered-candidate.yaml').write_text(after)
    left, right = resources(before), resources(after)
    changed = [k for k in left.keys() | right.keys() if 'snapshot' in k[2] and left.get(k) != right.get(k)]
    expected = {'dynamo-platform-snapshot-agent', 'dynamo-platform-snapshot-operator', 'dynamo-platform-snapshot-config'}
    if {k[2] for k in changed} != expected:
        raise ValueError('Unexpected Snapshot chart change')
    review = {'applied': False, 'node': NODE, 'candidate_device': disk,
              'mount_path_prerequisite': '/mnt/dynamo-snapshot must already be a verified NVMe filesystem mount',
              'formatting_authorized': False, 'topology': 'Experimental single-node RWO variant of shared-RWX chart',
              'changed_snapshot_resources': [list(k) for k in changed],
              'schema_dry_run': 'StorageClass/PV/PVC server dry-run passed; no host-path or runtime qualification',
              'chart': str(chart.relative_to(ROOT)), 'chart_sha256': digest(chart),
              'files': {p.name: digest(p) for p in OUTPUT.glob('*.yaml')},
              'evidence': str(run.path.relative_to(ROOT))}
    (OUTPUT / 'review.json').write_text(json.dumps(review, indent=2)+'\n')
    print(json.dumps(review, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    prepare(Run(parser.parse_args().run))
