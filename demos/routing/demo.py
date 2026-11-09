#!/usr/bin/env python3
"""Recorded AgentX investigation: replica count, cache locality, and routing."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

import yaml

import demos.common.runtime as ui

ROOT = ui.ROOT
BUNDLE = ROOT / 'demos/routing/recording'
PROFILE = 'agentx-routing-recorded-c4-scaleout-c1-policy-v1'
C16_BUNDLE = ROOT / 'demos/routing/recording-c16'
C16_PROFILE = 'agentx-routing-recorded-c16-fresh-workers-v1'
RECORDING_FILES = {
    'scaleout-analysis.json', 'policy-analysis.json', 'scaleout-verification.json', 'policy-verification.json',
    'scaleout-arm1-aiperf.json', 'scaleout-arm2-aiperf.json', 'policy-arm1-aiperf.json', 'policy-arm2-aiperf.json',
    'policy-round-robin-deployment.json', 'policy-kv-deployment.json', 'policy-kv-discovery.json',
}
STEPS = [
    ('Add a replica: what changed?', 'Inspect a recorded AgentX scale-out pair; capacity and cache placement change together.'),
    ('Follow the cache metadata', 'Workers publish residency updates; the frontend uses them to select a worker.'),
    ('Change the routing policy', 'Compare a separate, matched two-worker RR/KV observation at C1.'),
    ('A warm worker can also be busy', 'Balance reuse against load, then ask whether the cached state can move.'),
]
COMMON_CONTROLS = ('model', 'model_revision', 'runtime_image', 'dataset_revision', 'dataset_sha256',
                   'aiperf_commit', 'dataset_pin_patch_sha256', 'concurrency_session_trees',
                   'native_max_model_len', 'max_num_seqs_per_worker', 'client_preprocessor_workers')
METRICS = (
    ('Measured requests', 'requests', '.0f'),
    ('TTFT p50 (ms)', 'ttft_p50_ms', '.2f'),
    ('TTFT p99 (ms)', 'ttft_p99_ms', '.2f'),
    ('Mean active decode tokens/s/user', 'decode_tokens_per_second_per_user_mean', '.2f'),
    ('Server cache-read / prompt (%)', 'server_reported_cache_read_pct', '.2f'),
    ('Canonical output tokens/s', 'output_tokens_per_second', '.2f'),
    ('Canonical rate denominator (s)', 'canonical_throughput_denominator_seconds', '.2f'),
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def relative_file(directory, name):
    """A recording may only reference regular files beneath its own directory."""
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Recording path escapes its directory.')
    target = directory / path
    require(target.is_file() and target.resolve().is_relative_to(directory.resolve()),
            'Recording member is missing or escapes its directory: ' + name)
    return target


def graph(value):
    objects = value.get('items', [value])
    matches = [item for item in objects if item['kind'] == 'DynamoGraphDeployment']
    require(len(matches) == 1, 'Need exactly one DGD in a recorded manifest.')
    return matches[0]


def component(value, role):
    matches = [c for c in graph(value)['spec']['components'] if c['type'] == role]
    require(len(matches) == 1, 'Need exactly one recorded component of type ' + role)
    return matches[0]


def argument(argv, name):
    require(argv.count(name) == 1, 'Missing or ambiguous argument: ' + name)
    return argv[argv.index(name) + 1]


def validate_study(value, kind, concurrency):
    require(value['type'] == kind and value['concurrency_session_trees'] == concurrency and
            value['paired_repetitions'] == 1 and len(value['arms']) == 2, 'Unexpected recorded study.')
    first, second = value['arms']
    for key in COMMON_CONTROLS:
        require(first['spec'][key] == second['spec'][key], 'Recorded controls differ: ' + key)
    for row in value['arms']:
        require(row['requests'] > 0 and row['request_error_count'] == 0 and row['cancelled_profile_records'] == 0
                and row['metadata']['submission_valid'] is True, 'Recorded arm is not an accepted observation.')
        require(row['profile_seconds'] == 900 and row['grace_seconds'] == 300, 'Unexpected profiling window.')
        require(row['spec']['h100_gpus'] == 2 * row['spec']['replicas'], 'GPU count does not match TP2 replicas.')
        require(sum(item['requests'] for item in row['worker_generate_requests']) == row['requests'],
                'Worker attribution does not account for the measured requests.')
        require(all(isinstance(row[key], (int, float)) for _, key, _ in METRICS), 'Missing recorded metric.')
    if kind == 'scaleout':
        require([r['spec']['replicas'] for r in value['arms']] == [1, 2] and
                all(r['spec']['router_mode'] == 'round-robin' for r in value['arms']), 'Unexpected scale-out arms.')
        require({p['uid'] for p in first['spec']['worker_pods']} <=
                {p['uid'] for p in second['spec']['worker_pods']}, 'Original worker was not retained during scale-out.')
    else:
        require([r['spec']['router_mode'] for r in value['arms']] == ['round-robin', 'kv'] and
                all(r['spec']['replicas'] == 2 for r in value['arms']), 'Unexpected policy arms.')
        require(second['predicted_kv_hit_histogram_count'] > 0 and second['predicted_kv_hit_histogram_sum'] > 0,
                'No positive observed prefix-overlap evidence in the KV arm.')


def load_recording(directory):
    directory = Path(directory).resolve()
    metadata = ui.read_json(directory / 'recording.json')
    if metadata.get('profile') == C16_PROFILE:
        import demos.routing.recording as workshop_routing_c16
        return workshop_routing_c16.load_recording(directory, metadata)
    require(metadata.get('schema') == 1 and metadata.get('profile') == PROFILE and
            metadata.get('measurement_class') == 'historical-low-load-pilots', 'Unknown recording profile.')
    require(set(metadata['files_sha256']) == RECORDING_FILES, 'Recording hash inventory is incomplete or unexpected.')
    for name, expected in metadata['files_sha256'].items():
        require(ui.digest(relative_file(directory, name)) == expected, 'Recording hash mismatch: ' + name)
    studies = {name: ui.read_json(relative_file(directory, name + '-analysis.json')) for name in ('scaleout', 'policy')}
    validate_study(studies['scaleout'], 'scaleout', 4)
    validate_study(studies['policy'], 'routing', 1)
    for study, value in studies.items():
        for index, row in enumerate(value['arms'], 1):
            raw = ui.read_json(relative_file(directory, f'{study}-arm{index}-aiperf.json'))
            require(raw.get('is_complete') is True and raw.get('was_cancelled') is False and
                    raw['metadata']['submission_valid'] is True and not raw.get('error_summary') and
                    not raw.get('runtime_submission_invalid_reasons'), 'AIPerf export was not accepted.')
            for raw_name, row_name, statistic in (
                ('request_count', 'requests', 'avg'), ('error_request_count', 'request_error_count', 'avg'),
                ('total_osl', 'output_tokens', 'avg'), ('output_token_throughput', 'output_tokens_per_second', 'avg'),
                ('output_token_throughput_per_user', 'decode_tokens_per_second_per_user_mean', 'avg'),
                ('time_to_first_token', 'ttft_p50_ms', 'p50'), ('time_to_first_token', 'ttft_p99_ms', 'p99'),
                ('overall_usage_prompt_cache_read_pct', 'server_reported_cache_read_pct', 'avg')):
                actual = raw.get(raw_name, {}).get(statistic) or 0
                require(actual == row[row_name], 'Analysis differs from AIPerf export: ' + row_name)
            require(not raw.get('context_overflow_count', {}).get('avg'), 'Context-overflow export is not accepted.')
            denominator = row['output_tokens'] / row['output_tokens_per_second']
            require(abs(denominator - row['canonical_throughput_denominator_seconds']) < 1e-8,
                    'Rate denominator differs from exported token count/rate.')
    rr = ui.read_json(relative_file(directory, 'policy-round-robin-deployment.json'))
    kv = ui.read_json(relative_file(directory, 'policy-kv-deployment.json'))
    normalized = copy.deepcopy(rr)
    args = component(normalized, 'frontend')['podTemplate']['spec']['containers'][0]['args']
    require(argument(args, '--router-mode') == 'round-robin', 'RR manifest is not round-robin.')
    args[args.index('--router-mode') + 1] = 'kv'
    require(normalized == kv, 'Policy manifests differ beyond frontend routing mode.')
    discovery = ui.read_json(relative_file(directory, 'policy-kv-discovery.json'))
    require(discovery['passed'] and not discovery['errors'] and discovery['router_mode'] == 'kv' and
            len(discovery['registered_worker_ids']) == 2 and
            sorted(discovery['kv_event_source_hosts']) == sorted(discovery['expected_worker_pod_ips']),
            'KV discovery did not prove both current cache-event sources.')
    return metadata, studies, rr, kv, discovery


def metric_table(study, labels):
    rows = [f'{"Observation":35s}' + ''.join(f'{label:>14s}' for label in labels), '-' * 63]
    rows.append(f'{"H100 GPUs":35s}' + ''.join(f'{r["spec"]["h100_gpus"]:14d}' for r in study['arms']))
    for label, key, fmt in METRICS:
        rows.append(f'{label:35s}' + ''.join(format(row[key], fmt).rjust(14) for row in study['arms']))
    return '\n'.join(rows)


class ExcerptDumper(yaml.SafeDumper):
    """Keep the JSON-valued KV event argument readable on a projected terminal."""


def excerpt_string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|' if '\n' in value else None)


ExcerptDumper.add_representer(str, excerpt_string)


def settings_excerpt(kv):
    frontend = component(kv, 'frontend')
    worker = component(kv, 'worker')
    fargv = frontend['podTemplate']['spec']['containers'][0]['args']
    wargv = worker['podTemplate']['spec']['containers'][0]['args']
    event = json.loads(argument(wargv, '--kv-events-config'))
    require(event.get('enable_kv_cache_events') is True, 'Recorded worker did not enable KV events.')
    value = {'apiVersion': graph(kv)['apiVersion'], 'kind': 'DynamoGraphDeployment', 'spec': {'components': [
        {'name': frontend['name'], 'type': 'frontend', 'replicas': frontend['replicas'], 'podTemplate': {'spec': {
            'containers': [{'name': 'main', 'args': ['--router-mode', argument(fargv, '--router-mode'),
                '--kv-cache-block-size', argument(fargv, '--kv-cache-block-size')]}]}}},
        {'name': worker['name'], 'type': 'worker', 'replicas': worker['replicas'], 'podTemplate': {'spec': {
            'containers': [{'name': 'main', 'args': ['--enable-prefix-caching', '--block-size',
                argument(wargv, '--block-size'), '--kv-events-config', json.dumps(event, indent=2)]}]}}},
    ]}}
    return '# Excerpt from measured KV arm; full manifest retained.\n' + yaml.dump(value, Dumper=ExcerptDumper, sort_keys=False)


def write_views(path, metadata, studies, kv, discovery):
    scaleout = studies['scaleout']
    policy = studies['policy']
    (path / 'scaleout-summary.txt').write_text(
        'RECORDED: AgentX C4, one fixed-order pair; 900 s admission.\n' +
        'C counts live agent trees, not active HTTP requests.\n\n' + metric_table(scaleout, ['One worker RR', 'Two worker RR']) +
        '\n\nThe added worker split requests 57 / 57; it did not improve every metric.\n' +
        'This low-load pair does not locate a capacity limit or isolate routing.\n' +
        'Realized trace mix differs; the first worker/cache survived scale-out.\n' +
        'The second arm followed a network-recovery pause.\n' +
        'Earlier multimodal-capable profile with text requests; not the C1 profile.\n')
    (path / 'routing-settings.yaml').write_text(settings_excerpt(kv))
    rows = [r for r in discovery['connection_records'] if r['topic'] == 'kv-events']
    (path / 'cache-event-log.txt').write_text('\n'.join(r['line'] for r in rows) + '\n')
    (path / 'cache-events.txt').write_text(
        'RECORDED: frontend connected to both current workers for KV events.\n' +
        '\n'.join(f'{r["topic"]:12s} {r["endpoint"]}' for r in rows) + '\n' +
        'Original unabridged lines: cache-event-log.txt\n\n' +
        'Worker --metadata--> router index --request placement--> worker\n' +
        'These events describe cache residency; they do not carry KV tensors.\n' +
        'GPU/CPU tier visibility requires events from the selected integration.\n' +
        'This recording proves KV-event connectivity, not CPU-tier event coverage.\n')
    (path / 'policy-summary.txt').write_text(
        'RECORDED: separate AgentX C1 two-worker RR/KV pair, N=1.\n' +
        'Fresh workers per policy; same snapshot primer and default router tuning.\n\n' +
        metric_table(policy, ['Round-robin', 'KV aware']) + '\n\n' +
        'KV selection observed positive prefix overlap on ' +
        str(int(policy['arms'][1]['predicted_kv_hit_histogram_count'])) + ' selections.\n' +
        'Canonical rates use DIFFERENT drain-inclusive denominators.\n' +
        'Do not report their ratio as a capacity speedup or slowdown.\n' +
        'Realized request mixes differ; these are partial replay trees.\n' +
        'C16/C32/C64/C128 sweep is separate; this recording does not include it.\n')
    (path / 'tradeoff.txt').write_text(
        'ILLUSTRATIVE PLACEMENT CHOICE\n\n' +
        'Branch 1: [same accumulated context] [investigate implementation]\n' +
        'Branch 2: [same accumulated context] [design tests]\n' +
        'Branch 3: [same accumulated context] [check compatibility]\n\n' +
        'Worker A: reusable prefix, but busy.\n' +
        'Worker B: spare compute, but cold for this prefix.\n' +
        'Router tuning balances saved prefill work against assigned load.\n' +
        'It can choose B already; B then pays to recompute missing state.\n\n' +
        'Can B retrieve reusable state instead? Next investigation: KVCR.\n' +
        'That copies cached state; request migration is a separate mechanism.\n\n' +
        'Corpus evidence: two named parallel branches share 72,320 leading\n' +
        'recorded token units (~94%). This is structural prefix evidence,\n' +
        'not a measured cache hit, parent-context inheritance, or speedup.\n')
    ui.write_json(path / 'comparison.json', {'measurement_class': metadata['measurement_class'],
        'simulated': False, 'presentation_mode': 'recorded-evidence',
        'recording_sha256': ui.digest(path / 'recording' / 'recording.json'),
        'studies': studies, 'scope': 'Historical low-load pilots; no combined cross-study ratio or capacity claim.'})


class RoutingDemo(ui.Demo):
    pane_titles = ('Walkthrough', 'Routing comparison', 'Recorded evidence')
    """Present immutable measurements without changing or contacting a cluster."""
    entrypoint = Path(__file__).resolve()
    compact_output = True

    def __init__(self, args):
        from testlib import Run
        self.args = args
        path = args.run or ROOT / 'results' / ('demo-06-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        self.run = Run(path)
        self.path, self.file, self.forward = self.run.path, self.run.path / 'demo.json', None
        if self.file.exists():
            self.data = ui.read_json(self.file)
            require(self.data.get('routing_profile') in (PROFILE, C16_PROFILE) and self.data['rehearsal'] == args.rehearsal,
                    'Use a fresh run for a different recording/profile/mode.')
            requested = getattr(args, 'recording_profile', None)
            require(requested is None or self.data['routing_profile'] ==
                    (PROFILE if requested == 'historical' else C16_PROFILE), 'Recording choice differs from the frozen run.')
            self.check_inputs()
        else:
            selected = BUNDLE if getattr(args, 'recording_profile', None) == 'historical' else C16_BUNDLE
            metadata, studies, _, kv, discovery = load_recording(selected)
            destination = self.path / 'recording'
            destination.mkdir()
            for name in ['recording.json'] + list(metadata['files_sha256']):
                source = relative_file(selected, name)
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(source.read_bytes())
            self.ns = 'dynamo-ft-recorded-routing'
            self.data = {'schema': 1, 'routing_profile': metadata['profile'], 'demo_kind': 'routing',
                         'presentation_mode': 'recorded-evidence', 'rehearsal': args.rehearsal,
                         'namespace': self.ns, 'created_at': ui.now(), 'prepared': False, 'step': 0,
                         'model': studies['policy']['arms'][0]['spec']['model']}
            if metadata['profile'] == C16_PROFILE:
                import demos.routing.recording as workshop_routing_c16
                workshop_routing_c16.write_views(self.path, metadata, studies, kv, discovery)
            else:
                write_views(self.path, metadata, studies, kv, discovery)
            for policy in ('round-robin', 'kv'):
                source = destination / ('policy-' + policy + '-deployment.json')
                (self.path / ('deployment-' + policy + '.yaml')).write_text(yaml.safe_dump(ui.read_json(source), sort_keys=False))
            if metadata['profile'] == C16_PROFILE:
                (self.path / 'deployment-one-rr.yaml').write_text(yaml.safe_dump(ui.read_json(destination / 'deployment-one-rr.json'), sort_keys=False))
            self.data['inputs_sha256'] = {str(p.relative_to(self.path)): ui.digest(p) for p in self.path.rglob('*')
                                        if p.is_file() and p.name not in ('state.json', '.state.lock')}
            self.save()
        self.ns = self.data['namespace']
        if self.data['routing_profile'] == C16_PROFILE:
            from demos.routing.recording import STEPS as selected_steps
            self.steps = selected_steps
        else:
            self.steps = STEPS

    def check_inputs(self):
        for name, expected in self.data['inputs_sha256'].items():
            require(ui.digest(relative_file(self.path, name)) == expected, 'Prepared recording changed: ' + name)
        return load_recording(self.path / 'recording')

    def prepare(self):
        self.check_inputs()
        self.data['prepared'] = True
        self.save()
        print('Recording hashes and paired controls verified. No cluster calls or GPU reservation.')

    prime = prepare

    def preview(self):
        self.check_inputs()
        print('RECORDED EVIDENCE; no cluster commands. Full manifests are retained for inspection.\n')
        print((self.path / 'routing-settings.yaml').read_text())
        for index, (title, explanation) in enumerate(self.steps, 1):
            print(f'{index}. {title}: {explanation}')

    def show(self, *names):
        self.check_inputs()
        for name in names:
            self.command(['cat', relative_file(self.path, name)])

    def guided(self):
        self.require_prepared()
        self.check_inputs()
        require(self.args.auto or sys.stdin.isatty(), 'Interactive steps need a terminal; use --plain --auto.')
        mode = 'REHEARSAL OF RECORDED EVIDENCE' if self.args.rehearsal else 'RECORDED EVIDENCE'
        print('\nDynamo workshop · Scaling and routing\n' + mode + ' / NO CLUSTER CALLS\n' +
              'Run: ' + ui.repo_path(self.path), flush=True)
        names = [('scaleout-summary.txt',), ('routing-settings.yaml', 'cache-events.txt'),
                 ('policy-summary.txt',), ('tradeoff.txt',)]
        for index, ((title, explanation), files) in enumerate(zip(self.steps, names), 1):
            print(f'\nNext: {index}/{len(self.steps)}  {title}', flush=True)
            self.pause()
            if sys.stdout.isatty():
                print('\033[2J\033[H', end='', flush=True)
            print(f'\n{"=" * 64}\n{index}/{len(self.steps)}  {title}\n{explanation}\n{"=" * 64}', flush=True)
            self.data['step'] = index
            self.save()
            self.show(*files)
        self.data['completed_at'] = ui.now()
        self.save()
        print('\nRecorded investigation complete. No cluster resources were created.')
        print('Resume: ' + shlex.join(ui.presenter_command(self.entrypoint, '--run', ui.repo_path(self.path)) +
                                     (['--rehearsal'] if self.args.rehearsal else [])))

    def cleanup(self):
        self.check_inputs()
        print('No cluster resources or GPU reservations. Recording and presenter evidence retained.')


def observe(path, view, once=False):
    """Read-only recording panes; deliberately do not use the live cluster panes."""
    path = path.resolve()
    while True:
        data = ui.read_json(path / 'demo.json')
        print('\033[2J\033[HRECORDED EVIDENCE / NO CLUSTER CALLS', flush=True)
        if view == 'resources':
            if data['routing_profile'] == C16_PROFILE:
                print('C16 / fresh workers per cell / engine cap128\n' +
                      'One RR -> two RR -> two KV, TP2 each\n' +
                      'N=1, fixed order; realized trace/turn mixes differ\n' +
                      'No capacity knee or universal speedup\n\n' +
                      'Current step: ' + str(data['step']) + '/4\n\n' +
                      (path / 'pressure-summary.txt').read_text())
            else:
                print('C4 capacity/placement pair: 1 -> 2 TP2 workers (RR)\n' +
                  'C1 policy pair: 2 TP2 workers, RR -> KV aware\n' +
                  'These are separate studies; do not compare across them.\n\n' +
                  'Current step: ' + str(data['step']) + '/' + str(len(STEPS)) + '\n' +
                  'Recorded AgentX corpus: 393 source traces\n' +
                  'Engine cap: 4 sequences per worker\n' +
                  'C counts agent trees; active requests are different.\n' +
                  'New higher-load sweep: not in this recording.')
        else:
            print((path / 'cache-events.txt').read_text())
        if once:
            return
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run', choices=['run', 'prepare', 'prime', 'preview', 'cleanup', 'observe', 'hold'])
    parser.add_argument('--run', type=Path)
    parser.add_argument('--recording-profile', choices=['c16', 'historical'],
                        help='First-run recording choice (default: accepted C16); existing runs keep their frozen profile.')
    for flag in ('rehearsal', 'preview', 'plain', 'auto', 'detach', 'once', 'full-manifest'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    parser.add_argument('--port', type=int, default=18006, help=argparse.SUPPRESS)
    parser.add_argument('--timeout', type=int, default=60, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action == 'hold':
        while True:
            time.sleep(60)
    if args.action == 'observe':
        require(args.run is not None, 'observe requires --run')
        observe(args.run, args.view, args.once)
        return
    demo = RoutingDemo(args)
    print('Demo files: ' + str(demo.path), flush=True)
    if args.full_manifest:
        print((demo.path / 'deployment-kv.yaml').read_text())
    elif args.preview or args.action == 'preview':
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
        print('\nStopped. Recorded evidence is retained; no cluster resources were created.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('\nDemo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
