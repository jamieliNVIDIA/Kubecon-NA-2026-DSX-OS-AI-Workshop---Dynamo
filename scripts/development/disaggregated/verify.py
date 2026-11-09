#!/usr/bin/env python3
"""Offline independent evidence audit; never contacts a cluster or reruns a profile."""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
from pathlib import Path
import tarfile

import scripts.development.disaggregated.analyze as analysis

ROOT = Path(__file__).resolve().parents[3]


def required(value, reason):
    if not value:
        raise ValueError(reason)


def audit_arm(run, role, campaign):
    folder = run / campaign['arm_names'][role]
    result = analysis.load_arm(folder, analysis.sha(run / 'campaign.json'))
    spec = json.loads((folder / 'spec.json').read_text())
    original = folder / 'raw' / folder.name
    required(analysis.sha(original / 'profile.yaml') == spec['profile_sha256'], 'Raw original profile changed.')
    process = json.loads((original / 'process.json').read_text())
    exit = json.loads((original / 'exit.json').read_text())
    required(exit['exit_code'] == 0 and process['started_at'] == exit['started_at'], 'Original runner failed/changed.')
    raw_count = 0
    with tarfile.open(folder / 'raw-artifacts.tar.gz') as archive:
        for member in archive.getmembers():
            if member.isfile():
                import hashlib
                required(hashlib.sha256(archive.extractfile(member).read()).hexdigest() ==
                         analysis.sha(folder / 'raw' / member.name), 'Archive/extracted bytes differ.')
                raw_count += 1
    records = [json.loads(line) for p in (folder / 'raw').rglob('profile_export.jsonl')
               for line in p.read_text().splitlines()]
    profile = [v for v in records if v['metadata'].get('phase_kind') == 'profiling']
    metric = lambda record, name: record['metrics'].get(name, {}).get('value')
    ids = [v['metadata']['x_request_id'] for v in profile]
    required(len(ids) == len(set(ids)), 'Duplicate request IDs.')
    for v in profile:
        meta = v['metadata']
        required(not meta.get('was_cancelled') and not meta.get('context_overflow_skip'), 'Cancelled/skipped record.')
        required(meta['request_start_ns'] <= meta['request_ack_ns'] <= meta['request_end_ns'], 'Request timestamps unordered.')
        required(metric(v, 'http_req_chunks_received') > 0, 'No observed response chunks.')
        required(metric(v, 'output_sequence_length') == metric(v, 'usage_completion_tokens') > 0, 'Output usage mismatch.')
    for key, exported in (('input_sequence_length', 'input_tokens'), ('output_sequence_length', 'output_tokens')):
        required(sum(metric(v, key) for v in profile) == result['metrics'][exported], 'Per-record token sum differs.')
    startup = run / ('independent-aggregate-startup' if role == 'aggregate' else 'independent-pd-startup')
    proof = json.loads((startup / 'proof.json').read_text())
    for name, digest in proof['file_sha256'].items():
        required(analysis.sha(startup / name) == digest, 'Independent startup proof changed: ' + name)
    current = {p['metadata']['uid']: p for p in json.loads((folder / 'pods.json').read_text())['items']}
    qualification = json.loads((folder / 'worker-qualification.json').read_text())
    for identity in spec['worker_pods']:
        pod = current[identity['uid']]
        required(pod['metadata']['name'] == identity['name'] and pod['spec']['nodeName'] == identity['node'], 'Worker identity changed.')
        required(all(s['restartCount'] == 0 and s['imageID'] == campaign['model_lock']['runtime_image']
                     for s in pod['status']['containerStatuses']), 'Worker restarted/runtime changed.')
        observed = qualification['workers'][identity['node']]
        required(observed['pod_uid'] == identity['uid'] and
                 set(observed['gpu_uuids']) == set(campaign['gpu_uuids_by_node'][identity['node']]), 'GPU identity changed.')
        telemetry = folder / ('gpu-' + identity['name'] + '.csv')
        rows = list(csv.DictReader(telemetry.open()))
        uuids = {v[' uuid'].strip() for v in rows}
        required(uuids == set(observed['gpu_uuids']), 'GPU telemetry identity differs.')
    server = json.loads(next((folder / 'raw').rglob('server_metrics_export.json')).read_text())
    required(set(server['summary']['endpoints_configured']) == set(server['summary']['endpoints_successful']), 'Metrics endpoint missing.')
    result['independent_checks'] = {
        'passed': True, 'original_process': process, 'original_exit': exit,
        'archive_files_verified': raw_count, 'startup_proof_sha256': analysis.sha(startup / 'proof.json'),
        'unique_profile_request_ids': len(ids), 'cancelled_records': 0, 'context_overflow_records': 0,
        'per_record_usage_and_token_sums_match': True, 'response_chunks_observed_in_every_record': True,
        'raw_sse_bodies_retained': False,
        'raw_sse_scope': 'Streaming configuration and chunk/usage metrics audited; no literal SSE-body or answer-content revalidation is possible from these benchmark exports.',
        'source_kinds': dict(collections.Counter(v['metadata']['source_kind'] for v in profile)),
        'all_serving_pods_and_gpus_continuous': True,
        'original_console_sha256': analysis.sha(original / 'console.log')}
    turns = {tuple(v['metadata'].get(k) for k in
        ('source_trace_id', 'source_outer_idx', 'source_inner_idx', 'turn_index', 'source_kind')) for v in profile}
    return result, turns, server


def audit(run):
    inputs = json.loads((run / 'inputs-sha256.json').read_text())
    for name, digest in inputs.items():
        required(analysis.sha(ROOT / name) == digest, 'Frozen input changed: ' + name)
    campaign = json.loads((run / 'campaign.json').read_text())
    aggregate, at, _ = audit_arm(run, 'aggregate', campaign)
    pd, pt, server = audit_arm(run, 'disaggregated', campaign)
    transfers = {k: v for k, v in server['metrics'].items() if 'nixl' in k}
    byte_series = transfers['vllm:nixl_bytes_transferred']['series']
    required(any(v['stats'].get('sum', 0) > 0 for v in byte_series), 'No actual P/D transfer bytes.')
    for name in ('vllm:nixl_num_failed_transfers', 'vllm:nixl_num_failed_notifications',
                 'vllm:nixl_num_notifications_after_expiry'):
        required(all(v['stats']['total'] == 0 for v in transfers[name]['series']), 'NIXL error/late notification: ' + name)
    smoke = json.loads((run / campaign['arm_names']['disaggregated'] / 'endpoint-smoke.json').read_text())
    for response in smoke['responses']:
        workers = response['nvext']['worker_id']
        required(workers['prefill_worker_id'] != workers['decode_worker_id'], 'P/D roles were not distinct.')
    result = {'status': 'accepted_exploratory_pair', 'offline_only': True,
        'campaign_sha256': analysis.sha(run / 'campaign.json'), 'frozen_inputs_verified': len(inputs),
        'verifier_sha256': analysis.sha(__file__), 'arms': [aggregate, pd], 'nixl_metrics_per_endpoint': transfers,
        'source_turns': {'shared': len(at & pt), 'aggregate_only': sorted(at - pt, key=str),
                         'pd_only': sorted(pt - at, key=str)},
        'original_controller_exit_sha256': analysis.sha(run / 'controller-a2-exit.json'),
        'recovery_acceptance_sha256': analysis.sha(run / 'profile-recovery-r2/acceptance.json'),
        'limits': ['N=1, fixed order, C16 trees and no saturation/capacity/SLO or universal topology claim.',
                   'Required NIXL/EFA connector and explicit P/D SSM-layout settings differ.',
                   'Prefill KV-expiry counter is separate from failed transfers; retain its observed nonzero series for source/canary investigation.',
                   'Raw SSE bodies and generated answer text were not retained in the benchmark export.']}
    with (run / 'independent-pair-acceptance.json').open('x') as stream:
        json.dump(result, stream, indent=2)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run.resolve())
    print(json.dumps({'status': result['status'], 'frozen_inputs_verified': result['frozen_inputs_verified'],
                      'source_turns': result['source_turns']}, indent=2))


if __name__ == '__main__':
    main()
