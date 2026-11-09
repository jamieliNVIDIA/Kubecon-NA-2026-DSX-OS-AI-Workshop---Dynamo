"""Fail-closed coverage for the offline, lm_head-only FP8 layout candidate."""
import copy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.reader as reader


class Tensor:
    def __init__(self, shape, dtype, stride, *, is_meta=True):
        self.shape, self.dtype, self._stride = shape, dtype, stride
        self.is_meta, self.is_cuda = is_meta, not is_meta
        self.requires_grad = False
        self.input_dim, self.output_dim = 1, 0
    def stride(self): return self._stride
    def numel(self):
        result = 1
        for dim in self.shape: result *= dim
        return result
    def t(self): return Tensor(tuple(reversed(self.shape)), self.dtype, tuple(reversed(self._stride)))
    def reshape(self, shape): return Tensor(shape, self.dtype, ())


def instance(module, name):
    return type(name, (), {'__module__': module})()


class ReaderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.key = object()
        self.layer = instance(reader.LM_HEAD_MODULE, 'ParallelLMHead')
        qm = instance(reader.MODEL_OPT, 'ModelOptLinearMethod')
        qm.spec = SimpleNamespace(weight=self.key, activation=self.key)
        qm.wkey = instance(reader.MODEL_OPT, 'KFp8StaticTensor')
        qm.akey = instance(reader.MODEL_OPT, 'KFp8StaticTensor')
        self.layer.quant_method = qm
        self.layer.input_size_per_partition = 4096
        self.layer.output_size_per_partition = 65536
        self.param = Tensor(reader.RAW_WEIGHT_SHAPE, 'fp8', (4096, 1))
        self.tensor = Tensor(reader.FINAL_WEIGHT_SHAPE, 'fp8', reader.FINAL_WEIGHT_STRIDE, is_meta=False)
        self.torch = SimpleNamespace(float8_e4m3fn='fp8', float32='fp32',
            nn=SimpleNamespace(Parameter=lambda t, requires_grad: t))

    def call(self, attr='weight', name=None):
        with patch.dict(sys.modules, {'torch': self.torch,
                reader.QUANT_UTILS: SimpleNamespace(kFp8StaticTensorSym=self.key)}):
            return reader.prepare_known_meta_parameter(name or reader.LM_HEAD + '.' + attr,
                self.layer, attr, self.param, self.tensor)

    def test_only_meta_skeleton_is_transposed(self):
        original = copy.copy(self.tensor.__dict__)
        result = self.call()
        self.assertEqual(result.shape, reader.FINAL_WEIGHT_SHAPE)
        self.assertEqual(result.stride(), reader.FINAL_WEIGHT_STRIDE)
        self.assertEqual((result.input_dim, result.output_dim), (0, 1))
        self.assertEqual(self.tensor.__dict__, original)
        self.assertTrue(result.is_meta)

    def test_each_known_singleton_scale_can_be_reconstructed(self):
        for attr in ('input_scale', 'weight_scale'):
            self.param = Tensor((1,), 'fp32', (1,))
            self.tensor = Tensor((), 'fp32', (), is_meta=False)
            self.assertEqual(self.call(attr).shape, ())

    def test_materialized_parameter_does_not_get_adapted(self):
        self.param.is_meta = False
        self.assertIs(self.call(), self.param)

    def test_wrong_parameter_name_does_not_get_adapted(self):
        self.assertIs(self.call(name='language_model.other.weight'), self.param)

    def test_wrong_quant_key_is_rejected(self):
        self.layer.quant_method.spec.activation = object()
        self.assertIs(self.call(), self.param)

    def test_unknown_backend_or_layer_classes_are_rejected(self):
        self.layer.quant_method.wkey = instance(reader.MODEL_OPT, 'KFp8Block128')
        self.assertIs(self.call(), self.param)
        self.layer.quant_method.wkey = instance(reader.MODEL_OPT, 'KFp8StaticTensor')
        self.layer.__class__ = type('OtherHead', (), {})
        self.assertIs(self.call(), self.param)

    def test_dtype_shape_and_physical_stride_checks_remain(self):
        for field, value in (('dtype', 'fp32'), ('shape', (4096, 65535)),
                             ('_stride', (65536, 1)), ('is_cuda', False)):
            original = getattr(self.tensor, field)
            setattr(self.tensor, field, value)
            self.assertIs(self.call(), self.param, field)
            setattr(self.tensor, field, original)

    def test_non_singleton_scale_is_rejected(self):
        self.param = Tensor((2,), 'fp32', (1,))
        self.tensor = Tensor((), 'fp32', (), is_meta=False)
        self.assertIs(self.call('input_scale'), self.param)

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError): reader.patch_materializer('def changed(): pass\n')

    def test_original_shape_and_dtype_guard_is_preserved(self):
        original = '''def materialize(model, specs):
    for name, spec in specs.items():
        if spec:
            param = mod._parameters[attr]
            if param is not None:
                if param.shape != tensor.shape or param.dtype != tensor.dtype:
                    raise RuntimeError(f"Shape/dtype mismatch for {name}")
'''
        transformed = reader.patch_materializer(original)
        self.assertEqual(transformed.count('if param.shape != tensor.shape or param.dtype != tensor.dtype:'), 1)
        self.assertIn('prepare_known_meta_parameter(name, mod, attr, param, tensor)', transformed)
        self.assertIn('Shape/dtype mismatch for', transformed)


if __name__ == '__main__': unittest.main()
