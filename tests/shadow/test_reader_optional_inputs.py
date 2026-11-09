"""Writer invariance and immutable actual-source inputs for the v6 reader repair."""
from tests.support import ROOT
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import demos.shadow.writer_descriptors as writer
import demos.shadow.reader_descriptors as reader
import demos.shadow.reader_cpu as cpu
from demos.shadow.reader_delta import validate_reader_delta
import tests.shadow.test_writer_role_contracts as fixtures

BASIS = ROOT / 'results/shadow-writer-a6-remote-collected-a1/run'


class ReaderV6InputTests(unittest.TestCase):
    def test_writer_export_is_identical_and_all_nonreader_functions_are_unchanged(self):
        fixture = fixtures.IndependentRoleReviewTests(); fixture.setUp()
        model, modules, manager, identity = fixture.complete_writer()
        self.assertEqual(writer.export_runtime_manifest(model, manager, identity),
                         reader.export_runtime_manifest(model, manager, identity))
        original = (ROOT / 'demos/shadow/writer_descriptors.py').read_text()
        candidate = (ROOT / 'demos/shadow/reader_descriptors.py').read_text()
        proof = validate_reader_delta(original, candidate)
        self.assertEqual(writer.VERSION, reader.VERSION)
        self.assertTrue(proof['writer_export_and_schema_unchanged'])
        self.assertEqual(len(proof['unchanged_functions']), 29)
        self.assertEqual(proof['new_reader_functions'], ['restore_humming_optional_input_state'])
        for before, after in (("if require_object_alias and gate_tensor is not tensor:", 'if False:'),
                ("schema.quant_method != 'humming'", 'False'),
                ("schema.input_scale_group_size != 0", 'False'),
                ('gemm1_beta=getattr(layer, \'swiglu_beta\', None)', 'gemm1_beta=None')):
            self.assertIn(before, candidate)
            with self.assertRaisesRegex(ValueError, 'unreviewed writer/schema/reader changes'):
                validate_reader_delta(original, candidate.replace(before, after, 1))

    @unittest.skipUnless(BASIS.is_dir(), 'Accepted immutable writer collection is local qualification evidence')
    def test_packet_binds_eighty_actual_roles_and_all_seven_native_sources(self):
        packet = cpu.build_packet(BASIS)
        self.assertEqual(packet['covered_roles'], 80)
        self.assertEqual(len(packet['runtime_groups']), 1)
        self.assertEqual(len(packet['source_contracts']), 7)
        self.assertEqual(len(packet['extra_source_receipts']), 3)
        group = packet['runtime_groups'][0]
        self.assertEqual(len(group['covered_roles']), 80)
        self.assertEqual(len(group['fixture']['parameters']), 7)
        self.assertTrue(all(group['fixture']['input_schemas']['mapping'][prefix]['fields']['quant_method'] == 'humming'
                            for prefix in ('w13', 'w2')))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'packet'
            with redirect_stdout(io.StringIO()): cpu.prepare_packet(BASIS, output)
            files = json.loads((output / 'packet-manifest.json').read_text())
            self.assertEqual(set(files), {'fixtures.json', 'reader-delta.json', 'workshop_descriptors.py', 'cpu-program.py'})
            for name, entry in files.items():
                self.assertEqual(entry['sha256'], hashlib.sha256((output / name).read_bytes()).hexdigest())
                self.assertEqual(entry['bytes'], (output / name).stat().st_size)
            self.assertEqual(json.loads((output / 'fixtures.json').read_text()), packet)
            self.assertEqual((output / 'cpu-program.py').read_text(), cpu.PROGRAM)

    @unittest.skipUnless(BASIS.is_dir(), 'Accepted immutable writer collection is local qualification evidence')
    def test_extra_native_source_receipt_hash_and_image_mismatches_are_rejected(self):
        name = 'vllm/model_executor/utils.py'
        directory, expected = cpu.EXTRA_SOURCES[name]
        original = json.loads((directory / 'result.json').read_text())
        for case in ('receipt-hash', 'source-bytes', 'wrong-image', 'missing-source'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary)
                target = evidence / 'sources' / name
                target.parent.mkdir(parents=True)
                target.write_bytes((directory / 'sources' / name).read_bytes())
                receipt = json.loads(json.dumps(original))
                if case == 'receipt-hash': receipt['source_sha256'][name] = '0' * 64
                elif case == 'source-bytes': target.write_text(target.read_text() + '\n# source changed\n')
                elif case == 'wrong-image': receipt['image_id'] = 'example/other@sha256:' + '0' * 64
                elif case == 'missing-source': receipt['missing'] = [name]
                (evidence / 'result.json').write_text(json.dumps(receipt))
                sources = dict(cpu.EXTRA_SOURCES); sources[name] = (evidence, expected)
                with patch.dict(cpu.EXTRA_SOURCES, sources, clear=True), self.assertRaisesRegex(ValueError, 'exact image'):
                    cpu.build_packet(BASIS)


if __name__ == '__main__': unittest.main()
