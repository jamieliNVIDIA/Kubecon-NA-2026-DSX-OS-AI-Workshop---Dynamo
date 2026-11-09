#!/usr/bin/env python3
"""Bind fresh KVCR evidence to explicitly repaired, retained demo workers.

The KVCR presenter and owning parent's files are read-only dependencies. The
conditional refresh is a separate, single-attempt root-executed operation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import uuid

import demos.common.runtime as ui
import demos.common.support as support
import demos.kvcr.demo as base
import demos.kvcr.guard as guard
from testlib import Run, OWNER as RUN_OWNER

PROFILE = 'super-vl-kvcr-retained-parent-v1'
DEPENDENCIES = ['demos/kvcr/prepared.py', 'demos/kvcr/demo.py',
                'demos/kvcr/guard.py', 'demos/common/runtime.py',
                'demos/common/support.py', 'scripts/testlib.py', 'scripts/gpu_claims.py']
SOURCE_NAMES = ['deployment.json', 'deployment.yaml', 'runtime.py', 'bootstrap.py',
                'source-lock.json', 'placement.json', 'kvcr-settings.yaml', 'model-lock.json']

NATIVE_CHECKSUM_PROGRAM = '''import json,re,sys,importlib.metadata
from pathlib import Path
import dynamo._core as core
ModelDeploymentCard=core.ModelDeploymentCard
payload=json.load(sys.stdin)
assert '/tmp/kvcr-guard-candidate/installed/' in str(core.__file__),core.__file__
assert importlib.metadata.version('ai-dynamo-runtime')=='1.7.0.dev20261103'
result={}
for role,card in payload.items():
 directory=ModelDeploymentCard.from_json_str(json.dumps(card)).local_dir()
 digest=Path(directory).name
 assert re.fullmatch('[0-9a-f]{64}',digest),directory
 result[role]={'mdcsum':digest,'local_dir_pure_path':directory}
print(json.dumps({'status':'passed','cards':result,'runtime_version':importlib.metadata.version('ai-dynamo-runtime'),'native_module':str(core.__file__),'scope':'Pure native mdcsum path calculation; no model resolution or registration.'}))
'''

READINESS_PROGRAM = '''import json,sys
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import HTTPError
payload=json.load(sys.stdin)
try:
 with urlopen('http://127.0.0.1:8000/v1/models/'+quote(payload['model'],safe='')+'/ready',timeout=10) as response:
  status=response.status;body=json.load(response)
except HTTPError as error:status=error.code;body=json.loads(error.read())
print(json.dumps({'status_code':status,'body':body,'scope':'GET readiness; no inference dispatched.'}))
'''

ASSET_PROGRAM = '''import hashlib,json,os,sys
from pathlib import Path
p=json.load(sys.stdin)
assert os.environ['HF_HUB_OFFLINE']=='1'
root=Path(os.environ['HF_HOME'])/'hub'/('models--'+p['model'].replace('/','--'))/'snapshots'/p['revision']
assert root.is_dir(),str(root)
weights={'.safetensors','.bin','.gguf','.onnx','.tflite','.h5','.pt','.pth','.msgpack'}
def entries():return sorted(v for v in root.iterdir() if v.is_file() and not v.name.startswith('.') and v.suffix not in weights)
paths=entries();files={}
for path in paths:
 before=path.stat();h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
 after=path.stat()
 assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
 files[path.name]={'bytes':after.st_size,'sha256':h.hexdigest()}
assert [v.name for v in entries()]==[v.name for v in paths]
print(json.dumps({'status':'passed','model':p['model'],'revision':p['revision'],'nonweight_files':files,'scope':'Read-only cached assets; no downloads or registration.'}))
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return ui.read_json(Path(path))


def write(path, value):
    path = Path(path)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def tree_hashes(path):
    path = Path(path).resolve()
    return {str(p.relative_to(path)): ui.digest(p) for p in sorted(path.rglob('*')) if p.is_file()}


def dependency_hashes():
    return {name: ui.digest(ui.ROOT / name) for name in DEPENDENCIES}


def separate_output(output, *protected):
    output = Path(output).resolve()
    require(not output.exists(), 'Evidence output must be a fresh directory.')
    for path in map(lambda p: Path(p).resolve(), protected):
        require(output != path and path not in output.parents,
                'New evidence cannot be placed inside protected parent/capture/qualification evidence.')
    return output


def signature(pod):
    return {'uid': pod['metadata']['uid'], 'node': pod['spec']['nodeName'],
            'containers': {c['name']: {k: c[k] for k in ('containerID', 'imageID', 'restartCount')}
                           for c in pod['status']['containerStatuses']}}


def execution_spec(pod):
    """Discard only kubelet/node placement and injected service-account names."""
    spec = copy.deepcopy(pod['spec'])
    spec.pop('nodeName', None)
    injected = {v['name'] for v in spec.get('volumes', []) if v['name'].startswith('kube-api-access-')}
    spec['volumes'] = [v for v in spec.get('volumes', []) if v['name'] not in injected]
    for container in spec['containers']:
        container['volumeMounts'] = [m for m in container.get('volumeMounts', []) if m['name'] not in injected]
    return spec


def normalized_card(value):
    """Compare advertised cards without changing their native compatibility hash."""
    if isinstance(value, list):
        return [normalized_card(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'extra_files' and isinstance(item, list):
            result[key] = sorted((normalized_card(v) for v in item), key=lambda v: (v.get('path', ''), v.get('checksum', '')))
        elif key == 'path' and isinstance(item, str) and item.startswith(('http://', 'https://')):
            url = urlsplit(item)
            result[key] = urlunsplit((url.scheme, 'WORKER-METADATA', url.path, url.query, url.fragment))
        else:
            result[key] = normalized_card(item)
    return result


def role_pods(pods, namespace):
    require(len(pods) == 3, 'Need exactly the three original DGD workload Pods; diagnostic Pods use another selector.')
    result = {}
    for pod in pods:
        labels = pod['metadata'].get('labels', {})
        require(pod['metadata']['namespace'] == namespace and labels.get('feature-test-run') == namespace,
                'A workload Pod is outside the owned namespace.')
        role = labels.get('kvcr-peer', 'frontend')
        require(role in ('a', 'b', 'frontend') and role not in result, 'Ambiguous owned Pod role.')
        require(not pod['spec'].get('hostPID') and not pod['spec'].get('shareProcessNamespace'), 'Pod process isolation changed.')
        result[role] = pod
    require(set(result) == {'a', 'b', 'frontend'}, 'Missing owned workload role.')
    return result


def stable_ready(pod):
    support.healthy([pod])
    require(any(v['type'] == 'Ready' and v['status'] == 'True' for v in pod.get('status', {}).get('conditions', [])),
            'Workload Pod is not Ready.')
    require(bool(pod.get('status', {}).get('containerStatuses')) and
            all(c['ready'] and 'running' in c.get('state', {}) for c in pod['status']['containerStatuses']),
            'Every workload container must be running and Ready.')


def worker_cards(metadata, pods):
    cards, ids = {}, {}
    for role in ('a', 'b'):
        pod = pods[role]
        found = [v for v in metadata['items'] if v['metadata']['name'] == pod['metadata']['name']]
        require(len(found) == 1, 'Need one current worker metadata object per Pod.')
        item = found[0]
        require(any(o.get('kind') == 'Pod' and o.get('uid') == pod['metadata']['uid']
                    for o in item['metadata'].get('ownerReferences', [])), 'Worker metadata belongs to another Pod UID.')
        generated = [v for v in item['spec']['data'].get('endpoints', {}).values()
                     if v.get('component') == 'backend' and v.get('endpoint') == 'generate']
        registered = list(item['spec']['data'].get('model_cards', {}).values())
        require(len(generated) == len(registered) == 1, 'Need exactly one current generate endpoint and model card.')
        ids[role] = str(generated[0]['instance_id'])
        require(ids[role] == str(registered[0]['instance_id']), 'Model card and endpoint instance IDs disagree.')
        cards[role] = registered[0]['card_json']
    return cards, ids


def readiness_two_workers(value, namespace):
    require(value.get('status_code') == 200 and value.get('body', {}).get('ready') is True,
            'Frontend model is not serving Ready.')
    namespaces = value['body'].get('namespaces', {})
    require(set(namespaces) == {namespace}, 'Frontend readiness has unexpected serving namespaces.')
    selected = namespaces[namespace]
    workers = selected.get('worker_types', {})
    require(selected.get('ready') is True and set(workers) == {'aggregated'} and
            type(workers['aggregated'].get('workers')) is int and workers['aggregated']['workers'] == 2,
            'Frontend must admit exactly two aggregated workers before source or receiver HTTP.')


def check_pod_transition(original, current, *, replace_b, replace_frontend):
    require(signature(current['a']) == signature(original['a']), 'Source A changed; retained-source repair is invalid.')
    for role in ('a', 'b', 'frontend'):
        stable_ready(current[role])
        require(execution_spec(current[role]) == execution_spec(original[role]), 'Workload execution spec changed: ' + role)
        require(current[role]['metadata'].get('ownerReferences') == original[role]['metadata'].get('ownerReferences'),
                'Grove controller ownership changed: ' + role)
        require(current[role]['spec']['nodeName'] == original[role]['spec']['nodeName'], 'Workload placement changed: ' + role)
        replaced = replace_b if role == 'b' else replace_frontend if role == 'frontend' else False
        if replaced:
            require(current[role]['metadata']['uid'] != original[role]['metadata']['uid'], 'Expected a declared fresh Pod UID: ' + role)
        else:
            require(signature(current[role]) == signature(original[role]), 'Undeclared workload replacement: ' + role)


def check_native_cards(cards, native, expected_checksum, *, matching):
    require(native.get('status') == 'passed' and native.get('runtime_version') == '1.7.0.dev20261103' and
            set(native.get('cards', {})) == {'a', 'b'}, 'Need exact native matching-runtime MDC checksum results.')
    require(all(re.fullmatch('[0-9a-f]{64}', native['cards'][r].get('mdcsum', '')) for r in ('a', 'b')),
            'Invalid native MDC checksum.')
    require(native['cards']['a']['mdcsum'] == expected_checksum, 'Retained source A compatibility changed.')
    if matching:
        require(native['cards']['b']['mdcsum'] == expected_checksum and normalized_card(cards['a']) == normalized_card(cards['b']),
                'Repaired workers do not advertise matching native model cards; no checksum bypass allowed.')


def parent_guard(plan):
    parent = Path(plan['parent'])
    require(tree_hashes(parent) == plan['parent_sha256'], 'Original parent evidence changed.')
    require(tree_hashes(plan['parent_capture']) == plan['parent_capture_sha256'], 'Original failed capture changed.')
    lease = Path(plan['lease']) / 'owner.json'
    require(lease.is_file() and ui.digest(lease) == plan['lease_owner_sha256'], 'Owning parent lease changed or disappeared.')
    owner = read(lease)
    require(owner.get('agent') == base.OWNER and Path(owner.get('run', '')).resolve() == parent.resolve(),
            'The original parent no longer owns this reservation.')
    for name, expected in plan['source_sha256'].items():
        require(ui.digest(ui.ROOT / name) == expected, 'Frozen prepared adapter dependency changed: ' + name)


def exec_json(run, pod, program, payload, *, overlay=False):
    args = ['exec', '-i', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'env', 'PYTHONDONTWRITEBYTECODE=1']
    if overlay:
        args += ['PYTHONPATH=/tmp/kvcr-guard-candidate/installed']
    result = run.k(*args, 'python3', '-B', '-c', program, input_text=json.dumps(payload), timeout=150)
    rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    require(len(rows) == 1, 'CPU diagnostic did not return exactly one JSON record.')
    return rows[0]


def owner_chain(run, pod, graph):
    chain, current = [], pod
    allowed = {'PodClique', 'PodCliqueSet', 'PodCliqueScalingGroup', 'DynamoGraphDeployment'}
    for _ in range(5):
        owners = [o for o in current['metadata'].get('ownerReferences', []) if o.get('controller')]
        require(len(owners) == 1 and owners[0]['kind'] in allowed, 'Unexpected Grove/DGD owner chain.')
        owner = owners[0]
        obj = run.get('get', owner['kind'], owner['name'], '-n', run.ns)
        require(obj['metadata']['uid'] == owner['uid'] and obj['metadata']['namespace'] == run.ns,
                'Stale or foreign Grove owner reference.')
        chain.append(obj)
        if owner['kind'] == 'DynamoGraphDeployment':
            require(obj['metadata']['uid'] == graph['metadata']['uid'], 'Pod belongs to a different DGD.')
            return chain
        current = obj
    raise ValueError('Grove owner chain did not reach the owning DGD.')


def snapshot(run, plan, label, *, replace_b, replace_frontend, two_workers, bound=None):
    parent_guard(plan)
    folder = run.path / label
    folder.mkdir(exist_ok=False)
    namespace = plan['namespace']
    pods = role_pods(run.get('get', 'pods', '-n', namespace, '-l', 'workshop-kvcr-guard=true')['items'], namespace)
    check_pod_transition(plan['original_pods'], pods, replace_b=replace_b, replace_frontend=replace_frontend)
    if bound:
        require({r: signature(p) for r, p in pods.items()} == bound['pod_signatures'], 'Post-repair bound worker/frontend identity changed.')
    graph = run.get('get', 'dgd', plan['graph']['metadata']['name'], '-n', namespace)
    require(graph['metadata']['uid'] == plan['graph']['metadata']['uid'] and graph['spec'] == plan['graph']['spec'],
            'Owning DGD identity, replica count or GPU UUID policy changed.')
    chains = {r: owner_chain(run, p, graph) for r, p in pods.items()}
    claims = run.get('get', 'resourceclaims', '-n', namespace)['items']
    slices = run.get('get', 'resourceslices')['items']
    devices = {(s['spec']['pool']['name'], d['name']): d['attributes']['uuid']['string']
               for s in slices if s['spec']['driver'] == 'gpu.nvidia.com' for d in s['spec'].get('devices', [])}
    assigned = {}
    geometry = {}
    for role in ('a', 'b'):
        pod = pods[role]
        found = [c for c in claims if any(o.get('kind') == 'Pod' and o.get('uid') == pod['metadata']['uid']
                                        for o in c['metadata'].get('ownerReferences', []))]
        require(len(found) == 1, 'Need exactly one GPU claim owned by the current worker Pod.')
        claim = found[0]
        results = claim['status']['allocation']['devices']['results']
        require(len(results) == 2 and sorted(devices[(v['pool'], v['device'])] for v in results) ==
                sorted(plan['placement'][role]['gpu_uuids']), 'Actual GPU claim differs from the original UUID pair.')
        if role == 'a':
            require(claim['metadata']['uid'] == plan['original_claims'][role]['metadata']['uid'], 'Source A GPU claim changed.')
        elif replace_b:
            require(claim['metadata']['uid'] != plan['original_claims'][role]['metadata']['uid'], 'Replacement B retained an old claim UID.')
        assigned[role] = claim
        log = run.k('logs', pod['metadata']['name'], '-n', namespace, '-c', 'main', '--timestamps=true', '--limit-bytes=10000000').stdout
        (folder / (role + '-main.log')).write_text(log)
        geometry[role] = base.runtime_geometry(log)
        require(geometry[role] == plan['geometry'][role], 'Live page/context geometry changed.')
    if replace_b:
        require(not any(c['metadata']['uid'] == plan['original_claims']['b']['metadata']['uid'] for c in claims),
                'Old B GPU claim has not finished cleanup.')
    metadata = run.get('get', 'dynamoworkermetadatas', '-n', namespace)
    cards, ids = worker_cards(metadata, pods)
    require(ids['a'] == plan['original_worker_ids']['a'], 'Retained source A endpoint changed.')
    require((ids['b'] != plan['original_worker_ids']['b']) == replace_b, 'Receiver endpoint identity does not match its declared replacement.')
    require(cards['a'] == plan['original_cards']['a'], 'Retained A advertised card changed.')
    if not replace_b:
        require(cards['b'] == plan['original_cards']['b'], 'Original B metadata changed; the diagnosed refresh is no longer current.')
    native = exec_json(run, pods['frontend'], NATIVE_CHECKSUM_PROGRAM, cards, overlay=True)
    check_native_cards(cards, native, plan['expected_mdcsum'], matching=replace_b)
    readiness = None
    if two_workers:
        readiness = exec_json(run, pods['frontend'], READINESS_PROGRAM, {'model': plan['model']})
        readiness_two_workers(readiness, plan['dynamo_namespace'])
    require(bound is None or ids == bound['worker_ids'], 'Bound generate endpoint identity changed.')
    result = {'status': 'passed', 'completed_at': ui.now(), 'pods': pods, 'pod_signatures': {r: signature(p) for r, p in pods.items()},
              'graph': graph, 'owner_chains': chains, 'claims': assigned, 'cards': cards, 'native_checksums': native,
              'worker_ids': ids, 'geometry': geometry, 'frontend_readiness': readiness,
              'replace_b': replace_b, 'replace_frontend': replace_frontend, 'two_workers_admitted': two_workers}
    write(folder / 'snapshot.json', result)
    parent_guard(plan)
    return result


def comparable_inventory(value):
    require(value.get('status') == 'passed' and bool(value.get('nonweight_files')), 'Missing current cached-asset inventory.')
    return {n: {k: v[k] for k in ('bytes', 'sha256')} for n, v in value['nonweight_files'].items()}


def validate_assets(folder):
    folder = Path(folder)
    terminal = read(folder / 'terminal.json')
    require(terminal.get('status') == 'read_only_diagnostic_completed' and terminal.get('current_cached_assets_match') is True and
            terminal.get('advertised_mdcsums_match') is False and terminal.get('original_parent_and_capture_unchanged') is True and
            terminal.get('workers_and_DGD_unchanged') is True and terminal.get('frontend_status') == 200,
            'Conditional replacement requires a completed, unchanged-parent, matching-files diagnostic.')
    counts = terminal.get('frontend_admitted_aggregated_counts', {})
    require(len(counts) == 1 and list(counts.values()) == [1], 'Expected the diagnosed one-worker admission before refresh.')
    a, b = (comparable_inventory(read(folder / (role + '-cached-assets.json'))) for role in ('a', 'b'))
    require(a == b, 'Actual cached assets still differ; do not refresh a worker.')
    require(terminal['current_asset_count'] == {'a': len(a), 'b': len(b)}, 'Diagnostic summary and actual asset counts disagree.')
    checksums = read(folder / 'native-mdcsum.json')
    require(checksums.get('cards') == terminal.get('advertised_mdcsum'), 'Diagnostic checksum summary disagrees with the native receipt.')
    return terminal, a, checksums


def plan_refresh(parent, capture, assets, output):
    parent, capture, assets, output = map(lambda p: Path(p).resolve(), (parent, capture, assets, output))
    separate_output(output, parent, capture, assets)
    terminal, inventory, checksums = validate_assets(assets)
    demo = read(parent / 'demo.json')
    require(demo.get('kvcr_profile') == base.LEGACY_PROFILE and demo.get('prepared') is True and not demo.get('rehearsal') and
            demo.get('source_request_started_at') and not demo.get('target_request_started_at'), 'Unexpected owning parent lifecycle/profile.')
    require(read(parent / 'source/response.json')['status'] == 400 and capture.is_dir(), 'Original failed source and capture must be retained.')
    pods = {r: read(assets / ('before-' + r + '-pod.json')) for r in ('a', 'b', 'frontend')}
    original = role_pods(read(parent / 'ready-pods.json')['items'], demo['namespace'])
    require({r: signature(p) for r, p in pods.items()} == {r: signature(p) for r, p in original.items()},
            'Read-only assets diagnosis does not belong to the exact original parent Pods.')
    graph = read(assets / 'before-dgd.json')
    claims = read(assets / 'before-claims.json')['items']
    owned = {r: next(c for c in claims if any(o.get('uid') == pods[r]['metadata']['uid'] and o.get('kind') == 'Pod'
                                          for o in c['metadata'].get('ownerReferences', []))) for r in ('a', 'b')}
    cards, ids = worker_cards(read(assets / 'current-metadata.json'), pods)
    require(ids == read(parent / 'worker-ids.json'), 'Read-only assets diagnosis has different original generate endpoints.')
    require(normalized_card({k: v for k, v in cards['a'].items() if k != 'extra_files'}) ==
            normalized_card({k: v for k, v in cards['b'].items() if k != 'extra_files'}),
            'Diagnosis involves differences beyond advertised extra files; do not refresh automatically.')
    advertised = set()
    def gather(value):
        if isinstance(value, list):
            for v in value: gather(v)
        elif isinstance(value, dict):
            if 'checksum' in value and 'path' in value:
                advertised.add(Path(urlsplit(value['path']).path).name)
            for v in value.values(): gather(v)
    gather(cards['a'])
    require(advertised <= set(inventory), 'Expected source metadata is absent from the settled cache.')
    unexpected = set(inventory) - advertised
    require(all(n.lower().startswith('readme') for n in unexpected), 'Current cache contains unadvertised assets beyond README; expected fresh registration is uncertain.')
    lease = Path(demo['lease']) / 'owner.json'
    plan = {'schema': 1, 'kind': 'kvcr-supported-refresh-v1', 'created_at': ui.now(), 'parent': str(parent),
            'parent_sha256': tree_hashes(parent), 'parent_capture': str(capture), 'parent_capture_sha256': tree_hashes(capture),
            'lease': demo['lease'], 'lease_owner_sha256': ui.digest(lease), 'source_sha256': dependency_hashes(),
            'namespace': demo['namespace'], 'graph': graph, 'placement': demo['placement'],
            'model': demo['model'], 'revision': read(parent / 'model-lock.json')['revision'],
            'original_pods': pods, 'original_claims': owned, 'original_cards': cards, 'original_worker_ids': ids,
            'geometry': read(parent / 'prompt-preflight.json')['geometry_by_worker'],
            'expected_mdcsum': checksums['cards']['a']['mdcsum'], 'dynamo_namespace': next(iter(terminal['frontend_admitted_aggregated_counts'])),
            'settled_inventory': inventory, 'assets_directory': str(assets), 'assets_sha256': tree_hashes(assets),
            'scope': 'One UID-guarded graceful B/frontend replacement; A, DGD and UUID policy retained. No metadata/registry patch, checksum bypass or HTTP generation.'}
    parent_guard(plan)
    output.mkdir()
    write(output / 'plan.json', plan)
    return plan


class ApiProxy:
    """Own a loopback-only kubectl proxy for UID-preconditioned Kubernetes DELETE."""
    def __init__(self, run):
        self.run, self.process, self.log = run, None, None

    def __enter__(self):
        path = self.run.path / 'delete-api-proxy.log'
        self.log = path.open('x')
        self.process = subprocess.Popen(self.run.kbase + ['proxy', '--address=127.0.0.1', '--port=0'],
                                        stdout=self.log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                require(self.process.poll() is None, 'Owned API proxy exited before deletion.')
                match = re.search(r'Starting to serve on 127\.0\.0\.1:([0-9]+)', path.read_text())
                if match:
                    return 'http://127.0.0.1:' + match[1]
                time.sleep(0.2)
            raise TimeoutError('Owned API proxy did not bind.')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *unused):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()


def delete_pod_once(run, plan, role, current, api_base):
    parent_guard(plan)
    require(role in ('b', 'frontend'), 'Only B and frontend may be replaced.')
    expected = plan['original_pods'][role]
    require(current['metadata']['name'] == expected['metadata']['name'] and signature(current) == signature(expected),
            'Delete candidate is not the declared original Pod.')
    actual = run.get('get', 'pod', current['metadata']['name'], '-n', run.ns)
    require(signature(actual) == signature(expected) and actual['metadata'].get('ownerReferences') == expected['metadata'].get('ownerReferences'),
            'Pod identity changed immediately before the guarded delete.')
    body = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'gracePeriodSeconds': expected['spec'].get('terminationGracePeriodSeconds', 45),
            'propagationPolicy': 'Background', 'preconditions': {'uid': expected['metadata']['uid']}}
    path = '/api/v1/namespaces/' + quote(run.ns, safe='') + '/pods/' + quote(expected['metadata']['name'], safe='')
    write(run.path / ('delete-' + role + '-intent.json'), {'at': ui.now(), 'method': 'DELETE', 'path': path, 'body': body})
    try:
        with urlopen(Request(api_base + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='DELETE'), timeout=45) as response:
            value = json.load(response)
            write(run.path / ('delete-' + role + '-response.json'), {'status': response.status, 'body': value})
            require(response.status in (200, 202), 'Guarded delete was not accepted.')
    except BaseException as error:
        write(run.path / ('delete-' + role + '-failure.json'), {'at': ui.now(), 'error': type(error).__name__ + ': ' + str(error), 'retried': False})
        raise


def wait_replacement(run, plan, role, *, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        parent_guard(plan)
        items = run.get('get', 'pods', '-n', run.ns, '-l', 'workshop-kvcr-guard=true')['items']
        a = [p for p in items if p['metadata']['labels'].get('kvcr-peer') == 'a']
        require(len(a) == 1 and signature(a[0]) == signature(plan['original_pods']['a']), 'Source A changed during replacement.')
        selected = [p for p in items if (p['metadata']['labels'].get('kvcr-peer', 'frontend') == role)]
        old_uid = plan['original_pods'][role]['metadata']['uid']
        if len(selected) == 1 and selected[0]['metadata']['uid'] != old_uid:
            support.healthy(selected)
            if any(v['type'] == 'Ready' and v['status'] == 'True' for v in selected[0].get('status', {}).get('conditions', [])):
                return selected[0]
        print('Waiting for the declared ' + role + ' replacement; source A is retained.', flush=True)
        time.sleep(8)
    raise TimeoutError('Declared ' + role + ' replacement did not become Ready; no automatic repeat.')


def _refresh(path, plan, timeout):
    parent_guard(plan)
    require(tree_hashes(plan['assets_directory']) == plan['assets_sha256'], 'Read-only asset qualification changed.')
    validate_assets(plan['assets_directory'])
    write(path / 'started.json', {'at': ui.now(), 'scope': plan['scope']})
    run = Run(path)
    run.ns = run.state['namespace'] = plan['namespace']
    run.save()
    before = snapshot(run, plan, 'before-refresh', replace_b=False, replace_frontend=False, two_workers=False)
    for role in ('a', 'b'):
        current = exec_json(run, before['pods'][role], ASSET_PROGRAM, {'model': plan['model'], 'revision': plan['revision']})
        write(path / ('pre-delete-' + role + '-assets.json'), current)
        require(comparable_inventory(current) == plan['settled_inventory'], 'Cached assets changed before replacement; no Pod deleted.')
    with ApiProxy(run) as api_base:
        delete_pod_once(run, plan, 'b', before['pods']['b'], api_base)
        wait_replacement(run, plan, 'b', timeout=timeout)
        after_b = snapshot(run, plan, 'after-b', replace_b=True, replace_frontend=False, two_workers=False)
        delete_pod_once(run, plan, 'frontend', before['pods']['frontend'], api_base)
        wait_replacement(run, plan, 'frontend', timeout=min(timeout, 900))
    after = snapshot(run, plan, 'after-refresh', replace_b=True, replace_frontend=True, two_workers=True)
    require(signature(after['pods']['b']) == signature(after_b['pods']['b']), 'B changed while replacing frontend.')
    parent_guard(plan)
    proof = {'schema': 1, 'status': 'passed', 'kind': 'kvcr-supported-refresh-proof-v1', 'completed_at': ui.now(),
             'plan': str(path / 'plan.json'), 'plan_sha256': ui.digest(path / 'plan.json'),
             'qualified_snapshot': str(path / 'after-refresh/snapshot.json'),
             'qualified_snapshot_sha256': ui.digest(path / 'after-refresh/snapshot.json'),
             'source_retained': True, 'replaced_roles': ['b', 'frontend'], 'two_workers_admitted': True,
             'generation_requests': 0, 'metadata_patches': 0, 'registry_changes': 0, 'checksum_bypassed': False,
             'evidence_sha256': tree_hashes(path), 'scope': plan['scope']}
    write(path / 'repair.json', proof)
    return proof


def refresh(path, timeout=2700):
    require(type(timeout) is int and timeout > 0, 'Refresh timeout must be a positive integer before any live action.')
    path = Path(path).resolve()
    plan = read(path / 'plan.json')
    require(plan.get('kind') == 'kvcr-supported-refresh-v1', 'Wrong conditional-refresh plan.')
    for protected in (Path(plan['parent']).resolve(), Path(plan['parent_capture']).resolve()):
        require(path != protected and protected not in path.parents, 'Refresh cannot write into protected original evidence.')
    try:
        return _refresh(path, plan, timeout)
    except BaseException as error:
        write(path / ('failure-' + str(time.time_ns()) + '.json'),
              {'status': 'failed', 'at': ui.now(), 'error': type(error).__name__ + ': ' + str(error),
               'scope': 'Single attempt stopped; no automatic request, deletion replay, cleanup or parent evidence changes.'})
        raise


def repair_binding(path):
    proof_path = Path(path).resolve()
    proof = read(proof_path)
    require(proof.get('kind') == 'kvcr-supported-refresh-proof-v1' and proof.get('status') == 'passed' and
            proof.get('source_retained') is True and proof.get('replaced_roles') == ['b', 'frontend'] and
            proof.get('two_workers_admitted') is True and all(type(proof.get(k)) is int and proof[k] == 0
            for k in ('generation_requests', 'metadata_patches', 'registry_changes')) and proof.get('checksum_bypassed') is False,
            'Need an explicit supported B/frontend repair proof; no undeclared replacement or bypass.')
    plan = read(proof['plan'])
    require(ui.digest(Path(proof['plan'])) == proof['plan_sha256'], 'Repair plan changed.')
    for name, expected in proof['evidence_sha256'].items():
        require(ui.digest(proof_path.parent / name) == expected, 'Repair evidence changed: ' + name)
    require(ui.digest(Path(proof['qualified_snapshot'])) == proof['qualified_snapshot_sha256'], 'Qualified repair snapshot changed.')
    selected = read(proof['qualified_snapshot'])
    check_pod_transition(plan['original_pods'], selected['pods'], replace_b=True, replace_frontend=True)
    require(selected['pod_signatures'] == {r: signature(p) for r, p in selected['pods'].items()}, 'Repair identity receipt disagrees with its Pods.')
    check_native_cards(selected['cards'], selected['native_checksums'], plan['expected_mdcsum'], matching=True)
    readiness_two_workers(selected['frontend_readiness'], plan['dynamo_namespace'])
    parent_guard(plan)
    return proof, plan, selected


def bind(repair, output):
    proof, plan, selected = repair_binding(repair)
    output = separate_output(output, plan['parent'], plan['parent_capture'], Path(repair).resolve().parent)
    output.mkdir()
    parent = Path(plan['parent'])
    previous = read(parent / 'demo.json')
    for name in SOURCE_NAMES:
        shutil.copyfile(parent / name, output / name)
    (output / 'prompt-preflight-tokenizer.py').write_text(base.TOKENIZER_PROGRAM)
    context = base.coding_prefix(uuid.uuid4().hex)
    require(context != (parent / 'shared-context.txt').read_text(), 'Child must use a fresh shared prefix.')
    (output / 'shared-context.txt').write_text(context)
    requests = {role: base.request_body(plan['model'], context + suffix)
                for role, suffix in (('source', base.SOURCE_SUFFIX), ('target', base.TARGET_SUFFIX))}
    for role, body in requests.items():
        write(output / (role + '-request.json'), body)
    write(output / 'prompt-preflight-input.json', {'model': plan['model'], 'revision': plan['revision'], 'requests': requests})
    write(output / 'ready-pods.json', {'items': list(selected['pods'].values())})
    write(output / 'worker-ids.json', selected['worker_ids'])
    write(output / 'timing.json', {'simulated': False, 'apply_to_observed_ready_seconds': None,
                                 'scope': 'Workers prepared offstage in the owning parent; one declared B/frontend refresh. No child startup timing measured.'})
    keep = ['schema', 'demo_kind', 'graph', 'namespace', 'model', 'prepared', 'fixture_functions',
            'guard_harness_sha256', 'placement', 'source_bundle', 'candidate', 'runtime_configmap',
            'lease', 'pod_selector', 'resource_kinds', 'resource_note', 'log_files']
    data = {k: copy.deepcopy(previous[k]) for k in keep}
    data.update(kvcr_profile=base.LEGACY_PROFILE, prepared_profile=PROFILE, rehearsal=False, created_at=ui.now(), step=0,
                prepared=True, ready_observed_at=selected['completed_at'], prepared_parent=plan['parent'],
                resource_note='Prepared offstage: retained A, explicitly refreshed B/frontend, two admitted workers.')
    static = copy.deepcopy(data)
    binding = {'schema': 1, 'profile': PROFILE, 'created_at': ui.now(), 'parent_plan': plan,
               'repair': str(Path(repair).resolve()), 'repair_sha256': ui.digest(Path(repair)),
               'qualified_snapshot': selected, 'bound_fields': static,
               'scope': 'Fresh HTTP/metrics/proof evidence only. Owning parent lease and original failed bytes remain unchanged.'}
    write(output / 'prepared-binding.json', binding)
    inputs = SOURCE_NAMES + ['shared-context.txt', 'source-request.json', 'target-request.json',
                            'prompt-preflight-input.json', 'prompt-preflight-tokenizer.py', 'prepared-binding.json',
                            'ready-pods.json', 'worker-ids.json', 'timing.json']
    data['inputs'] = {name: ui.digest(output / name) for name in inputs}
    write(output / 'demo.json', data)
    run = Run(output)
    run.ns = run.state['namespace'] = plan['namespace']
    run.state['model_lock'] = read(output / 'model-lock.json')
    run.state['prepared_parent'] = plan['parent']
    run.save()
    parent_guard(plan)
    return data


class PreparedKVCRDemo(base.KVCRDemo):
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        self.args = copy.copy(args)
        self.path = Path(args.run).resolve()
        self.file = self.path / 'demo.json'
        self.data = read(self.file)
        self.binding = read(self.path / 'prepared-binding.json')
        require(self.binding.get('profile') == PROFILE and self.data.get('prepared_profile') == PROFILE,
                'This entrypoint needs an explicit prepared-parent child binding.')
        require(args.action != 'cleanup', 'A bound child cannot clean retained resources. Use the owning parent: ' + self.data['prepared_parent'])
        self.check_inputs()
        self.run = Run(self.path)
        self.ns = self.data['namespace']
        require(self.run.ns == self.ns and self.run.state.get('model_lock') == read(self.path / 'model-lock.json'),
                'Child state no longer matches its bound namespace/model.')
        self.placement = base.validate_placement(self.data['placement'])
        self.lease = Path(self.data['lease'])
        self.forward, self.compact_output = None, True

    def check_inputs(self):
        for name, digest in self.data['inputs'].items():
            require(ui.digest(self.path / name) == digest, 'Frozen child input changed: ' + name)
        for key, value in self.binding['bound_fields'].items():
            if key != 'step':
                require(self.data.get(key) == value, 'Bound child resource field changed: ' + key)
        require(self.data.get('prepared') is True and self.data.get('ready_observed_at'), 'Bound resources cannot be redeployed or re-prepared.')
        parent_guard(self.binding['parent_plan'])
        require(ui.digest(Path(self.binding['repair'])) == self.binding['repair_sha256'], 'Declared repair proof changed.')

    def require_lease(self):
        self.check_inputs()
        # The reservation continues to name its original owner. Never instantiate
        # Run(parent), rewrite owner.json or acquire a second lease for this child.
        parent_guard(self.binding['parent_plan'])

    def check_identity(self):
        self.require_lease()
        selected = self.binding['qualified_snapshot']
        snapshot(self.run, self.binding['parent_plan'], 'admission-' + str(time.time_ns()),
                 replace_b=True, replace_frontend=True, two_workers=True, bound=selected)

    def prepare(self):
        self.check_identity()
        print('Using the explicitly bound, prepared parent workers; original failed evidence is retained.')

    def deploy(self):
        raise RuntimeError('A prepared child cannot deploy inherited resources.')

    def wait(self):
        raise RuntimeError('A prepared child cannot restart or adopt an unrecorded worker.')

    def native_gate(self, *unused):
        raise RuntimeError('GPU preparation belongs to the owning parent, not this evidence child.')

    def cpu_gate(self):
        raise RuntimeError('Runtime preparation belongs to the owning parent, not this evidence child.')

    def prepared_workers(self):
        self.require_primed()
        self.check_identity()
        self.ensure_prompt_preflight()
        print('Workers prepared offstage. Source A retained; B/frontend refresh recorded; two workers admitted.')
        print(ui.compact_resource_table(self.pods(), pods_only=True))

    def cleanup(self):
        raise RuntimeError('A bound child cannot clean retained resources. Use the owning parent: ' + self.data['prepared_parent'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan-refresh')
    for name in ('parent', 'capture', 'assets', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p = sub.add_parser('refresh')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=2700)
    p = sub.add_parser('bind')
    p.add_argument('--repair', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    sub.add_parser('hold')
    p = sub.add_parser('observe')
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--view', choices=['resources', 'logs'], default='resources')
    p.add_argument('--once', action='store_true')
    for action in ('run', 'prime', 'preview', 'cleanup'):
        p = sub.add_parser(action)
        p.add_argument('--run', type=Path, required=True)
        for name in ('plain', 'auto', 'detach'):
            p.add_argument('--' + name, action='store_true')
        p.add_argument('--port', type=int, default=18007)
        p.add_argument('--timeout', type=int, default=2700)
    args = parser.parse_args()
    if hasattr(args, 'port'):
        require(0 < args.port < 65536 and args.timeout > 0, 'Port must be 1..65535 and timeout must be positive.')
    if args.action == 'hold':
        while True: time.sleep(30)
    elif args.action == 'observe':
        support.observe(args.run.resolve(), args.view, args.once)
    elif args.action == 'plan-refresh':
        plan_refresh(args.parent, args.capture, args.assets, args.output)
    elif args.action == 'refresh':
        refresh(args.plan.parent, args.timeout)
    elif args.action == 'bind':
        bind(args.repair, args.run)
    else:
        args.rehearsal, args.preview = False, args.action == 'preview'
        demo = PreparedKVCRDemo(args)
        print('Child evidence: ' + str(demo.path), flush=True)
        if args.action == 'preview':
            demo.preview()
        elif args.action == 'prime':
            with ui.presenter_lock(demo.path): demo.prime()
        else:
            demo.require_primed()
            if args.plain:
                with ui.presenter_lock(demo.path): demo.guided()
            else:
                ui.tmux_layout(demo)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Prepared KVCR operation stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
