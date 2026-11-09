#!/usr/bin/env python3
"""Private-cluster qualification of the portable renderer; no calls in freeze.

The effective deployment differs from the portable bundle only in exact test
node/GPU fencing. Existing cached weights do not qualify a fresh download.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from testlib import Run
from demos.common.allocation import Allocation

LEASE = ROOT / '.local/workshop-take-home.gpu-lease'
OWNER = 'workshop-take-home-qualification'
NAME = 'coding-agent'


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'take-home' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


portable = module('take_home_live_renderer', 'render.py')
response_check = module('take_home_live_response', 'check-response.py')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def freeze(args):
    if args.run.exists():
        raise ValueError('Use a new qualification directory; old attempts are immutable.')
    allocation = json.loads(args.allocations.read_text())['allocations'][args.slot]
    uuids = allocation['gpu_uuids_by_node'][args.node]
    if len(uuids) != 2:
        raise ValueError('Exactly one two-GPU node slot is required.')
    run = Run(args.run)
    run.ns = 'dynamo-ft-takehome-' + hashlib.sha256(str(run.path).encode()).hexdigest()[:10]
    run.state['namespace'] = run.ns
    run.save()
    settings = argparse.Namespace(namespace=run.ns, name=NAME, cache_pvc='feature-cache',
        runtime_image=args.runtime_image, runtime_version=args.runtime_version,
        image_pull_secret=None, gpu_mode='dra', cache_subpath='feature-tests/20261015-super-vl-tp2',
        run_as_user=args.run_as_user)
    objects, request, lock = portable.render(settings)
    bundle = run.path / 'bundle'
    bundle.mkdir()
    for name, obj in objects.items():
        (bundle / name).write_text(yaml.safe_dump(obj, sort_keys=False))
    write(bundle / 'request.json', request)
    profile = {'model': lock['model'], 'revision': lock['revision'], 'namespace': run.ns,
        'runtime_image': args.runtime_image, 'runtime_version': args.runtime_version,
        'gpu_mode': 'dra', 'cache_subpath': settings.cache_subpath,
        'run_as_user': args.run_as_user,
        'scope': 'Generated portable bundle using pre-existing qualified cache; no fresh-download proof.'}
    write(bundle / 'profile.json', profile)
    exact = Allocation(ROOT, {'schema': 1, 'assignment_id': 'takehome-' + run.path.name,
        'lease': str(LEASE.relative_to(ROOT)), 'targets': {'intro': {'node': args.node, 'gpu_uuids': uuids}}})
    graph, claim = copy.deepcopy(objects['deployment.yaml']), copy.deepcopy(objects['gpu-claim-template.yaml'])
    exact.pin(graph, claim, 'intro')
    write(run.path / 'allocation.json', exact.value)
    for name, obj in [('effective-deployment.json', graph), ('effective-claim.json', claim)]:
        write(run.path / name, obj)
    (run.path / 'runtime-probe.py').write_bytes((ROOT / 'take-home/runtime-probe.py').read_bytes())
    spec = {'schema': 1, 'created_at': now(), 'namespace': run.ns, 'name': NAME,
        'runtime_image': args.runtime_image, 'runtime_version': args.runtime_version,
        'expected_dynamo_package_version': args.expected_dynamo_package_version,
        'run_as_user': args.run_as_user,
        'public_candidate': args.public_candidate, 'node': args.node, 'gpu_uuids': uuids,
        'allocations_sha256': sha(args.allocations), 'source_slot': args.slot,
        'sources': {str(p.relative_to(ROOT)): sha(p) for p in (
            Path(__file__).resolve(), ROOT / 'take-home/render.py', ROOT / 'take-home/runtime-probe.py',
            ROOT / 'take-home/check-response.py', ROOT / 'demos/common/runtime.py',
            ROOT / 'demos/common/allocation.py', ROOT / 'scripts/testlib.py',
            ROOT / 'scripts/storage_tests.py')},
        'inputs': {str(p.relative_to(run.path)): sha(p) for p in run.path.rglob('*')
                   if p.is_file() and p.name not in ('state.json', '.state.lock')},
        'test_overlay': 'Only exact node selector and DRA UUID selectors differ; portable workload/engine/image controls are unchanged.',
        'download_scope': 'Existing cached revision; generated CPU Job runs but a new network weight download is not established.'}
    write(run.path / 'qualification-spec.json', spec)
    run.state['takehome_spec_sha256'] = sha(run.path / 'qualification-spec.json')
    run.save()
    print(json.dumps({'status': 'frozen_offline', 'run': str(run.path), 'namespace': run.ns,
                      'public_candidate': args.public_candidate, 'gpu_uuids': uuids}), flush=True)


def load(path):
    run = Run(path)
    spec = json.loads((run.path / 'qualification-spec.json').read_text())
    if sha(run.path / 'qualification-spec.json') != run.state['takehome_spec_sha256'] or spec['namespace'] != run.ns:
        raise ValueError('Qualification spec or namespace changed.')
    for name, digest in spec['sources'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('Source changed after freeze: ' + name)
    for name, digest in spec['inputs'].items():
        if sha(run.path / name) != digest:
            raise ValueError('Input changed after freeze: ' + name)
    return run, spec


def owned(run, obj):
    if obj['metadata'].get('labels', {}).get('workshop-service') != NAME:
        raise ValueError('Unexpected resource owner: ' + obj['metadata']['name'])


def apply_file(run, path):
    run.k('apply', '-n', run.ns, '-f', str(path))


def require_namespace(run):
    expected = run.state.get('namespace_uid')
    if not expected:
        raise ValueError('Observed creating namespace UID is required; never adopt a namespace by name.')
    actual = run.get('get', 'namespace', run.ns)
    if (actual['metadata']['uid'] != expected or
            actual['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != run.state['owner']):
        raise ValueError('Namespace identity/ownership changed; refuse mutation or cleanup.')


def create_namespace(run):
    if run.state.get('namespace_uid'):
        raise ValueError('Namespace creation already recorded; inspect original attempt.')
    found = run.k('get', 'namespace', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        raise ValueError('Namespace already exists; never adopt a previous name.')
    if 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    obj = {'apiVersion': 'v1', 'kind': 'Namespace',
           'metadata': {'name': run.ns, 'labels': run.labels()}}
    created = json.loads(run.k('create', '-f', '-', '-o', 'json', input_text=json.dumps(obj)).stdout)
    run.state['namespace_uid'] = created['metadata']['uid']
    run.save()
    require_namespace(run)


def wait_pod(run, name, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pod = run.get('get', 'pod', name, '-n', run.ns)
        phase = pod.get('status', {}).get('phase')
        if phase in ('Succeeded', 'Failed'):
            return pod
        states = [c.get('state', {}).get('waiting', {}).get('reason')
                  for c in pod.get('status', {}).get('containerStatuses', [])]
        if any(x in ('ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError') for x in states):
            raise RuntimeError('Candidate Pod startup failed: ' + str(states))
        time.sleep(3)
    raise TimeoutError('CPU probe exceeded its observation budget.')


def cpu(run, spec):
    if run.state.get('cpu_probe_intent'):
        raise ValueError('CPU probe was already attempted; inspect it instead of replaying.')
    create_namespace(run)
    run.state['cpu_probe_intent'] = now()
    run.save()
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'take-home-runtime-probe',
        'namespace': run.ns, 'labels': portable.labels(NAME, 'runtime-probe')},
        'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'activeDeadlineSeconds': 900, 'nodeSelector': {'kubernetes.io/hostname': spec['node']},
            'containers': [{'name': 'probe', 'image': spec['runtime_image'],
                'imagePullPolicy': 'Always', 'command': ['python3', '-c', (run.path / 'runtime-probe.py').read_text()],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                        {'name': 'EXPECTED_DYNAMO_VERSION', 'value': spec['expected_dynamo_package_version']}],
                'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'memory': '8Gi'}}}]}}
    write(run.path / 'runtime-probe-pod.json', pod)
    apply_file(run, run.path / 'runtime-probe-pod.json')
    try:
        actual = wait_pod(run, pod['metadata']['name'], 900)
        write(run.path / 'runtime-probe-observed.json', actual)
        result = run.k('logs', pod['metadata']['name'], '-n', run.ns, check=False)
        (run.path / 'runtime-probe.log').write_text(result.stdout + result.stderr)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        statuses = actual['status']['containerStatuses']
        image = statuses[0]['imageID']
        if not image.endswith(spec['runtime_image'].split('@')[1]) or statuses[0].get('restartCount', 0):
            raise ValueError('Probe actual image/restart identity mismatch.')
        if actual['status']['phase'] != 'Succeeded' or report['status'] != 'passed':
            raise RuntimeError('Unmodified image CPU capability probe failed: ' + str(report['errors']))
        details = {key: value for key, value in report.items() if key != 'status'}
        run.result('takehome-runtime-cpu', 'passed', image_id=image, public_candidate=spec['public_candidate'], **details)
    finally:
        run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)


def prepare(run, spec):
    require_namespace(run)
    if run.state['checks'].get('takehome-runtime-cpu', {}).get('status') != 'passed':
        raise ValueError('Exact unmodified candidate CPU probe must pass first.')
    if run.state.get('download_job_intent'):
        raise ValueError('Cache Job already attempted; do not replay it.')
    from storage_tests import prepare as storage
    storage(run)
    # These are the actual portable files, not regenerated private substitutes.
    paths = sorted((run.path / 'bundle').glob('*.yaml'))
    for path in paths:
        for dry in ('client', 'server'):
            run.k('apply', '-n', run.ns, '--dry-run=' + dry, '-f', str(path))
    run.state['download_job_intent'] = now()
    run.save()
    path = run.path / 'bundle/download-job.yaml'
    apply_file(run, path)
    job = run.get('get', 'job', NAME + '-download', '-n', run.ns)
    owned(run, job)
    run.state['cache_job_uid'] = job['metadata']['uid']
    run.save()
    try:
        wait_cache_job(run, 900)
    finally:
        collect_cache_job(run)
    run.result('takehome-cache-job', 'passed', scope=spec['download_scope'])


def wait_cache_job(run, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = run.get('get', 'job', NAME + '-download', '-n', run.ns)
        owned(run, job)
        if job['metadata']['uid'] != run.state['cache_job_uid']:
            raise ValueError('Cache Job UID changed; refuse adoption.')
        conditions = job.get('status', {}).get('conditions', [])
        failure = next((c for c in conditions if c['type'] in ('Failed', 'FailureTarget') and c['status'] == 'True'), None)
        if failure:
            raise RuntimeError('Generated cache Job failed: ' + failure.get('reason', '') + ': ' + failure.get('message', ''))
        if any(c['type'] == 'Complete' and c['status'] == 'True' for c in conditions):
            return
        time.sleep(3)
    raise TimeoutError('Cache Job observation exceeded its bound; preserve attempt for inspection.')


def collect_cache_job(run):
    job = run.get('get', 'job', NAME + '-download', '-n', run.ns)
    write(run.path / 'cache-job-observed.json', job)
    if job['metadata']['uid'] != run.state['cache_job_uid']:
        raise ValueError('Cache Job identity changed before evidence collection.')
    pods = run.get('get', 'pods', '-n', run.ns, '-l', 'job-name=' + NAME + '-download')
    write(run.path / 'cache-job-pods.json', pods)
    for pod in pods['items']:
        refs = pod['metadata'].get('ownerReferences', [])
        if not any(r['kind'] == 'Job' and r['uid'] == run.state['cache_job_uid'] for r in refs):
            raise ValueError('Cache Pod does not belong to the exact Job.')
        log = run.k('logs', '-n', run.ns, pod['metadata']['name'], '--timestamps=true', check=False)
        (run.path / ('cache-pod-' + pod['metadata']['uid'] + '.log')).write_text(log.stdout + log.stderr)
    log = run.k('logs', '-n', run.ns, 'job/' + NAME + '-download', '--timestamps=true', check=False)
    (run.path / 'cache-job.log').write_text(log.stdout + log.stderr)


def require_lease(run):
    if not (LEASE / 'owner.json').exists() or json.loads((LEASE / 'owner.json').read_text()) != {
            'owner': OWNER, 'run': str(run.path)}:
        raise ValueError('This run does not own the take-home GPU reservation.')


def deploy(run, spec):
    require_namespace(run)
    if run.state['checks'].get('takehome-cache-job', {}).get('status') != 'passed':
        raise ValueError('Cache Job must pass before a GPU deployment.')
    if run.state.get('deployment_intent'):
        raise ValueError('Deployment already attempted; no automatic replay.')
    claims = run.get('get', 'resourceclaims', '-A')
    slices = run.get('get', 'resourceslices')
    physical = {(s['spec']['pool']['name'], d['name']): d['attributes']['uuid']['string']
                for s in slices['items'] if s['spec']['driver'] == 'gpu.nvidia.com' for d in s['spec']['devices']}
    busy = [physical.get((d['pool'], d['device'])) for c in claims['items']
            for d in c.get('status', {}).get('allocation', {}).get('devices', {}).get('results', [])]
    if set(spec['gpu_uuids']) & set(busy):
        raise ValueError('Reserved take-home GPU pair is already allocated.')
    LEASE.mkdir()
    write(LEASE / 'owner.json', {'owner': OWNER, 'run': str(run.path)})
    run.state['deployment_intent'] = now()
    run.save()
    apply_file(run, run.path / 'effective-claim.json')
    apply_file(run, run.path / 'effective-deployment.json')
    apply_file(run, run.path / 'bundle/frontend-service.yaml')
    graph = run.get('get', 'dgd', NAME, '-n', run.ns)
    owned(run, graph)
    run.state['dgd_uid'] = graph['metadata']['uid']
    run.save()
    print('GPU deployment submitted; no serving qualification yet.', flush=True)


def collect(run):
    pods = run.get('get', 'pods', '-n', run.ns, '-l', 'workshop-service=' + NAME)
    write(run.path / 'serving-pods.json', pods)
    for pod in pods['items']:
        for container in pod['spec']['containers']:
            log = run.k('logs', '-n', run.ns, pod['metadata']['name'], '-c', container['name'],
                        '--timestamps=true', check=False)
            (run.path / ('pod-' + pod['metadata']['uid'] + '-' + container['name'] + '.log')).write_text(log.stdout + log.stderr)
    return pods


def verify(run, spec, timeout, port):
    require_namespace(run)
    require_lease(run)
    allocation = Allocation(ROOT, json.loads((run.path / 'allocation.json').read_text()))
    forward = None
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            pods = collect(run)['items']
            selected = [p for p in pods if p['metadata']['labels'].get('workshop-role') in ('worker', 'frontend')]
            for pod in selected:
                for state in pod.get('status', {}).get('containerStatuses', []):
                    if state.get('restartCount', 0) or pod['status'].get('phase') == 'Failed':
                        raise RuntimeError('Serving Pod restarted or failed.')
                    if not state['imageID'].endswith(spec['runtime_image'].split('@')[1]):
                        raise ValueError('Serving image digest differs.')
            if len(selected) == 2 and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in p.get('status', {}).get('conditions', [])) for p in selected):
                break
            time.sleep(10)
        else:
            raise TimeoutError('Serving readiness timed out; evidence/lease retained.')
        worker = next(p for p in selected if p['metadata']['labels']['workshop-role'] == 'worker')
        claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
        if len(claims) != 1:
            raise ValueError('Expected exactly one worker GPU claim.')
        proof = allocation.verify(worker, claims[0], run.get('get', 'resourceslices'), 'intro')
        write(run.path / 'gpu-proof.json', proof)
        log = (run.path / 'port-forward.log').open('x')
        forward = subprocess.Popen(run.kbase + ['port-forward', '-n', run.ns, 'service/' + NAME + '-http',
                                               str(port) + ':8000'], stdout=log, stderr=subprocess.STDOUT)
        base = 'http://127.0.0.1:' + str(port)
        models = None
        expected = json.loads((run.path / 'bundle/profile.json').read_text())['model']
        for _ in range(60):
            if forward.poll() is not None:
                raise RuntimeError('Port-forward exited before model discovery.')
            try:
                with urllib.request.urlopen(base + '/v1/models', timeout=5) as response:
                    models = json.load(response)
                if expected in {x.get('id') for x in models.get('data', [])}:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise TimeoutError('Exact expected frontend model never appeared.')
        write(run.path / 'bundle/models.json', models)
        if run.state.get('request_intent'):
            raise ValueError('The coding request already started; do not replay.')
        run.state['request_intent'] = now()
        run.save()
        request = urllib.request.Request(base + '/v1/chat/completions',
            data=(run.path / 'bundle/request.json').read_bytes(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.load(response)
        write(run.path / 'bundle/response.json', value)
        profile = json.loads((run.path / 'bundle/profile.json').read_text())
        content = response_check.check(profile, models, value)
        print(content, flush=True)
        run.result('takehome-serving', 'passed', public_candidate=spec['public_candidate'],
            model=profile['model'], image=spec['runtime_image'], gpu_proof=proof,
            scope='Cached DRA deployment, exact GPU/image identity, model discovery and one normally completed coding response. No fresh download, performance or other-feature qualification.')
    finally:
        if forward:
            forward.terminate()
            forward.wait(timeout=15)
        collect(run)


def cleanup(run, spec):
    require_namespace(run)
    if run.state.get('deployment_intent'):
        require_lease(run)
    graph = run.k('get', 'dgd', NAME, '-n', run.ns, '-o', 'json', check=False)
    if graph.returncode == 0:
        obj = json.loads(graph.stdout)
        owned(run, obj)
        if obj['metadata']['uid'] != run.state.get('dgd_uid'):
            raise ValueError('DGD UID changed; refuse cleanup.')
        run.k('delete', 'dgd', NAME, '-n', run.ns, '--wait=true', '--timeout=120s', timeout=135)
    elif 'NotFound' not in graph.stderr:
        raise RuntimeError(graph.stderr)
    for kind, name in [('service', NAME + '-http'), ('job', NAME + '-download'),
                       ('pod', 'take-home-runtime-probe')]:
        found = run.k('get', kind, name, '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0:
            owned(run, json.loads(found.stdout))
            run.k('delete', kind, name, '-n', run.ns, '--wait=true', '--timeout=120s', timeout=135)
        elif 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
    for _ in range(40):
        if not run.get('get', 'pods', '-n', run.ns)['items'] and not run.get('get', 'resourceclaims', '-n', run.ns)['items']:
            break
        time.sleep(3)
    else:
        raise RuntimeError('Owned Pods/claims remain; reservation retained.')
    found = run.k('get', 'resourceclaimtemplate', NAME + '-gpus', '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
        run.k('delete', 'resourceclaimtemplate', NAME + '-gpus', '-n', run.ns)
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    if run.state.get('deployment_intent'):
        require_lease(run)
        (LEASE / 'owner.json').unlink()
        LEASE.rmdir()
    run.result('takehome-cleanup', 'passed', scope='Owned DGD/Service/Job/Pods/claims/template gone; namespace/PV/PVC/cache/evidence retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'cpu', 'prepare', 'deploy', 'verify', 'cleanup'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--runtime-image')
    parser.add_argument('--runtime-version')
    parser.add_argument('--expected-dynamo-package-version',
                        help='Exact installed ai-dynamo/runtime version; distinct from the CRD-compatible X.Y.Z override.')
    parser.add_argument('--public-candidate', action='store_true')
    parser.add_argument('--run-as-user', type=int, help='Explicit common UID; qualification of a reused root-owned cache uses 0.')
    parser.add_argument('--allocations', type=Path, default=ROOT / 'reports/overnight-2026-11-04/allocations.json')
    parser.add_argument('--slot', default='migration')
    parser.add_argument('--node', default='kubecon-nke-site-cp-0942')
    parser.add_argument('--timeout', type=int, default=2700)
    parser.add_argument('--port', type=int, default=18116)
    args = parser.parse_args()
    if args.action == 'freeze':
        if not args.runtime_image or not args.runtime_version or not args.expected_dynamo_package_version:
            parser.error('freeze requires explicit image, operator-compatible version and exact expected Dynamo package version')
        freeze(args)
    else:
        run, spec = load(args.run)
        if args.action == 'verify':
            verify(run, spec, args.timeout, args.port)
        else:
            globals()[args.action](run, spec)


if __name__ == '__main__':
    main()
