"""Presenter gates for the integrated same-node Snapshot walkthrough."""
from tests.support import ROOT
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import demos.snapshot.dgd_demo as demo
import demos.common.capture as capture
import demos.common.runtime as ui


def args(path, **kwargs):
    return SimpleNamespace(**dict({'run': Path(path), 'action': 'run', 'rehearsal': True,
        'preview': False, 'auto': True, 'plain': True, 'port': 18004, 'timeout': 30, 'storage': None}, **kwargs))


class IntegratedPresenter(unittest.TestCase):
    def test_rehearsal_bootstrap_is_silent_and_restores_interactive_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, auto=False))
            with patch.object(presenter, 'pause', side_effect=lambda: self.assertTrue(presenter.args.auto)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                presenter.require_primed()
            self.assertTrue(presenter.data['initial_identity'])
            self.assertFalse(presenter.args.auto)
            self.assertEqual(output.getvalue(), '')

    def test_named_lease_is_recorded_and_reused_when_the_run_resumes(self):
        named = ui.ROOT / '.local/workshop-snapshot.gpu-lease'
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ), \
                patch.object(ui, 'LEASE', ui.LEASE), patch.object(ui, 'ALLOCATION', None):
            shared = ui.LEASE
            os.environ[ui.LEASE_ENV] = 'workshop-snapshot.gpu-lease'
            presenter = demo.SnapshotDgdDemo(args(temp))
            self.assertEqual(presenter.data['lease'], '.local/workshop-snapshot.gpu-lease')
            self.assertEqual(ui.LEASE, named)
            ui.LEASE = shared
            os.environ.pop(ui.LEASE_ENV)
            demo.SnapshotDgdDemo(args(temp))
            self.assertEqual(ui.LEASE, named)
            os.environ[ui.LEASE_ENV] = 'workshop-disagg.gpu-lease'
            with self.assertRaisesRegex(ValueError, 'reserves .local/workshop-snapshot.gpu-lease'):
                demo.SnapshotDgdDemo(args(temp))

    def test_foreign_or_incomplete_run_is_refused_before_state_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.json'
            original = '{"namespace":"dynamo-ft-existing","owner":"kubecon-dynamo-feature-tests"}\n'
            state.write_text(original)
            with self.assertRaisesRegex(ValueError, 'do not adopt'):
                demo.SnapshotDgdDemo(args(temp))
            self.assertEqual(state.read_text(), original)

    def test_preview_is_offline_and_projects_real_checkpoint_fields(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(demo.lifecycle, 'require_lease', side_effect=AssertionError('offline')):
            presenter = demo.SnapshotDgdDemo(args(temp))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.preview()
            executable = json.loads((Path(temp) / 'deployment.json').read_text())
            graph = next(x for x in executable['items'] if x['kind'] == 'DynamoGraphDeployment')
            projected = yaml.safe_load((Path(temp) / 'deployment-excerpt.yaml').read_text())
            worker = next(x for x in graph['spec']['components'] if x['type'] == 'worker')
            shown = next(x for x in projected['spec']['components'] if x['type'] == 'worker')
            frontend = next(x for x in graph['spec']['components'] if x['type'] == 'frontend')
            shown_frontend = next(x for x in projected['spec']['components'] if x['type'] == 'frontend')
            self.assertEqual(shown_frontend['podTemplate']['spec']['containers'][0], {
                key: frontend['podTemplate']['spec']['containers'][0][key] for key in ('name', 'command', 'args')})
            self.assertLessEqual(len((Path(temp) / 'deployment-excerpt.yaml').read_text().splitlines()), 40)
            self.assertEqual(shown['experimental']['checkpoint'], {k: worker['experimental']['checkpoint'][k]
                for k in ('enabled', 'startupPolicy', 'deletionPolicy')})
            self.assertNotIn('--enforce-eager', worker['podTemplate']['spec']['containers'][0]['args'])
            self.assertEqual(presenter.run.state['snapshot_dgd_storage_gate'], 'nvme')
            self.assertNotIn('snapshot_dgd_submitted_at', presenter.run.state)

    def test_rehearsal_full_flow_timing_precedes_gated_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp))
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(demo.lifecycle, 'deploy', side_effect=AssertionError('offline')), \
                    patch.object(demo.lifecycle, 'coding_request', side_effect=AssertionError('offline')):
                presenter.guided()
            text = output.getvalue()
            self.assertLess(text.index('Restore timing'), text.index('$ curl'))
            self.assertNotIn('Enter or Space', text)
            self.assertNotIn('Step finished in', text)
            self.assertNotIn('Commands shown relative to the run directory', text)
            self.assertNotIn('CPU model-cache', text)
            self.assertIn('$ cat recovery-summary.txt', text)
            self.assertIn('Worker Pod                  replaced', text)
            self.assertNotIn('"gpu_uuids":', text)
            timing = json.loads((Path(temp) / 'timing.json').read_text())
            self.assertTrue(timing['simulated'])
            self.assertIsNone(timing['agent_seconds'])
            self.assertFalse(timing['inference_sent'])
            self.assertTrue(presenter.data['ready_observed_at'])
            proof = json.loads((Path(temp) / 'recovery-proof.json').read_text())
            self.assertNotEqual(proof['before_uid'], proof['after_uid'])
            self.assertTrue((Path(temp) / 'response.json').exists())
            self.assertNotIn('snapshot_dgd_submitted_at', presenter.run.state)

    def test_capture_refuses_missing_readiness_even_with_finished_output(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.guided()
            self.assertTrue(capture.completed('04-snapshot-dgd', Path(temp), True)[0])
            presenter.data.pop('ready_observed_at')
            presenter.save()
            complete, reason = capture.completed('04-snapshot-dgd', Path(temp), True)
            self.assertFalse(complete)
            self.assertIn('readiness', reason)

    def test_pending_replacement_finishes_absolute_stage_four(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            presenter.run.state['replacement_intent'] = {'requested_at': demo.ui.now(), 'delete_submitted': True}
            presenter.run.save()
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(presenter, 'prepare', side_effect=AssertionError('prepare is offstage')):
                presenter.guided()
            self.assertIn('2/4  Replace the worker Pod', output.getvalue())
            self.assertIn('4/4  Use the recovered service', output.getvalue())
            self.assertEqual(presenter.data['step'], 4)
            self.assertTrue(capture.completed('04-snapshot-dgd', Path(temp), True)[0])

    def test_pending_replacement_pty_capture_records_complete_absolute_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            presenter = demo.SnapshotDgdDemo(args(root / 'run'))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            presenter.run.state['replacement_intent'] = {'requested_at': demo.ui.now(), 'delete_submitted': True}
            presenter.run.save()
            process = subprocess.run([sys.executable, '-B', '-m', 'demos.common.capture',
                '--demo', '04-snapshot-dgd', '--run', str(root / 'run'), '--output', str(root / 'capture'),
                '--raw-output', str(root / 'private-raw'), '--rehearsal', '--quiet'],
                cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            receipt = json.loads((root / 'capture/capture.json').read_text())
            self.assertEqual(receipt['status'], 'rehearsal_passed')
            text = (root / 'capture/rehearsal-main.txt').read_text()
            self.assertIn('2/4  Replace the worker Pod', text)
            self.assertIn('4/4  Use the recovered service', text)

    def test_changed_storage_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            demo.SnapshotDgdDemo(args(temp))
            with self.assertRaisesRegex(ValueError, 'Storage choice is frozen'):
                demo.SnapshotDgdDemo(args(temp, storage='efs'))

    def test_repeated_storage_checks_still_run_and_retain_full_private_output(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            presenter.run.state[demo.storage.KEY] = {'staged': True}
            snapshot, content = object(), object()
            calls = []

            def validate(run, actual_snapshot, actual_content):
                calls.append((run, actual_snapshot, actual_content))
                run.result('snapshot-dgd-nvme-staging', 'passed', validation=len(calls))
                return {'validated': len(calls)}

            output = io.StringIO()
            with patch.object(demo.storage, 'ensure', side_effect=validate), contextlib.redirect_stdout(output):
                self.assertEqual(presenter.callback()(presenter.run, snapshot, content), {'validated': 1})
                self.assertEqual(presenter.callback()(presenter.run, snapshot, content), {'validated': 2})
            self.assertEqual(calls, [(presenter.run, snapshot, content)] * 2)
            self.assertEqual(output.getvalue(), '')
            log = (Path(temp) / 'storage-validation.log').read_text()
            self.assertIn('"validation": 1', log)
            self.assertIn('"validation": 2', log)
            self.assertEqual(len(list(Path(temp).glob('check-snapshot-dgd-nvme-staging-*.json'))), 2)
            saved = json.loads((Path(temp) / 'state.json').read_text())
            self.assertEqual(saved['checks']['snapshot-dgd-nvme-staging']['validation'], 2)

    def test_quiet_storage_validation_surfaces_failure_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            presenter.run.state[demo.storage.KEY] = {'staged': True}

            def fail(*_):
                print('Full artifact mismatch details')
                raise ValueError('artifact changed')

            output, errors = io.StringIO(), io.StringIO()
            with patch.object(demo.storage, 'ensure', side_effect=fail), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                    self.assertRaisesRegex(ValueError, 'artifact changed'):
                presenter.callback()(presenter.run, object(), object())
            self.assertEqual(output.getvalue(), '')
            self.assertIn('Storage validation failed; details: storage-validation.log', errors.getvalue())
            self.assertIn('Full artifact mismatch details', (Path(temp) / 'storage-validation.log').read_text())

    def test_changed_frozen_overlay_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            demo.SnapshotDgdDemo(args(temp))
            with (Path(temp) / 'runtime-patch.yaml').open('a') as stream:
                stream.write('\n# changed\n')
            with self.assertRaisesRegex(ValueError, 'Frozen demo input changed'):
                demo.SnapshotDgdDemo(args(temp))

    def test_live_guided_refuses_to_capture_onstage(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'prime offstage'):
                presenter.guided()
            self.assertNotIn('snapshot_dgd_submitted_at', presenter.run.state)

    def test_ready_waiter_never_sends_a_request(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            (Path(temp) / 'restore-agent-full.log').write_text('retained agent evidence')
            identity = {'worker_name': 'worker', 'content_uid': 'content'}
            data = {'dgd': {'items': []}, 'pods': {'items': []}}
            with patch.object(presenter, 'current_identity', return_value=(identity, data)), \
                    patch.object(presenter, 'collect_visible_logs'), patch.object(demo.lifecycle, 'collect_logs'), \
                    patch.object(demo, 'restore_timing', return_value={'agent_seconds': 12, 'phases': {}}), \
                    patch.object(demo.lifecycle, 'coding_request', side_effect=AssertionError('must remain gated')), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = presenter.wait_restored()
            self.assertEqual(result['restore_timing']['agent_seconds'], 12)
            self.assertFalse((Path(temp) / 'response.json').exists())

    def test_final_request_waits_for_both_submission_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
                presenter.replace()
            gates = []
            with patch.object(presenter, 'pause', side_effect=lambda: gates.append(True)), \
                    contextlib.redirect_stdout(io.StringIO()):
                presenter.request()
            self.assertEqual(len(gates), 2)  # port-forward then curl

    def test_uncertain_delete_never_reissues_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            presenter.run.state['replacement_intent'] = {'pod_name': 'old', 'pod_uid': 'old-uid', 'delete_submitted': False}
            result = subprocess.CompletedProcess([], 0, json.dumps({'metadata': {'uid': 'old-uid'}}), '')
            with patch.object(demo.lifecycle, 'require_lease'), patch.object(presenter.run, 'k', return_value=result) as call, \
                    self.assertRaisesRegex(RuntimeError, 'uncertain'):
                presenter.submit_replacement()
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[0], 'get')

    def test_cleanup_preserves_lease_if_workloads_or_storage_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            presenter.run.state['snapshot_dgd_submitted_at'] = 'recorded'
            presenter.run.state[demo.storage.KEY] = {'agent': {}}
            calls = []
            with patch.object(demo.lifecycle, 'require_lease'), \
                    patch.object(demo.lifecycle, 'cleanup', side_effect=lambda *a: calls.append('workloads')), \
                    patch.object(demo.storage, 'cleanup', side_effect=ValueError('mount uncertain')), \
                    patch.object(demo.support, 'release') as release, self.assertRaisesRegex(ValueError, 'mount uncertain'):
                presenter.cleanup()
            self.assertEqual(calls, ['workloads'])
            release.assert_not_called()
            self.assertNotIn('cleaned_at', presenter.data)

    def test_cleanup_order_is_workloads_storage_then_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            presenter = demo.SnapshotDgdDemo(args(temp, rehearsal=False))
            presenter.run.state['snapshot_dgd_submitted_at'] = 'recorded'
            presenter.run.state[demo.storage.KEY] = {'agent': {}}
            calls = []
            with patch.object(demo.lifecycle, 'require_lease'), \
                    patch.object(demo.lifecycle, 'cleanup', side_effect=lambda *a: calls.append('workloads')), \
                    patch.object(demo.storage, 'cleanup', side_effect=lambda *a: calls.append('storage')), \
                    patch.object(demo.support, 'release', side_effect=lambda *a: calls.append('lease')), \
                    contextlib.redirect_stdout(io.StringIO()):
                presenter.cleanup()
            self.assertEqual(calls, ['workloads', 'storage', 'lease'])


class StreamEvidence(unittest.TestCase):
    def raw(self, **kwargs):
        chunk = {'model': 'model', 'choices': [{'delta': {'content': 'def add(a, b):\n    return a + b'}, 'finish_reason': 'stop'}],
            'nvext': {'worker_id': {'decode_worker_id': 123}}}
        chunk.update(kwargs)
        return 'data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n'

    def test_finished_code_and_new_worker_required(self):
        raw = self.raw()
        self.assertEqual(demo.parse_coding_stream(raw, 'model')['worker']['decode_worker_id'], 123)
        for value in (raw.replace('data: [DONE]', ''), self.raw(error={'message': 'failure'}),
                      self.raw(model='another'), self.raw(nvext={}),
                      raw.replace('return a + b', 'return a - b')):
            with self.subTest(value=value), self.assertRaises((ValueError, SyntaxError)):
                demo.parse_coding_stream(value, 'model')


if __name__ == '__main__':
    unittest.main()
