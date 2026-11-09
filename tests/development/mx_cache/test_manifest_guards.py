"""Independent binding of Xet storage keys to pinned HF data identities."""
from tests.support import ROOT
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

import scripts.development.mx_cache.seed as seed
import tests.development.mx_cache.test_content_identity as author

RENDER = ROOT / 'results/mx-dev-persistent-server-20261105-a4-reviewed'


class SeedV3ReviewTests(unittest.TestCase):
    def test_declared_xet_key_is_storage_identity_and_wrong_lfs_data_hash_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            spec, hf, snapshot, rows, payloads = author.fixture(directory)
            row = next(row for row in rows if row['path'] == 'model.safetensors')
            self.assertNotEqual(row['xetHash'], row['lfs']['oid'])
            self.assertEqual((snapshot / row['path']).resolve().name, row['xetHash'])
            row['lfs']['oid'] = 'f' * 64
            spec['hf_manifest_json'] = json.dumps(rows)
            spec['hf_manifest_sha256'] = hashlib.sha256(spec['hf_manifest_json'].encode()).hexdigest()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'LFS data checksum'):
                seed.seed(spec, hf, directory / 'cache', resource_gate=lambda *_: {})
            self.assertFalse((directory / 'cache/models--example--model').exists())
            self.assertFalse((directory / 'cache/mx-dev-cache-seed.json').exists())
            self.assertEqual((snapshot / row['path']).read_bytes(), payloads[row['path']])

    def test_pinned_tree_path_duplicate_and_lfs_size_or_key_corruption_reject(self):
        for case in ('duplicate', 'escape', 'lfs-size', 'xet-key', 'missing-weight-lfs'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                spec, hf, snapshot, rows, payloads = author.fixture(directory)
                row = next(row for row in rows if row['path'] == 'model.safetensors')
                if case == 'duplicate': rows.append(dict(rows[0]));spec['hf_manifest_entries'] += 1
                elif case == 'escape': row['path'] = '../model.safetensors'
                elif case == 'lfs-size': row['lfs']['size'] += 1
                elif case == 'xet-key': row['xetHash'] = 'not-a-key'
                elif case == 'missing-weight-lfs': del row['lfs']
                spec['hf_manifest_json'] = json.dumps(rows)
                spec['hf_manifest_sha256'] = hashlib.sha256(spec['hf_manifest_json'].encode()).hexdigest()
                with self.assertRaises(ValueError): seed.seed(spec, hf, directory / 'cache', resource_gate=lambda *_: {})
                self.assertFalse((directory / 'cache/models--example--model').exists())

    @unittest.skipUnless((RENDER / 'plan.json').exists(), 'Final reviewed a4 render is local evidence')
    def test_actual_final_render_binds_exact_114_file_tree_and_immutable_seed_without_gpu(self):
        plan = json.loads((RENDER / 'plan.json').read_text())
        for name, digest in plan['files_sha256'].items(): self.assertEqual(hashlib.sha256((RENDER / name).read_bytes()).hexdigest(), digest)
        objects = yaml.safe_load((RENDER / 'server.yaml').read_text())['items']
        cm = next(obj for obj in objects if obj['kind'] == 'ConfigMap')
        self.assertIs(cm['immutable'], True)
        self.assertEqual(cm['data']['seed.py'], (ROOT / 'scripts/development/mx_cache/seed.py').read_text())
        spec = json.loads(cm['data']['seed-spec.json'])
        raw = (ROOT / 'results/mx-dev-source-hf-tree-20261105-a1/tree.json').read_bytes()
        receipt = json.loads((ROOT / 'results/mx-dev-source-hf-tree-20261105-a1/receipt.json').read_text())
        self.assertEqual(spec['hf_manifest_json'].encode(), raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), spec['hf_manifest_sha256'])
        self.assertEqual(spec['hf_manifest_sha256'], receipt['sha256'])
        self.assertEqual(spec['hf_manifest_url'], receipt['url'])
        self.assertEqual(receipt['http_status'], 200)
        tree = seed.hf_manifest(spec)
        self.assertEqual(len(tree), 114)
        weights = {name: row for name, row in tree.items() if name.endswith('.safetensors')}
        self.assertEqual(len(weights), 88)
        self.assertEqual(sum(row['size'] for row in weights.values()), 75010188240)
        self.assertTrue(all('lfs' in row and len(row['lfs']['oid']) == 64 for row in weights.values()))
        self.assertEqual(spec['model_metadata_sha256'], json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())['model_metadata_sha256'])
        pod = next(obj for obj in objects if obj['kind'] == 'Deployment')['spec']['template']['spec']
        self.assertFalse(pod.get('resourceClaims'))
        for container in pod['containers'] + pod['initContainers']:
            self.assertFalse(any('gpu' in key.lower() for section in container['resources'].values() for key in section))
            self.assertEqual({value['name']: value['value'] for value in container['env']}['NVIDIA_VISIBLE_DEVICES'], 'void')
        self.assertEqual(pod['initContainers'][0]['args'][-2:], ['--timeout-seconds', '2400'])
        self.assertTrue(next(m for m in pod['initContainers'][0]['volumeMounts'] if m['name'] == 'source')['readOnly'])
        self.assertEqual({m['name'] for m in pod['containers'][0]['volumeMounts']}, {'cache'})

    def test_first_timeout_receipt_keeps_original_spec_and_never_replays_on_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            spec, hf, snapshot, rows, payloads = author.fixture(directory)
            spec_path = directory / 'spec.json'; spec_path.write_text(json.dumps(spec))
            original_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
            cache = directory / 'cache'
            argv = ['seed', '--spec', str(spec_path), '--source-hf-home', str(hf), '--cache', str(cache)]
            with patch.object(sys, 'argv', argv), patch.object(seed.signal, 'alarm'), patch.object(seed, 'seed', side_effect=TimeoutError('first bounded timeout')), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(TimeoutError): seed.main()
            first = (cache / 'mx-dev-cache-failure.json').read_bytes()
            record = json.loads(first)
            self.assertEqual(record['exception_type'], 'TimeoutError')
            self.assertEqual(record['spec_sha256'], original_sha)
            spec_path.write_text('{}')
            with patch.object(sys, 'argv', argv), patch.object(seed.signal, 'alarm'), patch.object(seed, 'seed') as replay, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError): seed.main()
                replay.assert_not_called()
            self.assertEqual((cache / 'mx-dev-cache-failure.json').read_bytes(), first)


if __name__ == '__main__': unittest.main()
