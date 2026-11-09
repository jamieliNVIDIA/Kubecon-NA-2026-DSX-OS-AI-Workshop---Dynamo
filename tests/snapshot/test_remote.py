"""Source-bundle and result-archive safety for the Snapshot remote controller."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import demos.snapshot.remote as subject


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(path, files, manifest_name, manifest, *, extra=None):
    with tarfile.open(path, 'w:gz') as tar:
        for name, raw in files.items():
            member = tarfile.TarInfo(name);member.size = len(raw)
            tar.addfile(member, io.BytesIO(raw))
        raw = (json.dumps(manifest) + '\n').encode()
        member = tarfile.TarInfo(manifest_name);member.size = len(raw)
        tar.addfile(member, io.BytesIO(raw))
        if extra is not None:
            tar.addfile(extra)


def fixture(root):
    run = root / 'results/demo-04-snapshot-test'
    run.mkdir(parents=True)
    (root / 'scripts').mkdir()
    (root / 'configs').mkdir()
    (root / '.local').mkdir()
    (root / subject.CONTROLLER).parent.mkdir(parents=True, exist_ok=True)
    (root / subject.CONTROLLER).write_text('# controller source\n')
    (root / 'scripts/example.py').write_text('# source\n')
    (root / 'configs/model.json').write_text('{"model":"example/model"}\n')
    namespace = 'dynamo-ft-unit-test'
    spec = {'namespace': namespace, 'settings': {'gpu_uuids': ['GPU-1', 'GPU-3'], 'node': 'node1'}}
    state = {'namespace': namespace, 'owner': 'kubecon-dynamo-feature-tests',
        'checks': {'model-staging': {'status': 'passed'}}, 'workshop_snapshot_nvme': {'agent': {'uid': 'agent-uid'}}}
    for name, value in [('state.json', state), ('snapshot-dgd-spec.json', spec),
                        ('nvme-agent-before.json', {'metadata': {'uid': 'agent-uid'}}), ('nvme-inspection.json', {'uid': 'agent-uid'}),
                        ('deployment.json', {'kind': 'DynamoGraphDeployment'}), ('model-lock.json', {'model': 'example/model'})]:
        (run / name).write_text(json.dumps(value) + '\n')
    data = {'namespace': namespace, 'prepared': True, 'rehearsal': False, 'storage': 'nvme',
        'source_hashes': {'configs/model.json': subject.sha(root / 'configs/model.json')},
        'inputs': {'deployment.json': subject.sha(run / 'deployment.json')}}
    (run / 'demo.json').write_text(json.dumps(data) + '\n')
    reservation = {'agent': subject.OWNER, 'run': str(run), 'acquired_at': '2026-11-05T00:00:00+00:00'}
    lease = root / subject.LEASE;lease.parent.mkdir(parents=True)
    lease.write_text(json.dumps(reservation) + '\n')
    return run, data, state


def derived_image(run):
    folder = run / 'controller-image';folder.mkdir()
    dockerfile = folder / 'Dockerfile';dockerfile.write_text('FROM ' + subject.IMAGE + '\nRUN install-curl\n')
    packages = folder / 'packages.json';packages.write_text(json.dumps({'curl': '8.0-test'}) + '\n')
    receipt = {'schema': 1, 'status': 'built', 'base_image': subject.IMAGE,
        'base_image_id': 'sha256:' + 'a' * 64, 'image_id': 'sha256:' + 'b' * 64,
        'tag': 'owned-controller:test', 'dockerfile_sha256': subject.sha(dockerfile),
        'packages_sha256': subject.sha(packages), 'curl_version': 'curl 8.0-test'}
    (run / 'controller-image.json').write_text(json.dumps(receipt) + '\n')
    return receipt


class ControllerImages(unittest.TestCase):
    def test_derived_image_is_pinned_by_id_and_only_build_provenance_is_packaged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _ = fixture(root);receipt = derived_image(run)
            (run / 'controller-image/build.log').write_text('not an input: private build output')
            with patch.object(subject, 'ROOT', root):
                self.assertEqual(subject.runtime_image(run), receipt['image_id'])
                result = subject.build(run)
                manifest = json.loads((run / 'remote-package/payload-manifest.json').read_text())
                plan = json.loads((run / 'remote-package/plan.json').read_text())
            self.assertEqual(result['image'], receipt['image_id'])
            self.assertEqual(result['controller_name'], manifest['name'])
            self.assertEqual(result['controller_name'], plan['controller_name'])
            self.assertEqual(manifest['image'], receipt['image_id'])
            self.assertEqual(manifest['base_image'], subject.IMAGE)
            self.assertEqual(plan['runtime']['receipt_sha256'], subject.sha(run / 'controller-image.json'))
            self.assertEqual(plan['runtime'], manifest['runtime'])
            names = set(manifest['files'])
            prefix = str(run.relative_to(root)) + '/'
            self.assertTrue(all(prefix + name in names for name in subject.IMAGE_INPUTS))
            self.assertNotIn(prefix + 'controller-image/build.log', names)

    def test_unbuilt_wrong_base_or_malformed_image_receipt_rejected(self):
        for field, value in (('schema', 0), ('status', 'building'), ('base_image', 'unapproved:latest'),
                             ('image_id', 'docker.io/other:latest'), ('base_image_id', 'missing'), ('curl_version', '')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, _, _ = fixture(root);receipt = derived_image(run)
                receipt[field] = value;(run / 'controller-image.json').write_text(json.dumps(receipt))
                with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'receipt'):
                    subject.runtime_image(run)

    def test_dockerfile_and_packages_hash_mismatch_rejected(self):
        for name in ('Dockerfile', 'packages.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();run, _, _ = fixture(root);derived_image(run)
                with (run / 'controller-image' / name).open('a') as stream:stream.write('changed\n')
                with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'hash differs'):
                    subject.runtime_image(run)

    def test_no_receipt_keeps_original_base_and_launch_refuses_receipt_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _ = fixture(root)
            with patch.object(subject, 'ROOT', root):
                self.assertEqual(subject.runtime_image(run), subject.IMAGE)
                receipt = derived_image(run);subject.build(run)
                receipt['curl_version'] = 'another build';(run / 'controller-image.json').write_text(json.dumps(receipt))
                with patch.object(subject.subprocess, 'run', side_effect=AssertionError('No network on drift')), \
                        self.assertRaisesRegex(ValueError, 'changed'):
                    subject.launch(run)


class Payloads(unittest.TestCase):
    def test_build_excludes_private_credentials_and_cpu_secret_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _ = fixture(root)
            secret = b'{"kind":"Secret","data":{"token":"credential-value"}}'
            (run / 'manifest-0001.json').write_bytes(secret)
            (run / 'command-0001.json').write_bytes(secret)
            (root / '.local/kubeconfig').write_bytes(secret)
            launcher = root / 'demos/snapshot/dgd_demo.py';launcher.parent.mkdir(parents=True, exist_ok=True)
            launcher.write_text('#!/bin/sh\n');launcher.chmod(0o700)
            with patch.object(subject, 'ROOT', root):
                result = subject.build(run)
                prep = subject.prep_path(run)
                manifest = subject.verify_payload(prep / 'payload.tar.gz', result['payload_sha256'])
            names = set(manifest['files'])
            self.assertFalse(any('.local' in name or name.endswith(('manifest-0001.json', 'command-0001.json')) for name in names))
            self.assertIn('demos/snapshot/dgd_demo.py', names)
            self.assertEqual(manifest['files']['demos/snapshot/dgd_demo.py']['mode'], 0o700)
            with tarfile.open(prep / 'payload.tar.gz') as tar:
                self.assertFalse(any(b'credential-value' in tar.extractfile(member).read() for member in tar.getmembers()))

    def test_build_refuses_reuse_and_submitted_or_unprepared_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, data, state = fixture(root)
            with patch.object(subject, 'ROOT', root):
                data['prepared'] = False;(run / 'demo.json').write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'CPU-prepared'):
                    subject.build(run)
                data['prepared'] = True;(run / 'demo.json').write_text(json.dumps(data))
                state['snapshot_dgd_submitted_at'] = 'already';(run / 'state.json').write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, 'CPU-prepared'):
                    subject.build(run)
                state.pop('snapshot_dgd_submitted_at');(run / 'state.json').write_text(json.dumps(state))
                subject.build(run)
                with self.assertRaises(FileExistsError):
                    subject.build(run)

    def test_build_rejects_private_source_path_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, data, _ = fixture(root)
            private = root / '.local/kubeconfig';private.write_text('do not copy')
            data['source_hashes'] = {'.local/kubeconfig': subject.sha(private)}
            (run / 'demo.json').write_text(json.dumps(data))
            with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Credential'):
                subject.prepared_inputs(run)
            alias = root / 'configs/alias.json';alias.symlink_to(private)
            data['source_hashes'] = {'configs/alias.json': subject.sha(private)};(run / 'demo.json').write_text(json.dumps(data))
            with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'symlink'):
                subject.prepared_inputs(run)

    def test_missing_nvme_inspection_refuses_before_packaging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _ = fixture(root);(run / 'nvme-agent-before.json').unlink()
            with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'inspection'):
                subject.prepared_inputs(run)

    def test_symlinked_source_ancestor_cannot_hide_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, data, _ = fixture(root)
            private = root / '.local/private';private.mkdir();(private / 'module.py').write_text('private bytes')
            alias = root / 'configs/alias';alias.symlink_to(private, target_is_directory=True)
            data['source_hashes'] = {'configs/alias/module.py': subject.sha(private / 'module.py')}
            (run / 'demo.json').write_text(json.dumps(data))
            with patch.object(subject, 'ROOT', root), self.assertRaisesRegex(ValueError, 'ancestor'):
                subject.prepared_inputs(run)

    def test_forged_payload_hash_or_credential_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.tar.gz'
            files = {'.local/kubeconfig': b'never'}
            manifest = {'files': {name: {'sha256': digest(raw), 'bytes': len(raw), 'mode': 0o600} for name, raw in files.items()}}
            archive(path, files, 'payload-manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'hash/size'):
                subject.verify_payload(path, '0' * 64)
            with self.assertRaisesRegex(ValueError, 'Credential'):
                subject.verify_payload(path, subject.sha(path))

    def test_changed_input_after_build_prevents_network_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();run, _, _ = fixture(root)
            with patch.object(subject, 'ROOT', root):
                subject.build(run)
                (root / 'scripts/example.py').write_text('# changed\n')
                with patch.object(subject.subprocess, 'run', side_effect=AssertionError('No network call')), \
                        self.assertRaisesRegex(ValueError, 'changed after build'):
                    subject.launch(run)


class Collections(unittest.TestCase):
    expected = {'run': 'results/run1', 'controller_name': 'controller1', 'plan_sha256': 'a' * 64}

    def package(self, path, payload=None, **overrides):
        files = payload or {'run/demo.json': b'{"prepared":true}\n', 'recording/main.txt': b'actual console\n'}
        manifest = {**self.expected, 'schema': 1, 'docker_state': {'Running': False, 'Status': 'exited'},
            'files': {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in files.items()}}
        manifest.update(overrides)
        archive(path, files, 'collection-manifest.json', manifest)
        return manifest

    def test_verified_collection_is_fresh_and_never_adopts_or_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp);source = path / 'result.tar.gz';self.package(source)
            result = subject.extract_collection(source, path / 'collected', self.expected)
            self.assertEqual(result['controller_name'], 'controller1')
            proof = json.loads((path / 'collected/collection-verification.json').read_text())
            self.assertFalse(proof['state_adopted']);self.assertFalse(proof['local_reservation_released'])
            self.assertEqual((path / 'collected/recording/main.txt').read_bytes(), b'actual console\n')
            with self.assertRaisesRegex(ValueError, 'never overwrite'):
                subject.extract_collection(source, path / 'collected', self.expected)

    def test_unsorted_manifest_hashes_data_in_physical_tar_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ordered.tar.gz'
            # Neither alphabetical nor manifest order matches these TAR members.
            files = {'run/z.txt': b'z' * 4096, 'recording/main.txt': b'console\n',
                     'run/a.txt': b'a' * 4096}
            manifest = {**self.expected, 'schema': 1,
                'docker_state': {'Running': False, 'Status': 'exited'},
                'files': {name: {'sha256': digest(raw), 'bytes': len(raw)}
                          for name, raw in reversed(list(files.items()))}}
            archive(path, files, 'collection-manifest.json', manifest)
            extracted = []
            original = tarfile.TarFile.extractfile

            def observe(tar, member):
                item = tar.getmember(member) if isinstance(member, str) else member
                if item.name != 'collection-manifest.json':
                    extracted.append((item.name, item.offset_data))
                return original(tar, member)

            with patch.object(tarfile.TarFile, 'extractfile', observe):
                self.assertEqual(subject.verify_collection(path, self.expected), manifest)
            self.assertEqual([name for name, _ in extracted], list(files))
            offsets = [offset for _, offset in extracted]
            self.assertEqual(offsets, sorted(offsets), 'Data verification must not seek gzip backwards.')

    def test_traversal_absolute_and_private_member_names_refuse_before_output(self):
        for name in ('../escaped', '/absolute', 'run/../escaped', 'run/.local/kubeconfig', 'run/credentials'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();source = root / 'bad.tar.gz';self.package(source, {name: b'bad'})
                with self.assertRaises(ValueError):
                    subject.extract_collection(source, root / 'collected', self.expected)
                self.assertFalse((root / 'collected').exists())

    def test_hash_identity_or_live_state_mismatch_refuses_before_output(self):
        for override in ({'controller_name': 'another'}, {'docker_state': {'Running': True}},
                         {'files': {'run/demo.json': {'sha256': 'b' * 64, 'bytes': 18}}}):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve();source = root / 'bad.tar.gz';self.package(source, **override)
                with self.assertRaises(ValueError):
                    subject.extract_collection(source, root / 'collected', self.expected)
                self.assertFalse((root / 'collected').exists())

    def test_symlink_member_is_never_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();source = root / 'bad.tar.gz'
            link = tarfile.TarInfo('run/link');link.type = tarfile.SYMTYPE;link.linkname = '/etc/passwd'
            manifest = {**self.expected, 'docker_state': {'Running': False}, 'files': {}}
            archive(source, {}, 'collection-manifest.json', manifest, extra=link)
            with self.assertRaisesRegex(ValueError, 'non-regular'):
                subject.extract_collection(source, root / 'collected', self.expected)

    def test_duplicate_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve();source = root / 'bad.tar.gz'
            duplicate = tarfile.TarInfo('run/demo.json');duplicate.size = 0
            manifest = {**self.expected, 'docker_state': {'Running': False}, 'files': {}}
            archive(source, {'run/demo.json': b'{}'}, 'collection-manifest.json', manifest, extra=duplicate)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                subject.extract_collection(source, root / 'collected', self.expected)


if __name__ == '__main__':
    unittest.main()
