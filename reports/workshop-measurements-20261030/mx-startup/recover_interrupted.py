#!/usr/bin/env python3
"""Collect an interrupted MX run and verify owned cleanup before lease release."""
import argparse
import json
from pathlib import Path
import time

import measure_startup as base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--recovery', required=True)
    args = parser.parse_args()
    run = base.setup_run(args.run)
    dest = run.path / args.recovery
    if not (dest / 'pre-recovery-integrity.json').is_file():
        raise ValueError('Preserve and verify the previous integrity inventory first')
    lease = json.loads((base.LEASE / 'owner.json').read_text())
    if lease['agent'] != base.OWNER or lease['run'] != str(run.path):
        raise ValueError('This is not the interrupted MX workstream lease')
    (dest / 'lease-before.json').write_text(json.dumps(lease, indent=2) + '\n')
    base.collect(run, args.recovery + '/remote-before-cleanup')
    for kind in ('resourceclaims', 'services', 'endpoints'):
        (dest / (kind + '-before.json')).write_text(json.dumps(
            run.get('get', kind, '-n', run.ns), indent=2) + '\n')

    for graph in ('ft-mx-target', 'ft-mx'):
        base.stop_graph(run, graph)
    for name in ('mx-coordinator', 'mx-redis'):
        found = run.k('get', 'pod', name, '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0:
            obj = json.loads(found.stdout)
            if obj['metadata']['labels'].get('feature-test-run') != run.ns:
                raise ValueError('Refusing to delete an unowned coordinator Pod')
            run.k('delete', 'pod', name, '-n', run.ns,
                  '--wait=true', '--timeout=90s', timeout=120)

    deadline = time.monotonic() + 180
    while True:
        pods = run.get('get', 'pods', '-n', run.ns)
        claims = run.get('get', 'resourceclaims', '-n', run.ns)
        gpu_pods = [pod['metadata']['name'] for pod in pods['items']
                    if any(container.get('resources', {}).get('claims')
                           for container in pod['spec'].get('containers', []))]
        graphs = run.get('get', 'dgd', '-n', run.ns)
        if not gpu_pods and not claims['items'] and not graphs['items']:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Owned GPU resources remain; retaining lease')
        time.sleep(3)
    for name, obj in [('pods-after.json', pods), ('resourceclaims-after.json', claims),
                      ('graphs-after.json', graphs)]:
        (dest / name).write_text(json.dumps(obj, indent=2) + '\n')
    proof = {'verified_at': base.now(), 'namespace': run.ns,
             'gpu_pods': gpu_pods, 'resourceclaims': len(claims['items']),
             'graphs': len(graphs['items']),
             'scope': 'Both GPU Pod and ResourceClaim absence independently verified before lease release'}
    (dest / 'cleanup-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    base.release(run)
    proof['lease_absent_after_release'] = not base.LEASE.exists()
    (dest / 'cleanup-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    run.result('mx-artifact03-connectivity-recovery', 'passed', **proof)
    print(json.dumps(proof), flush=True)


if __name__ == '__main__':
    main()
