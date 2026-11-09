"""Opt-in physical-GPU pins for presenters staged side by side on workshop day.

Read only when a run is created: the pins go into the run's frozen manifests, and
the run records the placement so actual allocations can be checked once scheduled.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re

from demos.common.allocation import physical_gpus

ENV = 'WORKSHOP_PLACEMENT'
UUID = r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'


def validate(value, demo, roles):
    """roles maps each role to its worker count; each worker gets two GPUs on its own node."""
    if (not isinstance(value, dict) or set(value) != {'schema', 'demo', 'targets'} or
            value['schema'] != 1 or value['demo'] != demo):
        raise ValueError(ENV + ' must name a schema 1 placement for ' + demo + '.')
    targets = value['targets']
    if not isinstance(targets, dict) or set(targets) != set(roles):
        raise ValueError('Placement targets must be exactly: ' + ', '.join(roles) + '.')
    seen = set()
    for role, count in roles.items():
        entries = targets[role]
        if not isinstance(entries, list) or len(entries) != count:
            raise ValueError('Placement role ' + role + ' needs ' + str(count) + ' worker target(s).')
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {'node', 'gpu_uuids'} or
                    not isinstance(entry['node'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', entry['node']) or
                    not isinstance(entry['gpu_uuids'], list) or len(entry['gpu_uuids']) != 2 or
                    not all(isinstance(u, str) and re.fullmatch(UUID, u) for u in entry['gpu_uuids'])):
                raise ValueError('Each placement target requires one node and two GPU UUIDs.')
            if len(set(entry['gpu_uuids'])) != 2 or seen & set(entry['gpu_uuids']):
                raise ValueError('A GPU UUID appears twice in the placement.')
            seen |= set(entry['gpu_uuids'])
        if len({entry['node'] for entry in entries}) != count:
            raise ValueError('Workers of one role need distinct nodes: ' + role + '.')
    return copy.deepcopy(value)


def from_environment(demo, roles):
    path = os.environ.get(ENV)
    return validate(json.loads(Path(path).read_text()), demo, roles) if path else None


def resolve(recorded, demo, roles, *, existing):
    """A new run takes the requested placement; an existing run keeps the one it recorded."""
    requested = from_environment(demo, roles)
    if not existing:
        return requested
    if requested is not None and requested != recorded:
        raise ValueError('This run ' + ('recorded a different' if recorded else 'has no') +
                         ' GPU placement; unset ' + ENV + ' to resume it.')
    return recorded


def pin(spec, claim, entries):
    """Restrict one worker component to its role's nodes and its claim template to their GPUs."""
    requests = claim['spec']['spec']['devices']['requests']
    if len(requests) != 1 or requests[0]['exactly']['count'] != 2:
        raise ValueError('Placement pins require one two-GPU DRA request.')
    nodes = [entry['node'] for entry in entries]
    terms = (spec.setdefault('affinity', {}).setdefault('nodeAffinity', {})
             .setdefault('requiredDuringSchedulingIgnoredDuringExecution', {})
             .setdefault('nodeSelectorTerms', [{}]))
    for term in terms:
        term.setdefault('matchExpressions', []).append(
            {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': nodes})
    requests[0]['exactly']['selectors'] = [{'cel': {'expression': (
        'device.driver == "gpu.nvidia.com" && '
        'has(device.attributes["gpu.nvidia.com"].uuid) && '
        'device.attributes["gpu.nvidia.com"].uuid in ' +
        json.dumps([uuid for entry in entries for uuid in entry['gpu_uuids']]))}}]


def verify(worker, claim, slices, entries):
    """Check one scheduled worker's actual node and GPUs, not only the requested pins."""
    node = worker['spec'].get('nodeName')
    target = next((entry for entry in entries if entry['node'] == node), None)
    if target is None:
        raise ValueError('Worker was scheduled outside its pinned nodes: ' + str(node))
    observed = physical_gpus(worker, claim, slices)
    if observed != sorted(target['gpu_uuids']):
        raise ValueError('Worker GPUs differ from the pinned pair on ' + node + '.')
    return {'node': node, 'gpu_uuids': observed, 'pod_uid': worker['metadata']['uid'],
            'claim_uid': claim['metadata']['uid']}
