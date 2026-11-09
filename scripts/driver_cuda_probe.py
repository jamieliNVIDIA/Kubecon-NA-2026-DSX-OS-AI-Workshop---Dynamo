#!/usr/bin/env python3
"""Validate all eight DRA-allocated GPUs and an intra-node NCCL collective after reload."""
import argparse
import json
import re
from pathlib import Path
from common_runtime_tests import pull_secret, SECRET
from gpu_claims import verify_allocation
from testlib import ROOT, Run

PROGRAM = r'''import datetime, json, os, subprocess
import torch
import torch.distributed as dist
import torch.multiprocessing as mp

def worker(rank, count):
    torch.cuda.set_device(rank)
    value = torch.full((1024 * 1024,), rank + 1, device='cuda', dtype=torch.float32)
    dist.init_process_group('nccl', init_method='tcp://127.0.0.1:29531', rank=rank,
                            world_size=count, timeout=datetime.timedelta(seconds=120))
    dist.all_reduce(value)
    torch.cuda.synchronize()
    assert bool((value == count * (count + 1) / 2).all()), rank
    dist.destroy_process_group()

if __name__ == '__main__':
    assert torch.cuda.device_count() == 8, torch.cuda.device_count()
    versions = subprocess.check_output(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], text=True).splitlines()
    assert versions == ['610.57.04'] * 8, versions
    mp.spawn(worker, args=(8,), nprocs=8, join=True)
    print('DRIVER_CUDA_RESULT ' + json.dumps({'node': os.environ['NODE_NAME'], 'driver': versions[0],
          'gpu_count': 8, 'cuda': torch.version.cuda, 'torch_reported_nccl': torch.cuda.nccl.version(),
          'collective': '8-rank all_reduce', 'payload_correct': True}), flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--node', required=True)
    parser.add_argument('--source-lock', type=Path, default=ROOT / 'configs/super-vl-tp2-lock.json')
    args = parser.parse_args()
    run = Run(args.run)
    run.ensure_namespace()
    model_lock = json.loads(args.source_lock.read_text())
    if model_lock['gpu_allocation'] != 'dra':
        raise ValueError('Requires the DRA image lock')
    if 'model_lock' in run.state and run.state['model_lock'] != model_lock:
        raise ValueError('Validation image lock changed')
    run.state['model_lock'] = model_lock
    run.save()
    target = run.path / 'model-lock.json'
    if target.exists() and json.loads(target.read_text()) != model_lock:
        raise ValueError('Existing image/model lock differs')
    target.write_text(json.dumps(model_lock, indent=2) + '\n')
    pull_secret(run)
    name = 'driver-cuda-' + args.node.rsplit('-', 1)[-1]
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'driver-cuda-code'},
                'data': {'probe.py': PROGRAM}}])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 600, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': args.node}, 'imagePullSecrets': [{'name': SECRET}],
        'containers': [{'name': 'test', 'image': model_lock['runtime_image'],
            'command': ['python3', '/tests/probe.py'], 'env': [{'name': 'NODE_NAME', 'value': args.node},
                {'name': 'NCCL_DEBUG', 'value': 'INFO'}],
            'resources': {'requests': {'cpu': '8', 'memory': '16Gi', 'nvidia.com/gpu': '8'},
                          'limits': {'memory': '48Gi', 'nvidia.com/gpu': '8'}},
            'volumeMounts': [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True},
                             {'name': 'shm', 'mountPath': '/dev/shm'}]}],
        'volumes': [{'name': 'tests', 'configMap': {'name': 'driver-cuda-code'}},
                    {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '8Gi'}}]}}
    run.apply([pod])
    claim = None
    try:
        running = run.wait_pod(name, timeout=660)
        claim = verify_allocation(run, running, running['spec']['containers'][0], 8)
        finished = run.wait_pod(name, timeout=660, completed=True)
        logs = run.k('logs', name, '-n', run.ns).stdout
        (run.path / f'{name}.log').write_text(logs)
        receipt = json.loads(next(l.split(' ', 1)[1] for l in logs.splitlines() if l.startswith('DRIVER_CUDA_RESULT ')))
        receipt['nccl_loaded_versions'] = sorted(set(re.findall(r'NCCL version (\S+)', logs)))
        if len(receipt['nccl_loaded_versions']) != 1:
            raise ValueError('Expected one loaded NCCL version in collective startup logs')
        run.result('driver-cuda-' + args.node, 'passed', **receipt,
            image_id=finished['status']['containerStatuses'][0]['imageID'],
            claim_uid=claim['metadata']['uid'], scope='Allocated CUDA and intra-node NCCL correctness; no model or peak-bandwidth test')
    except Exception as exc:
        run.result('driver-cuda-' + args.node, 'blocked', error=str(exc))
        raise
    finally:
        run.k('delete', 'pod', name, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=90s', timeout=105)
        if claim:
            run.k('wait', '--for=delete', 'resourceclaim/' + claim['metadata']['name'],
                  '-n', run.ns, '--timeout=90s', timeout=105)


if __name__ == '__main__':
    main()
