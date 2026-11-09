"""Lease conflicts must identify the reservation owner's cleanup entry point."""
from tests.support import ROOT
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from demos.common import runtime as ui
from demos.modelexpress.demo import ModelExpressDemo


class DummyMX(ui.Demo):
    """Exercise inherited preparation guidance without binding a live source."""
    entrypoint = ModelExpressDemo.entrypoint


class LeaseGuidanceTests(unittest.TestCase):
    def blocked_prepare(self, requesting_type, owner, expected_selector):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = root / 'lease'
            lease.mkdir()
            original = root / 'original run'
            metadata = {'agent': owner, 'run': str(original), 'acquired_at': 'unchanged'}
            ui.write_json(lease / 'owner.json', metadata)
            frozen_owner = (lease / 'owner.json').read_bytes()
            instance = requesting_type(SimpleNamespace(
                run=root / 'new-run', rehearsal=False, action='prepare', preview=False, auto=True))
            with (mock.patch.object(ui, 'LEASE', lease),
                  mock.patch.object(instance.run, 'apply') as apply,
                  mock.patch.object(instance, 'kubectl') as kubectl):
                with self.assertRaises(RuntimeError) as error:
                    instance.prepare()
            apply.assert_not_called()
            kubectl.assert_not_called()
            self.assertIn(str(original), str(error.exception))
            self.assertEqual((lease / 'owner.json').read_bytes(), frozen_owner)
            if expected_selector:
                command = shlex.split(str(error.exception).splitlines()[-1])
                self.assertEqual(command[1:], [
                    '-m', 'demos', expected_selector, 'cleanup', '--run', str(original)])
            else:
                self.assertIn('Inspect the reservation owner', str(error.exception))
                self.assertNotIn('cleanup --run', str(error.exception))

    def test_model_express_conflict_points_to_single_replica_owner(self):
        self.blocked_prepare(DummyMX, ui.OWNER, 'single-replica')

    def test_single_replica_conflict_points_to_model_express_owner(self):
        self.blocked_prepare(ui.Demo, 'workshop-demo-modelexpress', 'modelexpress')

    def test_unknown_owner_has_no_inferred_cleanup(self):
        self.blocked_prepare(DummyMX, 'external-measurement', None)

    def test_acquire_uses_same_owner_guidance_and_preserves_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / 'lease'
            lease.mkdir()
            metadata = {'agent': ui.OWNER, 'run': str(Path(directory) / 'original')}
            ui.write_json(lease / 'owner.json', metadata)
            with mock.patch.object(ui, 'LEASE', lease):
                with self.assertRaisesRegex(RuntimeError, '-m demos single-replica cleanup --run'):
                    ui.acquire(Path(directory) / 'new-run', 'workshop-demo-modelexpress')
            self.assertEqual(ui.read_json(lease / 'owner.json'), metadata)

    def test_cleanup_guidance_restores_owners_frozen_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'original run'
            run.mkdir()
            allocation = run / 'allocation.json'
            allocation.write_text('{}\n')
            command = shlex.split(ui.lease_conflict(
                {'agent': ui.OWNER, 'run': str(run)}, 'Reserved').splitlines()[-1])
            self.assertEqual(command[:2], ['env', 'WORKSHOP_ALLOCATION=' + str(allocation)])
            self.assertEqual(command[3:], ['-m', 'demos', 'single-replica', 'cleanup', '--run', str(run)])


class NamedLeaseTests(unittest.TestCase):
    """Presenters staged side by side take a named reservation that their run records."""

    def demo(self, path, action='prepare'):
        return ui.Demo(SimpleNamespace(run=path, rehearsal=False, action=action, preview=False, auto=True))

    @contextlib.contextmanager
    def environment(self, name=None):
        with mock.patch.dict(os.environ), mock.patch.object(ui, 'LEASE', ui.LEASE), \
                mock.patch.object(ui, 'ALLOCATION', None):
            os.environ.pop(ui.LEASE_ENV, None)
            if name:
                os.environ[ui.LEASE_ENV] = name
            yield

    def test_new_run_records_the_lease_and_later_actions_use_it_without_the_variable(self):
        shared = ui.LEASE
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            with self.environment('workshop-disagg.gpu-lease'):
                self.demo(run)
                self.assertEqual(ui.LEASE, ui.ROOT / '.local/workshop-disagg.gpu-lease')
            self.assertEqual(ui.LEASE, shared)
            self.assertEqual(ui.read_json(run / 'demo.json')['lease'], '.local/workshop-disagg.gpu-lease')
            with self.environment():
                self.demo(run, 'cleanup')
                self.assertEqual(ui.LEASE, ui.ROOT / '.local/workshop-disagg.gpu-lease')
            with self.environment('workshop-disagg.gpu-lease'):
                self.demo(run, 'run')
            with self.environment('workshop-continuity.gpu-lease'):
                with self.assertRaisesRegex(ValueError, 'reserves .local/workshop-disagg.gpu-lease'):
                    self.demo(run, 'run')

    def test_runs_without_a_named_lease_keep_the_shared_reservation(self):
        shared = ui.LEASE
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            with self.environment():
                self.demo(run)
                self.assertEqual(ui.LEASE, shared)
            self.assertNotIn('lease', ui.read_json(run / 'demo.json'))
            with self.environment('workshop-disagg.gpu-lease'):
                with self.assertRaisesRegex(ValueError, 'uses the shared reservation'):
                    self.demo(run, 'run')

    def test_invalid_names_and_allocation_conflicts_fail_before_creating_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            for name in ('Workshop.gpu-lease', '../shared.gpu-lease', 'workshop-disagg', '.gpu-lease'):
                with self.subTest(name), self.environment(name):
                    with self.assertRaisesRegex(ValueError, ui.LEASE_ENV):
                        self.demo(run)
            with self.environment('workshop-disagg.gpu-lease'), mock.patch.object(ui, 'ALLOCATION', object()):
                with self.assertRaisesRegex(ValueError, 'not both'):
                    self.demo(run)
            self.assertFalse(run.exists())

    def test_tmux_panes_resume_from_the_run_not_the_server_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = SimpleNamespace(path=Path(directory), args=SimpleNamespace(
                port=18003, timeout=60, rehearsal=False, auto=False, detach=True))

            def tmux(command, **kwargs):
                if 'has-session' in command:
                    return subprocess.CompletedProcess(command, 1, '', '')
                output = '$1 @2 %3' if 'new-session' in command else (
                    '%4' if '-h' in command else '%5') if 'split-window' in command else ''
                return subprocess.CompletedProcess(command, 0, output, '')

            with mock.patch.dict(os.environ, {'WORKSHOP_TMUX': '/usr/bin/tmux',
                                              ui.LEASE_ENV: 'workshop-disagg.gpu-lease'}, clear=True), \
                    mock.patch.object(ui, 'ALLOCATION', None), \
                    mock.patch.object(ui.subprocess, 'run', side_effect=tmux) as execute, \
                    contextlib.redirect_stdout(io.StringIO()):
                ui.tmux_layout(instance)
            panes = [call.args[0][-1] for call in execute.call_args_list
                     if 'split-window' in call.args[0] or 'respawn-pane' in call.args[0]]
            self.assertEqual(len(panes), 3)
            for command in panes:
                self.assertEqual(shlex.split(command)[:3], ['env', '-u', ui.LEASE_ENV])


if __name__ == '__main__':
    unittest.main()
