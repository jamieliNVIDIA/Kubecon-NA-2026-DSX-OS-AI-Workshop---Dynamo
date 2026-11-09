#!/usr/bin/env python3
"""Read-only inventory for Dynamo feature tests; never reads Kubernetes Secrets."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KUBECTL = ROOT / '.local/bin/kubectl'
CONFIG = ROOT / '.local/kubeconfig'


def command(args, *, timeout=60):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def k(*args):
    return json.loads(command([str(KUBECTL), f'--kubeconfig={CONFIG}',
                               '--request-timeout=30s', *args, '-o', 'json']))


def pod_summary(pod):
    spec = pod['spec']
    status = pod.get('status', {})
    return {
        'namespace': pod['metadata']['namespace'],
        'name': pod['metadata']['name'],
        'node': spec.get('nodeName'),
        'phase': status.get('phase'),
        'owners': pod['metadata'].get('ownerReferences', []),
        'containers': [
            {'name': c['name'], 'image': c['image'],
             'resources': c.get('resources', {}),
             'env_names': [v['name'] for v in c.get('env', [])],
             'mounts': c.get('volumeMounts', []),
             'securityContext': c.get('securityContext', {})}
            for c in spec.get('initContainers', []) + spec.get('containers', [])
        ],
        'volumes': [{key: value for key, value in v.items() if key in
                     {'name', 'persistentVolumeClaim', 'hostPath', 'emptyDir'}}
                    for v in spec.get('volumes', [])],
        'container_status': [
            {'name': c['name'], 'ready': c['ready'],
             'restarts': c['restartCount'], 'imageID': c.get('imageID'),
             'state': c.get('state', {})}
            for c in status.get('containerStatuses', [])
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = args.output or ROOT / 'results' / f'{stamp}-inventory'
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    command([str(ROOT / 'scripts/kubecon-tunnel.sh'), 'start'])
    receipt = {'started_at': stamp, 'kind': 'read-only-inventory', 'checks': {}}

    def collect(name, function):
        try:
            data = function()
            target = output / f'{name}.json'
            target.write_text(json.dumps(data, indent=2) + '\n')
            target.chmod(0o600)
            receipt['checks'][name] = {'status': 'collected', 'file': target.name}
            return data
        except Exception as exc:
            receipt['checks'][name] = {'status': 'error', 'error': str(exc)}
            return None

    version = collect('version', lambda: k('version'))
    nodes = collect('nodes', lambda: k('get', 'nodes'))
    collect('namespaces', lambda: k('get', 'namespaces'))
    collect('pods', lambda: [pod_summary(p) for p in k('get', 'pods', '-A')['items']])
    collect('storageclasses', lambda: k('get', 'storageclasses'))
    collect('pvc', lambda: k('get', 'pvc', '-A'))
    collect('services', lambda: k('get', 'services', '-A'))
    collect('resourceclaims', lambda: k('get', 'resourceclaims', '-A'))
    collect('deviceclasses', lambda: k('get', 'deviceclasses'))
    collect('helm', lambda: json.loads(command(['helm', f'--kubeconfig={CONFIG}',
                                               'list', '-A', '-o', 'json'])))
    crds = collect('crd-names', lambda: [c['metadata']['name'] for c in k('get', 'crds')['items']])
    if crds:
        for name in crds:
            if any(part in name for part in ('dynamo', 'snapshot', 'podclique', 'podgang', 'queues.scheduling', 'topology')):
                collect(f'crd-{name}', lambda name=name: k('get', 'crd', name))
    if nodes:
        receipt['nodes'] = [
            {'name': n['metadata']['name'],
             'ready': next((c['status'] for c in n['status']['conditions'] if c['type'] == 'Ready'), None),
             'gpu': n['status']['allocatable'].get('nvidia.com/gpu'),
             'efa': n['status']['allocatable'].get('vpc.amazonaws.com/efa'),
             'kernel': n['status']['nodeInfo']['kernelVersion'],
             'driver': n['metadata'].get('labels', {}).get('nvidia.com/cuda.driver-version.full'),
             'gpu_product': n['metadata'].get('labels', {}).get('nvidia.com/gpu.product'),
             'taints': n['spec'].get('taints', [])}
            for n in nodes['items']
        ]
    if version:
        receipt['api_version'] = version['serverVersion']['gitVersion']
    receipt['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'output': str(output), **receipt}, indent=2))


if __name__ == '__main__':
    main()
