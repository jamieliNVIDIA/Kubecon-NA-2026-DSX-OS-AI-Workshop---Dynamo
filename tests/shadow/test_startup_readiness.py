"""Startup probe health, stable identity and early coding evidence persistence."""
from tests.support import ROOT
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.composed as full
import serving_tests
import demos.snapshot.dgd as workshop_snapshot_dgd

A3 = ROOT / 'results/shadow-full-a3-remote-collected-a1/run'
BEFORE = A3 / 'shadow-observation-1793927043550929835.json'
AFTER = A3 / 'shadow-observation-1793927082120160388.json'


def healthy():
    if AFTER.exists():
        return json.loads(AFTER.read_text())
    image = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())['runtime_image']
    return {'pod_uid': 'pod', 'pod_name': 'worker', 'node': full.NODE,
        'states': {'engine-0': 'active', 'engine-1': 'standby'},
        'engines': {name: {'gpu_uuids': full.UUIDS} for name in ('engine-0', 'engine-1')},
        'container_statuses': {name: {'name': name, 'containerID': 'containerd://' + name,
            'restartCount': 0, 'ready': True, 'started': True, 'imageID': image,
            'state': {'running': {'startedAt': 'now'}}} for name in ('engine-0', 'engine-1', 'gms-server')},
        'gms': {'device_weights.sock': {'state': {'memory_layout_hash': 'layout'}, 'events': []},
                'device_kv_cache.sock': {'state': {'allocation_count': 1}, 'events': []}}}


class StartupGuardTests(unittest.TestCase):
    @unittest.skipUnless(BEFORE.exists() and AFTER.exists(), 'Retained actual a3 observations are local evidence')
    def test_actual_a3_is_stable_identity_but_must_wait_for_probe_health(self):
        before, after = json.loads(BEFORE.read_text()), json.loads(AFTER.read_text())
        full.validate_ready_observation(before, after)
        self.assertFalse(full.startup_probes_ready(before))
        self.assertTrue(full.startup_probes_ready(after))
        with self.assertRaisesRegex(ValueError, 'Ready/Started'):
            full.validate_startup_observation(before, after)
        full.validate_startup_observation(after, copy.deepcopy(after))

    def test_all_three_ready_started_running_and_exact_restart_metadata_are_required(self):
        for name in ('engine-0', 'engine-1', 'gms-server'):
            for field, value in (('ready', False), ('ready', 1), ('started', False), ('started', 1),
                    ('containerID', ''), ('containerID', True), ('restartCount', 1),
                    ('restartCount', False), ('restartCount', 0.0), ('state', {'waiting': {}}),
                    ('state', {'running': None})):
                with self.subTest(container=name, field=field, value=value):
                    value_ = healthy(); value_['container_statuses'][name][field] = value
                    self.assertFalse(full.startup_probes_ready(value_))
                    with self.assertRaises(ValueError): full.validate_startup_observation(healthy(), value_)

    def test_identity_roles_and_all_gms_state_layout_events_stay_guarded(self):
        for case in ('pod', 'engine-id', 'gms-id', 'roles', 'weight-layout', 'kv-state', 'kv-events', 'kv-float'):
            with self.subTest(case=case):
                expected, actual = healthy(), healthy()
                weight = next(n for n in actual['gms'] if n.endswith('_weights.sock'))
                kv = next(n for n in actual['gms'] if n.endswith('_kv_cache.sock'))
                if case == 'pod': actual['pod_uid'] = 'replacement'
                elif case == 'engine-id': actual['container_statuses']['engine-0']['containerID'] = 'new'
                elif case == 'gms-id': actual['container_statuses']['gms-server']['containerID'] = 'new'
                elif case == 'roles': actual['states'] = {'engine-0': 'standby', 'engine-1': 'active'}
                elif case == 'weight-layout': actual['gms'][weight]['state']['memory_layout_hash'] = 'changed'
                elif case == 'kv-state': actual['gms'][kv]['state']['allocation_count'] += 1
                elif case == 'kv-events': actual['gms'][kv]['events'] = {'events': ['new']}
                elif case == 'kv-float': actual['gms'][kv]['state']['allocation_count'] = float(actual['gms'][kv]['state']['allocation_count'])
                with self.assertRaises(ValueError): full.validate_startup_observation(expected, actual)
        expected, actual = healthy(), healthy()
        actual['container_statuses']['engine-1']['allocatedResources'] = {'cpu': '2'}
        full.validate_startup_observation(expected, actual)


class StartupEvidenceTests(unittest.TestCase):
    def exercise(self, case):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        pending, baseline, after = healthy(), healthy(), healthy()
        pending['container_statuses']['engine-1']['ready'] = False
        pending['container_statuses']['engine-1']['started'] = False
        if case == 'final-gms':
            kv = next(n for n in after['gms'] if n.endswith('_kv_cache.sock'))
            after['gms'][kv]['state']['allocation_count'] += 1
        elif case == 'final-node': after['node'] = 'other-node'
        elif case == 'final-gpu': after['engines']['engine-0']['gpu_uuids'] = ['GPU-other']
        elif case == 'final-health': after['container_statuses']['gms-server']['ready'] = False
        else: after['container_statuses']['engine-1']['allocatedResources'] = {'cpu': '2'}
        pod = {'metadata': {'uid': baseline['pod_uid'], 'labels': {'workshop-role': 'worker'}},
            'status': {'containerStatuses': list(copy.deepcopy(baseline['container_statuses']).values())}}
        image = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())['runtime_image']
        run = SimpleNamespace(state={'shadow_full_dgd_uid': 'dgd', 'checks': {},
            'model_lock': {'runtime_image': image}}, get=lambda *_: {'items': [pod]})
        def result(name, status, **values): run.state['checks'][name] = dict(status=status, **values)
        run.result = result
        demo = object.__new__(full.ComposedShadowDemo)
        demo.run, demo.path, demo.ns = run, path, 'dynamo-ft-test'
        demo.args, demo.data = SimpleNamespace(timeout=30), {'model': 'model'}
        demo.assert_graph = demo.logs = demo.cache_failure_logs = demo.stop = demo.save = lambda: None
        demo.collect_cache_stage = lambda _: True
        responses = [{'sse': 'data: correct-' + str(i) + '\ndata: [DONE]', 'content': 'def add(a,b): return a+b',
            'chunks': [{'index': i}], 'worker': {'decode_worker_id': 'worker'}} for i in range(3)]
        calls = []
        def coding(*_):
            self.assertTrue(full.startup_probes_ready(json.loads((path / 'full-ready-before.json').read_text())))
            self.assertEqual(snapshot.call_count, 2, 'Coding started before pending probes settled')
            index = len(calls); calls.append(index)
            if case == 'second-request' and index == 1: raise ValueError('second request failed')
            if index:
                self.assertEqual(json.loads((path / ('full-ready-coding-' + str(index) + '.json')).read_text()), responses[index - 1])
            return responses[index]
        with patch.object(full.presenter.control, 'snapshot', side_effect=[pending, baseline, after]) as snapshot, \
                patch.object(serving_tests, 'frontend', return_value=nullcontext('http://fixture')), \
                patch.object(workshop_snapshot_dgd, 'coding_request', side_effect=coding), \
                patch.object(full, 'collect_previous', return_value=None), patch.object(full.time, 'sleep'):
            if case == 'success': demo.wait_verified()
            else:
                with self.assertRaises(ValueError): demo.wait_verified()
        return path, run, responses

    def test_pending_probe_waits_then_persists_three_responses_and_snapshots(self):
        path, run, responses = self.exercise('success')
        self.assertEqual(run.state['checks']['shadow-full-ready']['status'], 'passed')
        self.assertEqual(json.loads((path / 'full-ready-coding.json').read_text()), responses)
        self.assertTrue((path / 'full-ready-after.json').exists())

    def test_later_request_failure_retains_already_validated_payload(self):
        path, run, responses = self.exercise('second-request')
        self.assertEqual(run.state['checks']['shadow-full-ready']['status'], 'failed')
        self.assertEqual(json.loads((path / 'full-ready-coding-1.json').read_text()), responses[0])
        self.assertEqual(json.loads((path / 'full-ready-coding.json').read_text()), responses[:1])
        self.assertTrue((path / 'full-ready-before.json').exists())
        self.assertFalse((path / 'full-ready-after.json').exists())
        self.assertFalse((path / 'shadow-fault-intent.json').exists())

    def test_all_postcoding_guards_preserve_three_payloads_and_both_snapshots(self):
        for case in ('final-gms', 'final-node', 'final-gpu', 'final-health'):
            with self.subTest(case=case):
                path, run, responses = self.exercise(case)
                self.assertEqual(run.state['checks']['shadow-full-ready']['status'], 'failed')
                self.assertEqual(json.loads((path / 'full-ready-coding.json').read_text()), responses)
                for index, response in enumerate(responses, 1):
                    self.assertEqual(json.loads((path / ('full-ready-coding-' + str(index) + '.json')).read_text()), response)
                self.assertTrue((path / 'full-ready-before.json').exists())
                self.assertTrue((path / 'full-ready-after.json').exists())
                self.assertFalse((path / 'shadow-fault-intent.json').exists())


if __name__ == '__main__': unittest.main()
