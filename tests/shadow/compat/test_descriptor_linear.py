"""Behavioral checks for the restricted JSON writer/reader descriptor prototype."""
import copy
from dataclasses import make_dataclass
from enum import Enum
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.compat.descriptor_linear as desc


def cls(key):
    module, name = key.split(':')
    return type(name, (), {'__module__': module})


class Tensor:
    is_cuda, is_meta, requires_grad = True, False, False
    dtype, shape, device = 'torch.int32', (4, 4), 'cuda:0'
    def __init__(self, pointer=1024): self.pointer = pointer
    def stride(self): return (4, 1)
    def data_ptr(self): return self.pointer
    def element_size(self): return 4


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self.config_cls = make_dataclass('LayerConfig', [('shape_n', int), ('dtype', object)])
        self.config_cls.__module__ = 'humming.config.config'
        self.config_cls.check_device = lambda _, device: None
        self.schema_cls = make_dataclass('HummingWeightSchema', [('hadamard_block_size', int)])
        self.schema_cls.__module__ = 'humming.schema.humming'
        self.enum_cls = Enum('WeightScaleType', {'GROUP': 'group'})
        self.enum_cls.__module__ = 'humming.config.enum'
        self.dt_cls = cls('humming.dtypes:FloatingPointType')
        self.dt_cls.__str__ = lambda _: 'float8e4m3'
        self.imports = {
            'humming.config.config': SimpleNamespace(LayerConfig=self.config_cls),
            'humming.schema.humming': SimpleNamespace(HummingWeightSchema=self.schema_cls),
            'humming.config.enum': SimpleNamespace(WeightScaleType=self.enum_cls),
            'humming.dtypes': SimpleNamespace(DataType=SimpleNamespace(from_str=lambda _: self.dt_cls())),
        }

    def decode(self, value):
        with patch.object(desc.importlib, 'import_module', side_effect=lambda key: self.imports[key]):
            return desc.decode(value)

    def test_restricted_config_schema_dtype_enum_roundtrip(self):
        value = {'config': self.config_cls(128, self.dt_cls()),
                 'schema': self.schema_cls(0), 'scale': self.enum_cls.GROUP}
        restored = self.decode(desc.encode(value))
        self.assertEqual(restored['config'].shape_n, 128)
        self.assertEqual(str(restored['config'].dtype), 'float8e4m3')
        self.assertEqual(restored['schema'].hadamard_block_size, 0)
        self.assertIs(restored['scale'], self.enum_cls.GROUP)

    def test_arbitrary_objects_tensors_and_nonfinite_values_refused(self):
        for value in (object(), Tensor(), float('nan'), float('inf'), {3: 'not-a-string-key'}):
            with self.assertRaises(ValueError): desc.encode(value)

    def test_data_cannot_select_an_arbitrary_class_to_import(self):
        with patch.object(desc.importlib, 'import_module') as importer:
            with self.assertRaises(ValueError):
                desc.decode({'class': 'os:system', 'fields': {}})
            importer.assert_not_called()

    def test_missing_extra_or_renamed_dataclass_fields_refused(self):
        payload = desc.encode(self.config_cls(128, 'fp8'))
        for wrong in ({'shape_n': 128}, {'shape_n': 128, 'dtype': 'fp8', 'extra': True}):
            payload['fields'] = wrong
            with self.assertRaises(ValueError): self.decode(payload)

    def test_unknown_tag_or_noncanonical_dtype_refused(self):
        with self.assertRaises(ValueError): self.decode({'pickle': 'unsafe'})
        with self.assertRaises(ValueError): self.decode({'dtype': 'not-canonical'})

    def test_manifest_publication_is_atomic_and_never_overwrites_old_generation(self):
        value = {'version': desc.VERSION, 'identity': {'candidate': 'new'}, 'modules': {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rank-0.json'
            desc.save_runtime_manifest(value, path)
            self.assertEqual(desc.load_runtime_manifest(path, value['identity']), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError): desc.save_runtime_manifest(value, path)
            with self.assertRaises(ValueError): desc.load_runtime_manifest(path, {'candidate': 'old'})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_complete_parameter_extent_must_fit_one_gms_mapping(self):
        manager = SimpleNamespace(mappings={1000: SimpleNamespace(aligned_size=128, allocation_id='a')})
        self.assertEqual(desc.allocation_identity(Tensor(), manager), {'allocation_id': 'a', 'offset_bytes': 24})
        with self.assertRaises(ValueError): desc.allocation_identity(Tensor(1100), manager)

    def manifest_contract(self):
        layout = desc.tensor_layout(Tensor())
        layout.update(allocation_id='weights', offset_bytes=24)
        row = {'kind': 'humming-linear', 'parameters': {'weight': layout}}
        manifest = {'version': desc.VERSION, 'modules': {'layer': row}}
        contracts = {'layer.weight': {k: layout[k] for k in (
            'shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes')}}
        return manifest, contracts

    def test_gms_layout_validation_checks_identity_and_physical_layout(self):
        manifest, contracts = self.manifest_contract()
        desc.validate_tensor_contracts(manifest, contracts)
        for key, value in (('allocation_id', 'foreign'), ('offset_bytes', 25),
                           ('stride', [1, 4]), ('shape', [2, 8]), ('dtype', 'torch.float32')):
            changed = copy.deepcopy(contracts)
            changed['layer.weight'][key] = value
            with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, changed)

    def test_extra_or_missing_gms_parameters_refused(self):
        manifest, contracts = self.manifest_contract()
        with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, {})
        contracts['layer.unexpected'] = contracts['layer.weight']
        with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, contracts)

    def test_unknown_backend_refused(self):
        qm = cls(desc.MODEL_OPT + ':ModelOptLinearMethod')()
        qm.kernel = object()
        with self.assertRaises(ValueError): desc._kind(SimpleNamespace(quant_method=qm))

    def test_stale_manifest_rejected_before_skeleton_mutation(self):
        model = SimpleNamespace(named_modules=lambda: iter(()))
        with patch.dict(sys.modules, {'torch': SimpleNamespace()}):
            with self.assertRaisesRegex(ValueError, 'Stale or foreign'):
                desc.prepare_reader_skeleton(model, {'identity': {'candidate': 'old'}}, {}, {'candidate': 'new'})

    def test_manifest_export_checks_pinned_inventory_and_never_instantiates_experts(self):
        # The full source-reviewed inventory is validated before a manifest
        # can be published; a partial writer is not enough for a reader.
        identity = {'candidate': 'new', 'image_sha256': 'a' * 64, 'model_revision': 'b' * 40,
            'model_config_sha256': 'd' * 64,
            'source_manifest_sha256': 'c' * 64, 'tp_rank': 0, 'tensor_parallel_size': 2}
        model = SimpleNamespace(named_modules=lambda: iter(()))
        with self.assertRaisesRegex(ValueError, 'module inventory'):
            desc.export_runtime_manifest(model, SimpleNamespace(mappings={}), identity)

    def complete_writer(self):
        identity = {'candidate': 'new', 'image_sha256': 'a' * 64, 'model_revision': 'b' * 40,
            'model_config_sha256': 'd' * 64,
            'source_manifest_sha256': 'c' * 64, 'tp_rank': 0, 'tensor_parallel_size': 2}
        modules = {}
        for index in range(80):
            layer = cls('vllm.model_executor.layers.linear:RowParallelLinear')()
            qm = cls(desc.MODEL_OPT + ':ModelOptLinearMethod')()
            kernel = cls(desc.HUMMING_LINEAR)()
            kernel.layer_config = self.config_cls(16, self.dt_cls())
            kernel.compute_config = '{"gemm_type":"dense"}'
            layer.weight_schema = self.schema_cls(0)
            layer.is_w4a16_nvfp4 = False
            layer._parameters = {'weight': Tensor()}
            layer.weight = layer._parameters['weight']
            layer.quant_method = qm
            qm.kernel, qm.spec = kernel, 'nvfp4-fixed-spec'
            modules['linear' + str(index)] = layer
        def forbidden_init(_): raise AssertionError('Export must not construct a new expert.')
        expert_cls = cls(desc.MOE_MODULE + ':HummingIndexedExperts')
        expert_cls.__init__ = forbidden_init
        for index in range(40):
            layer = cls('vllm.model_executor.layers.fused_moe.routed_experts:RoutedExperts')()
            qm = cls(desc.MODEL_OPT + ':ModelOptNvFp4FusedMoE')()
            expert = object.__new__(expert_cls)
            qm.experts_cls = expert_cls
            qm.nvfp4_backend = SimpleNamespace(name='HUMMING')
            qm.moe_kernel = SimpleNamespace(fused_experts=expert)
            layer.weight_schemas = {'w13': self.schema_cls(0), 'w2': self.schema_cls(0)}
            layer.input_schemas = {'w13': None, 'w2': None}
            layer.humming_configs = {'w13': self.config_cls(16, 'fp4'), 'w2': self.config_cls(16, 'fp4')}
            layer._parameters = {'w13_weight': Tensor(), 'w2_weight': Tensor(),
                                 'w13_input_scale': None, 'w2_input_scale': None}
            layer.quant_method = qm
            modules['moe' + str(index)] = layer
        # More than one FP8 layer is valid: the actual writer selects Cutlass
        # for dense projections as well as the output head.
        for name in ('attention', 'language_model.lm_head'):
            layer = cls('vllm.model_executor.layers.linear:QKVParallelLinear')()
            qm = cls(desc.MODEL_OPT + ':ModelOptLinearMethod')()
            qm.kernel = cls(desc.CUTLASS_FP8)()
            qm.kernel.logical_output_size = 16
            qm.spec = 'fp8-fixed-spec'
            tensor = Tensor()
            tensor.shape = (16, 16)
            tensor.stride = lambda: (1, 16)
            layer._parameters = {'weight': tensor}
            layer.weight = tensor
            layer.is_w4a16_nvfp4 = False
            layer.quant_method = qm
            modules[name] = layer
        model = SimpleNamespace(named_modules=lambda: iter(modules.items()),
            named_parameters=lambda: ((name + '.' + attr, tensor) for name, layer in modules.items()
                for attr, tensor in layer._parameters.items() if tensor is not None),
            named_buffers=lambda: iter(()))
        manager = SimpleNamespace(mappings={1000: SimpleNamespace(aligned_size=4096, allocation_id='a')})
        return model, manager, identity

    def test_final_writer_inventory_and_descriptors_export_without_any_weight_operation(self):
        model, manager, identity = self.complete_writer()
        value = desc.export_runtime_manifest(model, manager, identity)
        self.assertEqual(value['counts'], {'humming-linear': 80, 'humming-moe': 40, 'cutlass-fp8': 2})
        self.assertEqual(len(value['modules']), 122)
        self.assertEqual(value['modules']['moe0']['experts_class'],
            desc.MOE_MODULE + ':HummingIndexedExperts')
        self.assertEqual(value['modules']['linear0']['parameters']['weight']['offset_bytes'], 24)
        self.assertEqual(value['modules']['moe0']['none_parameters'], ['w13_input_scale', 'w2_input_scale'])

    def test_unhandled_attention_quant_method_is_observed_but_refuses_reader_startup(self):
        model, manager, identity = self.complete_writer()
        modules = dict(model.named_modules())
        qcache = cls(desc.MODEL_OPT + ':ModelOptFutureKVMethod')()
        modules['attention'] = SimpleNamespace(quant_method=qcache, _parameters={})
        model.named_modules = lambda: iter(modules.items())
        value = desc.export_runtime_manifest(model, manager, identity)
        self.assertFalse(value['reader_ready'])
        self.assertIn('attention', value['unhandled_modules'])
        with patch.dict(sys.modules, {'torch': self.fake_torch()}):
            with self.assertRaisesRegex(ValueError, 'unsupported reader runtime state'):
                desc.prepare_reader_skeleton(model, value, {}, identity)

    def test_gms_contract_adapter_uses_independent_parameter_metadata_only(self):
        meta = SimpleNamespace(shape=(16, 16), stride=(1, 16), dtype='torch.float32', tensor_type='parameter')
        spec = SimpleNamespace(meta=meta, allocation_id='weights-real', offset_bytes=72)
        buffer_meta = copy.copy(meta)
        buffer_meta.tensor_type = 'buffer'
        module = SimpleNamespace(GMSTensorSpec=SimpleNamespace(load_all=lambda _: {
            'head.weight': spec, 'head.buffer': SimpleNamespace(meta=buffer_meta)}))
        with patch.dict(sys.modules, {'gpu_memory_service.client.torch.tensor': module}):
            result = desc.gms_parameter_contracts(object())
        self.assertEqual(set(result), {'head.weight'})
        self.assertEqual(result['head.weight']['allocation_id'], 'weights-real')
        self.assertEqual(result['head.weight']['offset_bytes'], 72)

    def test_manifest_cannot_attach_to_a_different_committed_gms_layout(self):
        identity = {'candidate': 'new'}
        value = {'version': desc.VERSION, 'identity': identity,
                 'gms_memory_layout_hash': 'a' * 64, 'modules': {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rank-0.json'
            desc.save_runtime_manifest(value, path)
            with patch.object(desc, 'runtime_identity', return_value=identity), \
                    patch.object(desc, 'runtime_manifest_path', return_value=path):
                with self.assertRaisesRegex(ValueError, 'different committed GMS layout'):
                    desc.read_committed_manifest(SimpleNamespace(get_memory_layout_hash=lambda: 'b' * 64))

    def test_reader_missing_descriptor_has_a_bounded_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(desc, 'runtime_identity', return_value={}), \
                    patch.object(desc, 'runtime_manifest_path', return_value=Path(directory) / 'missing'):
                with self.assertRaises(TimeoutError): desc.read_committed_manifest(object(), timeout=0)

    def test_loader_composition_refuses_unrecognized_source(self):
        with self.assertRaises(ValueError): desc.patch_descriptor_loader('def changed_api(): pass\n')

    def exported_model(self):
        model, manager, identity = self.complete_writer()
        manifest = desc.export_runtime_manifest(model, manager, identity)
        contracts = {name + '.' + attr: {k: layout[k] for k in (
            'shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes')}
            for name, row in manifest['modules'].items() for attr, layout in row['parameters'].items()}
        return model, manager, identity, manifest, contracts

    def fake_torch(self):
        def empty(shape, stride, dtype, device):
            tensor = Tensor()
            tensor.shape, tensor.dtype, tensor.device = tuple(shape), dtype, device
            tensor.stride = lambda: tuple(stride)
            tensor.is_meta, tensor.is_cuda = True, False
            return tensor
        def zeros(size, dtype, device):
            tensor = Tensor(pointer=100000)
            tensor.shape, tensor.dtype, tensor.device = (size,), dtype, device
            tensor.stride = lambda: (1,)
            return tensor
        return SimpleNamespace(empty_strided=empty, zeros=zeros, int32='torch.int32',
            nn=SimpleNamespace(Parameter=lambda t, requires_grad: t))

    def test_reader_prepares_exact_final_meta_parameters_and_preserves_none_attributes(self):
        model, manager, identity, manifest, contracts = self.exported_model()
        for _, layer in model.named_modules():
            for tensor in layer._parameters.values():
                if tensor is not None: tensor.is_meta, tensor.is_cuda = True, False
            # Simulate raw checkpoint-only parameters removed by postprocess.
            raw = Tensor()
            raw.is_meta = True
            layer._parameters['raw_checkpoint_scale'] = raw
        fake = self.fake_torch()
        with patch.dict(sys.modules, {'torch': fake}):
            desc.prepare_reader_skeleton(model, manifest, contracts, identity)
        for name, layer in model.named_modules():
            self.assertNotIn('raw_checkpoint_scale', layer._parameters)
            for attr, layout in manifest['modules'][name]['parameters'].items():
                self.assertEqual(layer._parameters[attr].shape, tuple(layout['shape']))
                self.assertEqual(layer._parameters[attr].stride(), tuple(layout['stride']))
                self.assertTrue(layer._parameters[attr].is_meta)
        moe = dict(model.named_modules())['moe0']
        self.assertIn('w13_input_scale', moe._parameters)
        self.assertIsNone(moe._parameters['w13_input_scale'])

    def runtime_modules(self, foreign_alias=False):
        fake = self.fake_torch()
        model, manager, identity, manifest, contracts = self.exported_model()
        for _, layer in model.named_modules():
            qm = layer.quant_method
            qm.process_weights_after_loading = lambda _: (_ for _ in ()).throw(
                AssertionError('RO weight postprocess must never run'))
            if desc._kind(layer) != 'humming-moe': continue
            def config(layer):
                make = lambda: SimpleNamespace(scale=Tensor() if foreign_alias else None,
                    alpha_or_gscale=None, zp=None, bias=None)
                return SimpleNamespace(_w1=make(), _w2=make(),
                    w1_input_scale=None, w1_input_scale_2=None, w2_input_scale=None, w2_input_scale_2=None)
            qm.get_fused_moe_quant_config = config
            qm.moe = object()
            layer._expert_routing_tables = lambda: None
        def builder(**kwargs):
            expert = object.__new__(kwargs['experts_cls'])
            expert.locks = fake.zeros(1024, 'torch.int32', 'cuda:0')
            return SimpleNamespace(fused_experts=expert)
        def workspaces(model, manager):
            result = []
            for _, layer in model.named_modules():
                qm = layer.quant_method
                if desc._kind(layer) == 'humming-linear': owner = qm.kernel
                elif desc._kind(layer) == 'humming-moe': owner = qm.moe_kernel.fused_experts
                else: continue
                self.assertGreaterEqual(owner.locks.data_ptr(), 100000)
                result.append({'already_private': True})
            return result
        self.imports['vllm.model_executor.layers.quantization.utils.humming.moe'] = SimpleNamespace(
            make_humming_moe_kernel=builder)
        hook = SimpleNamespace(_pool_managers=lambda _: [manager], rebind_humming_locks=workspaces)
        return fake, hook, model, manager, manifest

    def test_reader_restores_all_runtime_descriptors_with_private_locks_and_no_weight_transform(self):
        fake, hook, model, manager, manifest = self.runtime_modules()
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(desc.importlib, 'import_module', side_effect=lambda name: self.imports[name]):
            counts = desc.restore_reader_runtime(model, manager, manifest)
        self.assertEqual(counts, {'humming-linear': 80, 'humming-moe': 40, 'cutlass-fp8': 2})

    def test_reader_rejects_moe_quant_descriptors_that_alias_other_tensors(self):
        fake, hook, model, manager, manifest = self.runtime_modules(foreign_alias=True)
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(desc.importlib, 'import_module', side_effect=lambda name: self.imports[name]):
            with self.assertRaisesRegex(ValueError, 'foreign tensor alias'):
                desc.restore_reader_runtime(model, manager, manifest)

    def attention_layer(self):
        class Scale(Tensor):
            dtype, shape = 'torch.float32', ()
            def __init__(self, value, device='cuda', pointer=20000):
                super().__init__(pointer)
                self.value, self.device = value, SimpleNamespace(type=device)
                self.is_cuda, self.is_meta = device == 'cuda', False
            def stride(self): return ()
            def numel(self): return 1
            def item(self): return self.value
        layer = cls(desc.ATTENTION_CLASS)()
        layer.quant_method = cls(desc.MODEL_OPT + ':ModelOptKVCacheMethod')()
        layer.impl = cls(desc.FLASHINFER_IMPL)()
        layer.impl.scale = 0.125
        layer.impl.sinks = layer.impl._sinks_source = None
        layer.impl.process_weights_after_loading = lambda _: (_ for _ in ()).throw(
            AssertionError('No attention callback is needed without sinks'))
        layer.kv_cache_dtype, layer.has_sink = 'fp8_e4m3', False
        layer.num_heads, layer.num_kv_heads = 16, 2
        layer.head_size = layer.head_size_v = 128
        layer.sliding_window, layer.dtype, layer.query_quant = (-1, -1), 'torch.bfloat16', None
        layer._parameters, layer._buffers = {}, {}
        contracts = {}
        for index, (attr, value) in enumerate(zip(desc.SCALE_BUFFERS, (0.25, 0.5, 0.75, 1.0))):
            tensor = Scale(value, pointer=20000 + 16 * index)
            setattr(layer, attr, tensor)
            layer._buffers[attr] = tensor
            setattr(layer, attr + '_float', value)
            contracts['attention.' + attr] = {'shape': [], 'stride': [], 'dtype': 'torch.float32',
                'allocation_id': 'a', 'offset_bytes': 128 + 4 * index, 'tensor_type': 'buffer'}
        layer._o_scale_float = None
        layer._k_scale_cpu, layer._v_scale_cpu = Scale(0.5, 'cpu'), Scale(0.75, 'cpu')
        manager = SimpleNamespace(mappings={1000: SimpleNamespace(aligned_size=4096, allocation_id='a')})
        hook = SimpleNamespace(_pool_managers=lambda _: [manager])
        return Scale, layer, manager, hook, contracts

    def test_attention_final_scale_and_host_state_exports_without_weight_mutation(self):
        Scale, layer, manager, hook, contracts = self.attention_layer()
        before = dict(layer._buffers)
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            runtime = desc._export_attention(layer, manager, 'attention', contracts)
        self.assertEqual(runtime['geometry']['sliding_window'], [-1, -1])
        self.assertEqual(runtime['host_floats']['_q_scale_float'], 0.25)
        self.assertEqual(runtime['host_tensors']['_k_scale_cpu']['device_type'], 'cpu')
        self.assertEqual(layer._buffers, before)

    def test_attention_restore_reads_private_buffers_and_recreates_host_copies_only(self):
        Scale, layer, manager, hook, contracts = self.attention_layer()
        before = dict(layer._buffers)
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            runtime = desc._export_attention(layer, manager, 'attention', contracts)
        layer._q_scale_float = 1.0
        layer._k_scale_cpu = Scale(1.0, 'cpu')
        fake = SimpleNamespace(float32='torch.float32', full=lambda shape, value, dtype, device:
            Scale(value, device if isinstance(device, str) else device.type, pointer=70000))
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            desc._restore_attention(layer, {'attention_runtime': runtime}, manager)
        self.assertEqual(layer._q_scale_float, 0.25)
        self.assertEqual(layer._k_scale_cpu.item(), 0.5)
        self.assertEqual(layer._v_scale_cpu.item(), 0.75)
        self.assertEqual(layer._buffers, before)

    def test_attention_refuses_shared_mutable_scale_and_unsupported_sinks(self):
        Scale, layer, manager, hook, contracts = self.attention_layer()
        layer._k_scale.pointer = 1100
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            with self.assertRaisesRegex(ValueError, 'aliases a GMS'):
                desc._export_attention(layer, manager, 'attention', contracts)
        layer.has_sink = True
        with self.assertRaisesRegex(ValueError, 'without sinks'): desc._kind(layer)

    def test_attention_buffer_contract_change_is_rejected(self):
        Scale, layer, manager, hook, contracts = self.attention_layer()
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            runtime = desc._export_attention(layer, manager, 'attention', contracts)
        row = {'kind': 'modelopt-attention', 'parameters': {}, 'attention_runtime': runtime}
        manifest = {'version': desc.VERSION, 'modules': {'attention': row}}
        desc.validate_tensor_contracts(manifest, contracts)
        wrong = copy.deepcopy(contracts)
        wrong['attention._k_scale']['allocation_id'] = 'foreign'
        with self.assertRaises(ValueError): desc.validate_tensor_contracts(manifest, wrong)

    def test_complete_model_can_export_supported_attention_as_reader_ready(self):
        Scale, layer, manager, hook, contracts = self.attention_layer()
        model, _, identity = self.complete_writer()
        modules = dict(model.named_modules())
        modules['attention-kv'] = layer
        model.named_modules = lambda: iter(modules.items())
        contracts = {name.replace('attention.', 'attention-kv.'): value for name, value in contracts.items()}
        with patch.dict(sys.modules, {'gpu_memory_service.integrations.vllm.workshop_humming': hook}):
            manifest = desc.export_runtime_manifest(model, manager, identity, contracts=contracts)
        self.assertTrue(manifest['reader_ready'])
        self.assertEqual(manifest['counts']['modelopt-attention'], 1)
        self.assertEqual(manifest['modules']['attention-kv']['parameters'], {})


if __name__ == '__main__': unittest.main()
