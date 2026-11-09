"""Bind the second replica to the retained first replica and its startup evidence."""
from __future__ import annotations

import math
import copy
from pathlib import Path
import re

import yaml

from demos.common import runtime as ui
from demos.common import weights
from demos.common.allocation import physical_gpus


INPUTS = ('deployment.yaml', 'gpu-claim-template.yaml', 'source-service.yaml',
          'timing.json', 'ready-pods.json', 'worker.log')


def _ready(pod):
    return (not pod['metadata'].get('deletionTimestamp') and
            any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in pod.get('status', {}).get('conditions', [])) and
            not any(c.get('restartCount', 0)
                    for c in pod.get('status', {}).get('containerStatuses', [])))


def _positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('The first replica has no measured ' + label + '; finish its startup first.')
    return value


def _intro(path):
    data = ui.read_json(path / 'demo.json')
    if data.get('profile') != ui.PROFILE:
        raise ValueError('The first replica uses an older launch configuration. Prepare and launch a fresh '
                         'single-replica run with ModelExpress enabled; the existing native loader cannot '
                         'publish weights without restarting. The current server was left running.')
    if data.get('rehearsal') or data.get('cleaned_at') or not data.get('prepared'):
        raise ValueError('ModelExpress needs an uncleaned, prepared live single-replica run.')
    if (data.get('demo_kind') not in (None, 'single-replica') or
            any(key != 'profile' and key.endswith('_profile') for key in data)):
        raise ValueError('The selected run is not the single-replica introduction.')
    state = ui.read_json(path / 'state.json')
    if state.get('owner') != 'kubecon-dynamo-feature-tests' or state.get('namespace') != data.get('namespace'):
        raise ValueError('The selected first replica is not an owned workshop run.')
    if (data.get('source_sha256') != ui.digest(ui.TEMPLATE) or
            data.get('lock_sha256') != ui.digest(ui.MODEL_LOCK)):
        raise ValueError('The first replica model/runtime inputs changed; use a fresh single-replica run.')
    if not data.get('ready_observed_at'):
        raise ValueError('Finish the single-replica startup before preparing ModelExpress.')
    graph = yaml.safe_load((path / 'deployment.yaml').read_text())
    if (graph['metadata'].get('name') != ui.GRAPH or
            graph['metadata'].get('namespace') != data['namespace'] or
            graph['metadata'].get('labels', {}).get('feature-test-run') != data['namespace']):
        raise ValueError('The selected first-replica manifest is not its owned introductory graph.')
    config = weights.worker_config(graph)
    args = config.get('args', [])
    if ('--load-format' not in args or args[args.index('--load-format') + 1:][:1] != ['modelexpress'] or
            next(c for c in graph['spec']['components'] if c['type'] == 'worker')
            ['podTemplate'].get('metadata', {}).get('labels', {}).get('mx-role') != 'source'):
        raise ValueError('The first replica is not an MX-enabled weight source; prepare and launch '
                         'a fresh single-replica run. The current server was left running.')
    for filename, key in (('deployment.yaml', 'manifest_sha256'),
                          ('gpu-claim-template.yaml', 'claim_sha256'),
                          ('source-service.yaml', 'mx_source_service_sha256')):
        if data.get(key) != ui.digest(path / filename):
            raise ValueError('A frozen first-replica input changed: ' + filename)
    return data, graph


def snapshot(path):
    """Freeze a completed storage-loaded intro's recorded identity and timings."""
    path = Path(path).resolve()
    data, graph = _intro(path)
    pods = ui.read_json(path / 'ready-pods.json')['items']
    if not ui.ready_pods(pods) or not all(_ready(p) for p in pods):
        raise ValueError('The recorded first-replica Pods were not Ready without restarts.')
    roles = {role: next(p for p in pods if p['metadata']['labels']['workshop-role'] == role)
             for role in ('worker', 'frontend')}
    worker, frontend = roles['worker'], roles['frontend']
    if worker['metadata'].get('labels', {}).get('mx-role') != 'source':
        raise ValueError('The recorded first replica was not an MX weight source.')
    logs = (path / 'worker.log').read_text()
    if re.search(r'Receiving \d+ tensors from source \(P2P\)|Transfer complete:', logs):
        raise ValueError('The first replica received peer weights; it cannot supply a storage startup baseline.')
    if not (re.search(r'Trying strategy:\s*default\b', logs) or
            ('Trying strategy: instant_tensor' in logs and
             'Loading safetensors using InstantTensor loader:' in logs)):
        raise ValueError('The first replica log does not prove its storage-loading strategy.')
    timing = ui.read_json(path / 'timing.json')
    if timing.get('rehearsal') or not timing.get('startup_phases', {}).get('ready'):
        raise ValueError('The first replica has no completed live startup timing.')
    seconds = _positive(timing.get('observed_seconds_since_apply', {}).get('worker_and_frontend_ready'),
                        'deployment-to-Ready time')
    phases = timing.get('logged_seconds_slowest_rank', {})
    loading = _positive(phases.get('model_loading'), 'model-loading time')
    if ui.phase_timings(logs).get('model_loading') != loading:
        raise ValueError('The first replica model-loading timing differs from its recorded log.')
    uid = worker['metadata']['uid']
    allocation = path / 'allocation.json'
    inputs = {name: ui.digest(path / name) for name in INPUTS}
    if allocation.exists():
        inputs['allocation.json'] = ui.digest(allocation)
    return {'run': str(path), 'namespace': data['namespace'], 'worker_uid': uid,
            'worker_name': worker['metadata']['name'], 'node': worker['spec']['nodeName'],
            'frontend_uid': frontend['metadata']['uid'], 'frontend_name': frontend['metadata']['name'],
            'inputs': inputs, 'allocation_present': allocation.exists(),
            'baseline': {'simulated': False, 'engine_signature': weights.engine_signature(graph),
                         'source_uid': uid, 'worker_uid': uid, 'node': worker['spec']['nodeName'],
                         'ready_seconds': seconds, 'model_loading_seconds': loading,
                         'engine_init_seconds': phases.get('engine_initialization')}}


def validate_files(binding):
    """Never let resumed presentations silently switch source or baseline evidence."""
    path = Path(binding['run'])
    expected_inputs = set(INPUTS) | ({'allocation.json'} if binding['allocation_present'] else set())
    if set(binding['inputs']) != expected_inputs:
        raise ValueError('The MX source binding is incomplete; prepare a fresh ModelExpress run.')
    if (path / 'allocation.json').exists() != binding['allocation_present']:
        raise ValueError('The bound first-replica allocation changed.')
    data, _ = _intro(path)
    if data['namespace'] != binding['namespace']:
        raise ValueError('The first-replica namespace changed.')
    for name, expected in binding['inputs'].items():
        if ui.digest(path / name) != expected:
            raise ValueError('The bound first-replica evidence changed: ' + name)


def _check_container(actual, expected):
    # Kubernetes adds default container fields; compare the explicit engine
    # configuration rather than treating admission defaults as a profile change.
    for key in ('image', 'command', 'args', 'resources'):
        if actual.get(key) != expected.get(key):
            raise RuntimeError('The running first-replica configuration changed: ' + key)
    def environments(container):
        result = {}
        for item in container.get('env', []):
            value = copy.deepcopy(item)
            field = value.get('valueFrom', {}).get('fieldRef', {})
            if field.get('apiVersion') == 'v1':
                del field['apiVersion']
            if value['name'] in result:
                raise RuntimeError('The running first replica has duplicate environment names.')
            result[value['name']] = value
        return result
    authored, observed = environments(expected), environments(actual)
    if any(observed.get(name) != value for name, value in authored.items()):
        raise RuntimeError('The running first-replica configuration changed: env')
    # Dynamo/Grove inject runtime identity and health/telemetry configuration.
    # An extra loader or transport setting must still invalidate the binding.
    extras = set(observed) - set(authored)
    if any(not name.startswith(('DYN_', 'GROVE_', 'NIXL_TELEMETRY_')) and
           name not in ('POD_NAME', 'POD_NAMESPACE', 'POD_UID', 'PROMETHEUS_ENDPOINT') for name in extras):
        raise RuntimeError('The running first replica has an unexpected environment setting.')


def identity(run, binding):
    """Inspect the exact live source, discovery endpoint and physical DRA GPUs."""
    validate_files(binding)
    ns = binding['namespace']
    frozen_graph = yaml.safe_load((Path(binding['run']) / 'deployment.yaml').read_text())
    expected = weights.worker_config(frozen_graph)
    graph = run.get('get', 'dgd', ui.GRAPH, '-n', ns)
    if (graph['metadata'].get('deletionTimestamp') or
            graph['metadata'].get('labels', {}).get('feature-test-run') != ns or
            not any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in graph.get('status', {}).get('conditions', []))):
        raise RuntimeError('The retained first-replica graph is not owned and Ready.')
    _check_container(weights.worker_config(graph), expected)
    sources = run.get('get', 'pods', '-n', ns, '-l', 'mx-role=source,workshop-role=worker')['items']
    active = [p for p in sources if not p['metadata'].get('deletionTimestamp')]
    if len(active) != 1:
        raise RuntimeError('Expected exactly one retained first-replica weight source.')
    worker = active[0]
    if (worker['metadata']['uid'] != binding['worker_uid'] or
            worker['metadata']['name'] != binding['worker_name'] or
            worker['spec'].get('nodeName') != binding['node']):
        raise RuntimeError('The first-replica worker was replaced or moved; its previous startup cannot qualify it.')
    frontend = run.get('get', 'pod', binding['frontend_name'], '-n', ns)
    if frontend['metadata']['uid'] != binding['frontend_uid']:
        raise RuntimeError('The first-replica frontend was replaced; inspect before continuing.')
    if not all(_ready(p) for p in (worker, frontend)):
        raise RuntimeError('The retained first replica is not Ready without restarts.')
    container = next(c for c in worker['spec']['containers'] if c['name'] == expected['name'])
    _check_container(container, expected)
    digest = expected['image'].split('@')[-1]
    if any(c.get('imageID', '').split('@')[-1] != digest
           for c in worker.get('status', {}).get('containerStatuses', [])):
        raise RuntimeError('The running first replica differs from the pinned runtime image.')
    service = run.get('get', 'service', weights.SOURCE_SERVICE, '-n', ns)
    frozen_service = yaml.safe_load((Path(binding['run']) / 'source-service.yaml').read_text())
    if (service['metadata'].get('deletionTimestamp') or
            service['metadata'].get('labels', {}).get('feature-test-run') != ns or
            service['spec'].get('selector') != frozen_service['spec']['selector'] or
            [{k: p[k] for k in ('name', 'port', 'targetPort')} for p in service['spec'].get('ports', [])]
            != frozen_service['spec']['ports']):
        raise RuntimeError('The first-replica weight-discovery Service changed.')
    slices = run.get('get', 'endpointslices', '-n', ns, '-l',
                     'kubernetes.io/service-name=' + weights.SOURCE_SERVICE)['items']
    endpoints = [e for s in slices for e in s.get('endpoints', [])
                 if e.get('conditions', {}).get('ready') is True]
    if (len(endpoints) != 1 or endpoints[0].get('targetRef', {}).get('uid') != binding['worker_uid'] or
            endpoints[0].get('addresses') != [worker.get('status', {}).get('podIP')]):
        raise RuntimeError('Weight discovery does not resolve only to the retained first replica.')
    references = container.get('resources', {}).get('claims', [])
    if len(references) != 1:
        raise RuntimeError('The retained first replica has an unexpected GPU claim binding.')
    names = [c['resourceClaimName'] for c in worker['status'].get('resourceClaimStatuses', [])
             if c['name'] == references[0]['name']]
    if len(names) != 1:
        raise RuntimeError('The retained first replica has no exact allocated GPU claim.')
    claim = run.get('get', 'resourceclaim', names[0], '-n', ns)
    owners = claim['metadata'].get('ownerReferences', [])
    if not any(o.get('kind') == 'Pod' and o.get('uid') == binding['worker_uid'] for o in owners):
        raise RuntimeError('The source GPU claim is not owned by the retained worker.')
    reservations = claim.get('status', {}).get('reservedFor', [])
    if reservations and any(r.get('uid') != binding['worker_uid'] for r in reservations):
        raise RuntimeError('The source GPU claim is reserved for another consumer.')
    try:
        observed = physical_gpus(worker, claim, run.get('get', 'resourceslices'))
    except ValueError as error:
        raise RuntimeError('Cannot verify source physical GPUs: ' + str(error)) from error
    if len(observed) != 2:
        raise RuntimeError('Expected two distinct physical GPUs for the retained first replica.')
    return {'uid': binding['worker_uid'], 'node': binding['node'], 'graph_uid': graph['metadata']['uid'],
            'frontend_uid': frontend['metadata']['uid'], 'claim_uid': claim['metadata']['uid'],
            'gpu_devices': sorted(observed), 'service_uid': service['metadata']['uid']}
