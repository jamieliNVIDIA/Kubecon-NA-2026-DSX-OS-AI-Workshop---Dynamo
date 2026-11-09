"""Stage the reviewed payload and start its detached, serialized CPU controller.

No credentials are copied. Existing remote files must match and are never
overwritten. The queued controller independently checks prior GPU cleanup.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]

REMOTE = r'''
import datetime,hashlib,io,json,os,subprocess,tarfile
from pathlib import Path
import sys
expected=EXPECTED_ARCHIVE_SHA
payload=sys.stdin.buffer.read(20000001)
assert len(payload)<=20000000 and hashlib.sha256(payload).hexdigest()==expected
workspace=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
assert workspace.is_dir()
with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
 members=archive.getmembers()
 assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
 assert len({m.name for m in members})==len(members)
 member_map={m.name:m for m in members}
 manifest_raw=archive.extractfile(member_map['text-only-payload-manifest.json']).read()
 manifest=json.loads(manifest_raw)
 assert manifest['physical_workspace']==str(workspace)
 assert manifest['logical_root']=='/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop'
 assert set(member_map)==set(manifest['files'])|{'text-only-payload-manifest.json'}
 existing=subprocess.run(['docker','inspect',manifest['controller_name']],capture_output=True,text=True,timeout=20)
 assert existing.returncode!=0,'Follow-up controller already exists; do not replay'
 prior=json.loads(subprocess.check_output(['docker','inspect',manifest['predecessor_name']],timeout=20))[0]
 assert prior['Id']==manifest['predecessor_id']
 assert prior['State']['Status']=='exited' and not prior['State']['Running']
 handoff=json.loads(archive.extractfile(member_map[manifest['predecessor_handoff_path']]).read())
 assert prior['State']['ExitCode']==handoff['accepted_terminal_exit_code']==1
 prior_exit=workspace/handoff['predecessor_exit_path']
 assert hashlib.sha256(prior_exit.read_bytes()).hexdigest()==handoff['predecessor_exit_sha256'],'Audited predecessor failure changed'
 assert Path('/home/ubuntu/.kube/config').is_file() and Path('/usr/bin/kubectl').is_file()
 for name,expected_sha in manifest['required_existing_sha256'].items():
  p=workspace/name
  assert p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==expected_sha,'Existing input differs: '+name
 verified={}
 for name,record in manifest['files'].items():
  raw=archive.extractfile(member_map[name]).read()
  assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256'],name
  p=workspace/name
  p.resolve().relative_to(workspace.resolve())
  assert not p.is_symlink(),name
  if p.exists():assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256'],'Refuse overwrite: '+name
  verified[name]=raw
 # Every byte and preexisting path is checked before the first file mutation.
 staged=[]
 for name,raw in verified.items():
  p=workspace/name
  if not p.exists():
   p.parent.mkdir(parents=True,exist_ok=True)
   descriptor=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(descriptor,'wb') as stream:stream.write(raw)
   staged.append(name)
 manifest_path=workspace/Path(manifest['plan_path']).parent/'payload-manifest-staged.json'
 if manifest_path.exists():assert manifest_path.read_bytes()==manifest_raw
 else:manifest_path.write_bytes(manifest_raw)
 plan=workspace/manifest['plan_path']
 assert hashlib.sha256(plan.read_bytes()).hexdigest()==manifest['plan_sha256']
 logical=manifest['logical_root']
 argv=['docker','run','--detach','--pull=never','--name',manifest['controller_name'],'--restart=no',
       '--network','host','--user','1000:1000','--cpus=2','--memory=4g','--cap-drop','ALL',
       '--security-opt','no-new-privileges','--env','PYTHONDONTWRITEBYTECODE=1',
       '--env','PYTHONPATH='+logical+'/.controller-deps',
       '--mount','type=bind,src='+str(workspace)+',dst='+logical,
       '--mount','type=bind,src=/usr/bin/kubectl,dst='+logical+'/.local/bin/kubectl,readonly',
       '--mount','type=bind,src=/home/ubuntu/.kube/config,dst='+logical+'/.local/kubeconfig,readonly',
       '--workdir',logical,'--entrypoint','/usr/local/bin/python',manifest['cpu_image'],
       '-B',logical+'/'+manifest['queue_script'],
       '--plan',logical+'/'+manifest['plan_path'],'--plan-sha256',manifest['plan_sha256']]
 result=subprocess.run(argv,capture_output=True,text=True,timeout=45)
 assert result.returncode==0,result.stderr[-2000:]
 controller_id=result.stdout.strip()
 current=json.loads(subprocess.check_output(['docker','inspect',controller_id],timeout=20))[0]
 record={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'controller_name':manifest['controller_name'],'controller_id':controller_id,
         'controller_state':current['State'],'cpu_image_id':current['Image'],
         'predecessor_id':prior['Id'],'predecessor_state':prior['State'],
         'plan_sha256':manifest['plan_sha256'],'payload_sha256':expected,
         'files_staged':staged,'files_verified':len(verified),
         'scope':'Detached CPU controller; new GPU work waits for prior success and independently verified cleanup'}
 receipt=workspace/Path(manifest['plan_path']).parent/'remote-launch.json'
 assert not receipt.exists()
 receipt.write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', choices=['02'], default='02')
    parser.add_argument('--generation', choices=['4', '5'], default='5')
    args = parser.parse_args()
    OUT = ROOT / ('results/workshop-textonly-controller-prep-20261103-a' + args.generation)
    payload = (OUT / 'payload.tar.gz').read_bytes()
    expected = (OUT / 'payload.sha256').read_text().strip()
    assert hashlib.sha256(payload).hexdigest() == expected
    manifest = json.loads((OUT / 'payload-manifest.json').read_text())
    assert hashlib.sha256((ROOT / manifest['plan_path']).read_bytes()).hexdigest() == manifest['plan_sha256']
    result_path = OUT / 'launch-attempt.json'
    assert not result_path.exists(), 'Preserve the prior launch attempt; inspect it before any retry'
    fence_path = ROOT / '.local/workshop-measurements-20261030.gpu-lease/owner.json'
    fence = json.loads(fence_path.read_text())
    assert fence['agent'] == '/root/stable_controller', 'Local execution fence belongs to another workflow'
    (OUT / 'local-fence-before-launch.json').write_text(json.dumps(fence, indent=2) + '\n')
    fence['authorized_followup'] = {'controller_name': manifest['controller_name'],
                                    'plan_sha256': manifest['plan_sha256'],
                                    'scope': 'Serialized follow-up after original remote queue and verified cleanup; no local GPU execution'}
    temporary = fence_path.with_name('owner.json.tmp')
    temporary.write_text(json.dumps(fence, indent=2) + '\n')
    temporary.replace(fence_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    program = REMOTE.replace('EXPECTED_ARCHIVE_SHA', repr(expected))
    argv = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', '-o', 'ForwardAgent=no',
            'ubuntu@3.238.63.5', 'python3', '-c', shlex.quote(program)]
    timed_out = False
    try:
        result = subprocess.run(argv, input=payload, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        result = subprocess.CompletedProcess(argv, 124, error.stdout or b'', error.stderr or b'')
    record = {'started_at': started, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'exit_code': result.returncode, 'payload_sha256': expected,
              'plan_sha256': manifest['plan_sha256'], 'stderr': result.stderr.decode(errors='replace'),
              'remote_state_unknown': timed_out,
              'launcher_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if result.returncode == 0:
        record['remote'] = json.loads(result.stdout)
    result_path.write_text(json.dumps(record, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError('Controller staging/launch failed: ' + record['stderr'][-2000:])
    print(json.dumps(record['remote'], indent=2))


if __name__ == '__main__':
    main()
