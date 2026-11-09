"""Opt-in GPU pins for presenters staged side by side must be exact and verifiable."""
from tests.support import ROOT
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from demos.common import placement

A = ['GPU-00000000-0000-0000-0000-00000000000a', 'GPU-00000000-0000-0000-0000-00000000000b']
B = ['GPU-00000000-0000-0000-0000-00000000000c', 'GPU-00000000-0000-0000-0000-00000000000d']
C = ['GPU-00000000-0000-0000-0000-00000000000e', 'GPU-00000000-0000-0000-0000-00000000000f']
ROLES = {'disabled': 2, 'enabled': 1}


def value():
    return {'schema': 1, 'demo': 'request-continuity', 'targets': {
        'disabled': [{'node': 'node-a', 'gpu_uuids': list(A)}, {'node': 'node-b', 'gpu_uuids': list(B)}],
        'enabled': [{'node': 'node-a', 'gpu_uuids': list(C)}]}}


def claim():
    return {'spec': {'spec': {'devices': {'requests': [
        {'name': 'gpu', 'exactly': {'deviceClassName': 'gpu.nvidia.com', 'count': 2}}]}}}}


def slices():
    devices = {'node-a': A + C, 'node-b': B}
    return {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': node, 'pool': {'name': node},
                                'devices': [{'name': 'gpu-' + str(i), 'attributes': {'uuid': {'string': uuid}}}
                                            for i, uuid in enumerate(uuids)]}}
                      for node, uuids in devices.items()]}


def allocated(node, indexes):
    return {'metadata': {'uid': 'claim-uid'}, 'status': {'allocation': {'devices': {'results': [
        {'driver': 'gpu.nvidia.com', 'pool': node, 'device': 'gpu-' + str(i)} for i in indexes]}}}}


def worker(node):
    return {'metadata': {'uid': 'pod-uid'}, 'spec': {'nodeName': node}}


class PlacementTests(unittest.TestCase):
    def test_validate_accepts_one_target_per_worker_and_returns_a_copy(self):
        original = value()
        accepted = placement.validate(original, 'request-continuity', ROLES)
        self.assertEqual(accepted, original)
        accepted['targets']['enabled'][0]['node'] = 'changed'
        self.assertEqual(original['targets']['enabled'][0]['node'], 'node-a')

    def test_validate_rejects_ambiguous_or_overlapping_assignments(self):
        cases = {
            'demo': lambda v: v.update(demo='disaggregated'),
            'schema': lambda v: v.update(schema=2),
            'extra key': lambda v: v.update(lease='.local/x.gpu-lease'),
            'missing role': lambda v: v['targets'].pop('enabled'),
            'worker count': lambda v: v['targets']['enabled'].append({'node': 'node-b', 'gpu_uuids': list(C)}),
            'shared node': lambda v: v['targets']['disabled'][1].update(node='node-a'),
            'reused GPU': lambda v: v['targets']['enabled'][0].update(gpu_uuids=[A[0], C[1]]),
            'duplicate GPU': lambda v: v['targets']['enabled'][0].update(gpu_uuids=[C[0], C[0]]),
            'GPU count': lambda v: v['targets']['enabled'][0].update(gpu_uuids=C + [A[0]]),
            'UUID form': lambda v: v['targets']['enabled'][0].update(gpu_uuids=['gpu-6', 'gpu-7']),
            'node form': lambda v: v['targets']['enabled'][0].update(node='Node A'),
        }
        for name, change in cases.items():
            with self.subTest(name):
                broken = value()
                change(broken)
                with self.assertRaises(ValueError):
                    placement.validate(broken, 'request-continuity', ROLES)

    def test_pin_adds_node_and_gpu_selectors_without_dropping_existing_terms(self):
        spec = {'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {
            'nodeSelectorTerms': [{'matchExpressions': [
                {'key': 'nvidia.com/gpu.product', 'operator': 'In', 'values': ['NVIDIA-H100-80GB-HBM3']}]}]}}}}
        template = claim()
        placement.pin(spec, template, value()['targets']['disabled'])
        term = spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]
        self.assertEqual(term['matchExpressions'], [
            {'key': 'nvidia.com/gpu.product', 'operator': 'In', 'values': ['NVIDIA-H100-80GB-HBM3']},
            {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['node-a', 'node-b']}])
        request = template['spec']['spec']['devices']['requests'][0]['exactly']
        self.assertEqual(request['count'], 2)
        expression = request['selectors'][0]['cel']['expression']
        self.assertTrue(expression.endswith('.uuid in ' + json.dumps(A + B)))
        self.assertIn('has(device.attributes["gpu.nvidia.com"].uuid)', expression)

    def test_pin_refuses_other_claim_shapes(self):
        for change in (lambda c: c['spec']['spec']['devices']['requests'].append(copy.deepcopy(
                           c['spec']['spec']['devices']['requests'][0])),
                       lambda c: c['spec']['spec']['devices']['requests'][0]['exactly'].update(count=1)):
            template = claim()
            change(template)
            with self.assertRaises(ValueError):
                placement.pin({}, template, value()['targets']['enabled'])

    def test_verify_requires_the_pinned_pair_on_the_observed_node(self):
        entries = value()['targets']['disabled']
        proof = placement.verify(worker('node-b'), allocated('node-b', [1, 0]), slices(), entries)
        self.assertEqual(proof, {'node': 'node-b', 'gpu_uuids': sorted(B), 'pod_uid': 'pod-uid',
                                 'claim_uid': 'claim-uid'})
        with self.assertRaisesRegex(ValueError, 'outside its pinned nodes'):
            placement.verify(worker('node-c'), allocated('node-b', [0, 1]), slices(), entries)
        with self.assertRaisesRegex(ValueError, 'differ from the pinned pair'):
            # node-a also advertises the enabled case's GPUs; only A is this role's pair there.
            placement.verify(worker('node-a'), allocated('node-a', [0, 2]), slices(), entries)

    def test_new_runs_take_the_requested_file_and_existing_runs_keep_theirs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'placement.json'
            path.write_text(json.dumps(value()))
            with mock.patch.dict(os.environ, {placement.ENV: str(path)}):
                self.assertEqual(placement.resolve(None, 'request-continuity', ROLES, existing=False), value())
                self.assertEqual(placement.resolve(value(), 'request-continuity', ROLES, existing=True), value())
                with self.assertRaisesRegex(ValueError, 'has no GPU placement'):
                    placement.resolve(None, 'request-continuity', ROLES, existing=True)
                other = value()
                other['targets']['enabled'][0]['node'] = 'node-b'
                with self.assertRaisesRegex(ValueError, 'recorded a different GPU placement'):
                    placement.resolve(other, 'request-continuity', ROLES, existing=True)
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(placement.resolve(None, 'request-continuity', ROLES, existing=False))
                self.assertEqual(placement.resolve(value(), 'request-continuity', ROLES, existing=True), value())


if __name__ == '__main__':
    unittest.main()
