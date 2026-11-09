"""Native fallback presentation keeps capture and priming offstage."""
from tests.support import ROOT
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from demos.snapshot import demo


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18003, timeout=60, storage=None)


class NativePresentationTests(unittest.TestCase):
    def test_rehearsal_bootstrap_never_waits_for_an_invisible_keypress(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = demo.SnapshotDemo(args(Path(directory) / 'run'))
            presenter.args.auto = False
            with mock.patch.object(presenter, 'pause', side_effect=lambda: self.assertTrue(presenter.args.auto)), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                presenter.require_primed()
            self.assertTrue(presenter.data['prepared'])
            self.assertTrue(presenter.data['restores'])
            self.assertFalse(presenter.args.auto)
            self.assertEqual(output.getvalue(), '')

    def test_live_walkthrough_requires_a_primed_serving_pod_before_any_cluster_action(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = demo.SnapshotDemo(args(Path(directory) / 'run'))
            presenter.args.rehearsal = False
            presenter.data['prepared'] = True
            with mock.patch.object(presenter, 'prime') as prime, \
                    mock.patch.object(presenter, 'prepare') as prepare, \
                    mock.patch.object(presenter.run, 'k') as kubectl, \
                    self.assertRaisesRegex(ValueError, 'Run prime offstage'):
                presenter.guided()
            prime.assert_not_called()
            prepare.assert_not_called()
            kubectl.assert_not_called()

    def test_pending_replacement_keeps_absolute_stage_numbers_and_does_not_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = demo.SnapshotDemo(args(Path(directory) / 'run'))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            presenter.data['replacement_pending'] = True
            output = io.StringIO()
            with mock.patch.object(presenter, 'prepare', side_effect=AssertionError('offstage')), \
                    contextlib.redirect_stdout(output):
                presenter.guided()
            self.assertIn('2/4  Replace the Pod', output.getvalue())
            self.assertIn('4/4  Use the recovered engine', output.getvalue())
            self.assertEqual(presenter.data['step'], 4)
            self.assertNotIn('Step finished in', output.getvalue())

    def test_existing_primed_walkthrough_does_not_prime_or_prepare_again(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = demo.SnapshotDemo(args(Path(directory) / 'run'))
            with contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            presenter.args.rehearsal = False
            with mock.patch.object(presenter, 'prime') as prime, \
                    mock.patch.object(presenter, 'prepare') as prepare, \
                    mock.patch.object(presenter, 'run_steps') as steps, \
                    contextlib.redirect_stdout(io.StringIO()):
                presenter.guided()
            prime.assert_not_called()
            prepare.assert_not_called()
            steps.assert_called_once()


if __name__ == '__main__':
    unittest.main()
