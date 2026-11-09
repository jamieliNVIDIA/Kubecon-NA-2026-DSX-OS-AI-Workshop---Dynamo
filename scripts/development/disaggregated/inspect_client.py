#!/usr/bin/env python3
"""Read-only metadata inspection for the exact expired AgentX client container.

Uses an existing read-only host-root view; creates no Kubernetes resources,
mounts, containerd snapshots, replacement containers or benchmark results.
Source files are not copied or adopted by this metadata probe.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from testlib import Run


HOST_PROGRAM = r'''import json,os,shutil,subprocess,sys
cid=sys.argv[1]
ctr=shutil.which('ctr')
out={'container_id':cid,'ctr_path':ctr,'metadata_only':True,'host_changes':False}
if ctr is None:
 print(json.dumps(out));raise SystemExit(0)
cmd=[ctr,'--address','/run/containerd/containerd.sock','--namespace','k8s.io','containers','info',cid]
p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
out['container_info_exit_code']=p.returncode
if p.returncode:
 out['error']=p.stderr[-2000:]
else:
 d=json.loads(p.stdout)
 spec=d.get('Spec',d.get('spec',{}))
 if isinstance(spec,str):
  try:spec=json.loads(spec)
  except json.JSONDecodeError:spec={}
 out['container_metadata']={k:d[k] for k in ('ID','id','Image','image','SnapshotKey','snapshot_key','Snapshotter','snapshotter','Labels','labels','CreatedAt','UpdatedAt') if k in d}
 out['oci_annotations']=spec.get('annotations',{}) if isinstance(spec,dict) else {}
 snapshot=d.get('SnapshotKey',d.get('snapshot_key'));snapshotter=d.get('Snapshotter',d.get('snapshotter','overlayfs'))
 if snapshot:
  for action in ('info','mounts'):
   action_args=(['/tmp/workshop-disagg-forensic-NOT-MOUNTED',snapshot] if action=='mounts' else [snapshot])
   # Without --temp, ctr prints the mount commands for <target> <key>; it
   # does not mount anything. The target is a literal unused print argument.
   cmd=[ctr,'--address','/run/containerd/containerd.sock','--namespace','k8s.io','snapshots','--snapshotter',snapshotter,action]+action_args
   q=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
   out['snapshot_'+action]={'exit_code':q.returncode,'stdout':q.stdout,'stderr':q.stderr}
   if action=='mounts':out['snapshot_'+action]['metadata_valid']=q.returncode==0 and not q.stdout.startswith('NAME:')
print(json.dumps(out))
'''


def source(inventory, run):
    items = json.loads(Path(inventory).read_text())['items']
    identity = json.loads((run.path / 'client-identity.json').read_text())
    pods = [p for p in items if p['metadata'].get('namespace') == run.ns and p['metadata']['name'] == 'rr-loadgen']
    if len(pods) != 1:
        raise ValueError('Need exactly the recorded original client in the recovered inventory.')
    pod = pods[0]
    if pod['metadata']['uid'] != identity['uid'] or pod['spec']['nodeName'] != identity['node']:
        raise ValueError('Original Pod/node identity changed.')
    statuses = pod['status']['containerStatuses']
    if len(statuses) != 1 or statuses[0].get('restartCount', 0):
        raise ValueError('Ambiguous client container history.')
    cid = statuses[0]['containerID']
    if not cid.startswith('containerd://') or len(cid.removeprefix('containerd://')) != 64:
        raise ValueError('Need the exact containerd container identity.')
    candidates = [p for p in items if p['spec'].get('nodeName') == identity['node'] and
        p['metadata'].get('namespace') == 'gpu-operator' and
        p['metadata']['name'].startswith('nvidia-container-toolkit-daemonset-')]
    if len(candidates) != 1:
        raise ValueError('Need one existing toolkit Pod on the exact node.')
    observer = candidates[0]
    containers = [c for c in observer['spec']['containers'] if c['name'] == 'nvidia-container-toolkit-ctr']
    if len(containers) != 1 or not any(m.get('mountPath') == '/host' and m.get('readOnly') is True
                                     for m in containers[0].get('volumeMounts', [])):
        raise ValueError('Observer does not expose a read-only host-root view.')
    return pod, cid[len('containerd://'):], observer


def inspect(run, inventory, attempt):
    if not attempt.isalnum():
        raise ValueError('Use an alphanumeric fresh attempt.')
    folder = run.path / ('cpu-forensics-' + attempt)
    folder.mkdir(exist_ok=False)
    pod, cid, observer = source(inventory, run)
    live = run.get('get', 'pod', observer['metadata']['name'], '-n', 'gpu-operator')
    if live['metadata']['uid'] != observer['metadata']['uid'] or live['spec'].get('nodeName') != pod['spec']['nodeName']:
        raise ValueError('Existing observer identity changed.')
    result = run.k('exec', observer['metadata']['name'], '-n', 'gpu-operator', '-c',
        'nvidia-container-toolkit-ctr', '--', 'sh', '-c',
        'exec chroot /host /usr/bin/python3 -c "$1" "$2"', 'inspect-owned-client', HOST_PROGRAM, cid,
        timeout=90)
    value = json.loads(result.stdout)
    value.update(source_pod_uid=pod['metadata']['uid'], source_node=pod['spec']['nodeName'],
                 source_namespace=run.ns, source_container_name='loadgen', observer_pod_uid=live['metadata']['uid'])
    (folder / 'metadata.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    inspect(Run(args.run), args.inventory, args.attempt)


if __name__ == '__main__':
    main()
