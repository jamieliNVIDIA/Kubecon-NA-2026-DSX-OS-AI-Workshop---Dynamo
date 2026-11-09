#!/usr/bin/env python3
"""Analyze accepted AgentX arms without substituting or changing their specs."""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import statistics
import yaml

HERE = Path(__file__).resolve().parent


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4194304):
            h.update(chunk)
    return h.hexdigest()


def load_arm(path):
    spec = json.loads((path / 'spec.json').read_text())
    assert sha(path / 'profile.yaml') == spec['profile_sha256']
    for rel, digest in json.loads((path / 'integrity.json').read_text()).items():
        assert sha(path / rel) == digest, rel
    exports = [p for p in (path / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
    assert len(exports) == 1
    data = json.loads(exports[0].read_text())
    assert data.get('is_complete') is True and data.get('was_cancelled') is False
    assert (data.get('metadata') or {}).get('submission_valid') is True
    assert not data.get('runtime_submission_invalid_reasons') and not data.get('error_summary')
    metric = lambda name, stat='avg': data.get(name, {}).get(stat)
    assert metric('request_count') > 0
    assert not metric('error_request_count') and not metric('context_overflow_count')
    server_path = next((path / 'raw').rglob('server_metrics_export.json'))
    server = json.loads(server_path.read_text())
    phase = server['summary']['phase_time_ranges']['profiling']
    phase_seconds = (phase['end_ns'] - phase['start_ns']) / 1e9
    metrics = server.get('metrics', {})
    worker_requests = []
    for series in metrics.get('dynamo_component_requests', {}).get('series', []):
        if series.get('labels', {}).get('dynamo_endpoint') == 'generate':
            worker_requests.append({'endpoint': series['endpoint_url'], 'worker_id': series['labels'].get('worker_id'),
                                    'requests': series['stats'].get('total')})

    records = []
    phases = {}
    traces = {}
    roots = set()
    for record_path in (path / 'raw').rglob('profile_export.jsonl'):
        with record_path.open() as stream:
            for line in stream:
                value = json.loads(line)
                meta = value.get('metadata', {})
                kind = meta.get('phase_kind', meta.get('benchmark_phase'))
                phases[kind] = phases.get(kind, 0) + 1
                if kind != 'profiling':
                    continue
                records.append(meta)
                if meta.get('root_correlation_id'):
                    roots.add(meta['root_correlation_id'])
                identity = meta.get('source_trace_id')
                item = traces.setdefault(identity, {'requests': 0, 'source_kinds': {}, 'outer_indices': []})
                item['requests'] += 1
                source_kind = meta.get('source_kind')
                item['source_kinds'][source_kind] = item['source_kinds'].get(source_kind, 0) + 1
                if meta.get('source_outer_idx') is not None:
                    item['outer_indices'].append(meta['source_outer_idx'])
    cancelled_records = sum(bool(r.get('was_cancelled')) for r in records)
    assert len(records) - cancelled_records == metric('request_count'), (len(records), cancelled_records, metric('request_count'))
    assert not any(r.get('context_overflow_skip') for r in records)
    for value in traces.values():
        indices = value.pop('outer_indices')
        value['source_outer_idx_min'] = min(indices) if indices else None
        value['source_outer_idx_max'] = max(indices) if indices else None

    profile = yaml.safe_load((path / 'profile.yaml').read_text())['benchmark']
    profile_seconds = profile['phases'][0]['duration']
    telemetry = {}
    for csv_path in path.glob('gpu-*.csv'):
        with csv_path.open() as stream:
            for row in csv.DictReader(stream):
                row = {k.strip(): v.strip() for k, v in row.items()}
                try:
                    at = dt.datetime.strptime(row['timestamp'], '%Y/%m/%d %H:%M:%S.%f').replace(tzinfo=dt.timezone.utc).timestamp() * 1e9
                    util = float(row['utilization.gpu [%]'])
                except (KeyError, ValueError):
                    continue
                if phase['start_ns'] <= at < phase['start_ns'] + profile_seconds * 1e9:
                    telemetry.setdefault(row['uuid'], []).append(util)
    predicted = metrics.get('dynamo_component_router_kv_hit_rate', {}).get('series', [])
    predicted_count = sum(s.get('stats', {}).get('count', 0) for s in predicted)
    predicted_sum = sum(s.get('stats', {}).get('sum',
        (s.get('stats', {}).get('avg') or 0) * s.get('stats', {}).get('count', 0)) for s in predicted)
    result = {'arm': path.name, 'spec': spec, 'spec_sha256': sha(path / 'spec.json'),
              'accepted_export': str(exports[0]), 'benchmark_id': data.get('benchmark_id'),
              'profile_seconds': profile_seconds, 'grace_seconds': profile['phases'][0]['grace_period'],
              'phase_window_seconds': phase_seconds, 'benchmark_duration_metric_seconds': metric('benchmark_duration'),
              'canonical_throughput_denominator_seconds': metric('total_osl') / metric('output_token_throughput'),
              'requests': metric('request_count'), 'request_error_count': metric('error_request_count') or 0,
              'output_tokens': metric('total_osl'), 'input_tokens': metric('total_isl'),
              'output_tokens_per_second': metric('output_token_throughput'),
              'output_tokens_per_second_per_gpu': metric('output_token_throughput') / spec['h100_gpus'],
              'record_span_output_tokens_per_second': metric('total_osl') / metric('benchmark_duration'),
              'decode_tokens_per_second_per_user_mean': metric('output_token_throughput_per_user'),
              'decode_tokens_per_second_per_user_p50': metric('output_token_throughput_per_user', 'p50'),
              'ttft_p50_ms': metric('time_to_first_token', 'p50'), 'ttft_p99_ms': metric('time_to_first_token', 'p99'),
              'itl_p50_ms': metric('inter_token_latency', 'p50'), 'itl_p99_ms': metric('inter_token_latency', 'p99'),
              'input_tokens_mean': metric('input_sequence_length'), 'output_tokens_mean': metric('output_sequence_length'),
              'server_reported_cache_read_pct': metric('overall_usage_prompt_cache_read_pct'),
              'server_reported_cache_read_tokens': metric('total_usage_prompt_cache_read_tokens'),
              'structural_theoretical_prefix_hit_pct': metric('theoretical_prefix_cache_hit'),
              'interactivity_metrics': {k: v for k, v in data.items() if 'interactivity' in k},
              'worker_generate_requests': worker_requests, 'predicted_kv_hit_histogram_count': predicted_count,
              'predicted_kv_hit_histogram_sum': predicted_sum,
              'branch_stats': data.get('branch_stats'), 'record_phase_counts': phases,
              'cancelled_profile_records': cancelled_records,
              'sampled_root_correlation_ids': sorted(roots), 'source_trace_requests': traces,
              'gpu_utilization_during_900s_admission_window': {k: {'samples': len(v), 'mean_pct': statistics.mean(v)}
                                                           for k, v in telemetry.items()},
              'metadata': data.get('metadata'),
              'phase_completion_log_lines': json.loads((path / 'summary.json').read_text()).get('phase_completion_log_lines')}
    return result


def normalized_profile(path):
    value = yaml.safe_load((path / 'profile.yaml').read_text())
    config = value['benchmark']
    config['endpoint']['urls'] = ['NORMALIZED']
    config['artifacts']['dir'] = 'NORMALIZED'
    config['server_metrics']['urls'] = ['NORMALIZED']
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, choices=[1, 4], required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--routing', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.attempt):
        raise ValueError('Invalid immutable label')
    prefix = 'routing' if args.routing else 'scaleout'
    names = ([f'routing-c{args.concurrency}-{mode}-{args.attempt}' for mode in ('round-robin', 'kv')] if args.routing
             else [f'c{args.concurrency}-r{n}-{args.attempt}' for n in (1, 2)])
    paths = [args.run.resolve() / name for name in names]
    assert normalized_profile(paths[0]) == normalized_profile(paths[1]), 'Workload settings differ'
    rows = [load_arm(path) for path in paths]
    first, second = rows
    for key in ('model', 'model_revision', 'runtime_image', 'dataset_revision', 'dataset_sha256',
                'aiperf_commit', 'dataset_pin_patch_sha256', 'concurrency_session_trees', 'native_max_model_len',
                'max_num_seqs_per_worker', 'client_preprocessor_workers'):
        assert first['spec'][key] == second['spec'][key], key
    if args.routing:
        assert first['spec']['router_mode'] == 'round-robin' and second['spec']['router_mode'] == 'kv'
        assert second['predicted_kv_hit_histogram_count'] > 0, 'No observed KV selection evidence'
        assert second['predicted_kv_hit_histogram_sum'] > 0, 'KV mode never observed positive prefix overlap'
    else:
        assert first['spec']['router_mode'] == second['spec']['router_mode'] == 'round-robin'
        assert {p['uid'] for p in first['spec']['worker_pods']}.issubset({p['uid'] for p in second['spec']['worker_pods']})
    comparison = {'type': prefix, 'concurrency_session_trees': args.concurrency, 'paired_repetitions': 1,
                  'arms': rows, 'second_over_first': {k: second[k] / first[k] for k in
                      ('output_tokens_per_second', 'record_span_output_tokens_per_second',
                       'decode_tokens_per_second_per_user_mean', 'ttft_p50_ms', 'ttft_p99_ms')},
                  'canonical_throughput_denominators_differ': abs(second['canonical_throughput_denominator_seconds'] -
                      first['canonical_throughput_denominator_seconds']) > 1,
                  'rate_interpretation': 'Canonical rates use exported phase windows, including actual grace/drain time. '
                      'Record-span-normalized rates are a separately labeled derived observation, not a replacement canonical score.'}
    destination = args.run / f'{prefix}-c{args.concurrency}-{args.attempt}-analysis.json'
    with destination.open('x') as stream:
        stream.write(json.dumps(comparison, indent=2) + '\n')
    report = args.run / f'{prefix}-c{args.concurrency}-{args.attempt}-REPORT.md'
    def fmt(value):
        return 'unavailable' if value is None else f'{value:,.2f}'
    lines = [f'# AgentX {prefix} comparison: C={args.concurrency}', '',
             'One fixed-order paired repetition. Full pinned AgentX corpus and replay settings were preserved.', '',
             '| Observation | ' + ' | '.join(names) + ' |', '| --- | ---: | ---: |']
    for label, key in [('H100 GPUs', None), ('Successful measured requests', 'requests'), ('Output tokens', 'output_tokens'),
                       ('Canonical aggregate output tokens/s', 'output_tokens_per_second'),
                       ('Derived output tokens/s over observed request span', 'record_span_output_tokens_per_second'),
                       ('Mean decode tokens/s/user', 'decode_tokens_per_second_per_user_mean'),
                       ('TTFT p50 (ms)', 'ttft_p50_ms'), ('TTFT p99 (ms)', 'ttft_p99_ms'),
                       ('Server-reported cache-read (%)', 'server_reported_cache_read_pct'),
                       ('Canonical throughput denominator (s)', 'canonical_throughput_denominator_seconds'),
                       ('Benchmark-duration metric (s)', 'benchmark_duration_metric_seconds')]:
        vals = [row['spec']['h100_gpus'] if key is None else row[key] for row in rows]
        lines.append('| ' + label + ' | ' + ' | '.join(fmt(v) for v in vals) + ' |')
    if comparison['canonical_throughput_denominators_differ']:
        lines += ['', '**The canonical aggregate-rate denominators differ between arms. Do not interpret their ratio alone as',
                  'a serving-capacity speedup.** Output counts, latency, cache reuse and the separately labeled observed-request-span',
                  'rate provide additional context. The comparison remains one fixed-order paired observation.']
    lines += ['', 'Admission lasts 900 s with a 300 s grace bound. The canonical aggregate rate uses the exported phase',
              'window, which can include drain time; the separate benchmark-duration metric can differ. Per-user decode',
              'speed excludes first-token delay and is distinct from end-to-end normalized interactivity.', '',
              'The source sample can contain resumed, incomplete agent trees. Logged completed replay sessions and branch',
              'counters do not establish complete coding-task successes. Exact source trace IDs, request mix, phase/session',
              'logs, branch counters, worker request distribution and GPU admission-window samples are in the analysis JSON.', '',
              'Observed cache-read tokens come from server usage. Structural theoretical prefix reuse is reported separately.',
              'No request-error, context-overflow, cancelled-run or invalid-submission result was accepted. Any tail-request',
              'cancellations at the bounded phase end are retained separately from successful measured requests.', '',
              ('The first worker survived scale-out; initial cache occupancy can differ. Every CLI run used its normal fresh '
               'benchmark prefix namespace. This changes capacity and placement opportunities together.') if not args.routing else
              ('Both policies started with fresh worker processes and the same primer. Only frontend routing mode changed. '
               'KV event ingress and actual predicted-hit observations must accompany any claimed routing benefit.'), '',
              'A single pair does not establish a distribution, production readiness, maximum capacity or a universal speedup.']
    report.write_text('\n'.join(lines) + '\n')
    print(json.dumps({'analysis': str(destination), 'report': str(report), 'ratios': comparison['second_over_first']}, indent=2))


if __name__ == '__main__':
    main()
