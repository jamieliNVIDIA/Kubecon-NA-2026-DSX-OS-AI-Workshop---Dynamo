#!/usr/bin/env python3
"""Build an owned CPU coordinator image with curl on the existing jump host.

The pinned base is never overwritten or pushed. Source/receipt paths are
exclusive and an uncertain build is inspected rather than silently replayed.
Only Docker build layers install packages; the host/platform is unchanged.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = 'docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5']
DOCKERFILE = ('FROM ' + BASE + '\n'
              'RUN apt-get update && apt-get install -y --no-install-recommends curl '
              '&& rm -rf /var/lib/apt/lists/*\n')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


BUILD = r'''
import datetime,hashlib,json,subprocess,sys
from pathlib import Path
p=json.load(sys.stdin)
assert p['base_image']==BASE and hashlib.sha256(p['dockerfile'].encode()).hexdigest()==p['dockerfile_sha256']
folder=Path(p['remote_build_dir']);assert folder.parent==Path('/home/ubuntu/workshop-measurements')
assert not folder.exists(),'Build context already exists; inspect it, never replay an uncertain build'
base=json.loads(subprocess.check_output(['docker','image','inspect',BASE],timeout=20))[0]
assert subprocess.run(['docker','image','inspect',p['tag']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20).returncode!=0,'Owned image tag already exists'
folder.mkdir(mode=0o700)
(folder/'Dockerfile').write_text(p['dockerfile'])
(folder/'intent.json').write_text(json.dumps(p,indent=2)+'\n')
with (folder/'build-console.log').open('x') as out:
 result=subprocess.run(['docker','build','--pull=false','--network=host','-t',p['tag'],str(folder)],stdout=out,stderr=subprocess.STDOUT,timeout=600)
if result.returncode:
 (folder/'failure.json').write_text(json.dumps({'exit_code':result.returncode,'reason':'Owned image build failed; no automatic retry'})+'\n')
 raise RuntimeError('Owned image build failed: '+(folder/'build-console.log').read_text()[-3000:])
image=json.loads(subprocess.check_output(['docker','image','inspect',p['tag']],timeout=20))[0]
assert json.loads(subprocess.check_output(['docker','image','inspect',BASE],timeout=20))[0]['Id']==base['Id'],'Base image changed'
common=['docker','run','--rm','--pull=never','--network=none','--user','1000:1000','--cpus=0.25','--memory=256m','--cap-drop=ALL','--security-opt=no-new-privileges']
curl=subprocess.check_output(common+['--entrypoint','/usr/bin/curl',image['Id'],'--version'],text=True,timeout=30)
raw=subprocess.check_output(common+['--entrypoint','/usr/bin/dpkg-query',image['Id'],'-W','-f=${binary:Package}\t${Version}\t${Architecture}\n'],text=True,timeout=30)
packages=[dict(zip(('package','version','architecture'),line.split('\t'))) for line in raw.splitlines()]
packages_json=json.dumps(sorted(packages,key=lambda x:x['package']),indent=2)+'\n'
(folder/'packages.json').write_text(packages_json)
receipt={'schema':1,'status':'built','at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_image':BASE,
 'base_image_id':base['Id'],'image_id':image['Id'],'tag':p['tag'],'dockerfile_sha256':p['dockerfile_sha256'],
 'curl_version':curl.splitlines()[0],'packages_sha256':hashlib.sha256(packages_json.encode()).hexdigest(),
 'remote_build_dir':str(folder),'attempt':p['attempt'],'scope':'Owned local CPU coordinator image only. No base overwrite, push, host package install or platform change.'}
(folder/'image-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'receipt':receipt,'packages_json':packages_json,'build_console':(folder/'build-console.log').read_text()}))
'''


def build(run, *, attempt='a1'):
    run = Path(run).resolve()
    run.relative_to(ROOT / 'results')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', run.name):
        raise ValueError('Use the owned named Snapshot run.')
    if not re.fullmatch(r'a[1-9][0-9]*', attempt):
        raise ValueError('Use an explicit numbered image-build attempt such as a2.')
    state = json.loads((run / 'state.json').read_text())
    if state.get('snapshot_dgd_submitted_at') or state.get('snapshot_dgd_uid'):
        raise ValueError('Prepare the coordinator runtime before starting GPUs.')
    target = run / 'controller-image'
    if (run / 'controller-image.json').exists():
        raise FileExistsError('A built image is already recorded; do not replace it.')
    if attempt == 'a1':
        target.mkdir(exist_ok=False)
        attempt_dir = target
    else:
        target.mkdir(exist_ok=True)
        attempts = target / 'attempts'
        attempts.mkdir(exist_ok=True)
        attempt_dir = attempts / attempt
        attempt_dir.mkdir(exist_ok=False)
    recipe_sha = sha(DOCKERFILE.encode())
    payload = {'base_image': BASE, 'dockerfile': DOCKERFILE, 'dockerfile_sha256': recipe_sha, 'attempt': attempt,
        'tag': 'kubecon-snapshot-controller:' + run.name + '-' + recipe_sha[:12] + '-' + attempt,
        'remote_build_dir': '/home/ubuntu/workshop-measurements/' + run.name + '-controller-image-' + recipe_sha[:12] + '-' + attempt}
    recipe = target / 'Dockerfile'
    if recipe.exists():
        if recipe.read_text() != DOCKERFILE:
            raise ValueError('Retained image recipe differs; do not overwrite it.')
    else:
        with recipe.open('x') as stream:
            stream.write(DOCKERFILE)
    with (attempt_dir / 'intent.json').open('x') as stream:
        stream.write(json.dumps({'at': now(), **payload}, indent=2) + '\n')
    program = 'BASE=' + repr(BASE) + '\n' + BUILD
    result = subprocess.run(SSH + ['python3', '-c', shlex.quote(program)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=720)
    (attempt_dir / 'transport.json').write_text(json.dumps({'at': now(), 'exit_code': result.returncode,
        'stderr': result.stderr, 'source_sha256': sha(Path(__file__).read_bytes())}, indent=2) + '\n')
    if result.returncode:
        raise RuntimeError('Owned controller image build failed or uncertain; preserve intent/context and inspect: ' + result.stderr[-3000:])
    response = json.loads(result.stdout)
    receipt = response['receipt']
    package_bytes = response['packages_json'].encode()
    if (receipt['base_image'] != BASE or receipt['dockerfile_sha256'] != recipe_sha
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', receipt['image_id'])
            or receipt['packages_sha256'] != sha(package_bytes)):
        raise ValueError('Built image/recipe/package provenance differs.')
    with (target / 'packages.json').open('xb') as stream:
        stream.write(package_bytes)
    (attempt_dir / 'build-console.log').write_text(response['build_console'])
    with (run / 'controller-image.json').open('x') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
    for path in (target / 'Dockerfile', target / 'packages.json', run / 'controller-image.json'):
        path.chmod(0o400)
    print(json.dumps({key: receipt[key] for key in ('status', 'base_image', 'image_id', 'curl_version',
                                                   'dockerfile_sha256', 'packages_sha256')}, indent=2), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', default='a1', help='Fresh explicit attempt; never reuses a failed build context/tag.')
    args = parser.parse_args()
    build(args.run, attempt=args.attempt)


if __name__ == '__main__':
    main()
