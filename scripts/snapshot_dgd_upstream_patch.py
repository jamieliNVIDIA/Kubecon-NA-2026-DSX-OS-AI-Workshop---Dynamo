#!/usr/bin/env python3
"""Backport merged KV-only capture, retaining only the restore-environment bridge.

The engine pause controller is Dynamo's installed VllmEnginePauseController.
This trial preserves its upstream communicator hooks. The v3 adapter and all
previous qualification artifacts remain unchanged.
"""
import argparse
import json
from pathlib import Path

import snapshot_dgd_runtime_patch as bridge

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'super-vl-dgd-snapshot-upstream-kv-v1'
UPSTREAM_COMMIT = '521225369330f2120f1676748057a692a24c2303'
UPSTREAM_MODULE_SHA256 = '9e467ad95714a7979a778ad32631da0f40593c05b50f04c9a64df40168ca59b1'
UPSTREAM_SOURCE = ROOT / 'configs/dgd/workshop-snapshot-dgd-upstream/upstream-snapshot.py'
UPSTREAM_URL = ('https://github.com/ai-dynamo/dynamo/blob/' + UPSTREAM_COMMIT +
                '/components/src/dynamo/vllm/snapshot.py')


def patch_source(source, upstream):
    if bridge.sha256(source) != bridge.PINNED_SOURCE_SHA256:
        raise ValueError('Installed Snapshot module differs from the inspected pinned SHA256')
    if bridge.sha256(upstream) != UPSTREAM_MODULE_SHA256:
        raise ValueError('Upstream Snapshot module differs from merged PR #15887 SHA256')
    marker = 'async def prepare_snapshot_engine('
    if upstream.count(marker) != 1 or upstream.count(bridge.ORIGINAL_RETURN) != 1:
        raise ValueError('Unexpected upstream Snapshot entrypoint')
    # Keep the entire upstream pause/controller selection path unchanged.
    patched = upstream.replace(marker, bridge.PROXY_RESTORE_CONTEXT_SOURCE + marker, 1)
    patched = patched.replace(bridge.ORIGINAL_RETURN, bridge.REPLACEMENT_RETURN, 1)
    compile(patched, '<snapshot-upstream-kv-patch>', 'exec')
    return patched


def receipt(source, upstream, patched):
    return {'profile': PROFILE, 'source_sha256': bridge.sha256(source),
        'upstream_commit': UPSTREAM_COMMIT, 'upstream_url': UPSTREAM_URL,
        'upstream_module_sha256': bridge.sha256(upstream),
        'patched_sha256': bridge.sha256(patched),
        'scope': 'Exact merged PR #15887 module plus the v3 destination identity/offline bridge',
        'pause_controller': 'installed dynamo.vllm.handlers.VllmEnginePauseController',
        'communicator_hooks': 'Upstream detection and checkpoint_prepare/checkpoint_restore preserved',
        'custom_pause_controller': False,
        'remaining_custom_runtime_changes': ['allowlisted restore proxy environment to restore-context.json',
            'destination HF_HUB_OFFLINE policy restoration before registration']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--upstream-source', type=Path, default=UPSTREAM_SOURCE)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes().decode('utf-8')
    upstream = args.upstream_source.read_bytes().decode('utf-8')
    patched = patch_source(source, upstream)
    info = receipt(source, upstream, patched)
    targets = [args.output] + ([args.receipt] if args.receipt else [])
    if len({p.resolve() for p in targets}) != len(targets):
        raise ValueError('Patch and receipt paths must be distinct')
    if any(p.exists() or p.is_symlink() for p in targets):
        raise FileExistsError('Refusing to overwrite an existing patch or receipt')
    for p in targets:
        p.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='') as stream:
        stream.write(patched)
    if args.receipt:
        with args.receipt.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
