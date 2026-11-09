#!/usr/bin/env python3
"""Capture a demo's real main panel into an immutable, shareable text attempt.

Composed Shadow records its first fault with --defer-qualification and an
explicit --pre-fault-health receipt. After external post-fault health and the
full controller's finalize, --finalize-pending appends qualification evidence
without launching the presenter again or changing the original main bytes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import sys
import termios
import time

from demos.registry import DEMOS
from scripts.source_paths import source_files as demo_sources, source_name, source_path

ROOT = Path(__file__).resolve().parents[2]
KVCR_DEMOS = ('07-kvcr', '07-kvcr-prepared')
COMPOSED_SHADOW = '08-shadow-engine-composed'
EVIDENCE_NAMES = (
    'demo.json', 'state.json', 'model-lock.json', 'allocation.json', 'request.json', 'active-request.json',
    'response.json', 'timing.json', 'comparison.json', 'ready-pods.json',
    'peer-proof.json', 'transfer-proof.json', 'recovery-proof.json', 'allocated-gpus.json',
    'metrics-before.json', 'metrics-after.json',
)
# Control strings are removed, not rendered: each cleared screen stays in the
# transcript in its original order rather than overwriting the previous screen.
ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[P^_].*?\x1b\\|'
                  r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]', re.DOTALL)
SECRET_NAME = r'(?:HF_TOKEN|HUGGING_FACE_HUB_TOKEN|NGC_API_KEY|NGC_API_TOKEN|GITHUB_TOKEN|GH_TOKEN|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|TOKEN|CLIENT_SECRET|SECRET_KEY|PASSWORD|\.dockerconfigjson)'
SECRET_ASSIGNMENT = re.compile(r'(?im)((?:["\']?' + SECRET_NAME + r'["\']?)\s*[:=]\s*)(["\']?)([^\s,"\'\n]+)(\2)')
YAML_SECRET_VALUE = re.compile(r'(?im)(\bname:\s*["\']?' + SECRET_NAME + r'["\']?\s*\n\s*value:\s*)([^\n]+)')
BEARER = re.compile(r'(?i)(\bauthorization["\']?\s*[:=]\s*["\']?(?:bearer|basic)\s+)([^\s"\'\n]+)')
TOKEN_LITERAL = re.compile(r'\b(?:hf_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|nvapi-[A-Za-z0-9_-]{16,})\b')
PRIVATE_KEY = re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----', re.DOTALL)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dump(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def read_state(run):
    path = Path(run) / 'demo.json'
    return json.loads(path.read_text()) if path.exists() else None


def snapshot_files(paths, destination, relative_root=None, *, source_ids=False):
    """Keep independent, read-only copies before the source run can change."""
    destination = Path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    hashes = {}
    for source in paths:
        source = Path(source)
        name = (source_name(source, root=ROOT) if source_ids else
                str(source.relative_to(relative_root)) if relative_root else source.name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
        target.chmod(0o400)
        hashes[name] = sha256(target)
    return hashes


def evidence_files(demo, run):
    paths = {run / name for name in EVIDENCE_NAMES if (run / name).is_file()}
    paths.update(p for p in (run / 'startup-observations').rglob('*') if p.is_file())
    if demo == '01-single-replica':
        paths.update(run / name for name in ('deployment.yaml', 'deployment-excerpt.yaml',
                     'gpu-claim-template.yaml', 'source-service.yaml', 'resources.json') if (run / name).is_file())
        paths.update(p for p in run.glob('aiperf-c*.json') if p.is_file())
        paths.update(p for folder in run.glob('aiperf-c*') if folder.is_dir() for p in folder.rglob('*') if p.is_file())
    if demo == '02-modelexpress':
        names = ('source.yaml', 'native.yaml', 'peer.yaml', 'deployment.yaml',
                 'source-gpu-claim-template.yaml', 'gpu-claim-template.yaml', 'source-service.yaml',
                 'source-binding.json', 'changes.diff', 'worker-changes.diff', 'modelexpress-settings.yaml')
        paths.update(run / name for name in names if (run / name).is_file())
        paths.update(p for p in (run / 'arms').rglob('*') if p.is_file())
    if demo == '05-request-continuity':
        for arm in ('disabled', 'enabled'):
            paths.update(p for p in (run / arm).glob('*') if p.is_file())
        paths.update(p for p in run.glob('*') if p.is_file() and (
            p.name.startswith(('disabled-', 'enabled-')) or p.name in
            ('migration-settings.yaml', 'integrity.json')))
    if demo == '04-snapshot-dgd':
        names = ('initial-identity.json', 'initial-request.json', 'replacement-identity.json',
                 'response.sse', 'captured-snapshot.json', 'captured-content.json', 'snapshot-dgd-spec.json',
                 'deployment.json', 'deployment.yaml', 'deployment-excerpt.yaml', 'runtime-patch.yaml',
                 'nvme-artifact-files.sha256', 'restore-agent-full.log', 'run-live.py', 'live-controller.json',
                 'capture-deadline-policy.json', 'capture-deadline-before.json', 'capture-deadline-after.json',
                 'capture-deadline-helper-revision.json', 'remote-controller-plan.json',
                 'remote-controller.json', 'remote-controller-start.json', 'remote-controller-exit.json')
        paths.update(run / name for name in names if (run / name).is_file())
        paths.update(p for p in run.glob('nvme-*.json') if p.is_file())
        paths.update(p for p in (run / 'capture-deadline-receipts').rglob('*.json') if p.is_file())
        paths.update(p for p in (run / 'remote-controller').rglob('*') if p.is_file())
    if demo in ('06-routing', '09-agentx-metrics'):
        paths.update(p for p in run.glob('*') if p.is_file() and p.suffix in ('.json', '.txt', '.yaml'))
        paths.update(p for p in (run / 'recording').rglob('*') if p.is_file())
    if demo in KVCR_DEMOS:
        paths.update(p for p in run.glob('*') if p.is_file() and p.suffix in ('.json', '.txt', '.yaml', '.log', '.py'))
        for name in ('source', 'target', 'before-seed', 'before-peer', 'after-peer', 'sources',
                     'warmup_main', 'warmup_sub', 'main', 'control', 'sub', 'warmup-before', 'warmup-after-main',
                     'warmup-after-sub', 'before-main', 'after-main', 'after-control', 'after-sub'):
            paths.update(p for p in (run / name).rglob('*') if p.is_file())
        if demo == '07-kvcr-prepared':
            paths.update(p for folder in run.glob('admission-*') if folder.is_dir()
                         for p in folder.rglob('*') if p.is_file())
    if demo in ('08-shadow-engine', COMPOSED_SHADOW):
        paths.update(p for p in run.glob('*') if p.is_file() and p.suffix in ('.json', '.yaml', '.log', '.py'))
        paths.update(p for p in (run / 'runtime-sources').rglob('*') if p.is_file())
        if demo == COMPOSED_SHADOW:
            for name in ('writer-basis', 'source-snapshot', 'runtime-contract-sources'):
                paths.update(p for p in (run / name).rglob('*') if p.is_file())
    return sorted(paths)


def modelexpress_source_provenance(run, state):
    """Retain the already measured intro bytes before recording its peer target."""
    from demos.modelexpress import source

    binding_bytes = (Path(run) / 'source-binding.json').read_bytes()
    binding = json.loads(binding_bytes)
    binding_hash = hashlib.sha256(binding_bytes).hexdigest()
    if (binding != state.get('source_binding') or
            state.get('mx_inputs', {}).get('source-binding.json') != binding_hash):
        raise ValueError('The captured ModelExpress run differs from its frozen first-replica binding.')
    source.validate_files(binding)
    source_run = Path(binding['run'])
    frozen = {}
    for name, expected in binding['inputs'].items():
        data = (source_run / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('First-replica evidence changed while capture was freezing it: ' + name)
        frozen[name] = data
    return ({'kind': 'retained_first_replica', 'source_run': str(source_run),
             'source_binding_sha256': binding_hash, 'source_files_sha256': dict(binding['inputs']),
             'source_worker_uid': binding['worker_uid'], 'source_node': binding['node'],
             'startup_measured_in_capture': False}, frozen, binding_bytes)


def _shadow_file(run, name):
    root = Path(run).resolve()
    path = root / name
    path.resolve().relative_to(root)
    if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents if p != root.parent):
        raise ValueError('Shadow evidence must be a regular in-run file: ' + name)
    return path


def _shadow_time(value):
    if type(value) is not str: raise ValueError('Shadow evidence timestamps must be strings.')
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None: raise ValueError('Shadow evidence timestamps must include a timezone.')
    return parsed


def shadow_composed_provenance(run, state):
    """Offline, portable verification of the frozen accepted writer and ready reader."""
    import demos.shadow.composed as full
    run = Path(run)
    read = lambda name: json.loads(_shadow_file(run, name).read_text())
    spec, runtime = read('full-spec.json'), read('state.json')
    if (state.get('rehearsal') is not False or state.get('profile') != full.PROFILE or
            state.get('shadow_profile') != full.PROFILE or spec.get('profile') != full.PROFILE or
            runtime.get('shadow_full_profile') != full.PROFILE or spec.get('namespace') != state.get('namespace') or
            runtime.get('namespace') != state.get('namespace') or spec.get('reader_enabled') is not True or
            spec.get('source_writer_collected') is not True or
            runtime.get('shadow_full_spec_sha256') != sha256(_shadow_file(run, 'full-spec.json'))):
        raise ValueError('Composed Shadow mode/profile/namespace or frozen specification changed.')
    for key, directory in (('inputs', ''), ('source_snapshot', 'source-snapshot/'),
            ('runtime_contract_hashes', 'runtime-contract-sources/'), ('writer_basis_receipts', 'writer-basis/')):
        if not spec.get(key): raise ValueError('Missing composed Shadow provenance: ' + key)
        for name, digest in spec[key].items():
            if sha256(_shadow_file(run, directory + name)) != digest:
                raise ValueError('Frozen composed Shadow evidence changed: ' + directory + name)
    audit = read('writer-basis/root-acceptance.json')
    collection = read('writer-basis/collection-manifest.json')
    verified = read('writer-basis/collection-verification.json')
    if (audit.get('schema') != 1 or audit.get('kind') != 'shadow-writer-basis-root-audit' or
            audit.get('status') != 'passed' or audit.get('source_run') != spec['source_writer_run'] or
            audit.get('original_run') != spec['source_writer_original_run'] or
            audit.get('namespace') != spec['source_writer_namespace'] or
            audit.get('collection_manifest_sha256') != sha256(_shadow_file(run, 'writer-basis/collection-manifest.json')) or
            audit.get('collection_verification_sha256') != sha256(_shadow_file(run, 'writer-basis/collection-verification.json')) or
            verified.get('status') != 'verified' or verified.get('state_adopted') is not False or
            collection.get('docker_state', {}).get('Running') is not False or
            collection.get('docker_state', {}).get('ExitCode') != 0 or
            any(audit.get(key) != collection.get(key) or audit.get(key) != verified.get(key)
                for key in ('plan_sha256', 'controller_name')) or
            audit.get('archive_sha256') != verified.get('archive_sha256')):
        raise ValueError('Composed Shadow lacks its exact accepted root writer/collection audit.')
    if set(audit.get('files', {})) != set(full.BASIS_FILES) | {'writer-remote-exit.json'}:
        raise ValueError('Accepted writer file inventory changed.')
    for name, digest in audit['files'].items():
        if sha256(_shadow_file(run, 'writer-basis/' + name)) != digest:
            raise ValueError('Root-accepted writer evidence changed: ' + name)
    exit_receipt = read('writer-basis/writer-remote-exit.json')
    if (exit_receipt.get('status') != 'qualified_and_cleaned_pending_root_audit' or
            exit_receipt.get('cleanup') != 'passed' or exit_receipt.get('reader_enabled') is not False or
            exit_receipt.get('intentional_fault') is not False):
        raise ValueError('Writer basis was not qualified and cleaned before composition.')
    writer_spec, writer_state = read('writer-basis/descriptor-writer-spec.json'), read('writer-basis/state.json')
    manifests = {str(rank): read('writer-basis/rank-manifests/rank-' + str(rank) + '.json') for rank in (0, 1)}
    capture = read('writer-basis/descriptor-capture.json')
    for rank in (0, 1):
        if capture[str(rank)]['manifest_sha256'] != sha256(_shadow_file(run, 'writer-basis/rank-manifests/rank-' + str(rank) + '.json')):
            raise ValueError('Captured writer rank manifest changed.')
    counts = full.validate_basis(writer_spec, writer_state, manifests, capture,
        read('writer-basis/descriptor-capture-provenance.json'), read('writer-basis/health-after.json'))
    if counts != spec.get('expected_runtime_counts'):
        raise ValueError('Accepted writer runtime inventory differs from the full candidate.')
    ready = runtime.get('checks', {}).get('shadow-full-ready', {})
    before, after = read('full-ready-before.json'), read('full-ready-after.json')
    if (ready.get('status') != 'passed' or not state.get('ready_observed_at') or
            ready.get('pod_uid') != after.get('pod_uid') or
            ready.get('dgd_uid') != runtime.get('shadow_full_dgd_uid') or
            ready.get('states') != after.get('states') or sorted(after.get('states', {}).values()) != ['active', 'standby'] or
            ready.get('responses') != 3):
        raise ValueError('Full Shadow has no accepted active and parked reader proof.')
    full.validate_ready_observation(before, after)
    if before.get('gms') != after.get('gms'):
        raise ValueError('Committed full-ready GMS generation changed during coding.')
    full.presenter.validate_pair(before, full.UUIDS)
    full.presenter.validate_pair(after, full.UUIDS)
    responses = read('full-ready-coding.json')
    if len(responses) != 3: raise ValueError('Three initial coding responses are required.')
    for response in responses: _shadow_coding(response, state['model'])
    graph = read('full-applied-dgd.json')
    if (graph['metadata']['uid'] != runtime['shadow_full_dgd_uid'] or
            graph['metadata']['generation'] != runtime['shadow_full_dgd_generation'] or
            hashlib.sha256(json.dumps(graph['spec'], sort_keys=True).encode()).hexdigest() != runtime['shadow_full_dgd_spec_sha256']):
        raise ValueError('Full Shadow DGD identity/generation/spec changed.')
    return {'kind': 'accepted_shadow_writer_and_parked_reader', 'profile': full.PROFILE,
        'source_writer_run': spec['source_writer_run'], 'source_writer_original_run': spec['source_writer_original_run'],
        'writer_acceptance_sha256': sha256(_shadow_file(run, 'writer-basis/root-acceptance.json')),
        'full_spec_sha256': sha256(_shadow_file(run, 'full-spec.json')), 'namespace': state['namespace'],
        'dgd_uid': ready['dgd_uid'], 'pod_uid': after['pod_uid'], 'initial_states': after['states'],
        'ready_proof_sha256': sha256(_shadow_file(run, 'full-ready-after.json')),
        'startup_measured_in_capture': False}


def _shadow_coding(response, model):
    from demos.snapshot.dgd import validate_coding_output
    if (response.get('request', {}).get('model') != model or not response.get('worker', {}).get('decode_worker_id') or
            'data: [DONE]' not in response.get('sse', '').splitlines() or not response.get('chunks') or
            any(c.get('error') or c.get('model') not in (None, model) for c in response['chunks']) or
            not any(choice.get('finish_reason') == 'stop' for c in response['chunks'] for choice in c.get('choices', []))):
        raise ValueError('Full Shadow fresh coding lacks complete stream/model/worker evidence.')
    chunks = [json.loads(line[6:]) for line in response['sse'].splitlines()
        if line.startswith('data: ') and line != 'data: [DONE]']
    content = ''.join(choice.get('delta', {}).get('content') or ''
        for chunk in chunks for choice in chunk.get('choices', []))
    worker = next((chunk['nvext']['worker_id'] for chunk in reversed(chunks)
        if chunk.get('nvext', {}).get('worker_id')), None)
    if (chunks != response['chunks'] or worker != response['worker'] or
            validate_coding_output(content) != response['content']):
        raise ValueError('Full Shadow coding summary differs from its retained SSE chunks/content/worker.')


def validate_shadow_composed_capture(run, state, *, require_health=True):
    """Require the actual single fault, preserved weights, promotion and replenishment."""
    import math
    import demos.shadow.composed as full
    from r610_retest_audit import new_xids
    run = Path(run)
    read = lambda name: json.loads(_shadow_file(run, name).read_text())
    provenance = shadow_composed_provenance(run, state)
    runtime, proof = read('state.json'), read('recovery-proof.json')
    checks = runtime['checks']
    failed = checks.get('shadow-failover', {})
    if (state.get('step') != 4 or failed.get('status') != 'passed' or proof.get('status') != 'passed' or
            any(proof.get(key) != value for key, value in failed.items()) or
            proof.get('rehearsal', False) is not False or proof.get('simulated', False) is not False or
            proof.get('tensor_parallel_size') != 2 or proof.get('new_standby_confirmed') is not True or
            proof.get('pod_uid') != provenance['pod_uid'] or proof.get('model') != state['model'] or
            {proof.get('active_before'), proof.get('active_after')} != {'engine-0', 'engine-1'}):
        raise ValueError('Full Shadow single-fault promotion/replenishment proof is incomplete.')
    elapsed = proof.get('fault_command_to_first_verified_response_seconds')
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError('Full Shadow recovery timing is not an actual positive observation.')
    before = read('full-ready-after.json')
    active, promoted = proof['active_before'], proof['active_after']
    intent, fault = read('shadow-fault-intent.json'), read('shadow-fault.json')
    engine_id = before['engines'][active]['engine_id']
    if (intent.get('pod_uid') != before['pod_uid'] or intent.get('container') != active or
            intent.get('container_id') != before['container_statuses'][active]['containerID'] or
            intent.get('engine_id') != engine_id or intent.get('signal') != 'SIGKILL' or
            fault.get('engine_id') != engine_id or fault.get('signal') != 'SIGKILL' or
            type(fault.get('pid')) is not int or fault['pid'] <= 1 or
            not fault.get('command', '').startswith('VLLM::EngineCore')):
        raise ValueError('Full Shadow fault does not name its single verified active EngineCore.')
    baseline, recovered = read('shadow-baseline-response.json'), read('shadow-recovered-response.json')
    for response in (baseline, recovered): _shadow_coding(response, state['model'])
    if (proof.get('worker_before') != baseline['worker'] or proof.get('worker_after') != recovered['worker'] or
            baseline['worker']['decode_worker_id'] == recovered['worker']['decode_worker_id']):
        raise ValueError('Full Shadow recovery did not demonstrate a distinct fresh coding worker.')
    candidates = [json.loads(p.read_text()) for p in sorted(run.glob('shadow-observation-*.json'))]
    candidates = [v for v in candidates if v.get('pod_uid') == before['pod_uid'] and
        v.get('states') == {active: 'standby', promoted: 'active'}]
    if not candidates: raise ValueError('No actual promoted/parked replenishment observation.')
    after = candidates[-1]
    full.presenter.validate_pair(after, full.UUIDS)
    for name in (promoted, 'gms-server'):
        if any(before['container_statuses'][name][key] != after['container_statuses'][name][key]
                for key in ('containerID', 'restartCount')):
            raise ValueError('Promoted standby or GMS restarted during recovery.')
    if after['container_statuses'][active]['restartCount'] <= before['container_statuses'][active]['restartCount']:
        raise ValueError('Failed active engine was not replenished.')
    report, old_report = after['engines'][promoted], before['engines'][promoted]
    if report.get('lock_held') is not True or report.get('lock_owner') != 'engine-' + report['engine_id']:
        raise ValueError('Promoted standby does not own the failover lock.')
    for suffix in ('switch_success_total', 'switch_attempts_total'):
        if full.presenter.control.counter(report['metrics'], suffix, engine_id=report['engine_id']) != \
                full.presenter.control.counter(old_report['metrics'], suffix, engine_id=old_report['engine_id']) + 1:
            raise ValueError('Promotion counters do not establish exactly one successful switch.')
    if set(before['gms']) != set(after['gms']): raise ValueError('GMS sockets changed during recovery.')
    if any(sum(name.endswith(suffix) for name in before['gms']) != 2 for suffix in ('_weights.sock', '_kv_cache.sock')):
        raise ValueError('Both TP-rank weight and KV sockets are required.')
    for name, old in before['gms'].items():
        new = after['gms'][name]
        if name.endswith('_weights.sock'):
            if (not old['state']['memory_layout_hash'] or old['state']['memory_layout_hash'] != new['state']['memory_layout_hash'] or
                    old['events'] != new['events'] or [e['kind'] for e in old['events']['events']] != ['rw_connected', 'committed']):
                raise ValueError('Committed weights changed or were republished during recovery.')
        elif name.endswith('_kv_cache.sock'):
            events = old['events']['events']
            if new['events']['events'][:len(events)] != events or not any(
                    e['kind'] == 'allocations_cleared' and e['allocation_count'] > 0 for e in new['events']['events'][len(events):]):
                raise ValueError('No failed-engine KV allocation reclamation proof.')
    health_before, health_fault = read('health-before.json'), read('health-before-fault.json')
    healths = [health_before, health_fault]
    if require_health:
        if checks.get('shadow-full-qualification', {}).get('status') != 'passed':
            raise ValueError('Post-fault full Shadow qualification is pending.')
        qualification_files = list(run.glob('check-shadow-full-qualification-*.json'))
        if len(qualification_files) != 1 or json.loads(qualification_files[0].read_text()) != checks['shadow-full-qualification']:
            raise ValueError('Exactly one matching full-controller qualification receipt is required.')
        healths.append(read('health-after.json'))
    times = [checks['shadow-full-ready']['updated_at'], failed['updated_at']]
    for index, health in enumerate(healths):
        receipt = health['receipt']
        if (receipt.get('node') != full.NODE or receipt.get('changed_conditions') or
                not receipt.get('outputs') or any(v.get('exit_code') != 0 for v in receipt['outputs'].values()) or
                receipt['driver_pod_uid'] != health_before['receipt']['driver_pod_uid'] or
                receipt['node_status']['nodeInfo']['bootID'] != health_before['receipt']['node_status']['nodeInfo']['bootID'] or
                new_xids(health_before['xids'], health['xids']) or
                (index > 0 and _shadow_time(receipt['observed_at']) < _shadow_time(times[index - 1]))):
            raise ValueError('Full Shadow health is incomplete, stale, changed or contains new Xids.')
    if require_health and _shadow_time(checks['shadow-full-qualification']['updated_at']) < _shadow_time(healths[-1]['receipt']['observed_at']):
        raise ValueError('Full qualification predates its post-fault health receipt.')
    return provenance


def plain_text(raw):
    """Drop display controls while retaining every screen and progress update."""
    text = raw.decode('utf-8', errors='replace')
    text = ANSI.sub('', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Backspace can occur in terminal progress indicators; preserve the final
    # spelling within each update. Tabs and line breaks remain readable.
    while '\b' in text:
        updated = re.sub(r'[^\n]\x08', '', text)
        if updated == text:
            text = text.replace('\b', '')
            break
        text = updated
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32).replace('\x7f', '')


def sanitize(text):
    """Redact common explicit credential forms; preserve a private raw original."""
    count = 0
    for pattern, replacement in (
        (YAML_SECRET_VALUE, lambda m: m[1] + '[REDACTED]'),
        (SECRET_ASSIGNMENT, lambda m: m[1] + m[2] + '[REDACTED]' + m[4]),
        (BEARER, lambda m: m[1] + '[REDACTED]'),
        (PRIVATE_KEY, '[REDACTED PRIVATE KEY]'),
        (TOKEN_LITERAL, '[REDACTED TOKEN]'),
    ):
        text, changes = pattern.subn(replacement, text)
        count += changes
    return text, count


def validate_kvcr_preflight(run, state):
    """Bind measured prompt geometry to the actual request pair and worker Pods."""
    from demos.kvcr.demo import PROFILE, ROLES, object_sha256, prompt_preflight_proof, speedup_preflight_proof
    run = Path(run)
    read = lambda name: json.loads((run / name).read_text())
    proof = read('prompt-preflight.json')
    if (proof.get('status') != 'passed' or proof.get('simulated') is not False or
            proof.get('checked_before_source_request') is not True or
            sha256(run / 'prompt-preflight.json') != state.get('prompt_preflight_sha256')):
        raise ValueError('Measured prompt preflight is missing or changed.')
    payload = read('prompt-preflight-input.json')
    if state.get('kvcr_profile') == PROFILE:
        # Speedup runs: every request, warm-up included, must match the measured preflight.
        speedup_preflight_proof(payload, proof, proof['geometry_by_worker'])
        first = state['warmup_main_started_at']
        tokens = proof['prompt_tokens']
        roles = tuple(ROLES)
    else:
        prompt_preflight_proof(payload, proof, proof['geometry_by_worker'])
        first = state['source_request_started_at']
        tokens = {role: proof[role + '_prompt_tokens'] for role in ('source', 'target')}
        roles = ('source', 'target')
    worker_uids = {p['metadata']['labels']['kvcr-peer']: p['metadata']['uid']
                   for p in read('ready-pods.json')['items']
                   if p['metadata'].get('labels', {}).get('kvcr-peer') in ('a', 'b')}
    if set(worker_uids) != {'a', 'b'} or worker_uids != proof.get('worker_pod_uids'):
        raise ValueError('Prompt preflight belongs to different worker Pods.')
    parse = lambda text: dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    if parse(proof['completed_at']) > parse(first):
        raise ValueError('Prompt preflight did not precede source generation.')
    for role in roles:
        if (object_sha256(read(role + '/request.json')) != proof['request_sha256'][role] or
                read(role + '/response.json')['usage']['prompt_tokens'] != tokens[role]):
            raise ValueError('Actual request/token usage differs from prompt preflight: ' + role)
    for name, digest in proof['evidence_sha256'].items():
        path = (run / name).resolve()
        path.relative_to(run.resolve())
        if sha256(path) != digest:
            raise ValueError('Prompt preflight evidence changed: ' + name)


def prepared_provenance(run, state, *, check_owner=False):
    """Read exact repair bytes; archived captures can validate without a live lease."""
    from demos.kvcr.prepared import PROFILE, repair_binding, require, check_pod_transition, check_native_cards, readiness_two_workers
    run = Path(run)
    binding_path = run / 'prepared-binding.json'
    binding = json.loads(binding_path.read_text())
    require(binding.get('profile') == PROFILE and state.get('prepared_profile') == PROFILE and state.get('rehearsal') is False,
            'Prepared KVCR capture requires an explicitly bound live child.')
    require(sha256(binding_path) == state.get('inputs', {}).get('prepared-binding.json'), 'Prepared binding changed.')
    plan = binding['parent_plan']
    require(state.get('prepared_parent') == plan['parent'] and state.get('namespace') == plan['namespace'] and
            state.get('lease') == plan['lease'], 'Prepared child parent/namespace/lease provenance changed.')
    if check_owner:
        repair_binding(binding['repair'])  # Read-only parent lease/source/evidence gate before execution.
    archived = run / 'prepared-parent'
    repair_path = archived / 'repair.json' if archived.exists() else Path(binding['repair'])
    repair_bytes = repair_path.read_bytes()
    require(hashlib.sha256(repair_bytes).hexdigest() == binding['repair_sha256'], 'Declared repair bytes changed.')
    repair = json.loads(repair_bytes)
    plan_path = archived / 'plan.json' if archived.exists() else Path(repair['plan'])
    selected_path = archived / 'snapshot.json' if archived.exists() else Path(repair['qualified_snapshot'])
    plan_bytes, selected_bytes = plan_path.read_bytes(), selected_path.read_bytes()
    require(hashlib.sha256(plan_bytes).hexdigest() == repair['plan_sha256'] and json.loads(plan_bytes) == plan,
            'Prepared repair plan does not match the bound parent plan.')
    selected = json.loads(selected_bytes)
    require(hashlib.sha256(selected_bytes).hexdigest() == repair['qualified_snapshot_sha256'] and
            selected == binding['qualified_snapshot'], 'Prepared repair snapshot changed.')
    require(repair.get('status') == 'passed' and repair.get('kind') == 'kvcr-supported-refresh-proof-v1' and
            repair.get('source_retained') is True and repair.get('replaced_roles') == ['b', 'frontend'] and
            repair.get('two_workers_admitted') is True and repair.get('checksum_bypassed') is False and
            all(type(repair.get(k)) is int and repair[k] == 0 for k in ('generation_requests', 'metadata_patches', 'registry_changes')),
            'Prepared capture lacks its explicit supported repair proof.')
    check_pod_transition(plan['original_pods'], selected['pods'], replace_b=True, replace_frontend=True)
    check_native_cards(selected['cards'], selected['native_checksums'], plan['expected_mdcsum'], matching=True)
    readiness_two_workers(selected['frontend_readiness'], plan['dynamo_namespace'])
    provenance = {'kind': 'prepared_parent', 'parent_run': plan['parent'], 'parent_capture': plan['parent_capture'],
                  'repair_sha256': binding['repair_sha256'], 'repair_completed_at': repair.get('completed_at'),
                  'repair_snapshot_sha256': repair['qualified_snapshot_sha256'],
                  'retained_source_uid': selected['pods']['a']['metadata']['uid'],
                  'receiver_uid': selected['pods']['b']['metadata']['uid'],
                  'frontend_uid': selected['pods']['frontend']['metadata']['uid'],
                  'two_workers_admitted': True, 'startup_measured_in_capture': False}
    return binding, provenance, {'repair.json': repair_bytes, 'plan.json': plan_bytes, 'snapshot.json': selected_bytes}


def validate_prepared_kvcr_capture(run, state):
    """Require the repaired identities and a distinct admission gate before each HTTP request."""
    from demos.kvcr.prepared import require, signature, check_pod_transition, check_native_cards, readiness_two_workers
    run = Path(run)
    binding, _, _ = prepared_provenance(run, state)
    plan, selected = binding['parent_plan'], binding['qualified_snapshot']
    parse = lambda value: dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    checks = []
    for path in sorted(run.glob('admission-*/snapshot.json')):
        check = json.loads(path.read_text())
        require(check.get('status') == 'passed' and check.get('two_workers_admitted') is True,
                'An admission snapshot did not qualify both workers.')
        check_pod_transition(plan['original_pods'], check['pods'], replace_b=True, replace_frontend=True)
        signatures = {r: signature(p) for r, p in check['pods'].items()}
        require(signatures == selected['pod_signatures'] == check['pod_signatures'] and
                check['worker_ids'] == selected['worker_ids'], 'Captured admission belongs to different repaired workers.')
        require(check['graph']['metadata']['uid'] == selected['graph']['metadata']['uid'] and
                check['graph']['spec'] == selected['graph']['spec'], 'Captured owning DGD changed.')
        check_native_cards(check['cards'], check['native_checksums'], plan['expected_mdcsum'], matching=True)
        readiness_two_workers(check['frontend_readiness'], plan['dynamo_namespace'])
        checks.append(parse(check['completed_at']))
    require(checks and any(at <= parse(state['source_request_started_at']) for at in checks),
            'No repaired two-worker admission gate precedes source HTTP.')
    require(any(parse(state['source_completed_at']) <= at <= parse(state['target_request_started_at']) for at in checks),
            'No fresh two-worker admission gate precedes receiver HTTP after source completion.')
    for role, worker in (('source', 'a'), ('target', 'b')):
        response = json.loads((run / role / 'response.json').read_text())
        require(response.get('workers') == [selected['worker_ids'][worker]] and response.get('http_requests') == 1,
                'Prepared response belongs to a different worker or repeated HTTP request.')


def completed(demo, run, rehearsal):
    """A zero process exit alone is insufficient to call this a full demo."""
    state = read_state(run)
    if state is None or state.get('rehearsal') is not rehearsal:
        return False, 'Missing or mismatched demo mode in demo.json.'
    if demo == COMPOSED_SHADOW:
        try:
            validate_shadow_composed_capture(run, state)
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            return False, 'Composed Shadow verification failed: ' + str(error)
        return True, 'Accepted writer, ready parked reader, one actual fault, replenishment and post-fault health verified.'
    if demo == '09-agentx-metrics':
        if (state.get('presentation_mode') != 'recorded-evidence' or state.get('step') != 3 or
                not state.get('completed_at')):
            return False, 'Recorded metrics walkthrough did not finish.'
        try:
            from demos.metrics.demo import validated_metrics
            measured, _, _ = validated_metrics(Path(run) / 'recording',
                json.loads((Path(run) / 'metric-definitions.json').read_text()))
            if json.loads((Path(run) / 'metrics-proof.json').read_text()) != measured:
                return False, 'Metrics differ from their verified source exports and definitions.'
        except (ValueError, OSError, KeyError, TypeError) as error:
            return False, 'Recorded metrics verification failed: ' + str(error)
        return True, 'Verified historical metrics walkthrough; no new live GPU measurement.'
    if demo == '06-routing':
        if (state.get('presentation_mode') != 'recorded-evidence' or state.get('step') != 4 or
                not state.get('completed_at')):
            return False, 'Recorded routing walkthrough did not finish.'
        try:
            from demos.routing.demo import load_recording
            metadata, studies, *_ = load_recording(Path(run) / 'recording')
            comparison = json.loads((Path(run) / 'comparison.json').read_text())
            if (comparison.get('simulated') is not False or comparison.get('studies') != studies or
                    comparison.get('recording_sha256') != sha256(Path(run) / 'recording/recording.json') or
                    comparison.get('measurement_class') != metadata['measurement_class']):
                return False, 'Recorded comparison differs from its verified source measurements.'
        except (ValueError, OSError, KeyError, TypeError) as error:
            return False, 'Recorded routing evidence failed verification: ' + str(error)
        return True, 'Verified historical measurement walkthrough; no new live GPU measurement.'
    expected = ['response.json', 'timing.json']
    if demo == '02-modelexpress':
        expected = ['response.json', 'comparison.json', 'peer-proof.json']
    elif demo == '03-disaggregated':
        expected.append('transfer-proof.json')
    elif demo in ('04-snapshot', '04-snapshot-dgd'):
        expected.append('recovery-proof.json')
    elif demo == '05-request-continuity':
        expected = ['comparison.json', 'disabled/proof.json', 'enabled/proof.json']
    elif demo in KVCR_DEMOS:
        expected.append('peer-proof.json')
        expected.append('prompt-preflight.json')
    elif demo == '08-shadow-engine':
        expected = ['recovery-proof.json']
    missing = [name for name in expected if not (Path(run) / name).is_file()]
    if missing:
        return False, 'Missing completion evidence: ' + ', '.join(missing)
    for name in expected:
        data = json.loads((Path(run) / name).read_text())
        simulated = data.get('simulated', data.get('rehearsal', False))
        if bool(simulated) != rehearsal:
            return False, 'Mode mismatch in ' + name
    if not state.get('ready_observed_at'):
        return False, 'No serving-readiness observation.'
    if demo == '04-snapshot-dgd':
        proof = json.loads((Path(run) / 'recovery-proof.json').read_text())
        initial, replacement = state.get('initial_identity', {}), state.get('replacement_identity', {})
        response = json.loads((Path(run) / 'response.json').read_text())
        stable = ('dgd_uid', 'frontend_uid', 'service_uid', 'checkpoint_uid', 'content_uid', 'node', 'gpu_uuids')
        if (state.get('step') != 4 or not proof.get('before_uid') or
                proof['before_uid'] == proof.get('after_uid') or
                proof['before_uid'] != initial.get('worker_uid') or proof.get('after_uid') != replacement.get('worker_uid') or
                any(not proof.get(key) or proof[key] != initial.get(key) or proof[key] != replacement.get(key)
                    for key in stable) or not response.get('content') or
                not response.get('worker', {}).get('decode_worker_id') or
                response['worker']['decode_worker_id'] == initial.get('response_worker', {}).get('decode_worker_id')):
            return False, 'Snapshot service/artifact identities or distinct-worker coding inference are missing.'
    if demo in KVCR_DEMOS and not rehearsal:
        try:
            validate_kvcr_preflight(run, state)
            if demo == '07-kvcr-prepared':
                validate_prepared_kvcr_capture(run, state)
        except (ValueError, OSError, KeyError, TypeError) as error:
            return False, 'KVCR prompt preflight failed verification: ' + str(error)
        proof = json.loads((Path(run) / 'peer-proof.json').read_text())
        if (proof.get('status') != 'passed' or state.get('step') != 5 or
                any(not isinstance(proof.get(key), (int, float)) or proof[key] <= 0
                    for key in ('blocks', 'bytes', 'external_cache_tokens', 'cached_prompt_tokens')) or
                not proof.get('matched_transfers') or not proof.get('source_workers') or
                proof.get('source_workers') == proof.get('target_workers')):
            return False, 'Positive matched peer-transfer and prompt-reuse evidence is missing.'
    if demo == '08-shadow-engine':
        proof = json.loads((Path(run) / 'recovery-proof.json').read_text())
        # The run's frozen lock sets its TP: 2 for Super VL, 1 for the Qwen variant.
        lock = Path(run) / 'model-lock.json'
        locked_tp = json.loads(lock.read_text()).get('tensor_parallel_size') if lock.is_file() else 2
        if (state.get('step') != 4 or proof.get('status') != ('simulated' if rehearsal else 'passed') or
                not proof.get('new_standby_confirmed') or (not rehearsal and (
                    proof.get('tensor_parallel_size') != locked_tp or not proof.get('worker_before') or
                    proof.get('worker_before') == proof.get('worker_after')))):
            return False, 'Shadow promotion, distinct worker or standby replenishment is missing.'
    if demo == '05-request-continuity':
        disabled = json.loads((Path(run) / 'disabled/proof.json').read_text())
        enabled = json.loads((Path(run) / 'enabled/proof.json').read_text())
        if (disabled.get('successful_completion') or not enabled.get('successful_completion') or
                any(p.get('http_requests') != 1 for p in (disabled, enabled)) or
                (not rehearsal and not enabled.get('continuation_workers'))):
            return False, 'Continuity outcome or one-request evidence is missing.'
    return True, 'Expected demo completion artifacts and readiness are present.'


def stop_group(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def record(command, raw_directory, *, mirror=True, timeout=14400, width=180, source_files=()):
    """Run only the main panel on a PTY, with stdout/stderr in terminal order."""
    raw_directory = Path(raw_directory)
    raw_directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(raw_directory, 0o700)
    # Capture source bytes before launching the child; later fixes must not
    # change the code provenance of an already recorded attempt.
    source_hashes = snapshot_files(source_files, raw_directory / 'sources', source_ids=True)
    raw_path = raw_directory / 'main-panel.ansi'
    timeline_path = raw_directory / 'timeline.jsonl'
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 50, width, 0, 0))
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
               TERM='xterm-256color', COLUMNS=str(width), LINES='50')
    start = time.monotonic()
    process = None
    interrupted = False
    timed_out = False
    try:
        with raw_path.open('xb') as output, timeline_path.open('x') as timeline:
            os.chmod(raw_path, 0o600)
            os.chmod(timeline_path, 0o600)
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                       cwd=ROOT, env=env, close_fds=True, start_new_session=True)
            os.close(slave)
            slave = None
            offset = 0
            while True:
                try:
                    if time.monotonic() - start > timeout and process.poll() is None:
                        timed_out = True
                        stop_group(process)
                    available, _, _ = select.select([master], [], [], 0.5)
                    if available:
                        try:
                            block = os.read(master, 65536)
                        except OSError as error:
                            if error.errno != errno.EIO:
                                raise
                            block = b''
                        if not block:
                            break
                        output.write(block)
                        output.flush()
                        timeline.write(json.dumps({'elapsed_seconds': time.monotonic() - start,
                                                   'offset': offset, 'bytes': len(block)}) + '\n')
                        timeline.flush()
                        offset += len(block)
                        if mirror:
                            sys.stdout.buffer.write(block)
                            sys.stdout.buffer.flush()
                    elif process.poll() is not None:
                        break
                except KeyboardInterrupt:
                    interrupted = True
                    stop_group(process)
            code = process.wait(timeout=15)
    finally:
        if process is not None:
            stop_group(process)
        os.close(master)
        if slave is not None:
            os.close(slave)
    return {'exit_code': code, 'interrupted': interrupted, 'timed_out': timed_out,
            'elapsed_seconds': time.monotonic() - start,
            'raw_path': str(raw_path), 'timeline_path': str(timeline_path),
            'source_snapshot_directory': str(raw_directory / 'sources'), 'source_sha256': source_hashes}


def capture(args):
    if getattr(args, 'finalize_pending', False):
        return finalize_pending_shadow(args)
    deferred = getattr(args, 'defer_qualification', False)
    if deferred and (args.demo != COMPOSED_SHADOW or args.rehearsal):
        raise ValueError('Deferred qualification is only available for actual composed Shadow capture.')
    output = args.output.resolve()
    run = args.run.resolve()
    if output == run or output in run.parents or run in output.parents:
        raise ValueError('Use separate, non-nested demo-run and transcript-attempt directories.')
    if output.exists():
        raise ValueError('Transcript attempt already exists; choose a new --output directory.')
    before = read_state(run)
    if before is None and run.exists() and any(run.iterdir()):
        raise ValueError('Existing nonempty --run lacks demo.json; use a fresh or explicitly primed demo run.')
    if before is not None and before.get('rehearsal') is not args.rehearsal:
        raise ValueError('Existing run uses a different rehearsal/live mode.')
    if (args.demo in ('06-routing', '09-agentx-metrics') and not args.rehearsal and
            (before is None or not before.get('prepared') or before.get('cleaned_at'))):
        raise ValueError('Prepare the recorded walkthrough offstage before capture:\n' +
                         shlex.join([sys.executable, '-m', 'demos', DEMOS[args.demo].selector,
                                     'prepare', '--run', str(run)]))
    provenance, prepared_bytes, pre_fault_health_bytes, pre_fault_health = None, None, None, None
    intro_bytes, mx_binding_bytes = None, None
    if args.demo == '02-modelexpress' and not args.rehearsal:
        if before is None:
            raise ValueError('Prepare ModelExpress from the completed first replica before capturing it.')
        if before.get('source_binding') is not None:
            provenance, intro_bytes, mx_binding_bytes = modelexpress_source_provenance(run, before)
    if args.demo == '07-kvcr-prepared':
        if args.rehearsal or before is None:
            raise ValueError('Prepared KVCR capture needs an explicitly bound live child; use 07-kvcr for rehearsal.')
        _, provenance, prepared_bytes = prepared_provenance(run, before, check_owner=True)
    if args.demo == COMPOSED_SHADOW:
        if args.rehearsal or before is None:
            raise ValueError('Composed Shadow capture requires a frozen, offstage-primed live run.')
        provenance = shadow_composed_provenance(run, before)
        if (any((run / name).exists() for name in ('shadow-fault-intent.json', 'shadow-fault.json', 'recovery-proof.json')) or
                any(key in json.loads((run / 'state.json').read_text()).get('checks', {})
                    for key in ('shadow-failover', 'shadow-full-qualification'))):
            raise ValueError('Capture must begin before the first actual composed Shadow fault.')
        health_source = getattr(args, 'pre_fault_health', None)
        if health_source is None:
            raise ValueError('Composed Shadow capture requires explicit --pre-fault-health receipt.')
        health_source = Path(health_source).resolve()
        pre_fault_health_bytes = health_source.read_bytes()
        receipt = json.loads(pre_fault_health_bytes)
        import demos.shadow.composed as full
        baseline = json.loads((run / 'health-before.json').read_text())['receipt']
        ready_time = json.loads((run / 'state.json').read_text())['checks']['shadow-full-ready']['updated_at']
        if (receipt.get('node') != full.NODE or _shadow_time(receipt['observed_at']) < _shadow_time(ready_time) or
                receipt.get('changed_conditions') or not receipt.get('outputs') or
                any(v.get('exit_code') != 0 for v in receipt['outputs'].values()) or
                receipt.get('driver_pod_uid') != baseline['driver_pod_uid'] or
                receipt.get('node_status', {}).get('nodeInfo', {}).get('bootID') != baseline['node_status']['nodeInfo']['bootID']):
            raise ValueError('Pre-fault health receipt is stale, incomplete or belongs to a different driver/node boot.')
        pre_fault_health = {'source': str(health_source), 'source_sha256': hashlib.sha256(pre_fault_health_bytes).hexdigest(),
                            'observed_at': receipt['observed_at']}
    raw_output = (args.raw_output or ROOT / 'results/demo-recordings' /
                  (args.demo + '-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))).resolve()
    if raw_output == output or output in raw_output.parents or raw_output in output.parents:
        raise ValueError('Raw/private capture must be separate from the shareable transcript attempt.')
    if raw_output.exists():
        raise ValueError('Raw capture directory already exists; choose a fresh --raw-output.')
    command = [sys.executable, '-B', '-m', 'demos', DEMOS[args.demo].selector,
               'run', '--plain', '--auto', '--run', str(run), '--timeout', str(args.startup_timeout)]
    if args.port is not None:
        command += ['--port', str(args.port)]
    if args.rehearsal:
        command.append('--rehearsal')
    if pre_fault_health is not None:
        command += ['--health-after', pre_fault_health['source']]
    output.mkdir(parents=True, exist_ok=False)
    source_files = demo_sources(ROOT)
    was_started = bool(before and (before.get('apply_started_at') or before.get('arms') or
                                  before.get('restores') or before.get('cases') or before.get('initial_identity') or
                                  (args.demo == '07-kvcr-prepared' and before.get('prepared_parent'))))
    recorded = args.demo in ('06-routing', '09-agentx-metrics')
    mode = 'rehearsal' if args.rehearsal else 'recorded-evidence' if recorded else 'live'
    before_arms = sorted((before or {}).get('arms', {}))
    if recorded:
        startup_scope = 'No live deployment or startup: this presents historical measurement evidence.'
    elif args.demo == '07-kvcr-prepared':
        startup_scope = ('Workers were prepared offstage in the owning parent; the declared B/frontend refresh '
                         'predates recording. This capture measures no deployment or startup interval.')
    elif args.demo == COMPOSED_SHADOW:
        startup_scope = ('Writer qualification and initial active/parked reader startup were prepared offstage. '
                         'This records the first actual single fault and recovery, not deployment/startup timing.')
    elif args.demo == '02-modelexpress' and 'storage' in before_arms and 'peer' not in before_arms:
        startup_scope = ('First-replica storage startup is pre-existing evidence from demo 1. '
                         'Peer-arm startup begins during this recording; use its separate arm timing.')
    elif args.demo == '02-modelexpress' and {'source', 'native'} <= set(before_arms) and 'peer' not in before_arms:
        startup_scope = ('Source and storage-baseline startup are pre-existing offstage evidence. '
                         'Peer-arm startup begins during this recording; use its separate arm timing.')
    elif was_started:
        startup_scope = 'Pre-existing startup evidence; recording is not a new startup measurement.'
    else:
        startup_scope = 'Run had no startup record when capture began; see demo timing boundaries.'
    manifest = {'schema': 1, 'demo': args.demo, 'mode': mode,
                'status': 'running', 'started_at': utc(), 'command': command, 'run': str(run),
                'output': str(output), 'raw_output': str(raw_output),
                'preexisting_run': before is not None, 'preexisting_startup': was_started,
                'startup_scope': startup_scope, 'startup_arms_before': before_arms,
                'main_panel_only': True, 'automatic_advance': True, 'defer_qualification': deferred,
                'source_sha256': {source_name(p, root=ROOT): sha256(p) for p in source_files},
                'state_before_sha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest() if before else None}
    if provenance is not None:
        manifest['startup_provenance'] = provenance
    if pre_fault_health is not None:
        manifest['pre_fault_health'] = pre_fault_health
    dump(output / 'capture.json', manifest)
    try:
        receipt = record(command, raw_output, mirror=not args.quiet, timeout=args.capture_timeout,
                         width=args.width, source_files=source_files)
        if before is not None:
            dump(raw_output / 'demo-before.json', before)
            (raw_output / 'demo-before.json').chmod(0o400)
            manifest['state_before_sha256'] = sha256(raw_output / 'demo-before.json')
        manifest.update(receipt)
        if pre_fault_health_bytes is not None:
            if Path(pre_fault_health['source']).read_bytes() != pre_fault_health_bytes:
                raise ValueError('Bound pre-fault health source changed during the recorded run.')
            captured_health = json.loads((run / 'health-before-fault.json').read_text())
            if (captured_health.get('source_sha256') != pre_fault_health['source_sha256'] or
                    captured_health.get('receipt') != json.loads(pre_fault_health_bytes)):
                raise ValueError('Recorded fault used a different health receipt from the explicit capture binding.')
            bound_path = raw_output / 'pre-fault-health-source.json'
            with bound_path.open('xb') as stream: stream.write(pre_fault_health_bytes)
            bound_path.chmod(0o400)
        evidence = raw_output / 'evidence'
        evidence_hashes = snapshot_files(evidence_files(args.demo, run), evidence, relative_root=run)
        if intro_bytes is not None:
            if (evidence / 'source-binding.json').read_bytes() != mx_binding_bytes:
                raise ValueError('The first-replica binding changed during the recorded ModelExpress run.')
            archived = evidence / 'source-intro'
            archived.mkdir(mode=0o700)
            for name, data in intro_bytes.items():
                target = archived / name
                with target.open('xb') as stream:
                    stream.write(data)
                target.chmod(0o400)
                evidence_hashes['source-intro/' + name] = sha256(target)
        if prepared_bytes is not None:
            archived = evidence / 'prepared-parent'
            archived.mkdir(mode=0o700)
            for name, data in prepared_bytes.items():
                target = archived / name
                with target.open('xb') as stream:
                    stream.write(data)
                target.chmod(0o400)
                evidence_hashes['prepared-parent/' + name] = sha256(target)
        if receipt['exit_code'] == 0 and deferred:
            validate_shadow_composed_capture(evidence, read_state(evidence), require_health=False)
            valid, validation = True, 'Actual first-fault recording sealed; post-fault health and controller finalization pending.'
        else:
            valid, validation = completed(args.demo, evidence, args.rehearsal) if receipt['exit_code'] == 0 else (
                False, 'Demo process did not complete successfully.')
        success = receipt['exit_code'] == 0 and valid and not receipt['interrupted'] and not receipt['timed_out']
        text, redactions = sanitize(plain_text(Path(receipt['raw_path']).read_bytes()))
        filename = ('pending-main.txt' if deferred else 'rehearsal-main.txt' if args.rehearsal else 'recorded-main.txt' if recorded else 'main.txt') if success else 'failed-main.txt'
        (output / filename).write_text(text)
        manifest.update(status=('pending_qualification' if deferred else 'rehearsal_passed' if args.rehearsal else 'recorded_evidence_passed' if recorded else 'live_passed') if success else 'failed',
                        finished_at=utc(), completion_validation=validation, transcript=filename,
                        redaction_count=redactions, share_review='Review main text before external publication; raw terminal capture stays private.',
                        transcript_sha256=sha256(output / filename), raw_sha256=sha256(receipt['raw_path']),
                        evidence_snapshot_directory=str(evidence), evidence_sha256=evidence_hashes)
        if success and deferred:
            manifest['timeline_sha256'] = sha256(receipt['timeline_path'])
            sealed = raw_output / 'pending-receipt.json'
            dump(sealed, manifest)
            sealed.chmod(0o400)
            manifest['pending_receipt_sha256'] = sha256(sealed)
        dump(output / 'capture.json', manifest)
        print('\nCapture: ' + str(output / filename) + '\nStatus: ' + manifest['status'], flush=True)
        return (0 if success else 124 if receipt['timed_out'] else 130 if receipt['interrupted'] else
                receipt['exit_code'] if receipt['exit_code'] > 0 else 1)
    except BaseException as error:
        manifest.update(status='capture_error', finished_at=utc(), error=type(error).__name__ + ': ' + str(error))
        raw = raw_output / 'main-panel.ansi'
        if raw.exists():
            text, redactions = sanitize(plain_text(raw.read_bytes()))
            (output / 'failed-main.txt').write_text(text)
            manifest.update(transcript='failed-main.txt', transcript_sha256=sha256(output / 'failed-main.txt'),
                            raw_sha256=sha256(raw), redaction_count=redactions)
        dump(output / 'capture.json', manifest)
        raise


def finalize_pending_shadow(args):
    """Append independently finalized health/proof without rerunning any child or fault."""
    if args.demo != COMPOSED_SHADOW or args.rehearsal or getattr(args, 'defer_qualification', False):
        raise ValueError('Pending finalization is only available for a live composed Shadow attempt.')
    output, run = args.output.resolve(), args.run.resolve()
    manifest_path = output / 'capture.json'
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get('status') != 'pending_qualification' or manifest.get('demo') != args.demo or
            manifest.get('mode') != 'live' or manifest.get('run') != str(run) or
            manifest.get('output') != str(output) or manifest.get('defer_qualification') is not True or
            manifest.get('exit_code') != 0 or manifest.get('interrupted') is not False or manifest.get('timed_out') is not False):
        raise ValueError('Only the exact successful pending recording can be finalized; terminal attempts stay closed.')
    private = Path(manifest['raw_output']).resolve()
    if args.raw_output is not None and args.raw_output.resolve() != private:
        raise ValueError('Pending private recording directory changed.')
    sealed_path = _shadow_file(private, 'pending-receipt.json')
    sealed = json.loads(sealed_path.read_text())
    if sha256(sealed_path) != manifest.get('pending_receipt_sha256') or \
            sealed != {key: value for key, value in manifest.items() if key != 'pending_receipt_sha256'}:
        raise ValueError('Sealed pending capture receipt changed.')
    if (manifest.get('raw_path') != str(private / 'main-panel.ansi') or
            manifest.get('source_snapshot_directory') != str(private / 'sources') or
            manifest.get('evidence_snapshot_directory') != str(private / 'evidence') or
            manifest.get('transcript') != 'pending-main.txt' or
            sha256(_shadow_file(private, 'main-panel.ansi')) != manifest['raw_sha256'] or
            sha256(_shadow_file(private, 'timeline.jsonl')) != manifest.get('timeline_sha256') or
            sha256(_shadow_file(private, 'demo-before.json')) != manifest.get('state_before_sha256') or
            sha256(_shadow_file(output, 'pending-main.txt')) != manifest['transcript_sha256'] or
            (output / 'main.txt').exists() or (private / 'final-evidence').exists()):
        raise ValueError('Pending raw/transcript/evidence identity changed or final output already exists.')
    if sha256(_shadow_file(private, 'pre-fault-health-source.json')) != manifest.get('pre_fault_health', {}).get('source_sha256'):
        raise ValueError('Sealed pre-fault health source changed.')
    for name, digest in manifest['source_sha256'].items():
        if sha256(_shadow_file(private, 'sources/' + name)) != digest or sha256(source_path(name, root=ROOT)) != digest:
            raise ValueError('Captured source changed before qualification: ' + name)
    for name, digest in manifest['evidence_sha256'].items():
        if sha256(_shadow_file(private, 'evidence/' + name)) != digest:
            raise ValueError('Sealed pending evidence changed: ' + name)
        if name != 'state.json' and sha256(_shadow_file(run, name)) != digest:
            raise ValueError('Run evidence drifted after the actual recorded fault: ' + name)
    additions = {str(path.relative_to(run)) for path in evidence_files(args.demo, run)} - set(manifest['evidence_sha256'])
    if any(name != 'health-after.json' and re.fullmatch(r'check-shadow-full-qualification-[0-9]+\.json', name) is None
            for name in additions):
        raise ValueError('Pending run gained evidence beyond post-fault health and full qualification.')
    previous = json.loads(_shadow_file(private, 'evidence/state.json').read_text())
    current = json.loads(_shadow_file(run, 'state.json').read_text())
    def stable(value):
        value = json.loads(json.dumps(value))
        value.pop('attempts', None)
        value.get('checks', {}).pop('shadow-full-qualification', None)
        return value
    if stable(previous) != stable(current) or current.get('attempts', [])[:len(previous.get('attempts', []))] != previous.get('attempts', []):
        raise ValueError('Pending run identity or checks drifted beyond appended full qualification.')
    provenance = validate_shadow_composed_capture(run, read_state(run))
    if provenance != manifest['startup_provenance']:
        raise ValueError('Qualified run does not match the recorded writer/reader/DGD provenance.')
    final_evidence = private / 'final-evidence'
    final_hashes = snapshot_files(evidence_files(args.demo, run), final_evidence, relative_root=run)
    valid, reason = completed(args.demo, final_evidence, False)
    if not valid: raise ValueError(reason)
    transcript = _shadow_file(output, 'pending-main.txt').read_bytes()
    with (output / 'main.txt').open('xb') as stream: stream.write(transcript)
    manifest.update(status='live_passed', qualified_at=utc(), transcript='main.txt',
        completion_validation=reason, final_evidence_snapshot_directory=str(final_evidence),
        final_evidence_sha256=final_hashes, qualification_method='appended external post-fault health and full-controller qualification; original PTY unchanged')
    dump(manifest_path, manifest)
    print('Capture: ' + str(output / 'main.txt') + '\nStatus: live_passed', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', choices=list(DEMOS), required=True)
    parser.add_argument('--run', type=Path, required=True, help='Fresh or pre-primed demo run; never a historical result directory.')
    parser.add_argument('--output', type=Path, required=True, help='Fresh immutable transcript-attempt directory.')
    parser.add_argument('--raw-output', type=Path, help='Fresh private raw-output directory; default: ignored results/demo-recordings/.')
    parser.add_argument('--rehearsal', action='store_true', help='Explicitly simulated; never emits a live main.txt.')
    parser.add_argument('--quiet', action='store_true', help='Capture without mirroring the terminal to stdout.')
    parser.add_argument('--startup-timeout', type=int, default=2700)
    parser.add_argument('--capture-timeout', type=int, default=14400, help='Overall capture limit in seconds (default: four hours).')
    parser.add_argument('--width', type=int, default=180)
    parser.add_argument('--port', type=int)
    parser.add_argument('--pre-fault-health', type=Path, help='Composed Shadow only: explicit fresh health receipt passed to the child fault gate as --health-after.')
    parser.add_argument('--defer-qualification', action='store_true', help='Composed Shadow only: seal the first fault recording pending external post-fault health/finalize.')
    parser.add_argument('--finalize-pending', action='store_true', help='Composed Shadow only: append final qualification to the exact pending recording; never rerun it.')
    args = parser.parse_args()
    if min(args.startup_timeout, args.capture_timeout, args.width) <= 0:
        parser.error('Timeouts and terminal width must be positive.')
    if args.port is not None and not 0 < args.port < 65536:
        parser.error('Port must be 1..65535.')
    try:
        return capture(args)
    except (RuntimeError, ValueError, OSError) as error:
        print('Capture stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
