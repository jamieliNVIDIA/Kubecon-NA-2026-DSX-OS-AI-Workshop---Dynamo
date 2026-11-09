#!/usr/bin/env python3
"""Read-only GPU driver ownership, policy and running container inventory."""
import argparse
import json
from pathlib import Path
from testlib import Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    run = Run(parser.parse_args().run)
    policies = run.get('get', 'clusterpolicies.nvidia.com')['items']
    sets = run.get('get', 'daemonsets', '-n', 'gpu-operator')['items']
    pods = run.get('get', 'pods', '-n', 'gpu-operator')['items']
    crd = run.k('get', 'crd', 'nvidiadrivers.nvidia.com', '-o', 'json', check=False)
    drivers = run.get('get', 'nvidiadrivers.nvidia.com')['items'] if crd.returncode == 0 else []
    summary = {
     'cluster_policies': [{'name': p['metadata']['name'], 'driver': p['spec'].get('driver'),
                           'state': p.get('status', {}).get('state')} for p in policies],
     'nvidia_driver_resources': [{'name': d['metadata']['name'], 'spec': d['spec']} for d in drivers],
     'driver_daemonsets': [{'name': d['metadata']['name'], 'owners': d['metadata'].get('ownerReferences', []),
                            'node_selector': d['spec']['template']['spec'].get('nodeSelector'),
                            'status': d.get('status'),
                            'containers': [{'name': c['name'], 'image': c['image']} for c in d['spec']['template']['spec']['containers']]}
                           for d in sets if d['metadata']['name'].startswith('nvidia-driver')],
     'driver_pods': [{'name': p['metadata']['name'], 'node': p['spec'].get('nodeName'),
                       'images': [{'name': c['name'], 'image': c['image'], 'ready': next(
                           (s.get('ready') for s in p.get('status', {}).get('containerStatuses', []) if s['name'] == c['name']), None)}
                                  for c in p['spec']['containers']]}
                      for p in pods if p['metadata']['name'].startswith('nvidia-driver')],
     'scope': 'Read-only; no driver upgrade, node drain, reboot or Helm mutation',
    }
    (run.path / 'driver-management.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
