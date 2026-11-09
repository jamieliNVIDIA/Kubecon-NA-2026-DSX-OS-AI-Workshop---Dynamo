from tests.support import ROOT
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE_SPEC = importlib.util.spec_from_file_location('seedv3', ROOT / 'scripts/development/mx_cache/seed.py')
seed = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(seed)


def fixture(root):
    model, revision = 'example/model', 'a' * 40
    hf = root / 'hf'
    repo = hf / 'hub/models--example--model'
    snapshot = repo / 'snapshots' / revision
    snapshot.mkdir(parents=True)
    payloads = {'config.json': b'{"test":true}', 'README.md': b'native Git metadata',
                'model.safetensors': b'trusted weight bytes', 'accuracy_plot.png': b'trusted LFS asset',
                'model.safetensors.index.json': b'{"weight_map":{"layer":"model.safetensors"}}'}
    rows = []
    for name, data in payloads.items():
        git = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        row = {'type': 'file', 'oid': git, 'size': len(data), 'path': name}
        if name in ('model.safetensors', 'accuracy_plot.png'):
            sha = hashlib.sha256(data).hexdigest()
            xet = hashlib.sha256(b'xet-storage-key:' + data).hexdigest()
            row.update(lfs={'oid': sha, 'size': len(data)}, xetHash=xet)
            blob = hf / 'hub/blobs' / xet[:2] / xet
        else:
            blob = repo / 'blobs' / git
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        (snapshot / name).symlink_to(blob)
        rows.append(row)
    raw = json.dumps(rows)
    spec = {'schema': 1, 'id': 'seed-fixture', 'model': model, 'revision': revision,
            'cache_limit_bytes': 96 * 1024**3, 'weight_files': 1,
            'weight_bytes': len(payloads['model.safetensors']),
            'model_metadata_sha256': {'config.json': hashlib.sha256(payloads['config.json']).hexdigest()},
            'hf_manifest_json': raw, 'hf_manifest_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'hf_manifest_entries': len(rows),
            'hf_manifest_url': 'https://huggingface.co/api/models/' + model + '/tree/' + revision + '?recursive=true&expand=false&limit=1000'}
    return spec, hf, snapshot, rows, payloads


class SeedV3Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.spec, self.hf, self.snapshot, self.rows, self.payloads = fixture(self.root)

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return seed.seed(self.spec, self.hf, self.root / 'cache', resource_gate=lambda *_: {})

    def test_xet_key_differs_from_content_but_full_lfs_and_git_identities_pass(self):
        receipt = self.execute()
        self.assertEqual(receipt['file_count'], 5)
        self.assertEqual(receipt['hf_manifest_sha256'], self.spec['hf_manifest_sha256'])
        for name in ('model.safetensors', 'accuracy_plot.png'):
            row = receipt['files'][name]
            self.assertNotEqual(row['source_blob_id'], row['sha256'])
            self.assertEqual(row['sha256'], row['hf_data_hash'])
            self.assertEqual(row['hf_data_hash_kind'], 'sha256-lfs')
            self.assertEqual(row['source_blob_id'], row['hf_xet_storage_key'])
        self.assertEqual(receipt['files']['README.md']['hf_data_hash_kind'], 'sha1-git-blob')
        destination = self.root / 'cache/models--example--model'
        for name, data in self.payloads.items():
            target = destination / 'snapshots' / self.spec['revision'] / name
            self.assertEqual(target.read_bytes(), data)
            self.assertTrue(target.resolve().is_relative_to(destination.resolve()))

    def test_same_size_lfs_or_git_corruption_never_publishes(self):
        for name in ('model.safetensors', 'README.md'):
            with self.subTest(name=name):
                target = self.snapshot / name
                original = target.read_bytes()
                target.write_bytes(b'X' * len(original))
                with self.assertRaisesRegex(ValueError, 'checksum differs'): self.execute()
                self.assertFalse((self.root / 'cache/models--example--model').exists())
                target.write_bytes(original)
                import shutil
                shutil.rmtree(self.root / 'cache')

    def test_unpinned_storage_key_rejected_even_when_data_correct(self):
        target = self.snapshot / 'accuracy_plot.png'
        payload = target.read_bytes()
        key = 'd' * 64
        wrong = self.hf / 'hub/blobs' / key[:2] / key
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(payload)
        target.unlink()
        target.symlink_to(wrong)
        with self.assertRaisesRegex(ValueError, 'not declared'): self.execute()
        self.assertFalse((self.root / 'cache').exists())

    def test_manifest_hash_revision_file_set_and_size_checked_before_copy(self):
        original = dict(self.spec)
        for field, value in (('hf_manifest_sha256', 'f' * 64), ('hf_manifest_url', 'https://wrong')):
            self.spec[field] = value
            with self.assertRaises(ValueError): self.execute()
            self.spec = dict(original)
        extra = self.snapshot / 'unexpected'
        extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'file set differs'): self.execute()
        extra.unlink()
        (self.snapshot / 'README.md').write_bytes(b'wrong size')
        with self.assertRaisesRegex(ValueError, 'size differs'): self.execute()
        self.assertFalse((self.root / 'cache').exists())

    def test_first_fatal_saved_and_reprinted_without_replaying_or_overwriting(self):
        spec_path = self.root / 'spec.json'
        spec_path.write_text(json.dumps(self.spec))
        cache = self.root / 'cache'
        argv = ['seed.py', '--spec', str(spec_path), '--source-hf-home', str(self.hf), '--cache', str(cache)]
        with patch.object(sys, 'argv', argv), patch.object(seed.signal, 'alarm'), patch.object(seed, 'seed', side_effect=ValueError('original fatal')), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError): seed.main()
        first = (cache / 'mx-dev-cache-failure.json').read_bytes()
        with patch.object(sys, 'argv', argv), patch.object(seed.signal, 'alarm'), patch.object(seed, 'seed') as replay, contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(RuntimeError): seed.main()
            replay.assert_not_called()
            self.assertIn('original fatal', output.getvalue())
        self.assertEqual((cache / 'mx-dev-cache-failure.json').read_bytes(), first)


if __name__ == '__main__':
    unittest.main()
