"""Recovery guards must preserve the original profile and failure receipts."""
from tests.support import ROOT
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    'recover_workshop_disagg_profile', ROOT / 'scripts/development/disaggregated/recover_profile.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class OriginalProfileRecoveryGuards(unittest.TestCase):
    def status(self, terminal=False):
        return {'original_profile_sha256': 'profile-hash',
                'process': {'pid': 123, 'started_at': '2026-11-05T20:02:00Z'},
                'exit': {'exit_code': 0} if terminal else None,
                'active_process_command': None if terminal else
                    '/original/venv/bin/python -m aiperf profile --config /original/profile.yaml',
                'console_tail': 'original output'}

    def test_inspection_accepts_original_active_or_terminal_profile(self):
        for terminal in (False, True):
            recovery.validate_original_status(self.status(terminal), 'profile-hash')

    def test_collection_refuses_original_active_profile(self):
        with self.assertRaisesRegex(ValueError, 'still running.*never replay'):
            recovery.validate_original_status(self.status(), 'profile-hash', completed=True)

    def test_changed_identity_or_unverifiable_process_is_rejected(self):
        for changed in ('hash', 'process', 'dead', 'unrelated'):
            value = self.status()
            if changed == 'hash':
                value['original_profile_sha256'] = 'changed'
            elif changed == 'process':
                value['process'] = None
            elif changed == 'dead':
                value['active_process_command'] = None
            else:
                value['active_process_command'] = '/usr/bin/python unrelated.py'
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                recovery.validate_original_status(value, 'profile-hash')

    def test_nonzero_original_exit_is_retained_for_diagnostics(self):
        value = self.status(terminal=True)
        value['exit']['exit_code'] = 1
        original = copy.deepcopy(value)
        recovery.validate_original_status(value, 'profile-hash', completed=True)
        self.assertEqual(value, original)

    def test_snapshot_copies_failure_receipts_without_rewriting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(path=Path(directory))
            folder = run.path / 'original-arm'
            folder.mkdir()
            destination = run.path / 'recovery'
            destination.mkdir()
            (folder / 'latest-profile.json').write_text('{"exit": null}\n')
            failure = run.path / 'controller-a2-exit.json'
            failure.write_text('{"status": "blocked", "cleanup": "blocked"}\n')
            original = failure.read_bytes()
            recovery.snapshot_before(run, folder, destination)
            self.assertEqual(failure.read_bytes(), original)
            copied = destination / 'before-recovery'
            self.assertEqual((copied / failure.name).read_bytes(), original)
            hashes = json.loads((destination / 'before-recovery-sha256.json').read_text())
            self.assertEqual(hashes[failure.name], recovery.handoff.b.sha(failure))
            self.assertTrue((folder / 'latest-profile.json').exists())

    def test_inspect_only_reads_original_and_never_replays_or_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(path=Path(directory))
            arm = 'original-pd-arm'
            folder = run.path / arm
            folder.mkdir()
            (folder / 'launch.json').write_text('{"runner_pid": 100}\n')
            (folder / 'spec.json').write_text('{"profile_sha256": "profile-hash"}\n')
            (run.path / 'campaign.json').write_text('{}\n')
            campaign = {'arm_names': {'disaggregated': arm},
                        'client_binding': {'pod_uid': 'original-cpu'}}
            b = recovery.handoff.b
            with mock.patch.object(b, 'verify'), \
                 mock.patch.object(recovery.handoff, 'check_client'), \
                 mock.patch.object(b, 'spec', return_value=campaign), \
                 mock.patch.object(b.e, 'client', return_value=SimpleNamespace(
                     stdout=json.dumps(self.status()))) as remote_read, \
                 mock.patch.object(b.e, 'launch_profile') as launch, \
                 mock.patch.object(b.e, 'collect_profile') as collect, \
                 mock.patch.object(b.c, 'cleanup_gpu') as cleanup, \
                 contextlib.redirect_stdout(io.StringIO()):
                recovery.recovery(run, 'inspect1', collect=False)
            launch.assert_not_called()
            collect.assert_not_called()
            cleanup.assert_not_called()
            remote_read.assert_called_once_with(
                run, recovery.REMOTE_INSPECT, argv=(arm, 'profile-hash'))
            evidence = json.loads((run.path / 'profile-recovery-inspect1/context.json').read_text())
            self.assertFalse(evidence['profile_replayed'])
            self.assertFalse(evidence['cleanup_performed'])
            self.assertEqual(json.loads((run.path / 'profile-recovery-inspect1/original-remote-status.json').read_text()),
                             self.status())

    def test_collect_refuses_replaced_serving_pod_before_export_or_sampler_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(path=Path(directory))
            arm = 'original-pd-arm'
            folder = run.path / arm
            folder.mkdir()
            (folder / 'launch.json').write_text('{"runner_pid": 100}\n')
            (folder / 'spec.json').write_text('{"profile_sha256": "profile-hash"}\n')
            (folder / 'worker-qualification.json').write_text(json.dumps({
                'workers': {'prefill': {'pod_uid': 'original-prefill'},
                            'decode': {'pod_uid': 'original-decode'}}}))
            (run.path / 'campaign.json').write_text('{}\n')
            campaign = {'arm_names': {'disaggregated': arm},
                        'client_binding': {'pod_uid': 'original-cpu'}}
            b = recovery.handoff.b
            with mock.patch.object(b, 'verify'), \
                 mock.patch.object(recovery.handoff, 'check_client'), \
                 mock.patch.object(b, 'spec', return_value=campaign), \
                 mock.patch.object(b.e, 'client', return_value=SimpleNamespace(
                     stdout=json.dumps(self.status(terminal=True)))), \
                 mock.patch.object(b.c, 'lease_owned'), \
                 mock.patch.object(b.e, 'workers', return_value=[
                     {'metadata': {'uid': 'replacement-prefill'}},
                     {'metadata': {'uid': 'original-decode'}}]), \
                 mock.patch.object(b.e, 'telemetry_stop') as stop, \
                 mock.patch.object(b.e, 'collect_profile') as collect, \
                 mock.patch.object(b.e, 'launch_profile') as launch, \
                 mock.patch.object(b.c, 'cleanup_gpu') as cleanup:
                with self.assertRaisesRegex(ValueError, 'serving Pods changed'):
                    recovery.recovery(run, 'collect1', collect=True)
            for mutation in (stop, collect, launch, cleanup):
                mutation.assert_not_called()
            self.assertFalse((folder / 'outcome.json').exists())
            self.assertFalse((folder / 'raw').exists())


if __name__ == '__main__':
    unittest.main()
