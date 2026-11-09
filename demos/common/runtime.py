#!/usr/bin/env python3
"""Shared presenter runtime, Kubernetes lifecycle and terminal controls."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import termios
import time
import tty
from types import SimpleNamespace
import urllib.request

import yaml
import demos.common.allocation as allocation
from demos.common import weights
from demos.common.startup import (
    PATTERNS, StartupDisplay, phase_timings, progress_lines, ready_pods, startup_progress, timestamp,
)
from demos.common.selection import RUN_HELP, RunSelection
from demos.common.presentation import request_text, response_text, shell_command
from demos.registry import by_script, get_demo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = get_demo('single-replica').path
TEMPLATE = ROOT / 'configs/dgd/super-vl-tp2/nemotron-agg-functionality.yaml'
MODEL_LOCK = ROOT / 'configs/super-vl-tp2-lock.json'
LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
ALLOCATION = allocation.from_environment(ROOT)
if ALLOCATION is not None:
    LEASE = ALLOCATION.lease
# Opt-in for presenters staged side by side on disjoint GPUs: a new run records the
# named reservation, and every later action on that run uses it.
LEASE_ENV = 'WORKSHOP_LEASE'
OWNER = 'workshop-demo-single-replica'
GRAPH = 'demo-inference'
PROFILE = 'intro-mx-text-only-eager-v1'
CURRENT_RUN = ROOT / '.local/demo-01-current.json'
INTRO_RESOURCES = 'dgd,podcliquesets,deployments,services,pods,resourceclaims'
STARTUP_OBSERVER_VERSION = 'bounded-reads-v1'
STARTUP_READ_TIMEOUT = 10.0
STARTUP_OUTAGE_BUDGET = 60.0


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remember_prepared(demo):
    if demo.args.rehearsal:
        return
    run_selection().remember(demo)


def current_run():
    return run_selection().resolve()


def forget_cleaned(path):
    run_selection().forget(path)


def run_selection(demo_type=None):
    if demo_type is None:
        return RunSelection(ROOT, SCRIPT, get_demo('single-replica').command, path=CURRENT_RUN, profile=PROFILE)
    spec = by_script(demo_type.entrypoint)
    return RunSelection(ROOT, demo_type.entrypoint, spec.command, key=spec.selection_key,
                        prepared_key='mx_prepared' if spec.selector == 'modelexpress' else 'prepared')


def presenter_command(entrypoint, *arguments):
    return [sys.executable, '-m', 'demos', by_script(entrypoint).selector, *map(str, arguments)]


def kbase():
    return [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'),
            '--request-timeout=15s']


def render(namespace, lock, *, enable_mx=True):
    """Derive actual manifests from the tested DGD, without changing the source."""
    objects = copy.deepcopy(yaml.safe_load(TEMPLATE.read_text())['items'])
    graph = next(obj for obj in objects if obj['kind'] == 'DynamoGraphDeployment')
    claim = next(obj for obj in objects if obj['kind'] == 'ResourceClaimTemplate')
    claim['metadata'] = {'name': GRAPH + '-gpus', 'namespace': namespace}
    graph['metadata'] = {'name': GRAPH, 'namespace': namespace}
    for component in graph['spec']['components']:
        component['replicas'] = 1
        pod = component['podTemplate']
        worker = component['type'] == 'worker'
        pod['metadata'] = {'labels': {'workshop-role': 'worker' if worker else 'frontend'}}
        spec = pod['spec']
        # A graph can replace an expired Pod: cleanup explicitly deletes the DGD.
        spec.pop('activeDeadlineSeconds', None)
        component.pop('sharedMemorySize', None)  # The explicit /dev/shm volume is sufficient.
        container = spec['containers'][0]
        container['image'] = lock['runtime_image']
        container.pop('imagePullPolicy', None)
        container.pop('workingDir', None)
        container['env'] = [e for e in container['env'] if e['name'] in {
            'HF_HOME', 'HF_HUB_OFFLINE', 'HF_MODULES_CACHE',
            'NVIDIA_VISIBLE_DEVICES', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT',
        }]
        if worker:
            spec['affinity'].pop('podAntiAffinity', None)
            spec['resourceClaims'][0]['resourceClaimTemplateName'] = claim['metadata']['name']
            # Keep model identity, required parallelism, and bounded H100 memory use.
            # Leave batching, prefix-cache, cache-dtype and kernel selection at defaults.
            container['args'] = [
                '--model', lock['model'], '--revision', lock['revision'], '--trust-remote-code',
                '--tensor-parallel-size', str(lock['tensor_parallel_size']),
                '--max-num-seqs', '4', '--gpu-memory-utilization', '0.85',
                '--limit-mm-per-prompt', '{"image":1,"video":0}',
                '--reasoning-parser', 'nemotron_v3', '--enforce-eager', '--language-model-only',
            ]
        else:
            container['args'] = ['--router-mode', 'round-robin', '--trust-remote-code']
            container['volumeMounts'] = [v for v in container['volumeMounts'] if v['name'] != 'dshm']
            spec['volumes'] = [v for v in spec['volumes'] if v['name'] != 'dshm']
    if enable_mx:
        for component in graph['spec']['components']:
            component['podTemplate']['metadata']['labels']['workshop-demo'] = 'single-replica'
        weights.configure(graph, lock, role='source')
    if ALLOCATION is not None:
        ALLOCATION.pin(graph, claim, 'intro')
    return graph, claim


class _InlineList(list):
    """Keep short argv and claim references legible in the projected excerpt."""


class _InlineMap(dict):
    pass


class _ExcerptDumper(yaml.SafeDumper):
    pass


_ExcerptDumper.add_representer(_InlineList, lambda d, v: d.represent_sequence(
    'tag:yaml.org,2002:seq', v, flow_style=True))
_ExcerptDumper.add_representer(_InlineMap, lambda d, v: d.represent_mapping(
    'tag:yaml.org,2002:map', v, flow_style=True))


def deployment_excerpt(graph, claim):
    """Project actual fields at their real schema paths; never use this to apply."""
    components = []
    for component in graph['spec']['components']:
        brief = {key: component[key] for key in ('name', 'type', 'replicas')}
        if component['type'] == 'frontend':
            main = component['podTemplate']['spec']['containers'][0]
            brief['podTemplate'] = {'spec': {'containers': [{
                'command': _InlineList(main['command']), 'args': _InlineList(main['args'])}]}}
        if component['type'] == 'worker':
            pod = component['podTemplate']['spec']
            main = pod['containers'][0]
            args = []
            for flag in ('--model', '--tensor-parallel-size'):
                index = main['args'].index(flag)
                args.extend(main['args'][index:index + 2])
            brief['podTemplate'] = {'spec': {
                'containers': [{'command': _InlineList(main['command']), 'args': args,
                    'resources': {'claims': _InlineList(_InlineMap(c) for c in main['resources']['claims'])}}],
                'resourceClaims': copy.deepcopy(pod['resourceClaims'])}}
        components.append(brief)
    requests = [{'name': item['name'], 'exactly': _InlineMap({key: item['exactly'][key]
                 for key in ('deviceClassName', 'count')})}
                for item in claim['spec']['spec']['devices']['requests']]
    dump = lambda obj: yaml.dump(obj, Dumper=_ExcerptDumper, sort_keys=False, width=96)
    return ('# deployment.yaml excerpt; image pins, storage and setup omitted.\n' +
            dump({'kind': graph['kind'], 'spec': {'components': components}}) +
            '\n---\n# gpu-claim-template.yaml excerpt\n' +
            dump({'kind': claim['kind'], 'metadata': _InlineMap({'name': claim['metadata']['name']}),
                  'spec': {'spec': {'devices': {'requests': requests}}}}))


def compact_resource_table(items, *, pods_only=False):
    """Summarize actual operator resources without generated names/IP columns."""
    aliases = {}
    for item in items:
        labels = item.get('metadata', {}).get('labels', {})
        role = labels.get('workshop-role') or labels.get('nvidia.com/dynamo-component-type')
        if item['kind'] == 'Pod' and role and labels.get('nvidia.com/dynamo-component'):
            aliases[labels['nvidia.com/dynamo-component']] = role

    def component(item):
        labels = item.get('metadata', {}).get('labels', {})
        role = labels.get('workshop-role') or labels.get('nvidia.com/dynamo-component-type')
        role = role or aliases.get(labels.get('nvidia.com/dynamo-component'),
                                   labels.get('nvidia.com/dynamo-component'))
        return role or '—'

    pods = {p['metadata']['uid']: component(p) for p in items if p['kind'] == 'Pod'
            and p['metadata'].get('uid')}
    rows = []
    for item in items:
        kind, status = item['kind'], item.get('status', {})
        role = component(item)
        if pods_only and kind not in ('DynamoGraphDeployment', 'Pod'):
            continue
        if kind == 'DynamoGraphDeployment':
            role = item['metadata']['name']
            ready = next((c for c in status.get('conditions', []) if c['type'] == 'Ready'), {})
            detail = 'Ready' if ready.get('status') == 'True' else ready.get('reason', 'Starting')
            kind = 'DGD'
        elif kind == 'Deployment':
            detail = f'{status.get("readyReplicas", 0)}/{item["spec"].get("replicas", 1)} ready'
        elif kind == 'PodCliqueSet':
            role = item['metadata']['name']
            detail = f'{status.get("availableReplicas", 0)}/{item["spec"].get("replicas", 1)} available'
        elif kind == 'Pod':
            if role == '—':  # Offstage cache/auth probes are not serving components.
                continue
            ready = sum(bool(c.get('ready')) for c in status.get('containerStatuses', []))
            total = len(item['spec']['containers'])
            detail = f'{ready}/{total} {status.get("phase", "Pending")}'
        elif kind == 'Service':
            detail = ', '.join(str(p['port']) + '/' + p.get('protocol', 'TCP')
                               for p in item['spec'].get('ports', []))
            if item['spec'].get('clusterIP') == 'None':
                role = 'discovery' if role == '—' else role
                detail = 'Headless DNS' + (': ' + detail if detail else '')
            elif role == 'frontend':
                detail += ' HTTP'
            elif role == 'worker':
                detail += ' system'
        elif kind == 'ResourceClaim':
            devices = status.get('allocation', {}).get('devices', {}).get('results', [])
            count = sum(d.get('driver') == 'gpu.nvidia.com' for d in devices)
            detail = f'{count} GPUs allocated' if count else 'Pending'
            references = item['metadata'].get('ownerReferences', []) + status.get('reservedFor', [])
            role = next((pods[r['uid']] for r in references if r.get('uid') in pods), role)
            kind = 'GPU claim'
        else:
            continue
        rows.append((kind, role, detail))
    if not rows:
        return 'Waiting for operator resources.'
    order = {'DGD': 0, 'PodCliqueSet': 1, 'Deployment': 1, 'Service': 2, 'Pod': 3, 'GPU claim': 4}
    rows.sort(key=lambda row: (order[row[0]], row[1]))
    widths = [max(len(row[i]) for row in [('KIND', 'COMPONENT', 'STATUS')] + rows) for i in (0, 1)]
    return '\n'.join(f'{kind:<{widths[0]}}  {role:<{widths[1]}}  {status}'
                     for kind, role, status in [('KIND', 'COMPONENT', 'STATUS')] + rows)


def rehearsal_resource_table(data):
    state = ('Ready' if data.get('ready_observed_at') else
             'Starting' if data.get('apply_started_at') else 'Not deployed')
    return ('KIND          COMPONENT       STATUS\n'
            f'DGD           {GRAPH:15s} {state}\n'
            f'PodCliqueSet  {GRAPH:15s} {state}\n'
            'Service       discovery       Headless DNS\n'
            'Service       frontend        8000/TCP HTTP\n'
            'Service       worker          9090/TCP system\n'
            f'Pod           frontend        {state} (CPU)\n'
            f'Pod           worker          {state} (2 GPUs)\n'
            f'GPU claim     worker          {"2 GPUs allocated" if data.get("apply_started_at") else "Not allocated"}')


def repo_path(path):
    """Short paths for instructions explicitly run from the repository root."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def transport_failure(result):
    """Retry read-only transport failures, never authorization or API mistakes."""
    if not result.returncode:
        return False
    text = (result.stderr + '\n' + result.stdout).lower()
    if any(marker in text for marker in ('forbidden', 'unauthorized', 'notfound', 'not found',
                                         'badrequest', 'bad request', 'x509', 'certificate')):
        return False
    return result.returncode == 124 or any(marker in text for marker in (
        'unable to connect to the server', 'tls handshake timeout', 'context deadline exceeded',
        'client.timeout', 'i/o timeout', 'connection refused', 'connection reset',
        'connection timed out', 'unexpected eof', 'no route to host',
        'serviceunavailable', 'service unavailable', 'server is currently unable'))


class StartupTransportError(RuntimeError):
    def __init__(self, message, started):
        super().__init__(message)
        self.started = started


def observer_note(observation):
    if not observation or observation.get('status') == 'fresh':
        return ''
    last = observation.get('last_successful_at') or 'none yet'
    prefix = 'Observer read failed.' if observation.get('status') == 'failed' else 'Observer disconnected.'
    return (prefix + ' Last successful read: ' + last +
            '. Saved phases/logs are stale; current readiness is unknown.')


def startup_context(data):
    return {'apply_started_at': data.get('apply_started_at'), 'arm': data.get('active_arm', 'intro')}


def cached_startup_log(path, data, worker_uid=None):
    """Read only a hash-verified log belonging to the currently observed Pod UID."""
    observation = data.get('startup_observation', {})
    uid = observation.get('worker_uid')
    if (observation.get('context') != startup_context(data) or
            not uid or (worker_uid is not None and uid != worker_uid) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,127}', uid)):
        return None
    relative = Path('startup-observations') / (uid + '.log')
    if observation.get('log_file') != str(relative):
        return None
    source = Path(path) / relative
    try:
        source.resolve().relative_to(Path(path).resolve())
        if digest(source) != observation.get('log_sha256'):
            return None
        return source.read_text()
    except (OSError, ValueError):
        return None


def startup_display_progress(path, data):
    """Reparse verified completed evidence for display without rewriting the run."""
    saved = data.get('startup')
    observation = data.get('startup_observation', {})
    if (data.get('rehearsal') or not data.get('ready_observed_at') or
            not data.get('apply_started_at') or observation.get('status') != 'fresh'):
        return saved
    try:
        pods = read_json(Path(path) / 'ready-pods.json')['items']
        if not ready_pods(pods):
            return saved
        worker = next(p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'worker')
        uid = worker['metadata']['uid']
        if any(c.get('restartCount', 0) for p in pods
               for c in p.get('status', {}).get('containerStatuses', [])):
            return saved
        logs = cached_startup_log(path, data, uid)
        if logs is None or digest(Path(path) / 'worker.log') != observation.get('log_sha256'):
            return saved
        return startup_progress(pods, logs, data['apply_started_at'], data['ready_observed_at'])
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return saved


def lease_owned(path, owner=OWNER):
    return (LEASE.exists() and read_json(LEASE / 'owner.json').get('agent') == owner
            and read_json(LEASE / 'owner.json').get('run') == str(Path(path).resolve()))


def lease_conflict(owner, message):
    """Describe the reservation and point only known owners at their own cleanup."""
    message += ' owned by ' + str(owner.get('agent')) + ':\n' + str(owner.get('run'))
    selector = {
        OWNER: 'single-replica',
        'workshop-demo-modelexpress': 'modelexpress',
        'workshop-demo-disagg': 'disaggregated',
        'workshop-demo-snapshot': 'snapshot',
        'workshop-demo-continuity': 'request-continuity',
        'workshop-demo-kvcr': 'kvcr',
        'workshop-demo-shadow': 'shadow',
    }.get(owner.get('agent'))
    run = owner.get('run')
    if selector and isinstance(run, str) and run:
        command = presenter_command(get_demo(selector).path, 'cleanup', '--run', repo_path(run))
        frozen_allocation = Path(run) / 'allocation.json'
        if frozen_allocation.is_file():
            command = ['env', allocation.ENV + '=' + repo_path(frozen_allocation)] + command
        message += '\nWhen that run is finished, release its reservation with:\n' + shlex.join(command)
    else:
        message += '\nInspect the reservation owner before continuing; no cleanup command is inferred.'
    return message


def named_lease(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}\.gpu-lease', name):
        raise ValueError(LEASE_ENV + ' must name a .local/<name>.gpu-lease directory, such as workshop-disagg.gpu-lease.')
    return ROOT / '.local' / name


def use_lease(name):
    """Point this process's reservation at a run's recorded named lease."""
    global LEASE
    LEASE = named_lease(name)


def requested_lease():
    """Validate a requested named lease before any run directory is created."""
    requested = os.environ.get(LEASE_ENV)
    if requested:
        named_lease(requested)
        if ALLOCATION is not None:
            raise ValueError('Set ' + allocation.ENV + ' or ' + LEASE_ENV + ', not both; an allocation names its own lease.')
    return requested


def record_lease(data, requested, *, existing):
    """A new run records the requested lease and an existing run keeps its own; either way, use it."""
    if existing:
        if requested and data.get('lease') != '.local/' + requested:
            raise ValueError('This run ' + ('reserves ' + data['lease'] if data.get('lease') else
                             'uses the shared reservation') + '; unset ' + LEASE_ENV + ' to resume it.')
    elif requested:
        data['lease'] = '.local/' + requested
    if data.get('lease'):
        use_lease(Path(data['lease']).name)


def acquire(path, owner=OWNER):
    try:
        LEASE.mkdir()
    except FileExistsError:
        if lease_owned(path, owner):
            return
        raise RuntimeError(lease_conflict(read_json(LEASE / 'owner.json'),
                                         'GPUs are reserved by another workshop run'))
    write_json(LEASE / 'owner.json', {'agent': owner, 'run': str(Path(path).resolve()), 'acquired_at': now()})


@contextlib.contextmanager
def presenter_lock(path):
    with (Path(path) / '.presenter.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This run already has an active presenter. Stop it before resuming or cleaning up.')
        yield


class Demo:
    entrypoint = SCRIPT
    steps = ()
    compact_output = False  # Subclasses with independent initialization keep their current view.

    def __init__(self, args):
        from testlib import Run
        self.args = args
        path = args.run or ROOT / 'results' / ('demo-01-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        if args.action == 'cleanup' and (not args.run or not (Path(path) / 'demo.json').is_file()):
            raise ValueError('Cleanup requires an existing demo run with demo.json: ' + str(path) +
                             '\nCheck the exact --run path; no run was created.')
        requested = requested_lease()
        self.run = Run(path)
        self.path = self.run.path
        self.file = self.path / 'demo.json'
        allocation.freeze(ALLOCATION, self.path, existing=self.file.exists())
        if self.file.exists():
            self.data = read_json(self.file)
            record_lease(self.data, requested, existing=True)
            if args.rehearsal != self.data['rehearsal']:
                raise ValueError('Use the same --rehearsal setting for an existing run.')
            if self.data.get('profile') != PROFILE and args.action != 'cleanup':
                raise ValueError('The demo profile changed. Use a fresh run; the old run can still be cleaned up.')
            if self.data['source_sha256'] != digest(TEMPLATE) or self.data['lock_sha256'] != digest(MODEL_LOCK):
                raise ValueError('Source manifest or model lock changed; create a fresh demo run.')
        else:
            namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(self.path).encode()).hexdigest()[:8] + '-demo'
            self.run.ns = namespace
            self.run.state['namespace'] = namespace
            self.run.save()
            self.data = {'schema': 2, 'profile': PROFILE, 'rehearsal': args.rehearsal, 'namespace': namespace,
                         'created_at': now(), 'source_sha256': digest(TEMPLATE),
                         'lock_sha256': digest(MODEL_LOCK), 'model': read_json(MODEL_LOCK)['model'],
                         'step': 0, 'prepared': False}
            record_lease(self.data, requested, existing=False)
            graph, claim = render(namespace, read_json(MODEL_LOCK), enable_mx=self.entrypoint == SCRIPT)
            for filename, obj in [('deployment.yaml', graph), ('gpu-claim-template.yaml', claim)]:
                obj['metadata']['labels'] = self.run.labels()
                (self.path / filename).write_text(yaml.safe_dump(obj, sort_keys=False))
            self.data['manifest_sha256'] = digest(self.path / 'deployment.yaml')
            self.data['claim_sha256'] = digest(self.path / 'gpu-claim-template.yaml')
            if self.entrypoint == SCRIPT:
                self.data['pod_selector'] = 'workshop-demo=single-replica'
                service = weights.source_service(namespace, read_json(MODEL_LOCK), self.run.labels())
                (self.path / 'source-service.yaml').write_text(yaml.safe_dump(service, sort_keys=False))
                self.data['mx_source_service_sha256'] = digest(self.path / 'source-service.yaml')
            write_json(self.path / 'request.json', {
                'model': self.data['model'], 'messages': [{'role': 'user', 'content':
                    'Write a short Python function add(a, b) that returns their sum. Reply with code only.'}],
                'max_completion_tokens': 64, 'temperature': 0,
                'chat_template_kwargs': {'enable_thinking': False}})
            self.save()
        self.ns = self.data['namespace']
        self.compact_output = self.entrypoint == SCRIPT
        self.forward = None
        if self.data.get('cleaned_at') and args.action in ('run', 'prepare', 'prime') and not args.preview:
            raise ValueError('This deployment was cleaned up. Use a fresh run for a new startup.')

    def save(self):
        write_json(self.file, self.data)

    def command_text(self, args):
        values = list(map(str, args))
        if self.compact_output:
            base = self.run.kbase
            if values[:len(base)] == base:
                values = ['kubectl'] + values[len(base):]
            for index, value in enumerate(values):
                prefix = '@' if value.startswith('@') else ''
                try:
                    relative = Path(value[len(prefix):]).relative_to(self.path)
                except ValueError:
                    continue
                values[index] = prefix + str(relative)
        return shell_command(values)

    def show_command(self, args):
        print('\n$ ' + self.command_text(args), flush=True)
        self.pause()

    def command(self, args, *, pause_before=True, **kwargs):
        if pause_before:
            self.show_command(args)
        else:
            print('\n$ ' + self.command_text(args), flush=True)
        result = self.run.command(list(map(str, args)), **kwargs)
        print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
        if result.stderr:
            print(result.stderr, end='' if result.stderr.endswith('\n') else '\n', flush=True)
        return result

    def kubectl(self, *args, **kwargs):
        return self.command(self.run.kbase + list(args), **kwargs)

    def write_excerpt(self):
        self.check_manifests()
        text = deployment_excerpt(yaml.safe_load((self.path / 'deployment.yaml').read_text()),
                                  yaml.safe_load((self.path / 'gpu-claim-template.yaml').read_text()))
        path = self.path / 'deployment-excerpt.yaml'
        path.write_text(text)
        return path

    def deployment(self):
        self.command(['cat', self.write_excerpt()])
        print('\nFull executable files: deployment.yaml + gpu-claim-template.yaml')

    def pause(self):
        if self.args.auto:
            return
        previous = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno(), termios.TCSANOW)
            self.data['awaiting_key'] = True
            self.save()
            while True:
                key = sys.stdin.read(1)
                if key in ('q', 'Q', '\x03', ''):
                    raise KeyboardInterrupt
                if key in ('\r', '\n', ' '):
                    break
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, previous)
            self.data['awaiting_key'] = False
            self.save()

    def check_manifests(self):
        if digest(self.path / 'deployment.yaml') != self.data['manifest_sha256']:
            raise ValueError('Rendered deployment changed; create a fresh run to record new settings.')
        if not self.data.get('claim_sha256'):
            raise ValueError('This older run has no frozen GPU claim hash; use its original runner or a fresh run.')
        if digest(self.path / 'gpu-claim-template.yaml') != self.data['claim_sha256']:
            raise ValueError('Rendered GPU claim changed; do not apply it or resume this startup.')
        if self.data.get('mx_source_service_sha256') and (
                digest(self.path / 'source-service.yaml') != self.data['mx_source_service_sha256']):
            raise ValueError('Rendered ModelExpress source service changed; use a fresh run.')

    def prepare(self):
        self.check_manifests()
        if self.data['prepared']:
            if not self.args.rehearsal:
                self.kubectl('get', 'namespace', self.ns, pause_before=False)
                self.kubectl('get', 'pvc', 'feature-cache', '-n', self.ns, pause_before=False)
            print('Preparation is complete. The checkpoint is staged; no external model download is timed.')
            return
        if self.args.rehearsal:
            print('[REHEARSAL] Simulated namespace, model-cache and image-pull preparation; no cluster commands.')
        else:
            if LEASE.exists():
                owner = read_json(LEASE / 'owner.json')
                raise RuntimeError(lease_conflict(owner, 'Preparation blocked by the measurement lease'))
            from r610_feature_retests import prepare
            print('Reusing feature-test preparation: fresh namespace, private PVC, registry secret, exact checkpoint checks.')
            prepare(self.run, self.path, 'demo')
            if self.run.ns != self.data['namespace']:
                raise ValueError('Prepared namespace differs from the rendered manifest.')
            prerequisites = [yaml.safe_load((self.path / 'gpu-claim-template.yaml').read_text())]
            if self.data.get('mx_source_service_sha256'):
                prerequisites.append(yaml.safe_load((self.path / 'source-service.yaml').read_text()))
            self.run.apply(prerequisites)
            self.kubectl('apply', '--dry-run=client', '-f', str(self.path / 'deployment.yaml'), pause_before=False)
            self.kubectl('apply', '--dry-run=server', '-f', str(self.path / 'deployment.yaml'), pause_before=False)
        self.data['prepared'] = True
        self.save()

    def deploy(self):
        self.check_manifests()
        if self.data.get('apply_started_at'):
            print('Continuing this deployment; preserving its original startup timestamp.')
            return
        if digest(self.path / 'deployment.yaml') != self.data['manifest_sha256']:
            raise ValueError('Rendered deployment changed; create a fresh run to record new settings.')
        command = self.run.kbase + ['apply', '-f', str(self.path / 'deployment.yaml')]
        self.show_command(command)
        if self.args.rehearsal:
            print('[REHEARSAL] dynamographdeployment.nvidia.com/demo-inference created (simulated)')
        else:
            acquire(self.path)
            if self.run.get('get', 'dgd', '-n', self.ns)['items']:
                raise ValueError('Demo namespace already has a graph; inspect it before deploying.')
        self.data['apply_started_at'] = now()
        self.save()
        if not self.args.rehearsal:
            self.run.apply([yaml.safe_load((self.path / 'deployment.yaml').read_text())])

    def resources(self):
        if self.args.rehearsal:
            print('[REHEARSAL] Example operator-created resources (simulated):')
            if self.compact_output:
                print(rehearsal_resource_table(self.data))
            else:
                print('DGD demo-inference\n  Service demo-inference-frontend :8000\n'
                      '  Frontend Pod: CPU\n  vLLM worker Pod: 2 GPUs, tensor parallelism 2')
        elif self.compact_output:
            args = self.run.kbase + ['get', INTRO_RESOURCES,
                                     '-n', self.ns, '-o', 'json']
            print('\n$ ' + self.command_text(args), flush=True)
            result = self.run.command(args)
            objects = json.loads(result.stdout)
            write_json(self.path / 'resources.json', objects)
            if result.stderr:
                print(result.stderr, end='' if result.stderr.endswith('\n') else '\n', flush=True)
            print('Resource summary:')
            print(compact_resource_table(objects['items']))
        else:
            self.kubectl('get', 'dgd,deployments,services,pods,resourceclaims', '-n', self.ns, '-o', 'wide',
                         pause_before=False)

    def startup(self):
        self.deploy()
        if (self.entrypoint == SCRIPT and not self.args.rehearsal and
                self.data.get('ready_observed_at')):
            self.replay_completed_startup()
            return
        self.wait()
        self.resources()
        self.summary()

    def replay_completed_startup(self):
        """Revalidate the retained replica, then display its original startup."""
        self.check_manifests()
        if not lease_owned(self.path):
            raise RuntimeError('The retained first replica no longer owns its GPU reservation.')
        evidence = ('ready-pods.json', 'worker.log', 'timing.json')
        hashes = {name: digest(self.path / name) for name in evidence}
        saved = read_json(self.path / 'ready-pods.json')['items']
        timing = read_json(self.path / 'timing.json')
        if (len(saved) != 2 or not ready_pods(saved) or timing.get('rehearsal') or
                not timing.get('startup_phases', {}).get('ready')):
            raise RuntimeError('The retained first replica has no completed startup evidence; inspect its run.')
        deadline = time.monotonic() + min(self.args.timeout, STARTUP_READ_TIMEOUT * 4)

        def get(*args):
            return self.startup_read(*args, deadline=deadline, json_output=True)

        current = get('get', 'pods', '-n', self.ns, '-l', self.data.get('pod_selector', 'workshop-role'))['items']
        if len(current) != 2 or not ready_pods(current):
            raise RuntimeError('The retained first replica is no longer Ready; prior startup evidence was preserved.')
        pinned = read_json(MODEL_LOCK)['runtime_image']
        roles = {}
        for role in ('worker', 'frontend'):
            recorded = next(p for p in saved if p['metadata']['labels']['workshop-role'] == role)
            live = next(p for p in current if p['metadata']['labels']['workshop-role'] == role)
            if (live['metadata'].get('deletionTimestamp') or
                    live['metadata']['uid'] != recorded['metadata']['uid'] or
                    live['metadata']['name'] != recorded['metadata']['name'] or
                    live['spec'].get('nodeName') != recorded['spec'].get('nodeName')):
                raise RuntimeError('The retained ' + role + ' was replaced or moved; prior startup evidence was preserved.')
            for pod in (recorded, live):
                statuses = {c['name']: c for c in pod.get('status', {}).get('containerStatuses', [])}
                for container in pod['spec']['containers']:
                    status = statuses.get(container['name'], {})
                    if status.get('restartCount', 0) or 'running' not in status.get('state', {}):
                        raise RuntimeError('The retained ' + role + ' restarted or stopped; prior startup evidence was preserved.')
                    if (container.get('image') != pinned or
                            status.get('imageID', '').split('@')[-1] != pinned.split('@')[-1]):
                        raise RuntimeError('The retained ' + role + ' differs from the pinned runtime image.')
            roles[role] = (recorded, live)
        recorded, worker = roles['worker']
        expected = recorded['spec']['containers'][0].get('resources', {}).get('claims', [])
        actual = worker['spec']['containers'][0].get('resources', {}).get('claims', [])
        if (len(expected) != 1 or actual != expected or
                worker['spec'].get('resourceClaims') != recorded['spec'].get('resourceClaims')):
            raise RuntimeError('The retained first replica GPU claim binding changed.')
        reference = expected[0]['name']

        def claims(pod):
            return [c['resourceClaimName'] for c in pod['status'].get('resourceClaimStatuses', [])
                    if c['name'] == reference]

        names = claims(worker)
        if len(names) != 1 or names != claims(recorded):
            raise RuntimeError('The retained first replica GPU claim reference changed.')
        claim = get('get', 'resourceclaim', names[0], '-n', self.ns)
        if (claim['metadata'].get('deletionTimestamp') or not any(
                owner.get('kind') == 'Pod' and owner.get('uid') == worker['metadata']['uid']
                for owner in claim['metadata'].get('ownerReferences', [])) or any(
                consumer.get('uid') != worker['metadata']['uid']
                for consumer in claim.get('status', {}).get('reservedFor', []))):
            raise RuntimeError('The retained first replica GPU claim is not owned by its worker.')
        slices = get('get', 'resourceslices')
        physical = allocation.physical_gpus(worker, claim, slices)
        if len(physical) != 2:
            raise RuntimeError('The retained first replica no longer has two distinct NVIDIA GPUs.')
        if ALLOCATION is not None:
            proof = ALLOCATION.verify(worker, claim, slices, 'intro')
            if read_json(self.path / 'allocated-gpus.json') != proof:
                raise RuntimeError('The retained first replica physical GPU identity changed.')
        if hashes != {name: digest(self.path / name) for name in evidence}:
            raise RuntimeError('The retained startup evidence changed during revalidation; inspect before continuing.')
        progress = startup_display_progress(self.path, self.data)
        if not progress or not progress.get('ready'):
            progress = timing['startup_phases']
        print('\nRetained startup timing · same Ready replica; no new measurement.')
        StartupDisplay().update(progress)
        seconds = timing.get('observed_seconds_since_apply', {}).get('worker_and_frontend_ready')
        print('  Ready first observed: ' + (f'{seconds:.1f}s since apply' if seconds is not None else 'not measured'))

    def startup_read(self, *args, deadline, json_output=False):
        """One bounded read; callers decide whether a transport failure is retriable."""
        started = time.monotonic()
        remaining = min(STARTUP_READ_TIMEOUT, deadline - started)
        if remaining <= 0:
            raise StartupTransportError('Startup observation deadline reached.', started)
        arguments = list(args) + (['-o', 'json'] if json_output else [])
        result = self.run.k(*arguments, '--request-timeout=' + f'{remaining:.3f}s',
                            timeout=remaining, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout or 'Read timed out.').strip()[-1200:]
            message = 'Startup read failed (' + ' '.join(map(str, args[:2])) + '): ' + detail
            if transport_failure(result):
                raise StartupTransportError(message, started)
            raise RuntimeError(message + '\nResources and lease retained; inspect before continuing.')
        if not json_output:
            return result.stdout
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError('Expected an API object.')
            return value
        except (ValueError, TypeError) as error:
            raise RuntimeError('Invalid startup API response; resources and lease retained.') from error

    def save_startup_observation(self, worker, logs, context):
        observation = {'version': STARTUP_OBSERVER_VERSION, 'status': 'fresh', 'context': context,
                       'last_successful_at': now(), 'worker_uid': None, 'last_log_at': None}
        if worker:
            uid = worker['metadata']['uid']
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,127}', uid):
                raise ValueError('Invalid observed worker UID; refusing log-cache path.')
            relative = Path('startup-observations') / (uid + '.log')
            destination = self.path / relative
            destination.parent.mkdir(exist_ok=True)
            temporary = destination.with_suffix(f'.{os.getpid()}.tmp')
            temporary.write_text(logs)
            temporary.replace(destination)
            stamps = [line.split()[0] for line in logs.splitlines() if re.match(r'^\d{4}-\d\d-\d\dT', line)]
            observation.update(worker_uid=uid, log_file=str(relative), log_sha256=digest(destination),
                               last_log_at=stamps[-1] if stamps else None)
            self.data.setdefault('startup_log_observations', {})[uid] = copy.deepcopy(observation)
        self.data['startup_observation'] = observation

    def wait(self):
        print('Starting the service. Running phase times refresh with each observation.')
        display = StartupDisplay()
        if self.args.rehearsal:
            names = ('Pod startup', 'Runtime setup', 'Worker / TP setup', 'Model setup',
                     'Weight loading', 'Weight finalizing', 'Engine init', '  Warmup window', 'Readiness')
            for active in range(len(names)):
                progress = {'ready': active == len(names) - 1, 'total_seconds': None, 'phases': [
                    {'name': name, 'status': 'done' if index < active or active == len(names) - 1 else
                     'running' if index == active else 'pending', 'seconds': None}
                    for index, name in enumerate(names)]}
                self.data['startup'] = progress
                self.save()
                display.update(progress)
                if not self.args.auto:
                    time.sleep(1.5)
            print('[REHEARSAL] Startup complete; no real timing measurements.')
        else:
            end = time.monotonic() + self.args.timeout
            outage_started = None
            outage_wall = None
            context = startup_context(self.data)
            previous = self.data.get('startup_observation', {})
            if previous.get('context') != context:
                self.data.pop('startup_observation', None)
                self.data.pop('startup', None)
            observed_uid = self.data.get('startup_observation', {}).get('worker_uid')
            while time.monotonic() < end:
                deadline = min(end, outage_started + STARTUP_OUTAGE_BUDGET) if outage_started is not None else end
                if time.monotonic() >= deadline:
                    self.data.setdefault('startup_observation', {})['retry_exhausted_at'] = now()
                    self.save()
                    raise TimeoutError('Startup observer transport retry budget exhausted; '
                                       'current readiness unknown. Resources and lease retained.')
                try:
                    def get(*args):
                        return self.startup_read(*args, deadline=deadline, json_output=True)

                    pods = get('get', 'pods', '-n', self.ns, '-l',
                               self.data.get('pod_selector', 'workshop-role'))['items']
                    worker = next((p for p in pods if p['metadata']['labels']['workshop-role'] == 'worker'
                                   and not p['metadata'].get('deletionTimestamp')), None)
                    uid = worker['metadata']['uid'] if worker else None
                    if uid != observed_uid:
                        qualified_worker_changed = bool(observed_uid and self.data.get('ready_observed_at'))
                        # Old phase/log evidence remains in its UID-bound history,
                        # never as the current replacement's startup observation.
                        self.data.pop('startup', None)
                        self.data['startup_observation'] = {
                            'version': STARTUP_OBSERVER_VERSION, 'status': 'disconnected', 'context': context,
                            'worker_uid': uid, 'previous_worker_uid': observed_uid,
                            'last_successful_at': None, 'last_log_at': None}
                        observed_uid = uid
                        display.reset()
                        self.save()
                        if qualified_worker_changed:
                            raise RuntimeError('Previously Ready worker changed; prior startup cannot qualify '
                                               'its replacement. Resources and lease retained.')
                    if any(p.get('status', {}).get('phase') == 'Failed' or
                           any(c.get('restartCount', 0) for c in p.get('status', {}).get('containerStatuses', []))
                           for p in pods):
                        raise RuntimeError('A demo Pod failed or restarted; inspect the logs before continuing.')
                    logs = ''
                    main = next((c for c in worker.get('status', {}).get('containerStatuses', [])
                                 if c['name'] == 'main'), {}) if worker else {}
                    waiting = main.get('state', {}).get('waiting', {}).get('reason')
                    if waiting in ('ErrImagePull', 'ImagePullBackOff', 'InvalidImageName',
                                   'CreateContainerConfigError', 'CreateContainerError',
                                   'CrashLoopBackOff', 'RunContainerError') or 'terminated' in main.get('state', {}):
                        raise RuntimeError('Worker container cannot start or terminated: ' + str(waiting or 'terminated') +
                                           '. Resources and lease retained; inspect before continuing.')
                    if worker and 'running' in main.get('state', {}):
                        logs = self.startup_read('logs', worker['metadata']['name'], '-n', self.ns, '-c', 'main',
                                                 '--timestamps=true', deadline=deadline)
                        confirmed = get('get', 'pod', worker['metadata']['name'], '-n', self.ns)
                        if confirmed['metadata']['uid'] != uid:
                            self.data.pop('startup', None)
                            self.data['startup_observation'] = {
                                'version': STARTUP_OBSERVER_VERSION, 'status': 'disconnected', 'context': context,
                                'worker_uid': confirmed['metadata']['uid'], 'last_successful_at': None,
                                'last_log_at': None, 'error': 'Worker UID changed during log read.'}
                            self.save()
                            raise RuntimeError('Worker UID changed during log read; resources and lease retained.')
                        pods = [confirmed if p['metadata'].get('uid') == uid else p for p in pods]
                        worker = confirmed
                        main = next((c for c in worker.get('status', {}).get('containerStatuses', [])
                                     if c['name'] == 'main'), {})
                        if (worker.get('status', {}).get('phase') == 'Failed' or any(
                                c.get('restartCount', 0) for c in worker.get('status', {}).get('containerStatuses', [])) or
                                'terminated' in main.get('state', {})):
                            raise RuntimeError('A demo Pod failed or restarted; inspect the logs before continuing.')
                    if ready_pods(pods):
                        if 'running' not in main.get('state', {}):
                            raise RuntimeError('Ready worker has no observed running container; refusing readiness.')
                        for pod in pods:
                            for status in pod.get('status', {}).get('containerStatuses', []):
                                if status.get('imageID', '').split('@')[-1] != read_json(MODEL_LOCK)['runtime_image'].split('@')[-1]:
                                    raise RuntimeError('Observed image differs from the pinned runtime.')
                        from gpu_claims import verify_allocation
                        reader = SimpleNamespace(ns=self.ns, get=get)
                        claim = verify_allocation(reader, worker, worker['spec']['containers'][0], 2)
                        if ALLOCATION is not None:
                            role = self.data.get('active_arm', 'intro')
                            proof = ALLOCATION.verify(worker, claim, get('get', 'resourceslices'), role)
                            write_json(self.path / 'allocated-gpus.json', proof)
                except StartupTransportError as error:
                    display.reset()
                    if outage_started is None:
                        outage_started, outage_wall = error.started, now()
                    observation = self.data.setdefault('startup_observation', {
                        'version': STARTUP_OBSERVER_VERSION, 'context': context, 'worker_uid': observed_uid})
                    observation.update(status='stale' if observation.get('last_successful_at') else 'disconnected',
                                       outage_started_at=outage_wall, error=str(error),
                                       retry_budget_seconds=STARTUP_OUTAGE_BUDGET)
                    self.save()
                    print('\n' + observer_note(observation), flush=True)
                    deadline = min(end, outage_started + STARTUP_OUTAGE_BUDGET)
                    if time.monotonic() >= deadline:
                        observation['retry_exhausted_at'] = now()
                        self.save()
                        raise TimeoutError('Startup observer transport retry budget exhausted; '
                                           'current readiness unknown. Resources and lease retained.') from error
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
                    continue
                except (RuntimeError, ValueError, KeyError) as error:
                    observation = self.data.setdefault('startup_observation', {
                        'version': STARTUP_OBSERVER_VERSION, 'context': context, 'worker_uid': observed_uid})
                    observation.update(status='failed', error=str(error), failed_at=now())
                    self.save()
                    raise
                if outage_started is not None:
                    print('\nObserver reconnected; fresh Pod and log observations resumed.', flush=True)
                    display.reset()
                outage_started = outage_wall = None
                progress = startup_progress(pods, logs, self.data['apply_started_at'])
                self.data['startup'] = progress
                self.track_startup(pods, logs)
                self.save_startup_observation(worker, logs, context)
                self.save()
                display.update(progress)
                if ready_pods(pods):
                    write_json(self.path / 'ready-pods.json', {'items': pods})
                    (self.path / 'worker.log').write_text(logs)
                    self.data['worker_pod'] = worker['metadata']['name']
                    self.data['worker_ready_transition_at'] = next(
                        c['lastTransitionTime'] for c in worker['status']['conditions'] if c['type'] == 'Ready')
                    break
                time.sleep(min(5, max(0, end - time.monotonic())))
            else:
                raise TimeoutError(f'Service did not become Ready in {self.args.timeout}s; '
                                   'current readiness unknown. Resources and lease retained.')
        self.data.setdefault('ready_observed_at', now())
        self.save()

    def track_startup(self, pods, logs):
        """Optional extra evidence for demos that reuse the startup monitor."""

    def endpoint(self):
        if self.args.rehearsal:
            self.data['base_url'] = 'http://127.0.0.1:' + str(self.args.port)
            self.show_command(['curl', '--fail', '--silent', '--show-error', self.data['base_url'] + '/v1/models'])
            print('[REHEARSAL] Port forward and /v1/models response are simulated.')
            print(json.dumps({'data': [{'id': self.data['model']}]}, indent=2))
        else:
            services = self.run.get('get', 'services', '-n', self.ns)['items']
            matching = [s for s in services if s['metadata']['name'].startswith(self.data.get('graph', GRAPH) + '-') and
                        any(p['port'] == 8000 for p in s['spec'].get('ports', []))]
            if len(matching) != 1:
                raise RuntimeError('Expected exactly one frontend HTTP Service.')
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', self.args.port))
            args = self.run.kbase + ['port-forward', '-n', self.ns, 'service/' + matching[0]['metadata']['name'],
                                     f'{self.args.port}:8000', '--address=127.0.0.1']
            self.show_command(args)
            with (self.path / 'port-forward.log').open('a') as output:
                self.forward = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT)
            self.data['base_url'] = f'http://127.0.0.1:{self.args.port}'
            for _ in range(30):
                if self.forward.poll() is not None:
                    raise RuntimeError('Port forward stopped; see port-forward.log.')
                try:
                    with urllib.request.urlopen(self.data['base_url'] + '/v1/models', timeout=2) as response:
                        models = json.load(response)
                    if self.data['model'] in [m['id'] for m in models.get('data', [])]:
                        break
                    raise RuntimeError('Frontend does not advertise the expected model.')
                except (OSError, TimeoutError):
                    time.sleep(1)
            else:
                raise TimeoutError('HTTP model discovery did not become available.')
            self.command(['curl', '--fail', '--silent', '--show-error', self.data['base_url'] + '/v1/models'])
            write_json(self.path / 'models.json', models)
        self.data.setdefault('model_discovered_at', now())
        self.save()

    def request(self):
        url = self.data['base_url'] + '/v1/chat/completions'
        args = ['curl', '--fail', '--silent', '--show-error', '--max-time', '180', url,
                '-H', 'Content-Type: application/json', '--data-binary', '@' + str(self.path / 'request.json')]
        print('\n' + request_text(read_json(self.path / 'request.json')))
        self.show_command(args)
        if self.args.rehearsal:
            response = {'model': self.data['model'], 'choices': [{'message': {'content':
                'def add(a, b):\n    return a + b'}, 'finish_reason': 'stop'}], 'simulated': True}
        else:
            response = json.loads(self.run.command(args, timeout=200).stdout)
            content = response.get('choices', [{}])[0].get('message', {}).get('content')
            if not content or response.get('model') != self.data['model']:
                raise RuntimeError('Inference did not return content for the expected model.')
        print(response_text(response))
        write_json(self.path / 'response.json', response)
        self.data.setdefault('response_observed_at', now())
        self.save()

    def summary(self):
        phases = {name: None for name in PATTERNS}
        if not self.args.rehearsal and self.data.get('worker_pod'):
            phases = phase_timings((self.path / 'worker.log').read_text())
        start = self.data.get('apply_started_at')
        boundaries = {}
        for name, key in [('worker_and_frontend_ready', 'ready_observed_at')]:
            value = self.data.get(key)
            boundaries[name] = ((timestamp(value) - timestamp(start)).total_seconds()
                                if start and value and not self.args.rehearsal else None)
        summary = {'rehearsal': self.args.rehearsal, 'observed_seconds_since_apply': boundaries,
                   'logged_seconds_slowest_rank': phases,
                   'startup_phases': self.data.get('startup', {}),
                   'notes': ['Startup proceeds without presenter pauses; readiness is polled every 5 seconds.',
                             'Logged subphases can overlap; do not sum them.',
                             'Checkpoint already staged; external download is excluded.',
                             'This introductory profile skips torch.compile and CUDA graphs (eager execution).']}
        transition = self.data.get('worker_ready_transition_at')
        worker_ready = ((timestamp(transition) - timestamp(start)).total_seconds() if start and transition else None)
        summary['apply_to_worker_ready_transition_seconds'] = worker_ready
        warmup = next((p for p in self.data.get('startup', {}).get('phases', [])
                       if p['name'] == '  Warmup window'), {})
        summary['observed_kernel_warmup_window_seconds'] = warmup.get('seconds') if warmup.get('status') == 'done' else None
        write_json(self.path / 'timing.json', summary)
        print('\nStartup timing' + (' · REHEARSAL / not measured' if self.args.rehearsal else ''))
        print('  Kubernetes worker Ready timestamp: ' +
              (f'{worker_ready:.1f}s since apply' if worker_ready is not None else 'not measured'))
        for name, value in boundaries.items():
            print(f'  {name:32s} ' + (f'{value:8.1f}s' if value is not None else 'not measured'))
        print('\nEngine log subphases (slowest TP rank):')
        for name, value in phases.items():
            if name == 'compilation':
                continue
            if name == 'warmup' and value is None:
                continue
            print(f'  {name:32s} ' + (f'{value:8.2f}s' if value is not None else 'not logged'))
        print('  Compilation / CUDA graphs        disabled for this demo')
        if phases['warmup'] is None and summary['observed_kernel_warmup_window_seconds'] is not None:
            print(f'  Kernel warmup window             {summary["observed_kernel_warmup_window_seconds"]:8.2f}s (log markers)')
        print('  This introductory profile skips torch.compile and CUDA graphs (eager execution).')

    def require_prepared(self):
        if self.args.rehearsal:
            # Rehearsals have no cluster prerequisites to prepare.
            self.data['prepared'] = True
            self.save()
        elif not self.data['prepared']:
            command = shlex.join(presenter_command(self.entrypoint, 'prepare', '--run', repo_path(self.path)))
            raise RuntimeError('Prepare this run offstage before opening the demo:\n' + command)

    def guided(self):
        self.require_prepared()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal. Use --preview, or --rehearsal --plain --auto.')
        mode = 'REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER'
        print(f'\nDynamo workshop · First deployment\n{mode}\nRun: {repo_path(self.path)}\nNamespace: {self.ns}', flush=True)
        actions = [self.deployment, self.startup,
                   self.endpoint, self.request]
        self.run_steps(self.steps, actions)

    def run_steps(self, steps, actions, *, start=1, total=None):
        if len(steps) != len(actions):
            raise ValueError('Each presentation step needs exactly one action.')
        total = total if total is not None else start + len(steps) - 1
        try:
            for index, ((title, explanation), action) in enumerate(zip(steps, actions), start):
                print(f'\nNext: {index}/{total}  {title}', flush=True)
                self.pause()
                if sys.stdout.isatty():
                    print('\033[2J\033[H', end='', flush=True)
                print(f'\n{"=" * 64}\n{index}/{total}  {title}\n{explanation}\n{"=" * 64}', flush=True)
                self.data['step'] = index
                self.save()
                action()
            print('\nDemo complete. The service stays running.')
        finally:
            if self.forward:
                self.forward.terminate()
                try:
                    self.forward.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.forward.kill()
                    self.forward.wait()
            launcher = presenter_command(self.entrypoint)
            run_path = repo_path(self.path) if self.compact_output else str(self.path)
            if self.compact_output:
                print('\nFrom the repository root:')
            print('\nResume: ' + shlex.join(launcher + ['--run', run_path] +
                                             (['--rehearsal'] if self.args.rehearsal else [])))
            print('Cleanup: ' + shlex.join(launcher + ['cleanup', '--run', run_path] +
                                          (['--rehearsal'] if self.args.rehearsal else [])))

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        from demos.common import dependencies
        with dependencies.parent_lock(self.path):
            dependencies.assert_clear(self.path)
            self._cleanup_owned_deployment()

    def _cleanup_owned_deployment(self):
        if self.data.get('apply_started_at') and not lease_owned(self.path):
            raise RuntimeError('Demo does not own the GPU lease. Inspect ownership before cleanup.')
        obj = self.run.k('get', 'dgd', GRAPH, '-n', self.ns, '-o', 'json', check=False)
        if obj.returncode == 0:
            if json.loads(obj.stdout)['metadata'].get('labels', {}).get('feature-test-run') != self.ns:
                raise ValueError('Refusing to delete an unowned graph.')
            self.kubectl('delete', 'dgd', GRAPH, '-n', self.ns, '--wait=true', '--timeout=90s', timeout=105,
                         pause_before=False)
        elif 'NotFound' not in obj.stderr:
            raise RuntimeError(obj.stderr)
        for _ in range(36):
            pods = self.run.get('get', 'pods', '-n', self.ns, '-l', 'workshop-role')['items']
            claims = self.run.get('get', 'resourceclaims', '-n', self.ns)['items']
            if not pods and not claims:
                if lease_owned(self.path):
                    (LEASE / 'owner.json').unlink()
                    LEASE.rmdir()
                self.data['cleaned_at'] = now()
                self.save()
                print('Verified zero demo Pods and GPU claims. Namespace/model cache retained.')
                return
            time.sleep(5)
        raise RuntimeError('Demo cleanup is incomplete; GPU lease retained.')


def panel_read(command):
    """Bound side-pane reads without creating a Run or changing saved state."""
    arguments = list(command) + ['--request-timeout=' + f'{STARTUP_READ_TIMEOUT:g}s']
    try:
        return subprocess.run(arguments, capture_output=True, text=True, timeout=STARTUP_READ_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(arguments, 124, '', 'Observer read timed out.')


def observe(path, view, once=False):
    """Read-only panes: never instantiate Run or mutate its state."""
    last_log_uid, last_logs = None, None
    last_log_context = None
    while True:
        data = read_json(path / 'demo.json')
        context = (data['namespace'], data.get('pod_selector'), startup_context(data))
        if context != last_log_context:
            last_log_uid, last_logs = None, None
            last_log_context = context
        rehearsal = data['rehearsal']
        title = 'Resources and elapsed time' if view == 'resources' else 'vLLM worker logs'
        print('\033[2J\033[H' + title + (' · REHEARSAL / SIMULATED' if rehearsal else ' · LIVE'), flush=True)
        print('Namespace: ' + data['namespace'])
        note = observer_note(data.get('startup_observation'))
        if note:
            print(note, flush=True)
        if data.get('active_arm'):
            print('Worker: ' + data['active_arm'])
        if view == 'resources' and data.get('demo_kind') == 'modelexpress' and data.get('arms', {}).get('source'):
            print('Source: ' + data['arms']['source']['node'])
        progress = startup_display_progress(path, data) if view == 'resources' else data.get('startup')
        if (data.get('startup_observation') and
                data['startup_observation'].get('context') != startup_context(data)):
            progress = None
        if progress and view == 'resources':
            elapsed = progress.get('total_seconds')
            print('Startup: ' + (f'{elapsed:.1f}s' if elapsed is not None else 'simulated'))
            print(progress_lines(progress))
            transfer = data.get('mx_transfer')
            if transfer:
                print(f'P2P: {transfer["completed_ranks"]}/{transfer["expected_ranks"]} ranks transferred')
        elif data.get('apply_started_at') and view == 'resources':
            elapsed = (dt.datetime.now(dt.timezone.utc) - timestamp(data['apply_started_at'])).total_seconds()
            print(f'Startup: {elapsed:.0f}s')
        if rehearsal:
            if view == 'resources':
                if not data.get('demo_kind'):
                    print('\n' + rehearsal_resource_table(data))
                else:
                    state = ('Ready' if data.get('ready_observed_at') else
                             'Starting' if data.get('apply_started_at') else 'Not deployed')
                    print('\nExample: 1 CPU frontend + 1 vLLM replica / 2 GPUs\nState: ' + state +
                          '\nStep: ' + str(data['step']))
            else:
                if not data.get('apply_started_at'):
                    print('\nWaiting for the Deploy step.')
                else:
                    print('\nExample engine phases:\n  Loading model weights\n  KV allocation and engine warmup')
                    if data.get('ready_observed_at'):
                        print('  Engine initialized')
                print('\nNo real model is running.')
        else:
            base = kbase()
            if view == 'resources':
                if not data.get('demo_kind'):
                    if not data.get('prepared'):
                        print('Waiting for preparation.', flush=True)
                    else:
                        result = panel_read(base + ['get', INTRO_RESOURCES, '-n', data['namespace'], '-o', 'json'])
                        print(compact_resource_table(json.loads(result.stdout)['items'])
                              if result.returncode == 0 else
                              'Resource observation unavailable; current readiness unknown.\n' + result.stderr, flush=True)
                    if once:
                        return
                    time.sleep(3)
                    continue
                if data.get('demo_kind') == 'modelexpress':
                    commands = [base + ['get', 'pods', '-n', data['namespace'], '-l', 'workshop-role=worker'],
                                base + ['get', 'dgd', '-n', data['namespace']]]
                else:
                    commands = [base + ['get', 'pods', '-n', data['namespace']],
                                base + ['get', 'dgd,services', '-n', data['namespace']]]
            else:
                selector = data.get('pod_selector', 'workshop-role') + ',workshop-role=worker'
                result = panel_read(base + ['get', 'pods', '-n', data['namespace'], '-l', selector, '-o', 'json'])
                pods = json.loads(result.stdout).get('items', []) if result.returncode == 0 else []
                expected_uid = data.get('startup_observation', {}).get('worker_uid')
                if expected_uid and expected_uid != last_log_uid:
                    last_log_uid, last_logs = None, None
                if result.returncode:
                    print('Observer disconnected; current readiness unknown.\n' + result.stderr, flush=True)
                    cached = cached_startup_log(path, data)
                    if cached is None and (not expected_uid or expected_uid == last_log_uid):
                        cached = last_logs
                    if cached is not None:
                        print('Last successful log observation (stale):\n' + '\n'.join(cached.splitlines()[-28:]), flush=True)
                    if once:
                        return
                    time.sleep(3)
                    continue
                pods = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
                uid = pods[0]['metadata']['uid'] if len(pods) == 1 else None
                if uid != last_log_uid:
                    last_log_uid, last_logs = None, None
                commands = [base + ['logs', pods[0]['metadata']['name'], '-n', data['namespace'], '-c', 'main',
                                    '--tail=28', '--timestamps=true']] if len(pods) == 1 else []
                if not pods:
                    print('Waiting for the operator to create the worker Pod.')
                elif len(pods) != 1:
                    print('Worker identity is ambiguous; no cached logs shown.')
            for command in commands:
                result = panel_read(command)
                if view != 'logs':
                    print(result.stdout if result.returncode == 0 else
                          'Resource observation unavailable; current readiness unknown.\n' + result.stderr, flush=True)
                    continue
                if result.returncode == 0:
                    confirmed = panel_read(base + ['get', 'pod', pods[0]['metadata']['name'], '-n',
                                                   data['namespace'], '-o', 'json'])
                    if (confirmed.returncode or json.loads(confirmed.stdout)['metadata']['uid'] != uid):
                        last_log_uid, last_logs = None, None
                        print('Cannot confirm worker UID after log read; current observation unavailable.', flush=True)
                        continue
                    last_log_uid, last_logs = uid, result.stdout
                    print(result.stdout, flush=True)
                else:
                    print('Log observation unavailable; current readiness unknown.\n' + result.stderr, flush=True)
                    cached = cached_startup_log(path, data, uid)
                    if cached is None and last_log_uid == uid:
                        cached = last_logs
                    if cached is not None:
                        print('Last successful log observation (stale):\n' + '\n'.join(cached.splitlines()[-28:]), flush=True)
        if once:
            return
        time.sleep(3)


def tmux_layout(demo):
    binary = os.environ.get('WORKSHOP_TMUX') or shutil.which('tmux')
    if not binary and (ROOT / '.local/bin/tmux').exists():
        binary = str(ROOT / '.local/bin/tmux')
    if not binary:
        raise RuntimeError('tmux is not installed. Install tmux, or add --plain. Offline preview: --preview.')
    nested = os.environ.get('TMUX')
    base = [binary, '-S', nested.split(',')[0]] if nested else [binary, '-L', 'dynamo-workshop', '-f', '/dev/null']
    name = 'demo-' + hashlib.sha256(str(demo.path).encode()).hexdigest()[:10]

    def tm(*args):
        result = subprocess.run(base + list(args), capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('tmux: ' + result.stderr.strip())
        return result.stdout.strip()

    # Panes resume the run, which records its own lease; the shared tmux server may
    # carry another presenter's environment.
    child = ['env', '-u', LEASE_ENV] + presenter_command(getattr(demo, 'entrypoint', SCRIPT))
    if os.environ.get('WORKSHOP_PULL_SECRET_SOURCE'):
        child = ['env', 'WORKSHOP_PULL_SECRET_SOURCE=' + os.environ['WORKSHOP_PULL_SECRET_SOURCE']] + child
    if ALLOCATION is not None:
        child = ['env', allocation.ENV + '=' + str(demo.path / 'allocation.json')] + child
    hold = shlex.join(child + ['hold'])
    fmt = '#{session_id} #{window_id} #{pane_id}'
    if nested:
        target = ['-t', os.environ['TMUX_PANE']] if os.environ.get('TMUX_PANE') else []
        session = tm('display-message', '-p', *target, '#{session_id}')
        ids = tm('new-window', '-d', '-P', '-F', fmt, '-t', session, '-n', name, '-c', str(ROOT), hold)
    else:
        if subprocess.run(base + ['has-session', '-t', name], capture_output=True).returncode == 0:
            raise RuntimeError(f'Demo session already exists. Reattach with: {shlex.join(base + ["attach", "-t", name])}')
        ids = tm('new-session', '-d', '-P', '-F', fmt, '-s', name, '-n', 'Deploy', '-x', '180', '-y', '50', '-c', str(ROOT), hold)
    session, window, left = ids.split()
    tm('set-option', '-w', '-t', window, 'remain-on-exit', 'on')
    tm('set-option', '-w', '-t', window, 'pane-border-status', 'top')
    tm('set-option', '-w', '-t', window, 'pane-border-format', ' #T ')
    tm('set-option', '-w', '-t', window, 'automatic-rename', 'off')
    top = tm('split-window', '-h', '-l', '42%', '-t', left, '-P', '-F', '#{pane_id}', '-c', str(ROOT),
             shlex.join(child + ['observe', '--run', str(demo.path), '--view', 'resources']))
    bottom = tm('split-window', '-v', '-l', '50%', '-t', top, '-P', '-F', '#{pane_id}', '-c', str(ROOT),
                shlex.join(child + ['observe', '--run', str(demo.path), '--view', 'logs']))
    titles = getattr(demo, 'pane_titles', ('Walkthrough', 'Resources + timing', 'Worker logs'))
    for pane, title in zip((left, top, bottom), titles):
        tm('select-pane', '-t', pane, '-T', title)
    if not nested:
        tm('set-option', '-t', session, 'mouse', 'on')
        tm('set-option', '-t', session, 'status-left', ' Dynamo workshop | ')
        tm('set-option', '-t', session, 'status-right', '')
    guided = child + ['run', '--plain', '--run', str(demo.path), '--port', str(demo.args.port), '--timeout', str(demo.args.timeout)]
    if demo.args.rehearsal:
        guided.append('--rehearsal')
    if demo.args.auto:
        guided.append('--auto')
    tm('respawn-pane', '-k', '-t', left, '-c', str(ROOT), shlex.join(guided))
    tm('select-pane', '-t', left)
    write_json(demo.path / 'tmux.json', {'command': base, 'session': session, 'window': window,
                                       'panes': [left, top, bottom], 'created_session': not bool(nested)})
    print('Demo layout ready: ' + shlex.join(base + ['attach-session', '-t', session]))
    if not demo.args.detach:
        if nested:
            tm('select-window', '-t', window)
        else:
            subprocess.run(base + ['attach-session', '-t', session], check=True)
