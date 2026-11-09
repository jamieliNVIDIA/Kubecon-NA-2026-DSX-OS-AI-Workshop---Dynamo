"""Offline validation and presentation of the accepted three-cell AgentX C16 pairings."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import yaml

import demos.common.runtime as ui
import demos.routing.demo as base

PROFILE = 'agentx-routing-recorded-c16-fresh-workers-v1'
BUNDLE = ui.ROOT / 'demos/routing/recording-c16'
ARMS = ('one-rr-c16-a1', 'two-rr-c16-a1', 'two-kv-c16-a1')
CELL_FILES = ('spec.json', 'profile.yaml', 'summary.json', 'worker-qualification.json',
              'discovery-qualification.json', 'integrity-final.json', 'aiperf.json', 'pod-identities.json')
FILES = {'analysis.json', 'collection-verification.json', 'independent-acceptance.json',
         'campaign.json', 'inputs-sha256.json', 'plan.json', 'payload-manifest.json',
         'frozen-plan.md', 'deployment-one-rr.json', 'policy-round-robin-deployment.json', 'policy-kv-deployment.json'}
FILES |= {f'cells/{arm}/{name}' for arm in ARMS for name in CELL_FILES}
STEPS = [
    ('Add a replica: what changed?', 'Compare fresh one-worker and two-worker RR configurations at AgentX C16.'),
    ('Follow the cache metadata', 'Inspect the measured KV configuration and its actual current-worker event connections.'),
    ('Change the routing policy', 'Compare two-worker RR and KV routing at the same C16 load and engine configuration.'),
    ('A warm worker can also be busy', 'Balance reuse against load, then ask whether the cached state can move.'),
]


def normalized_profile(value):
    result = copy.deepcopy(value)
    benchmark = result['benchmark']
    benchmark['endpoint']['urls'] = ['NORMALIZED']
    benchmark['artifacts']['dir'] = 'NORMALIZED'
    benchmark['server_metrics']['urls'] = ['NORMALIZED']
    return result


def validate_export(row, raw):
    base.require(raw.get('is_complete') is True and raw.get('was_cancelled') is False and
                 raw['metadata']['submission_valid'] is True and not raw.get('error_summary') and
                 not raw.get('runtime_submission_invalid_reasons'), 'C16 AIPerf export was not accepted.')
    for raw_name, row_name, statistic in (
        ('request_count', 'requests', 'avg'), ('error_request_count', 'request_error_count', 'avg'),
        ('total_osl', 'output_tokens', 'avg'), ('total_isl', 'input_tokens', 'avg'),
        ('output_token_throughput', 'output_tokens_per_second', 'avg'),
        ('output_token_throughput_per_user', 'decode_tokens_per_second_per_user_mean', 'avg'),
        ('time_to_first_token', 'ttft_p50_ms', 'p50'), ('time_to_first_token', 'ttft_p99_ms', 'p99'),
        ('input_sequence_length', 'input_tokens_mean', 'avg'), ('output_sequence_length', 'output_tokens_mean', 'avg'),
        ('overall_usage_prompt_cache_read_pct', 'server_reported_cache_read_pct', 'avg')):
        actual = raw.get(raw_name, {}).get(statistic) or 0
        base.require(math.isfinite(actual) and actual == row[row_name], 'C16 analysis/export mismatch: ' + row_name)
    base.require(not raw.get('context_overflow_count', {}).get('avg'), 'C16 context overflow is not accepted.')
    base.require(row['output_tokens_per_second'] > 0 and math.isclose(row['output_tokens'] / row['output_tokens_per_second'],
                 row['canonical_throughput_denominator_seconds'], rel_tol=1e-12), 'C16 rate divisor differs from export.')
    config = raw['input_config']
    base.require(config['scenario'] == 'inferencex-agentx-mvp' and config['endpoint']['streaming'] and
                 config['endpoint']['use_server_token_count'] and
                 not config['endpoint'].get('per_chunk_usage', False), 'C16 replay/token-count convention changed.')


def validate_identity(directory, arm, row, spec, manifest, campaign):
    prefix = directory / 'cells' / arm
    qualification = ui.read_json(prefix / 'worker-qualification.json')
    pods = ui.read_json(prefix / 'pod-identities.json')['items']
    by_name = {pod['metadata']['name']: pod for pod in pods}
    base.require(qualification['passed'] and qualification['max_num_seqs'] == 128 and
                 qualification['campaign_sha256'] == spec['campaign_sha256'], 'C16 worker qualification failed.')
    expected_nodes = {pod['node'] for pod in spec['worker_pods']}
    base.require(set(qualification['workers']) == expected_nodes, 'C16 worker qualification nodes differ.')
    ips = []
    for identity in spec['worker_pods']:
        pod = by_name[identity['name']]
        qualified = qualification['workers'][identity['node']]
        base.require(pod['metadata']['uid'] == identity['uid'] == qualified['uid'] and
                     pod['spec']['nodeName'] == identity['node'] and
                     all(status.get('restartCount', 0) == 0 and status['ready'] and
                         status['imageID'].endswith(spec['runtime_image'].split('@')[1])
                         for status in pod['status']['containerStatuses']), 'C16 worker identity/runtime changed.')
        base.require(sorted(qualified['gpu_uuids']) == sorted(campaign['gpu_uuids_by_node'][identity['node']]),
                     'C16 physical GPU allocation differs from campaign.')
        expected = base.component(manifest, 'worker')['podTemplate']['spec']['containers'][0]
        base.require(pod['spec']['containers'][0]['args'] == expected['args'] and
                     pod['spec']['containers'][0]['image'] == expected['image'], 'C16 effective worker arguments differ.')
        ips.append(pod['status']['podIP'])
    discovery = ui.read_json(prefix / 'discovery-qualification.json')
    base.require(discovery == row['event_discovery_proof'] and discovery['passed'] and not discovery.get('errors') and
                 sorted(discovery.get('expected_worker_pod_ips', discovery.get('worker_pod_ips', []))) == sorted(ips),
                 'C16 discovery does not match current Pods.')
    measured_ids = {str(int(item['worker_id'], 16)) for item in row['worker_generate_requests']}
    base.require(measured_ids == set(discovery['smoke_worker_ids']), 'C16 measured workers differ from smoke identities.')
    if spec['router_mode'] == 'kv':
        base.require(sorted(discovery['kv_event_source_hosts']) == sorted(ips) and
                     len(discovery['registered_worker_ids']) == len(ips) == 2, 'C16 KV event sources differ from current workers.')
        base.require(measured_ids == set(discovery['registered_worker_ids']), 'C16 measured workers differ from KV discovery identities.')
    return discovery


def load_recording(directory, metadata=None):
    directory = Path(directory).resolve()
    metadata = metadata or ui.read_json(directory / 'recording.json')
    base.require(metadata.get('schema') == 2 and metadata.get('profile') == PROFILE and
                 metadata.get('measurement_class') == 'fixed-order-c16-observation', 'Unknown C16 recording profile.')
    base.require(set(metadata['files_sha256']) == FILES, 'C16 recording inventory is incomplete or unexpected.')
    for name, expected in metadata['files_sha256'].items():
        base.require(ui.digest(base.relative_file(directory, name)) == expected, 'C16 recording hash mismatch: ' + name)
    analysis = ui.read_json(directory / 'analysis.json')
    campaign = ui.read_json(directory / 'campaign.json')
    accepted = ui.read_json(directory / 'independent-acceptance.json')
    transported = ui.read_json(directory / 'collection-verification.json')
    plan = ui.read_json(directory / 'plan.json')
    payload = ui.read_json(directory / 'payload-manifest.json')
    inputs = ui.read_json(directory / 'inputs-sha256.json')
    base.require(transported['verified'] and transported['files'] == accepted['transport_files_verified'] == 1040 and
                 accepted['frozen_payload_files_verified'] == len(payload['files']) == 47 and
                 transported['archive_sha256'] == metadata['source_archive_sha256'], 'C16 transport/acceptance identity differs.')
    base.require(ui.digest(directory / 'analysis.json') == accepted['analysis_sha256'] and
                 ui.digest(directory / 'plan.json') == accepted['plan_sha256'] == payload['plan_sha256'],
                 'C16 accepted analysis or frozen plan changed.')
    base.require(all(payload['files'].get(name, {}).get('sha256') == digest for name, digest in plan['source_sha256'].items()) and
                 set(payload['files']) - set(plan['source_sha256']) == {payload['plan'], plan['run'] + '/state.json'} and
                 payload['files'][payload['plan']]['sha256'] == accepted['plan_sha256'],
                 'C16 payload does not match the frozen launch plan.')
    base.require(analysis['campaign'] == campaign and analysis['campaign_sha256'] == ui.digest(directory / 'campaign.json') and
                 campaign['max_num_seqs'] == 128 and campaign['repetitions'] == 1 and campaign['text_only'] and
                 campaign['profile_seconds'] == 900 and campaign['grace_seconds'] == 300,
                 'C16 campaign controls differ from accepted analysis.')
    base.require(ui.digest(directory / 'frozen-plan.md') == inputs['reports/overnight-2026-11-04/routing-sweep/PLAN.md'],
                 'C16 written experiment plan changed.')
    cells = {cell['arm']: cell for cell in analysis['cells'] if cell['eligible']}
    base.require(set(cells) == set(ARMS), 'C16 requires all three accepted cells and no other eligible load.')
    rows, profiles, worker_uids = [], [], set()
    manifests = [ui.read_json(directory / name) for name in
                 ('deployment-one-rr.json', 'policy-round-robin-deployment.json', 'policy-kv-deployment.json')]
    discovery = None
    for index, arm in enumerate(ARMS):
        cell = cells[arm]
        row = cell['metrics']
        prefix = directory / 'cells' / arm
        spec = ui.read_json(prefix / 'spec.json')
        summary = ui.read_json(prefix / 'summary.json')
        inventory = ui.read_json(prefix / 'integrity-final.json')['sha256']
        raw = ui.read_json(prefix / 'aiperf.json')
        base.require(cell['status'] == 'clean' and summary == cell['summary'] and summary['outcome'] == 'clean' and
                     summary['clean_comparison_eligible'] and summary['submission_valid'] and
                     summary['request_errors'] == summary['context_overflow'] == summary['cancelled_profile_records'] == 0 and
                     not summary['error_summary'] and not summary['runtime_submission_invalid_reasons'], 'C16 cell was not clean.')
        for name in CELL_FILES:
            original = f'raw/{arm}/artifacts/profile_export_aiperf.json' if name == 'aiperf.json' else name
            if name == 'pod-identities.json':
                base.require(ui.read_json(prefix / name)['source_file_sha256'] == inventory['pods.json'],
                             'C16 identity excerpt is not tied to its inventoried Pod source.')
            elif name != 'integrity-final.json':
                base.require(ui.digest(prefix / name) == inventory[original], 'C16 frozen cell inventory mismatch: ' + name)
        for name, expected in cell['source_files'].items():
            base.require(ui.digest(prefix / name) == expected, 'C16 analysis source file changed: ' + name)
        base.require(spec == row['spec'] and ui.digest(prefix / 'spec.json') == row['spec_sha256'] and
                     ui.digest(prefix / 'profile.yaml') == spec['profile_sha256'] and
                     spec['campaign_sha256'] == analysis['campaign_sha256'], 'C16 cell specification changed.')
        base.require(spec['concurrency_session_trees'] == 16 and spec['max_num_seqs_per_worker'] == 128 and
                     spec['replicas'] == (1 if index == 0 else 2) and spec['h100_gpus'] == spec['replicas'] * 2 and
                     spec['router_mode'] == ('kv' if index == 2 else 'round-robin'), 'C16 topology/load controls changed.')
        base.require(spec['cache_history'] == campaign['cache_history'] and spec['model'] == campaign['model_lock']['model'] and
                     spec['model_revision'] == campaign['model_lock']['revision'] and
                     spec['runtime_image'] == campaign['model_lock']['runtime_image'], 'C16 cache/model/runtime controls changed.')
        if rows:
            for key in base.COMMON_CONTROLS:
                base.require(row['spec'][key] == rows[0]['spec'][key], 'C16 compared controls differ: ' + key)
        uids = {pod['uid'] for pod in spec['worker_pods']}
        base.require(len(uids) == spec['replicas'] and not worker_uids.intersection(uids), 'C16 cells did not start with fresh workers.')
        worker_uids.update(uids)
        profile = yaml.safe_load((prefix / 'profile.yaml').read_text())
        profiles.append(normalized_profile(profile))
        phase = profile['benchmark']['phases'][0]
        base.require(phase['concurrency'] == 16 and phase['duration'] == 900 and phase['grace_period'] == 300 and
                     row['requests'] > 0 and row['request_error_count'] == row['cancelled_profile_records'] == 0,
                     'C16 measured phase controls or validity changed.')
        validate_export(row, raw)
        base.require(sum(item['requests'] for item in row['source_trace_requests'].values()) == row['requests'] and
                     sum(item['requests'] for item in row['worker_generate_requests']) == row['requests'],
                     'C16 realized request/worker mix does not account for all measured requests.')
        proof = validate_identity(directory, arm, row, spec, manifests[index], campaign)
        if index == 2:
            discovery = proof
            base.require(row['predicted_kv_hit_histogram_count'] > 0 and row['predicted_kv_hit_histogram_sum'] > 0,
                         'C16 KV run never observed positive predicted prefix overlap.')
        rows.append(row)
    base.require(profiles[0] == profiles[1] == profiles[2], 'C16 workload profiles differ beyond endpoint/artifact/metric locations.')
    normalized = copy.deepcopy(manifests[1])
    args = base.component(normalized, 'frontend')['podTemplate']['spec']['containers'][0]['args']
    base.require(base.argument(args, '--router-mode') == 'round-robin', 'C16 RR manifest mode changed.')
    args[args.index('--router-mode') + 1] = 'kv'
    base.require(normalized == manifests[2], 'C16 policy manifests differ beyond routing mode.')
    normalized = copy.deepcopy(manifests[0])
    worker = base.component(normalized, 'worker')
    worker['replicas'] = 2
    terms = worker['podTemplate']['spec']['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
    for term in terms:
        for expression in term['matchExpressions']:
            if expression['key'] == 'kubernetes.io/hostname':
                expression['values'] = list(campaign['gpu_uuids_by_node'])
    base.require(normalized == manifests[1], 'C16 scale-out manifests differ beyond replica count and permitted worker nodes.')
    for manifest in manifests:
        worker = base.component(manifest, 'worker')['podTemplate']['spec']['containers'][0]
        base.require(base.argument(worker['args'], '--max-num-seqs') == '128' and '--language-model-only' in worker['args'] and
                     base.argument(worker['args'], '--tensor-parallel-size') == '2', 'C16 executable worker profile changed.')
    studies = {'scaleout': {'type': 'scaleout', 'concurrency_session_trees': 16, 'paired_repetitions': 1,
                           'arms': rows[:2], 'scope': 'Fresh-worker one-versus-two RR; fixed order, N=1; no capacity knee.'},
               'policy': {'type': 'routing', 'concurrency_session_trees': 16, 'paired_repetitions': 1,
                          'arms': rows[1:], 'scope': 'Fresh-worker two-RR versus two-KV; fixed order, N=1; not a universal speedup.'}}
    return metadata, studies, manifests[1], manifests[2], discovery


def pressure_line(row):
    pressure = row['pressure_series']
    running = pressure['vllm:num_requests_running']['series']
    waiting = pressure['vllm:num_requests_waiting']['series']
    means = ' / '.join(f'{item["stats"]["avg"]:.2f}' for item in running)
    tails = ' / '.join(f'{item["stats"]["p99"]:.0f}' for item in waiting)
    return f'{row["spec"]["configuration"]:8s}: mean running per worker {means}; waiting p99 {tails}'


def write_views(path, metadata, studies, kv, discovery):
    """Use the shared event/config view, then replace all study-specific pilot wording."""
    base.write_views(path, metadata, studies, kv, discovery)
    scaleout, policy = studies['scaleout'], studies['policy']
    first, second = scaleout['arms']
    decode_gain = (second['decode_tokens_per_second_per_user_mean'] / first['decode_tokens_per_second_per_user_mean'] - 1) * 100
    (path / 'scaleout-summary.txt').write_text(
        'RECORDED: AgentX C16 / fresh workers per cell / N=1, fixed order.\n' +
        'C counts live trees; all cells use a 128-sequence engine cap.\n\n' +
        base.metric_table(scaleout, ['One worker RR', 'Two worker RR']) + '\n\n' +
        f'Mean per-request decode rate rose {decode_gain:.1f}%; aggregate rate barely changed.\n' +
        'Cache-read share fell and TTFT tails worsened after adding a worker.\n' +
        'This changes capacity and placement opportunities together.\n' +
        pressure_line(first) + '\n' +
        'Running/queued pressure does not establish a capacity knee.\n' +
        'Fresh workers mean this is a controlled topology comparison,\n' +
        'not an in-place scale-up retaining the first worker cache.\n')
    (path / 'policy-summary.txt').write_text(
        'RECORDED: same C16 load / two TP2 workers / default router tuning.\n' +
        'Fresh workers per cell; same canonical AgentX primer.\n\n' +
        base.metric_table(policy, ['Round-robin', 'KV aware']) + '\n\n' +
        'More cache reuse and lower TTFT tails; aggregate rate is roughly flat.\n' +
        f'{int(policy["arms"][1]["predicted_kv_hit_histogram_count"])} KV selections; total predicted prefix overlap was positive.\n' +
        'Each p99 represents about three requests: this is an observation,\n' +
        'not a stable production percentile or an SLO guarantee.\n' +
        'Realized trace/turn mixes differ; see realized-mix.json.\n' +
        'Windows include drain (~1200s), not only the 900s admission.\n' +
        'Other tests used disjoint GPUs but shared CPU, storage and network.\n' +
        'C32 failed before profiling. No saturation curve is established.\n')
    rows = [first, second, policy['arms'][1]]
    ui.write_json(path / 'realized-mix.json', {row['arm']: {'requests': row['requests'],
        'input_tokens_mean': row['input_tokens_mean'], 'output_tokens_mean': row['output_tokens_mean'],
        'source_trace_requests': row['source_trace_requests'], 'sampled_root_correlation_ids': row['sampled_root_correlation_ids'],
        'branch_stats': row['branch_stats']} for row in rows})
    ui.write_json(path / 'pressure-proof.json', {row['arm']: row['pressure_series'] for row in rows})
    (path / 'pressure-summary.txt').write_text('\n'.join(pressure_line(row) for row in rows) +
        '\nC16 counts paced trees, not active HTTP requests. No capacity knee.\n')
    comparison = ui.read_json(path / 'comparison.json')
    comparison['scope'] = 'Three accepted fresh-worker C16 cells; N=1, fixed order, realized mixes differ; no capacity-knee claim.'
    ui.write_json(path / 'comparison.json', comparison)
