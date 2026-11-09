"""Parallel live qualification must retain exact GPU placement on resume."""
from tests.support import ROOT
import copy
import json
from pathlib import Path
import tempfile
import unittest

from demos.common.allocation import Allocation, freeze, physical_gpus
import demos.common.runtime as ui


def assignment():
    source = {'node': 'node-a', 'gpu_uuids': [
        'GPU-00000000-0000-0000-0000-000000000001', 'GPU-00000000-0000-0000-0000-000000000002']}
    peer = {'node': 'node-b', 'gpu_uuids': [
        'GPU-00000000-0000-0000-0000-000000000003', 'GPU-00000000-0000-0000-0000-000000000004']}
    return {'schema': 1, 'assignment_id': 'test', 'lease': '.local/test.gpu-lease',
            'targets': {'intro': source, 'source': source, 'native': peer, 'peer': peer}}


class AllocationTests(unittest.TestCase):
    def test_exact_devices_and_node_reach_executable_manifest(self):
        graph, claim = ui.render('test', ui.read_json(ui.MODEL_LOCK))
        candidate = Allocation(ROOT, assignment())
        candidate.pin(graph, claim, 'peer')
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(worker['podTemplate']['spec']['nodeSelector'], {'kubernetes.io/hostname': 'node-b'})
        spec = claim['spec']['spec']['devices']['requests'][0]['exactly']
        self.assertEqual(spec['count'], 2)
        expression = spec['selectors'][0]['cel']['expression']
        self.assertIn('has(device.attributes', expression)
        for uuid in assignment()['targets']['peer']['gpu_uuids']:
            self.assertIn(uuid, expression)
        candidate.pin(graph, claim, 'source')
        self.assertNotIn(assignment()['targets']['peer']['gpu_uuids'][0],
                         json.dumps(claim))

    def test_matched_arms_cannot_silently_use_different_devices(self):
        value = copy.deepcopy(assignment())
        value['targets']['native'] = copy.deepcopy(value['targets']['native'])
        value['targets']['native']['gpu_uuids'][0] = 'GPU-00000000-0000-0000-0000-000000000099'
        with self.assertRaises(ValueError):
            Allocation(ROOT, value)

    def test_cross_node_mx_rejects_gpu_overlap(self):
        value = copy.deepcopy(assignment())
        value['targets']['peer']['gpu_uuids'][0] = value['targets']['source']['gpu_uuids'][0]
        with self.assertRaises(ValueError):
            Allocation(ROOT, value)

    def test_lease_cannot_escape_named_local_directory(self):
        for name in ('/tmp/lease', '.local/../lease', '.local/nested/x.gpu-lease'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Allocation(ROOT, {**assignment(), 'lease': name})

    def test_resume_requires_same_explicit_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Allocation(ROOT, assignment())
            candidate.freeze(directory)
            candidate.freeze(directory, existing=True)
            with self.assertRaises(ValueError):
                freeze(None, directory, existing=True)
            changed = assignment()
            changed['assignment_id'] = 'changed'
            with self.assertRaises(ValueError):
                Allocation(ROOT, changed).freeze(directory, existing=True)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            candidate.freeze(directory, existing=True)

    def test_same_gpu_count_cannot_qualify_wrong_physical_devices(self):
        candidate = Allocation(ROOT, assignment())
        uuids = assignment()['targets']['intro']['gpu_uuids']
        worker = {'metadata': {'uid': 'worker'}, 'spec': {'nodeName': 'node-a'}}
        claim = {'metadata': {'uid': 'claim'}, 'status': {'allocation': {'devices': {'results': [
            {'driver': 'gpu.nvidia.com', 'pool': 'node-a', 'device': name} for name in ('gpu0', 'gpu1')]}}}}
        slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'node-a', 'pool': {'name': 'node-a'},
            'devices': [{'name': 'gpu' + str(i), 'attributes': {'uuid': {'string': uuid}}}
                        for i, uuid in enumerate(uuids)]}}]}
        self.assertEqual(candidate.verify(worker, claim, slices, 'intro')['gpu_uuids'], uuids)
        wrong = copy.deepcopy(slices)
        wrong['items'][0]['spec']['devices'][1]['attributes']['uuid']['string'] = assignment()['targets']['peer']['gpu_uuids'][1]
        with self.assertRaises(ValueError):
            candidate.verify(worker, claim, wrong, 'intro')
        worker['spec']['nodeName'] = 'node-b'
        with self.assertRaises(ValueError):
            candidate.verify(worker, claim, slices, 'intro')

    def test_gpu_claim_drift_is_rejected_before_preparation(self):
        from types import SimpleNamespace
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            demo = ui.Demo(SimpleNamespace(run=Path(directory), rehearsal=True, action='run', preview=False, auto=True))
            path = demo.path / 'gpu-claim-template.yaml'
            path.write_text(path.read_text().replace('count: 2', 'count: 4'))
            with mock.patch.object(demo.run, 'apply') as apply, self.assertRaises(ValueError):
                demo.prepare()
            apply.assert_not_called()

    def test_physical_resolution_rejects_wrong_node_unknown_driver_and_conflicts(self):
        worker = {'spec': {'nodeName': 'node-a'}}
        claim = {'status': {'allocation': {'devices': {'results': [
            {'driver': 'gpu.nvidia.com', 'pool': 'node-a', 'device': 'gpu0'}]}}}}
        slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'node-a',
            'pool': {'name': 'node-a'}, 'devices': [{'name': 'gpu0', 'attributes': {
                'uuid': {'string': assignment()['targets']['intro']['gpu_uuids'][0]}}}]}}]}
        self.assertEqual(physical_gpus(worker, claim, slices), assignment()['targets']['intro']['gpu_uuids'][:1])

        wrong_node = copy.deepcopy(slices)
        wrong_node['items'][0]['spec']['nodeName'] = 'node-b'
        wrong_driver = copy.deepcopy(claim)
        wrong_driver['status']['allocation']['devices']['results'][0]['driver'] = 'other.example'
        unknown_device = copy.deepcopy(claim)
        unknown_device['status']['allocation']['devices']['results'][0]['device'] = 'missing'
        conflict = copy.deepcopy(slices)
        conflict['items'].append(copy.deepcopy(conflict['items'][0]))
        conflict['items'][1]['spec']['devices'][0]['attributes']['uuid']['string'] = assignment()['targets']['intro']['gpu_uuids'][1]
        duplicate = copy.deepcopy(claim)
        duplicate['status']['allocation']['devices']['results'] *= 2
        for observed_worker, observed_claim, observed_slices in (
                ({'spec': {}}, claim, slices), (worker, claim, wrong_node),
                (worker, wrong_driver, slices), (worker, unknown_device, slices),
                (worker, claim, conflict), (worker, duplicate, slices)):
            with self.subTest(worker=observed_worker, claim=observed_claim, slices=observed_slices), \
                    self.assertRaises(ValueError):
                physical_gpus(observed_worker, observed_claim, observed_slices)


if __name__ == '__main__':
    unittest.main()
