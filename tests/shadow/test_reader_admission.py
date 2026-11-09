"""Independent admission negatives using copies of the actual v6 CPU evidence."""
from tests.support import ROOT
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import demos.shadow.composed as full

CPU = ROOT / 'results/workshop-shadow-reader-v6-cpu-live-20261105-a1'
PACKET = ROOT / 'results/workshop-shadow-reader-v6-cpu-packet-20261105-a1'
BASIS = ROOT / 'results/shadow-writer-a6-remote-collected-a1/run'
AUDIT = ROOT / 'results/shadow-writer-a6-root-closeout-a1/source-audit.json'


@unittest.skipUnless((CPU / 'result.json').exists() and (PACKET / 'fixtures.json').exists() and AUDIT.exists(),
    'Actual accepted v6 CPU/writer evidence is local qualification data')
class ActualReaderAdmissionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These admission fixtures replay archived CPU proof against its sealed
        # writer sources. They do not qualify the reorganized current code.
        with patch.object(full, 'source_path', side_effect=lambda name, root: BASIS / 'source-snapshot' / name):
            cls.archived_basis = full.qualified_basis(BASIS, AUDIT)
        cls.basis, cls.spec, _, _ = cls.archived_basis

    def test_current_source_rejects_archived_writer_after_frozen_code_changes(self):
        changed = []
        for name, expected in self.spec['source_snapshot'].items():
            current = full.source_path(name, root=ROOT)
            if not current.is_file() or full.ui.digest(current) != expected:
                changed.append(name)
        if not changed:
            self.skipTest('Current writer sources match the archived qualification exactly')
        with self.assertRaisesRegex(ValueError, 'Frozen writer implementation/source snapshot changed'):
            full.qualified_basis(BASIS, AUDIT)

    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            execution, packet = directory / 'execution', directory / 'packet'
            execution.mkdir(); packet.mkdir()
            for name in ('result.json', 'intent.json'): shutil.copyfile(CPU / name, execution / name)
            check = execution / 'check-reader-v6-source-cpu-review.json'
            shutil.copyfile(next(CPU.glob('check-reader-v6-source-cpu-*.json')), check)
            for name in ('fixtures.json', 'cpu-program.py'): shutil.copyfile(PACKET / name, packet / name)
            yield execution, packet, check

    def admit(self, execution, packet):
        return full.reader_delta_inputs(self.basis, self.spec, execution / 'result.json', packet / 'fixtures.json')

    def update(self, execution, check, mutate):
        report = json.loads((execution / 'result.json').read_text())
        mutate(report)
        (execution / 'result.json').write_text(json.dumps(report))
        canonical = json.loads(check.read_text())
        canonical.update(report)
        check.write_text(json.dumps(canonical))

    def test_actual_seven_source_eighty_role_three_case_proof_is_read_only_and_bound(self):
        before = (BASIS / 'state.json').read_bytes()
        with self.fixture() as (execution, packet, check):
            implementation, delta, files = self.admit(execution, packet)
            self.assertEqual(len(delta['actual_source_hashes']), 7)
            self.assertEqual(delta['covered_roles'], 80)
            self.assertEqual(set(files), {'reader-cpu-result.json', 'reader-cpu-packet.json', 'reader-cpu-program.py',
                'reader-cpu-intent.json', 'reader-cpu-check.json'})
            self.assertEqual(delta['actual_image_cpu'], {name: full.ui.digest(path) for name, path in files.items()})
            self.assertEqual(delta['writer_overlay_sha256'], self.spec['overlay_sha256'])
            self.assertEqual(implementation, (ROOT / 'demos/shadow/reader_descriptors.py').read_text())
        self.assertEqual((BASIS / 'state.json').read_bytes(), before)

    def test_malformed_canonical_types_are_not_equal_execution_receipts(self):
        for case in ('cuda', 'coverage', 'flags', 'count', 'swiglu'):
            with self.subTest(case=case), self.fixture() as (execution, packet, check):
                canonical = json.loads(check.read_text())
                if case == 'cuda': canonical['cuda_initialized'] = 0
                elif case == 'coverage': canonical['covered_roles'] = 80.0
                elif case == 'flags': canonical['builder_cases'][0]['deep_gemm_flags'] = [1, 1]
                elif case == 'count': canonical['builder_cases'][0]['native_warmup_count'] = False
                elif case == 'swiglu': canonical['builder_cases'][1]['swiglu'] = [0, 0, 0]
                check.write_text(json.dumps(canonical))
                with self.assertRaises(ValueError): self.admit(execution, packet)

    def test_image_identity_is_exact_not_an_arbitrary_matching_suffix(self):
        for identity in ('not-an-image-', 'other-registry/other-model@', ''):
            with self.subTest(identity=identity), self.fixture() as (execution, packet, check):
                expected_digest = self.basis.state['model_lock']['runtime_image'].split('@')[-1]
                self.update(execution, check, lambda report: report.update(image_id=identity + expected_digest))
                with self.assertRaises(ValueError): self.admit(execution, packet)

    def test_actual_native_sources_and_typed_cases_cannot_be_changed_in_both_receipts(self):
        for case in ('source', 'helper', 'coverage', 'missing-case', 'duplicate-case', 'flags', 'predicate', 'count', 'ordinary-state'):
            with self.subTest(case=case), self.fixture() as (execution, packet, check):
                def mutate(report):
                    if case == 'source': report['source_hashes']['vllm/model_executor/utils.py'] = '0' * 64
                    elif case == 'helper': report['descriptor_source_sha256'] = '0' * 64
                    elif case == 'coverage': report['covered_roles'] = 80.0
                    elif case == 'missing-case': report['builder_cases'].pop()
                    elif case == 'duplicate-case': report['builder_cases'].append(copy.deepcopy(report['builder_cases'][0]))
                    elif case == 'flags': report['builder_cases'][0]['deep_gemm_flags'] = [True, False]
                    elif case == 'predicate': report['builder_cases'][0]['native_warmup_predicate'] = 0
                    elif case == 'count': report['builder_cases'][0]['native_warmup_count'] = False
                    elif case == 'ordinary-state': report['builder_cases'][0]['native_ordinary_none_matches'] = 1
                self.update(execution, check, mutate)
                with self.assertRaises(ValueError): self.admit(execution, packet)

    def test_packet_source_schema_and_program_drift_or_extra_pass_check_is_refused(self):
        for case in ('packet', 'program', 'intent', 'duplicate-check', 'failed-check'):
            with self.subTest(case=case), self.fixture() as (execution, packet, check):
                if case == 'packet':
                    value = json.loads((packet / 'fixtures.json').read_text())
                    value['source_contracts'].pop('vllm/model_executor/utils.py')
                    (packet / 'fixtures.json').write_text(json.dumps(value))
                elif case == 'program': (packet / 'cpu-program.py').write_text('print("unreviewed")')
                elif case == 'intent':
                    value = json.loads((execution / 'intent.json').read_text()); value['sources']['DESCRIPTOR'] = '0' * 64
                    (execution / 'intent.json').write_text(json.dumps(value))
                elif case == 'duplicate-check': shutil.copyfile(check, execution / 'check-reader-v6-source-cpu-second.json')
                elif case == 'failed-check':
                    value = json.loads(check.read_text()); value['status'] = 'failed'; check.write_text(json.dumps(value))
                with self.assertRaises(ValueError): self.admit(execution, packet)

    def test_failed_cpu_admission_precedes_any_candidate_creation(self):
        with self.fixture() as (execution, packet, check):
            self.update(execution, check, lambda report: report.update(cuda_initialized=True))
            candidate = execution.parent / 'uncreated-full-candidate'
            # Reuse the archive fixture already validated above so this negative
            # reaches CPU admission rather than stopping at current-source drift.
            with patch.object(full, 'qualified_basis', return_value=self.archived_basis), \
                    patch.object(full, 'Run', side_effect=AssertionError('No Run before CPU admission')), self.assertRaises(ValueError):
                full.freeze(candidate, BASIS, AUDIT, execution / 'result.json', packet / 'fixtures.json')
            self.assertFalse(candidate.exists())


if __name__ == '__main__': unittest.main()
