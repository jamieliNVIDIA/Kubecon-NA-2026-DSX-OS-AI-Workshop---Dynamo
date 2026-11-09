#!/usr/bin/env python3
"""Stream a fully qualified pinned MX cache into a private RAM HF cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import sys
import time
from types import SimpleNamespace

GiB = 1024 ** 3


def validate_spec(spec):
    if type(spec.get('schema')) is not int or spec['schema'] != 1 or not re.fullmatch(r'[a-z][a-z0-9-]{1,35}', spec['id']):
        raise ValueError('Invalid staging identity.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', spec['model']):
        raise ValueError('Invalid pinned model.')
    if not re.fullmatch(r'[a-f0-9]{40}', spec['revision']):
        raise ValueError('Invalid pinned revision.')
    for name, row in spec['files'].items():
        p = PurePosixPath(name)
        if (not name or p.is_absolute() or str(p) != name or '..' in p.parts or
                type(row['bytes']) is not int or row['bytes'] < 0 or
                not isinstance(row['weight'], bool) or
                not re.fullmatch(r'[a-f0-9]{64}', row['sha256'])):
            raise ValueError('Unsafe/unqualified model file: ' + name)
    if not spec['files']:
        raise ValueError('Empty model inventory.')
    total = sum(row['bytes'] for row in spec['files'].values())
    if total + GiB > spec['cache_limit_bytes']:
        raise ValueError('Inventory exceeds bounded RAM cache.')
    return total


def memory_gate(cache, payload_bytes, cache_limit_bytes):
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable'):
            values[key] = int(value.split()[0]) * 1024
    for key in ('memory.max', 'memory.current'):
        p = Path('/sys/fs/cgroup') / key
        values[key] = p.read_text().strip() if p.exists() else None
    if values.get('MemAvailable', 0) < cache_limit_bytes + 32 * GiB:
        raise ValueError('Host memory cannot retain cache plus32GiB reserve.')
    if values['memory.max'] not in (None, 'max'):
        if int(values['memory.max']) - int(values['memory.current'] or 0) < payload_bytes + 4 * GiB:
            raise ValueError('Cgroup available memory cannot hold cache plus4GiB reserve.')
    stat = os.statvfs(cache)
    if stat.f_bavail * stat.f_frsize < payload_bytes + GiB:
        raise ValueError('Insufficient private cache filesystem space.')
    return values


def cuda_state():
    torch = sys.modules.get('torch')
    return {'torch_imported': torch is not None,
            'cuda_initialized': bool(torch.cuda.is_initialized()) if torch is not None else False}


class VerifiedSink:
    """Hash each streamed file before exposing a complete snapshot."""
    def __init__(self, staging, revision, inventory):
        self.staging = Path(staging)
        self.snapshot = self.staging / 'snapshots' / revision
        self.snapshot.mkdir(parents=True)
        (self.staging / 'blobs').mkdir()
        self.inventory = inventory
        self.completed = {}
        self.current = None

    def begin_file(self, name):
        if self.current is not None or name not in self.inventory or name in self.completed:
            raise ValueError('Unexpected or duplicate streamed file.')
        self.current = name
        self.path = self.staging / 'blobs' / '.incoming'
        self.stream = self.path.open('xb')
        self.hash = hashlib.sha256()
        self.size = 0

    def write(self, data):
        if self.current is None or self.size + len(data) > self.inventory[self.current]['bytes']:
            raise ValueError('Stream exceeds pinned file size.')
        self.stream.write(data)
        self.hash.update(data)
        self.size += len(data)

    def end_file(self):
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.stream.close()
        expected = self.inventory[self.current]
        actual = self.hash.hexdigest()
        if self.size != expected['bytes'] or actual != expected['sha256']:
            raise ValueError('Streamed file size/hash differs: ' + self.current)
        blob = self.staging / 'blobs' / actual
        if blob.exists():
            self.path.unlink()
        else:
            os.replace(self.path, blob)
        target = self.snapshot / self.current
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(os.path.relpath(blob, target.parent))
        self.completed[self.current] = {'bytes': self.size, 'sha256': actual, 'weight': expected['weight']}
        self.current = None
        if len(self.completed) % 10 == 0 or len(self.completed) == len(self.inventory):
            print(json.dumps({'staged_files': len(self.completed), 'total_files': len(self.inventory),
                              'staged_bytes': sum(row['bytes'] for row in self.completed.values())}), flush=True)

    def close(self):
        stream = getattr(self, 'stream', None)
        if stream is not None and not stream.closed:
            stream.close()


def stage(spec, hf_home, client, provider, resource_gate=memory_gate):
    started = time.monotonic()
    total = validate_spec(spec)
    model, revision = spec['model'], spec['revision']
    hf_home = Path(hf_home)
    hf_home.mkdir(parents=True, exist_ok=True)
    memory = resource_gate(hf_home, total, spec['cache_limit_bytes'])
    hub = hf_home / 'hub'
    hub.mkdir(exist_ok=True)
    destination = hub / ('models--' + model.replace('/', '--'))
    staging = hub / ('.mx-stage-' + spec['id'])
    receipt_path = hf_home / 'mx-dev-cache-stage.json'
    if any(p.exists() or p.is_symlink() for p in (destination, staging, receipt_path)):
        raise ValueError('Local cache is not fresh; inspect preserved state.')
    if cuda_state()['cuda_initialized']:
        raise ValueError('CPU cache stage unexpectedly initialized CUDA.')
    if client.ensure_downloaded(model, ignore_weights=False, revision=revision) != revision:
        raise ValueError('MX did not confirm the exact pinned revision.')
    manifest = client.list_files(model, ignore_weights=False, revision=revision)
    expected = {name: row['bytes'] for name, row in spec['files'].items()}
    if manifest != expected:
        raise ValueError('MX file manifest differs from complete trusted seed inventory.')
    sink = VerifiedSink(staging, revision, spec['files'])
    try:
        reported = client._stream_into(model, provider, sorted(expected), expected, sink,
                                       expected_commit=revision, revision=revision)
        if reported != revision or set(sink.completed) != set(expected) or sink.current is not None:
            raise ValueError('MX full stream did not complete at the pinned revision.')
        index = json.loads((sink.snapshot / 'model.safetensors.index.json').read_text())
        weights = {name for name, row in spec['files'].items() if row['weight']}
        if set(index['weight_map'].values()) != weights:
            raise ValueError('Complete stream index disagrees with trusted weight inventory.')
        cuda = cuda_state()
        if cuda['cuda_initialized']:
            raise ValueError('CPU cache stage initialized CUDA during download.')
        (staging / 'refs').mkdir()
        (staging / 'refs/main').write_text(revision + '\n')
        os.replace(staging, destination)
        receipt = {'schema': 1, 'status': 'passed', 'id': spec['id'], 'model': model, 'revision': revision,
                   'server_address': spec['server_address'], 'server_pod_uid': spec['server_pod_uid'],
                   'seed_receipt_sha256': spec['seed_receipt_sha256'],
                   'stage_spec_sha256': hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
                   'files': sink.completed, 'file_count': len(sink.completed),
                   'weight_files': len(weights), 'weight_bytes': sum(expected[n] for n in weights),
                   'logical_bytes': total, 'elapsed_seconds': time.monotonic() - started,
                   'hf_home': str(hf_home), 'memory': memory, **cuda,
                   'scope': 'CPU native ModelService full stream + all-file hashes into private cache; no inference or GMS-MX composition.'}
        with receipt_path.open('x') as out:
            out.write(json.dumps(receipt, sort_keys=True) + '\n')
        print('MX_DEV_CACHE_STAGE=' + json.dumps(receipt, sort_keys=True), flush=True)
        return receipt
    finally:
        sink.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--hf-home', type=Path, required=True)
    p.add_argument('--timeout-seconds', type=int, default=1200)
    p.add_argument('--rpc-timeout', type=int, default=900)
    a = p.parse_args()
    if not 1 <= a.rpc_timeout <= a.timeout_seconds <= 2400:
        p.error('Use1 <= RPC timeout <= overall timeout <=2400 seconds.')
    def timeout(signum, frame):
        raise TimeoutError('Bounded MX stage timed out; partial local cache retained.')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(a.timeout_seconds)
    spec = json.loads(a.spec.read_text())
    validate_spec(spec)
    from modelexpress.model_client import ModelCacheClient
    from modelexpress import model_pb2
    with ModelCacheClient(server_url=spec['server_address'], chunk_size=1024*1024) as client:
        raw = client.stub
        client._stub = SimpleNamespace(**{name: (lambda method: lambda request: method(request, timeout=a.rpc_timeout))(getattr(raw, name))
                                          for name in ('EnsureModelDownloaded', 'ListModelFiles', 'StreamModelFiles')})
        stage(spec, a.hf_home, client, model_pb2.HUGGING_FACE)
    signal.alarm(0)


if __name__ == '__main__':
    main()
