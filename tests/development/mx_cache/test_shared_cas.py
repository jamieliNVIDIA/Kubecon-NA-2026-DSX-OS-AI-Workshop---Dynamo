"""Pinned shared CAS layouts retain their content and publication checks."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import scripts.development.mx_cache.seed as seed
import tests.development.mx_cache.test_seed as author


class SharedCasReviewTests(unittest.TestCase):
    def test_all_shared_cas_files_are_hashed_and_relinked_inside_published_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            spec, hf, snapshot, payloads = author.fixture_snapshot(directory)
            rows = json.loads(spec['hf_manifest_json'])
            for name, content in payloads.items():
                digest = hashlib.sha256(content).hexdigest()
                blob = hf / 'hub/blobs' / digest[:2] / digest
                blob.parent.mkdir(parents=True, exist_ok=True);blob.write_bytes(content)
                target = snapshot / name;target.unlink();target.symlink_to(blob)
                next(row for row in rows if row['path'] == name)['xetHash'] = digest
            spec.update(hf_manifest_json=json.dumps(rows),
                        hf_manifest_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
            with contextlib.redirect_stdout(io.StringIO()): receipt = seed.seed(spec, hf, directory / 'cache', resource_gate=lambda *_: {})
            self.assertEqual(set(receipt['files']), set(payloads))
            for name, content in payloads.items():
                self.assertEqual(receipt['files'][name]['source_blob_id'], hashlib.sha256(content).hexdigest())
                target = directory / 'cache/models--example--model/snapshots' / spec['revision'] / name
                self.assertEqual(target.read_bytes(), content)
                self.assertTrue(target.resolve().is_relative_to((directory / 'cache/models--example--model').resolve()))

    def test_only_exact_shared_root_two_level_digest_prefix_layout_is_allowed(self):
        for case in ('wrong-prefix', 'extra-depth', 'nonhex', 'wrong-root', 'shared-root-symlink'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                spec, hf, snapshot, payloads = author.fixture_snapshot(directory)
                content = payloads['assets/vocab.json'];digest = hashlib.sha256(content).hexdigest()
                shared = hf / 'hub/blobs'
                if case == 'wrong-prefix': blob = shared / ('00' if digest[:2] != '00' else '11') / digest
                elif case == 'extra-depth': blob = shared / digest[:2] / 'extra' / digest
                elif case == 'nonhex': blob = shared / 'ab' / ('x' * 64)
                elif case == 'wrong-root': blob = hf / 'hub/arbitrary' / digest[:2] / digest
                else:
                    outside = directory / 'outside';outside.mkdir()
                    shared.symlink_to(outside, target_is_directory=True)
                    blob = shared / digest[:2] / digest
                blob.parent.mkdir(parents=True, exist_ok=True);blob.write_bytes(content)
                target = snapshot / 'assets/vocab.json';target.unlink();target.symlink_to(blob)
                with self.assertRaises(ValueError): seed.seed(spec, hf, directory / 'cache', resource_gate=lambda *_: {})
                self.assertFalse((directory / 'cache').exists())

    def test_correct_shared_layout_still_rejects_wrong_bytes_without_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            spec, hf, snapshot, payloads = author.fixture_snapshot(directory)
            name = 'model-00001-of-00001.safetensors'
            content = payloads[name];digest = hashlib.sha256(content).hexdigest()
            blob = hf / 'hub/blobs' / digest[:2] / digest
            blob.parent.mkdir(parents=True);blob.write_bytes(b'X' * len(content))
            target = snapshot / name;target.unlink();target.symlink_to(blob)
            with self.assertRaisesRegex(ValueError, 'LFS data checksum'), contextlib.redirect_stdout(io.StringIO()):
                seed.seed(spec, hf, directory / 'cache', resource_gate=lambda *_: {})
            self.assertFalse((directory / 'cache/models--example--model').exists())
            self.assertFalse((directory / 'cache/mx-dev-cache-seed.json').exists())


if __name__ == '__main__': unittest.main()
