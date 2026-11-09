#!/usr/bin/env python3
"""Windowed analysis of collected synthetic cells: throughput, TPS/GPU, TPS/user, TTFT and cache reuse.

Per-request metrics come from AIPerf records that started inside the analysis window; throughput counts
tokens of requests that completed inside it. Server pressure, router overlap and per-worker request
splits are whole-profile values from AIPerf's server-metrics export, labeled as such.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import statistics

# AgentX two-worker KV C32 (reports/overnight-2026-11-04/routing-c32/C32-RESULTS.md); calibration context only.
AGENTX_C32_KV = {'output_tokens_per_second': 525.23, 'output_tokens_per_second_per_gpu': 131.31,
                 'output_tokens_per_second_per_user_mean': 87.52, 'ttft_p50_ms': 339.74,
                 'cache_read_pct': 88.88}
PAIRS = {
    'same_agents_more_gpus': [('1w-32', '2kv-32'), ('1w-64', '2kv-64'), ('1w-128', '2kv-128')],
    'twice_agents_twice_gpus': [('1w-32', '2kv-64'), ('1w-64', '2kv-128')],
    'routing': [('2rr-64', '2kv-64'), ('2rr-128', '2kv-128')],
    'agentx_calibration': [('2kv-32', None)],
}
# Later turns by how much of the session's previous-turn prompt missed the cache. current: one-worker cells at 32 and
# 64 agents never exceed 4,222; one missed turn adds about 4,650 (4,000 input + 650 output).
# stale: an older copy of the session, missing recent turns. cold: little beyond the 32,000-token shared prompt.
CONTINUITY = {'current': 5000, 'cold': 20000}
RATIO_KEYS = ['output_tokens_per_second', 'output_tokens_per_second_per_gpu', 'output_tokens_per_second_per_user_mean',
              'ttft_p50_ms', 'ttft_p90_ms', 'itl_p50_ms', 'e2e_p50_ms', 'e2e_p90_ms', 'cache_read_pct',
              'recomputed_prompt_tokens_per_request']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def percentile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    position = (len(values) - 1) * q / 100
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def value(record, key):
    return (record['metrics'].get(key) or {}).get('value')


def gpu_utilization(path, start_ns, end_ns):
    samples = {}
    for csv_path in path.glob('gpu-*.csv'):
        with csv_path.open() as stream:
            for row in csv.DictReader(stream):
                row = {k.strip(): (v or '').strip() for k, v in row.items() if k}
                try:
                    at = dt.datetime.strptime(row['timestamp'], '%Y/%m/%d %H:%M:%S.%f').replace(
                        tzinfo=dt.timezone.utc).timestamp() * 1e9
                    utilization = float(row['utilization.gpu [%]'])
                except (KeyError, ValueError):
                    continue
                if start_ns <= at < end_ns:
                    samples.setdefault(row['uuid'], []).append(utilization)
    return {uuid: round(statistics.mean(v), 1) for uuid, v in samples.items()}


def series_stats(metrics, name, stat):
    return [{'endpoint': s.get('endpoint_url'), 'labels': {k: v for k, v in s.get('labels', {}).items()
             if k in ('worker_id', 'dynamo_endpoint', 'engine')}, stat: s.get('stats', {}).get(stat)}
            for s in metrics.get(name, {}).get('series', [])]


# Collections leave out the generated dataset and the duplicate artifact tarball (gigabytes per cell);
# the dataset is regenerable from the frozen seed and pinned AIPerf, and the tarball duplicates raw/.
NOT_TRANSFERRED = ('inputs.json', 'raw-artifacts.tar.gz')


def cell(path, start_seconds, end_seconds):
    spec = json.loads((path / 'spec.json').read_text())
    absent = []
    for rel, digest in json.loads((path / 'integrity-final.json').read_text())['sha256'].items():
        if not (path / rel).exists() and Path(rel).name in NOT_TRANSFERRED:
            absent.append(rel)
            continue
        assert sha(path / rel) == digest, 'Collected cell changed: ' + str(path / rel)
    export = [p for p in (path / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
    assert len(export) == 1, path
    data = json.loads(export[0].read_text())
    server = json.loads(next((path / 'raw').rglob('server_metrics_export.json')).read_text())
    phase = server['summary']['phase_time_ranges']['profiling']
    begin, finish = phase['start_ns'] + start_seconds * 1e9, phase['start_ns'] + end_seconds * 1e9
    records = []
    for record_path in (path / 'raw').rglob('profile_export.jsonl'):
        with record_path.open() as stream:
            for line in stream:
                item = json.loads(line)
                meta = item.get('metadata', {})
                if meta.get('phase_kind', meta.get('benchmark_phase')) == 'profiling' and not meta.get('was_cancelled'):
                    records.append(item)
    started = [r for r in records if begin <= r['metadata']['request_start_ns'] < finish]
    completed = [r for r in records if begin <= r['metadata']['request_end_ns'] < finish]
    seconds = end_seconds - start_seconds
    gpus = spec.get('h100_gpus') or 2 * spec['workers']
    tokens = sum(value(r, 'output_token_count') or 0 for r in completed)
    prompt = sum(value(r, 'usage_prompt_tokens') or 0 for r in started)
    cached = sum(value(r, 'usage_prompt_cache_read_tokens') or 0 for r in started)
    per_user = [value(r, 'output_token_throughput_per_user') for r in started]
    ttft = [value(r, 'time_to_first_token') for r in started]
    itl = [value(r, 'inter_token_latency') for r in started]
    e2e = [value(r, 'request_latency') for r in started]
    slices = {}
    for r in records:
        index = int((r['metadata']['request_end_ns'] - phase['start_ns']) // 30e9)
        slices[index] = slices.get(index, 0) + (value(r, 'output_token_count') or 0)
    # A later turn's previous-turn prompt minus its cache hit: how much of the session's existing context the serving
    # worker lacked. AIPerf does not record the serving worker, so this classifies placement from cache reuse alone.
    by_turn = {(r['metadata']['conversation_id'], r['metadata']['turn_index']): r for r in records}
    lacked = []
    for r in started:
        previous = by_turn.get((r['metadata']['conversation_id'], r['metadata']['turn_index'] - 1))
        if previous and value(previous, 'usage_prompt_tokens') is not None and value(r, 'usage_prompt_tokens') is not None:
            lacked.append(value(previous, 'usage_prompt_tokens') - (value(r, 'usage_prompt_cache_read_tokens') or 0))
    metrics = server.get('metrics', {})
    predicted = metrics.get('dynamo_component_router_kv_hit_rate', {}).get('series', [])
    window = {
        'output_tokens_per_second': tokens / seconds,
        'output_tokens_per_second_per_gpu': tokens / seconds / gpus,
        'output_tokens_per_second_per_user_mean': statistics.mean(v for v in per_user if v is not None) if any(per_user) else None,
        'output_tokens_per_second_per_user_p50': percentile(per_user, 50),
        'output_tokens_per_second_per_user_p10': percentile(per_user, 10),
        'ttft_p50_ms': percentile(ttft, 50), 'ttft_p90_ms': percentile(ttft, 90), 'ttft_p99_ms': percentile(ttft, 99),
        'itl_p50_ms': percentile(itl, 50), 'itl_p90_ms': percentile(itl, 90),
        'e2e_p50_ms': percentile(e2e, 50), 'e2e_p90_ms': percentile(e2e, 90), 'e2e_p99_ms': percentile(e2e, 99),
        'request_rate': len(completed) / seconds,
        'cache_read_pct': 100 * cached / prompt if prompt else None,
        'recomputed_prompt_tokens_per_request': (prompt - cached) / len(started) if started else None,
        'input_tokens_mean': prompt / len(started) if started else None,
        'requests_started': len(started), 'requests_completed': len(completed),
        'session_continuity': {'later_turns': len(lacked),
            'current_pct': 100 * sum(v < CONTINUITY['current'] for v in lacked) / len(lacked) if lacked else None,
            'stale_pct': 100 * sum(CONTINUITY['current'] <= v <= CONTINUITY['cold'] for v in lacked) / len(lacked) if lacked else None,
            'cold_pct': 100 * sum(v > CONTINUITY['cold'] for v in lacked) / len(lacked) if lacked else None,
            'previous_context_uncached_mean': statistics.mean(lacked) if lacked else None,
            'previous_context_uncached_max': max(lacked) if lacked else None},
    }
    offered = spec.get('offered_request_rate')
    return {'cell': path.name, 'workers': spec.get('workers'), 'gpus': gpus, 'frontend': spec.get('frontend'),
        'router_mode': spec.get('router_mode'), 'agents': spec.get('agents'), 'offered_request_rate': offered,
        'achieved_fraction_of_offered': window['request_rate'] / offered if offered else None,
        'window_seconds': [start_seconds, end_seconds], 'window': window, 'not_transferred': absent,
        'whole_profile': {'requests': (data.get('request_count') or {}).get('avg'),
            'request_errors': (data.get('error_request_count') or {}).get('avg') or 0,
            'output_sequence_length_mean': (data.get('output_sequence_length') or {}).get('avg'),
            'output_tokens_per_second': (data.get('output_token_throughput') or {}).get('avg'),
            'ttft_p90_ms': (data.get('time_to_first_token') or {}).get('p90')},
        'output_tokens_by_30s_slice': [slices.get(i, 0) for i in range(max(slices) + 1)] if slices else [],
        'router_predicted_overlap': {'count': sum(s.get('stats', {}).get('count', 0) for s in predicted),
                                     'sum': sum(s.get('stats', {}).get('sum', 0) or 0 for s in predicted)},
        'worker_requests': series_stats(metrics, 'dynamo_component_requests', 'total'),
        'pressure_whole_profile': {name: series_stats(metrics, name, stat) for name, stat in [
            ('vllm:num_requests_running', 'avg'), ('vllm:num_requests_waiting', 'p99'),
            ('vllm:request_queue_time_seconds', 'sum'), ('vllm:request_prefill_time_seconds', 'sum'),
            ('vllm:num_preemptions', 'total'), ('vllm:kv_cache_usage_perc', 'max')]},
        'gpu_utilization_window_pct': gpu_utilization(path, begin, finish)}


def ratios(rows, first, second):
    a, b = rows.get(first), rows.get(second)
    if not a or not b:
        return None
    out = {'pair': [first, second]}
    for key in RATIO_KEYS:
        x, y = a['window'].get(key), b['window'].get(key)
        out[key] = {first: x, second: y, 'ratio': y / x if x and y is not None else None}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True,
                        help='Collected run directory with one folder per cell; repeat to combine attempts, '
                             "a later run replacing an earlier run's cell of the same name")
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', type=float, default=180)
    parser.add_argument('--end', type=float, default=540)
    args = parser.parse_args()
    rows, replaced = {}, {}
    for run in args.run:
        for p in sorted(run.iterdir()):
            if p.is_dir() and re.fullmatch(r'[12](w|rr|kv)-\d+', p.name) and (p / 'summary.json').exists():
                if p.name in rows:
                    replaced.setdefault(p.name, []).append(rows[p.name])
                rows[p.name] = dict(cell(p, args.start, args.end), run=str(run))
    comparisons = {}
    for kind, pairs in PAIRS.items():
        for first, second in pairs:
            if kind == 'agentx_calibration':
                if first in rows:
                    comparisons.setdefault(kind, []).append({'synthetic': {k: rows[first]['window'].get(k) for k in AGENTX_C32_KV},
                                                             'agentx_two_kv_c32': AGENTX_C32_KV})
                continue
            value_ = ratios(rows, first, second)
            if value_:
                comparisons.setdefault(kind, []).append(value_)
    result = {'run': [str(r) for r in args.run], 'analyzed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'cells': rows, 'replaced_cells': replaced, 'comparisons': comparisons,
              'scope': ('Synthetic coding-agent-shaped load, never AgentX. N=1 per cell in fixed order with persistent workers. '
                        'Window metrics exclude the cold first turns; pressure, router and worker-split values cover the whole profile. '
                        'With several runs, each cell records its run; comparisons may span deployments.')}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for row in [r for rs in replaced.values() for r in rs] + list(rows.values()):
        w = row['window']
        print(f"{row['cell']:8s} {Path(row['run']).name[-2:]}  tok/s {w['output_tokens_per_second']:7.1f}  "
              f"/GPU {w['output_tokens_per_second_per_gpu']:6.1f}  /user {w['output_tokens_per_second_per_user_mean'] or 0:6.1f}  "
              f"TTFT p50/p90 {w['ttft_p50_ms'] or 0:7.0f}/{w['ttft_p90_ms'] or 0:7.0f} ms  "
              f"cache {w['cache_read_pct'] or 0:5.1f}%  achieved {row['achieved_fraction_of_offered'] or 0:4.2f}  "
              f"current/stale/cold {w['session_continuity']['current_pct'] or 0:5.1f}/{w['session_continuity']['stale_pct'] or 0:4.1f}/"
              f"{w['session_continuity']['cold_pct'] or 0:4.1f}%  max uncached (one worker) "
              f"{w['session_continuity']['previous_context_uncached_max'] if row['workers'] == 1 else '-'}")


if __name__ == '__main__':
    main()
