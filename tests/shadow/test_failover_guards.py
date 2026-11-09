"""Offline safety checks: missing/coexisting allocators and unsafe kill targets."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import shadow_failover_tests as shadow
import shadow_probe as probe


class FakeRun:
    def __init__(self, path, gpu=False, device_plugin=False):
        self.path = path
        self.ns = 'dynamo-ft-fixture'
        self.gpu = gpu
        self.device_plugin = device_plugin
        self.receipts = []

    def command(self, args):
        return types.SimpleNamespace(stdout=json.dumps({'resources': {'gpus': {'enabled': self.gpu}},
                                                       'gpuResourcesEnabledOverride': self.gpu}))

    def k(self, *args):
        return types.SimpleNamespace(stdout=json.dumps({'serverVersion': {'major': '1', 'minor': '34'}}))

    def get(self, *args):
        resource = args[1]
        if resource == 'deviceclasses':
            return {'items': [{'metadata': {'name': 'gpu.nvidia.com' if self.gpu else 'compute-domain-daemon.nvidia.com'}}]}
        if resource == 'resourceslices':
            return {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'h100-test', 'devices': [{}]}}] if self.gpu else []}
        if resource == 'nodes':
            return {'items': [{'metadata': {'name': 'h100-test', 'labels': {'nvidia.com/gpu.product': 'NVIDIA-H100-80GB-HBM3'}},
                               'status': {'nodeInfo': {}, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}
        if resource == 'deployments':
            return {'items': [{'metadata': {'name': 'dynamo-operator', 'namespace': 'dynamo-system'},
                               'spec': {'template': {'spec': {'containers': []}}}, 'status': {'readyReplicas': 1}}]}
        if resource == 'daemonsets':
            return {'items': []}
        if resource == 'pods':
            items = [{'metadata': {'name': 'dra-driver-kubelet'}, 'spec': {'nodeName': 'h100-test'},
                      'status': {'containerStatuses': [{'name': 'gpus', 'ready': True}]}}] if self.gpu else []
            if self.device_plugin:
                items.append({'metadata': {'name': 'nvidia-device-plugin-fixture'}, 'spec': {'nodeName': 'h100-test'},
                              'status': {'phase': 'Running'}})
            return {'items': items}
        if resource == 'crd':
            return {'spec': {'versions': [{'name': 'v1beta1', 'schema': {'openAPIV3Schema': {'properties': {
                'spec': {'properties': {'components': {'items': {'properties': {'experimental': {'properties': {
                    'failover': {}, 'gpuMemoryService': {}}}}}}}}}}}}]}}
        raise AssertionError(f'Unexpected resource read: {args}')

    def result(self, *args, **kwargs):
        self.receipts.append((args, kwargs))


class ShadowSafetyTests(unittest.TestCase):
    def test_recorded_fault_intent_prevents_a_second_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'shadow-fault-intent.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                shadow.verify(types.SimpleNamespace(path=root), 120, [])

    def test_computedomain_only_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            report = shadow.preflight(FakeRun(Path(directory)))
        self.assertTrue(any('DeviceClass' in b for b in report['blockers']))
        self.assertEqual(report['eligible_nodes'], [])

    def test_two_gpu_allocators_on_same_node_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            report = shadow.preflight(FakeRun(Path(directory), gpu=True, device_plugin=True))
        self.assertTrue(report['blockers'])
        self.assertEqual(report['eligible_nodes'], [])

    def test_isolated_ready_gpu_dra_node_is_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            report = shadow.preflight(FakeRun(Path(directory), gpu=True))
        self.assertEqual(report['blockers'], [])
        self.assertEqual(report['eligible_nodes'], ['h100-test'])

    def test_unowned_namespace_never_reaches_exec(self):
        run = types.SimpleNamespace(ns='dynamo-ft-fixture',
                                    get=lambda *args: {'metadata': {'labels': {}}})
        with self.assertRaisesRegex(ValueError, 'not owned'):
            shadow.owned_pod(run)

    def test_wrong_engine_never_sends_signal(self):
        with patch.dict(os.environ, {'ENGINE_ID': '1'}), patch.object(probe.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                probe.kill_active('0')
            kill.assert_not_called()

    def test_stale_owner_without_held_lock_never_sends_signal(self):
        with tempfile.NamedTemporaryFile(mode='w+') as lock:
            lock.write('engine-0')
            lock.flush()
            with patch.dict(os.environ, {'ENGINE_ID': '0', 'FAILOVER_LOCK_PATH': lock.name}), patch.object(probe.os, 'kill') as kill:
                with self.assertRaisesRegex(RuntimeError, 'Lock is free'):
                    probe.kill_active('0')
                kill.assert_not_called()

    def test_ambiguous_engine_core_never_sends_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / 'failover.lock'
            lock.write_text('engine-0')
            fakeproc = root / 'proc'
            for pid in ('2', '3'):
                target = fakeproc / pid
                target.mkdir(parents=True)
                (target / 'cmdline').write_bytes(b'VLLM::EngineCore\0')
            real_path = Path
            def path(value):
                return fakeproc if value == '/proc' else real_path(value)
            with lock.open() as holder:
                fcntl.flock(holder, fcntl.LOCK_EX)
                with patch.dict(os.environ, {'ENGINE_ID': '0', 'FAILOVER_LOCK_PATH': str(lock)}), patch.object(probe, 'Path', path), patch.object(probe.os, 'kill') as kill:
                    with self.assertRaisesRegex(RuntimeError, 'Expected one vLLM EngineCore'):
                        probe.kill_active('0')
                    kill.assert_not_called()

    def test_metric_parser_rejects_missing_or_duplicate_state(self):
        text = shadow.METRIC + '_state{state="active",engine_id="1"} 1\n'
        self.assertEqual(shadow.counter(text, 'state', state='active', engine_id='1'), 1)
        for invalid in ('', text + text):
            with self.assertRaises(RuntimeError):
                shadow.counter(invalid, 'state', state='active', engine_id='1')


if __name__ == '__main__':
    unittest.main()
