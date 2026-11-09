"""The diagnostic inventories both ranks before preserving strict v2 guards."""
from fractions import Fraction
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.compat.descriptor_linear as original
import demos.shadow.compat.descriptor_attention as diagnostic


class Tensor:
    dtype, shape, requires_grad = 'torch.int32', (4, 4), False
    def stride(self): return (4, 1)


class DiagnosticDescriptorTests(unittest.TestCase):
    def test_diagnostic_retains_existing_dtype_and_layout_allowlists(self):
        self.assertEqual(diagnostic.TORCH_DTYPES, original.TORCH_DTYPES)
        self.assertEqual(diagnostic.PARAM_ATTRS, original.PARAM_ATTRS)

    def test_unsupported_dtype_and_gradient_remain_strict_and_identify_parameter(self):
        for dtype, gradient in [('torch.float8_e8m0fnu', False), ('torch.float32', True)]:
            with self.subTest(dtype=dtype, gradient=gradient):
                tensor = Tensor()
                tensor.dtype, tensor.requires_grad = dtype, gradient
                with self.assertRaisesRegex(ValueError, r'parameter=decoder\.weight, dtype=' + dtype):
                    diagnostic.tensor_layout(tensor, 'decoder.weight')

    def test_fraction_none_and_bad_shape_remain_strict(self):
        for attr in (None, Fraction(1, 2), 'unexpected'):
            tensor = Tensor()
            tensor.packed_factor = attr
            with self.assertRaisesRegex(ValueError, r'layout attribute: parameter=decoder\.weight'):
                diagnostic.tensor_layout(tensor, 'decoder.weight')
        tensor = Tensor()
        tensor.shape = (4, -1)
        with self.assertRaisesRegex(ValueError, r'shape/stride: parameter=decoder\.weight'):
            diagnostic.tensor_layout(tensor, 'decoder.weight')

    def test_inventory_completes_before_any_exporter_or_gms_contract_guard(self):
        calls = []
        identity = {'candidate': 'fresh', 'tp_rank': 0, 'tensor_parallel_size': 2}
        inventory = SimpleNamespace(emit_writer_parameter_inventory=lambda model, observed, directory:
            calls.append(('inventory', observed, directory)))
        contracts, manifest = {}, {'version': diagnostic.VERSION}
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_parameter_inventory': inventory}), \
                patch.dict(diagnostic.os.environ, {'DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR': '/shared'}), \
                patch.object(diagnostic, '_pending_manifest', None), \
                patch.object(diagnostic, 'runtime_identity', return_value=identity), \
                patch.object(diagnostic, 'gms_tensor_contracts', side_effect=lambda manager:
                    calls.append(('gms',)) or contracts), \
                patch.object(diagnostic, 'export_runtime_manifest', side_effect=lambda *args, **kwargs:
                    calls.append(('export',)) or manifest), \
                patch.object(diagnostic, 'validate_tensor_contracts', side_effect=lambda *args:
                    calls.append(('validate',))):
            diagnostic.prepare_writer_manifest(object(), object())
            self.assertIs(diagnostic._pending_manifest, manifest)
        self.assertEqual(calls, [('inventory', identity, '/shared'), ('gms',), ('export',), ('validate',)])

    def test_incomplete_inventory_never_reaches_export_or_records_pending_descriptor(self):
        def fail(*args): raise TimeoutError('peer inventory missing')
        inventory = SimpleNamespace(emit_writer_parameter_inventory=fail)
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_parameter_inventory': inventory}), \
                patch.dict(diagnostic.os.environ, {'DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR': '/shared'}), \
                patch.object(diagnostic, '_pending_manifest', None), \
                patch.object(diagnostic, 'runtime_identity', return_value={}), \
                patch.object(diagnostic, 'gms_tensor_contracts') as contracts, \
                patch.object(diagnostic, 'export_runtime_manifest') as exporter:
            with self.assertRaisesRegex(TimeoutError, 'peer inventory missing'):
                diagnostic.prepare_writer_manifest(object(), object())
            contracts.assert_not_called()
            exporter.assert_not_called()
            self.assertIsNone(diagnostic._pending_manifest)


if __name__ == '__main__': unittest.main()
