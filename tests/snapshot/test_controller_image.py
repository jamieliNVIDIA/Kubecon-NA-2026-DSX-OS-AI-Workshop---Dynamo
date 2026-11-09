"""Owned CPU image preparation never mutates or silently replaces a GPU run."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import demos.snapshot.controller_image as subject


class ControllerImage(unittest.TestCase):
    def run_fixture(self, root, deployed=False):
        run = root / 'results/snapshot-a3';run.mkdir(parents=True)
        (run / 'state.json').write_text(json.dumps({'snapshot_dgd_uid': 'already' if deployed else None}))
        return run

    def reply(self, args, **kwargs):
        payload = json.loads(kwargs['input'])
        packages = json.dumps([{'package': 'curl', 'version': '1', 'architecture': 'amd64'}]) + '\n'
        receipt = {'schema': 1, 'status': 'built', 'base_image': subject.BASE,
            'base_image_id': 'sha256:' + 'b' * 64, 'image_id': 'sha256:' + 'c' * 64,
            'tag': payload['tag'], 'dockerfile_sha256': payload['dockerfile_sha256'],
            'curl_version': 'curl test-version', 'packages_sha256': subject.sha(packages.encode())}
        return subprocess.CompletedProcess(args, 0, json.dumps({'receipt': receipt, 'packages_json': packages,
                                                               'build_console': 'owned image built'}), '')

    def test_gpu_submission_refused_before_any_build_or_local_intent(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'ROOT', Path(temp).resolve()):
            run = self.run_fixture(Path(temp), deployed=True)
            with patch.object(subject.subprocess, 'run') as command, self.assertRaisesRegex(ValueError, 'before starting GPUs'):
                subject.build(run)
            command.assert_not_called()
            self.assertFalse((run / 'controller-image').exists())

    def test_pinned_base_recipe_and_exact_result_bytes_retained_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'ROOT', Path(temp).resolve()):
            run = self.run_fixture(Path(temp))
            with patch.object(subject.subprocess, 'run', side_effect=self.reply) as command, patch('sys.stdout'):
                receipt = subject.build(run)
            payload = json.loads(command.call_args.kwargs['input'])
            self.assertEqual(payload['base_image'], subject.BASE)
            self.assertTrue(payload['dockerfile'].startswith('FROM ' + subject.BASE))
            self.assertNotIn('kubeconfig', payload['dockerfile'])
            self.assertEqual(receipt['packages_sha256'], subject.sha((run / 'controller-image/packages.json').read_bytes()))
            self.assertEqual(receipt['dockerfile_sha256'], subject.sha((run / 'controller-image/Dockerfile').read_bytes()))
            with patch.object(subject.subprocess, 'run') as second, self.assertRaises(FileExistsError):
                subject.build(run)
            second.assert_not_called()

    def test_corrupt_package_provenance_does_not_create_a_runtime_receipt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'ROOT', Path(temp).resolve()):
            run = self.run_fixture(Path(temp))
            def corrupt(args, **kwargs):
                response = self.reply(args, **kwargs);data = json.loads(response.stdout)
                data['receipt']['packages_sha256'] = 'wrong'
                return subprocess.CompletedProcess(args, 0, json.dumps(data), '')
            with patch.object(subject.subprocess, 'run', side_effect=corrupt), self.assertRaisesRegex(ValueError, 'provenance differs'):
                subject.build(run)
            self.assertFalse((run / 'controller-image.json').exists())
            self.assertTrue((run / 'controller-image/intent.json').exists())

    def test_explicit_new_attempt_preserves_failed_context_and_avoids_legacy_flag(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'ROOT', Path(temp).resolve()):
            run = self.run_fixture(Path(temp));folder = run / 'controller-image';folder.mkdir()
            (folder / 'Dockerfile').write_text(subject.DOCKERFILE)
            (folder / 'intent.json').write_text('original first intent')
            (folder / 'transport.json').write_text('original unsupported flag failure')
            with patch.object(subject.subprocess, 'run', side_effect=self.reply) as command, patch('sys.stdout'):
                subject.build(run, attempt='a2')
            payload = json.loads(command.call_args.kwargs['input'])
            self.assertTrue(payload['remote_build_dir'].endswith('-a2'))
            self.assertTrue(payload['tag'].endswith('-a2'))
            self.assertNotIn('--progress', subject.BUILD)
            self.assertEqual((folder / 'intent.json').read_text(), 'original first intent')
            self.assertEqual((folder / 'transport.json').read_text(), 'original unsupported flag failure')
            self.assertTrue((folder / 'attempts/a2/transport.json').exists())
            with self.assertRaises(ValueError):subject.build(run, attempt='../bad')


if __name__ == '__main__':
    unittest.main()
