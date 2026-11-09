#!/usr/bin/env python3
"""Verify pinned metric sources and all recorded C4 formulas; freeze a receipt."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import demos.common.runtime as ui
import demos.routing.demo as routing


def freeze(output):
    routing.require(not output.exists(), 'Definition receipts are immutable; use a fresh output path.')
    location = ui.read_json(ROOT / 'reports/workshop-measurements-20261030/agentx-workload/source-location.json')
    archive = Path(location['pinned_source_archive'])
    routing.require(ui.digest(archive) == location['pinned_source_sha256'], 'Pinned AIPerf archive changed.')
    names = ['metrics/types/output_token_throughput_metrics.py', 'metrics/types/inter_token_latency_metric.py',
             'metrics/types/ttft_metric.py', 'metrics/types/request_latency_metric.py',
             'metrics/types/benchmark_duration_metric.py', 'metrics/metric_dicts.py',
             'config/endpoint.py', 'records/inference_result_parser.py']
    source_hashes = {}
    with tarfile.open(archive) as contents:
        for name in names:
            path = 'src/aiperf/' + name
            matches = [m for m in contents.getmembers() if m.name == path and m.isfile()]
            routing.require(len(matches) == 1, 'Missing or ambiguous pinned source: ' + path)
            source_hashes[path] = hashlib.sha256(contents.extractfile(matches[0]).read()).hexdigest()
    arm = ROOT / 'results/workshop-c4-closeout-20261104-a1/verified/results/workshop-rr-20261103-resume02/c4-r1-a1'
    raw = arm / 'raw/c4-r1-a1/artifacts/profile_export.jsonl'
    inventory = ui.read_json(arm / 'integrity-final.json')['sha256']
    routing.require(ui.digest(raw) == inventory[str(raw.relative_to(arm))], 'Per-request source inventory changed.')
    count, mismatches, rates, itls = 0, 0, [], []
    for line in raw.read_text().splitlines():
        value = json.loads(line)
        if value['metadata'].get('phase_kind') != 'profiling':
            continue
        metrics = {key: item['value'] for key, item in value['metrics'].items()}
        itl = (metrics['request_latency'] - metrics['time_to_first_token']) / (metrics['output_sequence_length'] - 1)
        mismatches += int(not math.isclose(itl, metrics['inter_token_latency'], rel_tol=1e-10))
        mismatches += int(not math.isclose(1000 / itl, metrics['output_token_throughput_per_user'], rel_tol=1e-10))
        rates.append(metrics['output_token_throughput_per_user'])
        itls.append(itl)
        count += 1
    export = ui.read_json(routing.BUNDLE / 'scaleout-arm1-aiperf.json')
    routing.require(count == export['request_count']['avg'] and mismatches == 0, 'Recorded formulas do not reproduce.')
    routing.require(math.isclose(sum(rates) / count, export['output_token_throughput_per_user']['avg'], rel_tol=1e-12),
                    'Export is not the average of per-request rates.')
    value = {'schema': 1, 'verified_at': ui.now(), 'aiperf_commit': location['source_commit'],
        'source_archive': str(archive.relative_to(ROOT)), 'source_archive_sha256': location['pinned_source_sha256'],
        'source_files_sha256': source_hashes,
        'definitions': {
            'ttft': 'first content timestamp - request start timestamp',
            'request_latency': 'last content timestamp - request start timestamp; usage-only trailer excluded',
            'itl_general': '(request_latency - ttft) / (output_sequence_length - first_content_chunk_tokens)',
            'itl_this_run': '(request_latency - ttft) / (output_sequence_length - 1)',
            'first_chunk_convention': 'per_chunk_usage is False in this run; parser leaves first_content_chunk_tokens=None '
                'and ITL falls back to OSL-1. This assumes one token in the first content chunk. With opt-in per-chunk '
                'usage, a valid reported first-chunk count is subtracted; inconsistent counts fall back with a warning.',
            'per_request_rate': '1 / ITL_seconds; mean is the arithmetic average of per-record rates',
            'itl_percentiles': 'percentiles of one mean-interval value per request, not pooled individual token gaps',
            'canonical_output_rate': 'total_osl / observation_duration; explicit analysis-window duration when set, '
                'otherwise BenchmarkDurationMetric',
            'benchmark_duration': 'maximum response timestamp - minimum request timestamp',
            'cache_read_percentage': '100 * total server-reported cache-read prompt tokens / total server-reported prompt tokens'},
        'record_formula_check': {'source': str(raw.relative_to(ROOT)), 'source_sha256': ui.digest(raw),
            'records': count, 'formula_mismatches': mismatches, 'mean_per_request_rate': sum(rates) / count,
            'mean_request_itl_ms': sum(itls) / count, 'inverse_mean_itl_tokens_per_second': 1000 / (sum(itls) / count)},
        'scope': 'Source definitions and offline reproduction of existing measured records; no new benchmark or GPU use.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'source_files': len(source_hashes), 'records': count,
                      'formula_mismatches': mismatches, 'sha256': ui.digest(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    freeze(parser.parse_args().output.resolve())
