"""Independent review of plain optional None state for native Humming warmup."""
from tests.support import ROOT
import ast
from dataclasses import make_dataclass
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.shadow.writer_descriptors as writer
import demos.shadow.reader_descriptors as reader
import demos.shadow.reader_delta as delta
import tests.shadow.test_writer_role_contracts as fixtures

NAMES = {'e_score_correction_bias', 'w13_weight', 'w13_weight_scale', 'w13_weight_scale_2',
    'w2_weight', 'w2_weight_scale', 'w2_weight_scale_2'}
NATIVE = ROOT / 'results/workshop-shadow-native-replace-source-20261105-a1/sources/vllm/model_executor/utils.py'
MODELOPT = ROOT / 'results/shadow-writer-a6-remote-collected-a1/run/runtime-contract-sources/vllm/model_executor/layers/quantization/modelopt.py'
WARMUP = ROOT / 'results/workshop-shadow-mx-runtime-sources-20261105-a2/sources/vllm/model_executor/warmup/deep_gemm_warmup.py'
PACKET = ROOT / 'results/workshop-shadow-reader-v6-cpu-packet-20261105-a1'


def schema_class():
    cls = make_dataclass('HummingInputSchema', [('a_dtype', object), ('input_quant_mode', object),
        ('input_scale_dtype', object), ('input_scale_group_size', int), ('quant_method', str)])
    cls.__module__ = 'humming.schema.humming'
    cls.static_tensor_scale_name = None
    return cls


def fixture():
    schema = schema_class()
    params = {name: object() for name in NAMES}
    layer = SimpleNamespace(_parameters=params, _buffers={},
        input_schemas={name: schema(None, None, None, 0, 'humming') for name in ('w13', 'w2')})
    return layer, {'kind': 'humming-moe', 'parameters': dict(params), 'none_parameters': []}


class OptionalInputStateReviewTests(unittest.TestCase):
    def test_only_reader_state_function_and_exact_reader_delta_change_from_v4(self):
        before = (ROOT / 'demos/shadow/writer_descriptors.py').read_text()
        after = (ROOT / 'demos/shadow/reader_descriptors.py').read_text()
        proof = delta.validate_reader_delta(before, after)
        self.assertEqual(writer.VERSION, reader.VERSION)
        self.assertEqual(len(proof['unchanged_functions']), 29)
        self.assertEqual(proof['new_reader_functions'], ['restore_humming_optional_input_state'])
        old_ast, new_ast = ast.parse(before), ast.parse(after)
        for name in proof['unchanged_functions']:
            old = next(node for node in old_ast.body if isinstance(node, ast.FunctionDef) and node.name == name)
            new = next(node for node in new_ast.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.get_source_segment(before, old), ast.get_source_segment(after, new), name)

    def test_plain_none_creation_is_idempotent_and_preserves_exact_seven_registered_objects(self):
        layer, row = fixture()
        original = dict(layer._parameters)
        reader.restore_humming_optional_input_state(layer, row)
        reader.restore_humming_optional_input_state(layer, row)
        self.assertEqual(set(layer._parameters), NAMES)
        self.assertEqual(layer._buffers, {})
        for name, parameter in original.items(): self.assertIs(layer._parameters[name], parameter)
        for name in ('w13_input_scale', 'w2_input_scale'):
            self.assertIn(name, layer.__dict__)
            self.assertIs(layer.__dict__[name], None)
            self.assertNotIn(name, layer._parameters)
            self.assertNotIn(name, layer._buffers)

    def test_registered_buffer_non_none_or_inherited_input_state_is_never_replaced(self):
        for prefix in ('w13', 'w2'):
            for case in ('registered-none', 'registered-object', 'buffer-none', 'buffer-object', 'ordinary-object', 'inherited-none'):
                with self.subTest(prefix=prefix, case=case):
                    layer, row = fixture()
                    name = prefix + '_input_scale'
                    if case.startswith('registered'): layer._parameters[name] = None if case.endswith('none') else object()
                    elif case.startswith('buffer'): layer._buffers[name] = None if case.endswith('none') else object()
                    elif case == 'ordinary-object': setattr(layer, name, object())
                    else:
                        cls = type('Inherited', (), {name: None})
                        inherited = cls(); inherited.__dict__.update(layer.__dict__); layer = inherited
                    parameters, buffers = dict(layer._parameters), dict(layer._buffers)
                    with self.assertRaises(ValueError): reader.restore_humming_optional_input_state(layer, row)
                    self.assertEqual(layer._parameters, parameters)
                    self.assertEqual(layer._buffers, buffers)
                    for attr in ('w13_input_scale', 'w2_input_scale'):
                        if attr != name: self.assertNotIn(attr, layer.__dict__)

    def test_only_exact_disabled_schemas_are_admitted_and_validation_is_atomic(self):
        changes = [('a_dtype', object()), ('input_quant_mode', 'dynamic_group'), ('input_scale_dtype', object()),
            ('input_scale_group_size', 128), ('input_scale_group_size', False), ('input_scale_group_size', 0.0),
            ('static_tensor_scale_name', 'scale'), ('quant_method', 'other')]
        for prefix in ('w13', 'w2'):
            for field, value in changes:
                with self.subTest(prefix=prefix, field=field, value_type=type(value).__name__):
                    layer, row = fixture()
                    setattr(layer.input_schemas[prefix], field, value)
                    with self.assertRaises(ValueError): reader.restore_humming_optional_input_state(layer, row)
                    self.assertNotIn('w13_input_scale', layer.__dict__)
                    self.assertNotIn('w2_input_scale', layer.__dict__)
        layer, row = fixture()
        layer.input_schemas['w2'] = SimpleNamespace(**vars(layer.input_schemas['w2']), static_tensor_scale_name=None)
        with self.assertRaises(ValueError): reader.restore_humming_optional_input_state(layer, row)
        self.assertNotIn('w13_input_scale', layer.__dict__)

    def test_changed_parameter_inventory_or_optional_manifest_state_fails_before_mutation(self):
        for case in ('missing', 'extra', 'none-manifest', 'wrong-kind', 'none-parameter'):
            with self.subTest(case=case):
                layer, row = fixture()
                if case == 'missing': del layer._parameters['w2_weight']
                elif case == 'extra': layer._parameters['unexpected'] = object()
                elif case == 'none-manifest': row['none_parameters'] = ['w13_input_scale']
                elif case == 'wrong-kind': row['kind'] = 'other'
                elif case == 'none-parameter': layer._parameters['w13_input_scale'] = None
                with self.assertRaises(ValueError): reader.restore_humming_optional_input_state(layer, row)
                self.assertNotIn('w13_input_scale', layer.__dict__)
                self.assertNotIn('w2_input_scale', layer.__dict__)

    @unittest.skipUnless(NATIVE.is_file() and MODELOPT.is_file(), 'Pinned native source is local qualification evidence')
    def test_actual_imported_native_none_branch_allocates_nothing_and_matches_ordinary_state(self):
        tree = ast.parse(MODELOPT.read_text())
        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and
            any(alias.name == 'replace_parameter' for alias in node.names)]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].module, 'vllm.model_executor.utils')
        native = next(node for node in ast.parse(NATIVE.read_text()).body
            if isinstance(node, ast.FunctionDef) and node.name == 'replace_parameter')
        program = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), native], type_ignores=[])
        class NoTorch:
            def __getattr__(self, name): raise AssertionError('Native None branch touched Torch: ' + name)
        namespace = {'torch': NoTorch()}
        exec(compile(ast.fix_missing_locations(program), 'pinned-native-replace-none', 'exec'), namespace)
        layer, row = fixture()
        before = dict(layer._parameters)
        namespace['replace_parameter'](layer, 'w13_input_scale', None)
        namespace['replace_parameter'](layer, 'w2_input_scale', None)
        self.assertEqual(layer._parameters, before)
        self.assertEqual(layer._buffers, {})
        self.assertIs(layer.__dict__['w13_input_scale'], None)
        self.assertIs(layer.__dict__['w2_input_scale'], None)

    @unittest.skipUnless(MODELOPT.is_file() and WARMUP.is_file(), 'Pinned generic/warmup source is local qualification evidence')
    def test_actual_generic_wrapper_and_native_predicate_count_reproduce_failure_then_zero_without_skip(self):
        modelopt = ast.parse(MODELOPT.read_text())
        method_class = next(node for node in modelopt.body if isinstance(node, ast.ClassDef) and node.name == 'ModelOptNvFp4FusedMoE')
        generic = next(node for node in method_class.body if isinstance(node, ast.FunctionDef) and node.name == 'get_fused_moe_quant_config')
        names = {'_deep_gemm_linear_data', '_fused_moe_grouped_gemm_may_use_deep_gemm', '_count_warmup_iterations'}
        native = [node for node in ast.parse(WARMUP.read_text()).body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in native}, names)
        calls = []
        def config(**kwargs):
            calls.append(kwargs)
            self.assertIs(kwargs['a13_scale'], None)
            self.assertIs(kwargs['a2_scale'], None)
            return SimpleNamespace(quant_dtype=None, block_shape=None)
        def forbidden(*args): raise AssertionError('No GEMM data extraction/allocation is needed after the native dtype filter')
        Runner, Linear = type('MoERunner', (), {}), type('DeepGemmFp8BlockScaledMMKernel', (), {})
        namespace = {'torch': SimpleNamespace(float8_e4m3fn='fp8'),
            'envs': SimpleNamespace(VLLM_USE_DEEP_GEMM=True, VLLM_MOE_USE_DEEP_GEMM=True),
            'MoERunner': Runner, 'DeepGemmFp8BlockScaledMMKernel': Linear,
            'make_nvfp4_moe_quant_config': config, 'FP8_GEMM_NT_WARMUP_CACHE': set(),
            'GROUPED_FP8_GEMM_NT_CONTIGUOUS_WARMUP_CACHE': set(),
            'get_mk_alignment_for_contiguous_layout': forbidden, '_extract_data_from_fused_moe_module': forbidden,
            '_get_fp8_gemm_nt_m_values': forbidden, '_get_grouped_gemm_params': forbidden}
        program = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
            generic] + native, type_ignores=[])
        exec(compile(ast.fix_missing_locations(program), 'pinned-generic-and-native-warmup', 'exec'), namespace)
        layer, row = fixture()
        for name in NAMES: setattr(layer, name, layer._parameters[name])
        method = SimpleNamespace(nvfp4_backend='HUMMING', use_a16=False)
        method.get_fused_moe_quant_config = lambda layer: namespace['get_fused_moe_quant_config'](method, layer)
        runner = Runner(); runner._quant_method, runner.routed_experts = method, layer
        model = SimpleNamespace(modules=lambda: iter([runner]))
        predicate, count = namespace['_fused_moe_grouped_gemm_may_use_deep_gemm'], namespace['_count_warmup_iterations']
        with self.assertRaisesRegex(AttributeError, 'w13_input_scale'): predicate(runner)
        with self.assertRaisesRegex(AttributeError, 'w13_input_scale'): count(model, 1024)
        self.assertEqual(calls, [])
        before = dict(layer._parameters)
        reader.restore_humming_optional_input_state(layer, row)
        self.assertIs(predicate(runner), False)
        self.assertEqual(count(model, 1024), 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(layer._parameters, before)

    def test_full_reader_restoration_keeps_seven_parameters_aliases_and_all_other_backends(self):
        review = fixtures.IndependentRoleReviewTests(); review.setUp()
        model, modules, manager, manifest, fake, hook = review.runtime()
        schema = schema_class()
        review.legacy.imports['humming.schema.humming'].HummingInputSchema = schema
        calls = []
        for name, layer in modules.items():
            if reader._kind(layer) != 'humming-moe': continue
            layer._buffers = {}
            layer._parameters.pop('w13_input_scale'); layer._parameters.pop('w2_input_scale')
            for attr in ('w13_weight_scale', 'w13_weight_scale_2', 'w2_weight_scale', 'w2_weight_scale_2'):
                tensor = fixtures.Tensor()
                layer._parameters[attr] = tensor
                setattr(layer, attr, tensor)
            manifest['modules'][name]['none_parameters'] = []
            manifest['modules'][name]['parameters'] = {attr: dict(reader.parameter_layout(layer, name, attr, tensor, modules),
                **reader.allocation_identity(tensor, manager)) for attr, tensor in layer._parameters.items()}
            manifest['modules'][name]['input_schemas'] = reader.encode({prefix: schema(None, None, None, 0, 'humming') for prefix in ('w13', 'w2')})
            layer.quant_method.get_fused_moe_quant_config = lambda *_: self.fail('Generic checkpoint callback must not replace v5 builder')
        def builder(layer, **kwargs):
            calls.append(layer)
            descriptor = lambda prefix: SimpleNamespace(scale=getattr(layer, prefix + '_weight_scale'),
                alpha_or_gscale=getattr(layer, prefix + '_weight_scale_2'), zp=None, bias=None)
            return SimpleNamespace(_w1=descriptor('w13'), _w2=descriptor('w2'), w1_input_scale=None,
                w1_input_scale_2=None, w2_input_scale=None, w2_input_scale_2=None)
        review.legacy.imports['vllm.model_executor.layers.quantization.utils.humming.moe'].get_humming_moe_quant_config = builder
        before = {name: dict(layer._parameters) for name, layer in modules.items()}
        with patch.dict(sys.modules, {'torch': fake, 'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(reader.importlib, 'import_module', side_effect=lambda key: review.legacy.imports[key]):
            self.assertEqual(reader.restore_reader_runtime(model, manager, manifest), manifest['counts'])
        self.assertEqual(len(calls), 40)
        for name, layer in modules.items():
            for attr, parameter in before[name].items(): self.assertIs(layer._parameters[attr], parameter)
            if reader._kind(layer) == 'humming-moe':
                self.assertEqual(set(layer._parameters), NAMES)
                self.assertIs(layer.__dict__['w13_input_scale'], None)
                self.assertIs(layer.__dict__['w2_input_scale'], None)

    @unittest.skipUnless((PACKET / 'fixtures.json').is_file(), 'Actual v6 CPU packet is local qualification evidence')
    def test_cpu_packet_rebuilds_exactly_from_accepted_roles_and_exact_image_source_receipts(self):
        import demos.shadow.reader_cpu as cpu
        packet = json.loads((PACKET / 'fixtures.json').read_text())
        self.assertEqual(cpu.build_packet(packet['writer_basis']), packet)
        for name, value in json.loads((PACKET / 'packet-manifest.json').read_text()).items():
            content = (PACKET / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), value['sha256'])
            self.assertEqual(len(content), value['bytes'])
        self.assertEqual((PACKET / 'cpu-program.py').read_text(), cpu.PROGRAM)
        self.assertEqual((PACKET / 'workshop_descriptors.py').read_text(), (ROOT / 'demos/shadow/reader_descriptors.py').read_text())
        roles = [(value['rank'], value['owner']) for group in packet['runtime_groups'] for value in group['covered_roles']]
        self.assertEqual(len(roles), 80)
        self.assertEqual(set(roles), {(rank, owner) for rank in (0, 1) for owner in reader.ROUTING_BIAS_OWNERS})
        self.assertEqual(len(packet['source_contracts']), 7)
        self.assertEqual(set(packet['extra_source_receipts']), set(cpu.EXTRA_SOURCES))

    @unittest.skipUnless((PACKET / 'fixtures.json').is_file(), 'Actual v6 CPU packet is local qualification evidence')
    def test_wrong_native_source_receipt_image_missing_file_or_bytes_fail_before_packet_output(self):
        import demos.shadow.reader_cpu as cpu
        packet = json.loads((PACKET / 'fixtures.json').read_text())
        name, (source, expected) = next(iter(cpu.EXTRA_SOURCES.items()))
        for case in ('wrong-image', 'missing-source', 'wrong-bytes'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                receipt = json.loads((source / 'result.json').read_text())
                content = (source / 'sources' / name).read_bytes()
                if case == 'wrong-image': receipt['image_id'] = 'other-image'
                elif case == 'missing-source': receipt['missing'] = [name]
                elif case == 'wrong-bytes': content += b'\n# changed native source\n'
                (directory / 'result.json').write_text(json.dumps(receipt))
                target = directory / 'sources' / name
                target.parent.mkdir(parents=True); target.write_bytes(content)
                output = directory / 'uncreated-output'
                with patch.object(cpu, 'EXTRA_SOURCES', {name: (directory, expected)}), self.assertRaises(ValueError):
                    cpu.prepare_packet(packet['writer_basis'], output)
                self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
