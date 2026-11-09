"""The jump-host setup selects the workspace environment on Linux shells."""
from tests.support import ROOT
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


class JumpEnvironmentTests(unittest.TestCase):
    def make_workspace(self, directory):
        root = Path(directory) / 'workspace with spaces'
        (root / 'scripts').mkdir(parents=True)
        shutil.copy2(ROOT / 'scripts/kubecon-jump-env.sh', root / 'scripts/kubecon-jump-env.sh')
        (root / '.local/bin').mkdir(parents=True)
        kubectl = root / '.local/bin/kubectl'
        kubectl.write_text('#!/bin/sh\nprintf "ok\\n"\n')
        kubectl.chmod(0o755)
        (root / '.local/kubeconfig').write_text('fixture configuration\n')
        (root / '.local/pull-secret-source').write_text('source/pull\n')
        return root

    def make_environment(self, path, marker):
        (path / 'bin').mkdir(parents=True)
        python = path / 'bin/python'
        python.write_text('#!/bin/sh\nprintf ' + shlex.quote(marker + '\n') + '\n')
        python.chmod(0o755)
        (path / 'bin/activate').write_text('export VIRTUAL_ENV=' + shlex.quote(str(path)) + '\n')

    def source(self, root):
        env = dict(os.environ, VIRTUAL_ENV='/previously/activated/environment')
        env.pop('WORKSHOP_PULL_SECRET_SOURCE', None)
        env.pop('WORKSHOP_PYTHON', None)
        return subprocess.run([
            'bash', '-ec', 'source "$1"; printf "VENV=%s\\nPYTHON=%s\\n" "$VIRTUAL_ENV" "$WORKSHOP_PYTHON"; python',
            'bash', str(root / 'scripts/kubecon-jump-env.sh')],
            env=env, capture_output=True, text=True, timeout=10)

    def test_uv_environment_wins_over_previously_activated_and_legacy_environments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_workspace(directory)
            self.make_environment(root / '.venv', 'selected-uv-environment')
            self.make_environment(root / '.local/venv', 'legacy-environment')
            result = self.source(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('VENV=' + str(root / '.venv'), result.stdout)
            self.assertIn('PYTHON=' + str(root / '.venv/bin/python'), result.stdout)
            self.assertIn('selected-uv-environment', result.stdout)
            self.assertNotIn('legacy-environment', result.stdout)

    def test_legacy_environment_can_still_select_the_existing_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_workspace(directory)
            self.make_environment(root / '.local/venv', 'selected-legacy-environment')
            result = self.source(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('VENV=' + str(root / '.local/venv'), result.stdout)
            self.assertIn('selected-legacy-environment', result.stdout)

    def test_missing_environment_reports_uv_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.source(self.make_workspace(directory))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('uv sync --locked', result.stdout + result.stderr)
