#!/usr/bin/env python3
"""Pin release Shadow Engine/GMS contracts without modifying the cluster."""
import argparse
import hashlib
import io
import json
import tarfile
import urllib.request
from testlib import ROOT

FILES = {
    'examples/backends/vllm/deploy/agg_failover.yaml',
    'deploy/operator/internal/dynamo/failover.go',
    'deploy/operator/internal/dynamo/failover_vllm.go',
    'deploy/operator/internal/gms/gms.go',
    'lib/gpu_memory_service/README.md',
    'lib/gpu_memory_service/integrations/vllm/model_loader.py',
    'lib/gpu_memory_service/integrations/vllm/worker.py',
    'lib/gpu_memory_service/integrations/vllm/patches.py',
    'lib/gpu_memory_service/failover_lock/flock/lock.py',
    'lib/gpu_memory_service/failover_lock/failover_metrics.py',
    'lib/gpu_memory_service/client/rpc.py',
    'lib/gpu_memory_service/common/protocol/messages.py',
    'lib/gpu_memory_service/common/utils.py',
    'tests/gpu_memory_service/test_shadow_failover.py',
    'tests/gpu_memory_service/common/gms.py',
    'tests/gpu_memory_service/flow_assertions.py',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='2093662a4d4e5fd318732935213dde08dc7be818')
    args = parser.parse_args()
    if len(args.revision) != 40 or any(c not in '0123456789abcdef' for c in args.revision):
        raise ValueError('Use an immutable commit SHA')
    url = f'https://codeload.github.com/ai-dynamo/dynamo/tar.gz/{args.revision}'
    with urllib.request.urlopen(url, timeout=90) as response:
        archive = response.read()
    files = []
    destination = ROOT / 'configs/upstream/shadow' / args.revision
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as source:
        for member in source.getmembers():
            path = '/'.join(member.name.split('/')[1:])
            selected = path in FILES or path.startswith('deploy/operator/internal/dra/') or (
                path.startswith('docs/') and any(s in path.lower() for s in ('shadow', 'gms', 'gpu-memory')))
            if not member.isfile() or not selected:
                continue
            if '..' in path.split('/'):
                raise ValueError('Invalid archive member')
            content = source.extractfile(member).read()
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != content:
                raise ValueError(f'Immutable source changed: {path}')
            target.write_bytes(content)
            files.append({'path': path, 'sha256': hashlib.sha256(content).hexdigest(),
                          'url': f'https://raw.githubusercontent.com/ai-dynamo/dynamo/{args.revision}/{path}'})
    for target in destination.rglob('*'):
        if target.is_file() and str(target.relative_to(destination)) not in {f['path'] for f in files}:
            target.unlink()
    lock = {'ref': 'v1.5.1' if args.revision == '2093662a4d4e5fd318732935213dde08dc7be818' else None,
            'revision': args.revision, 'archive_url': url,
            'archive_sha256': hashlib.sha256(archive).hexdigest(), 'files': files}
    (ROOT / 'configs/shadow-source.json').write_text(json.dumps(lock, indent=2) + '\n')
    print(json.dumps({'revision': args.revision, 'files': [f['path'] for f in files]}, indent=2))


if __name__ == '__main__':
    main()
