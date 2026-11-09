"""Reuse a cluster pull secret without putting its contents in command receipts."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.support import ROOT
import common_runtime_build as build
import common_runtime_tests as runtime


class PullSecretTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for patcher in (mock.patch.object(runtime, 'ROOT', self.root),
                        mock.patch.dict(os.environ, {}, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_context(self):
        run = mock.Mock()
        run.ns = 'owned-demo'
        run.kbase = ['kubectl', '--kubeconfig=direct']
        run.get.return_value = {'metadata': {'labels': {'app.kubernetes.io/managed-by': runtime.OWNER}}}
        run.k.return_value = SimpleNamespace(returncode=1, stdout='')
        run.labels.return_value = {'feature-test-run': run.ns}
        return run

    def test_source_secret_is_read_without_receipts_and_relabelled_for_target(self):
        run = self.run_context()
        config = {'auths': {'nvcr.io': {'auth': 'private-test-value'}}}
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        source = {'type': 'kubernetes.io/dockerconfigjson', 'data': {'.dockerconfigjson': encoded},
                  'metadata': {'namespace': 'source', 'uid': 'source-uid'}}
        response = subprocess.CompletedProcess([], 0, json.dumps(source), '')
        with mock.patch.dict(os.environ, WORKSHOP_PULL_SECRET_SOURCE='source/pull'), \
                mock.patch.object(runtime.subprocess, 'run', return_value=response) as read, \
                mock.patch.object(runtime, 'ngc_credential') as desktop:
            runtime.pull_secret(run)
        desktop.assert_not_called()
        self.assertIn('secret', read.call_args.args[0])
        self.assertFalse(any('get' in call.args and 'secret' in call.args and '-o' in call.args and
                             'json' in call.args for call in run.k.call_args_list))
        self.assertEqual(run.k.call_count, 3)
        for call in run.k.call_args_list[1:]:
            self.assertNotIn('private-test-value', repr(call.args))
            target = json.loads(call.kwargs['input_text'])
            self.assertEqual(target['metadata'], {'name': runtime.SECRET, 'namespace': run.ns,
                                                  'labels': run.labels()})
            self.assertEqual(target['data']['.dockerconfigjson'], encoded)
        run.apply.assert_not_called()

    def test_failed_source_read_does_not_apply_or_expose_output(self):
        run = self.run_context()
        with mock.patch.dict(os.environ, WORKSHOP_PULL_SECRET_SOURCE='source/pull'), \
                mock.patch.object(runtime.subprocess, 'run', return_value=
                                  subprocess.CompletedProcess([], 1, 'private-data', 'private-error')):
            with self.assertRaisesRegex(RuntimeError, '^Cannot read the configured workshop pull secret$'):
                runtime.pull_secret(run)
        self.assertEqual(run.k.call_count, 1)

    def test_mac_credential_path_remains_available(self):
        run = self.run_context()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(runtime, 'ngc_credential', return_value={'Username': 'user', 'Secret': 'key'}):
            runtime.pull_secret(run)
        self.assertEqual(run.k.call_count, 3)

    def test_saved_cluster_reference_works_without_sourcing_shell_environment(self):
        saved = self.root / '.local/pull-secret-source'
        saved.parent.mkdir()
        saved.write_text('source/saved-pull\n')
        run = self.run_context()
        config = {'auths': {'nvcr.io': {'auth': 'private-test-value'}}}
        source = {'type': 'kubernetes.io/dockerconfigjson', 'data': {
            '.dockerconfigjson': base64.b64encode(json.dumps(config).encode()).decode()}}
        with mock.patch.object(runtime.subprocess, 'run', return_value=
                               subprocess.CompletedProcess([], 0, json.dumps(source), '')) as read, \
                mock.patch.object(runtime, 'ngc_credential') as desktop:
            runtime.pull_secret(run)
        desktop.assert_not_called()
        self.assertEqual(read.call_args.args[0][-6:], ['secret', 'saved-pull', '-n', 'source', '-o', 'json'])
        run.apply.assert_not_called()
        self.assertNotIn('private-test-value', repr(run.k.call_args_list))

    def test_explicit_reference_takes_precedence_and_invalid_saved_reference_fails_closed(self):
        saved = self.root / '.local/pull-secret-source'
        saved.parent.mkdir()
        saved.write_text('source/saved-pull\n')
        with mock.patch.dict(os.environ, WORKSHOP_PULL_SECRET_SOURCE='override/pull'):
            self.assertEqual(runtime.configured_pull_secret_source(), ['override', 'pull'])
        for value in ('', 'source', 'source/pull/extra', 'source/--flag', '--flag/pull', 'source/with space'):
            saved.write_text(value)
            with self.subTest(reference=value), mock.patch.object(runtime, 'ngc_credential') as desktop:
                with self.assertRaisesRegex(ValueError, 'must be namespace/name'):
                    runtime.pull_secret(self.run_context())
                desktop.assert_not_called()


class DockerCredentialTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.config = Path(temporary.name) / 'config.json'
        for patcher in (mock.patch.dict(os.environ, {'DOCKER_CONFIG': str(self.config.parent)}, clear=True),
                        mock.patch.object(build.sys, 'platform', 'linux')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def save_config(self, data):
        self.config.write_text(json.dumps(data))

    def test_linux_uses_registry_helper_before_global_store(self):
        self.save_config({'credHelpers': {'nvcr.io': 'secretservice'}, 'credsStore': 'other'})
        result = subprocess.CompletedProcess([], 0, json.dumps({'Username': 'user', 'Secret': 'private-key'}), '')
        with mock.patch.object(build.shutil, 'which', return_value='/usr/bin/docker-credential-secretservice') as which, \
                mock.patch.object(build.subprocess, 'run', return_value=result) as execute:
            self.assertEqual(build.ngc_credential(), {'Username': 'user', 'Secret': 'private-key'})
        which.assert_called_once_with('docker-credential-secretservice')
        self.assertEqual(execute.call_args.args[0], ['/usr/bin/docker-credential-secretservice', 'get'])
        self.assertEqual(execute.call_args.kwargs['input'], 'nvcr.io\n')

    def test_linux_uses_configured_global_store(self):
        self.save_config({'credsStore': 'pass'})
        result = subprocess.CompletedProcess([], 0, '{"Username":"user","Secret":"key"}', '')
        with mock.patch.object(build.shutil, 'which', return_value='/usr/bin/docker-credential-pass') as which, \
                mock.patch.object(build.subprocess, 'run', return_value=result):
            self.assertEqual(build.ngc_credential()['Username'], 'user')
        which.assert_called_once_with('docker-credential-pass')

    def test_linux_reads_existing_auth_without_a_helper(self):
        auth = base64.b64encode(b'$oauthtoken:private:key').decode()
        self.save_config({'auths': {'nvcr.io': {'auth': auth}}})
        with mock.patch.object(build.subprocess, 'run') as execute:
            self.assertEqual(build.ngc_credential(), {'Username': '$oauthtoken', 'Secret': 'private:key'})
        execute.assert_not_called()

    def test_linux_missing_credentials_explains_cluster_reference_and_never_uses_mac_path(self):
        with mock.patch.object(build.subprocess, 'run') as execute, \
                mock.patch.object(build.shutil, 'which') as which:
            with self.assertRaisesRegex(RuntimeError, 'WORKSHOP_PULL_SECRET_SOURCE=namespace/name') as error:
                build.ngc_credential()
        self.assertNotIn('/Applications/', str(error.exception))
        execute.assert_not_called()
        which.assert_not_called()

    def test_unavailable_or_failing_helper_does_not_expose_output_or_use_a_mac_fallback_on_linux(self):
        self.save_config({'credsStore': 'desktop'})
        with mock.patch.object(build.shutil, 'which', return_value=None), \
                mock.patch.object(build.Path, 'is_file', side_effect=AssertionError('Mac path lookup on Linux')), \
                mock.patch.object(build.subprocess, 'run') as execute:
            with self.assertRaisesRegex(RuntimeError, 'unavailable on this host'):
                build.ngc_credential()
        execute.assert_not_called()
        for response in (subprocess.CompletedProcess([], 1, 'private-key', 'private-error'),
                         subprocess.CompletedProcess([], 0, 'private-key', 'private-error')):
            with self.subTest(code=response.returncode), \
                    mock.patch.object(build.shutil, 'which', return_value='/usr/bin/docker-credential-desktop'), \
                    mock.patch.object(build.subprocess, 'run', return_value=response):
                with self.assertRaises(RuntimeError) as error:
                    build.ngc_credential()
                self.assertNotIn('private-key', str(error.exception))
                self.assertNotIn('private-error', str(error.exception))

    def test_mac_fallback_requires_an_installed_executable(self):
        result = subprocess.CompletedProcess([], 0, '{"Username":"user","Secret":"key"}', '')
        with mock.patch.object(build.sys, 'platform', 'darwin'), \
                mock.patch.object(build.shutil, 'which', return_value=None), \
                mock.patch.object(build.Path, 'is_file', return_value=True), \
                mock.patch.object(build.os, 'access', return_value=True), \
                mock.patch.object(build.subprocess, 'run', return_value=result) as execute:
            build.ngc_credential()
        self.assertEqual(execute.call_args.args[0],
                         ['/Applications/Docker.app/Contents/Resources/bin/docker-credential-desktop', 'get'])

    def test_malformed_config_and_auth_errors_are_sanitized(self):
        for data in ('private-config-value', json.dumps({'auths': {'nvcr.io': {'auth': 'private-key'}}})):
            self.config.write_text(data)
            with self.subTest(config=data), self.assertRaises(RuntimeError) as error:
                build.ngc_credential()
            self.assertNotIn('private-config-value', str(error.exception))
            self.assertNotIn('private-key', str(error.exception))


if __name__ == '__main__':
    unittest.main()
