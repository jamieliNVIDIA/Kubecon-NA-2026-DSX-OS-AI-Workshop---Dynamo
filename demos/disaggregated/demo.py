#!/usr/bin/env python3
"""Presenter-led Super VL prefill/decode serving with measured KV-transfer proof."""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import uuid

import yaml
import demos.common.placement as placement
import demos.common.runtime as ui
import demos.common.support as support
from demos.common.presentation import prose, request_text, response_text

TEMPLATE = ui.ROOT / 'configs/dgd/super-vl-tp2/nemotron-disagg-functionality.yaml'
GRAPH = 'demo-disagg'
OWNER = 'workshop-demo-disagg'
PROFILE = 'super-vl-pd-text-only-v2'
ROLES = ('frontend', 'prefill', 'decode')
PINNED = {'prefill': 1, 'decode': 1}
STEPS = [
    ('Specialize the workers', 'Prefill and decode have different resource demands; give each its own pool.'),
    ('Follow both pools', 'Follow startup of one TP2 prefill worker and one TP2 decode worker, on separate nodes.'),
    ('Send a coding request', 'The HTTP interface stays the same; request state travels between workers.'),
    ('Follow the KV handoff', 'Check distinct worker IDs and completed NIXL transfers for this request.'),
]
COUNTERS = ('vllm:nixl_bytes_transferred_sum', 'vllm:nixl_bytes_transferred_count',
            'vllm:nixl_num_failed_transfers_total', 'vllm:nixl_num_failed_notifications_total')


class _FoldedSetting(str):
    pass


class _SettingsDumper(ui._ExcerptDumper):
    pass


_SettingsDumper.add_representer(_FoldedSetting, lambda dumper, value:
    dumper.represent_scalar('tag:yaml.org,2002:str', value, style='>'))


def render(namespace, lock):
    objects = copy.deepcopy(yaml.safe_load(TEMPLATE.read_text())['items'])
    graph = next(o for o in objects if o['kind'] == 'DynamoGraphDeployment')
    graph['metadata'] = {'name': GRAPH, 'namespace': namespace}
    claims = [o for o in objects if o['kind'] == 'ResourceClaimTemplate']
    names = {}
    for claim, role in zip(claims, ('prefill', 'decode')):
        names[claim['metadata']['name']] = GRAPH + '-' + role + '-gpus'
        claim['metadata'] = {'name': names[claim['metadata']['name']], 'namespace': namespace}
    for component in graph['spec']['components']:
        role = component['type']
        pod = component['podTemplate']
        pod['metadata'] = {'labels': {'workshop-role': role, 'workshop-demo': 'disagg'}}
        spec = pod['spec']
        spec.pop('activeDeadlineSeconds', None)
        main = spec['containers'][0]
        main['image'] = lock['runtime_image']
        if role != 'frontend':
            main['args'].append('--language-model-only')
            for flag, value in (('--model', lock['model']), ('--revision', lock['revision']),
                                ('--served-model-name', lock['model'])):
                main['args'][main['args'].index(flag) + 1] = value
            for claim in spec['resourceClaims']:
                claim['resourceClaimTemplateName'] = names[claim['resourceClaimTemplateName']]
    return graph, claims


def pin_workers(graph, claims, pins):
    """Pin each pool's GPUs; the qualified prefill/decode node split stays as it is."""
    for component in graph['spec']['components']:
        role = component['type']
        if role not in PINNED:
            continue
        spec = component['podTemplate']['spec']
        node = spec['nodeSelector']['kubernetes.io/hostname']
        if pins['targets'][role][0]['node'] != node:
            raise ValueError('P/D placement keeps the qualified nodes: ' + role + ' runs on ' + node + '.')
        claim = next(c for c in claims if c['metadata']['name'] == GRAPH + '-' + role + '-gpus')
        placement.pin(spec, claim, pins['targets'][role])


def teaching_settings(graph, claims):
    """Show the effective roles, frontend flags and transfer contract."""
    gpu_counts = {claim['metadata']['name']: sum(
        request['exactly']['count'] for request in claim['spec']['spec']['devices']['requests'])
        for claim in claims}
    settings = {'components': []}
    for component in graph['spec']['components']:
        pod = component['podTemplate']['spec']
        main = pod['containers'][0]
        item = {'type': component['type'], 'replicas': component['replicas']}
        if component['type'] == 'frontend':
            item.update(command=ui._InlineList(main['command']), args=ui._InlineList(main['args']))
        else:
            args = main['args']
            item.update(
                tensor_parallel_size=int(args[args.index('--tensor-parallel-size') + 1]),
                GPUs_per_replica=sum(gpu_counts[reference['resourceClaimTemplateName']]
                                     for reference in pod['resourceClaims']),
                node=pod['nodeSelector']['kubernetes.io/hostname'],
                args={'--disaggregation-mode': args[args.index('--disaggregation-mode') + 1],
                      '--kv-transfer-config': _FoldedSetting(args[args.index('--kv-transfer-config') + 1])},
                state_layout=next(e['value'] for e in main['env']
                                  if e['name'] == 'VLLM_SSM_CONV_STATE_LAYOUT'))
        settings['components'].append(item)
    return settings


def ready(pods):
    active = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
    return (len(active) == 3 and
            all(sum(p['metadata'].get('labels', {}).get('workshop-role') == role for p in active) == 1
                for role in ROLES) and
            all(any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in p.get('status', {}).get('conditions', [])) for p in active))


def decode_stream(text, model):
    chunks = [json.loads(line[6:]) for line in text.splitlines()
              if line.startswith('data: ') and line[6:] != '[DONE]']
    if not chunks or 'data: [DONE]' not in text or any(c.get('error') for c in chunks):
        raise ValueError('Incomplete or failed streaming response.')
    if any(c.get('model') != model for c in chunks if c.get('choices')):
        raise ValueError('Unexpected model in streaming response.')
    workers = next((c['nvext']['worker_id'] for c in reversed(chunks)
                    if c.get('nvext', {}).get('worker_id')), {})
    if (workers.get('prefill_worker_id') is None or workers.get('decode_worker_id') is None or
            workers['prefill_worker_id'] == workers['decode_worker_id']):
        raise ValueError('Expected distinct prefill and decode worker IDs.')
    content = ''.join(choice.get('delta', {}).get('content') or ''
                      for c in chunks for choice in c.get('choices', []))
    usage = next((c['usage'] for c in reversed(chunks) if c.get('usage')), {})
    if not content.strip() or usage.get('completion_tokens', 0) <= 0:
        raise ValueError('No generated answer / completion usage.')
    return {'worker': workers, 'content': content, 'usage': usage, 'chunks': chunks}


def metric(record, name, filter_text=''):
    # Prefer one endpoint, rather than double-counting proxied metrics.
    for port in ('9090', '8000', '19090'):
        text = record['metrics'].get(port)
        if not isinstance(text, str):
            continue
        values = [float(line.rsplit(' ', 1)[-1]) for line in text.splitlines()
                  if (line.startswith(name + '{') or line.startswith(name + ' ')) and filter_text in line]
        if values:
            if any(not math.isfinite(v) or v < 0 for v in values):
                raise ValueError('Invalid counter value: ' + name)
            return sum(values)
    return None


def transfer_proof(before, after, response):
    if before['pod_uid'] != after['pod_uid'] or before['node'] != after['node']:
        raise ValueError('Decode Pod changed during the measurement.')
    deltas = {}
    for name in COUNTERS:
        end = metric(after, name)
        if end is None:
            raise ValueError('Missing decode metric: ' + name)
        deltas[name] = end - (metric(before, name) or 0)
    if (deltas[COUNTERS[0]] <= 0 or deltas[COUNTERS[1]] < 1 or
            deltas[COUNTERS[2]] != 0 or deltas[COUNTERS[3]] != 0):
        raise ValueError('KV handoff was not completed cleanly: ' + json.dumps(deltas))
    workers = response['worker']
    if (workers.get('prefill_worker_id') is None or workers.get('decode_worker_id') is None or
            workers['prefill_worker_id'] == workers['decode_worker_id']):
        raise ValueError('Request did not identify distinct workers.')
    return {'simulated': False, 'worker': workers, 'decode_pod_uid': after['pod_uid'],
            'metric_deltas': deltas,
            'scope': 'One controlled request on an idle owned graph; functionality, not a performance comparison.'}


class DisaggDemo(ui.Demo):
    """Split prefill and decode and verify a cross-node KV handoff."""
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        args = copy.copy(args)
        if args.run is None:
            args.run = ui.ROOT / 'results' / ('demo-03-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        existed = (args.run / 'demo.json').exists()
        super().__init__(args)
        self.compact_output = True
        if existed:
            if self.data.get('disagg_profile') != PROFILE:
                raise ValueError('Use a fresh disaggregation demo run.')
            if args.action != 'cleanup':
                self.check_inputs()
                placement.resolve(self.data.get('placement'), 'disaggregated', PINNED, existing=True)
            return
        self.data.update(disagg_profile=PROFILE, demo_kind='disagg', graph=GRAPH,
                         disagg_source_sha256=ui.digest(TEMPLATE), pod_selector='workshop-demo=disagg',
                         resource_kinds='dgd', log_files=['prefill.log', 'decode.log'],
                         resource_note='1 frontend + prefill TP2 + decode TP2 / 4 H100 GPUs')
        graph, claims = render(self.ns, ui.read_json(ui.MODEL_LOCK))
        pins = placement.resolve(None, 'disaggregated', PINNED, existing=False)
        if pins:
            pin_workers(graph, claims, pins)
            self.data['placement'] = pins
        for obj in [graph] + claims:
            obj['metadata']['labels'] = self.run.labels()
        ui.write_json(self.path / 'deployment.json', graph)
        ui.write_json(self.path / 'gpu-claims.json', {'apiVersion': 'v1', 'kind': 'List', 'items': claims})
        support.write_yaml(self.path / 'deployment.yaml', graph)
        (self.path / 'disagg-settings.yaml').write_text(yaml.dump(teaching_settings(graph, claims),
            Dumper=_SettingsDumper, sort_keys=False, width=92))
        body = ui.read_json(self.path / 'request.json')
        body['messages'][0]['content'] = (
            'Repository context:\n'
            'def subtract(a, b):\n    return a - b\n\n'
            'def multiply(a, b):\n    return a * b\n\n'
            'def divide(a, b):\n    if b == 0:\n        raise ValueError("zero divisor")\n    return a / b\n\n'
            'Add a matching short Python function add(a, b). Return code only.')
        body.update(stream=True, stream_options={'include_usage': True},
                    nvext={'extra_fields': ['worker_id', 'timing']})
        ui.write_json(self.path / 'request.json', body)
        self.data['inputs'] = {name: ui.digest(self.path / name) for name in
                               ('deployment.json', 'gpu-claims.json', 'deployment.yaml',
                                'disagg-settings.yaml', 'request.json')}
        self.save()

    def check_inputs(self):
        if self.data['disagg_source_sha256'] != ui.digest(TEMPLATE):
            raise ValueError('P/D source changed; use a fresh run.')
        for name, sha in self.data['inputs'].items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen demo input changed: ' + name)

    def preview(self):
        print((self.path / 'disagg-settings.yaml').read_text())
        print('Full manifest: ' + str(self.path / 'deployment.yaml'))
        print('Uses the qualified bounded 8k compiled P/D engine configuration, not demo 1\'s eager profile.')

    def prepare(self):
        self.check_inputs()
        if self.args.rehearsal:
            print('[REHEARSAL] Namespace, checkpoint and EFA preparation simulated.')
        else:
            ui.acquire(self.path, OWNER)
            if not self.data['prepared']:
                from r610_feature_retests import prepare
                prepare(self.run, self.path, 'demo')
                if self.run.ns != self.ns:
                    raise ValueError('Namespace mismatch.')
                self.run.apply(ui.read_json(self.path / 'gpu-claims.json')['items'])
                self.kubectl('apply', '--dry-run=client', '-f', str(self.path / 'deployment.json'), pause_before=False)
                self.kubectl('apply', '--dry-run=server', '-f', str(self.path / 'deployment.json'), pause_before=False)
        self.data['prepared'] = True
        self.save()

    def prime(self):
        self.prepare()
        self.startup()
        self.data.setdefault('primed_at', ui.now())
        self.save()
        print('Primed. Both pools stay running; the walkthrough retains their original startup timing.')

    def deploy(self):
        self.check_inputs()
        if self.data.get('apply_started_at'):
            print('Continuing the original deployment; its startup clock is retained.')
            return
        self.show_command(self.run.kbase + ['apply', '-f', str(self.path / 'deployment.json')])
        if not self.args.rehearsal:
            ui.acquire(self.path, OWNER)
            if self.run.get('get', 'dgd', '-n', self.ns)['items']:
                raise ValueError('Expected an empty demo namespace.')
        self.data['apply_started_at'] = ui.now()
        self.save()
        if self.args.rehearsal:
            print('[REHEARSAL] Prefill/decode DGD created (simulated).')
        else:
            self.run.apply([ui.read_json(self.path / 'deployment.json')])

    def startup(self):
        if self.data.get('ready_observed_at'):
            self.check_identity()
            print('Both pools are already running. Showing their recorded startup; no new startup is measured.')
            self.summary()
            return
        super().startup()

    def wait(self):
        print('Starting both pools continuously; per-worker phases update in the resource pane.')
        display = ui.StartupDisplay()
        if self.args.rehearsal:
            for stage in range(4):
                progress = {'ready': stage == 3, 'total_seconds': None, 'phases': [
                    {'name': name, 'seconds': None, 'status': 'done' if i < stage or stage == 3 else
                     'running' if i == stage else 'pending'}
                    for i, name in enumerate(('Pod startup', 'Model loading', 'Engine init', 'Readiness'))]}
                self.data['worker_startup'] = {r: progress for r in ('prefill', 'decode')}
                self.data['startup'] = progress
                self.save()
                display.update(self.display_progress(self.data['worker_startup']))
                if not self.args.auto:
                    time.sleep(1)
        else:
            if not ui.lease_owned(self.path, OWNER):
                raise RuntimeError('This P/D startup no longer owns the GPU lease; resources were retained.')
            end = time.monotonic() + self.args.timeout
            outage_started, outage_wall = None, None
            context = {**ui.startup_context(self.data), 'graph': GRAPH}
            previous = self.data.get('startup_observation', {})
            observed_uids = dict(previous.get('role_uids', {})) if previous.get('context') == context else {}
            while time.monotonic() < end:
                deadline = min(end, outage_started + ui.STARTUP_OUTAGE_BUDGET) if outage_started is not None else end
                try:
                    reader = SimpleNamespace(ns=self.ns, get=lambda *args:
                        self.startup_read(*args, deadline=deadline, json_output=True))
                    pods = reader.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']
                    initial = self.startup_roles(pods, observed_uids)
                    logs = {}
                    for role in ('prefill', 'decode'):
                        worker = initial.get(role)
                        main = next((c for c in worker.get('status', {}).get('containerStatuses', [])
                                     if c['name'] == 'main'), {}) if worker else {}
                        if 'terminated' in main.get('state', {}):
                            raise RuntimeError('A P/D worker terminated; resources and lease retained.')
                        if worker and 'running' in main.get('state', {}):
                            logs[role] = self.startup_read('logs', worker['metadata']['name'], '-n', self.ns,
                                '-c', 'main', '--timestamps=true', deadline=deadline)
                    # A fresh Pod snapshot binds both log reads to unchanged workers.
                    if logs:
                        pods = reader.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']
                        confirmed = self.startup_roles(pods, {r: p['metadata']['uid'] for r, p in initial.items()})
                    else:
                        confirmed = initial
                    if ready(pods):
                        if not all(role in logs for role in ('prefill', 'decode')):
                            raise RuntimeError('Ready P/D workers have no confirmed running logs; readiness was not accepted.')
                        self.validate_workers(pods, reader=reader)
                    progress = {}
                    for role in ('prefill', 'decode'):
                        group = copy.deepcopy([p for p in pods
                            if p['metadata']['labels']['workshop-role'] in (role, 'frontend')])
                        for p in group:
                            if p['metadata']['labels']['workshop-role'] == role:
                                p['metadata']['labels']['workshop-role'] = 'worker'
                        progress[role] = ui.startup_progress(group, logs.get(role, ''), self.data['apply_started_at'])
                except ui.StartupTransportError as error:
                    display.reset()
                    if outage_started is None:
                        outage_started, outage_wall = error.started, ui.now()
                    observation = self.data.setdefault('startup_observation', {'context': context})
                    observation.update(status='stale' if observation.get('last_successful_at') else 'disconnected',
                        error=str(error), outage_started_at=outage_wall,
                        retry_budget_seconds=ui.STARTUP_OUTAGE_BUDGET)
                    self.save()
                    print('\n' + ui.observer_note(observation), flush=True)
                    if time.monotonic() >= min(end, outage_started + ui.STARTUP_OUTAGE_BUDGET):
                        observation['retry_exhausted_at'] = ui.now()
                        self.save()
                        raise TimeoutError('P/D startup observer retry budget exhausted; current readiness unknown. '
                                           'Resources and lease retained.') from error
                    time.sleep(min(5, max(0, min(end, outage_started + ui.STARTUP_OUTAGE_BUDGET) - time.monotonic())))
                    continue
                except (RuntimeError, ValueError, KeyError, TypeError, AttributeError, IndexError, StopIteration) as error:
                    malformed = not isinstance(error, (RuntimeError, ValueError))
                    message = ('Invalid P/D startup API snapshot; resources and lease retained.'
                               if malformed else str(error))
                    self.data.setdefault('startup_observation', {'context': context}).update(
                        status='failed', error=message, failed_at=ui.now())
                    self.save()
                    if malformed:
                        raise RuntimeError(message) from error
                    raise
                if outage_started is not None:
                    print('\nObserver reconnected; fresh P/D Pod and log observations resumed.', flush=True)
                    display.reset()
                outage_started = outage_wall = None
                observed_uids = {r: p['metadata']['uid'] for r, p in confirmed.items()}
                for role, log in logs.items():
                    (self.path / (role + '.log')).write_text(log)
                self.data['worker_startup'] = progress
                self.data['startup'] = {'ready': ready(pods), 'total_seconds': max(
                    p['total_seconds'] for p in progress.values()), 'phases': []}
                self.data['startup_observation'] = {'status': 'fresh', 'context': context,
                    'last_successful_at': ui.now(), 'role_uids': observed_uids}
                self.save()
                display.update(self.display_progress(progress))
                if ready(pods):
                    ui.write_json(self.path / 'ready-pods.json', {'items': pods})
                    self.data['pod_uids'] = {p['metadata']['name']: p['metadata']['uid'] for p in pods}
                    break
                time.sleep(min(5, max(0, end - time.monotonic())))
            else:
                raise TimeoutError('P/D startup observation deadline reached; current readiness unknown. '
                                   'Resources and lease retained.')
        self.data.setdefault('ready_observed_at', ui.now())
        self.save()

    @staticmethod
    def startup_roles(pods, previous):
        support.healthy(pods)
        result = {}
        for role in ROLES:
            matches = [p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == role
                       and not p['metadata'].get('deletionTimestamp')]
            if len(matches) > 1:
                raise RuntimeError('P/D worker identity is ambiguous for ' + role + '; resources and lease retained.')
            if matches:
                result[role] = matches[0]
        for role, uid in previous.items():
            if role not in result or result[role]['metadata']['uid'] != uid:
                raise RuntimeError('P/D ' + role + ' Pod changed during startup; earlier logs cannot qualify its replacement.')
        return result

    @staticmethod
    def display_progress(workers):
        return {'total_seconds': max(p['total_seconds'] for p in workers.values()
                                    if p['total_seconds'] is not None) if any(
                                        p['total_seconds'] is not None for p in workers.values()) else None,
                'phases': [{**phase, 'name': role + ' / ' + phase['name'].strip()}
                           for role, progress in workers.items() for phase in progress['phases']]}

    def pods(self):
        return self.run.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']

    def validate_workers(self, pods, *, reader=None):
        from gpu_claims import verify_allocation
        lock = ui.read_json(ui.MODEL_LOCK)
        slices = None
        for pod in pods:
            status = next(c for c in pod['status']['containerStatuses'] if c['name'] == 'main')
            if status['imageID'].split('@')[-1] != lock['runtime_image'].split('@')[-1]:
                raise ValueError('Runtime image mismatch.')
            role = pod['metadata']['labels']['workshop-role']
            if role != 'frontend':
                claim = verify_allocation(reader or self.run, pod, pod['spec']['containers'][0], 2)
                expected = 'kubecon-nke-site-cp-' + ('0124' if role == 'prefill' else '0198')
                if pod['spec']['nodeName'] != expected:
                    raise ValueError('Unexpected worker placement.')
                if self.data.get('placement'):
                    slices = slices or (reader or self.run).get('get', 'resourceslices')
                    self.data.setdefault('placement_observed', {})[role] = placement.verify(
                        pod, claim, slices, self.data['placement']['targets'][role])

    def check_identity(self):
        if self.args.rehearsal:
            return
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('This demo no longer owns the GPU lease.')
        pods = self.pods()
        support.healthy(pods)
        if not ready(pods) or {p['metadata']['name']: p['metadata']['uid'] for p in pods} != self.data['pod_uids']:
            raise ValueError('Workers changed; earlier readiness/transfer evidence cannot qualify them.')

    def summary(self):
        result = {'simulated': self.args.rehearsal, 'apply_to_ready_seconds':
                  self.data['startup']['total_seconds'], 'workers': self.data['worker_startup'],
                  'note': 'Compiled 8k P/D profile. Concurrent worker phases overlap; do not sum them. '
                          'Checkpoint staged; image pull and scheduling remain inside apply-to-Ready.'}
        ui.write_json(self.path / 'timing.json', result)
        print('\nStartup timing' + (' · REHEARSAL / not measured' if self.args.rehearsal else ''))
        for role, progress in result['workers'].items():
            print(role + '\n' + ui.progress_lines(progress))
        print(prose(result['note']))

    def resources(self):
        if self.args.rehearsal:
            print('[REHEARSAL] 1 CPU frontend; 1 prefill TP2 on cp-0124; 1 decode TP2 on cp-0198.')
        else:
            self.kubectl('get', 'dgd,deployments,services,pods,resourceclaims', '-n', self.ns,
                         '-o', 'wide', pause_before=False)

    def read_metrics(self):
        self.check_identity()
        pod = next(p for p in self.pods() if p['metadata']['labels']['workshop-role'] == 'decode')
        code = ('import json, urllib.request\nr={}\n'
                'for port in (9090,8000,19090):\n'
                ' try:\n  r[str(port)]=urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics",timeout=5).read().decode()\n'
                ' except Exception as e: r[str(port)]={"error":str(e)}\nprint(json.dumps(r))\n')
        value = self.run.k('exec', '-i', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--',
                           'python3', '-', input_text=code)
        return {'pod_uid': pod['metadata']['uid'], 'node': pod['spec']['nodeName'], 'metrics': json.loads(value.stdout)}

    def request(self):
        self.check_identity()
        self.endpoint()
        body = ui.read_json(self.path / 'request.json')
        body['messages'][0]['content'] = 'Request ' + uuid.uuid4().hex + '. ' + body['messages'][0]['content']
        ui.write_json(self.path / 'active-request.json', body)
        print('\n' + request_text(body, filename='active-request.json'))
        args = ['curl', '--fail', '--silent', '--show-error', '--no-buffer', '--max-time', '180',
                self.data['base_url'] + '/v1/chat/completions', '-H', 'Content-Type: application/json',
                '--data-binary', '@' + str(self.path / 'active-request.json')]
        self.show_command(args)
        before = self.read_metrics() if not self.args.rehearsal else None
        if self.args.rehearsal:
            response = {'simulated': True, 'worker': {'prefill_worker_id': 'example-prefill',
                        'decode_worker_id': 'example-decode'}, 'content': 'def add(a, b):\n    return a + b',
                        'usage': {'completion_tokens': None}}
        else:
            raw = self.run.command(args, timeout=200).stdout
            (self.path / 'response.sse').write_text(raw)
            response = decode_stream(raw, self.data['model'])
        ui.write_json(self.path / 'response.json', response)
        print(response_text(response))
        if self.args.rehearsal:
            proof = {'simulated': True, 'worker': response['worker'], 'metric_deltas': None,
                     'scope': 'Illustrative response; no KV bytes or performance measured.'}
        else:
            # Metrics can trail request completion. Poll within a small bounded window.
            for attempt in range(6):
                after = self.read_metrics()
                ui.write_json(self.path / 'metrics-before.json', before)
                ui.write_json(self.path / 'metrics-after.json', after)
                try:
                    proof = transfer_proof(before, after, response)
                    break
                except ValueError:
                    if attempt == 5:
                        raise
                    time.sleep(1)
        ui.write_json(self.path / 'transfer-proof.json', proof)

    def show_transfer(self):
        self.check_identity()
        self.command(['cat', self.path / 'transfer-proof.json'])
        print('Prefill builds state; decode consumes transferred state and generates the answer.')
        print(prose('This establishes the handoff. A matched workload/GPU budget is needed to establish a speedup.'))

    def guided(self):
        self.require_prepared()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal; use --rehearsal --plain --auto offline.')
        print('\nDynamo workshop · Disaggregated serving\n' +
              ('REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER') +
              '\nRun: ' + ui.repo_path(self.path) + '\nNamespace: ' + self.ns, flush=True)
        self.run_steps(STEPS, [lambda: self.command(['cat', self.path / 'disagg-settings.yaml']),
                               self.startup, self.request, self.show_transfer])

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        if self.data.get('cleaned_at'):
            print('Already cleaned up.')
            return
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('This run does not own the GPU lease; cleanup deferred.')
        from common_runtime_tests import stop
        stop(self.run, [GRAPH])
        for _ in range(36):
            if not self.pods() and not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
                support.release(self.path, OWNER)
                self.data['cleaned_at'] = ui.now()
                self.save()
                print('Verified zero demo Pods and GPU claims. Cache/namespace retained.')
                return
            time.sleep(5)
        raise RuntimeError('Cleanup incomplete; lease retained.')


if __name__ == '__main__':
    support.launch(DisaggDemo, STEPS, 18002)
