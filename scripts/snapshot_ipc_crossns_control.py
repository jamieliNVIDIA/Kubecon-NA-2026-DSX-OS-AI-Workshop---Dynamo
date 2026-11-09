#!/usr/bin/env python3
"""Bounded two-GPU legacy IPC checkpoint via the agent's host-namespace helper."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from serving_tests import lock_model
from testlib import ROOT, Run


def test(run, nccl=False):
    revision = '00d5cce84c628088d6caa203fc4af40c1538b6f7'
    url = f'https://raw.githubusercontent.com/NVIDIA/cuda-checkpoint/{revision}/src/r610-get-mem-handle-ipc.c'
    original = urllib.request.urlopen(url, timeout=30).read()
    text = original.decode().replace('#define PEER_COUNT 4', '#define PEER_COUNT 2')
    text = text.replace('cuDevicePrimaryCtxRetain(&ctx, 0)', 'cuDevicePrimaryCtxRetain(&ctx, idx % 2)')
    start = text.index('    printf("Checkpointing... ");')
    end = text.index('    printf("Restored!\\n");', start)
    text = text[:start] + '''    FILE *control = fopen("/control/ready", "w");
    CHECK(control != NULL);
    fprintf(control, "%d %d\\n", pids[0], pids[1]);
    CHECK_OK(fclose(control));
    while (access("/control/resume", F_OK) != 0) { usleep(100000); }
''' + text[end:]
    (run.path / 'r610-ipc-crossns.c').write_text(text)
    name = 'snapshot-nccl-crossns' if nccl else 'snapshot-ipc-crossns'
    data = {'probe.py': (ROOT / 'scripts/snapshot_nccl_control_probe.py').read_text()} if nccl else {'ipc.c': text}
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name}, 'data': data}])
    lock = lock_model(run)
    command = '''set -eu
export PATH=/snapshot-bootstrap:$PATH
gcc -I/usr/local/cuda/include -pthread /tests/ipc.c -o /tmp/ipc-crossns -L/usr/local/cuda/lib64/stubs -lcuda
exec /tmp/ipc-crossns --configure-env
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name},
           'spec': {'restartPolicy': 'Never', 'runtimeClassName': 'nvidia', 'activeDeadlineSeconds': 180,
               'terminationGracePeriodSeconds': 5, 'automountServiceAccountToken': False,
               'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
               'imagePullSecrets': [{'name': lock['image_pull_secret']}],
               'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                   'command': ['/bin/sh', '-c', command],
                   'readinessProbe': {'exec': {'command': ['test', '-s', '/control/ready']}, 'periodSeconds': 1},
                   'resources': {'requests': {'cpu': '2', 'memory': '2Gi', 'nvidia.com/gpu': '2'},
                                 'limits': {'memory': '4Gi', 'nvidia.com/gpu': '2'}},
                   'volumeMounts': [{'name': 'bootstrap', 'mountPath': '/snapshot-bootstrap', 'readOnly': True},
                                    {'name': 'tests', 'mountPath': '/tests', 'readOnly': True},
                                    {'name': 'control', 'mountPath': '/control'},
                                    {'name': 'shm', 'mountPath': '/dev/shm'}]}],
               'volumes': [{'name': 'bootstrap', 'configMap': {'name': 'snapshot-launch-bootstrap', 'defaultMode': 365}},
                           {'name': 'tests', 'configMap': {'name': name}},
                           {'name': 'control', 'emptyDir': {}},
                           {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '64Mi'}}]}}
    if nccl:
        container = pod['spec']['containers'][0]
        container['command'] = ['/bin/sh', '/snapshot-bootstrap/entrypoint.sh', 'python3', '/tests/probe.py']
        container['env'] = [{'name': 'SNAPSHOT_CONTROL_DIR', 'value': '/control'}] + [
            {'name': key, 'value': value} for key, value in {
                'NCCL_CUMEM_ENABLE': '0', 'NCCL_CUMEM_HOST_ENABLE': '0', 'NCCL_NVLS_ENABLE': '0',
                'NCCL_IB_DISABLE': '1', 'NCCL_RAS_ENABLE': '0', 'TORCH_NCCL_ENABLE_MONITORING': '0'}.items()]
        container['resources']['limits']['memory'] = '12Gi'
        pod['spec']['volumes'][-1]['emptyDir']['sizeLimit'] = '1Gi'
    run.apply([pod])
    report = {'source': url, 'source_sha256': hashlib.sha256(original).hexdigest(),
              'adapted_sha256': hashlib.sha256(text.encode()).hexdigest(), 'actions': []}
    if nccl:
        report = {'probe_sha256': hashlib.sha256(data['probe.py'].encode()).hexdigest(), 'actions': []}
    try:
        ready = run.wait_pod(name, timeout=100)
        from gpu_claims import verify_allocation
        claim = verify_allocation(run, ready, ready['spec']['containers'][0], 2)
        report.update(pod_uid=ready['metadata']['uid'], devices=claim['status']['allocation']['devices']['results'])
        peers = list(map(int, run.k('exec', name, '-n', run.ns, '--', 'cat', '/control/ready').stdout.split()))
        agent = next(p for p in run.get('get', 'pods', '-n', 'dynamo-system')['items']
                     if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
                     and p['spec'].get('nodeName') == ready['spec']['nodeName'])
        uid = ready['metadata']['uid'].replace('-', '_')
        script = '''for pid in $(pgrep -x "$2"); do
case "$(cat /proc/$pid/cgroup)" in *"$1"*)
printf '%s ' "$pid"; awk '/^NSpid:/ {print $NF}' /proc/$pid/status;; esac; done'''
        mapping = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
                        'sh', '-c', script, 'map-owned-ipc-peers', uid, 'python3' if nccl else 'ipc-crossns').stdout
        by_inner = {int(inner): int(outer) for outer, inner in (line.split() for line in mapping.splitlines())}
        if not {1, *peers}.issubset(by_inner) or len(peers) != 2 or len(set(peers)) != 2:
            raise ValueError(f'Unexpected owned process mapping: {by_inner}, {peers}')
        targets = [by_inner[peer] for peer in peers]
        report.update(peer_namespace_pids=peers, peer_host_pids=targets)
        job_file = f'/host/proc/{by_inner[1]}/root/dev/shm/cuda-checkpoint-demo'
        if nccl:
            job_file = f'/host/proc/{by_inner[1]}/root/control/cuda-checkpoint-job'
        feature = 'snapshot-nccl-crossns-control' if nccl else 'snapshot-ipc-crossns-control'
        for action in ('lock', 'checkpoint', 'restore', 'unlock'):
            for target in targets:
                started = time.monotonic()
                result = run.k('exec', agent['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--',
                    'timeout', '-k', '2s', '20s', '/usr/local/bin/cuda-checkpoint-helper',
                    '--action', action, '--pid', str(target), '--job-file', job_file, timeout=35, check=False)
                step = {'action': action, 'pid': target, 'seconds': time.monotonic() - started,
                        'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
                report['actions'].append(step)
                (run.path / f'{name}-actions.json').write_text(json.dumps(report, indent=2))
                print(json.dumps(step), flush=True)
                if result.returncode:
                    raise RuntimeError(f'{action} of owned peer failed: {step}')
        run.k('exec', name, '-n', run.ns, '--', 'touch', '/control/resume')
        run.wait_pod(name, completed=True, timeout=45)
        logs = run.k('logs', name, '-n', run.ns).stdout
        if 'Restored!' not in logs:
            raise ValueError('Control did not verify restored CUDA IPC buffers')
        run.result(feature, 'passed', **report,
                   scope=('NCCL all-reduce correct before/after external CUDA checkpoint/restore; no vLLM/model/CRIU' if nccl else
                          'Two different GPUs; agent helper uses host PIDs and live container job file; buffers verified after CUDA restore; no CRIU'))
    except Exception as error:
        feature = 'snapshot-nccl-crossns-control' if nccl else 'snapshot-ipc-crossns-control'
        run.result(feature, 'failed', **report, error=str(error))
        raise
    finally:
        logs = run.k('logs', name, '-n', run.ns, check=False)
        (run.path / f'{name}.log').write_text(logs.stdout + logs.stderr)
        run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=90s', timeout=105)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--nccl', action='store_true', help='Use two live PyTorch NCCL peers instead of the raw CUDA IPC demo')
    args = parser.parse_args()
    test(Run(args.run), nccl=args.nccl)
