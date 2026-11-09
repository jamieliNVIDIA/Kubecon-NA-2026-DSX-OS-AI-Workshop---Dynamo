#!/usr/bin/env python3
"""Run bounded feature checks in an owned, isolated namespace."""
import argparse
import json
from pathlib import Path
from testlib import ROOT, Run

BASE_IMAGE = 'nvcr.io/nvidia/ai-dynamo/vllm-runtime@sha256:b23ce9e87c413725024ddfd2e06c1e7da220eb48f8a93037f0b01d564b54bd13'


def probe(run, image, efa=False, node_count=None):
    run.ensure_namespace()
    nodes = run.get('get', 'nodes')['items']
    nodes = [n for n in nodes if int(n['status']['allocatable'].get('nvidia.com/gpu', 0)) >= 1]
    if node_count is not None:
        nodes = nodes[:node_count]
    code = (ROOT / 'scripts/runtime_probe.py').read_text()
    data = {'probe.py': code}
    if efa:
        data['check-efa-userspace.sh'] = (ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh').read_text()
        data['entrypoint.sh'] = (ROOT / 'scripts/efa-entrypoint.sh').read_text()
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'runtime-probe'},
                'data': data}])
    pods = []
    for index, node in enumerate(nodes):
        name = f'runtime-probe-{index}'
        pods.append({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name},
            'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 900,
                'automountServiceAccountToken': False,
                'nodeSelector': {'kubernetes.io/hostname': node['metadata']['name']},
                'containers': [{'name': 'probe', 'image': image,
                    'command': (['bash', '/tests/entrypoint.sh', 'python3', '/tests/probe.py'] if efa else ['python3', '/tests/probe.py']),
                    'resources': {'requests': {'cpu': '1', 'memory': '8Gi', 'nvidia.com/gpu': '1', 'vpc.amazonaws.com/efa': '4'},
                                  'limits': {'memory': '16Gi', 'nvidia.com/gpu': '1', 'vpc.amazonaws.com/efa': '4'}},
                    'securityContext': {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK']}},
                    'volumeMounts': [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]}],
                'volumes': [{'name': 'tests', 'configMap': {'name': 'runtime-probe'}}]}})
    run.apply(pods)
    reports = []
    try:
        for pod in pods:
            completed = run.wait_pod(pod['metadata']['name'], completed=True, timeout=900)
            logs = run.k('logs', pod['metadata']['name'], '-n', run.ns).stdout
            (run.path / f'{pod["metadata"]["name"]}.log').write_text(logs)
            marker = logs.rfind('\n{')
            report = json.loads(logs[marker + 1:] if marker >= 0 else logs)
            report['node'] = pod['spec']['nodeSelector']['kubernetes.io/hostname']
            report['image_id'] = completed['status']['containerStatuses'][0].get('imageID')
            reports.append(report)
        (run.path / 'runtime-reports.json').write_text(json.dumps(reports, indent=2) + '\n')
        run.result('runtime-probe', 'passed' if all(r.get('gpu_arithmetic_ok') for r in reports) else 'failed',
                   image=image, reports=reports,
                   scope='GPU arithmetic, packages, EFA device/provider visibility; not transfer qualification')
    finally:
        for pod in pods:
            run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


def inspect(run):
    for resource in ('persistentvolumes', 'dynamographdeployments', 'pods', 'queues.scheduling.run.ai'):
        args = ['get', resource]
        if resource in {'dynamographdeployments', 'pods'}:
            args.append('-A')
        data = run.get(*args)
        if resource == 'pods':
            data = {'items': [{'namespace': p['metadata']['namespace'], 'name': p['metadata']['name'],
                              'phase': p.get('status', {}).get('phase')}
                             for p in data['items']]}
        (run.path / f'{resource}.json').write_text(json.dumps(data, indent=2) + '\n')
    run.result('inspection', 'collected', output=str(run.path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['probe', 'inspect'])
    parser.add_argument('--run', type=Path)
    parser.add_argument('--image', default=BASE_IMAGE)
    parser.add_argument('--efa', action='store_true', help='Install pinned EFA userspace inside the disposable container')
    parser.add_argument('--node-count', type=int, choices=[1, 2, 3])
    args = parser.parse_args()
    run = Run(args.run)
    print(f'Run: {run.path}; namespace: {run.ns}', flush=True)
    try:
        if args.action == 'probe':
            probe(run, args.image, args.efa, args.node_count)
        else:
            inspect(run)
    except Exception as exc:
        run.result(args.action, 'blocked', error=str(exc))
        raise


if __name__ == '__main__':
    main()
