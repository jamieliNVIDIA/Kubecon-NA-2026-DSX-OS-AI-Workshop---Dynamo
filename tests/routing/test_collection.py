"""Collection must reject tampering and archive traversal before trusting evidence."""
from tests.support import ROOT
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = ROOT / 'reports/overnight-2026-11-04/routing-sweep/collect.py'
SPEC = importlib.util.spec_from_file_location('overnight_routing_collection', SOURCE)
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)


def payload(name='results/run/campaign.json', corrupt=False):
    raw = b'{"measured": false}\n'
    manifest = {'files': {name: {'bytes': len(raw), 'sha256': '0' * 64 if corrupt else hashlib.sha256(raw).hexdigest()}},
                'completed_cells': [], 'controller_status': {'stage': 'qualify-cpu'}}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for key, value in ((name, raw), ('collection-manifest.json', json.dumps(manifest).encode())):
            member = tarfile.TarInfo(key)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    return output.getvalue()


class CollectionTests(unittest.TestCase):
    def execute(self, root, data):
        def run(argv, stdout, stderr, timeout):
            self.assertEqual(argv[0], 'ssh')
            stdout.write(data)
            return subprocess.CompletedProcess(argv, 0, stderr=b'')
        with patch.object(collect, 'ROOT', Path(root)), patch.object(collect.subprocess, 'run', run), \
             patch('sys.argv', ['collect.py', '--label', 'fixture']):
            collect.main()

    def test_valid_partial_collection_is_not_a_completed_cell(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'results').mkdir()
            self.execute(root, payload())
            receipt = json.loads((Path(root) / 'results/workshop-routing-overnight-collection-fixture/verification.json').read_text())
            self.assertTrue(receipt['verified'])
            self.assertEqual(receipt['completed_cells'], [])

    def test_tampered_evidence_has_no_verification_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'results').mkdir()
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                self.execute(root, payload(corrupt=True))
            self.assertFalse(list(Path(root).rglob('verification.json')))

    def test_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'results').mkdir()
            with self.assertRaises(ValueError):
                self.execute(root, payload('../../escaped.json'))
            self.assertFalse((Path(root) / 'escaped.json').exists())
            self.assertFalse(list(Path(root).rglob('verification.json')))


if __name__ == '__main__':
    unittest.main()
