#!/usr/bin/env python3
"""Read-only GPU and kernel evidence after a failed Snapshot capture; no reset."""
import argparse
import datetime as dt
import json
from pathlib import Path
import time

from testlib import Run


def inspect(run, baseline, node_name):
    before = json.loads((baseline / 'nodes.json').read_text())['items']
    previous = next(n for n in before if n['metadata']['name'] == node_name)
    node = run.get('get', 'node', node_name)
    prior = {c['type']: c for c in previous['status']['conditions']}
    changed = [c for c in node['status']['conditions']
               if c['status'] != prior.get(c['type'], {}).get('status')]
    pods = run.get('get', 'pods', '-A')['items']
    drivers = [p for p in pods if p['spec'].get('nodeName') == node_name
               and p['status'].get('phase') == 'Running'
               and any(c['name'] == 'nvidia-driver-ctr' for c in p['spec']['containers'])]
    if len(drivers) != 1:
        raise ValueError('Expected exactly one running driver Pod on the requested node')
    pod = drivers[0]
    suffix = str(time.time_ns())
    prefix = run.path / ('snapshot-gpu-health-' + suffix)
    outputs = {}
    for key, command in (
        ('nvidia-smi', ['nvidia-smi', '-q', '-x']),
        ('kernel', ['bash', '-o', 'pipefail', '-c', "dmesg --time-format iso | "
                    "awk '/NVRM|Xid|nvidia|NVLink|SXid|ECC/' | tail -240"]),
        ('kernel-xids', ['bash', '-o', 'pipefail', '-c', "dmesg --time-format iso | "
                         "awk '/NVRM: Xid/' | tail -160"]),
    ):
        result = run.k('exec', pod['metadata']['name'], '-n', pod['metadata']['namespace'],
                       '-c', 'nvidia-driver-ctr', '--', *command, check=False, timeout=45)
        file = Path(str(prefix) + '-' + key + '.log')
        file.write_text(result.stdout + result.stderr)
        outputs[key] = {'file': file.name, 'exit_code': result.returncode}
    report = {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'node': node_name, 'baseline': str(baseline.resolve()),
              'driver_pod_uid': pod['metadata']['uid'],
              'changed_conditions': changed, 'outputs': outputs,
              'node_status': node['status'],
              'scope': 'Read-only node conditions, nvidia-smi and kernel logs; no GPU reset'}
    Path(str(prefix) + '.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'node_status'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--node', default='kubecon-nke-site-cp-0124')
    args = parser.parse_args()
    inspect(Run(args.run), args.baseline, args.node)


if __name__ == '__main__':
    main()
