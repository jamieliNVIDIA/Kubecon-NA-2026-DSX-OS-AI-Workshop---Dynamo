"""Importing host tools must not parse CLI arguments or execute operations."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import argparse
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.request

import yaml  # Load the host tools' dependency before forbidding file operations.
from tests.support import ROOT
import testlib


HOST_TOOLS = (
    'archive_evidence', 'cleanup_snapshot_sources', 'cleanup_tests',
    'driver_build_probe', 'driver_node_preflight', 'export_manifests',
    'fetch_kvcr_adapter', 'inspect_driver_management', 'prepare_kvcr',
    'prepare_snapshot', 'prepare_snapshot_current', 'prepare_snapshot_legacy',
    'restore_feature_receipts', 'snapshot_preflight', 'stop_super_vl_startup',
)


class HostScriptImportTests(unittest.TestCase):
    def test_imports_do_not_parse_arguments_touch_runs_or_execute_commands(self):
        for name in HOST_TOOLS:
            with self.subTest(tool=name), ExitStack() as stack:
                for owner, attribute in (
                    (argparse.ArgumentParser, 'parse_args'),
                    (urllib.request, 'urlopen'), (subprocess, 'run'),
                    (subprocess, 'Popen'), (subprocess, 'check_output'),
                    (subprocess, 'check_call'), (os, 'kill'), (testlib, 'Run'),
                    (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'mkdir'),
                    (Path, 'open'), (Path, 'unlink'), (Path, 'rename'),
                ):
                    stack.enter_context(patch.object(owner, attribute, side_effect=AssertionError(
                        f'{name} attempted {attribute} during import')))
                stack.enter_context(redirect_stdout(io.StringIO()))
                stack.enter_context(redirect_stderr(io.StringIO()))
                spec = importlib.util.spec_from_file_location(
                    '_host_import_' + name, ROOT / 'scripts' / (name + '.py'))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertTrue(callable(module.main))

    def test_empty_test_selection_is_an_error(self):
        result = subprocess.run(
            [sys.executable, '-B', '-m', 'tests', 'common', '--pattern', 'no_tests_match.py'],
            cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('No tests matched', result.stderr)
