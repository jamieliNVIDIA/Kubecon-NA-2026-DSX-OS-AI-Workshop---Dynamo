#!/usr/bin/env python3
"""Package and transport one Snapshot controller on the existing jump host.

Build is offline and requires a fresh CPU-prepared run. Launch uses only the
jump host's existing kubectl/kubeconfig/dependencies. Collection is verified
into a fresh local directory; it never adopts state or releases reservations.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile

from scripts.source_paths import source_files

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337'
DEPS = '/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace/.controller-deps'
CONTROLLER = 'demos/snapshot/remote_controller.py'
OWNER = 'workshop-snapshot-dgd'
LEASE = '.local/workshop-measurements-20261030.gpu-lease/owner.json'
MAX_PAYLOAD = 64_000_000
MAX_MEMBER = 128 * 1024 * 1024
MAX_COLLECTION = 2 * 1024 * 1024 * 1024
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5']
RUN_INPUTS = ('demo.json', 'state.json', 'model-lock.json', 'deployment.json', 'deployment.yaml',
              'deployment-excerpt.yaml', 'runtime-patch.yaml', 'request.json', 'snapshot-dgd-spec.json',
              'nvme-agent-before.json', 'nvme-inspection.json')
IMAGE_INPUTS = ('controller-image.json', 'controller-image/Dockerfile', 'controller-image/packages.json')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write_new(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def safe_path(value, *, payload=False):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Unsafe archive path.')
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in ('.', '..') for part in path.parts):
        raise ValueError('Unsafe archive path: ' + value)
    if any(part in ('.local', '.aws', '.git') for part in path.parts) or path.name.lower() in (
            'kubeconfig', 'credentials', 'credentials.json', 'registry-auth.json', '.dockerconfigjson'):
        raise ValueError('Credential/private path excluded: ' + value)
    if payload and path.parts[0] not in ('scripts', 'configs', 'demos', 'results'):
        raise ValueError('Unexpected payload root.')
    return path


def run_path(value):
    value = Path(value).resolve()
    relative = value.relative_to(ROOT / 'results')
    if not relative.parts or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', value.name):
        raise ValueError('Use a named workshop run beneath results/.')
    return value


def prep_path(run):
    return Path(run) / 'remote-package'


def regular_payload_path(path):
    path = Path(path)
    relative = path.relative_to(ROOT)
    current = ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Payload source or ancestor may not be a symlink.')
    if not path.is_file():
        raise ValueError('Payload source must be a regular file.')
    return path


def runtime_provenance(run):
    """Accept only a completed owned image build from the original pinned base."""
    run = run_path(run)
    receipt_path = run / 'controller-image.json'
    if not receipt_path.exists():
        return {'image': IMAGE, 'base_image': IMAGE, 'kind': 'pinned_base', 'receipt_sha256': None}
    receipt = json.loads(regular_payload_path(receipt_path).read_text())
    image_id = receipt.get('image_id', '')
    if (receipt.get('schema') != 1 or receipt.get('status') != 'built' or receipt.get('base_image') != IMAGE
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', image_id)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', receipt.get('base_image_id', ''))
            or not isinstance(receipt.get('curl_version'), str) or not receipt['curl_version'].strip()
            or not isinstance(receipt.get('tag'), str) or not receipt['tag'].strip()):
        raise ValueError('Controller image receipt is incomplete, unbuilt or uses an unapproved base/image.')
    dockerfile = regular_payload_path(run / 'controller-image/Dockerfile')
    packages = regular_payload_path(run / 'controller-image/packages.json')
    if sha(dockerfile) != receipt.get('dockerfile_sha256') or sha(packages) != receipt.get('packages_sha256'):
        raise ValueError('Controller image Dockerfile/package hash differs from its build receipt.')
    json.loads(packages.read_text())
    return {'image': image_id, 'base_image': IMAGE, 'base_image_id': receipt['base_image_id'],
            'kind': 'owned_derived_image', 'receipt': str(receipt_path.relative_to(ROOT)),
            'receipt_sha256': sha(receipt_path), 'dockerfile_sha256': receipt['dockerfile_sha256'],
            'packages_sha256': receipt['packages_sha256'], 'curl_version': receipt['curl_version'],
            'tag': receipt['tag']}


def runtime_image(run):
    return runtime_provenance(run)['image']


def prepared_inputs(run):
    """Only source and explicitly safe run inputs; never CPU secret receipts."""
    run = run_path(run)
    data = json.loads(regular_payload_path(run / 'demo.json').read_text())
    state = json.loads(regular_payload_path(run / 'state.json').read_text())
    spec = json.loads(regular_payload_path(run / 'snapshot-dgd-spec.json').read_text())
    if (not data.get('prepared') or data.get('rehearsal') is not False or state.get('snapshot_dgd_submitted_at')
            or state.get('snapshot_dgd_uid') or data.get('initial_identity') or data.get('cleaned_at')
            or state.get('owner') != 'kubecon-dynamo-feature-tests'
            or state.get('checks', {}).get('model-staging', {}).get('status') != 'passed'
            or state['namespace'] != data['namespace'] or state['namespace'] != spec['namespace']):
        raise ValueError('Need a fresh, CPU-prepared live Snapshot run; no DGD submission or adoption.')
    reservation = json.loads((ROOT / LEASE).read_text())
    if reservation.get('agent') != OWNER or reservation.get('run') != str(run) or not reservation.get('acquired_at'):
        raise ValueError('The exact fresh run must hold its existing local Snapshot reservation.')
    payload = {}
    files = source_files(ROOT) + [path for path in (ROOT / 'scripts').rglob('*')
                                 if path.is_file() and path.suffix in {'.c', '.sh'}]
    for path in files:
        if 'transcripts' not in path.relative_to(ROOT).parts:
            payload[str(path.relative_to(ROOT))] = path
    for name, expected in data['source_hashes'].items():
        safe_path(name, payload=True)
        if sha(regular_payload_path(ROOT / name)) != expected:
            raise ValueError('Frozen source changed: ' + name)
        payload[name] = ROOT / name
    for name, expected in data['inputs'].items():
        if name not in RUN_INPUTS or sha(run / name) != expected:
            raise ValueError('Unexpected or changed run input: ' + name)
    for name in RUN_INPUTS:
        path = run / name
        if path.is_file():
            payload[str(path.relative_to(ROOT))] = path
    runtime = runtime_provenance(run)
    if runtime['kind'] == 'owned_derived_image':
        for name in IMAGE_INPUTS:
            path = regular_payload_path(run / name)
            payload[str(path.relative_to(ROOT))] = path
    if data.get('storage') == 'nvme' and (not (run / 'nvme-agent-before.json').is_file() or
            not (run / 'nvme-inspection.json').is_file() or not state.get('workshop_snapshot_nvme', {}).get('agent')):
        raise ValueError('CPU preparation must retain the pinned NVMe agent/disk inspection.')
    if CONTROLLER not in payload:
        raise ValueError('Snapshot remote controller source is missing.')
    for name, path in payload.items():
        safe_path(name, payload=True)
        regular_payload_path(path)
    return payload, data, state, spec, reservation


def verify_payload(archive_path, expected_sha256):
    archive_path = Path(archive_path)
    if archive_path.stat().st_size > MAX_PAYLOAD or sha(archive_path) != expected_sha256:
        raise ValueError('Payload hash/size differs.')
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if (len({m.name for m in members}) != len(members) or any(not m.isfile() for m in members)
                or any(m.size < 0 or m.size > MAX_MEMBER for m in members)
                or sum(m.size for m in members) > MAX_COLLECTION):
            raise ValueError('Invalid payload members or size.')
        for member in members:
            safe_path(member.name, payload=member.name != 'payload-manifest.json')
        manifest = json.load(archive.extractfile('payload-manifest.json'))
        if set(m.name for m in members) != set(manifest['files']) | {'payload-manifest.json'}:
            raise ValueError('Payload membership differs.')
        for name, record in manifest['files'].items():
            member = archive.getmember(name)
            if member.size != record['bytes'] or record.get('mode') not in (0o600, 0o700):
                raise ValueError('Payload file size/mode differs.')
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            if digest.hexdigest() != record['sha256']:
                raise ValueError('Payload file hash differs: ' + name)
    return manifest


def build(run, *, mode='full'):
    if mode not in ('full', 'prime'):
        raise ValueError('Choose full or prime.')
    run = run_path(run)
    payload, data, state, spec, reservation = prepared_inputs(run)
    runtime = runtime_provenance(run)
    prep = prep_path(run)
    prep.mkdir(exist_ok=False)
    tag = hashlib.sha256(str(run.relative_to(ROOT)).encode()).hexdigest()[:8]
    controller_name = 'kubecon-snapshot-' + run.name[:55] + '-' + tag
    workspace = '/home/ubuntu/workshop-measurements/' + run.name + '-' + tag + '-controller/workspace'
    run_relative = str(run.relative_to(ROOT))
    fixed = {name: sha(path) for name, path in payload.items() if not name.startswith(run_relative + '/')}
    run_hashes = {str(path.relative_to(run)): sha(path) for path in payload.values() if path.is_relative_to(run)}
    plan = {'schema': 1, 'run': run_relative, 'logical_root': str(ROOT), 'controller_name': controller_name,
        'mode': mode, 'source_sha256': fixed, 'run_input_sha256': run_hashes, 'reservation': reservation,
        'runtime': runtime,
        'namespace': state['namespace'], 'prime_timeout_seconds': 5400,
        'recording': 'demos/transcripts/live/04-snapshot-dgd/' + run.name,
        'raw_recording': 'results/' + run.name + '-remote-recording',
        'gpu_uuids': spec['settings']['gpu_uuids'], 'node': spec['settings']['node'],
        'scope': 'Fresh same-node Snapshot only. Stock source deadline, no platform changes, no old checkpoint adoption.'}
    write_new(prep / 'plan.json', plan)
    payload[str((prep / 'plan.json').relative_to(ROOT))] = prep / 'plan.json'
    records = {name: {'sha256': sha(path), 'bytes': path.stat().st_size,
                      'mode': 0o700 if path.stat().st_mode & 0o100 else 0o600} for name, path in payload.items()}
    manifest = {'schema': 1, 'files': records, 'logical_root': str(ROOT), 'workspace': workspace,
        'name': controller_name, 'image': runtime['image'], 'base_image': IMAGE, 'runtime': runtime,
        'dependencies': DEPS, 'controller': CONTROLLER,
        'plan': str((prep / 'plan.json').relative_to(ROOT)), 'plan_sha256': sha(prep / 'plan.json')}
    write_new(prep / 'payload-manifest.json', manifest)
    with tarfile.open(prep / 'payload.tar.gz', 'w:gz') as archive:
        for name, path in sorted(payload.items()):
            archive.add(path, arcname=name, recursive=False)
        raw = (prep / 'payload-manifest.json').read_bytes()
        member = tarfile.TarInfo('payload-manifest.json');member.size = len(raw);member.mode = 0o600
        archive.addfile(member, io.BytesIO(raw))
    if (prep / 'payload.tar.gz').stat().st_size > MAX_PAYLOAD:
        raise ValueError('Payload exceeds bounded source-bundle size.')
    (prep / 'payload.sha256').write_text(sha(prep / 'payload.tar.gz') + '\n')
    return {'files': len(records), 'payload_bytes': (prep / 'payload.tar.gz').stat().st_size,
            'payload_sha256': sha(prep / 'payload.tar.gz'), 'plan_sha256': manifest['plan_sha256'],
            'controller_name': controller_name, 'workspace': workspace, 'mode': mode, 'image': runtime['image']}


BOOTSTRAP = r'''
import hashlib,io,json,os,subprocess,sys,tarfile
from pathlib import Path,PurePosixPath
os.umask(0o077)
data=sys.stdin.buffer.read(64000001)
if len(data)>64000000 or hashlib.sha256(data).hexdigest()!=EXPECTED_SHA:raise ValueError('Payload hash/size differs')
def safe(name):
 p=PurePosixPath(name)
 if not name or p.is_absolute() or str(p)!=name or '\\' in name or '..' in p.parts or any(x in p.parts for x in ('.local','.aws','.git')):raise ValueError('Unsafe payload path')
 if p.name.lower() in ('kubeconfig','credentials','credentials.json','registry-auth.json','.dockerconfigjson'):raise ValueError('Private input forbidden')
 return p
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
 members=archive.getmembers()
 if any(not m.isfile() or m.size>134217728 for m in members) or len({m.name for m in members})!=len(members):raise ValueError('Invalid payload member')
 for m in members:safe(m.name)
 manifest=json.loads(archive.extractfile('payload-manifest.json').read())
 if set(m.name for m in members)!=set(manifest['files'])|{'payload-manifest.json'}:raise ValueError('Payload membership differs')
 w=Path(manifest['workspace']);logical=manifest['logical_root']
 if not str(w).startswith('/home/ubuntu/workshop-measurements/') or w.name!='workspace' or not Path(logical).is_absolute():raise ValueError('Wrong isolated workspace')
 if manifest['image']!=EXPECTED_IMAGE or manifest.get('base_image')!=EXPECTED_BASE_IMAGE or manifest['dependencies']!=EXPECTED_DEPS:raise ValueError('Unreviewed runtime/dependencies')
 if subprocess.run(['docker','inspect',manifest['name']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20).returncode==0:raise ValueError('Controller exists; never replay')
 for path in ('/usr/bin/kubectl','/home/ubuntu/.kube/config'):
  if not Path(path).is_file():raise ValueError('Existing host client/credentials unavailable')
 if not Path(manifest['dependencies']).is_dir():raise ValueError('Existing controller dependencies unavailable')
 subprocess.run(['docker','image','inspect',manifest['image']],check=True,stdout=subprocess.DEVNULL,timeout=20)
 verified={}
 for name,record in manifest['files'].items():
  safe(name);raw=archive.extractfile(name).read()
  if len(raw)!=record['bytes'] or hashlib.sha256(raw).hexdigest()!=record['sha256'] or record.get('mode') not in (384,448):raise ValueError('Payload file mismatch: '+name)
  p=w/name;p.resolve().relative_to(w.resolve())
  if p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent!=w.parent):raise ValueError('Symlink target forbidden')
  if p.exists() and (not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']):raise ValueError('Refuse overwrite: '+name)
  verified[name]=raw
 if hashlib.sha256(verified[manifest['plan']]).hexdigest()!=manifest['plan_sha256']:raise ValueError('Plan hash differs')
 plan=json.loads(verified[manifest['plan']])
 if plan['logical_root']!=logical or plan['controller_name']!=manifest['name']:raise ValueError('Plan identity differs')
 if plan.get('runtime')!=manifest.get('runtime') or plan['runtime']['image']!=manifest['image']:raise ValueError('Runtime provenance differs')
 runtime=manifest['runtime']
 if runtime.get('receipt_sha256'):
  receipt_raw=verified[runtime['receipt']]
  if hashlib.sha256(receipt_raw).hexdigest()!=runtime['receipt_sha256']:raise ValueError('Runtime build receipt changed')
  receipt=json.loads(receipt_raw);run_path=plan['run']
  if receipt['base_image']!=EXPECTED_BASE_IMAGE or receipt['image_id']!=manifest['image'] or receipt['status']!='built':raise ValueError('Runtime receipt identity differs')
  if hashlib.sha256(verified[run_path+'/controller-image/Dockerfile']).hexdigest()!=receipt['dockerfile_sha256'] or hashlib.sha256(verified[run_path+'/controller-image/packages.json']).hexdigest()!=receipt['packages_sha256']:raise ValueError('Runtime build inputs changed')
 if plan['reservation']['agent']!='workshop-snapshot-dgd' or plan['reservation']['run']!=logical+'/'+plan['run']:raise ValueError('Wrong mirrored reservation')
 w.mkdir(parents=True,exist_ok=True)
 for name,raw in verified.items():
  p=w/name
  if not p.exists():
   p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('xb') as stream:stream.write(raw)
   p.chmod(manifest['files'][name]['mode'])
 local=w/'.local';(local/'bin').mkdir(parents=True,exist_ok=True);(local/'venv/bin').mkdir(parents=True,exist_ok=True)
 for name in ('bin/kubectl','kubeconfig'):
  p=local/name
  if not p.exists():p.touch(mode=0o600)
 python=local/'venv/bin/python'
 if not python.is_symlink() and not python.exists():python.symlink_to('/usr/local/bin/python')
 if not python.is_symlink() or os.readlink(python)!='/usr/local/bin/python':raise ValueError('Unexpected private Python launcher')
 lease=local/'workshop-measurements-20261030.gpu-lease';lease.mkdir(exist_ok=True)
 owner=lease/'owner.json'
 if owner.exists():
  if json.loads(owner.read_text())!=plan['reservation']:raise ValueError('Foreign mirrored reservation')
 else:
  with owner.open('x') as stream:stream.write(json.dumps(plan['reservation'],indent=2)+'\n')
 (w/'.controller-deps').mkdir(exist_ok=True)
 staged=w/manifest['plan'];staged.parent.joinpath('payload-manifest-staged.json').write_text(json.dumps(manifest,indent=2)+'\n')
 command=['docker','run','--detach','--pull=never','--name',manifest['name'],'--restart=no','--network','host','--user','1000:1000','--cpus=2','--memory=4g','--cap-drop','ALL','--security-opt','no-new-privileges',
 '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH='+logical+'/.controller-deps','--env','NVIDIA_VISIBLE_DEVICES=void',
 '--mount','type=bind,src='+str(w)+',dst='+logical,
 '--mount','type=bind,src=/usr/bin/kubectl,dst='+logical+'/.local/bin/kubectl,readonly',
 '--mount','type=bind,src=/home/ubuntu/.kube/config,dst='+logical+'/.local/kubeconfig,readonly',
 '--mount','type=bind,src='+manifest['dependencies']+',dst='+logical+'/.controller-deps,readonly',
 '--workdir',logical,'--entrypoint','/usr/local/bin/python',manifest['image'],'-B','-m',manifest['controller'][:-3].replace('/','.'),'run','--plan',logical+'/'+manifest['plan'],'--plan-sha256',manifest['plan_sha256']]
 import_probe="import subprocess,sys;sys.path.insert(0,"+repr(logical)+");import demos.snapshot.dgd_demo as workshop_snapshot_dgd_demo,demos.snapshot.remote_controller as workshop_snapshot_remote_controller;print(subprocess.check_output(['curl','--version'],text=True,timeout=5).splitlines()[0]);print('Snapshot controller imports passed')"
 probe=['docker','run','--rm','--pull=never','--network=none','--user','1000:1000','--cpus=0.25','--memory=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH='+logical+'/.controller-deps','--mount','type=bind,src='+str(w)+',dst='+logical+',readonly','--mount','type=bind,src='+manifest['dependencies']+',dst='+logical+'/.controller-deps,readonly','--workdir',logical,'--entrypoint','/usr/local/bin/python',manifest['image'],'-B','-c',import_probe]
 tested=subprocess.run(probe,capture_output=True,text=True,timeout=30)
 if tested.returncode:raise RuntimeError('Frozen source dependency probe failed before GPU actions: '+tested.stderr[-2000:])
 result=subprocess.run(command,capture_output=True,text=True,timeout=45)
 if result.returncode:raise RuntimeError(result.stderr[-2000:])
 identifier=result.stdout.strip();inspection=json.loads(subprocess.check_output(['docker','inspect',identifier],timeout=20))[0]
 print(json.dumps({'controller_id':identifier,'state':inspection['State'],'plan_sha256':manifest['plan_sha256'],'files_verified':len(verified),'image_id':inspection['Image'],'workspace':str(w),'source_import_probe':tested.stdout.strip()}))
'''


def package_manifest(run):
    run = run_path(run)
    prep = prep_path(run)
    manifest = json.loads((prep / 'payload-manifest.json').read_text())
    expected = (prep / 'payload.sha256').read_text().strip()
    if sha(prep / 'payload.tar.gz') != expected or sha(prep / 'plan.json') != manifest['plan_sha256']:
        raise ValueError('Frozen package or plan hash changed.')
    if verify_payload(prep / 'payload.tar.gz', expected) != manifest:
        raise ValueError('Payload manifest differs from its saved manifest.')
    return run, prep, manifest, expected


def launch(run):
    run, prep, manifest, expected = package_manifest(run)
    for name, record in manifest['files'].items():
        if sha(ROOT / name) != record['sha256']:
            raise ValueError('A source or prepared input changed after build: ' + name)
    reservation = json.loads((ROOT / LEASE).read_text())
    plan = json.loads((prep / 'plan.json').read_text())
    runtime = runtime_provenance(run)
    if runtime != manifest.get('runtime') or runtime != plan.get('runtime') or runtime['image'] != manifest['image']:
        raise ValueError('Controller runtime receipt changed after package freeze.')
    if reservation != plan['reservation']:
        raise ValueError('Local reservation changed after build.')
    write_new(prep / 'launch-intent.json', {'at': now(), 'payload_sha256': expected, 'plan_sha256': manifest['plan_sha256']})
    program = (BOOTSTRAP.replace('EXPECTED_SHA', repr(expected)).replace('EXPECTED_BASE_IMAGE', repr(IMAGE))
               .replace('EXPECTED_IMAGE', repr(runtime['image'])).replace('EXPECTED_DEPS', repr(DEPS)))
    started = now()
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(program)], input=(prep / 'payload.tar.gz').read_bytes(),
                            capture_output=True, timeout=240)
    receipt = {'started_at': started, 'finished_at': now(), 'exit_code': result.returncode,
               'payload_sha256': expected, 'stderr': result.stderr.decode(errors='replace'),
               'launcher_sha256': sha(__file__)}
    if result.returncode == 0:
        receipt['remote'] = json.loads(result.stdout)
    write_new(prep / 'launch-result.json', receipt)
    if result.returncode:
        raise RuntimeError('Launch failed or uncertain; inspect intent/results before any new attempt: ' + receipt['stderr'][-2000:])
    return receipt


def remote_program(manifest, body):
    return "manifest=" + repr(manifest) + "\n" + body


STATUS = r'''
import datetime,hashlib,json,subprocess
from pathlib import Path
w=Path(manifest['workspace']);raw=(w/manifest['plan']).read_bytes()
if hashlib.sha256(raw).hexdigest()!=manifest['plan_sha256']:raise ValueError('Remote plan hash differs')
plan=json.loads(raw);run=w/plan['run']
state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',manifest['name']],timeout=20))
files={}
for name in ('remote-controller.json','remote-controller-plan.json','demo.json','state.json'):
 p=run/name
 if p.is_file():files[name]=json.loads(p.read_text())
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller_state':state,'files':files}))
'''


def status(run):
    _, prep, manifest, _ = package_manifest(run)
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(remote_program(manifest, STATUS))],
                            capture_output=True, text=True, timeout=90)
    folder = prep / 'observations';folder.mkdir(exist_ok=True)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr}
    if not result.returncode:
        receipt['remote'] = json.loads(result.stdout)
    write_new(folder / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode:
        raise RuntimeError('Read-only status failed: ' + result.stderr[-2000:])
    return receipt['remote']


COLLECT = r'''
import hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
w=Path(manifest['workspace']);raw=(w/manifest['plan']).read_bytes()
if hashlib.sha256(raw).hexdigest()!=manifest['plan_sha256']:raise ValueError('Remote plan hash differs')
plan=json.loads(raw)
state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',manifest['name']],timeout=20))
if state.get('Running'):raise ValueError('Controller is still writing; use status and collect after exit')
roots={'run':w/plan['run'],'recording':w/plan['recording']}
capture=roots['recording']/'capture.json'
if capture.is_file():
 proof=json.loads(capture.read_text())
 if proof.get('run')!=plan['logical_root']+'/'+plan['run'] or proof.get('demo')!='04-snapshot-dgd':raise ValueError('Recording provenance differs')
 raw_relative=Path(proof['raw_output']).relative_to(Path(plan['logical_root']))
 if (str(raw_relative)!=plan['raw_recording'] and raw_relative.parts[:2]!=('results','demo-recordings')) or '..' in raw_relative.parts:raise ValueError('Unowned raw recording path')
 roots['recording-private']=w/raw_relative
files={};paths={};total=0
for prefix,root in roots.items():
 if not root.exists():continue
 root.resolve().relative_to(w.resolve())
 if root.is_symlink() or not root.is_dir():raise ValueError('Unexpected result root')
 for p in root.rglob('*'):
  if p.is_symlink():raise ValueError('Result symlink forbidden')
  if not p.is_file():continue
  name=prefix+'/'+str(p.relative_to(root));size=p.stat().st_size;total+=size
  if size>134217728 or total>2147483648:raise ValueError('Result size bound exceeded')
  digest=hashlib.sha256()
  with p.open('rb') as stream:
   for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
  files[name]={'sha256':digest.hexdigest(),'bytes':size};paths[name]=p
collection={'schema':1,'run':plan['run'],'controller_name':manifest['name'],'plan_sha256':manifest['plan_sha256'],'docker_state':state,'files':files}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 for name,p in sorted(paths.items()):archive.add(p,arcname=name,recursive=False)
 raw=(json.dumps(collection,indent=2)+'\n').encode();member=tarfile.TarInfo('collection-manifest.json');member.size=len(raw);member.mode=0o600;archive.addfile(member,io.BytesIO(raw))
'''


def verify_collection(archive_path, expected):
    """Validate the whole stream before creating any destination files."""
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len({m.name for m in members}) != len(members) or any(not m.isfile() for m in members):
            raise ValueError('Duplicate or non-regular collection member.')
        for member in members:
            safe_path(member.name)
            if member.size < 0 or member.size > MAX_MEMBER:
                raise ValueError('Collection member exceeds size bound.')
        manifest_member = archive.getmember('collection-manifest.json')
        manifest = json.load(archive.extractfile(manifest_member))
        if any(manifest.get(key) != expected[key] for key in ('run', 'controller_name', 'plan_sha256')):
            raise ValueError('Collection belongs to another run/controller/plan.')
        if manifest.get('docker_state', {}).get('Running'):
            raise ValueError('Live controller result is not a stable collection.')
        if set(m.name for m in members) != set(manifest['files']) | {'collection-manifest.json'}:
            raise ValueError('Collection membership differs.')
        if sum(m.size for m in members) > MAX_COLLECTION:
            raise ValueError('Collection exceeds total size bound.')
        # Keep decompression forward-only across data members. Manifest insertion
        # order need not match physical TAR order; backwards gzip seeks otherwise
        # repeatedly decompress the archive and make large collections quadratic.
        for member in members:
            name = member.name
            if name == 'collection-manifest.json':
                continue
            record = manifest['files'][name]
            path = safe_path(name)
            if path.parts[0] not in ('run', 'recording', 'recording-private'):
                raise ValueError('Unexpected collection root.')
            if member.size != record['bytes']:
                raise ValueError('Collection size differs: ' + name)
            digest = hashlib.sha256()
            stream = archive.extractfile(member)
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            if digest.hexdigest() != record['sha256']:
                raise ValueError('Collection hash differs: ' + name)
    return manifest


def extract_collection(archive_path, output, expected):
    output = Path(output)
    if output.exists():
        raise ValueError('Collection output already exists; never overwrite.')
    manifest = verify_collection(archive_path, expected)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive.getmembers():
            target = output / member.name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open('xb') as stream:
                source = archive.extractfile(member)
                digest = hashlib.sha256()
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
                    stream.write(block)
            if member.name != 'collection-manifest.json' and digest.hexdigest() != manifest['files'][member.name]['sha256']:
                raise ValueError('Collection changed between verification and extraction.')
            target.chmod(0o400)
    write_new(output / 'collection-verification.json', {'status': 'verified', 'at': now(),
        'archive_sha256': sha(archive_path), 'files': len(manifest['files']),
        'run': manifest['run'], 'controller_name': manifest['controller_name'],
        'plan_sha256': manifest['plan_sha256'], 'state_adopted': False, 'local_reservation_released': False})
    return manifest


def collect(run, output):
    run, prep, manifest, _ = package_manifest(run)
    output = Path(output).resolve()
    output.relative_to(ROOT / 'results')
    if output.exists() or output == run or run in output.parents or output in run.parents:
        raise ValueError('Use a fresh separate results/ collection directory.')
    output.parent.mkdir(parents=True, exist_ok=True)
    archive_path = output.with_name(output.name + '.tar.gz')
    stderr_path = output.with_name(output.name + '.stderr.txt')
    started = now()
    with archive_path.open('xb') as archive, stderr_path.open('x') as errors:
        result = subprocess.run(SSH + ['python3', '-c', shlex.quote(remote_program(manifest, COLLECT))],
                                stdout=archive, stderr=errors, timeout=600)
    receipt = {'started_at': started, 'finished_at': now(), 'exit_code': result.returncode,
               'archive_sha256': sha(archive_path), 'archive_bytes': archive_path.stat().st_size}
    write_new(output.with_name(output.name + '.transport.json'), receipt)
    if result.returncode:
        raise RuntimeError('Collection transport failed; preserve archive/stderr and choose a fresh attempt.')
    archive_path.chmod(0o400)
    expected = {'run': str(run.relative_to(ROOT)), 'controller_name': manifest['name'], 'plan_sha256': manifest['plan_sha256']}
    return extract_collection(archive_path, output, expected)


PREFLIGHT = r'''
import datetime,json,os,subprocess
from pathlib import Path
paths={'kubectl':'/usr/bin/kubectl','existing_kubeconfig':'/home/ubuntu/.kube/config','dependencies':EXPECTED_DEPS}
for name,path in paths.items():
 p=Path(path)
 if not p.exists() or not os.access(path,os.R_OK):raise ValueError('Missing/read-protected existing dependency: '+name)
 if name=='kubectl' and not os.access(path,os.X_OK):raise ValueError('kubectl is not executable')
image=json.loads(subprocess.check_output(['docker','image','inspect',EXPECTED_IMAGE],timeout=20))[0]
probe="import json,subprocess,yaml; print(json.dumps({'pyyaml_version':yaml.__version__,'curl':subprocess.check_output(['curl','--version'],text=True,timeout=5).splitlines()[0]}))"
probe_command=['docker','run','--rm','--pull=never','--network=none','--user','1000:1000','--cpus=0.25','--memory=256m','--cap-drop=ALL','--security-opt=no-new-privileges','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONPATH=/opt/controller-deps','--mount','type=bind,src='+EXPECTED_DEPS+',dst=/opt/controller-deps,readonly','--entrypoint','/usr/local/bin/python',EXPECTED_IMAGE,'-B','-c',probe]
runtime=json.loads(subprocess.check_output(probe_command,text=True,timeout=30))
client=subprocess.run(['/usr/bin/kubectl','--kubeconfig=/home/ubuntu/.kube/config','--request-timeout=10s','get','--raw=/readyz'],capture_output=True,text=True,timeout=25)
if client.returncode:raise RuntimeError('Existing remote API client failed: '+client.stderr[-1000:])
if not (Path(EXPECTED_DEPS)/'yaml/__init__.py').is_file():raise ValueError('Existing PyYAML dependency missing')
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'image_id':image['Id'],'api_readyz':client.stdout.strip(),'dependencies_readable':True,'credentials_copied':False,'cluster_mutation':False,'ephemeral_cpu_probe':True,'runtime':runtime}))
'''


def preflight(run):
    run = run_path(run)
    runtime = runtime_provenance(run)
    program = PREFLIGHT.replace('EXPECTED_DEPS', repr(DEPS)).replace('EXPECTED_IMAGE', repr(runtime['image']))
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(program)], capture_output=True, text=True, timeout=90)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr,
               'cluster_read_only': True, 'runtime': runtime}
    if not result.returncode:
        receipt['remote'] = json.loads(result.stdout)
    write_new(run / ('remote-preflight-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode:
        raise RuntimeError('Read-only remote preflight failed: ' + result.stderr[-1500:])
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'build', 'launch', 'status', 'collect'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--mode', choices=('full', 'prime'), default='full')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'preflight':
        value = preflight(args.run)
    elif args.action == 'build':
        value = build(args.run, mode=args.mode)
    elif args.action == 'launch':
        value = launch(args.run)
    elif args.action == 'status':
        remote = status(args.run)
        files = remote['files']
        value = {'at': remote['at'], 'controller_state': remote['controller_state'],
                 'controller': files.get('remote-controller.json'),
                 'namespace': files.get('state.json', {}).get('namespace'),
                 'dgd_uid': files.get('state.json', {}).get('snapshot_dgd_uid'),
                 'ready_observed_at': files.get('demo.json', {}).get('ready_observed_at')}
    else:
        if args.output is None:
            parser.error('collect needs --output')
        value = collect(args.run, args.output)
        value = {key: value[key] for key in ('run', 'controller_name', 'plan_sha256', 'docker_state')}
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
