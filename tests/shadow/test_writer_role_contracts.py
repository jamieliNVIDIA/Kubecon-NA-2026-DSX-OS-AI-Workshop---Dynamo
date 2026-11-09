"""Independent negative review of the narrow v4 routing-bias exception.

Metadata doubles exercise the complete writer/reader path without CUDA or
tensor contents. The legacy fixture supplies the 80/40/2 backend inventory;
the forty new role names, alias parameters and contracts are installed here.
"""
from fractions import Fraction
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.writer_descriptors as desc
import tests.shadow.compat.test_descriptor_linear as legacy_fixture
from tests.shadow.compat.test_descriptor_linear import Tensor, cls


class Parameter(Tensor):
    def __init__(self, tensor=None, requires_grad=True, pointer=1024):
        super().__init__(pointer)
        self.shape, self.dtype = (512,), 'torch.float32'
        self._stride = (1,)
        self.requires_grad = requires_grad
        if tensor is not None:
            self.shape, self.dtype, self.device = tensor.shape, tensor.dtype, tensor.device
            self._stride = tensor.stride()
            self.is_meta, self.is_cuda = tensor.is_meta, tensor.is_cuda
    def stride(self): return self._stride
    def __repr__(self): raise AssertionError('Review must not render tensor contents')


Parameter.__module__ = 'torch.nn.parameter'


def parameter_contracts(modules):
    """Independent fake-GMS metadata, not a projection of exported JSON."""
    result = {}
    for name, layer in modules.items():
        for attr, tensor in layer._parameters.items():
            if tensor is not None:
                result[name + '.' + attr] = {
                    'shape': list(tensor.shape), 'stride': list(tensor.stride()),
                    'dtype': tensor.dtype, 'allocation_id': 'a',
                    'offset_bytes': tensor.pointer - 1000, 'tensor_type': 'parameter'}
    return result


class IndependentRoleReviewTests(unittest.TestCase):
    def setUp(self):
        self.legacy = legacy_fixture.DescriptorTests()
        self.legacy.setUp()

    def complete_writer(self):
        model, manager, identity = self.legacy.complete_writer()
        modules = dict(model.named_modules())
        for index, owner in enumerate(sorted(desc.ROUTING_BIAS_OWNERS)):
            layer = modules.pop('moe' + str(index))
            layer.global_num_experts = 512
            bias = Parameter()
            layer._parameters['e_score_correction_bias'] = bias
            modules[owner] = layer
            gate = cls(desc.GATE_LINEAR)()
            gate.quant_method = cls('vllm.model_executor.layers.linear:UnquantizedLinearMethod')()
            gate._parameters = {'e_score_correction_bias': bias}
            gate_name = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter'].rsplit('.', 1)[0]
            modules[gate_name] = gate
        model.named_modules = lambda: iter(modules.items())
        model.named_parameters = lambda: ((name + '.' + attr, tensor)
            for name, layer in modules.items() for attr, tensor in layer._parameters.items() if tensor is not None)
        return model, modules, manager, identity

    def exported(self):
        model, modules, manager, identity = self.complete_writer()
        contracts = parameter_contracts(modules)
        manifest = desc.export_runtime_manifest(model, manager, identity, contracts=contracts)
        desc.validate_tensor_contracts(manifest, contracts)
        return model, modules, manager, identity, manifest, contracts

    def fake_torch(self):
        def empty(shape, stride, dtype, device):
            tensor = Tensor()
            tensor.shape, tensor.dtype, tensor.device = tuple(shape), dtype, device
            tensor.stride = lambda: tuple(stride)
            tensor.is_meta, tensor.is_cuda = True, False
            return tensor
        def zeros(size, dtype, device):
            tensor = Tensor(100000)
            tensor.shape, tensor.dtype, tensor.device = (size,), dtype, device
            tensor.stride = lambda: (1,)
            return tensor
        return SimpleNamespace(empty_strided=empty, zeros=zeros, nn=SimpleNamespace(Parameter=Parameter),
            **{name.removeprefix('torch.'): name for name in desc.TORCH_DTYPES})

    def runtime(self):
        model, modules, manager, identity, manifest, contracts = self.exported()
        fake = self.fake_torch()
        for layer in modules.values():
            qm = layer.quant_method
            qm.process_weights_after_loading = lambda _: self.fail('Weight transformation must not run')
            if desc._kind(layer) != 'humming-moe': continue
            def config(_layer):
                make = lambda: SimpleNamespace(scale=None, alpha_or_gscale=None, zp=None, bias=None)
                return SimpleNamespace(_w1=make(), _w2=make(), w1_input_scale=None,
                    w1_input_scale_2=None, w2_input_scale=None, w2_input_scale_2=None)
            qm.get_fused_moe_quant_config = config
            qm.moe = object()
            layer._expert_routing_tables = lambda: None
        def build(**kwargs):
            expert = object.__new__(kwargs['experts_cls'])
            expert.locks = fake.zeros(1024, 'torch.int32', 'cuda:0')
            return SimpleNamespace(fused_experts=expert)
        self.legacy.imports['vllm.model_executor.layers.quantization.utils.humming.moe'] = SimpleNamespace(
            make_humming_moe_kernel=build)
        hook = SimpleNamespace(_pool_managers=lambda _: [manager],
            rebind_humming_locks=lambda *_: [{'already_private': True}])
        return model, modules, manager, manifest, fake, hook

    def restore(self, model, manager, manifest, fake, hook):
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(desc.importlib, 'import_module', side_effect=lambda name: self.legacy.imports[name]):
            return desc.restore_reader_runtime(model, manager, manifest)

    def test_complete_writer_export_preserves_exact_roles_and_validates_independent_gms(self):
        model, modules, manager, identity, manifest, contracts = self.exported()
        self.assertEqual(manifest['counts'], {'humming-linear': 80, 'humming-moe': 40, 'cutlass-fp8': 2})
        self.assertTrue(manifest['reader_ready'])
        observed = {name for name, row in manifest['modules'].items()
            if row['parameters'].get('e_score_correction_bias', {}).get('requires_grad') is True}
        self.assertEqual(observed, desc.ROUTING_BIAS_OWNERS)
        self.assertEqual(sum(row['parameters'][attr]['requires_grad'] is True
            for row in manifest['modules'].values() for attr in row['parameters']), 40)

    def test_full_writer_rejects_general_gradient_dtype_layout_and_bias_alias_changes(self):
        for case in ('ordinary-gradient', 'ordinary-dtype', 'ordinary-fraction-attr', 'ordinary-none-attr',
                'ordinary-bool-shape', 'ordinary-negative-stride', 'bias-object-alias',
                'bias-nonplain-parameter', 'bias-cpu', 'bias-meta', 'missing-role'):
            with self.subTest(case=case):
                model, modules, manager, identity = self.complete_writer()
                owner = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                bias = modules[owner]._parameters['e_score_correction_bias']
                ordinary = modules['linear0']._parameters['weight']
                gate_name = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter'].rsplit('.', 1)[0]
                if case == 'ordinary-gradient': ordinary.requires_grad = True
                elif case == 'ordinary-dtype': ordinary.dtype = 'torch.float8_e8m0fnu'
                elif case == 'ordinary-fraction-attr': ordinary.packed_factor = Fraction(1, 2)
                elif case == 'ordinary-none-attr': ordinary.input_dim = None
                elif case == 'ordinary-bool-shape': ordinary.shape = (True, 4)
                elif case == 'ordinary-negative-stride': ordinary.stride = lambda: (4, -1)
                elif case == 'bias-object-alias': modules[gate_name]._parameters['e_score_correction_bias'] = Parameter()
                elif case == 'bias-nonplain-parameter':
                    bias.__class__ = type('OtherParameter', (Parameter,), {'__module__': 'torch.nn.parameter'})
                elif case == 'bias-cpu': bias.is_cuda = False
                elif case == 'bias-meta': bias.is_meta = True
                elif case == 'missing-role': del modules[owner]._parameters['e_score_correction_bias']
                with self.assertRaises(ValueError): desc.export_runtime_manifest(model, manager, identity)

    def test_full_writer_rejects_bias_extent_overflow_or_ambiguous_mapping(self):
        for case in ('overflow', 'ambiguous'):
            with self.subTest(case=case):
                model, modules, manager, identity = self.complete_writer()
                bias = modules[sorted(desc.ROUTING_BIAS_OWNERS)[0]]._parameters['e_score_correction_bias']
                if case == 'overflow': bias.pointer = 4000
                else: manager.mappings[1001] = SimpleNamespace(aligned_size=4096, allocation_id='overlap')
                with self.assertRaisesRegex(ValueError, 'unambiguously'):
                    desc.export_runtime_manifest(model, manager, identity)

    def test_gate_metadata_missing_buffer_or_foreign_layout_is_rejected(self):
        for case in ('missing', 'buffer', 'allocation_id', 'offset_bytes', 'shape', 'stride', 'dtype'):
            with self.subTest(case=case):
                model, modules, manager, identity, manifest, contracts = self.exported()
                owner = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                gate = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter']
                if case == 'missing': del contracts[gate]
                elif case == 'buffer': contracts[gate]['tensor_type'] = 'buffer'
                else: contracts[gate][case] = {'allocation_id': 'other', 'offset_bytes': 28,
                    'shape': [511], 'stride': [2], 'dtype': 'torch.bfloat16'}[case]
                with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, contracts)

    def test_role_layout_and_allocation_reject_equal_but_noncanonical_numbers(self):
        for case in ('float-shape', 'float-stride', 'bool-stride', 'float-offset', 'bool-offset',
                'gms-float-offset', 'gms-bool-offset', 'gate-float-offset', 'gate-bool-offset'):
            with self.subTest(case=case):
                model, modules, manager, identity, manifest, contracts = self.exported()
                owner = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                qualified = owner + '.e_score_correction_bias'
                gate = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter']
                layout = manifest['modules'][owner]['parameters']['e_score_correction_bias']
                if case == 'float-shape': layout['shape'] = [512.0]
                elif case == 'float-stride': layout['stride'] = [1.0]
                elif case == 'bool-stride': layout['stride'] = [True]
                elif case == 'float-offset': layout['offset_bytes'] = 24.0
                elif case == 'bool-offset':
                    layout['offset_bytes'] = False
                    contracts[qualified]['offset_bytes'] = contracts[gate]['offset_bytes'] = 0
                elif case == 'gms-float-offset': contracts[qualified]['offset_bytes'] = 24.0
                elif case == 'gms-bool-offset':
                    layout['offset_bytes'] = 0
                    contracts[qualified]['offset_bytes'] = False
                    contracts[gate]['offset_bytes'] = 0
                elif case == 'gate-float-offset': contracts[gate]['offset_bytes'] = 24.0
                elif case == 'gate-bool-offset':
                    layout['offset_bytes'] = contracts[qualified]['offset_bytes'] = 0
                    contracts[gate]['offset_bytes'] = False
                with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, contracts)

    def test_reader_rejects_late_nonmeta_or_bad_attrs_without_rebinding_any_layer(self):
        for case in ('late-materialized', 'nonfinite-attrs', 'fraction-attrs', 'extra-role'):
            with self.subTest(case=case):
                model, modules, manager, identity, manifest, contracts = self.exported()
                for layer in modules.values():
                    for tensor in layer._parameters.values():
                        if tensor is not None: tensor.is_meta, tensor.is_cuda = True, False
                owner = sorted(desc.ROUTING_BIAS_OWNERS)[-1]
                if case == 'late-materialized': modules[owner]._parameters['w13_weight'].is_meta = False
                elif case == 'extra-role':
                    manifest['modules']['linear0']['parameters']['weight']['inference_role'] = {'role': 'fake'}
                else:
                    manifest['modules']['linear0']['parameters']['weight']['attrs'] = {
                        'packed_factor': float('nan') if case == 'nonfinite-attrs' else Fraction(1, 2)}
                originals = {name: dict(layer._parameters) for name, layer in modules.items()}
                with patch.dict(sys.modules, {'torch': self.fake_torch()}), self.assertRaises(ValueError):
                    desc.prepare_reader_skeleton(model, manifest, contracts, identity)
                for name, layer in modules.items():
                    self.assertEqual(set(layer._parameters), set(originals[name]))
                    for attr, tensor in layer._parameters.items(): self.assertIs(tensor, originals[name][attr])

    def test_post_materialization_allows_distinct_parameters_only_with_exact_allocation_alias(self):
        model, modules, manager, manifest, fake, hook = self.runtime()
        for owner in desc.ROUTING_BIAS_OWNERS:
            gate_name = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter'].rsplit('.', 1)[0]
            modules[gate_name]._parameters['e_score_correction_bias'] = Parameter()
        self.assertEqual(self.restore(model, manager, manifest, fake, hook), manifest['counts'])

    def test_post_materialization_rechecks_layout_grad_gate_type_and_pointer(self):
        cases = ('bias-cpu', 'bias-meta', 'bias-dtype', 'bias-shape', 'bias-stride', 'bias-grad',
            'bias-attrs', 'bias-offset', 'bias-allocation', 'gate-offset', 'gate-grad', 'gate-dtype',
            'gate-type', 'gate-attrs', 'ordinary-gradient', 'ordinary-dtype', 'ordinary-offset',
            'ordinary-layout', 'optional-present')
        for case in cases:
            with self.subTest(case=case):
                model, modules, manager, manifest, fake, hook = self.runtime()
                owner = sorted(desc.ROUTING_BIAS_OWNERS)[0]
                bias = modules[owner]._parameters['e_score_correction_bias']
                gate_name = desc.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter'].rsplit('.', 1)[0]
                gate = Parameter()
                modules[gate_name]._parameters['e_score_correction_bias'] = gate
                ordinary = modules['linear0']._parameters['weight']
                if case == 'bias-cpu': bias.is_cuda = False
                elif case == 'bias-meta': bias.is_meta = True
                elif case == 'bias-dtype': bias.dtype = 'torch.bfloat16'
                elif case == 'bias-shape': bias.shape = (256,)
                elif case == 'bias-stride': bias._stride = (2,)
                elif case == 'bias-grad': bias.requires_grad = False
                elif case == 'bias-attrs': bias.input_dim = 0
                elif case == 'bias-offset': bias.pointer += 4
                elif case == 'bias-allocation':
                    bias.pointer = 10000
                    manager.mappings[10000] = SimpleNamespace(aligned_size=4096, allocation_id='other')
                elif case == 'gate-offset': gate.pointer += 4
                elif case == 'gate-grad': gate.requires_grad = False
                elif case == 'gate-dtype': gate.dtype = 'torch.bfloat16'
                elif case == 'gate-type': gate.__class__ = cls('torch.nn.parameter:OtherParameter')
                elif case == 'gate-attrs': gate.packed_factor = 2
                elif case == 'ordinary-gradient': ordinary.requires_grad = True
                elif case == 'ordinary-dtype': ordinary.dtype = 'torch.float8_e8m0fnu'
                elif case == 'ordinary-offset': ordinary.pointer += 4
                elif case == 'ordinary-layout': ordinary.stride = lambda: (1, 4)
                elif case == 'optional-present': modules[owner]._parameters['w13_input_scale'] = Tensor()
                with self.assertRaises(ValueError): self.restore(model, manager, manifest, fake, hook)

    def test_runtime_reconstruction_still_rejects_foreign_moe_alias_and_gms_workspace(self):
        for case in ('foreign-moe-alias', 'gms-workspace'):
            with self.subTest(case=case):
                model, modules, manager, manifest, fake, hook = self.runtime()
                if case == 'foreign-moe-alias':
                    qm = modules[sorted(desc.ROUTING_BIAS_OWNERS)[0]].quant_method
                    original = qm.get_fused_moe_quant_config
                    def foreign(layer):
                        config = original(layer)
                        config._w1.scale = Tensor()
                        return config
                    qm.get_fused_moe_quant_config = foreign
                else: hook.rebind_humming_locks = lambda *_: [{'already_private': False}]
                with self.assertRaises(ValueError): self.restore(model, manager, manifest, fake, hook)


if __name__ == '__main__': unittest.main()
