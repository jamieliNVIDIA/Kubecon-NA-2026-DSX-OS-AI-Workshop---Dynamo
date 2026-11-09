"""Preserve the failed baseline01 validator attempt and verify its cleanup."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-baseline-failed-pullback-20261104-a1'
PROGRAM=r'''
import datetime,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-mx-startup-20261104-baseline01'
controller=w/'results/workshop-baseline-controller-20261104-a1'
preparation=w/'results/workshop-baseline-controller-prep-20261104-a1'
docker=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-baseline-20261104-a1'],timeout=20))[0]
assert docker['Id']=='27f5e872befffac9634c048102433734de15df35ef85e30ea5dc7ab4392b63f1'
assert docker['State']['Status']=='exited' and docker['State']['ExitCode']==1,docker['State']
assert json.loads((controller/'exit.json').read_text())['exit_code']==1
assert json.loads((run/'state.json').read_text())['checks']['matched-baseline-startup']['error']=="AssertionError('Effective worker setting differs: startupProbe')"
cleanup=json.loads((run/'cleanup-proof.json').read_text())
assert cleanup['verified'] is True and cleanup['gpu_lease_absent'] is True
assert not (w/'.local/workshop-measurements-20261030.gpu-lease').exists()
ns=json.loads((run/'state.json').read_text())['namespace']
resources={k:json.loads(subprocess.check_output(['kubectl','--request-timeout=15s','get',k,'-n',ns,'-o','json'],timeout=25)) for k in ('pods','resourceclaims','dgd')}
assert not any(v['items'] for v in resources.values()),'Final pilot resources remain'
for name,expected in json.loads((run/'evidence-sha256.json').read_text()).items():
 assert hashlib.sha256((run/name).read_bytes()).hexdigest()==expected,name
files={}
for base in (run,controller,preparation):
 for p in base.rglob('*'):
  if p.is_file():
   assert not p.is_symlink()
   files[str(p.relative_to(w))]=p
manifest={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller_id':docker['Id'],'controller_state':docker['State'],'final_resource_counts':{k:len(v['items']) for k,v in resources.items()},'gpu_lease_absent':True,'files':{name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for name,p in sorted(files.items())}}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 raw=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('pullback-manifest.json');info.size=len(raw);info.mode=0o600;archive.addfile(info,io.BytesIO(raw))
 for name,p in sorted(files.items()):archive.add(p,arcname=name,recursive=False)
'''


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(PROGRAM)]
    archive_path=OUT/'evidence.tar.gz'
    with archive_path.open('wb') as out:
        result=subprocess.run(argv,stdout=out,stderr=subprocess.PIPE,timeout=180)
    (OUT/'stderr.txt').write_bytes(result.stderr)
    if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[-2500:])
    dest=OUT/'verified';dest.mkdir(exist_ok=False)
    with tarfile.open(archive_path) as archive:
        members=archive.getmembers()
        assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
        assert sum(m.size for m in members)<100000000
        assert len({m.name for m in members})==len(members)
        manifest=json.loads(archive.extractfile('pullback-manifest.json').read())
        assert {m.name for m in members}==set(manifest['files'])|{'pullback-manifest.json'}
        archive.extractall(dest,members=members)
    for name,record in manifest['files'].items():
        p=dest/name
        assert p.stat().st_size==record['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256'],name
    report={'files_verified':len(manifest['files']),'mismatches':0,'archive_sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest(),'controller_state':manifest['controller_state'],'gpu_lease_absent':manifest['gpu_lease_absent'],'final_resource_counts':manifest['final_resource_counts'],'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
