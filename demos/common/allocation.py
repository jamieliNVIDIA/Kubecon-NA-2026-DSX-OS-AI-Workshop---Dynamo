"""Explicit physical-GPU assignments for parallel presenter qualification.

Opt-in only. This pins manifests and selects a scoped lease; the coordinator must
still verify live ownership and disjoint assignments before starting any run.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re


ENV = 'WORKSHOP_ALLOCATION'


def physical_gpus(worker, claim, slices):
    """Resolve claimed devices to distinct physical GPUs on the worker's node."""
    worker_node = worker.get('spec', {}).get('nodeName')
    if not worker_node:
        raise ValueError('Observed worker has no assigned node.')
    advertised = {}
    for item in slices['items']:
        spec = item['spec']
        if spec['driver'] != 'gpu.nvidia.com':
            continue
        for device in spec.get('devices', []):
            key = (spec['pool']['name'], device['name'])
            value = (spec.get('nodeName'), device['attributes']['uuid']['string'])
            if key in advertised and advertised[key] != value:
                raise ValueError('Conflicting physical GPU advertisements.')
            advertised[key] = value
    devices = claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', [])
    observed = []
    for item in devices:
        key = (item.get('pool'), item.get('device'))
        if item.get('driver') != 'gpu.nvidia.com' or key not in advertised:
            raise ValueError('Cannot resolve an allocated NVIDIA GPU to its physical identity.')
        node, uuid = advertised[key]
        if node != worker_node:
            raise ValueError('Allocated GPU is advertised on a different node.')
        if uuid in observed:
            raise ValueError('GPU allocation contains duplicate physical devices.')
        observed.append(uuid)
    return sorted(observed)


class Allocation:
    def __init__(self, root, value):
        self.root = Path(root).resolve()
        if (not isinstance(value, dict) or value.get('schema') != 1 or
                set(value) != {'schema', 'assignment_id', 'lease', 'targets'} or
                not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', value['assignment_id'])):
            raise ValueError('Invalid workshop allocation identity/schema.')
        lease = Path(value['lease'])
        if (lease.is_absolute() or len(lease.parts) != 2 or lease.parts[0] != '.local' or
                not re.fullmatch(r'[a-z0-9-]+\.gpu-lease', lease.name)):
            raise ValueError('Allocation lease must be a named .local/*.gpu-lease directory.')
        targets = value['targets']
        if not isinstance(targets, dict) or 'intro' not in targets or set(targets) - {'intro', 'source', 'native', 'peer'}:
            raise ValueError('Allocation targets require intro and may name source/native/peer.')
        for target in targets.values():
            if (not isinstance(target, dict) or set(target) != {'node', 'gpu_uuids'} or
                    not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', target['node']) or
                    not isinstance(target['gpu_uuids'], list) or len(target['gpu_uuids']) != 2 or
                    len(set(target['gpu_uuids'])) != 2 or not all(
                        isinstance(u, str) and re.fullmatch(
                            r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', u)
                        for u in target['gpu_uuids'])):
                raise ValueError('Each allocation target requires one node and two distinct GPU UUIDs.')
        for a, b in (('intro', 'source'), ('native', 'peer')):
            if a in targets and b in targets and targets[a] != targets[b]:
                raise ValueError('Sequential allocation targets must match: ' + a + '/' + b)
        if 'source' in targets and 'peer' in targets:
            source, peer = targets['source'], targets['peer']
            if source['node'] == peer['node'] or set(source['gpu_uuids']) & set(peer['gpu_uuids']):
                raise ValueError('MX qualification requires distinct nodes and disjoint source/target GPUs.')
        self.value = copy.deepcopy(value)
        self.lease = self.root / lease

    def freeze(self, run, *, existing=False):
        path = Path(run) / 'allocation.json'
        if path.exists():
            if json.loads(path.read_text()) != self.value:
                raise ValueError('Frozen GPU assignment changed; use the original allocation or a fresh run.')
        elif existing:
            raise ValueError('Cannot add an allocation to an existing unassigned demo; use a fresh run.')
        else:
            with path.open('x') as stream:
                stream.write(json.dumps(self.value, indent=2) + '\n')
            path.chmod(0o400)

    def pin(self, graph, claim, role):
        if role not in self.value['targets']:
            raise ValueError('GPU allocation has no target for ' + role)
        target = self.value['targets'][role]
        workers = [c for c in graph['spec']['components'] if c['type'] == 'worker']
        if len(workers) != 1 or workers[0]['replicas'] != 1:
            raise ValueError('Presenter allocation expects exactly one TP2 worker per graph.')
        workers[0]['podTemplate']['spec']['nodeSelector'] = {'kubernetes.io/hostname': target['node']}
        requests = claim['spec']['spec']['devices']['requests']
        if len(requests) != 1 or requests[0]['exactly']['count'] != 2:
            raise ValueError('Presenter allocation requires exactly two DRA GPUs.')
        requests[0]['exactly']['selectors'] = [{'cel': {'expression': (
            'device.driver == "gpu.nvidia.com" && '
            'has(device.attributes["gpu.nvidia.com"].uuid) && '
            'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(target['gpu_uuids']))}}]

    def verify(self, worker, claim, slices, role):
        """Check actual allocation, not only the requested selector or GPU count."""
        target = self.value['targets'][role]
        if worker['spec'].get('nodeName') != target['node']:
            raise ValueError('Observed worker node differs from its frozen assignment.')
        observed = physical_gpus(worker, claim, slices)
        if observed != sorted(target['gpu_uuids']):
            raise ValueError('Actual GPU UUIDs differ from this run\'s frozen assignment.')
        return {'assignment_id': self.value['assignment_id'], 'role': role, 'node': target['node'],
                'gpu_uuids': sorted(observed), 'pod_uid': worker['metadata']['uid'],
                'claim_uid': claim['metadata']['uid'], 'scope': 'Observed placement, not utilization or inference proof.'}


def from_environment(root):
    path = os.environ.get(ENV)
    return Allocation(root, json.loads(Path(path).read_text())) if path else None


def freeze(allocation, run, *, existing=False):
    if allocation is None:
        if (Path(run) / 'allocation.json').exists():
            raise ValueError('This demo has a frozen GPU assignment; set WORKSHOP_ALLOCATION to resume it.')
    else:
        allocation.freeze(run, existing=existing)
