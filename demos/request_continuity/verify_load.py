#!/usr/bin/env python3
"""Recompute controlled-stream qualification from retained SSE, traces and identities."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import demos.request_continuity.demo as migration
import demos.request_continuity.evidence as migration_evidence
import demos.request_continuity.load as migration_load
from demos.request_continuity.evidence import retry_proof
from demos.request_continuity.load import stream_summary


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sse_frames(raw):
    """Parse the complete actual protocol independently of stream.json."""
    frames, pending = [], []
    for line in raw.decode('utf-8').splitlines():
        if not line:
            if pending:
                data = '\n'.join(pending)
                frames.append('[DONE]' if data == '[DONE]' else json.loads(data))
                pending = []
        elif line.startswith('data:'):
            pending.append(line[5:].lstrip(' '))
    if pending:
        raise ValueError('Raw SSE has an unterminated data event.')
    return frames


def normalize(value):
    """Remove only the agreed fresh resource identities and migration limit."""
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: normalize(v) for k, v in value.items()}
    if result.get('name') == 'DYN_MIGRATION_LIMIT' and 'value' in result:
        result['value'] = 'MODE'
    for key in ('namespace', 'feature-test-run'):
        if key in result:
            result[key] = 'RUN'
    if 'workshop-arm' in result:
        result['workshop-arm'] = 'ARM'
    for key, value in result.items():
        if isinstance(value, str) and 'demo-continuity-' in value:
            result[key] = value.replace('demo-continuity-disabled', 'demo-continuity-ARM').replace(
                'demo-continuity-enabled', 'demo-continuity-ARM')
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_case(directory, mode):
    directory = Path(directory).resolve()
    stored = read(directory / 'load-qualification.json')
    spec = read(directory / 'load-spec.json')
    model = read(directory / 'request.json')['model']
    require(stored['mode'] == spec['mode'] == mode, 'Case/mode mismatch.')
    require(stored['simulated'] is False, 'Rehearsal cannot qualify a live case.')
    require(digest(directory / 'load-spec.json') == stored['spec_sha256'], 'Load spec changed.')
    require(digest(directory / 'request.json') == spec['request_sha256'], 'Request changed.')
    require(spec['concurrency'] == spec['requests_per_batch'] == 4 and spec['client_retries'] == 0,
            'Unexpected concurrency or client retry policy.')
    evidence = [directory / name for name in ('load-qualification.json',
        'load-spec.json', 'request.json', 'physical-allocation.json',
        'load-before-pods.json', 'load-after-pods.json', mode + '-deployment.json', mode + '-claim.json',
        mode + '-ready-pods.json', mode + '-worker-metadata.json')]
    captures, summaries = {}, {}
    for phase in ('baseline', 'fault'):
        captures[phase], summaries[phase] = {}, {}
        batch = directory / (phase + '-load')
        for index in range(4):
            request = batch / ('request-%02d' % index)
            result, http = read(request / 'stream.json'), read(request / 'http.json')
            events = [json.loads(line) for line in (request / 'events.jsonl').read_text().splitlines()]
            require(events == result['events'], 'Event journal and summary diverged.')
            frames = sse_frames((request / 'response.sse').read_bytes())
            observed = [e['chunk'] if e['type'] == 'chunk' else '[DONE]' for e in events
                        if e['type'] in ('chunk', 'done')]
            require(frames == observed, 'Raw SSE and parsed capture diverged.')
            require(http['request_count'] == result['request_count'] == 1,
                    'Each client must make exactly one POST.')
            require(http['status'] == result['http_status'], 'HTTP metadata diverged.')
            captures[phase][index] = result
            summaries[phase][str(index)] = stream_summary(result, model)
            evidence.extend(request / name for name in ('stream.json', 'http.json', 'events.jsonl', 'response.sse'))
        require(summaries[phase] == stored[phase] == read(batch / 'stream-summaries.json'),
                'Stored client summaries do not reproduce.')
    require(all(v['successful_completion'] for v in summaries['baseline'].values()), 'Baseline failed.')
    result = captures['fault'][0]
    before, after = read(directory / 'load-before-pods.json')['items'], read(directory / 'load-after-pods.json')['items']
    frontend = next(p['metadata']['name'] for p in before if p['metadata']['labels']['workshop-role'] == 'frontend')
    frontend_log = directory / ('load-after-' + frontend + '.log')
    text = frontend_log.read_text()
    evidence.append(frontend_log)
    namespace = before[0]['metadata']['namespace']
    mapping = migration.registered_workers(before, read(directory / (mode + '-worker-metadata.json'))['items'], namespace)
    workers = {wid: {'pod': pod['metadata']['name'], 'uid': pod['metadata']['uid']}
               for wid, pod in mapping.items()}
    proof = migration.validate_stream(result, mode, model, workers, frontend_log=text)
    require(proof == stored['foreground_continuity_proof'], 'Foreground proof does not reproduce.')
    migration.verify_survivors(before, after, result['fault']['receipt']['pod_uid'])
    target = proof['failed_worker']
    affected = [i for i, summary in summaries['fault'].items() if summary['sse_initial_worker'] == target]
    traces = {}
    if mode == 'enabled':
        require(all(v['successful_completion'] for v in summaries['fault'].values()), 'An enabled stream failed.')
        for index in affected:
            summary = summaries['fault'][index]
            require(len(summary['response_ids']) == 1, 'Expected one stable response ID.')
            traces[index] = retry_proof(text, summary['response_ids'][0], target, workers)
    load = read(directory / 'fault-load/load-at-fault.json')
    require(load == stored['load_at_fault'] and load['outstanding_client_indices'] == [0, 1, 2, 3],
            'All four clients must be outstanding at fault submission.')
    fault_intents = list((directory / 'fault-load').glob('request-*/fault-intent.json'))
    require(len(fault_intents) == 1 and not list((directory / 'baseline-load').glob('request-*/fault-intent.json')),
            'Expected exactly one fault intent for the case.')
    allocation = read(directory / 'physical-allocation.json')
    require(set(allocation) == set(spec['assignment']['nodes']), 'Allocated nodes differ.')
    for node, expected in spec['assignment']['nodes'].items():
        require(sorted(allocation[node]['gpu_uuids']) == sorted(expected), 'Allocated UUIDs differ.')
    for p in fault_intents:
        evidence.extend((p, p.with_name('fault-result.json')))
    evidence.append(directory / 'fault-load/load-at-fault.json')
    return {'mode': mode, 'passed': True, 'run': str(directory),
        'baseline_completed': sum(v['successful_completion'] for v in summaries['baseline'].values()),
        'fault_completed': sum(v['successful_completion'] for v in summaries['fault'].values()),
        'requests_per_batch': 4, 'client_post_count': 8, 'fault_count': 1,
        'affected_client_indices': affected, 'response_correlated_retries': traces,
        'summaries': summaries, 'foreground_proof': proof,
        'raw_sse_matches_journal_and_summary': True, 'survivor_identities_and_physical_gpus_verified': True,
        'evidence_sha256': {str(p.relative_to(directory)): digest(p) for p in sorted(set(evidence))}}


def verify_pair(disabled, enabled):
    paths = {'disabled': Path(disabled).resolve(), 'enabled': Path(enabled).resolve()}
    cases = {mode: verify_case(path, mode) for mode, path in paths.items()}
    specs = {mode: read(path / 'load-spec.json') for mode, path in paths.items()}
    controls = [{k: v for k, v in specs[mode].items() if k not in ('mode', 'migration_limit')}
                for mode in ('disabled', 'enabled')]
    require(controls[0] == controls[1], 'Load/model/hardware controls differ between modes.')
    for suffix in ('deployment.json', 'claim.json'):
        objects = [normalize(read(paths[mode] / (mode + '-' + suffix))) for mode in ('disabled', 'enabled')]
        require(objects[0] == objects[1], 'Engine/claim controls differ between modes.')
    return {'verified_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'passed': True,
        'verifier_sha256': digest(__file__),
        'verification_helpers_sha256': {Path(module.__file__).name: digest(module.__file__)
            for module in (migration, migration_evidence, migration_load)},
        'cases': cases, 'matched_controls': True,
        'total_client_posts': 16, 'total_faults': 2, 'client_retries': 0,
        'scope': 'Functional continuity under four concurrent coding-stream clients; fixed-order N=1.',
        'exact_handoff_gap_seconds': None, 'slo_qualification': 'not performed',
        'agentx_replay': False, 'capacity_recovery': 'not measured',
        'limits': ['Shared EFS/CPU/network traffic may overlap.',
                   'Maximum adjacent client content gap does not isolate the worker handoff.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disabled', type=Path, required=True)
    parser.add_argument('--enabled', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Verification output exists; preserve it and use a fresh path.')
    result = verify_pair(args.disabled, args.enabled)
    with args.output.open('x') as target:
        target.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'outcomes': {
        mode: {'baseline_completed': case['baseline_completed'], 'fault_completed': case['fault_completed'],
               'affected_clients_with_correlated_retry': len(case['response_correlated_retries'])}
        for mode, case in result['cases'].items()}, 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
