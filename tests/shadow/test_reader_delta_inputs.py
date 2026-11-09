"""Full freeze binds accepted writer bytes and exact actual-image reader CPU proof."""
from tests.support import ROOT
from contextlib import contextmanager
import hashlib
import json
import unittest
from unittest.mock import patch

import demos.shadow.composed as full
import tests.shadow.test_composed as composed_tests


class ReaderDeltaInputTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        implementation = (ROOT / 'demos/shadow/reader_descriptors.py').read_bytes()
        with composed_tests.FullShadowTests().collected_fixture() as fixture:
            target = fixture.root / 'demos/shadow/reader_descriptors.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(implementation)
            basis, spec, _, _ = full.qualified_basis(fixture.source, fixture.audit)
            packet_dir, cpu_dir = fixture.root / 'reader-packet', fixture.root / 'cpu-execution'
            packet_dir.mkdir(); cpu_dir.mkdir()
            packet = {'source_contracts': {'fixture-source': 'fixed'}, 'marker': {'shape': [512]},
                'runtime_groups': [{'runtime_signature_sha256': 'a' * 64, 'covered_roles': list(range(80))}]}
            packet_path, report_path = packet_dir / 'fixtures.json', cpu_dir / 'result.json'
            fixture.save(packet_path, packet)
            (packet_dir / 'cpu-program.py').write_text(full.READER_CPU_PROGRAM)
            fixture.save(cpu_dir / 'intent.json', {
                'program_sha256': hashlib.sha256(full.READER_CPU_PROGRAM.encode()).hexdigest(),
                'sources': {'DESCRIPTOR': hashlib.sha256(implementation).hexdigest(), 'MOE_PACKET': full.ui.digest(packet_path)}})
            report = {'cuda_initialized': False, 'descriptor_source_sha256': hashlib.sha256(implementation).hexdigest(),
                'reader_adapter_revision': full.READER_ADAPTER_REVISION, 'descriptor_version': full.VERSION,
                'fixture_packet_sha256': full.ui.digest(packet_path), 'source_hashes': packet['source_contracts'],
                'runtime_groups': 1, 'covered_roles': 80, 'image_id': fixture.state['model_lock']['runtime_image'],
                'native_functions_executed': ['vllm.model_executor.utils.replace_parameter',
                    'ModelOptNvFp4FusedMoE.get_fused_moe_quant_config', 'make_nvfp4_moe_quant_config',
                    'get_humming_moe_quant_config', '_deep_gemm_linear_data',
                    '_fused_moe_grouped_gemm_may_use_deep_gemm', '_count_warmup_iterations'],
                'metadata_test_doubles': ['DeepGEMM env flags forced true', 'ineligible linear-provider/expert classes',
                    'unreachable hardware helpers raise AssertionError', 'empty DeepGEMM warmup caches'],
                'builder_cases': [{'runtime_signature_sha256': 'a' * 64, 'swiglu': values, 'covered_roles': 80,
                    'native_ordinary_none_matches': True, 'real_HummingMoEQuantConfig': True,
                    'generic_ModelOpt_callback': True, 'exact_parameter_and_gate_aliases': True,
                    'parameters_unchanged': True, 'deep_gemm_flags': [True, True],
                    'native_warmup_predicate': False, 'native_warmup_count': 0,
                    'counterfactual_error': "'RoutedExperts' object has no attribute 'w13_input_scale'"}
                    for values in (None, [0.0, 0.0, 0.0], [0.25, 1.5, 7.0])]}
            fixture.save(report_path, report)
            check = cpu_dir / 'check-reader-v6-source-cpu-unit.json'
            fixture.save(check, dict(status='passed', updated_at='2026-11-06T00:17:46+00:00', **report))
            fixture.basis, fixture.source_spec = basis, spec
            fixture.packet, fixture.packet_path = packet, packet_path
            fixture.report, fixture.report_path, fixture.check = report, report_path, check
            with patch.object(full, 'build_reader_packet', return_value=packet):
                yield fixture

    def test_exact_cpu_result_accepts_only_the_reviewed_reader_delta(self):
        with self.fixture() as fixture:
            original = (fixture.original / 'state.json').read_bytes()
            implementation, delta, inputs = full.reader_delta_inputs(fixture.basis, fixture.source_spec,
                fixture.report_path, fixture.packet_path)
            self.assertEqual(hashlib.sha256(implementation.encode()).hexdigest(), delta['reader_helper_sha256'])
            self.assertTrue(delta['writer_export_and_schema_unchanged'])
            self.assertEqual(delta['descriptor_version'], full.VERSION)
            self.assertEqual(set(inputs), {'reader-cpu-result.json', 'reader-cpu-packet.json',
                'reader-cpu-program.py', 'reader-cpu-intent.json', 'reader-cpu-check.json'})
            self.assertEqual((fixture.original / 'state.json').read_bytes(), original)

    def test_cuda_wrong_image_helper_packet_source_or_coverage_never_pass(self):
        for field, value in [('cuda_initialized', True), ('image_id', 'foreign-image'),
                ('descriptor_source_sha256', 'foreign-helper'), ('fixture_packet_sha256', 'foreign-packet'),
                ('source_hashes', {}), ('covered_roles', 79), ('covered_roles', 80.0), ('runtime_groups', True)]:
            with self.subTest(field=field, value=value), self.fixture() as fixture:
                fixture.report[field] = value
                fixture.save(fixture.report_path, fixture.report)
                fixture.save(fixture.check, dict(status='passed', updated_at='2026-11-06T00:17:46+00:00', **fixture.report))
                with self.assertRaises(ValueError):
                    full.reader_delta_inputs(fixture.basis, fixture.source_spec, fixture.report_path, fixture.packet_path)

    def test_changed_packet_program_or_actual_intent_is_refused(self):
        for change in ('packet', 'program', 'intent', 'check'):
            with self.subTest(change=change), self.fixture() as fixture:
                if change == 'packet':
                    altered = dict(fixture.packet, marker={'shape': [512.0]})
                    fixture.save(fixture.packet_path, altered)
                elif change == 'program':
                    (fixture.packet_path.parent / 'cpu-program.py').write_text('changed program')
                elif change == 'intent':
                    path = fixture.report_path.parent / 'intent.json'
                    value = json.loads(path.read_text()); value['program_sha256'] = 'changed'
                    fixture.save(path, value)
                else:
                    fixture.save(fixture.check, dict(status='failed', updated_at='2026-11-06T00:17:46+00:00', **fixture.report))
                with self.assertRaises(ValueError):
                    full.reader_delta_inputs(fixture.basis, fixture.source_spec, fixture.report_path, fixture.packet_path)

    def test_missing_mutating_or_duplicate_builder_case_is_refused(self):
        for change in ('missing', 'parameter-mutated', 'alias-changed', 'ordinary-state-missing', 'duplicate'):
            with self.subTest(change=change), self.fixture() as fixture:
                cases = fixture.report['builder_cases']
                if change == 'missing': cases.pop()
                elif change == 'parameter-mutated': cases[0]['parameters_unchanged'] = False
                elif change == 'alias-changed': cases[0]['exact_parameter_and_gate_aliases'] = False
                elif change == 'ordinary-state-missing': cases[0]['native_ordinary_none_matches'] = False
                else: cases.append(dict(cases[0]))
                fixture.save(fixture.report_path, fixture.report)
                fixture.save(fixture.check, dict(status='passed', updated_at='2026-11-06T00:17:46+00:00', **fixture.report))
                with self.assertRaises(ValueError):
                    full.reader_delta_inputs(fixture.basis, fixture.source_spec, fixture.report_path, fixture.packet_path)

    def test_disabled_skipped_or_unreproduced_native_warmup_is_refused(self):
        changes = [('deep_gemm_flags', [False, True]), ('deep_gemm_flags', [1, True]),
            ('native_warmup_predicate', True), ('native_warmup_count', 1), ('native_warmup_count', False),
            ('native_warmup_count', 0.0), ('counterfactual_error', ''), ('generic_ModelOpt_callback', False)]
        for field, value in changes:
            with self.subTest(field=field, value=value), self.fixture() as fixture:
                fixture.report['builder_cases'][0][field] = value
                fixture.save(fixture.report_path, fixture.report)
                fixture.save(fixture.check, dict(status='passed', updated_at='2026-11-06T00:17:46+00:00', **fixture.report))
                with self.assertRaises(ValueError):
                    full.reader_delta_inputs(fixture.basis, fixture.source_spec, fixture.report_path, fixture.packet_path)

    def test_native_function_doubles_and_exact_swiglu_cases_are_bound(self):
        for case in ('function', 'doubles', 'absent-vs-explicit-null', 'zero-bool', 'zero-int'):
            with self.subTest(case=case), self.fixture() as fixture:
                if case == 'function': fixture.report['native_functions_executed'].pop()
                elif case == 'doubles': fixture.report['metadata_test_doubles'].clear()
                elif case == 'absent-vs-explicit-null': fixture.report['builder_cases'][0]['swiglu'] = [None, None, None]
                elif case == 'zero-bool': fixture.report['builder_cases'][1]['swiglu'] = [False, 0.0, 0.0]
                elif case == 'zero-int': fixture.report['builder_cases'][1]['swiglu'] = [0, 0, 0]
                fixture.save(fixture.report_path, fixture.report)
                fixture.save(fixture.check, dict(status='passed', updated_at='2026-11-06T00:17:46+00:00', **fixture.report))
                with self.assertRaises(ValueError):
                    full.reader_delta_inputs(fixture.basis, fixture.source_spec, fixture.report_path, fixture.packet_path)

    def test_missing_reader_cpu_gate_creates_no_full_candidate(self):
        with self.fixture() as fixture:
            candidate = fixture.root / 'results/full-not-created'
            with patch.object(full, 'Run', side_effect=AssertionError('Run may not precede CPU admission')):
                with self.assertRaisesRegex(ValueError, 'passed actual-image reader CPU'):
                    full.freeze(candidate, fixture.source, fixture.audit)
            self.assertFalse(candidate.exists())


if __name__ == '__main__': unittest.main()
