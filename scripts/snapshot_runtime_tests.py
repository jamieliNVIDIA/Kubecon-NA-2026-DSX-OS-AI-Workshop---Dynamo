#!/usr/bin/env python3
"""Owned model/TP-specific Snapshot preparation check without host changes."""
import argparse
import json
from pathlib import Path
from serving_tests import lock_model, model_cache_home, worker_resources
from testlib import ROOT, Run


def test(run):
    lock = lock_model(run)
    if run.state.get('checks', {}).get('model-staging', {}).get('status') != 'passed':
        raise ValueError('Reverify or download the exact model cache first')
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'snapshot-runtime-probe'},
                'data': {'probe.py': (ROOT / 'scripts/snapshot_runtime_probe.py').read_text(),
                         'model-lock.json': json.dumps(lock)}}])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'snapshot-runtime-probe'},
           'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 1800, 'automountServiceAccountToken': False,
               'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
               'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                    'command': ['python3', '/tests/probe.py'],
                    'env': [{'name': k, 'value': v} for k, v in {
                        'HF_HOME': model_cache_home(run), 'HF_HUB_OFFLINE': '1',
                        'HF_MODULES_CACHE': '/tmp/hf_modules', 'VLLM_CACHE_ROOT': '/tmp/vllm',
                        'TRITON_CACHE_DIR': '/tmp/triton', 'VLLM_WORKER_MULTIPROC_METHOD': 'spawn',
                        'VLLM_NO_USAGE_STATS': '1'}.items()],
                    'resources': worker_resources(lock),
                    'securityContext': {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK']}},
                    'volumeMounts': [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True},
                                     {'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True},
                                     {'name': 'shm', 'mountPath': '/dev/shm'}]}],
               'volumes': [{'name': 'tests', 'configMap': {'name': 'snapshot-runtime-probe'}},
                           {'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                           {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Gi'}}]}}
    if lock.get('image_pull_secret'):
        pod['spec']['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
    if lock.get('snapshot_legacy_ipc'):
        pod['spec']['containers'][0]['env'] += [{'name': k, 'value': '0'} for k in
                                              ('NCCL_CUMEM_ENABLE', 'NCCL_CUMEM_HOST_ENABLE', 'NCCL_NVLS_ENABLE')]
    run.apply([pod])
    try:
        finished = run.wait_pod('snapshot-runtime-probe', timeout=1900, completed=True)
        logs = run.k('logs', 'snapshot-runtime-probe', '-n', run.ns).stdout
        (run.path / 'snapshot-runtime.log').write_text(logs)
        line = next(line for line in logs.splitlines() if line.startswith('SNAPSHOT_RUNTIME_RESULT '))
        report = json.loads(line.split(' ', 1)[1])
        if not report['passed']:
            raise RuntimeError(report)
        report['image_id'] = finished['status']['containerStatuses'][0]['imageID']
        run.result('snapshot-runtime-preparation', 'passed', **report)
    except Exception as error:
        logs = run.k('logs', 'snapshot-runtime-probe', '-n', run.ns, check=False)
        (run.path / 'snapshot-runtime.log').write_text(logs.stdout + logs.stderr)
        run.result('snapshot-runtime-preparation', 'failed', error=str(error),
                   scope='No CRIU or real restore attempted')
        raise
    finally:
        run.k('delete', 'pod', 'snapshot-runtime-probe', '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    test(Run(args.run))


if __name__ == '__main__':
    main()
