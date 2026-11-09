#!/usr/bin/env python3
"""Compare the AgentX C32 one-worker cell with the accepted November 5 two-worker pair.

Each cell's metrics come from the C32 report's own cell analysis; end-to-end turn latency percentiles are added from
the profiling records. A cell outside clean acceptance keeps its status and stays out of the ratios.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
module_spec = importlib.util.spec_from_file_location('routing_c32_analysis', ROOT / 'reports/overnight-2026-11-04/routing-c32/analyze.py')
c32 = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(c32)
PAIR = ROOT / 'results/workshop-routing-c32-collection-terminal-20261105-a2/verified/results/workshop-routing-c32-20261105-a1'
KEYS = ('output_tokens_per_second', 'decode_tokens_per_second_per_user_mean', 'ttft_p50_ms', 'ttft_p99_ms',
        'server_reported_cache_read_pct', 'canonical_throughput_denominator_seconds')


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def latency(path):
    """Request-to-last-token latency of every measured (profiling, not cancelled) request, in seconds."""
    values = []
    for records in (path / 'raw').rglob('profile_export.jsonl'):
        for line in records.read_text().splitlines():
            item = json.loads(line)
            meta = item.get('metadata', {})
            if meta.get('phase_kind', meta.get('benchmark_phase')) == 'profiling' and not meta.get('was_cancelled'):
                value = (item['metrics'].get('request_latency') or {}).get('value')
                if value is not None:
                    values.append(value / 1000)
    return {'requests': len(values), **{f'e2e_p{q}_s': percentile(values, q) for q in (50, 90, 99)}}


def row(path, gpus):
    value = c32.cell(path)
    out = {'arm': path.name, 'run': str(path.parent.relative_to(ROOT)), 'status': value['status'],
           'eligible': value['eligible'], 'h100_gpus': gpus}
    if value.get('metrics'):
        out.update({key: value['metrics'].get(key) for key in KEYS})
        out['output_tokens_per_second_per_gpu'] = value['metrics']['output_tokens_per_second'] / gpus
    if (path / 'raw').is_dir():
        out.update(latency(path))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--one', type=Path, required=True, help='Collected one-rr-c32-a1 cell directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [row(args.one.resolve(), 2), row(PAIR / 'two-rr-c32-a1', 4), row(PAIR / 'two-kv-c32-a1', 4)]
    one = rows[0]
    for other in rows[1:]:
        if one['eligible'] and other['eligible']:
            other['over_one_worker'] = {key: other[key] / one[key] if one.get(key) else None
                                        for key in ('output_tokens_per_second', 'decode_tokens_per_second_per_user_mean',
                                                    'ttft_p99_ms', 'e2e_p50_s', 'e2e_p90_s', 'e2e_p99_s')}
    value = {'cells': rows, 'scope': ('AgentX C32, N=1 per cell. The one-worker cell ran November 8 with health canaries off on '
             'cp-0942; the two-worker pair ran November 5 with canaries on. Separate observations of one profile, not a '
             'controlled capacity curve.')}
    args.output.write_text(json.dumps(value, indent=2) + '\n')
    for r in rows:
        print(f"{r['arm']:14s} {r['status']:20s} tok/s {r.get('output_tokens_per_second') or 0:7.1f}  "
              f"/user {r.get('decode_tokens_per_second_per_user_mean') or 0:6.1f}  TTFT p50/p99 {r.get('ttft_p50_ms') or 0:6.0f}/"
              f"{r.get('ttft_p99_ms') or 0:7.0f} ms  E2E p50/p90/p99 {r.get('e2e_p50_s') or 0:5.1f}/{r.get('e2e_p90_s') or 0:5.1f}/"
              f"{r.get('e2e_p99_s') or 0:5.1f} s  n={r.get('requests')}")


if __name__ == '__main__':
    main()
