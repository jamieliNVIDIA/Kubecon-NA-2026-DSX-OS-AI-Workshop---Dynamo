#!/usr/bin/env python3
"""Fresh, frozen-model R610 TP2 Snapshot workflow with reusable evidence."""
import argparse
import base64
import hashlib
import time
import json
from pathlib import Path
from testlib import ROOT, Run
from serving_tests import lock_model, model_cache_home, worker_resources


def prepare(run, baseline, legacy_ipc=False, eager=False, cuinterpose=False, capture_keepalive=False):
    old = json.loads((baseline / 'state.json').read_text())
    lock = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())
    if old['owner'] != run.state['owner'] or old['checks']['model-staging']['status'] != 'passed':
        raise ValueError('Requires an owned, previously staged cache')
    for key in ('model', 'revision', 'runtime_image', 'tensor_parallel_size'):
        if old['model_lock'][key] != lock[key]:
            raise ValueError(f'Baseline identity differs: {key}')
    lock['manifest_directory'] = 'snapshot-super-vl-tp2-r610'
    lock['snapshot_launch_job'] = True
    if legacy_ipc:
        lock['snapshot_legacy_ipc'] = True
        lock['manifest_directory'] += '-legacy-ipc'
    if eager:
        lock['snapshot_eager'] = True
        lock['manifest_directory'] += '-eager'
    if cuinterpose:
        lock['snapshot_launch_job'] = False
        lock['snapshot_cuinterpose'] = True
        lock['manifest_directory'] = 'snapshot-super-vl-tp2-cuinterpose' + ('-eager' if eager else '')
        if capture_keepalive:
            lock['capture_keepalive'] = True
            lock['manifest_directory'] += '-keepalive'
    target = run.path / 'model-lock.json'
    if target.exists() and json.loads(target.read_text()) != lock:
        raise ValueError('Use a fresh run for different inputs')
    target.write_text(json.dumps(lock, indent=2) + '\n')
    lock_model(run)
    from storage_tests import prepare as storage
    from common_runtime_tests import pull_secret
    storage(run)
    pull_secret(run)
    source = old.get('model_cache_run_id', old['run_id'])
    if Path(source).name != source or source in ('.', '..'):
        raise ValueError('Invalid source cache identifier')
    run.state.update(model_cache_run_id=source, baseline_run=str(baseline.resolve()))
    run.save()
    program = '''import hashlib,json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK'])
root=Path(os.environ['HF_HOME'])/'hub'/('models--'+lock['model'].replace('/','--'))/'snapshots'/lock['revision']
index=json.loads((root/'model.safetensors.index.json').read_text())
weights=sorted(set(index['weight_map'].values()))
sizes={name:(root/name).stat().st_size for name in weights}
assert all(v>0 for v in sizes.values())
assert len(sizes)==lock['checkpoint_weight_files']
# Index total_size is tensor metadata; qualify actual files against the
# original successful download receipt, which includes safetensors headers.
assert sum(sizes.values())==int(os.environ['EXPECTED_FILE_BYTES'])
for name in ('config.json','tokenizer_config.json','model.safetensors.index.json'):
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==lock['model_metadata_sha256'][name],name
print(json.dumps({'model':lock['model'],'revision':lock['revision'],'weight_files':len(sizes),
 'weight_bytes':sum(sizes.values()),'snapshot_path':str(root)}))
'''
    report = cpu_probe(run, 'snapshot-cache-check', program, [
        {'name': 'HF_HOME', 'value': model_cache_home(run)},
        {'name': 'EXPECTED_FILE_BYTES', 'value': str(old['checks']['model-staging']['weight_bytes'])},
        {'name': 'MODEL_LOCK', 'value': json.dumps(lock)}], cache=True)
    run.result('model-staging', 'passed', **report, cache_source=source,
               scope='Exact cached revision, all shard sizes and metadata hashes reverified; no download')


def cpu_probe(run, name, program, env=None, cache=False):
    lock = lock_model(run)
    spec = {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
            'automountServiceAccountToken': False,
            'imagePullSecrets': [{'name': lock['image_pull_secret']}],
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
            'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                'command': ['python3', '-c', program],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}] + (env or []),
                'resources': {'requests': {'cpu': '1', 'memory': '1Gi'}, 'limits': {'memory': '2Gi'}}}]}
    if cache:
        spec['volumes'] = [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]
        spec['containers'][0]['volumeMounts'] = [{'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True}]
    return finish_probe(run, {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': spec})


def finish_probe(run, pod):
    name = pod['metadata']['name']
    run.apply([pod])
    try:
        finished = run.wait_pod(name, completed=True, timeout=240)
        expected_image = lock_model(run)['runtime_image'].split('@')[-1]
        if finished['status']['containerStatuses'][0]['imageID'].split('@')[-1] != expected_image:
            raise ValueError('Probe ran a different image digest')
        logs = run.k('logs', name, '-n', run.ns).stdout
        (run.path / f'{name}.log').write_text(logs)
        report = json.loads(logs.strip().splitlines()[-1])
        report['image_id'] = finished['status']['containerStatuses'][0]['imageID']
        return report
    finally:
        logs = run.k('logs', name, '-n', run.ns, check=False)
        (run.path / f'{name}.log').write_text(logs.stdout + logs.stderr)
        run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=60s', timeout=75)


def workload_probe(run):
    lock = lock_model(run)
    program = '''import json,os
from pathlib import Path
job=Path(os.environ['CUDA_CHECKPOINT_JOB_FILE'])
assert str(job)=='/snapshot-control/cuda-checkpoint-job' and job.stat().st_size>0
import torch
assert torch.cuda.device_count()==2
values=[torch.tensor([i+1],device=f'cuda:{i}').item() for i in range(2)]
assert values==[1,2]
print(json.dumps({'job_file':str(job),'job_file_bytes':job.stat().st_size,
 'cuda_values':values,'driver':open('/proc/driver/nvidia/version').read()}))
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'snapshot-workload-launch-probe'},
           'spec': {'restartPolicy': 'Never', 'runtimeClassName': 'nvidia', 'activeDeadlineSeconds': 180,
               'automountServiceAccountToken': False,
               'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
               'imagePullSecrets': [{'name': lock['image_pull_secret']}],
               'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                   'command': ['/bin/sh', '/snapshot-bootstrap/entrypoint.sh', 'python3', '-c', program],
                   'env': [{'name': 'SNAPSHOT_CONTROL_DIR', 'value': '/snapshot-control'}],
                   'resources': worker_resources(lock),
                   'volumeMounts': [{'name': 'bootstrap', 'mountPath': '/snapshot-bootstrap', 'readOnly': True},
                                    {'name': 'control', 'mountPath': '/snapshot-control'}]}],
               'volumes': [{'name': 'bootstrap', 'configMap': {'name': 'snapshot-launch-bootstrap', 'defaultMode': 365}},
                           {'name': 'control', 'emptyDir': {}}]}}
    report = finish_probe(run, pod)
    passed = report.get('job_file_bytes', 0) > 0 and report.get('cuda_values') == [1, 2]
    run.result('snapshot-workload-launch', 'passed' if passed else 'blocked', **report)
    return passed


def bootstrap(run):
    pods = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    agent = next(p for p in pods if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == 'kubecon-nke-site-cp-0124')
    expected = 'sha256:973e93dfd2388f3bcba6099de8c4c806262690d23077fd1042b87391bcdd80ff'
    if not any(expected in c.get('imageID', '') for c in agent['status']['containerStatuses']):
        raise ValueError('Unexpected Snapshot agent image; review the binary source')
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent',
                   '--', 'base64', '/usr/local/sbin/cuda-checkpoint')
    binary = base64.b64decode(result.stdout)
    digest = hashlib.sha256(binary).hexdigest()
    if digest != '707fa7f54136824d6c1d6dd724b9b1717610f831033c00d06da474de363a06db':
        raise ValueError('Checkpoint executable differs from the inspected pinned agent')
    if not binary.startswith(b'\x7fELF'):
        raise ValueError('Expected the agent ELF checkpoint executable')
    (run.path / 'cuda-checkpoint').write_bytes(binary)
    cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'snapshot-launch-bootstrap'},
          'immutable': True,
          'data': {'entrypoint.sh': (ROOT / 'scripts/snapshot-launch-entrypoint.sh').read_text(),
                   'persist-job.sh': (ROOT / 'scripts/snapshot-persist-job.sh').read_text()},
          'binaryData': {'cuda-checkpoint': base64.b64encode(binary).decode()}}
    run.apply([cm])
    run.result('snapshot-launch-bootstrap', 'created', agent_uid=agent['metadata']['uid'],
               source_image=expected, executable_sha256=digest, bytes=len(binary),
               scope='Owned immutable ConfigMap; copy of pinned agent executable; runtime image unchanged')


def inspect_agent(run):
    pods = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    agent = next(p for p in pods if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == 'kubecon-nke-site-cp-0124')
    (run.path / 'snapshot-agent-spec.json').write_text(json.dumps(agent, indent=2))
    command = ['sh', '-c', 'ls -l /usr/local/sbin/cuda-checkpoint /usr/bin/cuda-checkpoint; '
               'sha256sum /usr/local/sbin/cuda-checkpoint; '
               'awk \'/cuda-checkpoint|driver/ {print}\' /proc/self/mountinfo']
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--', *command)
    (run.path / 'snapshot-agent-tool.txt').write_text(result.stdout + result.stderr)
    print(result.stdout)


def progress(run):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    stamp = time.time_ns()
    for pod in pods:
        name = pod['metadata']['name']
        print(name, pod.get('status', {}).get('phase'), flush=True)
        if pod.get('status', {}).get('phase') in ('Running', 'Failed'):
            for container in pod['spec']['containers']:
                if pod['metadata'].get('labels', {}).get('nvidia.com/dynamo-component') == 'Frontend':
                    continue
                logs = run.k('logs', name, '-n', run.ns, '-c', container['name'], '--tail=45', check=False)
                (run.path / f'progress-{name}-{container["name"]}-{stamp}.log').write_text(logs.stdout + logs.stderr)
                print(logs.stdout[-2300:], flush=True)
        for container in pod['spec']['containers']:
            if container.get('resources', {}).get('claims') and pod.get('status', {}).get('resourceClaimStatuses'):
                from gpu_claims import verify_allocation
                claim = verify_allocation(run, pod, container, 2)
                (run.path / f'allocation-{pod["metadata"]["uid"]}.json').write_text(json.dumps(claim, indent=2))
    for resource in ('dgd', 'snapshotjob', 'podsnapshot'):
        objects = run.get('get', resource, '-n', run.ns)
        (run.path / f'progress-{resource}-{stamp}.json').write_text(json.dumps(objects, indent=2))
        for obj in objects['items']:
            status = obj.get('status', {})
            print(resource, obj['metadata']['name'], json.dumps({k: status[k] for k in
                ('state', 'checkpoints', 'conditions') if k in status}), flush=True)


def source_check(run):
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    source = [p for p in pods if 'nvidia.com/snapshot-job' in p['metadata'].get('labels', {})
              and p.get('status', {}).get('phase') == 'Running']
    if len(source) != 1:
        raise ValueError('Expected one active owned source Pod')
    pod = source[0]
    graph = run.get('get', 'dgd', 'ft-snapshot', '-n', run.ns)
    if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Source graph is not owned')
    checkpoint = graph['status']['checkpoints']['VllmSnapshotWorker']['checkpointName']
    if pod['metadata']['labels']['nvidia.com/snapshot-job'] != checkpoint:
        raise ValueError('Source Pod belongs to another checkpoint')
    job = run.get('get', 'snapshotjob', checkpoint, '-n', run.ns)
    if not any(o['kind'] == 'Job' and o['uid'] == job['status']['sourceJobUID']
               for o in pod['metadata'].get('ownerReferences', [])):
        raise ValueError('Source Pod owner UID differs from the owned SnapshotJob')
    from gpu_claims import verify_allocation
    main = next(c for c in pod['spec']['containers'] if c['name'] == 'main')
    claim = verify_allocation(run, pod, main, 2)
    (run.path / 'snapshot-source-pod.json').write_text(json.dumps(pod, indent=2))
    (run.path / 'snapshot-source-claim.json').write_text(json.dumps(claim, indent=2))
    program = '''import json,os
from pathlib import Path
env=dict(v.split('=',1) for v in Path('/proc/1/environ').read_bytes().decode().split('\\0') if '=' in v)
job=Path('/snapshot-control/cuda-checkpoint-job')
assert env['CUDA_CHECKPOINT_JOB_FILE']==str(job) and job.stat().st_size>0
names=('NCCL_CUMEM_ENABLE','NCCL_CUMEM_HOST_ENABLE','NCCL_NVLS_ENABLE','NCCL_IB_DISABLE')
workers=[]
for process in Path('/proc').glob('[0-9]*'):
 try:
  comm=(process/'comm').read_text().strip()
  if comm.startswith('VLLM::Worker'):
   worker_env=dict(v.split('=',1) for v in (process/'environ').read_bytes().decode().split('\\0') if '=' in v)
   workers.append({'pid':int(process.name),'comm':comm,'nccl_env':{k:worker_env.get(k) for k in names}})
 except (FileNotFoundError,ProcessLookupError):pass
print(json.dumps({'job_file':str(job),'job_file_bytes':job.stat().st_size,
 'nccl_env':{k:env.get(k) for k in names},'workers':workers,
 'pid1_command':Path('/proc/1/cmdline').read_bytes().decode().split('\\0')}))
'''
    result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--', 'python3', '-c', program)
    logs = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--tail=1200')
    (run.path / f'snapshot-source-log-{time.time_ns()}.log').write_text(logs.stdout)
    run.result('snapshot-source-launch', 'passed', **json.loads(result.stdout),
               pod_uid=pod['metadata']['uid'], claim_uid=claim['metadata']['uid'], physical_gpus=2,
               scope='Live source launch identity and DRA allocation; capture/restore not implied')


def agent_progress(run):
    pods = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    agent = next(p for p in pods if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == 'kubecon-nke-site-cp-0124')
    snapshots = run.get('get', 'podsnapshot', '-n', run.ns)['items']
    if len(snapshots) != 1:
        raise ValueError('Expected exactly one owned run snapshot')
    snapshot = snapshots[0]
    content = run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
    if content['spec']['snapshotRef']['uid'] != snapshot['metadata']['uid']:
        raise ValueError('Snapshot content identity differs')
    import uuid
    content_uid = str(uuid.UUID(content['metadata']['uid']))
    logs = run.k('logs', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--tail=600')
    stamp = time.time_ns()
    (run.path / f'snapshot-agent-progress-{stamp}.log').write_text(logs.stdout)
    relevant = [line for line in logs.stdout.splitlines()
                if content_uid in line or snapshot['metadata']['name'] in line or content['metadata']['name'] in line]
    print('\n'.join(relevant[-14:]), flush=True)
    root = '/checkpoints/artifacts/' + content_uid
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
        'sh', '-c', 'ps -eo pid,ppid,stat,etime,wchan:32,comm | '
        'awk \'NR==1 || $6 ~ /cuda|criu|nsenter/\'; '
        'for pid in $(pgrep -f "^/usr/local/bin/cuda-checkpoint-helper"); do '
        'tr "\\000" " " < /proc/$pid/cmdline; echo; '
        'target=$(tr "\\000" "\\n" < /proc/$pid/cmdline | '
        'awk \'prev=="--pid" {print; exit} {prev=$0}\'); '
        'case "$(cat /proc/$target/cgroup)" in *"$2"*) '
        'ps -L -p "$target" -o pid,tid,pcpu,stat,wchan:32,comm | '
        'awk \'NR==1 || $6 !~ /^python3$/\' | head -35; '
        'cat /proc/$target/io; '
        'awk \'/VmRSS|VmSize|RssAnon|RssFile|VmSwap/ {print}\' /proc/$target/status;; esac; done; '
        'find "$1" -maxdepth 6 -type f -name dump.log -exec tail -12 {} \\;; '
        'find "$1" -maxdepth 6 -type f -printf "%s %p\\n" | sort -nr | head -8',
        'inspect-owned-capture', root, str(uuid.UUID(content['spec']['source']['podRef']['uid'])).replace('-', '_'),
        check=False, timeout=30)
    (run.path / f'snapshot-owned-artifact-progress-{stamp}.log').write_text(result.stdout + result.stderr)
    print(result.stdout[-4000:], flush=True)


def runtime_cuda_hooks(run):
    source = json.loads((run.path / 'snapshot-source-pod.json').read_text())
    uid = source['metadata']['uid'].replace('-', '_')
    agent = next(p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
                 if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == source['spec']['nodeName'])
    script = '''for helper in $(pgrep -f '^/usr/local/bin/cuda-checkpoint-helper'); do
target=$(tr '\\000' '\\n' < /proc/$helper/cmdline | awk 'prev=="--pid" {print; exit} {prev=$0}')
case "$(cat /proc/$target/cgroup)" in *"$1"*)
root=/proc/$target/root/usr/local/lib/python3.12/dist-packages
for name in vllm/v1/worker/gpu_worker.py vllm/distributed/parallel_state.py vllm/distributed/device_communicators/cuda_communicator.py vllm/distributed/device_communicators/flashinfer_all_reduce.py; do
echo "$name"
awk '/def checkpoint_prepare|def checkpoint_restore|def prepare_for_checkpoint/ {n=100} n>0 {print; n--}' "$root/$name"
done;; esac; done'''
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
                   'sh', '-c', script, 'inspect-owned-runtime-hooks', uid, timeout=30)
    (run.path / 'runtime-cuda-checkpoint-hooks.txt').write_text(result.stdout + result.stderr)
    print(result.stdout[-18000:])


def ipc_control(run):
    """Isolate R610 legacy CUDA IPC from the large vLLM engine, on another node."""
    import urllib.request
    revision = '00d5cce84c628088d6caa203fc4af40c1538b6f7'
    url = f'https://raw.githubusercontent.com/NVIDIA/cuda-checkpoint/{revision}/src/r610-get-mem-handle-ipc.c'
    original = urllib.request.urlopen(url, timeout=30).read()
    text = original.decode()
    for before, after in [('#define PEER_COUNT 4', '#define PEER_COUNT 2'),
                          ('cuDevicePrimaryCtxRetain(&ctx, 0)', 'cuDevicePrimaryCtxRetain(&ctx, idx % 2)')]:
        if text.count(before) != 1:
            raise ValueError('Upstream IPC demo changed; review before adapting it')
        text = text.replace(before, after)
    (run.path / 'r610-ipc-original.c').write_bytes(original)
    (run.path / 'r610-ipc-two-gpu.c').write_text(text)
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'snapshot-ipc-control'},
                'data': {'ipc.c': text}}])
    lock = lock_model(run)
    command = '''set -eu
export PATH=/snapshot-bootstrap:$PATH
gcc -I/usr/local/cuda/include -pthread /tests/ipc.c -o /tmp/ipc-control -L/usr/local/cuda/lib64/stubs -lcuda
timeout 150s /tmp/ipc-control --configure-env
echo '{"legacy_ipc_checkpoint_restore":true,"physical_gpus":2,"peers":2}'
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'snapshot-ipc-control'},
           'spec': {'restartPolicy': 'Never', 'runtimeClassName': 'nvidia', 'activeDeadlineSeconds': 180,
               'automountServiceAccountToken': False,
               'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0198'},
               'imagePullSecrets': [{'name': lock['image_pull_secret']}],
               'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                   'command': ['/bin/sh', '-c', command],
                   'resources': {'requests': {'cpu': '2', 'memory': '2Gi', 'nvidia.com/gpu': '2'},
                                 'limits': {'memory': '4Gi', 'nvidia.com/gpu': '2'}},
                   'volumeMounts': [{'name': 'bootstrap', 'mountPath': '/snapshot-bootstrap', 'readOnly': True},
                                    {'name': 'tests', 'mountPath': '/tests', 'readOnly': True},
                                    {'name': 'shm', 'mountPath': '/dev/shm'}]}],
               'volumes': [{'name': 'bootstrap', 'configMap': {'name': 'snapshot-launch-bootstrap', 'defaultMode': 365}},
                           {'name': 'tests', 'configMap': {'name': 'snapshot-ipc-control'}},
                           {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '64Mi'}}]}}
    try:
        report = finish_probe(run, pod)
        run.result('snapshot-ipc-control', 'passed', **report, source=url,
                   source_sha256=hashlib.sha256(original).hexdigest(), adapted_sha256=hashlib.sha256(text.encode()).hexdigest(),
                   scope='Two processes on different GPUs: legacy CUDA IPC buffers correct before/after CUDA checkpoint/restore; no CRIU')
    except Exception as error:
        run.result('snapshot-ipc-control', 'failed', source=url, error=str(error))
        raise


def stop_stalled(run):
    """Bound an owned source stuck before CRIU; retain diagnostic objects/artifacts."""
    source = json.loads((run.path / 'snapshot-source-pod.json').read_text())
    graph = run.get('get', 'dgd', 'ft-snapshot', '-n', run.ns)
    if graph['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
        raise ValueError('Graph is not owned')
    checkpoint = graph['status']['checkpoints']['VllmSnapshotWorker']
    if checkpoint.get('ready'):
        raise ValueError('Capture became ready; do not stop it as stalled')
    current = run.get('get', 'pod', source['metadata']['name'], '-n', run.ns)
    if current['metadata']['uid'] != source['metadata']['uid'] or current['metadata'].get('labels', {}).get('nvidia.com/snapshot-job') != checkpoint['checkpointName']:
        raise ValueError('Saved source identity differs from the current capture')
    agent = next(p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
                 if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                 and p['spec'].get('nodeName') == source['spec']['nodeName'])
    script = '''for helper in $(pgrep -f '^/usr/local/bin/cuda-checkpoint-helper'); do
args=$(tr '\\000' ' ' < /proc/$helper/cmdline)
case "$args" in *'--action checkpoint '*)
target=$(tr '\\000' '\\n' < /proc/$helper/cmdline | awk 'prev=="--pid" {print; exit} {prev=$0}')
case "$(cat /proc/$target/cgroup)" in *"$1"*)
printf '%s ' "$helper"; ps -p "$helper" -o etimes=; printf '%s\\n' "$args";; esac;; esac; done'''
    result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
                   'sh', '-c', script, 'verify-owned-stalled-helper', source['metadata']['uid'].replace('-', '_'))
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2:
        raise ValueError('Expected exactly one owned CUDA checkpoint helper')
    helper, elapsed = map(int, lines[0].split())
    if elapsed < 600:
        raise ValueError(f'Wait until the bounded 600-second CUDA action limit ({elapsed}s observed)')
    job = run.get('get', 'snapshotjob', checkpoint['checkpointName'], '-n', run.ns)
    (run.path / 'snapshot-stalled-capture.json').write_text(json.dumps({'graph': graph, 'job': job,
        'source': source, 'helper_pid': helper, 'helper_elapsed_seconds': elapsed, 'command': lines[1]}, indent=2))
    run.result('snapshot-capture-bounded-stop', 'blocked', helper_elapsed_seconds=elapsed,
               reason='Owned first-rank CUDA checkpoint action exceeded 600 seconds before CRIU; no usable artifact',
               helper_command=lines[1])
    from snapshot_tests import reset
    reset(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'bootstrap', 'workload-probe', 'ipc-control', 'stop-stalled', 'runtime-cuda-hooks', 'inspect-agent', 'progress', 'agent-progress', 'source-check', 'runtime', 'render', 'deploy', 'verify', 'status', 'cleanup', 'dry-run'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'results/20261015-super-vl-tp2')
    parser.add_argument('--legacy-ipc', action='store_true', help='Fresh-run NCCL legacy allocation control; no NVLS/cumem IPC')
    parser.add_argument('--eager', action='store_true', help='Fresh-run control without torch.compile or CUDA graphs')
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'prepare':
        prepare(run, args.baseline, legacy_ipc=args.legacy_ipc, eager=args.eager)
    elif args.action == 'workload-probe':
        if not workload_probe(run):
            raise RuntimeError('Workload launch support missing; inspect probe receipt')
    elif args.action == 'inspect-agent':
        inspect_agent(run)
    elif args.action == 'bootstrap':
        bootstrap(run)
    elif args.action == 'progress':
        progress(run)
    elif args.action == 'source-check':
        source_check(run)
    elif args.action == 'agent-progress':
        agent_progress(run)
    elif args.action == 'ipc-control':
        ipc_control(run)
    elif args.action == 'runtime-cuda-hooks':
        runtime_cuda_hooks(run)
    elif args.action == 'stop-stalled':
        stop_stalled(run)
    elif args.action == 'dry-run':
        from snapshot_tests import render
        render(run)
        manifest = run.state['graphs']['snapshot']['manifest']
        for mode in ('client', 'server'):
            run.k('apply', '--dry-run=' + mode, '-f', manifest)
        run.result('snapshot-effective-manifest', 'passed', manifest=manifest, dry_runs=['client', 'server'])
    elif args.action == 'runtime':
        from snapshot_runtime_tests import test
        test(run)
    elif args.action == 'verify':
        from snapshot_tests import verify
        from snapshot_diagnostics import collect_resources, collect
        try:
            verify(run, observer=collect_resources)
            from snapshot_measurements import measure
            measure(run)
        except Exception as error:
            run.result('snapshot-restore', 'failed', error=str(error))
            raise
        finally:
            collect(run)
    elif args.action == 'status':
        from snapshot_diagnostics import collect
        collect(run)
    else:
        import snapshot_tests
        getattr(snapshot_tests, args.action)(run)


if __name__ == '__main__':
    main()
