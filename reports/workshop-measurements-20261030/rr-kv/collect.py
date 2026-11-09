#!/usr/bin/env python3
"""Pull back a completed RR/KV campaign, verify it, then release its local fence."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = 'results/workshop-rrkv-20261104-a1'
CONTROL = 'results/workshop-rrkv-controller-20261104-a1'
PREP = 'results/workshop-rrkv-controller-prep-20261104-a1'
LEASE = ROOT / '.local/workshop-rrkv-20261104.gpu-lease'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4194304), b''):
            h.update(chunk)
    return h.hexdigest()


PROGRAM = r'''
import datetime,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
r=w/RUN;c=w/CONTROL;p=w/PREP
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(4194304),b''):h.update(chunk)
 return h.hexdigest()
controller=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-rrkv-20261104-a1'],timeout=20))[0]
assert controller['Id']==EXPECTED_CONTROLLER
assert controller['State']['Status']=='exited' and controller['State']['ExitCode']==0
assert json.loads((c/'exit.json').read_text())['exit_code']==0
qualification=json.loads((r/'qualification.json').read_text());assert qualification['passed'] and qualification['cleanup_verified'] and qualification['scoped_lease_absent']
assert not (w/'.local/workshop-rrkv-20261104.gpu-lease').exists()
files={};inventories={}
def add(path):
 assert path.is_file() and not path.is_symlink(),str(path)
 path.resolve().relative_to(w.resolve())
 name=str(path.relative_to(w));assert not Path(name).is_absolute() and '..' not in Path(name).parts
 assert not name.startswith(('.local/','.aws/','.git/'))
 files[name]=path
def inventory(folder,name,wrapped=False):
 path=folder/name;value=json.loads(path.read_text());entries=value['sha256'] if wrapped else value
 add(path)
 for rel,digest in entries.items():
  assert not Path(rel).is_absolute() and '..' not in Path(rel).parts
  f=folder/rel;add(f);assert sha(f)==digest,'Inventory mismatch: '+str(f)
 inventories[str(path.relative_to(w))]={'files_verified':len(entries),'sha256':sha(path)}
inventory(r,'evidence-sha256.json')
for concurrency in [1,4]:
 analysis=json.loads((r/f'routing-c{concurrency}-a1-analysis.json').read_text())
 assert analysis['paired_repetitions']==1 and len(analysis['arms'])==2
 assert analysis['arms'][1]['predicted_kv_hit_histogram_count']>0 and analysis['arms'][1]['predicted_kv_hit_histogram_sum']>0
 for mode in ['round-robin','kv']:
  arm=r/f'routing-c{concurrency}-{mode}-a1'
  inventory(arm,'integrity-final.json',True);inventory(arm,'integrity.json')
  assert json.loads((arm/'worker-qualification.json').read_text())['passed']
  assert json.loads((arm/'discovery-qualification.json').read_text())['passed']
  assert analysis['arms'][0 if mode=='round-robin' else 1]['cancelled_profile_records']==0
  export=list((arm/'raw').rglob('profile_export_aiperf.json'))
  export=[path for path in export if 'phases' not in path.parts];assert len(export)==1
  value=json.loads(export[0].read_text());assert value['is_complete'] and not value['was_cancelled'] and value['metadata']['submission_valid']
  assert not value.get('error_summary') and not value.get('runtime_submission_invalid_reasons')
for directory in [r,c,p]:
 for path in directory.rglob('*'):
  if path.is_file():add(path)
frozen=json.loads((r/'inputs-sha256.json').read_text())
for name,digest in frozen.items():
 path=w/name;add(path);assert sha(path)==digest,'Frozen source changed: '+name
for name,digest in json.loads((p/'plan.json').read_text())['source_sha256'].items():
 path=w/name;add(path);assert sha(path)==digest,name
def get(*parts):return json.loads(subprocess.check_output(['kubectl','--request-timeout=15s']+list(parts)+['-o','json'],timeout=25))
ns=json.loads((r/'campaign.json').read_text())['namespace']
namespace=get('get','namespace',ns);assert namespace['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
objects={kind:get('get',kind,'-n',ns)['items'] for kind in ['pods','resourceclaims','dgd']}
assert not any(objects.values())
assert sum(path.stat().st_size for path in files.values())<512*1024*1024
manifest={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller_id':controller['Id'],
 'controller_state':controller['State'],'qualification':qualification,'inventories':inventories,
 'scope':'Only the completed RR/KV campaign. Snapshot resources and global reservations were not changed.',
 'live_namespace_audit':{'namespace':ns,'pods':[],'resourceclaims':[],'dgd':[],'scoped_lease_absent':True},
 'files':{name:{'sha256':sha(path),'bytes':path.stat().st_size} for name,path in sorted(files.items())}}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 raw=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('pullback-manifest.json');info.size=len(raw);info.mode=0o600;archive.addfile(info,io.BytesIO(raw))
 for name,path in sorted(files.items()):archive.add(path,arcname=name,recursive=False)
'''


def collect(out):
    out = out.resolve()
    out.relative_to(ROOT / 'results')
    out.mkdir(exist_ok=False)
    launch = json.loads((ROOT / PREP / 'launch-attempt.json').read_text())
    assert launch['exit_code'] == 0
    expected_controller = launch['remote']['controller_id']
    program = ('RUN=' + repr(RUN) + '\nCONTROL=' + repr(CONTROL) + '\nPREP=' + repr(PREP)
               + '\nEXPECTED_CONTROLLER=' + repr(expected_controller) + '\n' + PROGRAM)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
               '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5', 'python3', '-c', shlex.quote(program)]
    began = dt.datetime.now(dt.timezone.utc).isoformat()
    archive_path = out / 'evidence.tar.gz'
    with archive_path.open('wb') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.PIPE, timeout=300)
    (out / 'stderr.txt').write_bytes(result.stderr)
    receipt = {'started_at': began, 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'exit_code': result.returncode, 'collector_sha256': sha(Path(__file__))}
    (out / 'transfer-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-3000:]
    dest = out / 'verified'
    dest.mkdir()
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
        assert len({m.name for m in members}) == len(members)
        assert sum(m.size for m in members) < 513 * 1024 * 1024
        manifest = json.loads(archive.extractfile('pullback-manifest.json').read())
        assert {m.name for m in members} == set(manifest['files']) | {'pullback-manifest.json'}
        for member in members:
            target = dest / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                for chunk in iter(lambda: source.read(4194304), b''):
                    output.write(chunk)
    for name, record in manifest['files'].items():
        path = dest / name
        assert path.stat().st_size == record['bytes'] and sha(path) == record['sha256'], name
    sys.path.insert(0, str(dest / 'reports/workshop-measurements-20261030/round-robin'))
    import analyze
    for concurrency in [1, 4]:
        pair = json.loads((dest / RUN / f'routing-c{concurrency}-a1-analysis.json').read_text())
        paths = [dest / RUN / f'routing-c{concurrency}-{mode}-a1' for mode in ['round-robin', 'kv']]
        assert analyze.normalized_profile(paths[0]) == analyze.normalized_profile(paths[1])
        for path, expected in zip(paths, pair['arms']):
            actual = analyze.load_arm(path)
            expected = dict(expected)
            actual.pop('accepted_export');expected.pop('accepted_export')
            assert actual == expected, 'Local analysis differs: ' + str(path)
    proof = {'passed': True, 'files_verified': len(manifest['files']), 'mismatches': 0,
             'archive_sha256': sha(archive_path), 'manifest_sha256': sha(dest / 'pullback-manifest.json'),
             'controller_id': expected_controller, 'live_namespace_audit': manifest['live_namespace_audit'],
             'local_analysis_reproduced': ['C1 RR/KV', 'C4 RR/KV'], 'collector_sha256': sha(Path(__file__))}
    (out / 'verification.json').write_text(json.dumps(proof, indent=2) + '\n')
    # The local fence is distinct from the remote per-arm lease and Snapshot's global lease.
    owner = json.loads((LEASE / 'owner.json').read_text())
    assert owner['agent'] == '/root/rrkv_controller' and owner['run'] == str(ROOT / RUN)
    assert owner['plan_sha256'] == launch['remote']['plan_sha256']
    (out / 'released-local-owner.json').write_text(json.dumps(owner, indent=2) + '\n')
    (LEASE / 'owner.json').unlink()
    LEASE.rmdir()
    print(json.dumps(proof, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'results/workshop-rrkv-pullback-20261104-a1')
    args = parser.parse_args()
    os.umask(0o077)
    collect(args.out)


if __name__ == '__main__':
    main()
