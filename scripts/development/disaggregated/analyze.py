#!/usr/bin/env python3
"""Analyze a sealed matched AgentX P/D pair, retaining denominators and mix.

Never promote an incomplete/errored profile to a speedup. Counter/gauge series
remain per endpoint; P/D phase work must not be counted as extra user requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import yaml


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4194304), b''):
            h.update(chunk)
    return h.hexdigest()


def value(data, name, statistic='avg'):
    return (data.get(name) or {}).get(statistic)


def normalized_profile(path):
    result = yaml.safe_load(Path(path).read_text())
    config = result['benchmark']
    config['endpoint']['urls'] = ['ENDPOINT']
    config['artifacts']['dir'] = 'ARTIFACTS'
    config['server_metrics']['urls'] = ['WORKER_METRICS']
    return result


def derive_metrics(data, gpu_count):
    if gpu_count != 4:
        raise ValueError('This matched comparison requires four H100s in each arm.')
    if (data.get('is_complete') is not True or data.get('was_cancelled') is not False or
            (data.get('metadata') or {}).get('submission_valid') is not True or
            data.get('runtime_submission_invalid_reasons') or data.get('error_summary') or
            (value(data, 'error_request_count') or 0) or (value(data, 'context_overflow_count') or 0)):
        raise ValueError('Profile is incomplete, invalid, or has request/context errors.')
    throughput, tokens = value(data, 'output_token_throughput'), value(data, 'total_osl')
    requests = value(data, 'request_count')
    if not requests or requests <= 0 or not throughput or throughput <= 0 or not tokens or tokens <= 0:
        raise ValueError('A positive successful request/token measurement is required.')
    return {
        'successful_requests': requests,
        'output_tokens': tokens, 'input_tokens': value(data, 'total_isl'),
        'output_tokens_per_second': throughput,
        'output_tokens_per_second_per_gpu': throughput / gpu_count,
        'exported_throughput_denominator_seconds': tokens / throughput,
        'benchmark_duration_metric_seconds': value(data, 'benchmark_duration'),
        'ttft_p50_ms': value(data, 'time_to_first_token', 'p50'),
        'ttft_p99_ms': value(data, 'time_to_first_token', 'p99'),
        'itl_p50_ms': value(data, 'inter_token_latency', 'p50'),
        'itl_p99_ms': value(data, 'inter_token_latency', 'p99'),
        'decode_tokens_per_second_per_user_mean': value(data, 'output_token_throughput_per_user'),
        'decode_tokens_per_second_per_user_p50': value(data, 'output_token_throughput_per_user', 'p50'),
        'mean_input_tokens': value(data, 'input_sequence_length'),
        'mean_output_tokens': value(data, 'output_sequence_length'),
        'server_reported_cache_read_pct': value(data, 'overall_usage_prompt_cache_read_pct'),
        'structural_prefix_hit_pct': value(data, 'theoretical_prefix_cache_hit'),
    }


def load_arm(folder, campaign_hash):
    spec = json.loads((folder / 'spec.json').read_text())
    if spec['campaign_sha256'] != campaign_hash or spec['profile_sha256'] != sha(folder / 'profile.yaml'):
        raise ValueError('Sealed campaign/profile identity changed: ' + str(folder))
    for name in ('integrity.json', 'integrity-final.json'):
        for relative, digest in json.loads((folder / name).read_text()).items():
            if sha(folder / relative) != digest:
                raise ValueError('Collected evidence changed: ' + str(folder / relative))
    qualification = json.loads((folder / 'worker-qualification.json').read_text())
    if qualification.get('passed') is not True:
        raise ValueError('Worker qualification is missing or failed.')
    for pod in spec['worker_pods']:
        text = (folder / (pod['name'] + '.log')).read_text()
        if ('running in text-only mode' not in text or
                not re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)', text)):
            raise ValueError('Actual native context/text-only startup evidence is missing.')
    paths = [p for p in (folder / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
    if len(paths) != 1:
        raise ValueError('Need exactly one main AIPerf export.')
    data = json.loads(paths[0].read_text())
    result = {'arm': folder.name, 'spec_sha256': sha(folder / 'spec.json'),
        'export_sha256': sha(paths[0]), 'benchmark_id': data.get('benchmark_id'),
        'metrics': derive_metrics(data, spec['gpus_per_topology']),
        'branch_stats': data.get('branch_stats'), 'source_trace_mix': {},
        'profiling_records': 0, 'cancelled_profile_records': 0,
        'submitted_tree_count': None, 'export_metadata': data.get('metadata')}
    roots = set()
    for path in (folder / 'raw').rglob('profile_export.jsonl'):
        with path.open() as stream:
            for line in stream:
                meta = json.loads(line).get('metadata', {})
                if meta.get('phase_kind', meta.get('benchmark_phase')) != 'profiling':
                    continue
                result['profiling_records'] += 1
                result['cancelled_profile_records'] += bool(meta.get('was_cancelled'))
                root = meta.get('root_correlation_id')
                if root:
                    roots.add(root)
                identity = str(meta.get('source_trace_id'))
                entry = result['source_trace_mix'].setdefault(identity, {'records': 0, 'source_kinds': {}})
                entry['records'] += 1
                kind = str(meta.get('source_kind'))
                entry['source_kinds'][kind] = entry['source_kinds'].get(kind, 0) + 1
                if meta.get('context_overflow_skip'):
                    raise ValueError('A profiling record skipped a context overflow.')
    if result['profiling_records'] - result['cancelled_profile_records'] != result['metrics']['successful_requests']:
        raise ValueError('Per-request record accounting differs from exported successful count.')
    result['sampled_root_ids'] = sorted(roots)
    server_paths = list((folder / 'raw').rglob('server_metrics_export.json'))
    if len(server_paths) != 1:
        raise ValueError('Need exactly one server metrics export.')
    server = json.loads(server_paths[0].read_text())
    phase = server['summary']['phase_time_ranges']['profiling']
    profile = yaml.safe_load((folder / 'profile.yaml').read_text())['benchmark']['phases'][0]
    result['admission_seconds'] = profile['duration']
    result['bounded_drain_seconds'] = profile['grace_period']
    result['server_phase_window_seconds'] = (phase['end_ns'] - phase['start_ns']) / 1e9
    wanted = ('requests_running', 'requests_waiting', 'cache_usage', 'preemptions', 'nixl', 'router_kv_hit')
    result['server_series'] = {name: metric for name, metric in server.get('metrics', {}).items()
                               if any(token in name for token in wanted)}
    smoke = json.loads((folder / 'endpoint-smoke.json').read_text())
    result['smoke_worker_ids'] = [v.get('nvext', {}).get('worker_id') for v in smoke['responses']]
    return result


def analyze(run):
    campaign = json.loads((run / 'campaign.json').read_text())
    arms_by_role = campaign.get('arm_names', {topology: topology + '-c16-a1'
                                             for topology in ('aggregate', 'disaggregated')})
    paths = [run / arms_by_role[topology] for topology in ('aggregate', 'disaggregated')]
    if normalized_profile(paths[0] / 'profile.yaml') != normalized_profile(paths[1] / 'profile.yaml'):
        raise ValueError('Workload profiles differ beyond endpoint/artifact/metric addresses.')
    arms = [load_arm(path, sha(run / 'campaign.json')) for path in paths]
    result = {'status': 'accepted_exploratory_pair', 'campaign_sha256': sha(run / 'campaign.json'),
        'gpu_uuids_by_node': campaign['gpu_uuids_by_node'], 'concurrency_session_trees': 16,
        'routing_controls': campaign['routing_tuning'],
        'serving_path_differences': [
            'Aggregate uses two general TP2 workers with KV-aware routing; P/D uses one TP2 pool of each role.',
            'P/D requires its NIXL/EFA connector settings and explicitly sets VLLM_SSM_CONV_STATE_LAYOUT=DS; aggregate leaves that variable unset.'],
        'arms': arms, 'limits': [
            'N=1 and fixed aggregate-then-P/D order; no significance or maximum-capacity conclusion.',
            'Other workshop jobs share CPU, storage, PCIe and network; GPU identities are disjoint.',
            'C16 counts live AgentX trees, not HTTP request concurrency.',
            'Trace-turn mix and completion/cancellation can differ under duration-bound replay.',
            'Canonical throughput uses its exported denominator; admission is 900 seconds plus bounded drain.',
            'Worker/phase request counters do not increase the logical user-request count.',
            'Structural prefix reuse is not observed backend cache reuse.',
            'JSONL preserves streaming metrics/metadata, not literal SSE bodies or generated answers; smoke uses nonstreaming responses.',
            'The original local controller receipt remains blocked after observer transport loss; separate recovery receipts qualify the original unreplayed P/D profile.',
            'A balanced P/D split is one configuration, not optimized independent pool sizing.']}
    output = run / 'comparison.json'
    with output.open('x') as stream:
        json.dump(result, stream, indent=2)
    rows = [
        ('Successful requests', 'successful_requests'),
        ('Output tokens/s, all four GPUs', 'output_tokens_per_second'),
        ('Output tokens/s/GPU', 'output_tokens_per_second_per_gpu'),
        ('Mean generation tokens/s/user', 'decode_tokens_per_second_per_user_mean'),
        ('TTFT p50 (ms)', 'ttft_p50_ms'), ('TTFT p99 (ms)', 'ttft_p99_ms'),
        ('ITL p50 (ms)', 'itl_p50_ms'), ('ITL p99 (ms)', 'itl_p99_ms'),
        ('Mean input tokens', 'mean_input_tokens'), ('Mean output tokens', 'mean_output_tokens'),
        ('Server-reported cache-read percent', 'server_reported_cache_read_pct'),
        ('Exported throughput denominator (s)', 'exported_throughput_denominator_seconds'),
    ]

    def number(v):
        return 'unavailable' if v is None else f'{v:,.2f}'

    lines = ['# Matched four-H100 AgentX comparison', '',
        'C16 live session trees; 900-second admission plus 300-second bounded drain.', '',
        '| Metric | Two aggregated TP2 workers | TP2 prefill + TP2 decode |',
        '| --- | ---: | ---: |']
    for label, key in rows:
        lines.append('| ' + label + ' | ' + ' | '.join(number(arm['metrics'][key]) for arm in arms) + ' |')
    lines += ['', 'Fixed-order, N=1 exploratory measurements. The exact spec, source hashes,',
              'realized trace mix, cancellations and full precision are retained in comparison.json.', '',
              *['- ' + difference for difference in result['serving_path_differences']], '',
              *['- ' + limit for limit in result['limits']], '']
    with (run / 'comparison.md').open('x') as stream:
        stream.write('\n'.join(lines))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.run.resolve())
    print(json.dumps({'status': result['status'], 'arms': [{'arm': v['arm'], **v['metrics']} for v in result['arms']]}, indent=2))


if __name__ == '__main__':
    main()
