"""Independent host-only regression tests using retained full-a3 observations."""
from tests.support import ROOT
from contextlib import contextmanager, nullcontext, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.composed as full
import demos.snapshot.dgd as coding
import serving_tests

COLLECTED = ROOT / 'results/shadow-full-a3-remote-collected-a1/run'
BEFORE = COLLECTED / 'shadow-observation-1793927043550929835.json'
AFTER = COLLECTED / 'shadow-observation-1793927082120160388.json'


@unittest.skipUnless(BEFORE.is_file() and AFTER.is_file(), 'Requires preserved actual full-a3 observation evidence')
class ReadinessReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        expected = ((BEFORE, 'c5dcf63b84ddc2aff5a295e8fe184eff364cd5afc3eb9c276104ceb645d1176b'),
                    (AFTER, 'fe660385e75f64556cc4ed338b52fd0485d560370d1aa52b4b853ed07d05f19f'))
        for path, digest in expected:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Actual snapshot fixture drift: ' + str(path))
        cls.before = json.loads(BEFORE.read_text())
        cls.after = json.loads(AFTER.read_text())

    def test_actual_probe_transition_is_health_progress_and_healthy_pair_passes(self):
        self.assertFalse(full.startup_probes_ready(self.before))
        self.assertTrue(full.startup_probes_ready(self.after))
        full.validate_ready_observation(self.before, self.after)
        full.presenter.validate_pair(self.after, full.UUIDS)
        full.validate_startup_observation(self.after, copy.deepcopy(self.after))
        with self.assertRaisesRegex(ValueError, 'healthy Ready/Started'):
            full.validate_startup_observation(self.before, self.after)
        extra = copy.deepcopy(self.after)
        extra['container_statuses']['engine-1']['kubelet_observation'] = 'unrelated status progress'
        full.validate_startup_observation(self.after, extra)

    def test_every_container_must_have_exact_healthy_ready_started_and_running_state(self):
        for name in ('engine-0', 'engine-1', 'gms-server'):
            for case in ('ready', 'started', 'numeric-ready', 'numeric-started', 'terminated',
                         'null-running', 'missing', 'blank-id', 'restart', 'boolean-restart'):
                with self.subTest(container=name, case=case):
                    actual = copy.deepcopy(self.after)
                    status = actual['container_statuses'][name]
                    if case in ('ready', 'started'): status[case] = False
                    elif case == 'numeric-ready': status['ready'] = 1
                    elif case == 'numeric-started': status['started'] = 1
                    elif case == 'terminated': status['state'] = {'terminated': {'exitCode': 0}}
                    elif case == 'null-running': status['state'] = {'running': None}
                    elif case == 'missing': del actual['container_statuses'][name]
                    elif case == 'blank-id': status['containerID'] = ''
                    elif case == 'restart': status['restartCount'] = 1
                    elif case == 'boolean-restart': status['restartCount'] = False
                    self.assertFalse(full.startup_probes_ready(actual))
                    with self.assertRaises(ValueError): full.validate_startup_observation(self.after, actual)

    def test_stable_generation_states_and_full_gms_changes_still_reject(self):
        for case in ('pod', 'engine-0-id', 'engine-1-id', 'gms-id', 'role', 'weight-layout',
                     'weight-events', 'kv-state', 'extra-gms', 'missing-gms'):
            with self.subTest(case=case):
                actual = copy.deepcopy(self.after)
                weights = next(name for name in actual['gms'] if name.endswith('_weights.sock'))
                kv = next(name for name in actual['gms'] if name.endswith('_kv_cache.sock'))
                if case == 'pod': actual['pod_uid'] = 'replaced'
                elif case.endswith('-id'):
                    name = 'gms-server' if case == 'gms-id' else case.removesuffix('-id')
                    actual['container_statuses'][name]['containerID'] = 'containerd://replacement'
                elif case == 'role': actual['states'] = {'engine-0': 'standby', 'engine-1': 'active'}
                elif case == 'weight-layout': actual['gms'][weights]['state']['memory_layout_hash'] = 'changed'
                elif case == 'weight-events': actual['gms'][weights]['events'] = {'changed': True}
                elif case == 'kv-state': actual['gms'][kv]['state']['unreviewed'] = True
                elif case == 'extra-gms': actual['gms']['unreviewed.sock'] = {}
                elif case == 'missing-gms': del actual['gms'][kv]
                with self.assertRaises(ValueError): full.validate_startup_observation(self.after, actual)

    @contextmanager
    def demo(self, observations):
        """Actual observation bytes plus host control-flow doubles; never a Run."""
        with tempfile.TemporaryDirectory() as directory:
            obj = object.__new__(full.ComposedShadowDemo)
            obj.path = Path(directory)
            obj.ns = 'dynamo-ft-review-only'
            obj.args = SimpleNamespace(timeout=300)
            obj.data = {'model': 'fixture/coding-model'}
            events = []
            statuses = copy.deepcopy(self.after['container_statuses'])
            pod = {'metadata': {'uid': self.after['pod_uid'], 'labels': {'workshop-role': 'worker'}},
                   'status': {'containerStatuses': list(statuses.values())}}
            state = {'shadow_full_dgd_uid': 'fixture-dgd', 'checks': {},
                     'model_lock': {'runtime_image': statuses['engine-0']['imageID']}}
            def result(name, disposition, **values):
                state['checks'][name] = dict(status=disposition, **values)
            obj.run = SimpleNamespace(get=lambda *args: {'items': [pod]}, state=state, result=result)
            obj.assert_graph = lambda: events.append('graph')
            obj.collect_cache_stage = lambda value: True
            obj.logs = lambda: None
            obj.cache_failure_logs = lambda: None
            obj.stop = lambda: events.append('stop')
            obj.save = lambda: events.append('save')
            def observation(*args):
                value = observations.pop(0)
                events.append('observation')
                if isinstance(value, Exception): raise value
                return copy.deepcopy(value)
            with patch.object(full.presenter.control, 'snapshot', side_effect=observation), \
                    patch.object(full, 'collect_previous', lambda *args: None), \
                    patch.object(full.time, 'sleep', lambda *args: events.append('sleep')), \
                    patch.object(serving_tests, 'frontend', lambda *args: nullcontext('fixture-endpoint')), \
                    redirect_stdout(io.StringIO()):
                yield obj, events

    def test_wait_does_not_code_until_actual_unready_snapshot_settles(self):
        with self.demo([self.before, self.after, self.after]) as (demo, events):
            count = 0
            def request(*args):
                nonlocal count
                self.assertIn('sleep', events)
                retained = json.loads((demo.path / 'full-ready-before.json').read_text())
                self.assertTrue(full.startup_probes_ready(retained))
                count += 1
                return {'request': count, 'raw_stream': 'fixture'}
            with patch.object(coding, 'coding_request', side_effect=request): demo.wait_verified()
            self.assertEqual(count, 3)
            self.assertEqual(demo.run.state['checks']['shadow-full-ready']['status'], 'passed')
            self.assertEqual(len(json.loads((demo.path / 'full-ready-coding.json').read_text())), 3)

    def test_second_request_failure_retains_first_payload_and_baseline(self):
        with self.demo([self.after]) as (demo, events):
            first = {'request': 1, 'raw_stream': 'first validated stream'}
            calls = 0
            def request(*args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    self.assertTrue((demo.path / 'full-ready-before.json').exists())
                    return first
                self.assertEqual(json.loads((demo.path / 'full-ready-coding-1.json').read_text()), first)
                self.assertEqual(json.loads((demo.path / 'full-ready-coding.json').read_text()), [first])
                raise RuntimeError('second coding request failed')
            with patch.object(coding, 'coding_request', side_effect=request):
                with self.assertRaisesRegex(RuntimeError, 'second coding'): demo.wait_verified()
            self.assertEqual(json.loads((demo.path / 'full-ready-coding-1.json').read_text()), first)
            self.assertFalse((demo.path / 'full-ready-coding-2.json').exists())
            self.assertFalse((demo.path / 'full-ready-after.json').exists())
            self.assertEqual(demo.run.state['checks']['shadow-full-ready']['status'], 'failed')
            self.assertIn('stop', events)

    def test_wrong_initial_gpu_pair_prevents_coding(self):
        actual = copy.deepcopy(self.after)
        actual['engines']['engine-0']['gpu_uuids'] = ['GPU-wrong']
        with self.demo([actual]) as (demo, events):
            with patch.object(coding, 'coding_request', side_effect=AssertionError('Must not code')) as request:
                with self.assertRaisesRegex(ValueError, 'allocation differs'): demo.wait_verified()
            request.assert_not_called()
            self.assertFalse((demo.path / 'full-ready-before.json').exists())
            self.assertIn('stop', events)

    def test_after_observation_failure_preserves_all_completed_payloads(self):
        with self.demo([self.after, RuntimeError('after observation failed')]) as (demo, events):
            responses = [{'request': index, 'raw_stream': 'raw-' + str(index)} for index in range(1, 4)]
            with patch.object(coding, 'coding_request', side_effect=responses):
                with self.assertRaisesRegex(RuntimeError, 'after observation failed'): demo.wait_verified()
            self.assertEqual(json.loads((demo.path / 'full-ready-before.json').read_text()), self.after)
            self.assertEqual(json.loads((demo.path / 'full-ready-coding.json').read_text()), responses)
            for index, response in enumerate(responses, 1):
                self.assertEqual(json.loads((demo.path / ('full-ready-coding-' + str(index) + '.json')).read_text()), response)
            self.assertFalse((demo.path / 'full-ready-after.json').exists())
            self.assertEqual(demo.run.state['checks']['shadow-full-ready']['status'], 'failed')
            self.assertIn('stop', events)

    def test_later_guard_failure_retains_all_raw_responses_and_both_snapshots(self):
        changes = ('generation', 'gms', 'gpu', 'unready', 'dgd')
        for case in changes:
            with self.subTest(case=case):
                actual = copy.deepcopy(self.after)
                if case == 'generation': actual['container_statuses']['engine-1']['containerID'] = 'replacement'
                elif case == 'gms': actual['gms'][next(iter(actual['gms']))]['state']['changed'] = True
                elif case == 'gpu': actual['engines']['engine-1']['gpu_uuids'] = ['GPU-wrong']
                elif case == 'unready': actual['container_statuses']['gms-server']['ready'] = False
                with self.demo([self.after, actual]) as (demo, events):
                    responses = [{'request': index, 'raw_stream': 'raw-' + str(index)} for index in range(1, 4)]
                    if case == 'dgd':
                        count = 0
                        def graph():
                            nonlocal count
                            count += 1
                            if count == 2: raise ValueError('DGD changed after coding')
                        demo.assert_graph = graph
                    with patch.object(coding, 'coding_request', side_effect=responses):
                        with self.assertRaises(ValueError): demo.wait_verified()
                    self.assertEqual(json.loads((demo.path / 'full-ready-before.json').read_text()), self.after)
                    self.assertEqual(json.loads((demo.path / 'full-ready-after.json').read_text()), actual)
                    self.assertEqual(json.loads((demo.path / 'full-ready-coding.json').read_text()), responses)
                    for index, response in enumerate(responses, 1):
                        self.assertEqual(json.loads((demo.path / ('full-ready-coding-' + str(index) + '.json')).read_text()), response)
                    self.assertEqual(demo.run.state['checks']['shadow-full-ready']['status'], 'failed')
                    self.assertIn('stop', events)


if __name__ == '__main__': unittest.main()
