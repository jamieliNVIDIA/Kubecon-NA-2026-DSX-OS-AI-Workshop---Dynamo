"""Retain the lost failure generation before the verifier destroys its Pod."""
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.diagnostics as diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_actual_follower_stream_has_no_inherited_deadline_and_observer_stays_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(path=Path(directory), ns='test',
                kbase=['kubectl', '--context=workshop', '--request-timeout', '30s'])
            follower = diagnostics.LogFollowers(run)
            follower.path.mkdir()
            pod = {'metadata': {'name': 'worker', 'uid': 'uid', 'labels': {'feature-test-run': 'test'}},
                'status': {'containerStatuses': [{'name': 'main', 'containerID': 'container-generation',
                    'restartCount': 0}]}}
            def start_stream(command, **kwargs):
                follower.stop_event.set()
                return SimpleNamespace(poll=lambda: 0)
            result = SimpleNamespace(returncode=0, stdout=json.dumps({'items': [pod]}))
            with patch.object(diagnostics.subprocess, 'run', return_value=result) as observer, \
                    patch.object(diagnostics.subprocess, 'Popen', side_effect=start_stream) as stream:
                follower.watch()
            get_command = observer.call_args.args[0]
            stream_command = stream.call_args.args[0]
            self.assertEqual([arg for arg in stream_command if arg.startswith('--request-timeout')],
                ['--request-timeout=0'])
            self.assertEqual(get_command[-1], '--request-timeout=8s')
            self.assertEqual(observer.call_args.kwargs['timeout'], 12)
            self.assertEqual(run.kbase[-2:], ['--request-timeout', '30s'])
            for process, output in follower.children:
                output.close()

    def test_restart_preserves_previous_fatal_and_last_nonempty_current_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'worker-main.log').write_text('old generation finished loading weights\n')
            pod = {'metadata': {'name': 'worker', 'uid': 'pod-uid', 'labels': {'feature-test-run': 'test'}},
                'spec': {'containers': [{'name': 'main'}]},
                'status': {'containerStatuses': [{'name': 'main', 'restartCount': 1, 'containerID': 'new'}]}}
            calls = []
            def logs(*args, **kwargs):
                calls.append(args)
                text = 'ValueError: concrete original fatal\n' if '--previous' in args else ''
                return SimpleNamespace(stdout=text, stderr='', returncode=0)
            run = SimpleNamespace(path=path, ns='test', get=lambda *args: {'items': [pod]}, k=logs)
            self.assertEqual(diagnostics.collect_previous(run), [pod])
            history = list((path / 'writer-log-history').glob('*.log'))
            self.assertTrue(any('concrete original fatal' in p.read_text() for p in history))
            self.assertTrue(any('finished loading weights' in p.read_text() for p in history))
            self.assertTrue(any('--previous' in args for args in calls))

    def test_foreign_pod_is_refused_without_reading_its_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            pod = {'metadata': {'labels': {'feature-test-run': 'foreign'}}}
            run = SimpleNamespace(path=Path(directory), ns='test', get=lambda *args: {'items': [pod]})
            with self.assertRaisesRegex(ValueError, 'Foreign writer Pod'):
                diagnostics.collect_previous(run)

    def test_collection_override_and_followers_are_restored_after_verifier_failure(self):
        original = object()
        writer = SimpleNamespace(collect=original)
        follower = SimpleNamespace(path=Path('/offline-follow'), start=lambda: None, stop=lambda: None)
        with patch.object(diagnostics, 'LogFollowers', return_value=follower):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                with diagnostics.preserve_writer_logs(object(), writer):
                    self.assertIs(writer.collect, diagnostics.collect_previous)
                    raise RuntimeError('verification failed')
        self.assertIs(writer.collect, original)


if __name__ == '__main__': unittest.main()
