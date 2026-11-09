"""Startup reads fail closed while tolerating a bounded transport interruption."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui


class Clock:
    def __init__(self):
        self.value = 1000.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        assert seconds >= 0
        self.value += seconds


def pods(uid='worker-a', ready=False, pending=False):
    image = ui.read_json(ui.MODEL_LOCK)['runtime_image']
    values = []
    for role in ('worker', 'frontend'):
        pod = {'metadata': {'name': role + '-pod', 'uid': uid if role == 'worker' else 'frontend-uid',
                            'labels': {'workshop-role': role}},
               'spec': {'nodeName': 'test-node', 'containers': [{'name': 'main', 'resources': {
                   'claims': [{'name': 'gpu-main'}]}}]},
               'status': {'phase': 'Running', 'conditions': [{'type': 'Ready',
                   'status': 'True' if ready else 'False', 'lastTransitionTime': '2026-11-04T00:00:30Z'}],
                   'resourceClaimStatuses': [{'name': 'gpu-main', 'resourceClaimName': 'gpu-claim'}],
                   'containerStatuses': [{'name': 'main', 'imageID': image, 'restartCount': 0,
                       'state': {'running': {'startedAt': '2026-11-04T00:00:05Z'}}}]}}
        if role == 'worker' and pending:
            pod['status']['phase'] = 'Pending'
            pod['status'].pop('containerStatuses')
        values.append(pod)
    return values


def result(value='', code=0, error=''):
    return subprocess.CompletedProcess([], code, json.dumps(value) if isinstance(value, dict) else value, error)


LOADING = '2026-11-04T00:00:10.123456789Z Loading model from scratch...\n'
COMPLETE = LOADING + '2026-11-04T00:00:20Z Model loading took 40 GiB and 10.0 seconds\n'
CLAIM = {'status': {'allocation': {'devices': {'results': [
    {'driver': 'gpu.nvidia.com'}, {'driver': 'gpu.nvidia.com'}]}}}}


class ObserverTests(unittest.TestCase):
    def test_main_pane_refreshes_running_time_without_a_phase_transition(self):
        pending, ready = pods(), pods(ready=True)
        entries = []
        for batch in (pending, pending, ready):
            entries.extend([(('get', 'pods'), result({'items': batch})),
                            (('logs', 'worker-pod'), result(LOADING)),
                            (('get', 'pod'), result(batch[0]))])
        entries.append((('get', 'resourceclaim'), result(CLAIM)))
        callback, remaining = self.scripted(entries)
        real_progress = ui.startup_progress
        observations = iter(['2026-11-04T00:00:20Z', '2026-11-04T00:00:25Z', '2026-11-04T00:00:35Z'])

        def progress(*args):
            return real_progress(*args, observed_at=next(observations))

        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            with mock.patch.object(ui, 'startup_progress', side_effect=progress), \
                    mock.patch.object(ui, 'StartupDisplay') as display:
                self.execute(instance, Clock())
            self.assertFalse(remaining)
            updates = [call.args[0] for call in display.return_value.update.call_args_list]
            self.assertEqual(len(updates), 3)
            self.assertEqual([p['status'] for p in updates[0]['phases']],
                             [p['status'] for p in updates[1]['phases']])
            timers = [next(p['seconds'] for p in value['phases'] if p['name'] == 'Model setup')
                      for value in updates[:2]]
            self.assertAlmostEqual(timers[1] - timers[0], 5)

    def instance(self, path, callback, clock, timeout=180):
        instance = object.__new__(ui.Demo)
        instance.path, instance.ns = Path(path), 'dynamo-ft-test'
        instance.args = SimpleNamespace(rehearsal=False, timeout=timeout, plain=True, auto=True)
        instance.data = {'apply_started_at': '2026-11-04T00:00:00Z'}
        instance.saved = []
        instance.save = lambda: instance.saved.append(copy.deepcopy(instance.data))
        instance.track_startup = mock.Mock()
        instance.calls = []

        def read(*args, **kwargs):
            instance.calls.append((args, kwargs))
            return callback(args, kwargs)

        instance.run = SimpleNamespace(k=read)
        return instance

    def execute(self, instance, clock, allocation=None):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(ui.time, 'monotonic', side_effect=clock.monotonic))
        stack.enter_context(mock.patch.object(ui.time, 'sleep', side_effect=clock.sleep))
        stack.enter_context(mock.patch.object(ui, 'ALLOCATION', allocation))
        output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        instance.wait()
        return output.getvalue()

    def scripted(self, entries):
        remaining = list(entries)

        def callback(args, kwargs):
            operation, response = remaining.pop(0)
            self.assertEqual(args[:2], operation)
            return response

        return callback, remaining

    def test_log_timeout_preserves_last_observation_then_recovers_without_reapplying(self):
        old, ready = pods(), pods(ready=True)
        callback, remaining = self.scripted([
            (('get', 'pods'), result({'items': old})), (('logs', 'worker-pod'), result(LOADING)),
            (('get', 'pod'), result(old[0])),
            (('get', 'pods'), result({'items': ready})),
            (('logs', 'worker-pod'), result(code=1, error='Unable to connect to the server: TLS handshake timeout')),
            (('get', 'pods'), result({'items': ready})), (('logs', 'worker-pod'), result(COMPLETE)),
            (('get', 'pod'), result(ready[0])), (('get', 'resourceclaim'), result(CLAIM)),
        ])
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            output = self.execute(instance, Clock())
            self.assertFalse(remaining)
            fresh = next(x for x in instance.saved if x.get('startup_observation', {}).get('status') == 'fresh')
            stale = next(x for x in instance.saved if x.get('startup_observation', {}).get('status') == 'stale')
            self.assertEqual(stale['startup'], fresh['startup'])
            self.assertFalse(stale['startup']['ready'])
            self.assertEqual(next(p for p in stale['startup']['phases'] if p['name'] == 'Model setup')['status'], 'running')
            self.assertNotIn('ready_observed_at', stale)
            self.assertEqual(stale['startup_observation']['last_log_at'], '2026-11-04T00:00:10.123456789Z')
            self.assertIn('current readiness is unknown', output)
            self.assertIn('Observer reconnected', output)
            self.assertTrue(instance.data['startup']['ready'])
            self.assertEqual(instance.data['startup_observation']['status'], 'fresh')
            self.assertEqual(instance.track_startup.call_count, 2)
            self.assertTrue(all(args[0] in ('get', 'logs') for args, _ in instance.calls))
            self.assertEqual((Path(directory) / 'worker.log').read_text(), COMPLETE)

    def test_transport_budget_exhaustion_retains_cache_and_never_accepts_readiness(self):
        clock = Clock()
        first = [(('get', 'pods'), result({'items': pods()})),
                 (('logs', 'worker-pod'), result(LOADING)), (('get', 'pod'), result(pods()[0]))]
        initial, remaining = self.scripted(first)
        failure_started = []

        def callback(args, kwargs):
            if remaining:
                return initial(args, kwargs)
            failure_started.append(clock.value)
            clock.value += kwargs['timeout']
            return result(code=124)

        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, clock)
            with self.assertRaisesRegex(TimeoutError, 'retry budget exhausted'):
                self.execute(instance, clock)
            self.assertLessEqual(clock.value - failure_started[0], ui.STARTUP_OUTAGE_BUDGET + 0.001)
            self.assertEqual(ui.cached_startup_log(Path(directory), instance.data), LOADING)
            self.assertFalse(instance.data['startup']['ready'])
            self.assertNotIn('ready_observed_at', instance.data)
            self.assertFalse((Path(directory) / 'ready-pods.json').exists())
            self.assertEqual(instance.track_startup.call_count, 1)
            self.assertTrue(all(kwargs['timeout'] <= ui.STARTUP_READ_TIMEOUT for _, kwargs in instance.calls))

    def test_existing_startup_deadline_is_not_extended_by_retry_budget(self):
        clock = Clock()

        def callback(args, kwargs):
            clock.value += kwargs['timeout']
            return result(code=124)

        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, clock, timeout=12)
            with self.assertRaisesRegex(TimeoutError, 'Resources and lease retained'):
                self.execute(instance, clock)
            self.assertLessEqual(clock.value, 1012.001)
            self.assertNotIn('ready_observed_at', instance.data)

    def test_new_worker_uid_invalidates_current_cache_before_a_failed_log_read(self):
        a, b = pods('worker-a'), pods('worker-b', ready=True)
        callback, remaining = self.scripted([
            (('get', 'pods'), result({'items': a})), (('logs', 'worker-pod'), result(LOADING)),
            (('get', 'pod'), result(a[0])), (('get', 'pods'), result({'items': b})),
            (('logs', 'worker-pod'), result(code=1, error='TLS handshake timeout')),
            (('get', 'pods'), result({'items': b})), (('logs', 'worker-pod'), result(COMPLETE)),
            (('get', 'pod'), result(b[0])), (('get', 'resourceclaim'), result(CLAIM)),
        ])
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            self.execute(instance, Clock())
            outage = next(x for x in instance.saved if x.get('startup_observation', {}).get('error', '').endswith('TLS handshake timeout'))
            self.assertEqual(outage['startup_observation']['worker_uid'], 'worker-b')
            self.assertNotIn('startup', outage)
            self.assertIsNone(ui.cached_startup_log(Path(directory), outage))
            self.assertEqual(set(instance.data['startup_log_observations']), {'worker-a', 'worker-b'})
            self.assertEqual((Path(directory) / 'startup-observations/worker-a.log').read_text(), LOADING)
            self.assertFalse(remaining)

    def test_uid_change_between_log_read_and_confirmation_is_refused(self):
        callback, _ = self.scripted([
            (('get', 'pods'), result({'items': pods('worker-a')})),
            (('logs', 'worker-pod'), result(LOADING)), (('get', 'pod'), result(pods('worker-b')[0]))])
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            with self.assertRaisesRegex(RuntimeError, 'UID changed during log read'):
                self.execute(instance, Clock())
            self.assertNotIn('startup', instance.data)
            self.assertFalse((Path(directory) / 'startup-observations').exists())

    def test_replacement_cannot_inherit_a_previously_qualified_ready_clock(self):
        callback, _ = self.scripted([(('get', 'pods'), result({'items': pods('worker-b', ready=True)}))])
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            instance.save_startup_observation(pods('worker-a')[0], LOADING, ui.startup_context(instance.data))
            instance.data['ready_observed_at'] = '2026-11-04T00:00:30Z'
            with self.assertRaisesRegex(RuntimeError, 'Previously Ready worker changed'):
                self.execute(instance, Clock())
            self.assertEqual(len(instance.calls), 1)
            self.assertEqual(instance.data['startup_observation']['status'], 'failed')
            self.assertIsNone(ui.cached_startup_log(Path(directory), instance.data))

    def test_pending_without_container_status_does_not_request_logs(self):
        ready = pods(ready=True)
        callback, remaining = self.scripted([
            (('get', 'pods'), result({'items': pods(pending=True)})),
            (('get', 'pods'), result({'items': ready})), (('logs', 'worker-pod'), result(COMPLETE)),
            (('get', 'pod'), result(ready[0])), (('get', 'resourceclaim'), result(CLAIM))])
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            self.execute(instance, Clock())
            self.assertFalse(remaining)
            self.assertTrue(instance.data['startup']['ready'])

    def test_fatal_api_log_and_container_failures_are_not_retried(self):
        for error in ('Error from server (Forbidden): no access', 'Error from server (BadRequest): wrong container',
                      'Unable to connect to the server: x509: certificate expired'):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                callback, _ = self.scripted([
                    (('get', 'pods'), result({'items': pods()})),
                    (('logs', 'worker-pod'), result(code=1, error=error))])
                instance = self.instance(directory, callback, Clock())
                with self.assertRaisesRegex(RuntimeError, 'Resources and lease retained'):
                    self.execute(instance, Clock())
                self.assertEqual(len(instance.calls), 2)
                self.assertNotIn('startup', instance.data)
                self.assertEqual(instance.data['startup_observation']['status'], 'failed')
        with tempfile.TemporaryDirectory() as directory:
            broken = pods()
            broken[0]['status']['containerStatuses'][0]['state'] = {'waiting': {'reason': 'ImagePullBackOff'}}
            callback, _ = self.scripted([(('get', 'pods'), result({'items': broken}))])
            instance = self.instance(directory, callback, Clock())
            with self.assertRaisesRegex(RuntimeError, 'ImagePullBackOff'):
                self.execute(instance, Clock())
            self.assertEqual(len(instance.calls), 1)

    def test_ready_observation_still_requires_actual_gpu_identity_guard(self):
        ready = pods(ready=True)
        callback, remaining = self.scripted([
            (('get', 'pods'), result({'items': ready})), (('logs', 'worker-pod'), result(COMPLETE)),
            (('get', 'pod'), result(ready[0])), (('get', 'resourceclaim'), result(CLAIM)),
            (('get', 'resourceslices'), result({'items': []}))])
        allocation = SimpleNamespace(verify=mock.Mock(side_effect=ValueError('Actual GPU UUIDs differ')))
        with tempfile.TemporaryDirectory() as directory:
            instance = self.instance(directory, callback, Clock())
            with self.assertRaisesRegex(ValueError, 'GPU UUIDs differ'):
                self.execute(instance, Clock(), allocation)
            self.assertFalse(remaining)
            allocation.verify.assert_called_once_with(ready[0], CLAIM, {'items': []}, 'intro')
            self.assertNotIn('ready_observed_at', instance.data)
            self.assertFalse((Path(directory) / 'ready-pods.json').exists())

    def test_readonly_log_pane_can_show_validated_cache_without_worker_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            instance = self.instance(path, None, Clock())
            instance.data.update(namespace='dynamo-ft-test', rehearsal=False)
            instance.save_startup_observation(pods()[0], LOADING, ui.startup_context(instance.data))
            instance.data['startup_observation']['status'] = 'stale'
            ui.write_json(path / 'demo.json', instance.data)
            before = {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}
            with mock.patch.object(ui.subprocess, 'run', return_value=result(code=1, error='TLS handshake timeout')), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                ui.observe(path, 'logs', once=True)
            self.assertIn('Last successful log observation (stale)', out.getvalue())
            self.assertIn('Loading model from scratch', out.getvalue())
            self.assertIn('current readiness is unknown', out.getvalue())
            self.assertFalse((path / 'worker.log').exists())
            self.assertEqual(before, {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()})
            changed = copy.deepcopy(instance.data)
            changed['startup_observation']['worker_uid'] = 'other-worker'
            self.assertIsNone(ui.cached_startup_log(path, changed))
            changed = copy.deepcopy(instance.data)
            changed['active_arm'] = 'peer'
            self.assertIsNone(ui.cached_startup_log(path, changed))
            (path / 'startup-observations/worker-a.log').write_text('corrupted')
            self.assertIsNone(ui.cached_startup_log(path, instance.data))

    def test_log_pane_does_not_reuse_old_uid_cache_for_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            instance = self.instance(path, None, Clock())
            instance.data.update(namespace='dynamo-ft-test', rehearsal=False)
            instance.save_startup_observation(pods('worker-a')[0], LOADING, ui.startup_context(instance.data))
            ui.write_json(path / 'demo.json', instance.data)
            responses = [result({'items': [pods('worker-b')[0]]}),
                         result(code=1, error='TLS handshake timeout')]
            with mock.patch.object(ui.subprocess, 'run', side_effect=responses), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                ui.observe(path, 'logs', once=True)
            self.assertIn('Log observation unavailable', out.getvalue())
            self.assertNotIn('Loading model from scratch', out.getvalue())

    def test_log_pane_invalidates_in_memory_cache_when_mx_arm_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            instance = self.instance(path, None, Clock())
            instance.data.update(namespace='dynamo-ft-test', rehearsal=False, active_arm='source')
            instance.save_startup_observation(pods()[0], LOADING, ui.startup_context(instance.data))
            source, peer = copy.deepcopy(instance.data), copy.deepcopy(instance.data)
            peer['active_arm'] = 'peer'
            responses = [result({'items': [pods()[0]]}), result('SOURCE LOG\n'), result(pods()[0]),
                         result(code=1, error='TLS handshake timeout')]
            with mock.patch.object(ui, 'read_json', side_effect=[source, peer]), \
                    mock.patch.object(ui.subprocess, 'run', side_effect=responses), \
                    mock.patch.object(ui.time, 'sleep', side_effect=[None, StopIteration]), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(StopIteration):
                    ui.observe(path, 'logs')
            second_screen = out.getvalue().rsplit('\033[2J\033[H', 1)[-1]
            self.assertIn('Observer disconnected', second_screen)
            self.assertNotIn('SOURCE LOG', second_screen)
            self.assertNotIn('Loading model from scratch', second_screen)


if __name__ == '__main__':
    unittest.main()
