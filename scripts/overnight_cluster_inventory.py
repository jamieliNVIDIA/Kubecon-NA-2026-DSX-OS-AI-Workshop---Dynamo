#!/usr/bin/env python3
"""Read-only allocation/budget audit for the November 4 overnight demo runs."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOCATIONS = ROOT / 'reports/overnight-2026-11-04/allocations.json'


def audit(allocations, nodes, slices, claims, pods, dgds):
    expected = {}
    by_uuid = {}
    for name, slot in allocations['allocations'].items():
        for node, uuids in slot['gpu_uuids_by_node'].items():
            for uuid in uuids:
                if uuid in by_uuid:
                    raise ValueError('Duplicate GPU reservation: ' + uuid)
                by_uuid[uuid] = (name, node)
    for item in slices['items']:
        spec = item['spec']
        if spec['driver'] != 'gpu.nvidia.com':
            continue
        for device in spec['devices']:
            key = (spec['pool']['name'], device['name'])
            uuid = device['attributes']['uuid']['string']
            if key in expected:
                raise ValueError('Duplicate advertised physical device: ' + str(key))
            expected[key] = {'uuid': uuid, 'node': spec['nodeName'],
                             'assignment': by_uuid.get(uuid, (None, None))[0]}

    issues = []
    used = {}
    claim_records = []
    for claim in claims['items']:
        metadata = claim['metadata']
        devices = []
        for item in claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', []):
            if item['driver'] != 'gpu.nvidia.com':
                continue
            key = (item['pool'], item['device'])
            physical = expected.get(key)
            if physical is None:
                issues.append('Unknown physical GPU in claim ' + metadata['name'])
                continue
            uuid = physical['uuid']
            if uuid in used:
                issues.append('GPU allocated twice: ' + uuid)
            used[uuid] = metadata['namespace'] + '/' + metadata['name']
            if physical['assignment'] is None:
                issues.append('GPU outside overnight reservations: ' + uuid)
            elif by_uuid[uuid][1] != physical['node']:
                issues.append('Reserved GPU changed node: ' + uuid)
            devices.append(dict(physical, device=item['device'], pool=item['pool']))
        if devices:
            names = {d['assignment'] for d in devices}
            if len(names) != 1:
                issues.append('Claim crosses workstream reservations: ' + metadata['name'])
            claim_records.append({'namespace': metadata['namespace'], 'name': metadata['name'],
                                  'uid': metadata['uid'], 'devices': devices,
                                  'reserved_for': claim.get('status', {}).get('reservedFor', [])})

    # Scheduling sums container requests, but init containers may set a larger
    # peak. EFA is ordinary container-only in these frozen workshop templates.
    # Report init requests too rather than silently treating them as zero.
    efa = {n['metadata']['name']: {'allocatable': int(n['status']['allocatable'].get('vpc.amazonaws.com/efa', '0')),
                                  'requested_running_or_pending': 0, 'pods': []} for n in nodes['items']}
    gpu_pods = []
    for pod in pods['items']:
        meta, spec, status = pod['metadata'], pod['spec'], pod.get('status', {})
        if status.get('phase') in ('Failed', 'Succeeded'):
            continue
        node = spec.get('nodeName')
        main_efa = sum(int(c.get('resources', {}).get('requests', {}).get('vpc.amazonaws.com/efa', '0'))
                       for c in spec.get('containers', []))
        init_efa = max([int(c.get('resources', {}).get('requests', {}).get('vpc.amazonaws.com/efa', '0'))
                        for c in spec.get('initContainers', [])] or [0])
        request = max(main_efa, init_efa)
        if request and node in efa:
            efa[node]['requested_running_or_pending'] += request
            efa[node]['pods'].append({'namespace': meta['namespace'], 'name': meta['name'], 'efa': request})
        if spec.get('resourceClaims') or any(int(c.get('resources', {}).get('limits', {}).get('nvidia.com/gpu', '0'))
                                           for c in spec.get('containers', [])):
            gpu_pods.append({'namespace': meta['namespace'], 'name': meta['name'], 'uid': meta['uid'],
                             'node': node, 'phase': status.get('phase'),
                             'ready': any(c['type'] == 'Ready' and c['status'] == 'True' for c in status.get('conditions', [])),
                             'containers': [{'name': c['name'], 'ready': c.get('ready'), 'restarts': c.get('restartCount'),
                                             'state': c.get('state')} for c in status.get('containerStatuses', [])],
                             'deletion_timestamp': meta.get('deletionTimestamp')})
    for node, budget in efa.items():
        if budget['requested_running_or_pending'] > budget['allocatable']:
            issues.append('EFA request oversubscription on ' + node)

    assigned = {name: {'owner': slot['owner'],
                       'reserved_gpus': sum(len(v) for v in slot['gpu_uuids_by_node'].values()),
                       'allocated_gpus': sum(uuid in used for uuids in slot['gpu_uuids_by_node'].values() for uuid in uuids)}
                for name, slot in allocations['allocations'].items()}
    return {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'scope': 'Read-only placement and scheduling audit; not utilization or demo qualification',
            'advertised_gpus': len(expected), 'allocated_gpus': len(used),
            'assignments': assigned, 'claims': claim_records, 'gpu_pods': gpu_pods,
            'efa': efa, 'dgd_count': len(dgds['items']), 'issues': issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allocations', type=Path, default=DEFAULT_ALLOCATIONS)
    parser.add_argument('--output', type=Path, required=True,
                        help='New private snapshot directory, never overwritten.')
    parser.add_argument('--offline-source', type=Path,
                        help='Read existing nodes/slices/claims/pods/dgds JSON instead of querying the cluster.')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refuse to overwrite an inventory snapshot')
    args.output.mkdir(mode=0o700, parents=True)
    allocations = json.loads(args.allocations.read_text())
    values = {}
    for key, resource in [('nodes', 'nodes'), ('slices', 'resourceslices'), ('claims', 'resourceclaims'),
                          ('pods', 'pods'), ('dgds', 'dgd')]:
        if args.offline_source:
            raw = (args.offline_source / (key + '.json')).read_text()
        else:
            argv = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'),
                    '--request-timeout=30s', 'get', resource]
            if key in ('claims', 'pods', 'dgds'):
                argv.append('-A')
            argv += ['-o', 'json']
            completed = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=45)
            raw = completed.stdout
        (args.output / (key + '.json')).write_text(raw)
        values[key] = json.loads(raw)
    report = audit(allocations, **values)
    report['offline'] = args.offline_source is not None
    (args.output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'observed_at': report['observed_at'], 'offline': report['offline'],
                      'advertised_gpus': report['advertised_gpus'], 'allocated_gpus': report['allocated_gpus'],
                      'assignments': report['assignments'], 'issues': report['issues']}, indent=2))
    if report['issues']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
