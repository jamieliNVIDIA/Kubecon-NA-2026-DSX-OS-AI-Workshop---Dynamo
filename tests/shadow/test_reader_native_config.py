"""Reader-only Humming callback regression; accepted writer schema is unchanged."""
from tests.support import ROOT
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.writer_descriptors as writer
import demos.shadow.compat.descriptor_native_config as reader
from demos.shadow.compat.native_config_delta import validate_reader_delta, READER_REVISION
import tests.shadow.test_writer_role_contracts as v4_review


class ReaderOnlyTests(unittest.TestCase):
    def setUp(self):
        self.review = v4_review.IndependentRoleReviewTests()
        self.review.setUp()

    def test_exact_reader_delta_preserves_format_and_every_nonreader_function(self):
        original = (ROOT / 'demos/shadow/writer_descriptors.py').read_text()
        candidate = (ROOT / 'demos/shadow/compat/descriptor_native_config.py').read_text()
        proof = validate_reader_delta(original, candidate)
        self.assertEqual(writer.VERSION, reader.VERSION)
        self.assertEqual(reader.READER_ADAPTER_REVISION, READER_REVISION)
        self.assertTrue(proof['writer_export_and_schema_unchanged'])
        for name in ('export_runtime_manifest', 'prepare_writer_manifest', 'publish_writer_manifest',
                'tensor_layout', 'parameter_layout', 'validate_tensor_contracts', 'prepare_reader_skeleton'):
            self.assertIn(name, proof['unchanged_functions'])
        for changed in (candidate.replace("'requires_grad': False", "'requires_grad': True", 1),
                candidate.replace("VERSION = 'workshop-super-vl-humming-runtime-v4-routing-bias'", "VERSION = 'new'", 1)):
            with self.assertRaisesRegex(ValueError, 'unreviewed writer/schema/code changes'):
                validate_reader_delta(original, changed)

    def test_writer_export_data_is_identical_with_reader_only_helper(self):
        model, modules, manager, identity = self.review.complete_writer()
        before = writer.export_runtime_manifest(model, manager, identity)
        after = reader.export_runtime_manifest(model, manager, identity)
        self.assertEqual(after, before)

    def test_reader_calls_humming_builder_with_oracle_fields_never_generic_checkpoint_wrapper(self):
        model, modules, manager, manifest, fake, hook = self.review.runtime()
        calls = []
        getters = {}
        for name, layer in modules.items():
            if reader._kind(layer) != 'humming-moe': continue
            getters[id(layer)] = layer.quant_method.get_fused_moe_quant_config
            layer.swiglu_alpha, layer.swiglu_beta, layer.swiglu_limit = 0.25, 1.5, 7.0
            layer.quant_method.get_fused_moe_quant_config = lambda _: self.fail('Generic checkpoint wrapper ran')
            self.assertFalse(hasattr(layer, 'w13_input_scale'))
            self.assertFalse(hasattr(layer, 'w2_input_scale'))
        def builder(layer, **values):
            calls.append(values)
            return getters[id(layer)](layer)
        humming = self.review.legacy.imports['vllm.model_executor.layers.quantization.utils.humming.moe']
        humming.get_humming_moe_quant_config = builder
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(reader.importlib, 'import_module', side_effect=lambda name: self.review.legacy.imports[name]):
            counts = reader.restore_reader_runtime(model, manager, manifest)
        self.assertEqual(counts, manifest['counts'])
        self.assertEqual(len(calls), 40)
        self.assertTrue(all(values == {'gemm1_alpha': 0.25, 'gemm1_beta': 1.5, 'gemm1_clamp_limit': 7.0} for values in calls))
        for layer in modules.values():
            if reader._kind(layer) == 'humming-moe':
                self.assertFalse(hasattr(layer, 'w13_input_scale'))
                self.assertFalse(hasattr(layer, 'w2_input_scale'))


if __name__ == '__main__': unittest.main()
