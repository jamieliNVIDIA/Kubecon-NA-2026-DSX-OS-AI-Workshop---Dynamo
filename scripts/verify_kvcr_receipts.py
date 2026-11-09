#!/usr/bin/env python3
"""Verify a completed peer transfer from saved receipts after log-fetch failure."""
import argparse
import hashlib
import json
from pathlib import Path
from testlib import Run


def verify(run):
    paths = [run.path / name for name in ('kvcr-metrics-before.json', 'kvcr-metrics-after.json', 'kvcr-requests.json', 'model-lock.json')]
    before, after, requests, lock = [json.loads(p.read_text()) for p in paths]
    seed = next(r for r in requests if r['step'] == 'seed')
    retrieved = next(r for r in requests if r['step'] == 'retrieve')
    assert seed['expected_worker'] != retrieved['expected_worker']
    assert seed['worker']['decode_worker_id'] == seed['expected_worker']
    assert retrieved['worker']['decode_worker_id'] == retrieved['expected_worker']
    assert seed['usage']['prompt_tokens_details']['cached_tokens'] == 0
    cached = retrieved['usage']['prompt_tokens_details']['cached_tokens']
    assert cached > 0
    text = ''.join(c['choices'][0].get('delta', {}).get('content', '') or '' for c in retrieved['chunks'] if c.get('choices'))
    assert text.strip().strip('.') == 'READY', text
    assert all(c.get('model', lock['model']) == lock['model'] for c in retrieved['chunks'])

    def values(records, metric, labels):
        return {pod: sum(float(line.rsplit(' ', 1)[-1]) for text in r['metrics'].values() if isinstance(text, str)
            for line in text.splitlines() if line.split('{', 1)[0].removesuffix('_total') == metric
            and all(label in line for label in labels)) for pod, r in records.items() if '-agg-' in pod}
    def delta(metric, labels):
        b, a = values(before, metric, labels), values(after, metric, labels)
        return {pod: value - b.get(pod, 0) for pod, value in a.items()}
    source_blocks = delta('vllm:kvcr_transfer_blocks', ['operation="source_write"'])
    target_blocks = delta('vllm:kvcr_transfer_blocks', ['operation="remote_deliver"'])
    source_bytes = delta('vllm:kv_offload_tiering_write_bytes', ['1:kvcr'])
    target_bytes = delta('vllm:kv_offload_tiering_read_bytes', ['1:kvcr'])
    assert sum(source_blocks.values()) == sum(target_blocks.values()) > 0
    assert sum(source_bytes.values()) == sum(target_bytes.values()) > 0
    for outcome in ('failed', 'partial'):
        assert sum(delta('vllm:kvcr_duration_seconds_count', ['scope="remote_deliver"', f'result="{outcome}"']).values()) == 0
    source = next(p for p, n in source_blocks.items() if n > 0)
    target = next(p for p, n in target_blocks.items() if n > 0)
    assert source != target and after[source]['node'] != after[target]['node']
    providers = {}
    for pod in (source, target):
        log = run.path / f'kvcr-full-{pod}.log'
        if log.is_file() and 'using provider=efa' in log.read_text():
            paths.append(log)
            providers[pod] = str(log.relative_to(run.path))
            continue
        for path in sorted(run.path.glob('command-*.json')):
            receipt = json.loads(path.read_text())
            if receipt['exit_code'] == 0 and 'logs' in receipt['args'] and pod in receipt['args'] and 'using provider=efa' in receipt['stdout']:
                paths.append(path)
                providers[pod] = path.name
                break
        assert pod in providers, f'No successful EFA log receipt for {pod}'
    report = {'model': lock['model'], 'tensor_parallel_size': lock.get('tensor_parallel_size', 1),
        'source_node': after[source]['node'], 'target_node': after[target]['node'],
        'blocks': sum(source_blocks.values()), 'bytes': sum(source_bytes.values()), 'cached_tokens': cached,
        'backend': 'LIBFABRIC', 'provider': 'efa', 'provider_receipts': providers,
        'remote_failed': 0, 'remote_partial': 0,
        'evidence_sha256': {str(p.relative_to(run.path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'scope': 'Completed cross-node peer reuse verified from saved requests, metric deltas and successful EFA log receipts; idle-canary test not included'}
    (run.path / 'kvcr-transfer-receipts.json').write_text(json.dumps(report, indent=2) + '\n')
    run.result('kvcr', 'passed', **report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    verify(Run(parser.parse_args().run))
