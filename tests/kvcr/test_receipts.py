"""Reject partial, mismatched or unsupported offline KVCR transfer claims."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from verify_kvcr_receipts import verify

SOURCE, TARGET = 'ft-kvcr-0-agg-source', 'ft-kvcr-0-agg-target'


class ReceiptTests(unittest.TestCase):
    def fixture(self, root, *, read_bytes=100, cached=4224, provider=True):
        def metric(blocks, write, read):
            return '\n'.join([
                f'vllm:kvcr_transfer_blocks{{operation="source_write"}} {blocks[0]}',
                f'vllm:kvcr_transfer_blocks{{operation="remote_deliver"}} {blocks[1]}',
                f'vllm:kv_offload_tiering_write_bytes{{tier="1:kvcr"}} {write}',
                f'vllm:kv_offload_tiering_read_bytes{{tier="1:kvcr"}} {read}'])
        def records(source, target):
            return {SOURCE: {'node': 'node-a', 'metrics': {'9090': source}},
                    TARGET: {'node': 'node-b', 'metrics': {'9090': target}}}
        before = records(metric((0, 0), 0, 0), metric((0, 0), 0, 0))
        after = records(metric((6, 0), 100, 0), metric((0, 6), 0, read_bytes))
        requests = [{'step': 'seed', 'expected_worker': 1, 'worker': {'decode_worker_id': 1},
                     'usage': {'prompt_tokens_details': {'cached_tokens': 0}}},
                    {'step': 'retrieve', 'expected_worker': 2, 'worker': {'decode_worker_id': 2},
                     'usage': {'prompt_tokens_details': {'cached_tokens': cached}},
                     'chunks': [{'model': 'fixture-model', 'choices': [{'delta': {'content': 'READY'}}]}]}]
        for name, obj in [('kvcr-metrics-before.json', before), ('kvcr-metrics-after.json', after),
                          ('kvcr-requests.json', requests), ('model-lock.json', {'model': 'fixture-model', 'tensor_parallel_size': 2})]:
            (root / name).write_text(json.dumps(obj))
        (root / f'kvcr-full-{SOURCE}.log').write_text('Created rails using provider=efa')
        (root / f'kvcr-full-{TARGET}.log').write_text('Created rails using provider=efa' if provider else 'provider=socket')
        return types.SimpleNamespace(path=root, result=lambda *a, **kw: None)

    def test_complete_receipts_record_scoped_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verify(self.fixture(root))
            report = json.loads((root / 'kvcr-transfer-receipts.json').read_text())
            self.assertEqual(report['bytes'], 100)
            self.assertEqual(report['cached_tokens'], 4224)
            self.assertIn('idle-canary test not included', report['scope'])
            self.assertEqual(len(report['evidence_sha256']), 6)

    def test_mismatched_transfer_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                verify(self.fixture(Path(directory), read_bytes=99))

    def test_no_engine_cache_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AssertionError):
                verify(self.fixture(Path(directory), cached=0))

    def test_missing_efa_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, 'No successful EFA'):
                verify(self.fixture(Path(directory), provider=False))


if __name__ == '__main__':
    unittest.main()
