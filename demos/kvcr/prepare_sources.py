#!/usr/bin/env python3
"""Recreate the exact KVCR demo source bundle from hash-pinned public sources."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / 'demos/kvcr/source-lock.json'


def fetch(record, destination):
    url = urllib.parse.urlparse(record['url'])
    if url.scheme != 'https' or url.hostname not in ('codeload.github.com', 'raw.githubusercontent.com', 'files.pythonhosted.org'):
        raise ValueError('Source URL must be an allowlisted public HTTPS host.')
    with urllib.request.urlopen(record['url'], timeout=120) as response:
        data = response.read()
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Downloaded bytes do not match the frozen source record.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(data)
    return data


def make_bundle(directory, destination):
    """Fixed file ordering, metadata and gzip header match the qualified bundle."""
    with destination.open('xb') as stream, gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for group in ('kvcr', 'adapter', 'build-wheels', 'runtime-meta'):
                for path in sorted((directory / group).rglob('*')):
                    if not path.is_file() or path.is_symlink():
                        continue
                    data = path.read_bytes()
                    info = tarfile.TarInfo(str(path.relative_to(directory)))
                    info.size, info.mode, info.mtime, info.uid, info.gid = len(data), 0o644, 0, 0, 0
                    info.uname = info.gname = ''
                    archive.addfile(info, io.BytesIO(data))
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def prepare(output, lock_path=LOCK):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Use a fresh output directory; never overwrite a source attempt.')
    lock = json.loads(Path(lock_path).read_text())
    output.mkdir(parents=True, mode=0o700)
    (output / 'source-lock.json').write_bytes(Path(lock_path).read_bytes())
    stage = output / 'sources'
    records = lock['sources']['records']
    archive = fetch(records['kvcr-upstream.tar.gz'], output / 'kvcr-upstream.tar.gz')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            relative = Path(*parts[1:])
            if not member.isfile() or not (relative.parts[:1] in (('src',), ('tests',)) or
                                          str(relative) in ('LICENSE', 'README.md', 'pyproject.toml')):
                continue
            if not parts or Path(member.name).is_absolute() or '..' in parts:
                raise ValueError('Unsafe KVCR archive member.')
            path = stage / 'kvcr' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as target:
                target.write(source.extractfile(member).read())
    for name, record in records.items():
        if name.startswith('adapter/'):
            if '..' in Path(name).parts or Path(name).is_absolute():
                raise ValueError('Unsafe adapter file path.')
            fetch(record, stage / name)
    for record in lock['build_wheels']:
        if Path(record['filename']).name != record['filename']:
            raise ValueError('Unsafe build-wheel filename.')
        fetch(record, stage / 'build-wheels' / record['filename'])
    runtime = stage / 'runtime-meta/runtime-sources.json'
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps(lock['nightly'], indent=2) + '\n')
    bundle = output / lock['bundle_filename']
    if Path(lock['bundle_filename']).name != lock['bundle_filename']:
        raise ValueError('Unsafe bundle filename.')
    sha = make_bundle(stage, bundle)
    receipt = {'status': 'passed' if sha == lock['bundle_sha256'] else 'failed',
               'bundle': str(bundle), 'sha256': sha, 'expected_sha256': lock['bundle_sha256'],
               'scope': 'Source recreation only; no cluster deployment or serving qualification.'}
    (output / 'preparation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if receipt['status'] != 'passed':
        raise ValueError('Recreated bundle differs from the qualified bytes; inspect this retained attempt.')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        prepare(args.output)
    except (RuntimeError, ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
