"""The second replica must retain the first replica's identity and storage evidence."""
from tests.support import ROOT
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

from demos.common import runtime as ui
from demos.common import weights
from demos.modelexpress import source


class SourceFixture:
    def __init__(self, path):
        self.path = Path(path)
        self.ns = 'dynamo-ft-retained-intro'
        lock = ui.read_json(ui.MODEL_LOCK)
        self.graph, claim_template = ui.render(self.ns, lock)
        self.graph['metadata'].update(uid='graph-uid', labels={'feature-test-run': self.ns})
        self.graph['status'] = {'conditions': [{'type': 'Ready', 'status': 'True'}]}
        self.service = weights.source_service(self.ns, lock, {'feature-test-run': self.ns})
        self.service['metadata']['uid'] = 'service-uid'
        self.pods = []
        for role in ('worker', 'frontend'):
            component = next(c for c in self.graph['spec']['components'] if c['type'] == role)
            pod = copy.deepcopy(component['podTemplate'])
            pod['metadata'].update(name='intro-' + role, uid=role + '-uid')
            pod['spec']['nodeName'] = 'node-a'
            pod['status'] = {'conditions': [{'type': 'Ready', 'status': 'True'}],
                             'podIP': '10.0.0.1', 'containerStatuses': [
                                 {'name': 'main', 'restartCount': 0,
                                  'imageID': lock['runtime_image']}]}
            if role == 'worker':
                pod['status']['resourceClaimStatuses'] = [{'name': 'gpu-main', 'resourceClaimName': 'intro-gpus'}]
                env = pod['spec']['containers'][0]['env']
                env.append({'name': 'DYN_COMPONENT', 'value': 'agg'})
                next(e for e in env if e['name'] == 'MX_WORKER_HOST')['valueFrom']['fieldRef']['apiVersion'] = 'v1'
            self.pods.append(pod)
        self.claim = {'metadata': {'name': 'intro-gpus', 'uid': 'claim-uid',
                                  'ownerReferences': [{'kind': 'Pod', 'uid': 'worker-uid'}]},
                      'status': {'reservedFor': [{'uid': 'worker-uid'}], 'allocation': {'devices': {'results': [
                          {'driver': 'gpu.nvidia.com', 'pool': 'node-a', 'device': 'gpu-' + str(i)}
                          for i in range(2)]}}}}
        self.slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'node-a',
                                         'pool': {'name': 'node-a'}, 'devices': [
                                             {'name': 'gpu-' + str(i), 'attributes': {
                                                 'uuid': {'string': 'physical-gpu-' + str(i)}}}
                                             for i in range(2)]}}]}
        self.endpoints = {'items': [{'endpoints': [{'conditions': {'ready': True},
                                                  'targetRef': {'uid': 'worker-uid'},
                                                  'addresses': ['10.0.0.1']}]}]}
        self.write_yaml('deployment.yaml', self.graph)
        self.write_yaml('gpu-claim-template.yaml', claim_template)
        self.write_yaml('source-service.yaml', self.service)
        ui.write_json(self.path / 'state.json', {'owner': 'kubecon-dynamo-feature-tests', 'namespace': self.ns})
        ui.write_json(self.path / 'ready-pods.json', {'items': self.pods})
        (self.path / 'worker.log').write_text(
            '[Worker 0] Trying strategy: instant_tensor\n'
            'Loading safetensors using InstantTensor loader: 100% Completed\n'
            '(Worker_TP0) Model loading took 80 GiB and 100.0 seconds\n')
        ui.write_json(self.path / 'timing.json', {
            'rehearsal': False, 'startup_phases': {'ready': True, 'total_seconds': 500.0},
            'observed_seconds_since_apply': {'worker_and_frontend_ready': 500.0},
            'logged_seconds_slowest_rank': {'model_loading': 100.0, 'engine_initialization': 50.0}})
        ui.write_json(self.path / 'demo.json', {
            'profile': ui.PROFILE, 'prepared': True, 'namespace': self.ns,
            'rehearsal': False, 'ready_observed_at': '2026-11-07T03:00:00Z',
            'source_sha256': ui.digest(ui.TEMPLATE), 'lock_sha256': ui.digest(ui.MODEL_LOCK),
            'manifest_sha256': ui.digest(self.path / 'deployment.yaml'),
            'claim_sha256': ui.digest(self.path / 'gpu-claim-template.yaml'),
            'mx_source_service_sha256': ui.digest(self.path / 'source-service.yaml')})

    def write_yaml(self, name, value):
        (self.path / name).write_text(yaml.safe_dump(value, sort_keys=False))

    def get(self, *args):
        kind = args[1]
        value = {'dgd': self.graph, 'pods': {'items': [self.pods[0]]}, 'pod': self.pods[1],
                 'service': self.service, 'endpointslices': self.endpoints, 'resourceclaim': self.claim,
                 'resourceslices': self.slices}[kind]
        return copy.deepcopy(value)


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.assignment = mock.patch.object(ui, 'ALLOCATION', None)
        self.assignment.start()
        self.addCleanup(self.assignment.stop)
        self.fixture = SourceFixture(self.directory.name)

    def test_storage_baseline_and_live_source_have_exact_identity(self):
        binding = source.snapshot(self.fixture.path)
        self.assertEqual(binding['baseline']['ready_seconds'], 500)
        self.assertEqual(binding['baseline']['model_loading_seconds'], 100)
        self.assertEqual(binding['baseline']['source_uid'], 'worker-uid')
        proof = source.identity(self.fixture, binding)
        self.assertEqual(proof, {'uid': 'worker-uid', 'node': 'node-a', 'graph_uid': 'graph-uid',
                                 'frontend_uid': 'frontend-uid', 'claim_uid': 'claim-uid',
                                 'gpu_devices': ['physical-gpu-0', 'physical-gpu-1'], 'service_uid': 'service-uid'})

    def test_native_source_is_rejected_with_fresh_launch_guidance(self):
        worker = next(c for c in self.fixture.graph['spec']['components'] if c['type'] == 'worker')
        args = worker['podTemplate']['spec']['containers'][0]['args']
        del args[args.index('--load-format'):]
        self.fixture.write_yaml('deployment.yaml', self.fixture.graph)
        with self.assertRaisesRegex(ValueError, 'fresh single-replica run'):
            source.snapshot(self.fixture.path)

    def test_old_profile_explains_running_server_is_preserved(self):
        data = ui.read_json(self.fixture.path / 'demo.json')
        data['profile'] = 'intro-text-only-eager-v3'
        ui.write_json(self.fixture.path / 'demo.json', data)
        with self.assertRaisesRegex(ValueError, 'current server was left running'):
            source.snapshot(self.fixture.path)

    def test_peer_loaded_first_replica_cannot_be_called_storage(self):
        with (self.fixture.path / 'worker.log').open('a') as handle:
            handle.write('(Worker_TP0) Receiving 1869 tensors from source (P2P)\n')
        with self.assertRaisesRegex(ValueError, 'received peer weights'):
            source.snapshot(self.fixture.path)

    def test_missing_storage_strategy_is_not_inferred_from_absence_of_peer_logs(self):
        (self.fixture.path / 'worker.log').write_text('Model loading took 80 GiB and 100.0 seconds\n')
        with self.assertRaisesRegex(ValueError, 'does not prove its storage-loading strategy'):
            source.snapshot(self.fixture.path)

    def test_source_evidence_edit_and_allocation_addition_are_rejected(self):
        binding = source.snapshot(self.fixture.path)
        (self.fixture.path / 'allocation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'allocation changed'):
            source.validate_files(binding)
        (self.fixture.path / 'allocation.json').unlink()
        with (self.fixture.path / 'worker.log').open('a') as handle:
            handle.write('edited')
        with self.assertRaisesRegex(ValueError, 'evidence changed: worker.log'):
            source.validate_files(binding)

    def test_frozen_allocation_is_part_of_source_binding(self):
        assignment = self.fixture.path / 'allocation.json'
        assignment.write_text('{"assignment_id":"original"}')
        binding = source.snapshot(self.fixture.path)
        self.assertIn('allocation.json', binding['inputs'])
        assignment.write_text('{"assignment_id":"replacement"}')
        with self.assertRaisesRegex(ValueError, 'evidence changed: allocation.json'):
            source.validate_files(binding)

    def test_source_worker_replacement_or_restart_invalidates_binding(self):
        binding = source.snapshot(self.fixture.path)
        self.fixture.pods[0]['metadata']['uid'] = 'replacement'
        with self.assertRaisesRegex(RuntimeError, 'replaced or moved'):
            source.identity(self.fixture, binding)
        self.fixture.pods[0]['metadata']['uid'] = binding['worker_uid']
        self.fixture.pods[0]['status']['containerStatuses'][0]['restartCount'] = 1
        with self.assertRaisesRegex(RuntimeError, 'Ready without restarts'):
            source.identity(self.fixture, binding)

    def test_wrong_discovery_endpoint_or_foreign_claim_cannot_pass(self):
        binding = source.snapshot(self.fixture.path)
        self.fixture.endpoints['items'][0]['endpoints'][0]['targetRef']['uid'] = 'other-source'
        with self.assertRaisesRegex(RuntimeError, 'does not resolve only'):
            source.identity(self.fixture, binding)
        self.fixture.endpoints['items'][0]['endpoints'][0]['targetRef']['uid'] = 'worker-uid'
        self.fixture.claim['metadata']['ownerReferences'][0]['uid'] = 'other-worker'
        with self.assertRaisesRegex(RuntimeError, 'not owned by the retained worker'):
            source.identity(self.fixture, binding)

    def test_unresolvable_or_duplicate_physical_gpu_is_rejected(self):
        binding = source.snapshot(self.fixture.path)
        self.fixture.slices['items'][0]['spec']['nodeName'] = 'node-b'
        with self.assertRaisesRegex(RuntimeError, 'different node'):
            source.identity(self.fixture, binding)
        self.fixture.slices['items'][0]['spec']['nodeName'] = 'node-a'
        devices = self.fixture.slices['items'][0]['spec']['devices']
        devices[1]['attributes']['uuid']['string'] = devices[0]['attributes']['uuid']['string']
        with self.assertRaisesRegex(RuntimeError, 'duplicate physical devices'):
            source.identity(self.fixture, binding)

    def test_extra_loader_setting_is_rejected_but_operator_identity_defaults_are_allowed(self):
        binding = source.snapshot(self.fixture.path)
        self.fixture.pods[0]['spec']['containers'][0]['env'].append({'name': 'MX_MODEL_URI', 'value': 'unexpected'})
        with self.assertRaisesRegex(RuntimeError, 'unexpected environment setting'):
            source.identity(self.fixture, binding)


if __name__ == '__main__':
    unittest.main()
