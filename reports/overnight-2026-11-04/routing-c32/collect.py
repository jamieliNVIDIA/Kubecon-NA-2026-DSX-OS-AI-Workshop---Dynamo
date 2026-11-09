#!/usr/bin/env python3
"""Snapshot completed remote cells without overwriting local or remote evidence."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]
REMOTE = '/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace'
RUN = 'results/workshop-routing-c32-20261105-a1'
CONTROL = 'results/workshop-routing-c32-controller-20261105-a1'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
       '-o', 'ServerAliveCountMax=2', '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5']

PROGRAM = r'''
from pathlib import Path
import datetime,hashlib,io,json,sys,tarfile
w=Path(WORKSPACE);r=w/RUN_PATH;c=w/CONTROL_PATH
paths=set(p for p in r.iterdir() if p.is_file() and p.name not in ('.state.lock',))
completed=[]
for p in r.glob('*-c*-a1'):
 if p.is_dir() and (p/'integrity-final.json').is_file():
  frozen=json.loads((p/'integrity-final.json').read_text())['sha256']
  for name,digest in frozen.items():
   assert hashlib.sha256((p/name).read_bytes()).hexdigest()==digest,'Changed completed cell '+name
  paths.update(q for q in p.rglob('*') if q.is_file());completed.append(p.name)
for p in c.glob('*.json'):paths.add(p)
status=json.loads((c/'STATUS.json').read_text()) if (c/'STATUS.json').exists() else None
if (c/'exit.json').is_file():
 # A terminal failure must retain its failed cell/startup and control evidence too.
 paths.update(p for p in r.rglob('*') if p.is_file() and p.name!='.state.lock')
 paths.update(p for p in c.rglob('*') if p.is_file())
manifest={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'completed_cells':sorted(completed),'controller_status':status,'files':{}}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:
 for p in sorted(paths):
  assert not p.is_symlink();name=str(p.relative_to(w));raw=p.read_bytes()
  member=tarfile.TarInfo(name);member.size=len(raw);member.mode=0o400
  archive.addfile(member,io.BytesIO(raw))
  manifest['files'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 raw=json.dumps(manifest,indent=2).encode();member=tarfile.TarInfo('collection-manifest.json')
 member.size=len(raw);member.mode=0o400;archive.addfile(member,io.BytesIO(raw))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.label):
        parser.error('Use an immutable lowercase label.')
    destination = ROOT / 'results' / ('workshop-routing-c32-collection-' + args.label)
    destination.mkdir(exist_ok=False)
    archive_path = destination / 'evidence.tar.gz'
    program = PROGRAM.replace('WORKSPACE', repr(REMOTE)).replace('RUN_PATH', repr(RUN)).replace('CONTROL_PATH', repr(CONTROL))
    with archive_path.open('xb') as stream:
        result = subprocess.run(SSH + ['python3', '-c', shlex.quote(program)],
                                stdout=stream, stderr=subprocess.PIPE, timeout=900)
    (destination / 'transport-stderr.txt').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('Collection failed; preserve archive/error and use a fresh label.')
    target = destination / 'verified'
    target.mkdir()
    with tarfile.open(archive_path) as archive:
        names = set()
        for member in archive.getmembers():
            if not member.isfile() or member.name in names:
                raise ValueError('Unexpected archive member.')
            names.add(member.name)
            (target / member.name).resolve().relative_to(target.resolve())
        manifest = json.load(archive.extractfile('collection-manifest.json'))
        if names != set(manifest['files']) | {'collection-manifest.json'}:
            raise ValueError('Archive members differ from recorded inventory.')
        for member in archive.getmembers():
            raw = archive.extractfile(member).read()
            if member.name in manifest['files']:
                record = manifest['files'][member.name]
                if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Collection hash mismatch: ' + member.name)
            path = target / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(raw)
    receipt = {'verified': True, 'files': len(manifest['files']),
               'completed_cells': manifest['completed_cells'],
               'controller_status': manifest['controller_status'],
               'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
               'run': str(target / RUN)}
    (destination / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
