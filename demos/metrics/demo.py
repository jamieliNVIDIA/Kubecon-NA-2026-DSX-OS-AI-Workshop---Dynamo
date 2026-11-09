#!/usr/bin/env python3
"""Four-minute recorded AgentX workload and inference-metrics walkthrough."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import time

import yaml

import demos.common.runtime as ui
import demos.routing.demo as routing

ROOT = ui.ROOT
PROFILE = 'agentx-metrics-recorded-c4-one-worker-v1'
DEFINITIONS = ROOT / 'demos/metrics/metric-definitions.json'
STEPS = [
    ('What did AIPerf send?', 'Replay coding-agent trees; distinguish tree concurrency from active inference requests.'),
    ('What did a user experience?', 'Read first-content latency, inter-token latency and per-request generation rate.'),
    ('What did the service do?', 'Read throughput, GPU normalization and cache reuse with their actual denominators.'),
]


def validated_metrics(recording, definitions):
    metadata, studies, _, _, _ = routing.load_recording(recording)
    row = studies['scaleout']['arms'][0]
    raw = ui.read_json(recording / 'scaleout-arm1-aiperf.json')
    require = routing.require
    require(definitions['schema'] == 1 and definitions['aiperf_commit'] == row['spec']['aiperf_commit'] and
            definitions['record_formula_check']['records'] == row['requests'] and
            definitions['record_formula_check']['formula_mismatches'] == 0,
            'Metric definitions do not match the qualified recording.')
    config = raw['input_config']
    phase = config['phases'][0]
    require(config['endpoint']['streaming'] and config['endpoint']['use_server_token_count'] and
            not config['endpoint'].get('per_chunk_usage', False), 'Recorded token-count/streaming convention changed.')
    require(config['scenario'] == 'inferencex-agentx-mvp' and phase['concurrency'] == 4 and
            phase['duration'] == 900 and phase['grace_period'] == 300, 'Unexpected recorded AgentX controls.')
    require(config['models']['items'][0]['name'] == row['spec']['model'] and
            config['tokenizer']['revision'] == row['spec']['model_revision'] and
            row['spec']['replicas'] == 1 and row['spec']['h100_gpus'] == 2, 'Unexpected recorded model or GPU topology.')
    def metric(name, stat='avg'):
        value = raw[name][stat]
        require(isinstance(value, (int, float)) and math.isfinite(value) and value >= 0,
                'Invalid exported metric: ' + name)
        return value
    cache_read, prompt = metric('total_usage_prompt_cache_read_tokens'), metric('total_usage_prompt_tokens')
    require(prompt > 0 and math.isclose(cache_read / prompt * 100, metric('overall_usage_prompt_cache_read_pct'), rel_tol=1e-12),
            'Cache-read percentage differs from server-reported token totals.')
    aggregate = metric('output_token_throughput')
    require(aggregate > 0, 'Aggregate throughput must be positive.')
    result = {'schema': 1, 'presentation_mode': 'recorded-evidence', 'simulated': False,
        'measurement_class': 'historical-low-load-pilot', 'recording_sha256': ui.digest(recording / 'recording.json'),
        'arm': row['arm'], 'benchmark_id': raw['benchmark_id'], 'model': row['spec']['model'],
        'model_revision': row['spec']['model_revision'], 'runtime_image': row['spec']['runtime_image'],
        'aiperf_commit': row['spec']['aiperf_commit'], 'dataset_revision': row['spec']['dataset_revision'],
        'agent_tree_concurrency': phase['concurrency'], 'h100_gpus': row['spec']['h100_gpus'],
        'requests': metric('request_count'), 'request_errors': row['request_error_count'],
        'ttft_p50_ms': metric('time_to_first_token', 'p50'), 'ttft_p99_ms': metric('time_to_first_token', 'p99'),
        'itl_p50_ms': metric('inter_token_latency', 'p50'), 'itl_p99_ms': metric('inter_token_latency', 'p99'),
        'mean_per_request_decode_tokens_per_second': metric('output_token_throughput_per_user'),
        'canonical_output_tokens_per_second': aggregate,
        'canonical_output_tokens_per_second_per_gpu': aggregate / row['spec']['h100_gpus'],
        'output_tokens': metric('total_osl'), 'server_prompt_tokens': prompt,
        'server_cache_read_tokens': cache_read, 'server_cache_read_percent': metric('overall_usage_prompt_cache_read_pct'),
        'admission_seconds': phase['duration'], 'grace_bound_seconds': phase['grace_period'],
        'canonical_rate_denominator_seconds': metric('total_osl') / aggregate,
        'observed_request_span_seconds': metric('benchmark_duration'),
        'scope': 'One recorded fixed-load C4 pilot, N=1; partial replay trees. '
                 'GPU-normalized observed rate includes the canonical drain window and is not peak capacity.'}
    require(math.isclose(result['canonical_rate_denominator_seconds'], row['canonical_throughput_denominator_seconds'], rel_tol=1e-12),
            'Canonical denominator differs from source analysis.')
    return result, config, metadata


def write_views(path, metrics, config):
    phase = config['phases'][0]
    workload = {'scenario': config['scenario'], 'datasets': [{'dataset': config['datasets'][0]['dataset']}],
                'phases': [{key: phase[key] for key in ('type', 'concurrency', 'duration', 'grace_period', 'timing_mode')}]}
    (path / 'workload.txt').write_text(
        'RECORDED: one Super VL TP2 worker / 2 H100s / AgentX C4.\n' +
        'Recorded command shape: aiperf profile --config profile.yaml\n\n' +
        yaml.safe_dump(workload, sort_keys=False) + '\n' +
        'One coding-agent tree contains many inference requests and tool waits.\n' +
        'Branches can add parallel requests. C4 is not four active HTTP requests.\n' +
        'Both use concurrency, but the counted unit matters.\n' +
        'This is the same pinned full AgentX corpus used in the scaling pilots.\n' +
        'The recorded run sampled partial trees; it did not complete coding tasks.\n')
    (path / 'user-metrics.txt').write_text(
        'RECORDED: user-visible latency and active generation\n\n' +
        f'Accepted measured requests               {metrics["requests"]:10.0f}\n' +
        f'Reported request errors                  {metrics["request_errors"]:10.0f}\n' +
        f'TTFT p50 / p99 (ms)                {metrics["ttft_p50_ms"]:8.2f} / {metrics["ttft_p99_ms"]:8.2f}\n' +
        f'ITL p50 / p99 (ms per token)        {metrics["itl_p50_ms"]:8.2f} / {metrics["itl_p99_ms"]:8.2f}\n' +
        f'Mean decode tokens/s/request             {metrics["mean_per_request_decode_tokens_per_second"]:10.2f}\n\n' +
        'TTFT: request start -> first content chunk.\n' +
        'ITL: (last content time - first content time) / (output tokens - 1).\n' +
        'This run assumes one token in the first chunk; per-chunk usage was off.\n' +
        'Rate per request = 1 / ITL_seconds; the shown mean averages those rates.\n' +
        'ITL percentiles summarize request-average gaps, not all token gaps.\n' +
        'These generation rates exclude TTFT, queueing before first content,\n' +
        'and tool waits. They are not end-to-end agent speed.\n')
    (path / 'service-metrics.txt').write_text(
        'RECORDED: service rate and prefix reuse\n\n' +
        f'Canonical output tokens/s                {metrics["canonical_output_tokens_per_second"]:10.2f}\n' +
        f'Observed output tokens/s/H100             {metrics["canonical_output_tokens_per_second_per_gpu"]:10.2f}\n' +
        f'Completed output tokens                  {metrics["output_tokens"]:10,.0f}\n' +
        f'Server prompt tokens (sum over requests)  {metrics["server_prompt_tokens"]:10,.0f}\n' +
        f'Server cache-read prompt tokens          {metrics["server_cache_read_tokens"]:10,.0f}\n' +
        f'Cache read / prompt tokens (%)           {metrics["server_cache_read_percent"]:10.2f}\n\n' +
        f'Admission / grace bound: {metrics["admission_seconds"]:.0f} / {metrics["grace_bound_seconds"]:.0f} s\n' +
        f'Canonical rate denominator: {metrics["canonical_rate_denominator_seconds"]:.2f} s\n' +
        f'Observed request span:       {metrics["observed_request_span_seconds"]:.2f} s\n\n' +
        'Aggregate rate = completed output tokens / canonical observation window.\n' +
        'Per-GPU rate divides that observed rate by the two assigned H100s.\n' +
        'Tool waits and drain count here; this is not peak GPU capacity.\n' +
        'Prompt totals include repeated context; cache-read is server-reported.\n' +
        'More cache reuse saves prefill work, not generation of each new token.\n' +
        'Do not divide aggregate rate by C4 to infer generation speed per user.\n' +
        'Scaling asks how these measures change as load grows. No curve is\n' +
        'inferred from this single low-load observation.\n')
    ui.write_json(path / 'metrics-proof.json', metrics)
    ui.write_json(path / 'aiperf-effective-config.json', config)


class MetricsDemo(ui.Demo):
    pane_titles = ('Walkthrough', 'AgentX metrics', 'Metric definitions')
    """Present recorded AgentX metrics; never contact a cluster or run AIPerf."""
    entrypoint = Path(__file__).resolve()
    compact_output = True

    def __init__(self, args):
        from testlib import Run
        self.args = args
        self.run = Run(args.run or ROOT / 'results' / ('demo-09-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
        self.path, self.file, self.forward = self.run.path, self.run.path / 'demo.json', None
        if self.file.exists():
            self.data = ui.read_json(self.file)
            routing.require(self.data.get('metrics_profile') == PROFILE and self.data['rehearsal'] == args.rehearsal,
                            'Use a fresh run for a different metrics profile or mode.')
            self.check_inputs()
        else:
            metadata, _, _, _, _ = routing.load_recording(routing.BUNDLE)
            destination = self.path / 'recording'
            destination.mkdir()
            for name in ['recording.json'] + list(metadata['files_sha256']):
                (destination / name).write_bytes(routing.relative_file(routing.BUNDLE, name).read_bytes())
            (self.path / 'metric-definitions.json').write_bytes(DEFINITIONS.read_bytes())
            metrics, config, _ = validated_metrics(destination, ui.read_json(self.path / 'metric-definitions.json'))
            self.data = {'schema': 1, 'metrics_profile': PROFILE, 'demo_kind': 'agentx-metrics',
                         'presentation_mode': 'recorded-evidence', 'rehearsal': args.rehearsal,
                         'namespace': 'dynamo-ft-recorded-metrics', 'created_at': ui.now(), 'prepared': False,
                         'model': metrics['model'], 'step': 0}
            write_views(self.path, metrics, config)
            self.data['inputs_sha256'] = {str(p.relative_to(self.path)): ui.digest(p) for p in self.path.rglob('*')
                                        if p.is_file() and p.name not in ('state.json', '.state.lock')}
            self.save()
        self.ns = self.data['namespace']

    def check_inputs(self):
        for name, expected in self.data['inputs_sha256'].items():
            routing.require(ui.digest(routing.relative_file(self.path, name)) == expected, 'Prepared metrics changed: ' + name)
        measured, _, _ = validated_metrics(self.path / 'recording', ui.read_json(self.path / 'metric-definitions.json'))
        routing.require(measured == ui.read_json(self.path / 'metrics-proof.json'), 'Prepared metrics differ from source exports.')

    def prepare(self):
        self.check_inputs()
        self.data['prepared'] = True
        self.save()
        print('Historical exports, metric definitions and derived values verified; no cluster calls.')

    prime = prepare

    def preview(self):
        self.check_inputs()
        print('RECORDED EVIDENCE / NO CLUSTER CALLS\n')
        for index, (title, explanation) in enumerate(STEPS, 1):
            print(f'{index}. {title}: {explanation}')
        print('\n' + (self.path / 'workload.txt').read_text())

    def guided(self):
        self.require_prepared()
        self.check_inputs()
        routing.require(self.args.auto or sys.stdin.isatty(), 'Interactive steps need a terminal; use --plain --auto.')
        print('\nDynamo workshop · Workload and metrics\n' +
              ('REHEARSAL OF ' if self.args.rehearsal else '') + 'RECORDED EVIDENCE / NO CLUSTER CALLS\n' +
              'Run: ' + ui.repo_path(self.path), flush=True)
        for index, ((title, explanation), name) in enumerate(zip(STEPS,
                ('workload.txt', 'user-metrics.txt', 'service-metrics.txt')), 1):
            print(f'\nNext: {index}/{len(STEPS)}  {title}', flush=True)
            self.pause()
            if sys.stdout.isatty():
                print('\033[2J\033[H', end='', flush=True)
            print(f'\n{"=" * 64}\n{index}/{len(STEPS)}  {title}\n{explanation}\n{"=" * 64}', flush=True)
            self.data['step'] = index
            self.save()
            self.check_inputs()
            self.command(['cat', self.path / name])
        self.data['completed_at'] = ui.now()
        self.save()
        print('\nRecorded metrics investigation complete. No cluster resources were created.')
        print('Resume: ' + shlex.join(ui.presenter_command(self.entrypoint, '--run', ui.repo_path(self.path)) +
                                     (['--rehearsal'] if self.args.rehearsal else [])))

    def cleanup(self):
        self.check_inputs()
        print('No cluster resources or GPU reservations. Metrics and presenter evidence retained.')


def observe(path, view, once=False):
    path = path.resolve()
    while True:
        data = ui.read_json(path / 'demo.json')
        metrics = ui.read_json(path / 'metrics-proof.json')
        print('\033[2J\033[HRECORDED EVIDENCE / NO CLUSTER CALLS', flush=True)
        if view == 'resources':
            print('Recorded: one worker / TP2 / 2 H100s\nAgentX C4 = four concurrent trees, not four HTTP requests\n' +
                  'One 900s admission + up to 300s drain pilot\nNo scaling curve or capacity result\n\n' +
                  'Current step: ' + str(data['step']) + '/3\nBenchmark: ' + metrics['benchmark_id'])
        else:
            print('Pinned metric semantics\n\nTTFT: request start -> first content\n' +
                  'ITL: content-generation window / (OSL - 1)\nRate/request: inverse ITL, then average\n' +
                  'Aggregate: output tokens / observation window\nCache read: server-reported prompt reuse\n\n' +
                  'First-token/chunk convention: see metric-definitions.json')
        if once:
            return
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run', choices=['run', 'prepare', 'prime', 'preview', 'cleanup', 'observe', 'hold'])
    parser.add_argument('--run', type=Path)
    for flag in ('rehearsal', 'preview', 'plain', 'auto', 'detach', 'once'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    parser.add_argument('--port', type=int, default=18009, help=argparse.SUPPRESS)
    parser.add_argument('--timeout', type=int, default=60, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == 'hold':
        while True:
            time.sleep(60)
    if args.action == 'observe':
        routing.require(args.run is not None, 'observe requires --run')
        observe(args.run, args.view, args.once)
        return
    demo = MetricsDemo(args)
    print('Demo files: ' + str(demo.path), flush=True)
    if args.preview or args.action == 'preview':
        demo.preview()
    elif args.action in ('prepare', 'prime', 'cleanup'):
        with ui.presenter_lock(demo.path):
            getattr(demo, args.action)()
    else:
        demo.require_prepared()
        if args.plain:
            with ui.presenter_lock(demo.path):
                demo.guided()
        else:
            ui.tmux_layout(demo)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Recorded metrics are retained; no cluster resources were created.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('\nDemo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
