#!/usr/bin/env python3
"""Save pinned public upstream recipes and a model revision lock."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4'
FILES = [
    'recipes/nemotron-3.5-lightning/vllm/agg-h100-dspark-kv-router/deploy.yaml',
    'recipes/nemotron-3.5-lightning/vllm/disagg-h100-dspark/deploy.yaml',
    'recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh',
    'lib/sidecar/vllm/deploy/agg.yaml',
    'lib/sidecar/sglang/deploy/agg_kv_router.yaml',
]


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dynamo-ref', required=True)
    args = parser.parse_args()
    if len(args.dynamo_ref) != 40 or any(c not in '0123456789abcdef' for c in args.dynamo_ref):
        raise ValueError('Use an immutable Dynamo commit SHA')
    root = ROOT / 'configs' / 'upstream'
    root.mkdir(parents=True, exist_ok=True)
    sources = []
    for path in FILES:
        url = f'https://raw.githubusercontent.com/ai-dynamo/dynamo/{args.dynamo_ref}/{path}'
        contents = fetch(url)
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)
        sources.append({'path': path, 'url': url, 'sha256': hashlib.sha256(contents).hexdigest()})
    model = json.loads(fetch(f'https://huggingface.co/api/models/{MODEL}'))
    lock = {'model': MODEL, 'revision': model['sha'], 'gated': model.get('gated'),
            'architecture': model.get('config', {}).get('architectures'),
            'dynamo_source_revision': args.dynamo_ref,
            'runtime_image': 'nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.5.0-nemotron-3.5-lightning-dev.1',
            'sources': sources}
    (ROOT / 'configs/model-lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    print(json.dumps(lock, indent=2))


if __name__ == '__main__':
    main()
