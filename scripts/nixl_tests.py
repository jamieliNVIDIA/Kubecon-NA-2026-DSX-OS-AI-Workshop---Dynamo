#!/usr/bin/env python3
"""Run disposable cross-node NIXL GPU-buffer tests with four EFA devices per pod."""
import argparse
import itertools
import json
from pathlib import Path
from feature_tests import BASE_IMAGE
from testlib import ROOT, Run


def test(run, pairs):
    run.ensure_namespace()
    lock = run.state.get('model_lock', {})
    data = {'transfer.py': (ROOT / 'scripts/nixl_transfer.py').read_text(),
            'entrypoint.sh': (ROOT / 'scripts/efa-entrypoint.sh').read_text(),
            'check-efa-userspace.sh': (ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh').read_text()}
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'nixl-tests'}, 'data': data}])
    nodes = [n['metadata']['name'] for n in run.get('get', 'nodes')['items']]
    selected = list(itertools.combinations(nodes, 2))[:pairs]
    reports = []
    for index, (source, target) in enumerate(selected):
        pods = []
        for role, node in [('source', source), ('target', target)]:
            name = f'nixl-{index}-{role}'
            pods.append({'apiVersion': 'v1', 'kind': 'Pod',
                'metadata': {'name': name, 'labels': {'nixl-source-pair': str(index), 'nixl-role': role}},
                'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 1200,
                    'automountServiceAccountToken': False,
                    'nodeSelector': {'kubernetes.io/hostname': node},
                    **({'imagePullSecrets': [{'name': lock['image_pull_secret']}]}
                       if lock.get('image_pull_secret') else {}),
                    'containers': [{'name': 'test', 'image': lock.get('runtime_image', BASE_IMAGE),
                        'command': ['bash', '/tests/entrypoint.sh', 'python3', '/tests/transfer.py'],
                        'env': [{'name': name, 'value': value} for name, value in {
                            'TEST_ROLE': role, 'NODE_NAME': node, 'POD_NAME': name,
                            'FI_PROVIDER': 'efa', 'FI_EFA_USE_DEVICE_RDMA': '1',
                            'FI_EFA_ENABLE_SHM_TRANSFER': '0', 'FI_EFA_ENABLE_SHM': '0',
                            'FI_HMEM_CUDA_USE_DMABUF': '1', 'NIXL_LIBFABRIC_USE_DEVICE_RDMA': '1',
                            'NIXL_LOG_LEVEL': 'INFO'}.items()],
                        'resources': {'requests': {'cpu': '2', 'memory': '8Gi', 'nvidia.com/gpu': '1', 'vpc.amazonaws.com/efa': '4'},
                                      'limits': {'memory': '16Gi', 'nvidia.com/gpu': '1', 'vpc.amazonaws.com/efa': '4'}},
                        'securityContext': {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK', 'SYS_RESOURCE']}},
                        'volumeMounts': [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]}],
                    'volumes': [{'name': 'tests', 'configMap': {'name': 'nixl-tests'}}]}})
        service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'nixl-source'},
                   'spec': {'selector': {'nixl-source-pair': str(index), 'nixl-role': 'source'},
                            'ports': [{'port': 23000, 'targetPort': 23000}]}}
        run.apply([service] + pods)
        try:
            for pod in reversed(pods):
                name = pod['metadata']['name']
                completed = run.wait_pod(name, completed=True, timeout=1250)
                log = run.k('logs', name, '-n', run.ns).stdout
                (run.path / f'{name}.log').write_text(log)
                # Native backend destructors log after our JSON receipt.
                receipts = [json.loads(line) for line in log.splitlines()
                            if line.startswith('{') and '"role"' in line]
                if len(receipts) != 1:
                    raise ValueError(f'Expected one transfer receipt from {name}')
                report = receipts[0]
                if report['role'] == 'target' and not report.get('all_correct'):
                    raise ValueError(f'GPU payload validation failed in {name}')
                report['image_id'] = completed['status']['containerStatuses'][0].get('imageID')
                reports.append(report)
            run.result('nixl-efa', 'passed', pairs_completed=index + 1, reports=reports,
                       scope='VRAM payload correctness over LIBFABRIC; bounded transfers are not peak bandwidth measurements')
        finally:
            for pod in pods:
                run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns,
                      '--ignore-not-found', '--wait=false', check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--pairs', type=int, choices=[1, 3], default=3)
    args = parser.parse_args()
    run = Run(args.run)
    print(f'Run: {run.path}; namespace: {run.ns}', flush=True)
    try:
        test(run, args.pairs)
    except Exception as exc:
        run.result('nixl-efa', 'blocked', error=str(exc))
        raise


if __name__ == '__main__':
    main()
