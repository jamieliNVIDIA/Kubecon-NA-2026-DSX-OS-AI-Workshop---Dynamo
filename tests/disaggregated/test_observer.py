"""P/D startup keeps both worker observations bounded and UID-bound."""
from tests.support import ROOT
import contextlib
import datetime as dt
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from demos.common import runtime as ui
from demos.disaggregated import demo as pd
from tests.common.test_observer import Clock, result


APPLIED = '2026-11-07T00:00:00Z'
LOADING = ('2026-11-07T00:00:02Z Initializing a V1 LLM engine\n'
           '2026-11-07T00:00:04Z Loading model from scratch...\n')
COMPLETE = (LOADING + '2026-11-07T00:00:14Z Model loading took 40 GiB and 10.0 seconds\n'
            '2026-11-07T00:00:24Z init engine (profile, create kv cache, warmup model) took 10.0 s\n')
CLAIM = {'status': {'allocation': {'devices': {'results': [
    {'driver': 'gpu.nvidia.com'}, {'driver': 'gpu.nvidia.com'}]}}}}


def pods(*, ready=False):
    image = ui.read_json(ui.MODEL_LOCK)['runtime_image']
    return [{'metadata': {'name': role + '-pod', 'uid': role + '-uid',
                         'labels': {'workshop-role': role, 'workshop-demo': 'disagg'}},
             'spec': {'nodeName': 'kubecon-nke-site-cp-' + ('0198' if role == 'decode' else '0124'),
                      'containers': [{'name': 'main', 'image': image, 'args': [],
                                      'resources': {'claims': [{'name': 'gpu-main'}]}}]},
             'status': {'phase': 'Running', 'conditions': [{'type': 'Ready',
                        'status': 'True' if ready else 'False', 'lastTransitionTime': '2026-11-07T00:00:27Z'}],
                        'resourceClaimStatuses': [{'name': 'gpu-main', 'resourceClaimName': role + '-claim'}],
                        'containerStatuses': [{'name': 'main', 'imageID': image, 'restartCount': 0,
                            'state': {'running': {'startedAt': '2026-11-07T00:00:01Z'}}}]}}
            for role in pd.ROLES]


class ObserverTests(unittest.TestCase):
    @contextlib.contextmanager
    def presenter(self, *, timeout=200):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instance = pd.DisaggDemo(SimpleNamespace(run=root / 'run', action='run', rehearsal=True,
                preview=False, auto=True, plain=True, port=18002, timeout=timeout))
            instance.args.rehearsal = False
            instance.data.update(prepared=True, apply_started_at=APPLIED)
            instance.save()
            clock = Clock()
            actual_progress = ui.startup_progress

            def progress(*args):
                observed = ui.timestamp(APPLIED) + dt.timedelta(seconds=20 + clock.value - 1000)
                return actual_progress(*args, observed_at=observed.isoformat())

            with (mock.patch.object(ui, 'LEASE', root / 'lease'),
                  mock.patch.object(pd.time, 'monotonic', side_effect=clock.monotonic),
                  mock.patch.object(pd.time, 'sleep', side_effect=clock.sleep),
                  mock.patch.object(ui, 'startup_progress', side_effect=progress),
                  mock.patch.object(instance.run, 'apply') as apply,
                  contextlib.redirect_stdout(io.StringIO()) as output):
                ui.acquire(instance.path, pd.OWNER)
                yield instance, clock, output
                apply.assert_not_called()
                self.assertTrue(ui.lease_owned(instance.path, pd.OWNER))

    def scripted(self, entries):
        pending = list(entries)

        def read(*args, **kwargs):
            operation, response = pending.pop(0)
            self.assertEqual(args[:2], operation)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], ui.STARTUP_READ_TIMEOUT)
            self.assertTrue(any(a.startswith('--request-timeout=') for a in args))
            return response
        return read, pending

    @staticmethod
    def observation(batch, logs=LOADING):
        return [(('get', 'pods'), result({'items': batch})),
                (('logs', 'prefill-pod'), result(logs)),
                (('logs', 'decode-pod'), result(logs)),
                (('get', 'pods'), result({'items': batch}))]

    def test_main_running_phases_advance_and_ready_claim_reads_remain_bounded(self):
        entries = self.observation(pods()) + self.observation(pods()) + self.observation(pods(ready=True), COMPLETE)
        entries += [(('get', 'resourceclaim'), result(CLAIM)), (('get', 'resourceclaim'), result(CLAIM))]
        read, pending = self.scripted(entries)
        with self.presenter() as (instance, _, _), mock.patch.object(instance.run, 'k', side_effect=read), \
                mock.patch.object(ui, 'StartupDisplay') as display:
            instance.wait()
            updates = [call.args[0] for call in display.return_value.update.call_args_list]
            self.assertEqual(len(updates), 3)
            self.assertEqual([p['name'] for p in updates[0]['phases']], [p['name'] for p in updates[1]['phases']])
            for role in ('prefill', 'decode'):
                timers = [next(p['seconds'] for p in value['phases'] if p['name'] == role + ' / Model setup')
                          for value in updates[:2]]
                self.assertAlmostEqual(timers[1] - timers[0], 5)
            self.assertTrue(instance.data['startup']['ready'])
            self.assertTrue(instance.data['ready_observed_at'])
            self.assertEqual(instance.data['pod_uids'], {p['metadata']['name']: p['metadata']['uid'] for p in pods()})
            self.assertTrue((instance.path / 'ready-pods.json').is_file())
        self.assertFalse(pending)

    def test_temporary_log_transport_failure_recovers_without_emptying_saved_logs(self):
        initial = self.observation(pods())
        entries = initial + [(('get', 'pods'), result({'items': pods(ready=True)})),
            (('logs', 'prefill-pod'), result(code=1, error='TLS handshake timeout'))]
        entries += self.observation(pods(ready=True), COMPLETE)
        entries += [(('get', 'resourceclaim'), result(CLAIM)), (('get', 'resourceclaim'), result(CLAIM))]
        read, pending = self.scripted(entries)
        with self.presenter() as (instance, _, output), mock.patch.object(instance.run, 'k', side_effect=read):
            instance.wait()
            self.assertIn('Observer disconnected', output.getvalue())
            self.assertIn('Observer reconnected', output.getvalue())
            self.assertEqual((instance.path / 'prefill.log').read_text(), COMPLETE)
            self.assertEqual((instance.path / 'decode.log').read_text(), COMPLETE)
            self.assertEqual(instance.data['startup_observation']['status'], 'fresh')
        self.assertFalse(pending)

    def test_exhausted_log_outage_retains_last_successful_phases_and_logs_without_ready(self):
        read_initial, pending = self.scripted(self.observation(pods()))
        failures = []
        with self.presenter() as (instance, clock, _):
            def read(*args, **kwargs):
                if pending:
                    return read_initial(*args, **kwargs)
                if args[:2] == ('get', 'pods'):
                    return result({'items': pods(ready=True)})
                failures.append(clock.value)
                clock.value += kwargs['timeout']
                return result(code=124)
            with mock.patch.object(instance.run, 'k', side_effect=read), \
                    self.assertRaisesRegex(TimeoutError, 'retry budget exhausted'):
                instance.wait()
            self.assertLessEqual(clock.value - failures[0], ui.STARTUP_OUTAGE_BUDGET + 0.001)
            for role in ('prefill', 'decode'):
                self.assertEqual((instance.path / (role + '.log')).read_text(), LOADING)
                saved = next(phase for phase in instance.data['worker_startup'][role]['phases']
                             if phase['name'] == 'Model setup')
                self.assertAlmostEqual(saved['seconds'], 16)
            self.assertFalse(instance.data['startup']['ready'])
            self.assertNotIn('ready_observed_at', instance.data)
            self.assertFalse((instance.path / 'ready-pods.json').exists())
            self.assertEqual(instance.data['startup_observation']['status'], 'stale')

    def test_startup_deadline_is_not_extended_by_transport_retries(self):
        with self.presenter(timeout=12) as (instance, clock, _):
            def read(*args, **kwargs):
                clock.value += kwargs['timeout']
                return result(code=124)
            with mock.patch.object(instance.run, 'k', side_effect=read), self.assertRaises(TimeoutError):
                instance.wait()
            self.assertLessEqual(clock.value, 1012.001)
            self.assertNotIn('ready_observed_at', instance.data)

    def test_forbidden_log_read_is_not_retried_or_used_as_empty_success(self):
        read, pending = self.scripted([(('get', 'pods'), result({'items': pods(ready=True)})),
            (('logs', 'prefill-pod'), result('partial log', code=1, error='Error from server (Forbidden)'))])
        with self.presenter() as (instance, _, _):
            (instance.path / 'prefill.log').write_text('last verified log')
            with mock.patch.object(instance.run, 'k', side_effect=read) as call, \
                    self.assertRaisesRegex(RuntimeError, 'Forbidden'):
                instance.wait()
            self.assertEqual(call.call_count, 2)
            self.assertEqual((instance.path / 'prefill.log').read_text(), 'last verified log')
            self.assertNotIn('ready_observed_at', instance.data)
            self.assertEqual(instance.data['startup_observation']['status'], 'failed')
        self.assertFalse(pending)

    def test_uid_change_during_log_read_never_qualifies_the_replacement(self):
        original, replacement = pods(), pods(ready=True)
        replacement[-1]['metadata']['uid'] = 'another-decode-uid'
        entries = self.observation(original)
        entries[-1] = (('get', 'pods'), result({'items': replacement}))
        read, pending = self.scripted(entries)
        with self.presenter() as (instance, _, _), mock.patch.object(instance.run, 'k', side_effect=read), \
                self.assertRaisesRegex(RuntimeError, 'Pod changed during startup'):
            instance.wait()
        self.assertFalse(pending)

    def test_malformed_valid_json_marks_previous_observation_failed(self):
        for payload in ({'items': None}, {'items': [{'metadata': None}]}):
            with self.subTest(payload=payload), self.presenter() as (instance, _, _):
                instance.data['startup_observation'] = {'status': 'fresh', 'last_successful_at': 'previous read'}
                with mock.patch.object(instance.run, 'k', return_value=result(payload)) as read, \
                        self.assertRaisesRegex(RuntimeError, 'Invalid P/D startup API snapshot'):
                    instance.wait()
                self.assertEqual(read.call_count, 1)
                self.assertEqual(instance.data['startup_observation']['status'], 'failed')
                self.assertNotIn('ready_observed_at', instance.data)
                self.assertFalse((instance.path / 'ready-pods.json').exists())


if __name__ == '__main__':
    unittest.main()
