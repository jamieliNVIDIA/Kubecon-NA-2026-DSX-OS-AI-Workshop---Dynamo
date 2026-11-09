#!/usr/bin/env python3
"""Observe a broken coding response, then the same process fault with token replay enabled."""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import urllib.request

import demos.common.placement as placement
import demos.common.runtime as ui
import demos.common.support as support
from scripts.source_paths import source_path
from demos.request_continuity.evidence import retry_proof

GRAPH = 'demo-continuity'
OWNER = 'workshop-demo-continuity'
PROFILE = 'super-vl-continuity-text-eager-v2'
PROBE = Path(__file__).with_name('probe.py')
EVIDENCE = Path(__file__).with_name('evidence.py')
ARMS = {'disabled': 0, 'enabled': 3}
PINNED = {arm: 2 for arm in ARMS}  # Opt-in placement: one target per worker, each on its own node.
FAULT_AFTER_CHUNKS = 16
STEPS = [
    ('Two prepared cases', 'The same two-worker configuration, with frontend migration set to zero or three.'),
    ('Break a streaming response', 'After visible output, kill its serving EngineCore and inspect the stream failure.'),
    ('Continue through worker failure', 'Repeat with migration enabled: follow one request across two workers.'),
    ('Inspect request continuity', 'Compare completion, retained output and worker changes; distinguish client gaps from the handoff.'),
]


def render(namespace, lock, arm):
    graph, claim = ui.render(namespace, lock, enable_mx=False)
    name = GRAPH + '-' + arm
    graph['metadata'] = {'name': name, 'namespace': namespace}
    claim['metadata'] = {'name': name + '-gpus', 'namespace': namespace}
    for component in graph['spec']['components']:
        worker = component['type'] == 'worker'
        component['replicas'] = 2 if worker else 1
        pod = component['podTemplate']
        pod['metadata'] = {'labels': {'feature-test-run': namespace,
                                     'workshop-demo': 'continuity', 'workshop-arm': arm,
                                     'workshop-role': 'worker' if worker else 'frontend'}}
        if worker:
            spec = pod['spec']
            spec['resourceClaims'][0]['resourceClaimTemplateName'] = claim['metadata']['name']
            spec['affinity']['podAntiAffinity'] = {'requiredDuringSchedulingIgnoredDuringExecution': [
                {'topologyKey': 'kubernetes.io/hostname', 'labelSelector': {'matchLabels': {
                    'workshop-demo': 'continuity', 'workshop-arm': arm, 'workshop-role': 'worker'}}}]}
        else:
            pod['spec']['containers'][0]['env'] += [
                {'name': 'DYN_MIGRATION_LIMIT', 'value': str(ARMS[arm])},
                {'name': 'DYN_HTTP_BACKEND_STREAM_TIMEOUT_SECS', 'value': '30'}]
    return graph, claim


def settings_excerpt(graphs):
    """Project the actual case manifests, rather than restating their defaults."""
    cases = {}
    for arm, graph in graphs.items():
        frontend = next(c for c in graph['spec']['components'] if c['type'] == 'frontend')
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        frontend_main = frontend['podTemplate']['spec']['containers'][0]
        env = {item['name']: item.get('value') for item in frontend_main['env']}
        args = worker['podTemplate']['spec']['containers'][0]['args']
        cases[arm] = {
            'frontend': {name: env[name] for name in
                         ('DYN_MIGRATION_LIMIT', 'DYN_HTTP_BACKEND_STREAM_TIMEOUT_SECS')},
            'worker_replicas': worker['replicas'],
            'tensor_parallel_size': int(args[args.index('--tensor-parallel-size') + 1]),
        }
    return {'cases': cases, 'client_retries': 0,
            'fault_after_visible_content_chunks': FAULT_AFTER_CHUNKS}


def outcome_summary(proof):
    """Keep display claims within the saved proof's actual measurement scope."""
    simulated = proof.get('simulated', False)
    trace = proof.get('migration_trace') or {}
    retained = trace.get('retained_output_tokens')
    gap = proof.get('client_recovery_gap_seconds')
    max_gap = proof.get('max_client_inter_content_gap_seconds')
    sticky = proof.get('worker_attribution') == 'correlated_frontend_trace_sse_sticky'
    exact_gap = ('not measured' if simulated else 'unavailable (sticky SSE)' if sticky else
                 f'{gap:.2f}s' if gap is not None else 'not applicable')
    return {
        'Outcome': 'completed' if proof['successful_completion'] else 'interrupted',
        'HTTP requests': 'simulated' if simulated else str(proof['http_requests']),
        'Client response ID': 'not measured' if simulated else 'stable',
        'Worker transition': 'simulated' if simulated else
                             'peer observed' if proof.get('continuation_workers') else 'stream interrupted',
        'Accepted output retained': f'{retained} tokens' if retained is not None else 'not reported',
        'Finish reason': 'not measured' if simulated else
                         ', '.join(proof.get('finish_reasons', [])) or 'no successful finish',
        'Exact handoff gap': exact_gap,
        'Max client content gap': f'{max_gap:.2f}s' if max_gap is not None else 'not measured',
    }


def ready(pods):
    active = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
    return (len(active) == 3 and
            sum(p['metadata']['labels']['workshop-role'] == 'worker' for p in active) == 2 and
            sum(p['metadata']['labels']['workshop-role'] == 'frontend' for p in active) == 1 and
            all(any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in p.get('status', {}).get('conditions', [])) for p in active))


def registered_workers(pods, metadata, namespace):
    """Join generate IDs to live Pod UIDs; names or stale metadata alone are insufficient."""
    workers = {p['metadata']['name']: p for p in pods
               if p['metadata']['labels']['workshop-role'] == 'worker'}
    result = {}
    for item in metadata:
        pod = workers.get(item['metadata']['name'])
        if not pod:
            continue
        if (pod['metadata'].get('namespace') != namespace or
                item['metadata'].get('namespace') != namespace or
                pod['metadata'].get('labels', {}).get('feature-test-run') != namespace or
                not any(o.get('kind') == 'Pod' and o.get('uid') == pod['metadata']['uid']
                        for o in item['metadata'].get('ownerReferences', []))):
            raise ValueError('Worker metadata is not owned by the current demo Pod.')
        ids = {str(e['instance_id']) for e in item['spec']['data'].get('endpoints', {}).values()
               if e.get('component') == 'backend' and e.get('endpoint') == 'generate'}
        if len(ids) != 1 or next(iter(ids)) in result:
            raise ValueError('Expected one unique generate endpoint per worker.')
        result[next(iter(ids))] = pod
    if len(result) != 2:
        raise ValueError('Expected two current registered workers.')
    return result


def verify_survivors(before, after, fault_uid):
    """The client frontend and qualified peer must survive, including their containers."""
    current = {p['metadata']['name']: p for p in after}
    expected = {p['metadata']['name']: p for p in before if p['metadata']['uid'] != fault_uid}
    if len(expected) != 2 or not set(expected).issubset(current):
        raise ValueError('The frontend or surviving worker disappeared.')
    for name, old in expected.items():
        pod = current[name]
        if pod['metadata']['uid'] != old['metadata']['uid'] or pod['metadata'].get('deletionTimestamp'):
            raise ValueError('An unfaulted Pod was replaced or is terminating.')
        if not any(c['type'] == 'Ready' and c['status'] == 'True'
                   for c in pod.get('status', {}).get('conditions', [])):
            raise ValueError('An unfaulted Pod is no longer Ready.')
        containers = lambda p: {s['name']: s.get('containerID')
                                for s in p.get('status', {}).get('containerStatuses', [])}
        if not containers(old) or containers(pod) != containers(old):
            raise ValueError('An unfaulted container identity changed.')
        support.healthy([pod])


def worker_id(chunk):
    value = chunk.get('nvext', {}).get('worker_id', {})
    if isinstance(value, dict):
        value = value.get('decode_worker_id')
    return str(value) if value is not None else None


def content(chunk):
    return ''.join(choice.get('delta', {}).get('content') or '' for choice in chunk.get('choices', []))


def capture_stream(base, body, directory, on_fault, *, threshold=FAULT_AFTER_CHUNKS, echo=True):
    """One HTTP request, no SDK/retries. Keep reading while a separate thread injects the fault."""
    directory = Path(directory)
    events = []
    fault = {}
    started = time.monotonic()
    fault_thread = None
    texts = 0
    current_worker = None

    def inject(target):
        fault['submitted_at_seconds'] = time.monotonic() - started
        try:
            fault['receipt'] = on_fault(target)
        except Exception as error:
            fault['error'] = str(error)
        finally:
            fault['acknowledged_at_seconds'] = time.monotonic() - started
            ui.write_json(directory / 'fault-result.json', fault)

    def event(value):
        row = {'seconds': time.monotonic() - started, 'at': ui.now(), **value}
        events.append(row)
        with (directory / 'events.jsonl').open('a') as log:
            log.write(json.dumps(row) + '\n')
        return row

    def dispatch(data):
        nonlocal texts, current_worker, fault_thread
        if data == '[DONE]':
            event({'type': 'done'})
            if echo:
                print('\n[data: [DONE]]', flush=True)
            return
        chunk = json.loads(data)
        current_worker = worker_id(chunk) or current_worker
        text = content(chunk)
        event({'type': 'chunk', 'chunk': chunk, 'worker': current_worker, 'content': text})
        if echo and text:
            print(text, end='', flush=True)
        if echo and chunk.get('error'):
            print('\n[stream error] ' + json.dumps(chunk['error']), flush=True)
        if text:
            texts += 1
        if texts >= threshold and fault_thread is None:
            if current_worker is None:
                raise ValueError('No serving worker identity before the fault gate.')
            event({'type': 'fault_gate', 'worker': current_worker, 'visible_chunks': texts})
            fault_thread = threading.Thread(target=inject, args=(current_worker,), daemon=True)
            fault_thread.start()

    req = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    error = None
    status = None
    try:
        with urllib.request.urlopen(req, timeout=180) as response, (directory / 'response.sse').open('wb') as raw:
            status = response.status
            ui.write_json(directory / 'http.json', {'status': status, 'headers': dict(response.headers),
                                                   'started_at': ui.now(), 'request_count': 1})
            pending = []
            while True:
                if time.monotonic() - started > 240:
                    raise TimeoutError('Streaming request exceeded its whole-response bound.')
                line = response.readline()
                if not line:
                    if pending:
                        raise ValueError('SSE ended with an unterminated event.')
                    break
                raw.write(line)
                raw.flush()
                line = line.decode('utf-8').rstrip('\r\n')
                if not line:
                    if pending:
                        dispatch('\n'.join(pending))
                        pending = []
                elif line.startswith('data:'):
                    pending.append(line[5:].lstrip(' '))
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
        event({'type': 'read_error', 'error': error})
        if echo:
            print('\n[client read error] ' + json.dumps(error), flush=True)
    finally:
        if fault_thread:
            fault_thread.join(timeout=50)
            if fault_thread.is_alive():
                raise RuntimeError('Fault injector has not quiesced; preserve this run and its GPU lease.')
    result = {'simulated': False, 'http_status': status, 'request_count': 1,
              'events': events, 'fault': fault, 'read_error': error}
    ui.write_json(directory / 'stream.json', result)
    return result


def validate_stream(result, arm, model, workers, *, frontend_log=None):
    events = result['events']
    gates = [e for e in events if e['type'] == 'fault_gate']
    receipt = result.get('fault', {}).get('receipt', {})
    if (result.get('request_count') != 1 or result.get('http_status') != 200 or len(gates) != 1 or
            not receipt.get('signal_sent') or receipt.get('signal') != 'SIGKILL' or
            result.get('fault', {}).get('error')):
        raise ValueError('One streaming request and one acknowledged mid-output fault are required.')
    target = gates[0]['worker']
    if (target not in workers or receipt.get('worker_id') != target or
            receipt.get('pod_uid') != workers[target]['uid'] or
            result['fault']['submitted_at_seconds'] < gates[0]['seconds']):
        raise ValueError('Fault target does not match the observed serving worker.')
    chunks = [e for e in events if e['type'] == 'chunk']
    if any(e['chunk'].get('model') != model or not e['chunk'].get('id')
           for e in chunks if e['chunk'].get('choices')):
        raise ValueError('Unexpected response model.')
    ids = {e['chunk']['id'] for e in chunks if e['chunk'].get('id')}
    if len(ids) != 1:
        raise ValueError('Expected one stable client response identity.')
    text_events = [e for e in chunks if e.get('content')]
    before = [e for e in text_events if e['seconds'] <= gates[0]['seconds']]
    if len(before) < FAULT_AFTER_CHUNKS or any(e['worker'] != target for e in before):
        raise ValueError('The fault must follow visible output from its actual target.')
    if any(e['type'] == 'done' or
           any(c.get('finish_reason') for c in e.get('chunk', {}).get('choices', []))
           for e in events if e['seconds'] <= gates[0]['seconds']):
        raise ValueError('The response already ended before fault injection.')
    if any(c.get('index', 0) != 0 for e in chunks for c in e['chunk'].get('choices', [])):
        raise ValueError('This demo requires one output choice.')
    errors = [e['chunk']['error'] for e in chunks if e['chunk'].get('error')]
    finishes = [c.get('finish_reason') for e in chunks for c in e['chunk'].get('choices', [])
                if c.get('finish_reason')]
    successful = bool(finishes) and all(f in ('stop', 'length') for f in finishes)
    done = any(e['type'] == 'done' for e in events)
    resumed = [e for e in text_events if e['worker'] in workers and e['worker'] != target and
               e['seconds'] >= result['fault']['submitted_at_seconds']]
    trace = None
    if arm == 'enabled' and not resumed and frontend_log is not None:
        trace = retry_proof(frontend_log, next(iter(ids)), target, workers)
    if arm == 'disabled':
        if resumed or successful or not (errors or result.get('read_error') or not finishes):
            raise ValueError('Migration-disabled case did not expose an interrupted response.')
    elif arm == 'enabled':
        if errors or result.get('read_error') or not successful or not done or not (resumed or trace):
            raise ValueError('Migration-enabled stream did not continue on a healthy peer and finish.')
        if any(e['worker'] not in workers for e in text_events):
            raise ValueError('A replacement/restarted worker was used instead of the qualified survivor.')
        first = resumed[0] if resumed else next((e for e in text_events
            if e['seconds'] > result['fault']['acknowledged_at_seconds']), None)
        if first is None:
            raise ValueError('No visible continuation after the acknowledged fault.')
        if resumed and any(e['worker'] == target for e in text_events if e['seconds'] >= first['seconds']):
            raise ValueError('Output returned to the failed worker after peer continuation.')
        final = [e for e in chunks if any(c.get('finish_reason') for c in e['chunk'].get('choices', []))]
        dones = [e for e in events if e['type'] == 'done']
        if (len(final) != 1 or final[0]['seconds'] < first['seconds'] or len(dones) != 1 or
                dones[0]['seconds'] < final[0]['seconds'] or events[-1]['type'] != 'done'):
            raise ValueError('Expected one terminal completion followed by DONE after peer output.')
    else:
        raise ValueError('Unknown case.')
    gap = None
    if resumed:
        first = resumed[0]
        last = max(e['seconds'] for e in text_events if e['worker'] == target and e['seconds'] < first['seconds'])
        gap = first['seconds'] - last
    adjacent_gap = max((b['seconds'] - a['seconds'] for a, b in zip(text_events, text_events[1:])), default=None)
    return {'simulated': False, 'arm': arm, 'response_id': next(iter(ids)),
            'http_requests': 1, 'failed_worker': target,
            'continuation_workers': sorted({e['worker'] for e in resumed}) if resumed else
                                    [trace['continuation_worker']] if trace else [],
            'worker_attribution': 'correlated_frontend_trace_sse_sticky' if trace else 'sse',
            'migration_trace': trace,
            'prefix_before_fault': ''.join(e['content'] for e in before),
            'content': ''.join(e['content'] for e in text_events), 'error_frames': errors,
            'read_error': result.get('read_error'), 'finish_reasons': finishes, 'done': done,
            'successful_completion': successful and done and not errors and not result.get('read_error'),
            'client_recovery_gap_seconds': gap,
            'max_client_inter_content_gap_seconds': adjacent_gap,
            'scope': ('One request, no client retries. SSE worker ID is first-write-wins; trace proves retry to peer. '
                      'Exact handoff gap unavailable. Maximum adjacent client content gap spans the whole response.'
                      if trace else 'One request, no client retries; gap spans last received old-worker content to first peer content.')}


class MigrationDemo(ui.Demo):
    """Presenter-controlled request continuity across an EngineCore crash."""
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        args = copy.copy(args)
        if args.run is None:
            args.run = ui.ROOT / 'results' / ('demo-05-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        existed = (args.run / 'demo.json').exists()
        if ui.ALLOCATION is not None and not existed:
            # The shared renderer would pin both cases to the intro's assignment.
            raise ValueError('Continuity takes ' + placement.ENV + ', not ' + ui.allocation.ENV + '; unset it.')
        super().__init__(args)
        self.compact_output = True
        if existed:
            if self.data.get('migration_profile') != PROFILE and args.action != 'cleanup':
                raise ValueError('Use a fresh continuity demo run.')
            if self.data.get('cleaned_at') and args.action in ('prepare', 'prime'):
                raise ValueError('This run was cleaned up; use a fresh run.')
            if args.action != 'cleanup':
                self.check_inputs()
                placement.resolve(self.data.get('placement'), 'request-continuity', PINNED, existing=True)
            return
        self.data.update(migration_profile=PROFILE, demo_kind='continuity', graph=GRAPH + '-disabled',
                         pod_selector='workshop-demo=continuity',
                         resource_kinds='dgd,podcliquesets,services,resourceclaims',
                         resource_note='Two prepared two-worker cases: 4 TP2 workers / 8 H100s total.',
                         log_files=['frontend.log', 'disabled.log', 'enabled.log'], cases={})
        lock = ui.read_json(ui.MODEL_LOCK)
        pins = placement.resolve(None, 'request-continuity', PINNED, existing=False)
        if pins:
            self.data['placement'] = pins
        for arm in ARMS:
            graph, claim = render(self.ns, lock, arm)
            if pins:
                worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
                placement.pin(worker['podTemplate']['spec'], claim, pins['targets'][arm])
            for obj in (graph, claim):
                obj['metadata']['labels'] = self.run.labels()
            ui.write_json(self.path / (arm + '-deployment.json'), graph)
            support.write_yaml(self.path / (arm + '-deployment.yaml'), graph)
            ui.write_json(self.path / (arm + '-claim.json'), claim)
        body = {'model': lock['model'], 'messages': [{'role': 'user', 'content':
            'Write a self-contained Python pytest module for an integer add(a, b) function. '
            'Include 12 individually named test functions, covering positive and negative values, '
            'zero, commutativity, and large integers. Each function needs its own assertion. '
            'Return Python code only, no explanations or markdown.'}],
            'stream': True, 'stream_options': {'include_usage': True}, 'max_completion_tokens': 1024,
            'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False},
            'nvext': {'extra_fields': ['worker_id', 'timing']}}
        ui.write_json(self.path / 'request.json', body)
        support.write_yaml(self.path / 'migration-settings.yaml', settings_excerpt({
            arm: ui.read_json(self.path / (arm + '-deployment.json')) for arm in ARMS}))
        names = ['request.json', 'migration-settings.yaml'] + [
            arm + suffix for arm in ARMS for suffix in ('-deployment.json', '-deployment.yaml', '-claim.json')]
        self.data['inputs'] = {name: ui.digest(self.path / name) for name in names}
        self.data['probe_sha256'] = ui.digest(PROBE)
        self.data['evidence_sha256'] = ui.digest(EVIDENCE)
        self.data['support_sha256'] = {str(p.relative_to(ui.ROOT)): ui.digest(p) for p in
                                       (Path(ui.__file__), Path(support.__file__))}
        self.data['runner_sha256'] = ui.digest(self.entrypoint)
        self.save()

    def check_inputs(self):
        for name, sha in self.data['inputs'].items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen continuity input changed: ' + name)
        if (ui.digest(PROBE) != self.data['probe_sha256'] or
                ui.digest(EVIDENCE) != self.data['evidence_sha256'] or
                ui.digest(self.entrypoint) != self.data['runner_sha256']):
            raise ValueError('Demo/probe source changed; use a fresh run.')
        for name, sha in self.data['support_sha256'].items():
            if ui.digest(source_path(name, root=ui.ROOT)) != sha:
                raise ValueError('Shared demo source changed; use a fresh run.')

    def preview(self):
        print((self.path / 'migration-settings.yaml').read_text())
        print('Two fresh matching deployments are prepared offstage (8 H100s total).')
        print('No worker pins; the serving worker is identified from live SSE metadata.')
        print('Pinned runtime keeps the initial SSE worker ID; a response-correlated frontend trace proves the retry target.')

    def pods(self, arm=None):
        selector = self.data['pod_selector'] + (',workshop-arm=' + arm if arm else '')
        return self.run.get('get', 'pods', '-n', self.ns, '-l', selector)['items']

    def prepare(self):
        self.check_inputs()
        if self.args.rehearsal:
            print('[REHEARSAL] Two prepared pairs; no model loading or cluster calls.')
        else:
            ui.acquire(self.path, OWNER)
            if not self.data['prepared']:
                from r610_feature_retests import prepare
                prepare(self.run, self.path, 'demo')
                if self.run.ns != self.ns:
                    raise ValueError('Namespace mismatch.')
                self.run.apply([ui.read_json(self.path / (arm + '-claim.json')) for arm in ARMS])
                for arm in ARMS:
                    for mode in ('client', 'server'):
                        self.kubectl('apply', '--dry-run=' + mode, '-f',
                                     str(self.path / (arm + '-deployment.json')), pause_before=False)
        self.data['prepared'] = True
        self.save()

    def prime(self):
        self.prepare()
        # Independent pairs load offstage together; only readiness observation is sequential.
        for arm in ARMS:
            case = self.data['cases'].setdefault(arm, {})
            if case.get('completed_at'):
                continue
            if (self.path / arm).exists():
                raise ValueError('Interrupted case retained; inspect its evidence and use a fresh run.')
            if not self.args.rehearsal and not case.get('applied_at'):
                case['applied_at'] = ui.now()
                self.save()
                self.run.apply([ui.read_json(self.path / (arm + '-deployment.json'))])
        for arm in ARMS:
            if not self.data['cases'].get(arm, {}).get('completed_at'):
                self.prime_case(arm)
        self.data['ready_observed_at'] = self.data.get('ready_observed_at') or ui.now()
        self.save()

    def prime_case(self, arm):
        if self.data['cases'].get(arm, {}).get('ready_at'):
            if not self.args.rehearsal:
                self.verify_case(arm)
            return
        graph = ui.read_json(self.path / (arm + '-deployment.json'))
        case = self.data['cases'].setdefault(arm, {})
        if self.args.rehearsal:
            case.update(ready_at=ui.now(), pod_uids={}, workers={}, engines={})
            self.save()
            return
        ui.acquire(self.path, OWNER)
        if not case.get('applied_at'):
            case['applied_at'] = ui.now()
            self.save()
            self.run.apply([graph])
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline:
            pods = self.pods(arm)
            support.healthy(pods)
            logs = []
            for pod in pods:
                if pod['metadata']['labels']['workshop-role'] == 'worker':
                    result = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'main',
                                        '--tail=70', '--timestamps=true', check=False)
                    logs.append(result.stdout + result.stderr)
            (self.path / (arm + '.log')).write_text('\n'.join(logs))
            if ready(pods):
                from gpu_claims import verify_allocation
                lock = ui.read_json(ui.MODEL_LOCK)
                slices, placed = None, []
                for pod in pods:
                    main = next(s for s in pod['status']['containerStatuses'] if s['name'] == 'main')
                    if main['imageID'].split('@')[-1] != lock['runtime_image'].split('@')[-1]:
                        raise ValueError('Observed image differs from lock.')
                    if pod['metadata']['labels']['workshop-role'] == 'worker':
                        claim = verify_allocation(self.run, pod, pod['spec']['containers'][0], 2)
                        if self.data.get('placement'):
                            slices = slices or self.run.get('get', 'resourceslices')
                            placed.append(placement.verify(pod, claim, slices, self.data['placement']['targets'][arm]))
                if len({p['node'] for p in placed}) != len(placed):
                    raise ValueError('Both workers of the ' + arm + ' case landed on one node.')
                if placed:
                    case['placement_observed'] = placed
                metadata = self.run.get('get', 'dynamoworkermetadatas', '-n', self.ns)['items']
                mapping = registered_workers(pods, metadata, self.ns)
                engines = {wid: self.probe(pod, 'inspect') for wid, pod in mapping.items()}
                case.update(ready_at=ui.now(), pod_uids={p['metadata']['name']: p['metadata']['uid'] for p in pods},
                            workers={wid: {'pod': p['metadata']['name'], 'uid': p['metadata']['uid']}
                                     for wid, p in mapping.items()}, engines=engines)
                ui.write_json(self.path / (arm + '-ready-pods.json'), {'items': pods})
                ui.write_json(self.path / (arm + '-worker-metadata.json'), {'items': metadata})
                self.save()
                print(arm + ': two workers and frontend Ready; EngineCore identities recorded.', flush=True)
                return
            print(arm + ': waiting for prepared workers (' + str(round(time.monotonic() - (deadline - self.args.timeout))) + 's)', flush=True)
            time.sleep(10)
        raise TimeoutError('Continuity case did not become ready: ' + arm)

    def verify_case(self, arm):
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('Continuity demo does not own the GPU lease.')
        pods = self.pods(arm)
        support.healthy(pods)
        if (not ready(pods) or {p['metadata']['name']: p['metadata']['uid'] for p in pods} !=
                self.data['cases'][arm]['pod_uids']):
            raise ValueError('Prepared Pod identities/readiness changed; use a fresh case.')
        return pods

    def probe(self, pod, action, expected=None):
        if (pod['metadata'].get('namespace') != self.ns or
                pod['metadata'].get('labels', {}).get('feature-test-run') != self.ns or
                pod['metadata']['labels'].get('workshop-demo') != 'continuity' or
                pod['metadata']['labels'].get('workshop-role') != 'worker' or
                pod['spec'].get('hostPID') or pod['spec'].get('shareProcessNamespace')):
            raise ValueError('Refusing process access outside an owned isolated worker container.')
        argv = ['exec', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--',
                'python3', '-c', PROBE.read_text(), action]
        if expected:
            argv.append(json.dumps(expected))
        result = self.run.k(*argv, timeout=35, check=False)
        lines = [line[len('RESULT_JSON='):] for line in result.stdout.splitlines() if line.startswith('RESULT_JSON=')]
        if not lines or (result.returncode and action != 'kill'):
            raise RuntimeError('Engine probe failed: ' + result.stderr[-1000:])
        value = json.loads(lines[-1])
        if action == 'kill' and not value.get('signal_sent'):
            raise RuntimeError('Signal send was not acknowledged.')
        return value

    def inject(self, arm, worker, directory):
        case = self.data['cases'][arm]
        if worker not in case['workers'] or not ui.lease_owned(self.path, OWNER):
            raise ValueError('Unknown fault target or lost GPU lease.')
        identity = case['workers'][worker]
        pod = self.run.get('get', 'pod', identity['pod'], '-n', self.ns)
        if pod['metadata']['uid'] != identity['uid']:
            raise ValueError('Fault target Pod UID changed.')
        intent = {'arm': arm, 'worker_id': worker, 'pod': identity, 'engine': case['engines'][worker],
                  'at': ui.now(), 'signal': 'SIGKILL'}
        with (directory / 'fault-intent.json').open('x') as stream:
            stream.write(json.dumps(intent, indent=2) + '\n')
        print('\n[fault] SIGKILL EngineCore on worker ' + worker + ' (' + identity['pod'] + ')', flush=True)
        return {**self.probe(pod, 'kill', case['engines'][worker]), 'worker_id': worker,
                'pod_uid': identity['uid']}

    def snapshot_evidence(self, arm, directory, label):
        pods = self.pods(arm)
        ui.write_json(directory / (label + '-pods.json'), {'items': pods})
        ui.write_json(directory / (label + '-claims.json'), self.run.get('get', 'resourceclaims', '-n', self.ns))
        for pod in pods:
            name = pod['metadata']['name']
            log = self.run.k('logs', name, '-n', self.ns, '-c', 'main', '--timestamps=true', check=False)
            (directory / (label + '-' + name + '.log')).write_text(log.stdout + log.stderr)
            if pod['metadata']['labels']['workshop-role'] == 'frontend':
                (self.path / 'frontend.log').write_text(log.stdout + log.stderr)
        return pods

    def run_case(self, arm):
        directory = self.path / arm
        if (directory / 'proof.json').exists():
            print('Showing the already completed case; no new fault is injected.')
            self.show_outcome(ui.read_json(directory / 'proof.json'))
            return
        directory.mkdir(exist_ok=False)
        if self.args.rehearsal:
            proof = {'simulated': True, 'arm': arm, 'http_requests': 1,
                     'successful_completion': arm == 'enabled', 'client_recovery_gap_seconds': None,
                     'scope': 'Illustrative sequence only; no real process fault, worker transition, or timings.'}
            print('[REHEARSAL] Partial coding response -> simulated EngineCore failure -> ' +
                  ('error frame and stream end' if arm == 'disabled' else 'peer continuation and completion'))
            ui.write_json(directory / 'proof.json', proof)
            self.data['cases'][arm]['completed_at'] = ui.now()
            self.save()
            return
        self.verify_case(arm)
        self.data['graph'] = GRAPH + '-' + arm
        self.data['active_arm'] = arm
        self.save()
        if self.forward:
            self.forward.terminate()
            self.forward.wait(timeout=10)
            self.forward = None
        self.endpoint()
        before = self.snapshot_evidence(arm, directory, 'before')
        body = ui.read_json(self.path / 'request.json')
        print('\nRequest body:\n' + json.dumps(body, indent=2))
        print('\n$ streaming POST /v1/chat/completions (one request; no client retry)', flush=True)
        self.pause()
        result = capture_stream(self.data['base_url'], body, directory,
                                lambda wid: self.inject(arm, wid, directory))
        after = self.snapshot_evidence(arm, directory, 'after')
        fault_uid = result.get('fault', {}).get('receipt', {}).get('pod_uid')
        verify_survivors(before, after, fault_uid)
        frontend = next(p['metadata']['name'] for p in before
                        if p['metadata']['labels']['workshop-role'] == 'frontend')
        proof = validate_stream(result, arm, self.data['model'], self.data['cases'][arm]['workers'],
                                frontend_log=(directory / ('after-' + frontend + '.log')).read_text())
        ui.write_json(directory / 'proof.json', proof)
        self.data['cases'][arm]['completed_at'] = ui.now()
        self.save()
        self.show_outcome(proof)

    def show_outcome(self, proof):
        print('\nObserved outcome' + (' · REHEARSAL' if proof.get('simulated') else ''))
        if proof.get('response_id'):
            print('Response: ' + proof['response_id'])
        if proof.get('continuation_workers'):
            print('Worker: ' + proof['failed_worker'] + ' -> ' + ', '.join(proof['continuation_workers']))
        for label, value in outcome_summary(proof).items():
            print(f'{label:25s} {value}')
        print('Full evidence: ' + str(Path(proof['arm']) / 'proof.json'))

    def compare(self):
        proof = {arm: ui.read_json(self.path / arm / 'proof.json') for arm in ARMS}
        value = {'simulated': self.args.rehearsal, 'cases': proof,
                 'request_sha256': ui.digest(self.path / 'request.json'),
                 'scope': 'Functional request-continuity demonstration; two prepared deployments, not an SLO benchmark.'}
        ui.write_json(self.path / 'comparison.json', value)
        print('Migration disabled: interrupted stream.\nMigration enabled: the same client response continues on its surviving peer.')
        summaries = {arm: outcome_summary(result) for arm, result in proof.items()}
        width = max(24, *(len(value) for summary in summaries.values() for value in summary.values()))
        print('\n' + f'{"Observed result":25s}' + ''.join(f'{arm:>{width}s}' for arm in summaries))
        for label in next(iter(summaries.values())):
            print(f'{label:25s}' + ''.join(f'{summary[label]:>{width}s}' for summary in summaries.values()))
        if any(result.get('worker_attribution') == 'correlated_frontend_trace_sse_sticky' for result in proof.values()):
            print('\nSSE keeps its initial worker ID; the correlated frontend trace proves the peer transition.')
            print('The maximum client content gap spans the entire response and does not isolate the handoff.')
        if any('length' in result.get('finish_reasons', []) for result in proof.values()):
            print('A length finish means the output budget was reached; it does not establish a complete Python module.')
        hashes = {str(p.relative_to(self.path)): ui.digest(p) for p in self.path.rglob('*')
                  if p.is_file() and p.name not in ('integrity.json',) and not p.name.startswith('.')}
        ui.write_json(self.path / 'integrity.json', hashes)

    def require_primed(self):
        """Onstage playback can inspect readiness, but cannot prepare or reload workers."""
        if self.args.rehearsal:
            self.data['prepared'] = True
            for arm in ARMS:
                if not self.data['cases'].get(arm, {}).get('completed_at'):
                    self.prime_case(arm)
            self.data.setdefault('ready_observed_at', ui.now())
            self.save()
            return
        if (not self.data.get('prepared') or any(
                not self.data['cases'].get(arm, {}).get('ready_at') and
                not self.data['cases'].get(arm, {}).get('completed_at') for arm in ARMS)):
            command = shlex.join(ui.presenter_command(self.entrypoint, 'prime', '--run', ui.repo_path(self.path)))
            raise RuntimeError('Prime both continuity cases offstage before opening the presentation:\n' + command)
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('Continuity demo does not own the GPU lease; inspect before presenting.')
        for arm in ARMS:
            if not self.data['cases'][arm].get('completed_at'):
                self.verify_case(arm)

    def guided(self):
        self.require_primed()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Use a terminal, or --rehearsal --plain --auto.')
        print('\nDynamo workshop · Request continuity\n' +
              ('REHEARSAL / SIMULATED / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER') +
              '\nRun: ' + ui.repo_path(self.path), flush=True)
        self.run_steps(STEPS, [lambda: self.command(['cat', self.path / 'migration-settings.yaml']),
                               lambda: self.run_case('disabled'), lambda: self.run_case('enabled'), self.compare])

    def cleanup(self, *, release_lease=True):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        if self.data.get('cleaned_at'):
            print('Already cleaned up.')
            return
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('Not the lease owner; refusing cleanup.')
        from common_runtime_tests import stop
        for arm in ARMS:
            name = GRAPH + '-' + arm
            graph = self.run.k('get', 'dgd', name, '-n', self.ns, '-o', 'json', check=False)
            if graph.returncode == 0:
                if json.loads(graph.stdout)['metadata'].get('labels', {}).get('feature-test-run') != self.ns:
                    raise ValueError('Refusing to clean an unowned DGD.')
            elif 'NotFound' not in graph.stderr:
                raise RuntimeError(graph.stderr)
        stop(self.run, [GRAPH + '-' + arm for arm in ARMS])
        for _ in range(36):
            if not self.pods() and not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
                if release_lease:
                    support.release(self.path, OWNER)
                self.data['cleaned_at'] = ui.now()
                self.save()
                print('Verified zero continuity Pods and GPU claims; lease ' +
                      ('released.' if release_lease else 'retained by caller for an owned run handoff.'))
                return
            time.sleep(5)
        raise RuntimeError('Cleanup incomplete; GPU lease retained.')


if __name__ == '__main__':
    support.launch(MigrationDemo, STEPS, 18004)
