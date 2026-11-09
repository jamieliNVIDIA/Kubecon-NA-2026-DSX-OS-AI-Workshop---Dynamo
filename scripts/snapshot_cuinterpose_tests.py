#!/usr/bin/env python3
"""Gated Nemotron TP2 CuInterpose capture/restore with exact-image and GPU evidence."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import time
import yaml

from gpu_claims import convert_pod, verify_allocation
from serving_tests import lock_model, model_cache_home, worker_resources
from snapshot_multigpu_upgrade import SHA
from testlib import ROOT, Run

NAME = 'super-vl-tp2-cuinterpose'
RESTORE = NAME + '-restored'


def render(run):
    lock = lock_model(run)
    if not lock.get('snapshot_cuinterpose') or lock['tensor_parallel_size'] != 2:
        raise ValueError('Needs a fresh CuInterpose TP2 run')
    source = ROOT / 'configs/upstream/snapshot-cuinterpose' / SHA / 'docs/guides/vllm/capture/glm-5.3-snapshotjob.yaml'
    job = yaml.safe_load(source.read_text())
    job['metadata'] = {'name': NAME, 'namespace': run.ns, 'labels': run.labels()}
    job['spec']['activeDeadlineSeconds'] = 3600
    template = job['spec']['podTemplate']
    template['metadata'].setdefault('labels', {}).update(run.labels())
    spec = template['spec']
    spec['nodeSelector'] = {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'}
    spec['automountServiceAccountToken'] = False
    spec['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
    spec.pop('initContainers', None)
    spec['terminationGracePeriodSeconds'] = 30
    args = {'model': lock['model'], 'revision': lock['revision'], 'tokenizer_revision': lock['revision'],
        'trust_remote_code': True, 'tensor_parallel_size': 2, 'max_model_len': 8192,
        'max_num_seqs': 2, 'max_num_batched_tokens': 8192, 'gpu_memory_utilization': 0.65,
        'limit_mm_per_prompt': {'image': 1, 'video': 0}, 'enable_prefix_caching': True,
        'block_size': 64, 'mamba_backend': 'flashinfer', 'mamba_ssm_cache_dtype': 'float16',
        'mamba_cache_mode': 'align', 'enforce_eager': lock.get('snapshot_eager', False)}
    main = spec['containers'][0]
    main.update(image=lock['runtime_image'], command=['python3', '/snapshot-app/app.py'], args=[json.dumps(args)])
    main['env'] = [{'name': k, 'value': v} for k, v in {
        'HF_HOME': model_cache_home(run), 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_XET': '1',
        'HF_MODULES_CACHE': '/tmp/hf_modules', 'VLLM_CACHE_ROOT': '/tmp/vllm',
        'TRITON_CACHE_DIR': '/tmp/triton', 'VLLM_WORKER_MULTIPROC_METHOD': 'spawn',
        'NCCL_IB_DISABLE': '1', 'NCCL_RAS_ENABLE': '0', 'TORCH_NCCL_ENABLE_MONITORING': '0',
        'TORCH_NCCL_DUMP_ON_TIMEOUT': '0', 'VLLM_NO_USAGE_STATS': '1'}.items()]
    main['resources'] = worker_resources(lock)
    main['resources']['requests']['memory'] = '256Gi'
    main['resources']['limits']['memory'] = '512Gi'
    main['volumeMounts'] = [{'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True},
        {'name': 'shm', 'mountPath': '/dev/shm'}, {'name': 'app', 'mountPath': '/snapshot-app', 'readOnly': True}]
    spec['volumes'] = [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
        {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}},
        {'name': 'app', 'configMap': {'name': 'snapshot-cuinterpose-app'}}]
    if lock.get('capture_keepalive'):
        # CRIU terminates main before EFS publication. Keep the Pod nonterminal
        # until finish-source verifies publication and signals this helper.
        job['spec']['activeDeadlineSeconds'] = 7200
        spec['containers'].append({'name': 'capture-keepalive', 'image': lock['runtime_image'],
            'command': ['/bin/sh', '-c', 'trap "exit 0" TERM INT; while :; do sleep 3600 & wait $!; done'],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
            'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '32Mi'}}})
    claims = convert_pod(spec, NAME)
    for claim in claims:
        claim['metadata'].update(namespace=run.ns, labels=run.labels())
    run.apply(claims)
    target = ROOT / 'configs/dgd' / lock['manifest_directory']
    target.mkdir(exist_ok=True)
    (target / 'snapshotjob.yaml').write_text(yaml.safe_dump(job, sort_keys=False))
    (run.path / 'snapshotjob.json').write_text(json.dumps(job, indent=2))
    return job


def deploy(run):
    if run.state['checks']['model-staging']['status'] != 'passed':
        raise ValueError('Verify the frozen cache before deployment')
    code = (ROOT / 'scripts/snapshot_cuinterpose_app.py').read_text()
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'snapshot-cuinterpose-app'},
                'immutable': True, 'data': {'app.py': code}}])
    run.apply([render(run)])
    run.result('cuinterpose-deployment', 'created', source_sha=SHA,
        app_sha256=hashlib.sha256(code.encode()).hexdigest(), scope='Gated direct-vLLM SnapshotJob; no Dynamo engine teardown hooks')


def source_pod(run):
    job = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
    if job['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Unowned SnapshotJob')
    uid = job.get('status', {}).get('sourceJobUID')
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    candidates = [p for p in pods if any(o['kind'] == 'Job' and o['uid'] == uid for o in p['metadata'].get('ownerReferences', []))]
    if len(candidates) != 1:
        raise ValueError('Expected exactly one owned source Pod')
    return candidates[0]


def progress(run):
    for kind in ('snapshotjobs', 'podsnapshots', 'pods', 'resourceclaims'):
        objects = run.get('get', kind, '-n', run.ns)
        (run.path / f'cuinterpose-{kind}-{time.time_ns()}.json').write_text(json.dumps(objects, indent=2))
        for obj in objects['items']:
            print(kind, obj['metadata']['name'], json.dumps(obj.get('status', {}).get('conditions', obj.get('status', {}).get('phase'))), flush=True)
            if kind == 'pods':
                for c in obj['spec'].get('containers', []) + obj['spec'].get('initContainers', []):
                    logs = run.k('logs', obj['metadata']['name'], '-n', run.ns, '-c', c['name'], '--tail=60', check=False)
                    (run.path / f'cuinterpose-{obj["metadata"]["name"]}-{c["name"]}-{time.time_ns()}.log').write_text(logs.stdout + logs.stderr)
                    print(logs.stdout[-2200:], flush=True)


def wait_prepared(run):
    deadline = time.monotonic() + 1500
    last = None
    while time.monotonic() < deadline:
        job = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in job.get('status', {}).get('conditions', [])):
            raise RuntimeError('Source SnapshotJob failed: ' + json.dumps(job['status']))
        try:
            pod = source_pod(run)
        except ValueError:
            time.sleep(10)
            continue
        logs = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--tail=30', check=False)
        (run.path / 'cuinterpose-source-latest.log').write_text(logs.stdout + logs.stderr)
        state = logs.stdout[-1400:] or logs.stderr[-500:]
        if state != last:
            print(state, flush=True);last = state
        if '"phase": "prepared"' in logs.stdout:
            return
        if pod['status'].get('phase') == 'Failed':
            raise RuntimeError('Model source Pod failed before preparation')
        time.sleep(15)
    raise TimeoutError('Source did not finish preparation within 25 minutes')


def identity(run):
    if run.state.get('checks', {}).get('cuinterpose-capture-gate', {}).get('status') == 'opened':
        raise ValueError('Do not inject a diagnostic process after opening capture')
    pod = source_pod(run)
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, pod, main, 2)
    program = '''import json
from pathlib import Path
procs=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  comm=(p/'comm').read_text().strip()
  if comm.startswith(('python','VLLM','pt_')):
   status=(p/'status').read_text().splitlines()
   procs.append({'pid':int(p.name),'comm':comm,'wchan':(p/'wchan').read_text(),
     'status':[s for s in status if s.startswith(('VmRSS:','Threads:','State:'))],
     'interposed':'libcuinterpose.so' in (p/'maps').read_text()})
 except (FileNotFoundError,ProcessLookupError):pass
phase=Path('/snapshot-control/test-phase.json')
print(json.dumps({'phase':json.loads(phase.read_text()) if phase.exists() else None,'processes':procs}))
'''
    result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'python3', '-c', program)
    report = {'pod_uid': pod['metadata']['uid'], 'devices': claim['status']['allocation']['devices']['results'], **json.loads(result.stdout)}
    (run.path / f'cuinterpose-identity-{time.time_ns()}.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def staging(run):
    active = [j for j in run.get('get', 'snapshotjobs', '-A')['items'] if not any(
        c['type'] in ('Completed', 'Failed') and c['status'] == 'True' for c in j.get('status', {}).get('conditions', []))]
    own = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
    if own['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Unowned SnapshotJob')
    if len(active) > 1 or (active and (active[0]['metadata']['namespace'], active[0]['metadata']['name']) != (run.ns, NAME)):
        raise ValueError('Staging inspection needs this run to be the only active SnapshotJob')
    agent = next(p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
        if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-') and p['spec'].get('nodeName') == 'kubecon-nke-site-cp-0124')
    log = run.k('logs', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'pagebroker', '--tail=100').stdout
    transactions = set(re.findall(r'transaction=([0-9a-f-]{36})', log))
    if len(transactions) != 1:
        raise ValueError('Cannot unambiguously attribute PageBroker transaction')
    transaction = transactions.pop()
    script = '''ps -eo pid,ppid,stat,etime,wchan:24,comm | awk 'NR==1 || /tar|gzip|criu|pagebroker/'
for pid in $(pgrep -x pagebroker); do
 cat /proc/$pid/io
 ps -L -p "$pid" -o pid,tid,stat,wchan:32,comm
 for fd in /proc/$pid/fd/*; do readlink "$fd"; done | awk '/checkpoints|staging/' | head -16
done
du -sk /pagebroker/staging
find /pagebroker/staging -maxdepth 5 -type f -printf '%s %p\\n' | sort -nr | head -12
timeout -k 2s 8s du -sk /checkpoints
timeout -k 2s 8s find /checkpoints -maxdepth 8 -type f -printf '%s %p\\n' | sort -nr | head -8
'''
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
                   'sh', '-c', script, timeout=45, check=False)
    target = run.path / f'cuinterpose-staging-{time.time_ns()}.log'
    target.write_text('transaction=' + transaction + '\n' + log + result.stdout + result.stderr + f'\nexit_code={result.returncode}\n')
    print(log + result.stdout + result.stderr + f'\nexit_code={result.returncode}', flush=True)


def wait_capture(run):
    deadline = time.monotonic() + 1800
    last = None
    while time.monotonic() < deadline:
        job = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
        conditions = job.get('status', {}).get('conditions', [])
        state = [(c['type'], c['status'], c.get('reason')) for c in conditions]
        if state != last:
            print(json.dumps({'capture': state}), flush=True);last = state
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in conditions):
            (run.path / 'cuinterpose-capture-failure.json').write_text(json.dumps(job, indent=2))
            run.result('cuinterpose-capture', 'failed', job=job['status'])
            raise RuntimeError('Capture failed: ' + json.dumps(job['status']))
        if any(c['type'] == 'Captured' and c['status'] == 'True' for c in conditions):
            snapshot = run.get('get', 'podsnapshot', job['status']['podSnapshotName'], '-n', run.ns)
            (run.path / 'cuinterpose-artifact.json').write_text(json.dumps(snapshot, indent=2))
            run.result('cuinterpose-capture', 'passed', artifact=snapshot['metadata']['name'], job_status=job['status'])
            return
        time.sleep(15)
    raise TimeoutError('Capture did not finish within 30 minutes')


def inspect(run):
    pod = source_pod(run)
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, pod, main, 2)
    program = '''import hashlib,json,os
from pathlib import Path
root=Path('/snapshot-control')
assert (root/'preparation-complete').exists() and not (root/'ready-for-snapshot').exists()
phase=json.loads((root/'test-phase.json').read_text()); assert phase['phase']=='prepared'
procs=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  maps=(p/'maps').read_text()
  if 'libcuinterpose.so' in maps:
   procs.append({'pid':int(p.name),'name':(p/'comm').read_text().strip(),'core':'libcuinterpose_core.so' in maps})
 except (FileNotFoundError,ProcessLookupError,PermissionError):pass
sockets=sorted(str(p) for p in Path('/tmp').glob('cuinterpose-*.sock'))
socket_pids={int(Path(p).stem.split('-')[-1]) for p in sockets}
live_core_pids={p['pid'] for p in procs if p['core']}
assert live_core_pids.issubset(socket_pids), 'Live interposed process lacks a control socket'
core_pids=sorted(live_core_pids)
assert len(core_pids)>=2
libraries={n:hashlib.sha256((Path('/tmp/snapshot-cuda')/n).read_bytes()).hexdigest() for n in ('libcuinterpose.so','libcuinterpose_core.so')}
print(json.dumps({'phase':phase,'processes':procs,'core_pids':core_pids,'sockets':sockets,
 'stale_socket_pids':sorted(socket_pids-live_core_pids),'libraries':libraries}))
'''
    result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'python3', '-c', program)
    report = json.loads(result.stdout)
    if not main['command'][0].endswith('/cuinterpose-launch'):
        raise ValueError('Source lacks the injected CuInterpose launcher')
    (run.path / 'cuinterpose-source-pod.json').write_text(json.dumps(pod, indent=2))
    (run.path / 'cuinterpose-source-claim.json').write_text(json.dumps(claim, indent=2))
    agent = next(p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
                 if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == pod['spec']['nodeName'])
    # Map container PID 1 through the owned Pod cgroup, then retain binary and
    # namespace descriptors exactly as upstream's CommandInNamespaces does.
    shell = '''set -eu
target=
for path in /host/proc/[0-9]*; do
 case "$(cat "$path/cgroup" 2>/dev/null || true)" in *"$1"*)
  # The Pod's pause container also has namespace PID 1. Select the Python
  # application container, not every PID namespace in the Pod cgroup.
  [ "$(cat "$path/comm" 2>/dev/null || true)" = python3 ] || continue
  inner=$(awk '/^NSpid:/ {print $NF}' "$path/status" 2>/dev/null || true)
  if [ "$inner" = 1 ]; then test -z "$target"; target=${path##*/}; fi;; esac
done
test -n "$target"
exec 3</usr/local/bin/cuinterpose-coordinator
exec 4<"/host/proc/$target/ns/mnt"
exec 5<"/host/proc/$target/root"
shift
exec timeout -k 2s 45s nsenter --mount=/proc/self/fd/4 -t "$target" -u -i -n -p --root=/proc/self/fd/5 --wd=/proc/self/fd/5 -- /proc/self/fd/3 --inspect --socket-dir /tmp "$@"
'''
    args = [a for p in report['core_pids'] for a in ('--process', str(p))]
    checked = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
        'bash', '-c', shell, 'inspect-owned-cuinterpose', pod['metadata']['uid'].replace('-', '_'), *args, check=False, timeout=60)
    (run.path / 'cuinterpose-coordinator-inspect.log').write_text(checked.stdout + checked.stderr)
    if checked.returncode:
        raise RuntimeError('Read-only coordinator inspect failed: ' + checked.stderr[-2000:])
    from snapshot_gpu_health import inspect as health
    health(run, ROOT / 'results/20261022-snapshot-cuinterpose-before', pod['spec']['nodeName'])
    kernel = max(run.path.glob('snapshot-gpu-health-*-kernel-xids.log'), key=lambda p:p.stat().st_mtime)
    created = dt.datetime.fromisoformat(pod['metadata']['creationTimestamp'].replace('Z', '+00:00'))
    new = [line for line in kernel.read_text().splitlines() if 'NVRM: Xid' in line and
           dt.datetime.fromisoformat(line.split()[0].replace(',', '.')) >= created]
    if new:
        (run.path / 'cuinterpose-new-xids.log').write_text('\n'.join(new))
        raise RuntimeError('New GPU Xids appeared before capture; gate remains closed')
    run.result('cuinterpose-preparation-inspect', 'passed', pod_uid=pod['metadata']['uid'], **report,
               scope='Pre-capture inference/pause/KV release, injected libraries, DRA2 and coordinator inspection; no new kernel Xids')


def capture(run):
    pod = source_pod(run)
    check = run.state.get('checks', {}).get('cuinterpose-preparation-inspect', {})
    if check.get('status') != 'passed' or check.get('pod_uid') != pod['metadata']['uid']:
        raise ValueError('Requires passing inspection of this source Pod')
    run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--',
          'python3', '-c', "from pathlib import Path; Path('/snapshot-control/allow-capture').write_text('approved\\n')")
    run.result('cuinterpose-capture-gate', 'opened', source_uid=pod['metadata']['uid'])


def finish_source(run):
    job = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
    if job['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Unowned SnapshotJob')
    snapshot = run.get('get', 'podsnapshot', NAME, '-n', run.ns)
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in snapshot.get('status', {}).get('conditions', [])):
        raise ValueError('Do not stop the companion before durable capture readiness')
    if any(c['type'] == 'Completed' and c['status'] == 'True' for c in job.get('status', {}).get('conditions', [])):
        return
    pod = source_pod(run)
    recorded = json.loads((run.path / 'cuinterpose-source-pod.json').read_text())
    if pod['metadata']['uid'] != recorded['metadata']['uid']:
        raise ValueError('Source Pod UID changed')
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    if content['spec']['source']['podRef']['uid'] != pod['metadata']['uid']:
        raise ValueError('Ready content belongs to another source')
    helper = next(c for c in pod['spec']['containers'] if c['name'] == 'capture-keepalive')
    if helper['resources'].get('claims') or helper['command'] != ['/bin/sh', '-c', 'trap "exit 0" TERM INT; while :; do sleep 3600 & wait $!; done']:
        raise ValueError('Unexpected companion configuration')
    main = next(c for c in pod['status']['containerStatuses'] if c['name'] == 'main')
    if 'terminated' not in main['state']:
        raise ValueError('Capture target is still running')
    (run.path / 'cuinterpose-before-companion-stop.json').write_text(json.dumps(pod, indent=2))
    run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'capture-keepalive', '--',
          '/bin/sh', '-c', 'kill -TERM 1', check=False)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        job = run.get('get', 'snapshotjob', NAME, '-n', run.ns)
        conditions = job.get('status', {}).get('conditions', [])
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in conditions):
            raise RuntimeError('Source completion failed: ' + json.dumps(job['status']))
        if any(c['type'] == 'Completed' and c['status'] == 'True' for c in conditions):
            (run.path / 'cuinterpose-completed-job.json').write_text(json.dumps(job, indent=2))
            run.result('cuinterpose-source-completion', 'passed', job_status=job['status'])
            return
        time.sleep(5)
    raise TimeoutError('Companion did not finish cleanly within 150 seconds')


def restore(run):
    if lock_model(run).get('capture_keepalive'):
        finish_source(run)
    snapshot = run.get('get', 'podsnapshot', NAME, '-n', run.ns)
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in snapshot.get('status', {}).get('conditions', [])):
        raise ValueError('No ready capture')
    run.apply([restore_manifest(run)])
    run.result('cuinterpose-restore-deployment', 'created', artifact=NAME)


def restore_manifest(run, name=RESTORE):
    # A distinct restore Pod uses the same environment, image, volumes and app.
    source = json.loads((run.path / 'snapshotjob.json').read_text())['spec']['podTemplate']['spec']
    spec = copy.deepcopy(source)
    spec['containers'] = [c for c in spec['containers'] if c['name'] == 'main']
    spec['restartPolicy'] = 'Never'
    spec['activeDeadlineSeconds'] = 2400
    spec.pop('resourceClaims', None)
    main = spec['containers'][0]
    main['resources'].pop('claims', None)
    main['resources']['limits']['nvidia.com/gpu'] = '2'
    main['env'].append({'name': 'SNAPSHOT_CONTROL_DIR', 'value': '/snapshot-control'})
    main['volumeMounts'].append({'name': 'snapshot-control', 'mountPath': '/snapshot-control', 'subPath': 'main'})
    main['readinessProbe'] = {'exec': {'command': ['test', '-s', '/snapshot-control/vllm-restore-ready']}, 'periodSeconds': 2}
    main['startupProbe'] = {'exec': {'command': ['test', '-s', '/snapshot-control/restore-complete']}, 'periodSeconds': 2, 'failureThreshold': 900}
    spec['volumes'].append({'name': 'snapshot-control', 'emptyDir': {}})
    spec['securityContext'] = {'seccompProfile': {'type': 'Localhost', 'localhostProfile': 'profiles/block-iouring.json'}}
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name,
           'annotations': {'nvidia.com/restore-from': NAME}}, 'spec': spec}
    return pod


def verify(run, name=RESTORE):
    pod = run.wait_pod(name, timeout=1900)
    snapshot = run.get('get', 'podsnapshot', NAME, '-n', run.ns)
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    source_uid = content['spec']['source']['podRef']['uid']
    if pod['metadata']['uid'] == source_uid or not any(c['type'] == 'nvidia.com/Restored' and c['status'] == 'True' for c in pod['status'].get('conditions', [])):
        raise ValueError('Needs a distinct successfully restored Pod')
    lock = lock_model(run)
    image = next(c['imageID'] for c in pod['status']['containerStatuses'] if c['name'] == 'main')
    if image.split('@')[-1] != lock['runtime_image'].split('@')[-1]:
        raise ValueError('Restored image changed')
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, pod, main, 2)
    reply = run.k('exec', name, '-n', run.ns, '-c', 'main', '--', 'python3', '-c',
                  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/test',timeout=180).read().decode())", timeout=200)
    response = json.loads(reply.stdout)
    if response['text'].strip('.') != 'READY' or response['model'] != lock['model'] or response['revision'] != lock['revision'] or response['tp'] != 2:
        raise ValueError('Incorrect restored inference')
    for name, obj in [('pod', pod), ('claim', claim), ('content', content), ('inference', response)]:
        (run.path / ('cuinterpose-restored-' + name + '.json')).write_text(json.dumps(obj, indent=2))
    run.result('cuinterpose-restore', 'passed', source_uid=source_uid, restored_uid=pod['metadata']['uid'], image=image, response=response)


def measure(run):
    from snapshot_measurements import measure as collect
    source = json.loads((run.path / 'cuinterpose-source-pod.json').read_text())
    collect(run, snapshot_name=NAME, source_uid=source['metadata']['uid'])


def resources(run):
    from snapshot_diagnostics import collect_resources
    collect_resources(run)


def cleanup(run):
    for pod in run.get('get', 'pods', '-n', run.ns)['items']:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Refusing unowned workload cleanup')
    jobs = run.get('get', 'snapshotjobs', '-n', run.ns)['items']
    for job in jobs:
        if job['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Refusing unowned SnapshotJob')
        uid = job['metadata']['uid']
        sources = [j for j in run.get('get', 'jobs', '-n', run.ns)['items']
                   if any(o['uid'] == uid for o in j['metadata'].get('ownerReferences', []))]
        run.k('delete', 'snapshotjob', job['metadata']['name'], '-n', run.ns, '--cascade=orphan', '--wait=true', '--timeout=60s', timeout=75)
        for j in sources:
            run.k('delete', 'job', j['metadata']['name'], '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
    run.k('delete', 'pods', '-n', run.ns, '-l', 'feature-test-run=' + run.ns, '--wait=true', '--timeout=120s', timeout=135)
    from super_vl_tests import idle
    idle(run)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'deploy', 'progress', 'identity', 'staging', 'wait-prepared', 'inspect', 'capture', 'wait-capture', 'finish-source', 'restore', 'verify', 'measure', 'resources', 'cleanup'))
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--eager', action='store_true')
    p.add_argument('--keepalive', action='store_true', help='CPU source companion to avoid the five-minute terminal-Pod grace during EFS publication')
    a = p.parse_args();run = Run(a.run)
    if a.action == 'prepare':
        from snapshot_tp2_workflow import prepare
        prepare(run, ROOT / 'results/20261015-super-vl-tp2', cuinterpose=True, eager=a.eager, capture_keepalive=a.keepalive)
    else:
        globals()[a.action.replace('-', '_')](run)


if __name__ == '__main__':
    main()
