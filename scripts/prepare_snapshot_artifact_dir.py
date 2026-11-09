#!/usr/bin/env python3
"""Prepare an owned EFS artifact directory and verify aligned direct I/O."""
import argparse
import copy
import json
from pathlib import Path
from feature_tests import BASE_IMAGE
from storage_tests import prepare
from testlib import Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True, type=Path)
    parser.add_argument('--subpath', action='store_true', help='Verify the proposed EFS export through an owned subdirectory PV/PVC')
    args = parser.parse_args()
    run = Run(args.review)
    review = json.loads((run.path / 'snapshot-install-review.json').read_text())
    expected = f'/feature-tests/{run.state["run_id"]}/snapshot-artifacts'
    if review['artifact_subdirectory'] != expected:
        raise ValueError('Artifact path must be owned by this review run')
    prepare(run)
    claim = 'feature-cache'
    if args.subpath:
        source = run.get('get', 'pv', 'dynamo-shared-pv')
        csi = copy.deepcopy(source['spec']['csi'])
        if ':' in csi['volumeHandle']:
            raise ValueError('Expected root filesystem source')
        csi['volumeHandle'] += ':' + expected
        pv_name = run.ns + '-snapshot-subdir'
        claim = 'snapshot-subdir-probe'
        run.apply([{'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': pv_name},
            'spec': {'capacity': {'storage': '256Gi'}, 'accessModes': ['ReadWriteMany'],
                'storageClassName': '', 'persistentVolumeReclaimPolicy': 'Retain',
                'claimRef': {'namespace': run.ns, 'name': claim}, 'csi': csi}},
            {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': claim},
                'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '',
                    'volumeName': pv_name, 'resources': {'requests': {'storage': '256Gi'}}}}], cluster_scope=True)
    code = '''import json,mmap,os
from pathlib import Path
root=Path('/efs')/os.environ['ARTIFACT_DIRECTORY'].lstrip('/')
root.mkdir(parents=True,exist_ok=True)
marker=root/'.workshop-owner.json'
owner={'run':os.environ['TEST_RUN']}
if marker.exists():
 assert json.loads(marker.read_text())==owner
else:
 marker.write_text(json.dumps(owner))
name=root/'aligned-direct-io-probe.bin'
report={'directory':str(root),'direct_io':False,'bytes':4096}
try:
 with mmap.mmap(-1,4096) as write_buffer,mmap.mmap(-1,4096) as read_buffer:
  write_buffer[:]=bytes(range(256))*16
  fd=os.open(name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_DIRECT,0o600)
  try:
   assert os.write(fd,write_buffer)==4096
   os.fsync(fd)
  finally:os.close(fd)
  fd=os.open(name,os.O_RDONLY|os.O_DIRECT)
  try:assert os.readv(fd,[read_buffer])==4096
  finally:os.close(fd)
  assert read_buffer[:]==write_buffer[:]
  report['direct_io']=True
 print(json.dumps(report))
finally:
 name.unlink(missing_ok=True)
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'snapshot-artifact-io-probe'},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 120, 'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': review['agent_node']},
            'containers': [{'name': 'probe', 'image': BASE_IMAGE, 'command': ['python3', '-c', code],
                'securityContext': {'runAsUser': 0},
                'env': [{'name': 'TEST_RUN', 'value': run.state['run_id']},
                        {'name': 'ARTIFACT_DIRECTORY', 'value': '' if args.subpath else expected}],
                'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'memory': '1Gi'}},
                'volumeMounts': [{'name': 'efs', 'mountPath': '/efs'}]}],
            'volumes': [{'name': 'efs', 'persistentVolumeClaim': {'claimName': claim}}]}}
    run.apply([pod])
    try:
        run.wait_pod('snapshot-artifact-io-probe', timeout=180, completed=True)
        report = json.loads(run.k('logs', 'snapshot-artifact-io-probe', '-n', run.ns).stdout)
        run.result('snapshot-artifact-subpath' if args.subpath else 'snapshot-artifact-directory', 'passed', **report,
                   export_path=expected,
                   scope='Owned artifact subdirectory and aligned 4 KiB O_DIRECT correctness, not Snapshot throughput')
    except Exception as error:
        logs = run.k('logs', 'snapshot-artifact-io-probe', '-n', run.ns, check=False)
        (run.path / 'snapshot-artifact-io.log').write_text(logs.stdout + logs.stderr)
        run.result('snapshot-artifact-subpath' if args.subpath else 'snapshot-artifact-directory', 'failed', error=str(error))
        raise
    finally:
        run.k('delete', 'pod', 'snapshot-artifact-io-probe', '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


if __name__ == '__main__':
    main()
