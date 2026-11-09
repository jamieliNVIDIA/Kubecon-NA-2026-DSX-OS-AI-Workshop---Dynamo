#!/usr/bin/env python3
"""Analyze collected immutable cells, keeping failed/stress cells out of ratios."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'reports/workshop-measurements-20261030/round-robin/analyze.py'
module = importlib.util.spec_from_file_location('agentx_base_analysis', SOURCE)
base = importlib.util.module_from_spec(module)
module.loader.exec_module(base)

PRESSURE = (
    'vllm:num_requests_running', 'vllm:num_requests_waiting',
    'vllm:num_requests_waiting_by_reason', 'vllm:kv_cache_usage_perc',
    'vllm:num_preemptions', 'vllm:prefix_cache_hits', 'vllm:prefix_cache_queries',
    'vllm:prompt_tokens_cached', 'vllm:request_queue_time_seconds',
    'vllm:request_prefill_time_seconds', 'vllm:request_decode_time_seconds',
    'dynamo_frontend_active_requests', 'dynamo_frontend_queued_requests',
    'dynamo_component_gpu_cache_usage_percent',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cell(path):
    row = {'arm': path.name, 'status': 'not_collected', 'eligible': False}
    required = ('summary.json', 'worker-qualification.json', 'discovery-qualification.json',
                'integrity-final.json', 'profile.yaml', 'spec.json')
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        row['missing'] = missing
        return row
    integrity = json.loads((path / 'integrity-final.json').read_text())['sha256']
    for name, expected in integrity.items():
        if sha(path / name) != expected:
            raise ValueError('Collected cell changed: ' + str(path / name))
    summary = json.loads((path / 'summary.json').read_text())
    worker = json.loads((path / 'worker-qualification.json').read_text())
    discovery = json.loads((path / 'discovery-qualification.json').read_text())
    row.update(status=summary['outcome'], summary=summary,
               eligible=bool(summary.get('clean_comparison_eligible') and worker.get('passed')
                             and discovery.get('passed')),
               source_files={name: sha(path / name) for name in required})
    if not row['eligible']:
        return row
    facts = base.load_arm(path)
    # Per-record cancellation is stronger than a process/export completion bit.
    if facts['cancelled_profile_records']:
        row.update(eligible=False, status='cancelled_profile_records', metrics=facts)
        return row
    files = list((path / 'raw').rglob('server_metrics_export.json'))
    if len(files) != 1:
        raise ValueError('Need one server metrics export per cell.')
    server = json.loads(files[0].read_text())
    facts['pressure_series'] = {name: server.get('metrics', {}).get(name)
                                for name in PRESSURE if name in server.get('metrics', {})}
    facts['all_completed_output_tokens_over_900s_admission'] = (
        facts['output_tokens'] / facts['profile_seconds'])
    facts['admission_denominator_caveat'] = (
        'Numerator includes completions in the grace/drain tail. This derived '
        'rate does not measure tokens emitted strictly inside admission.')
    facts['event_discovery_proof'] = discovery
    facts['worker_configuration_proof'] = worker
    if facts['spec']['router_mode'] == 'kv' and not (
            facts['predicted_kv_hit_histogram_count'] > 0 and
            facts['predicted_kv_hit_histogram_sum'] > 0):
        row.update(eligible=False, status='missing_positive_kv_overlap', metrics=facts)
        return row
    row['metrics'] = facts
    return row


def comparisons(run, rows):
    result = []
    by_name = {row['arm']: row for row in rows}
    for n in (16, 32):
        for kind, names in (
            ('scaleout', (f'one-rr-c{n}-a1', f'two-rr-c{n}-a1')),
            ('routing', (f'two-rr-c{n}-a1', f'two-kv-c{n}-a1')),
        ):
            pair = [by_name[name] for name in names]
            item = {'kind': kind, 'concurrency_session_trees': n, 'arms': names,
                    'eligible': all(row['eligible'] for row in pair)}
            if item['eligible']:
                a, b = [row['metrics'] for row in pair]
                if base.normalized_profile(run / names[0]) != base.normalized_profile(run / names[1]):
                    raise ValueError('Workload settings differ: ' + repr(names))
                for key in ('model', 'model_revision', 'runtime_image', 'dataset_revision',
                            'dataset_sha256', 'aiperf_commit', 'dataset_pin_patch_sha256',
                            'concurrency_session_trees', 'native_max_model_len',
                            'max_num_seqs_per_worker', 'client_preprocessor_workers'):
                    if a['spec'][key] != b['spec'][key]:
                        raise ValueError('Comparison controls differ: ' + key)
                keys = ('output_tokens_per_second', 'decode_tokens_per_second_per_user_mean',
                        'ttft_p50_ms', 'ttft_p99_ms', 'server_reported_cache_read_pct')
                item['second_over_first'] = {key: b[key] / a[key] if a[key] else None for key in keys}
                item['canonical_rate_denominators_differ'] = abs(
                    a['canonical_throughput_denominator_seconds'] -
                    b['canonical_throughput_denominator_seconds']) > 1
            else:
                item['reasons'] = {row['arm']: row['status'] for row in pair if not row['eligible']}
            result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    campaign = json.loads((run / 'campaign.json').read_text())
    if sha(run / 'campaign.json') != (run / 'campaign.sha256').read_text().strip():
        raise ValueError('Campaign fingerprint changed.')
    rows = [cell(run / item['arm']) for item in campaign['sequence']]
    state = json.loads((run / 'state.json').read_text()) if (run / 'state.json').exists() else {}
    for row in rows:
        if row['eligible']:
            continue
        key = 'configuration-' + row['arm'].rsplit('-a1', 1)[0]
        check = state.get('checks', {}).get(key)
        if check and check.get('status') == 'stopped':
            row.update(status='failed', failure=check)
        elif not (run / row['arm']).exists():
            row['status'] = 'not_started'
    value = {'schema': 1, 'campaign_sha256': sha(run / 'campaign.json'),
             'campaign': campaign, 'cells': rows, 'comparisons': comparisons(run, rows),
             'saved_gpu_cleanup': state.get('checks', {}).get('rr-gpu-cleanup'),
             'cell_cleanup_receipts': {p.name: json.loads(p.read_text()) for p in run.glob('after-*-cleanup.json')},
             'limits': ['N=1, topology-first fixed order, fresh workers per cell',
                        'Concurrent disjoint-GPU tests share node CPU, EFS and network',
                        'Realized source trace/turn mixes and drain denominators can differ',
                        'Live AgentX tree concurrency differs from active HTTP requests',
                        'No SLO, peak-capacity, production-readiness or universal-speedup claim']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'output': str(args.output), 'cells': len(rows),
                      'eligible_cells': sum(row['eligible'] for row in rows),
                      'eligible_pairs': sum(row['eligible'] for row in value['comparisons'])}))


if __name__ == '__main__':
    main()
