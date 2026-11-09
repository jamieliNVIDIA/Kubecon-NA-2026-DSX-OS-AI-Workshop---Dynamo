#!/usr/bin/env python3
"""Native Dynamo Snapshot DGD and real restored-worker verification."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import time
import yaml
from serving_tests import frontend, lock_model, model_cache_home, worker_args, worker_resources, status
from shadow_failover_tests import completion
from testlib import ROOT, Run

GRAPH = 'ft-snapshot'
COMPONENT = 'VllmSnapshotWorker'


def render(run):
    lock = lock_model(run)
    source = ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/agg-h100-dspark-kv-router/deploy.yaml'
    graph = copy.deepcopy(next(o for o in yaml.safe_load_all(source.read_text()) if o and o['kind'] == 'DynamoGraphDeployment'))
    graph['metadata'] = {'name': GRAPH, 'namespace': run.ns, 'labels': run.labels(),
                         'annotations': {'nvidia.com/enable-grove': 'false'}}
    for component in graph['spec']['components']:
        component['replicas'] = 1
        component['runtimeVersionOverride'] = lock.get('runtime_version_override', '1.5.1')
        spec = component['podTemplate']['spec']
        spec.pop('imagePullSecrets', None)
        if lock.get('image_pull_secret'):
            spec['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
        spec.pop('affinity', None)
        spec['runtimeClassName'] = 'nvidia'
        spec['nodeSelector'] = {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'}
        spec['volumes'] = [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                           {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}}]
        # Deployment/ReplicaSet templates reject Pod activeDeadlineSeconds.
        # The bounded verifier and explicit DGD cleanup own this test's lifetime.
        spec.pop('activeDeadlineSeconds', None)
        component['podTemplate'].setdefault('metadata', {}).setdefault('labels', {}).update(run.labels())
        main = spec['containers'][0]
        main['image'] = lock['runtime_image']
        main['env'] = [{'name': k, 'value': v} for k, v in {
            'HF_HOME': model_cache_home(run), 'HF_HUB_OFFLINE': '1', 'HF_MODULES_CACHE': '/tmp/hf_modules',
            'VLLM_CACHE_ROOT': '/tmp/vllm', 'TRITON_CACHE_DIR': '/tmp/triton',
            'NCCL_IB_DISABLE': '1', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT': '180'}.items()]
        main['volumeMounts'] = [{'name': 'cache', 'mountPath': '/model-cache'}, {'name': 'shm', 'mountPath': '/dev/shm'}]
        if component['type'] == 'frontend':
            main['command'] = ['python3', '-m', 'dynamo.frontend']
            main['args'] = ['--router-mode', 'round-robin', '--trust-remote-code']
            main['resources'] = {'requests': {'cpu': '1', 'memory': '4Gi'}, 'limits': {'memory': '8Gi'}}
            if lock.get('common_runtime'):
                main['env'].append({'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'})
        else:
            component['name'] = COMPONENT
            component['sharedMemorySize'] = '16Gi'
            component['experimental'] = {'checkpoint': {'enabled': True, 'startupPolicy': 'WaitForCheckpoint', 'deletionPolicy': 'Retain'}}
            main['command'] = ['python3', '-m', 'dynamo.vllm']
            if lock.get('snapshot_launch_job'):
                main['command'] = ['/bin/sh', '/snapshot-bootstrap/entrypoint.sh', 'python3', '-m', 'dynamo.vllm']
                spec['volumes'].append({'name': 'snapshot-bootstrap', 'configMap': {
                    'name': 'snapshot-launch-bootstrap', 'defaultMode': 365}})
                main['volumeMounts'].append({'name': 'snapshot-bootstrap', 'mountPath': '/snapshot-bootstrap', 'readOnly': True})
            main['args'] = worker_args(lock['model'], lock['revision'], 'agg', tp=lock.get('tensor_parallel_size', 1))
            if lock.get('snapshot_eager'):
                main['args'].append('--enforce-eager')
            # A functionality capture needs a small KV pool, not the serving reserve.
            main['args'][main['args'].index('--gpu-memory-utilization') + 1] = '0.65'
            index = main['args'].index('--kv-events-config')
            del main['args'][index:index + 2]
            main['resources'] = worker_resources(lock)
            if lock.get('snapshot_legacy_ipc'):
                main['env'] += [{'name': k, 'value': '0'} for k in
                                ('NCCL_CUMEM_ENABLE', 'NCCL_CUMEM_HOST_ENABLE', 'NCCL_NVLS_ENABLE')]
            spec.setdefault('securityContext', {})['seccompProfile'] = {'type': 'Localhost', 'localhostProfile': 'profiles/block-iouring.json'}
    directory = ROOT / 'configs/dgd' / lock.get('manifest_directory', 'common-runtime' if lock.get('common_runtime') else '')
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'nemotron-snapshot.yaml'
    run.write_manifest(destination, [graph])
    (run.path / 'snapshot-dgd.json').write_text(json.dumps(graph, indent=2) + '\n')
    run.state.setdefault('graphs', {})['snapshot'] = {'name': GRAPH, 'manifest': str(destination)}
    run.save()
    return graph


def deploy(run):
    run.command([sys.executable, str(ROOT / 'scripts/snapshot_preflight.py'), '--run', str(run.path)])
    check = json.loads((run.path / 'state.json').read_text())['checks']['snapshot-preflight']
    if check['missing']:
        raise RuntimeError('Snapshot infrastructure absent; no DGD applied')
    for kind, name in (('deployment', 'dynamo-platform-snapshot-operator'), ('daemonset', 'dynamo-platform-snapshot-agent')):
        run.k('rollout', 'status', kind + '/' + name, '-n', 'dynamo-system', '--timeout=120s', timeout=135)
    if run.state.get('checks', {}).get('snapshot-runtime-preparation', {}).get('status') != 'passed':
        raise ValueError('Run and pass the exact-model runtime preparation check first')
    if lock_model(run).get('snapshot_launch_job') and run.state.get('checks', {}).get('snapshot-workload-launch', {}).get('status') != 'passed':
        raise ValueError('Pass the workload launch bootstrap probe before capture')
    run.apply([render(run)])
    run.result('snapshot-deployment', 'created', name=GRAPH, physical_gpus=lock_model(run).get('tensor_parallel_size', 1))


def verify(run, observer=None):
    capture_timeout = 3600 if lock_model(run).get('tensor_parallel_size', 1) > 1 else 1800
    deadline = time.monotonic() + capture_timeout
    last = None
    next_observation = time.monotonic()
    while time.monotonic() < deadline:
        graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
        if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('DGD is not owned')
        checkpoint = graph.get('status', {}).get('checkpoints', {}).get(COMPONENT, {})
        checkpoint_name = checkpoint.get('checkpointName')
        if observer is not None and time.monotonic() >= next_observation:
            observer(run)
            next_observation = time.monotonic() + 60
        if checkpoint_name:
            job = run.get('get', 'snapshotjob', checkpoint_name, '-n', run.ns)
            conditions = job.get('status', {}).get('conditions', [])
            if any(c['type'] == 'Failed' and c['status'] == 'True' for c in conditions):
                (run.path / 'snapshot-capture-failure.json').write_text(json.dumps(job, indent=2))
                raise RuntimeError(f'Snapshot capture failed: {conditions}')
            stage = [(c['type'], c['status'], c.get('reason')) for c in conditions]
            if stage != last:
                print(json.dumps({'capture': checkpoint_name, 'conditions': stage}), flush=True)
                last = stage
        if checkpoint.get('ready') and checkpoint.get('checkpointName'):
            break
        time.sleep(5)
    else:
        raise TimeoutError(f'No captured artifact ready within {capture_timeout}s')
    name = checkpoint['checkpointName']
    snapshot = run.get('get', 'podsnapshot', name, '-n', run.ns)
    (run.path / 'snapshot-artifact.json').write_text(json.dumps(snapshot, indent=2))
    restore_timeout = 1800 if lock_model(run).get('tensor_parallel_size', 1) > 1 else 600
    run.k('wait', '--for=condition=Ready', 'dgd/' + GRAPH, '-n', run.ns,
          f'--timeout={restore_timeout}s', timeout=restore_timeout + 20)
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    workers = [p for p in pods if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == GRAPH
               and p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component') == COMPONENT
               and 'nvidia.com/snapshot-job' not in p['metadata'].get('labels', {})]
    if len(workers) != 1:
        raise RuntimeError('Expected exactly one serving worker, excluding the capture Pod')
    pod = workers[0]
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    source_uid = content['spec']['source']['podRef']['uid']
    if pod['metadata']['uid'] == source_uid:
        raise RuntimeError('Serving worker has the capture Pod UID; a new-Pod restore is required')
    if pod['metadata'].get('annotations', {}).get('nvidia.com/restore-from') != name:
        raise RuntimeError('Serving worker does not reference the captured artifact')
    if not any(c['type'] == 'nvidia.com/Restored' and c['status'] == 'True' for c in pod['status'].get('conditions', [])):
        raise RuntimeError('Serving worker lacks nvidia.com/Restored=True')
    lock = lock_model(run)
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    image_id = next(c['imageID'] for c in pod['status']['containerStatuses'] if c['name'] == 'main')
    if image_id.split('@')[-1] != lock['runtime_image'].split('@')[-1]:
        raise RuntimeError('Restored worker image digest differs from the frozen input')
    if lock.get('gpu_allocation') == 'dra':
        from gpu_claims import verify_allocation
        claim = verify_allocation(run, pod, main, lock.get('tensor_parallel_size', 1))
        (run.path / 'snapshot-restored-claim.json').write_text(json.dumps(claim, indent=2))
    (run.path / 'snapshot-restored-pod.json').write_text(json.dumps(pod, indent=2))
    with frontend(run, 'snapshot') as base:
        response = completion(base, lock_model(run)['model'], timeout=180)
    (run.path / 'snapshot-restored-inference.json').write_text(json.dumps(response, indent=2))
    def elapsed(start, end):
        return (dt.datetime.fromisoformat(end.replace('Z', '+00:00')) -
                dt.datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds()
    captured_at = next((c['lastTransitionTime'] for c in snapshot.get('status', {}).get('conditions', [])
                        if c['type'] == 'Ready' and c['status'] == 'True'), None)
    restored_at = next(c['lastTransitionTime'] for c in pod['status']['conditions'] if c['type'] == 'nvidia.com/Restored')
    run.result('snapshot-restore', 'passed', artifact=name, restored_pod=pod['metadata']['name'],
               pod_uid=pod['metadata']['uid'], node=pod['spec']['nodeName'], worker=response['worker'],
               source_pod_uid=source_uid,
               capture_resource_creation_to_ready_seconds=elapsed(snapshot['metadata']['creationTimestamp'], captured_at) if captured_at else None,
               restored_pod_creation_to_restored_condition_seconds=elapsed(pod['metadata']['creationTimestamp'], restored_at),
               model=run.state['model_lock']['model'], tensor_parallel_size=run.state['model_lock'].get('tensor_parallel_size', 1),
               scope='Native Dynamo same-node capture/restore and correct inference at the locked TP size')


def cleanup(run):
    found = run.k('get', 'dgd', GRAPH, '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        graph = json.loads(found.stdout)
        if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('DGD is not owned')
        run.k('delete', 'dgd', GRAPH, '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    selector = 'nvidia.com/dynamo-graph-deployment-name=' + GRAPH
    pods = run.get('get', 'pods', '-n', run.ns, '-l', selector)['items']
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Refusing to wait on an unowned graph Pod')
        run.k('wait', '--for=delete', 'pod/' + pod['metadata']['name'], '-n', run.ns,
              '--timeout=150s', timeout=165)
    run.result('snapshot-cleanup', 'passed', scope='Owned DGD and workload Pods removed; Retain artifact kept for inspection')


def reset(run):
    graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
    if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('DGD is not owned')
    checkpoint_names = {c['checkpointName'] for c in graph.get('status', {}).get('checkpoints', {}).values()
                        if c.get('checkpointName')}
    jobs = run.get('get', 'snapshotjobs', '-n', run.ns)['items']
    owned = [j for j in jobs if j['metadata']['name'] in checkpoint_names
             and j['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == GRAPH]
    source_jobs = run.get('get', 'jobs', '-n', run.ns)['items']
    job_uids = {j['metadata']['uid'] for j in owned}
    source_jobs = [j for j in source_jobs if any(o['uid'] in job_uids for o in j['metadata'].get('ownerReferences', []))]
    (run.path / f'snapshot-reset-{time.time_ns()}.json').write_text(json.dumps({'graph': graph, 'snapshotjobs': owned, 'source_jobs': source_jobs}, indent=2))
    cleanup(run)
    for job in owned:
        run.k('delete', 'snapshotjob', job['metadata']['name'], '-n', run.ns,
              '--cascade=orphan', '--ignore-not-found', '--wait=true', '--timeout=60s', timeout=75)
    for job in source_jobs:
        run.k('delete', 'job', job['metadata']['name'], '-n', run.ns,
              '--ignore-not-found', '--wait=true', '--timeout=90s', timeout=105)
    run.result('snapshot-reset', 'completed', stopped_capture_jobs=[j['metadata']['name'] for j in owned],
               scope='Owned DGD and its capture jobs only; orphaned Snapshot artifacts retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('render', 'dry-run', 'deploy', 'verify', 'status', 'cleanup', 'reset'))
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'render':
        render(run)
    elif args.action == 'dry-run':
        graph = render(run)
        run.ensure_namespace()
        run.k('apply', '--dry-run=client', '-f', '-', input_text=json.dumps(graph))
        server = run.k('apply', '--dry-run=server', '-f', '-', input_text=json.dumps(graph), check=False)
        if server.returncode and 'checkpoint functionality is disabled' in server.stderr:
            run.result('snapshot-dgd-dry-run', 'blocked', client_validation='passed',
                       reason='Native checkpoint gate is disabled in the shared operator; no DGD created')
        elif server.returncode:
            raise RuntimeError(server.stderr)
        else:
            run.result('snapshot-dgd-dry-run', 'passed', scope='Admission only; no DGD created')
    elif args.action == 'deploy':
        deploy(run)
    elif args.action == 'verify':
        try:
            verify(run)
        except Exception as error:
            run.result('snapshot-restore', 'failed', error=str(error))
            from snapshot_diagnostics import collect
            collect(run)
            raise
    elif args.action == 'status':
        status(run, brief=True)
    elif args.action == 'reset':
        reset(run)
    else:
        cleanup(run)


if __name__ == '__main__':
    main()
