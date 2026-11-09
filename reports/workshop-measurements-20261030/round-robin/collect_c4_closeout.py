#!/usr/bin/env python3
"""Read-only, inventory-complete C4 pullback into fresh verified local staging."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = r'''
import datetime,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-rr-20261103-resume02'
controller=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-controller-20261103'],timeout=20))[0]
assert controller['Id']=='5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411'
assert controller['State']['Status']=='exited' and controller['State']['ExitCode']==1
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
files={};inventories={}
def add(path):
 assert path.is_file() and not path.is_symlink(),str(path)
 path.resolve().relative_to(w.resolve())
 name=str(path.relative_to(w));assert not Path(name).is_absolute() and '..' not in Path(name).parts
 assert not name.startswith(('.local/','.aws/','.git/'))
 files[name]=path
def inventory(folder,name,wrapped=False):
 p=folder/name;value=json.loads(p.read_text());entries=value['sha256'] if wrapped else value
 add(p)
 for relative,expected in entries.items():
  assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
  f=folder/relative;add(f);assert sha(f)==expected,'Inventory mismatch: '+str(f)
 inventories[str(p.relative_to(w))]={'files_verified':len(entries),'sha256':sha(p)}
for arm in ['c4-r1-a1','c4-r2-a1']:
 folder=run/arm
 inventory(folder,'integrity-final.json',True)
 inventory(folder,'integrity.json')
 assert 'raw-artifacts.tar.gz' in json.loads((folder/'integrity-final.json').read_text())['sha256']
 inventory_export=next((folder/'raw').rglob('profile_export_aiperf.json'))
 export=json.loads(inventory_export.read_text())
 assert export['is_complete'] and not export['was_cancelled'] and export['metadata']['submission_valid']
 assert not export.get('error_summary') and not export.get('runtime_submission_invalid_reasons')
for folder in ['recovery-c4-r1-a1','resume-c4-r2-stable-a1']:
 inventory(run/folder,'integrity.json')
stage=run/'resume-c4-r2-stable-a1'
assert json.loads((stage/'exit.json').read_text())['exit_code']==0
cleanup=json.loads((stage/'cleanup-proof.json').read_text())
assert cleanup['verified'] and not any(cleanup[k] for k in ['gpu_pods','resourceclaims','graphs','gpu_lease_present'])
state=json.loads((run/'state.json').read_text())
assert state['checks']['rr-pair-c4']['status']=='completed'
for name in ['state.json','model-lock.json','upstream-c1-prerequisite.json',
             'rr-1-replica.yaml','rr-2-replica.yaml','pair-c4-a1-intent.json',
             'scaleout-c4-a1-analysis.json','scaleout-c4-a1-REPORT.md',
             'client-precache.json','client-environment.json','runtime-inspection.json',
             'continuation-a1/plan.json']:
 add(run/name)
for name in ['client-identity.json','plan.json','mx-outcome.json','STATUS.json','exit.json',
             'routing-c1/command.json','routing-c1/process.json','routing-c1/exit.json','routing-c1/console.log']:
 p=run/'continuation-stable-a2'/name
 if p.exists():add(p)
later=json.loads((run/'continuation-stable-a2/exit.json').read_text())
assert later['exit_code']==1 and 'routing-c1 exited 1' in later['error']
for pattern in ['check-rr-c4-*.json','check-rr-pair-c4-*.json']:
 for p in run.glob(pattern):add(p)
helper=w/'reports/workshop-measurements-20261030/round-robin/analyze.py';add(helper)
frozen=json.loads((run/'continuation-a1/plan.json').read_text())['source_sha256']
helper_name=str(helper.relative_to(w));assert sha(helper)==frozen[helper_name]
anchors={
 'c4-r1-a1/spec.json':'705ecb1d1aeb9c1a8898aa710c94511f799967dbd9bd8ac86d5ae8e457270508',
 'c4-r1-a1/profile.yaml':'d6bae50ed91ba2cb614de81b8da5282552c60302b1fa1f21eb20a2bb2c1b7098',
 'recovery-c4-r1-a1/remote-completion.json':'910d6cd3d34bbb9a26bc2291a6815580d239568e7e3bd0e80810e484599d5e9b',
 'upstream-c1-prerequisite.json':'4ad9179af589b220abaeca885f01ab23debc82eaf906cc37990c58d3754f5b9d',
 'continuation-a1/plan.json':'2aa9d50b382c1f0582a6a68bc53421b06bb58cee2a871587dd17810f6bff200f'}
for name,expected in anchors.items():assert sha(run/name)==expected,name
r1export=run/'c4-r1-a1/raw/c4-r1-a1/artifacts/profile_export_aiperf.json'
assert sha(r1export)=='710fe2a25e0e07a7ebb2ed8ec9bb675b773a4b2b4f5bd3d5e2a8a4928bc7d5c0'
def get(*parts):return json.loads(subprocess.check_output(['kubectl','--request-timeout=15s']+list(parts)+['-o','json'],timeout=25))
ns=state['namespace'];namespace=get('get','namespace',ns)
assert namespace['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
objects={k:get('get',k,'-n',ns)['items'] for k in ['pods','resourceclaims','dgd']}
def gpu(p):return any(c.get('resources',{}).get('claims') or any(k.startswith('nvidia.com/') and 'gpu' in k for k in c.get('resources',{}).get('limits',{})) for c in p['spec'].get('containers',[]))
assert not any(gpu(p) for p in objects['pods']) and not objects['resourceclaims'] and not objects['dgd']
manifest={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Original accepted C4 scale-out pair only; later routing failure preserved, no new GPU execution',
 'controller_id':controller['Id'],'controller_state':controller['State'],
 'c4_stage_exit':json.loads((stage/'exit.json').read_text()),'c4_cleanup':cleanup,
 'later_continuation_exit':later,'inventories':inventories,'known_anchors_verified':anchors,
 'live_namespace_audit':{'namespace':ns,'gpu_pods':[],'resourceclaims':[],'graphs':[],
   'retained_non_gpu_pods':[{'name':p['metadata']['name'],'phase':p.get('status',{}).get('phase')} for p in objects['pods']]},
 'files':{name:{'sha256':sha(p),'bytes':p.stat().st_size} for name,p in sorted(files.items())}}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 raw=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('pullback-manifest.json');info.size=len(raw);info.mode=0o600;archive.addfile(info,io.BytesIO(raw))
 for name,p in sorted(files.items()):archive.add(p,arcname=name,recursive=False)
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'results/workshop-c4-closeout-20261104-a1')
    args = parser.parse_args()
    os.umask(0o077)
    out = args.out.resolve()
    out.relative_to(ROOT / 'results')
    out.mkdir(exist_ok=False)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
               '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5', 'python3', '-c', shlex.quote(PROGRAM)]
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    archive_path = out / 'evidence.tar.gz'
    with archive_path.open('wb') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.PIPE, timeout=180)
    (out / 'stderr.txt').write_bytes(result.stderr)
    (out / 'transfer-receipt.json').write_text(json.dumps({'started_at': started,
        'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'exit_code': result.returncode,
        'collector_sha256': sha(Path(__file__)), 'scope': 'Remote reads and local staging only'}, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-2500:])
    dest = out / 'verified'
    dest.mkdir()
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
        assert len({m.name for m in members}) == len(members)
        assert sum(m.size for m in members) < 256 * 1024 * 1024
        manifest = json.loads(archive.extractfile('pullback-manifest.json').read())
        assert {m.name for m in members} == set(manifest['files']) | {'pullback-manifest.json'}
        archive.extractall(dest, members=members)
    for name, record in manifest['files'].items():
        p = dest / name
        assert p.stat().st_size == record['bytes'] and sha(p) == record['sha256'], name
    report = {'files_verified': len(manifest['files']), 'mismatches': 0,
        'archive_sha256': sha(archive_path), 'manifest_sha256': sha(dest / 'pullback-manifest.json'),
        'controller_state': manifest['controller_state'], 'c4_stage_exit': manifest['c4_stage_exit'],
        'inventories': manifest['inventories'], 'live_namespace_audit': manifest['live_namespace_audit'],
        'collector_sha256': sha(Path(__file__)), 'scope': manifest['scope']}
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
