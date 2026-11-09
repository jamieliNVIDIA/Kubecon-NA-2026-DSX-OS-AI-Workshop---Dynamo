#!/usr/bin/env python3
"""Create an owned Retain PV/PVC on existing EFS and verify cross-node sharing."""
import argparse
import copy
import json
from pathlib import Path
from testlib import ROOT, Run


def prepare(run):
    run.ensure_namespace()
    source = run.get('get', 'pv', 'dynamo-shared-pv')
    if source['spec']['csi']['driver'] != 'efs.csi.aws.com':
        raise ValueError('Expected existing EFS CSI volume')
    pv_name = run.ns + '-efs'
    pv = {'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': pv_name},
          'spec': {'capacity': {'storage': '128Gi'}, 'accessModes': ['ReadWriteMany'],
                   'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '',
                   'claimRef': {'namespace': run.ns, 'name': 'feature-cache'},
                   'csi': copy.deepcopy(source['spec']['csi'])}}
    pvc = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
           'metadata': {'name': 'feature-cache'},
           'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '',
                    'volumeName': pv_name, 'resources': {'requests': {'storage': '128Gi'}}}}
    run.apply([pv, pvc], cluster_scope=True)
    run.state['storage'] = {'pv': pv_name, 'pvc': 'feature-cache',
                            'source_pv': 'dynamo-shared-pv',
                            'test_directory': f'feature-tests/{run.state["run_id"]}',
                            'reclaim_policy': 'Retain'}
    run.save()


def inspect(run):
    """Record live storage bindings without creating or modifying resources."""
    volumes = run.get('get', 'pv')
    claims = run.get('get', 'pvc', '-A')
    classes = run.get('get', 'storageclasses')
    for name, data in [('pv', volumes), ('pvc', claims), ('storageclasses', classes)]:
        (run.path / f'{name}.json').write_text(json.dumps(data, indent=2) + '\n')
    by_name = {v['metadata']['name']: v for v in volumes['items']}
    shared = []
    for claim in claims['items']:
        if 'ReadWriteMany' not in claim['spec'].get('accessModes', []):
            continue
        volume = by_name.get(claim['spec'].get('volumeName'), {})
        shared.append({'namespace': claim['metadata']['namespace'],
                       'pvc': claim['metadata']['name'],
                       'phase': claim.get('status', {}).get('phase'),
                       'pv': claim['spec'].get('volumeName'),
                       'storage_class': claim['spec'].get('storageClassName', ''),
                       'csi': volume.get('spec', {}).get('csi', {})})
    summary = {'rwx_claims': shared,
               'storage_classes': [{'name': c['metadata']['name'],
                                    'provisioner': c['provisioner']}
                                   for c in classes['items']]}
    run.result('storage-inspection', 'collected', **summary,
               scope='Read-only configuration inspection; does not repeat mount or write tests')
    print(json.dumps(summary, indent=2))


def test(run):
    prepare(run)
    nodes = run.get('get', 'nodes')['items'][:2]
    if len(nodes) < 2:
        raise ValueError('Two nodes required for a cross-node storage test')
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'storage-test'},
                'data': {'probe.py': (ROOT / 'scripts/storage_probe.py').read_text()}}])
    pods = []
    for index, node in enumerate(nodes):
        pods.append({'apiVersion': 'v1', 'kind': 'Pod',
             'metadata': {'name': f'storage-test-{index}'},
             'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 300,
                 'automountServiceAccountToken': False,
                 'nodeSelector': {'kubernetes.io/hostname': node['metadata']['name']},
                 'containers': [{'name': 'test', 'image': 'python:3.12-slim-bookworm',
                     'command': ['python3', '/tests/probe.py'],
                     'env': [{'name': 'TEST_RUN', 'value': run.state['run_id']},
                             {'name': 'TEST_INDEX', 'value': str(index)},
                             {'name': 'NODE_NAME', 'value': node['metadata']['name']}],
                     'resources': {'requests': {'cpu': '100m', 'memory': '64Mi'},
                                   'limits': {'cpu': '1', 'memory': '256Mi'}},
                     'volumeMounts': [{'name': 'efs', 'mountPath': '/efs'},
                                      {'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]}],
                 'volumes': [{'name': 'efs', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                             {'name': 'tests', 'configMap': {'name': 'storage-test'}}]}})
    run.apply(pods)
    reports = []
    try:
        for pod in pods:
            completed = run.wait_pod(pod['metadata']['name'], completed=True, timeout=600)
            report = json.loads(run.k('logs', pod['metadata']['name'], '-n', run.ns).stdout)
            report['image_id'] = completed['status']['containerStatuses'][0].get('imageID')
            reports.append(report)
        assert len({r['node'] for r in reports}) == 2
        run.result('storage', 'passed', reports=reports,
                   scope='Cross-node visibility and byte correctness; 4 MiB writes are not a throughput qualification')
    finally:
        for pod in pods:
            run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns,
                  '--ignore-not-found', '--wait=false', check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--inspect-only', action='store_true',
                      help='Read-only PV/PVC and StorageClass inspection')
    args = parser.parse_args()
    run = Run(args.run)
    print(f'Run: {run.path}; namespace: {run.ns}', flush=True)
    try:
        if args.inspect_only:
            inspect(run)
        else:
            prepare(run) if args.prepare_only else test(run)
    except Exception as exc:
        run.result('storage', 'blocked', error=str(exc))
        raise


if __name__ == '__main__':
    main()
