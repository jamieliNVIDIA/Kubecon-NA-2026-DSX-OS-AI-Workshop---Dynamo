"""Only the forty observed inference correction roles may preserve grad=True."""
import copy
from fractions import Fraction
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.compat.descriptor_attention as strict
import demos.shadow.writer_descriptors as desc


def cls(key):
    module, name = key.split(':')
    return type(name, (), {'__module__': module})


class Tensor:
    def __init__(self, shape=(512,), stride=(1,), dtype='torch.float32'):
        self.shape, self._stride, self.dtype = tuple(shape), tuple(stride), dtype
        self.requires_grad, self.is_meta, self.is_cuda = False, True, False
    def stride(self): return self._stride


class Parameter(Tensor):
    def __init__(self, tensor=None, requires_grad=True):
        if tensor is None: tensor = Tensor()
        super().__init__(tensor.shape, tensor.stride(), tensor.dtype)
        self.requires_grad = requires_grad


Parameter.__module__ = 'torch.nn.parameter'


def fixture():
    modules = {'': SimpleNamespace(quant_method=None)}
    records, contracts = {}, {}
    for index, name in enumerate(sorted(desc.ROUTING_BIAS_OWNERS)):
        tensor = Parameter()
        layer, gate = cls(desc.ROUTED_EXPERTS)(), cls(desc.GATE_LINEAR)()
        layer.quant_method = cls(desc.MODEL_OPT + ':ModelOptNvFp4FusedMoE')()
        layer.quant_method.nvfp4_backend = SimpleNamespace(name='HUMMING')
        layer.quant_method.moe_kernel = None
        layer.global_num_experts = 512
        layer._parameters = {'e_score_correction_bias': tensor}
        gate.quant_method = cls('vllm.model_executor.layers.linear:UnquantizedLinearMethod')()
        gate._parameters = {'e_score_correction_bias': tensor}
        role = desc.routing_bias_role(name, 'e_score_correction_bias')
        gate_name = role['gate_parameter'].rsplit('.', 1)[0]
        modules[name], modules[gate_name] = layer, gate
        layout = desc.parameter_layout(layer, name, 'e_score_correction_bias', tensor, modules)
        layout.update(allocation_id='routing-' + str(index), offset_bytes=0)
        records[name] = {'kind': 'humming-moe', 'layer_class': desc.ROUTED_EXPERTS,
            'quant_method_class': desc.class_key(layer.quant_method), 'parameters': {'e_score_correction_bias': layout},
            'none_parameters': []}
        contract = {key: layout[key] for key in ('shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes')}
        contracts[name + '.e_score_correction_bias'] = dict(contract, tensor_type='parameter')
        contracts[role['gate_parameter']] = dict(contract, tensor_type='parameter')
    manifest = {'version': desc.VERSION, 'identity': {'fresh': 'fixture'}, 'reader_ready': True,
        'unhandled_modules': {}, 'modules': records, 'counts': {'humming-linear': 0, 'humming-moe': 40, 'cutlass-fp8': 0}}
    model = SimpleNamespace(named_modules=lambda: iter(modules.items()))
    return model, modules, manifest, contracts


class RoutingCorrectionTests(unittest.TestCase):
    def test_exact_observed_role_preserves_true_bit_without_mutating_tensor_or_expanding_dtype(self):
        model, modules, manifest, contracts = fixture()
        desc.validate_tensor_contracts(manifest, contracts)
        self.assertEqual(len(desc.ROUTING_BIAS_OWNERS), 40)
        self.assertEqual(desc.TORCH_DTYPES, strict.TORCH_DTYPES)
        self.assertEqual(desc.PARAM_ATTRS, strict.PARAM_ATTRS)
        for name, row in manifest['modules'].items():
            tensor = modules[name]._parameters['e_score_correction_bias']
            self.assertTrue(tensor.requires_grad)
            self.assertTrue(row['parameters']['e_score_correction_bias']['requires_grad'])
            with self.assertRaisesRegex(ValueError, 'dtype/gradient contract'):
                desc.tensor_layout(tensor, name + '.e_score_correction_bias')

    def test_wrong_owner_backend_type_shape_dtype_grad_or_attrs_remains_strict(self):
        cases = ('unknown-name', 'wrong-class', 'wrong-backend', 'wrong-expert-count',
            'wrong-gate-class', 'wrong-shape', 'wrong-stride', 'wrong-dtype', 'false-grad',
            'fraction-attr', 'none-attr', 'lost-object-alias')
        for case in cases:
            with self.subTest(case=case):
                model, modules, manifest, contracts = fixture()
                name = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                layer = modules[name]; tensor = layer._parameters['e_score_correction_bias']
                role = desc.routing_bias_role(name, 'e_score_correction_bias')
                gate = modules[role['gate_parameter'].rsplit('.', 1)[0]]
                if case == 'unknown-name': name += '_unknown'
                elif case == 'wrong-class': layer.__class__ = cls('unreviewed:RoutedExperts')
                elif case == 'wrong-backend': layer.quant_method.nvfp4_backend.name = 'MARLIN'
                elif case == 'wrong-expert-count': layer.global_num_experts = 513
                elif case == 'wrong-gate-class': gate.__class__ = cls('unreviewed:GateLinear')
                elif case == 'wrong-shape': tensor.shape = (513,)
                elif case == 'wrong-stride': tensor._stride = (2,)
                elif case == 'wrong-dtype': tensor.dtype = 'torch.float8_e8m0fnu'
                elif case == 'false-grad': tensor.requires_grad = False
                elif case == 'fraction-attr': tensor.packed_factor = Fraction(1, 2)
                elif case == 'none-attr': tensor.input_dim = None
                elif case == 'lost-object-alias': gate._parameters['e_score_correction_bias'] = Parameter()
                with self.assertRaises(ValueError):
                    desc.parameter_layout(layer, name, 'e_score_correction_bias', tensor, modules)

    def test_gradient_on_any_other_parameter_or_forged_role_is_refused(self):
        model, modules, manifest, contracts = fixture()
        name = sorted(desc.ROUTING_BIAS_OWNERS)[0]
        tensor = Parameter()
        with self.assertRaisesRegex(ValueError, 'dtype/gradient contract'):
            desc.parameter_layout(modules[name], name, 'another_weight', tensor, modules)
        row = copy.deepcopy(manifest['modules'][name]['parameters']['e_score_correction_bias'])
        manifest['modules'][name]['parameters']['another_weight'] = row
        with self.assertRaisesRegex(ValueError, 'Unreviewed gradient-bearing parameter role'):
            desc.validate_tensor_contracts(manifest, contracts)

    def test_independent_gate_contract_requires_exact_allocation_offset_shape_stride_dtype(self):
        for field, wrong in [('allocation_id', 'foreign'), ('offset_bytes', 4),
                ('shape', [256]), ('stride', [2]), ('dtype', 'torch.bfloat16')]:
            with self.subTest(field=field):
                model, modules, manifest, contracts = fixture()
                name = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                role = desc.routing_bias_role(name, 'e_score_correction_bias')
                contracts[role['gate_parameter']][field] = wrong
                with self.assertRaisesRegex(ValueError, 'gate/correction alias mismatch'):
                    desc.validate_tensor_contracts(manifest, contracts)

    def test_missing_role_or_wrong_true_flag_is_refused_before_reader_mutation(self):
        for change in ('missing-owner', 'false-flag', 'forged-gate'):
            with self.subTest(change=change):
                model, modules, manifest, contracts = fixture()
                name = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                original = modules[name]._parameters['e_score_correction_bias']
                layout = manifest['modules'][name]['parameters']['e_score_correction_bias']
                if change == 'missing-owner': del manifest['modules'][name]
                elif change == 'false-flag': layout['requires_grad'] = False
                else: layout['inference_role']['gate_parameter'] += '_wrong'
                with patch.dict(sys.modules, {'torch': SimpleNamespace()}), self.assertRaises(ValueError):
                    desc.prepare_reader_skeleton(model, manifest, contracts, manifest['identity'])
                self.assertIs(modules[name]._parameters['e_score_correction_bias'], original)

    def test_reader_meta_skeleton_roundtrip_preserves_exact_40_true_flags(self):
        model, modules, manifest, contracts = fixture()
        restored = desc.decode(desc.encode({'ordinary': True}))
        self.assertEqual(restored, {'ordinary': True})
        manifest = __import__('json').loads(__import__('json').dumps(manifest))
        torch = SimpleNamespace(float32='torch.float32', nn=SimpleNamespace(Parameter=Parameter),
            empty_strided=lambda shape, stride, dtype, device: Tensor(shape, stride, dtype))
        before = {name: modules[name]._parameters['e_score_correction_bias'] for name in desc.ROUTING_BIAS_OWNERS}
        with patch.dict(sys.modules, {'torch': torch}):
            desc.prepare_reader_skeleton(model, manifest, contracts, manifest['identity'])
        for name in desc.ROUTING_BIAS_OWNERS:
            current = modules[name]._parameters['e_score_correction_bias']
            self.assertIsNot(current, before[name]); self.assertTrue(current.is_meta)
            self.assertIs(current.requires_grad, True)
            self.assertEqual((current.dtype, current.shape, current.stride()), ('torch.float32', (512,), (1,)))


if __name__ == '__main__': unittest.main()
