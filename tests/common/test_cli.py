"""The common CLI preserves identities and dispatches without eager demo imports."""
from tests.support import ROOT
import contextlib
from dataclasses import FrozenInstanceError
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


from demos import __main__ as cli
from demos.registry import DEMOS, by_script, get_demo


class DemoCliTests(unittest.TestCase):
    def test_aliases_and_source_paths_preserve_distinct_variant_identities(self):
        for spec in DEMOS.values():
            with self.subTest(demo=spec.id):
                self.assertIs(get_demo(spec.selector), spec)
                self.assertIs(get_demo(spec.id), spec)
                self.assertIs(by_script(spec.path), spec)
                self.assertEqual(spec.path, ROOT.joinpath(*spec.module.split('.')).with_suffix('.py'))
                self.assertEqual(spec.command, 'python -m demos ' + spec.selector)
        self.assertIs(get_demo('01'), get_demo('1'))
        self.assertIs(get_demo('1'), get_demo('single-replica'))
        self.assertIs(get_demo('04'), get_demo('snapshot'))
        self.assertNotEqual(get_demo('snapshot').selection_key, get_demo('snapshot-dgd').selection_key)
        self.assertNotEqual(get_demo('kvcr').selection_key, get_demo('kvcr-prepared').selection_key)
        self.assertNotEqual(get_demo('shadow').selection_key, get_demo('shadow-composed').selection_key)
        with self.assertRaises(FrozenInstanceError):
            get_demo('01').module = 'other'

    def test_dispatch_preserves_demo_options(self):
        with mock.patch.object(cli, 'dispatch') as dispatch:
            result = cli.main(['snapshot-dgd', 'prepare', '--run', 'a-run', '--storage', 'nvme'])
        self.assertEqual(result, 0)
        dispatch.assert_called_once_with(get_demo('snapshot-dgd'),
                                         ['prepare', '--run', 'a-run', '--storage', 'nvme'])

    def test_demo_help_reaches_native_parser(self):
        with mock.patch.object(cli, 'dispatch') as dispatch:
            cli.main(['kvcr-prepared', 'prepare', '--help'])
        dispatch.assert_called_once_with(get_demo('kvcr-prepared'), ['prepare', '--help'])

    def test_first_demo_calls_its_main_and_restores_argv(self):
        previous = sys.argv
        observed = []
        module = SimpleNamespace(main=lambda: observed.append(list(sys.argv)))
        with mock.patch.object(cli.importlib, 'import_module', return_value=module) as load:
            cli.dispatch(get_demo('1'), ['prepare', '--run', 'run'])
        load.assert_called_once_with('demos.single_replica.demo')
        self.assertEqual(observed, [[str(get_demo('1').path), 'prepare', '--run', 'run']])
        self.assertIs(sys.argv, previous)

    def test_other_demos_use_prepared_run_selection_boundary(self):
        presenter = SimpleNamespace(launch=mock.Mock())
        with mock.patch.dict(sys.modules, {'demos.common.presenter': presenter}):
            cli.dispatch(get_demo('shadow-composed'), ['freeze', '--source-writer', 'writer'])
        presenter.launch.assert_called_once_with(get_demo('shadow-composed').path,
                                                 ['freeze', '--source-writer', 'writer'])

    def test_unknown_demo_fails_before_dispatch(self):
        with mock.patch.object(cli, 'dispatch') as dispatch, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                cli.main(['missing'])
        self.assertEqual(error.exception.code, 2)
        dispatch.assert_not_called()

    def test_help_and_listing_need_no_dependencies_or_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            for arguments in (['--help'], ['list']):
                with self.subTest(arguments=arguments):
                    result = subprocess.run([sys.executable, '-S', '-B', '-m', 'demos'] + arguments,
                                            cwd=directory, env=env, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(result.stdout.strip())
                    if arguments == ['list']:
                        for spec in DEMOS.values():
                            self.assertIn(spec.selector, result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_live_only_variants_offer_the_standard_offline_demo_before_selecting_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            for variant, standard in (('kvcr-prepared', 'kvcr'), ('shadow-composed', 'shadow')):
                with self.subTest(variant=variant):
                    result = subprocess.run([sys.executable, '-S', '-B', '-m', 'demos', variant, '--rehearsal'],
                                            cwd=directory, env=env, text=True, capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f'python -m demos {standard} --rehearsal', result.stderr)
                    self.assertNotIn('--run is required', result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
