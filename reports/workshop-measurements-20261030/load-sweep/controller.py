#!/usr/bin/env python3
"""Package, launch and observe the higher-load controller independently of VPN."""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tarfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'results/workshop-load-sweep-20261104-a1'
PREP = ROOT / 'results/workshop-load-sweep-controller-prep-20261104-a1'
CONTROL = ROOT / 'results/workshop-load-sweep-controller-20261104-a1'
NAME = 'kubecon-workshop-load-sweep-20261104-a1'
WORKSPACE = '/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace'
IMAGE = 'docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337'
LEASE = ROOT / '.local/workshop-load-sweep-20261104.gpu-lease'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5']


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def build():
    inputs = json.loads((RUN / 'inputs-sha256.json').read_text())
    for name, digest in inputs.items():
        assert sha(ROOT / name) == digest, name
    PREP.mkdir(exist_ok=False)
    payload = {name: ROOT / name for name in inputs}
    for path in [Path(__file__), RUN / 'inputs-sha256.json', RUN / 'campaign.sha256',
                 RUN / 'state.json', RUN / 'offline-validation.json']:
        payload[str(path.relative_to(ROOT))] = path
    fixed = {name: sha(path) for name, path in payload.items() if path.name not in ['state.json', 'LIVE_STATUS.json']}
    plan = {'schema': 1, 'run': str(RUN.relative_to(ROOT)), 'controller_name': NAME,
        'source_sha256': fixed, 'campaign_sha256': sha(RUN / 'campaign.json'),
        'stages': [{'action': action, 'timeout_seconds': timeout} for action, timeout in
            [('prepare', 1800), ('qualify-cpu', 10800), ('one-rr', 21600), ('two-rr', 21600), ('two-kv', 21600), ('finalize', 900)]],
        'scope': 'Routing only on cp-0198/cp-0942; preserve all Snapshot/global reservations and resources'}
    write(PREP / 'plan.json', plan)
    payload[str((PREP / 'plan.json').relative_to(ROOT))] = PREP / 'plan.json'
    records = {}
    for name, path in payload.items():
        assert path.is_file() and not path.is_symlink()
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert not name.startswith(('.local/', '.aws/', '.git/'))
        records[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    manifest = {'files': records, 'logical_root': str(ROOT), 'workspace': WORKSPACE, 'name': NAME,
        'image': IMAGE, 'controller': str(Path(__file__).relative_to(ROOT)),
        'plan': str((PREP / 'plan.json').relative_to(ROOT)), 'plan_sha256': sha(PREP / 'plan.json')}
    write(PREP / 'payload-manifest.json', manifest)
    with tarfile.open(PREP / 'payload.tar.gz', 'w:gz') as archive:
        for name, path in sorted(payload.items()):
            archive.add(path, arcname=name, recursive=False)
        raw = (PREP / 'payload-manifest.json').read_bytes()
        member = tarfile.TarInfo('payload-manifest.json');member.size = len(raw);member.mode = 0o600
        archive.addfile(member, io.BytesIO(raw))
    (PREP / 'payload.sha256').write_text(sha(PREP / 'payload.tar.gz') + '\n')
    print(json.dumps({'files': len(records), 'payload_bytes': (PREP / 'payload.tar.gz').stat().st_size,
        'plan_sha256': manifest['plan_sha256'], 'payload_sha256': sha(PREP / 'payload.tar.gz')}, indent=2))


BOOTSTRAP = r'''
import hashlib,io,json,os,subprocess,sys,tarfile
from pathlib import Path
data=sys.stdin.buffer.read(64000001);assert len(data)<=64000000 and hashlib.sha256(data).hexdigest()==EXPECTED_SHA
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace');assert w.is_dir()
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
 members=archive.getmembers();assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
 assert len({m.name for m in members})==len(members)
 manifest=json.loads(archive.extractfile('payload-manifest.json').read());assert manifest['workspace']==str(w)
 assert set(m.name for m in members)==set(manifest['files'])|{'payload-manifest.json'}
 assert subprocess.run(['docker','inspect',manifest['name']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20).returncode!=0,'Controller already exists; do not replay'
 verified={}
 for name,record in manifest['files'].items():
  raw=archive.extractfile(name).read();assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256']
  p=w/name;p.resolve().relative_to(w.resolve());assert not p.is_symlink()
  if p.exists():assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256'],'Refuse overwrite: '+name
  verified[name]=raw
 for name,raw in verified.items():
  p=w/name
  if not p.exists():
   p.parent.mkdir(parents=True,exist_ok=True)
   fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb') as stream:stream.write(raw)
 plan=w/manifest['plan'];assert hashlib.sha256(plan.read_bytes()).hexdigest()==manifest['plan_sha256']
 (plan.parent/'payload-manifest-staged.json').write_text(json.dumps(manifest,indent=2)+'\n')
 logical=manifest['logical_root']
 command=['docker','run','--detach','--pull=never','--name',manifest['name'],'--restart=no',
  '--network','host','--user','1000:1000','--cpus=2','--memory=4g','--cap-drop','ALL','--security-opt','no-new-privileges',
  '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH='+logical+'/.controller-deps',
  '--mount','type=bind,src='+str(w)+',dst='+logical,
  '--mount','type=bind,src=/usr/bin/kubectl,dst='+logical+'/.local/bin/kubectl,readonly',
  '--mount','type=bind,src=/home/ubuntu/.kube/config,dst='+logical+'/.local/kubeconfig,readonly',
  '--workdir',logical,'--entrypoint','/usr/local/bin/python',manifest['image'],
  '-B',logical+'/'+manifest['controller'],'run','--plan',logical+'/'+manifest['plan'],'--plan-sha256',manifest['plan_sha256']]
 result=subprocess.run(command,capture_output=True,text=True,timeout=45);assert result.returncode==0,result.stderr[-2000:]
 identifier=result.stdout.strip();state=json.loads(subprocess.check_output(['docker','inspect',identifier],timeout=20))[0]
 print(json.dumps({'controller_id':identifier,'state':state['State'],'plan_sha256':manifest['plan_sha256'],'files_verified':len(verified),'image_id':state['Image']}))
'''


def launch():
    expected = (PREP / 'payload.sha256').read_text().strip()
    assert sha(PREP / 'payload.tar.gz') == expected
    assert not (PREP / 'launch-attempt.json').exists(), 'Inspect any previous launch before retry'
    manifest = json.loads((PREP / 'payload-manifest.json').read_text())
    campaign = json.loads((RUN / 'campaign.json').read_text())
    LEASE.mkdir()
    write(LEASE / 'owner.json', {'agent': '/root/load_sweep_controller', 'run': str(RUN), 'acquired_at': now(),
        'controller_name': NAME, 'plan_sha256': manifest['plan_sha256'],
        'gpu_uuids_by_node': campaign['gpu_uuids_by_node'],
        'scope': 'Routing-only reservation; global Snapshot lease and cp-0124 unchanged'})
    began = now()
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(BOOTSTRAP.replace('EXPECTED_SHA', repr(expected)))],
        input=(PREP / 'payload.tar.gz').read_bytes(), capture_output=True, timeout=240)
    receipt = {'started_at': began, 'finished_at': now(), 'exit_code': result.returncode,
        'stderr': result.stderr.decode(errors='replace'), 'payload_sha256': expected,
        'launcher_sha256': sha(Path(__file__))}
    if result.returncode == 0:
        receipt['remote'] = json.loads(result.stdout)
    write(PREP / 'launch-attempt.json', receipt)
    assert result.returncode == 0, receipt['stderr'][-2500:]
    print(json.dumps(receipt['remote'], indent=2))


def execute(plan_path, expected):
    assert sha(plan_path) == expected
    plan = json.loads(plan_path.read_text())
    assert plan['controller_name'] == NAME and plan['run'] == str(RUN.relative_to(ROOT))
    CONTROL.mkdir(exist_ok=False)
    write(CONTROL / 'consumed-plan.json', {'at': now(), 'plan_sha256': expected, 'plan': plan})
    started = now();child = None
    def unchanged():
        for name, digest in plan['source_sha256'].items():
            assert sha(ROOT / name) == digest, 'Frozen source changed: ' + name
    def state(stage, **details):
        write(CONTROL / 'STATUS.json', {'at': now(), 'stage': stage, **details})
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Controller signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try:
        for stage in plan['stages']:
            unchanged()
            action = stage['action'];folder = CONTROL / action;folder.mkdir()
            argv = [str(ROOT / '.local/venv/bin/python'), '-B', str(HERE / 'campaign.py'), action, '--run', str(RUN)]
            write(folder / 'command.json', {'argv': argv, 'at': now(), 'timeout_seconds': stage['timeout_seconds']})
            with (folder / 'console.log').open('w') as stream:
                child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + stage['timeout_seconds']
                while child.poll() is None:
                    state(action, child_pid=child.pid)
                    if time.monotonic() >= deadline:
                        raise TimeoutError(action)
                    time.sleep(10)
                code = child.returncode;child = None
            write(folder / 'exit.json', {'exit_code': code, 'at': now()})
            assert code == 0, action + ' failed; inspect ' + str(folder / 'console.log')
        assert json.loads((RUN / 'qualification.json').read_text())['passed']
        assert not LEASE.exists()
        state('Completed, accepted and cleaned')
        write(CONTROL / 'exit.json', {'exit_code': 0, 'started_at': started, 'finished_at': now()})
    except BaseException as error:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL);child.wait()
        state('Stopped; preserve inputs and inspect failure', error=repr(error), traceback=traceback.format_exc())
        write(CONTROL / 'exit.json', {'exit_code': 1, 'started_at': started, 'finished_at': now(),
            'error': repr(error), 'scoped_lease_present': LEASE.exists()})
        raise


def probe(label):
    folder = ROOT / 'results/workshop-load-sweep-observations-20261104' / label
    folder.mkdir(parents=True, exist_ok=False)
    program = r'''
import datetime,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
r=w/'results/workshop-load-sweep-20261104-a1';c=w/'results/workshop-load-sweep-controller-20261104-a1'
v={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller_state':json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}','kubecon-workshop-load-sweep-20261104-a1'],timeout=20)), 'receipts':{}}
for p in [c/'STATUS.json',c/'exit.json',r/'LIVE_STATUS.json',r/'qualification.json',r/'cpu-qualification-a1/latest.json']:
 if p.exists():v['receipts'][str(p.relative_to(w))]=json.loads(p.read_text())
v['console_tails']={str(p.relative_to(w)):p.read_text()[-7000:] for p in c.glob('*/console.log')}
print(json.dumps(v))
'''
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(program)], capture_output=True, text=True, timeout=90)
    (folder / 'stderr.txt').write_text(result.stderr)
    assert result.returncode == 0, result.stderr[-2500:]
    value = json.loads(result.stdout);write(folder / 'status.json', value)
    print(json.dumps({'at': value['at'], 'controller': value['controller_state']['Status'],
        'status': {k: v.get('stage', v.get('exit_code')) for k, v in value['receipts'].items()
                   if k.endswith(('STATUS.json', 'LIVE_STATUS.json', 'exit.json'))}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'launch', 'run', 'probe'])
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--label')
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'build':
        build()
    elif args.action == 'launch':
        launch()
    elif args.action == 'run':
        execute(args.plan, args.plan_sha256)
    else:
        assert re_label(args.label)
        probe(args.label)


def re_label(value):
    import re
    return value and re.fullmatch(r'[a-z0-9-]+', value)


if __name__ == '__main__':
    main()
