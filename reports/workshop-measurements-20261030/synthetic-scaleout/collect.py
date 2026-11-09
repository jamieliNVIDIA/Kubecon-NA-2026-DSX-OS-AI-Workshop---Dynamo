#!/usr/bin/env python3
"""Collect a synthetic run from the jumphost without the multi-gigabyte generated datasets.

Each cell's AIPerf `inputs.json` (the generated dataset, ~2.7 GB) and `raw-artifacts.tar.gz` (a copy of
`raw/`) stay on the jumphost; their sizes and SHA-256 are recorded in `excluded-files.txt` first.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', 'ubuntu@3.238.63.5']
EXCLUDED = ['inputs.json', 'raw-artifacts.tar.gz']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1 << 22):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', required=True, choices=['a1', 'a2', 'a3'])
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    workspace = {'a1': '/home/ubuntu/workshop-measurements/synthetic-scaleout-20261107/workspace',
                 'a2': '/home/ubuntu/workshop-measurements/synthetic-scaleout-20261107-a2/workspace',
                 'a3': '/home/ubuntu/workshop-measurements/synthetic-scaleout-20261107-a3/workspace'}[args.attempt]
    paths = [f'results/workshop-synthetic-scaleout-20261107-{args.attempt}',
             f'results/workshop-synthetic-scaleout-controller-20261107-{args.attempt}']
    folder = ROOT / f'results/workshop-synthetic-scaleout-collection-{args.attempt}-{args.label}'
    folder.mkdir(exist_ok=False)
    names = ' -o '.join(f'-name {shlex.quote(n)}' for n in EXCLUDED)
    listing = subprocess.run(SSH + [f'cd {shlex.quote(workspace)} && find {paths[0]} \\( {names} \\) -type f '
                                    '-exec sh -c \'for f; do printf "%s %s " "$(stat -c %s "$f")" "$f"; sha256sum "$f" | cut -d" " -f1; done\' sh {} +'],
                             capture_output=True, text=True, timeout=1800)
    assert listing.returncode == 0, listing.stderr[-2000:]
    (folder / 'excluded-files.txt').write_text(listing.stdout)
    excludes = ' '.join(f'--exclude={shlex.quote("*/" + n)}' for n in EXCLUDED)
    archive = folder / 'collected.tar.gz'
    with archive.open('wb') as stream:
        result = subprocess.run(SSH + [f'cd {shlex.quote(workspace)} && tar -czf - {excludes} ' + ' '.join(paths)],
                                stdout=stream, stderr=subprocess.PIPE, timeout=3600)
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-2000:]
    target = folder / 'verified'
    target.mkdir()
    with tarfile.open(archive) as tf:
        # Python 3.9 here has no extraction filters; check members the way execute_pair.collect_profile does.
        for member in tf.getmembers():
            if not (member.isfile() or member.isdir()):
                raise ValueError('Unexpected archive member type: ' + member.name)
            candidate = (target / member.name).resolve()
            if candidate != target.resolve() and target.resolve() not in candidate.parents:
                raise ValueError('Unsafe archive path: ' + member.name)
        tf.extractall(target)
    files = {str(p.relative_to(target)): sha(p) for p in target.rglob('*') if p.is_file()}
    (folder / 'transport.json').write_text(json.dumps({'at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'workspace': workspace, 'archive_sha256': sha(archive), 'files': len(files), 'excluded_patterns': EXCLUDED,
        'sha256': files}, indent=2) + '\n')
    print(json.dumps({'collection': str(folder.relative_to(ROOT)), 'files': len(files),
                      'excluded': len(listing.stdout.splitlines()), 'archive_bytes': archive.stat().st_size}))


if __name__ == '__main__':
    main()
