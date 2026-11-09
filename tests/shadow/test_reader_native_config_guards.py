"""Independent offline review of the isolated final-layout Humming reader fix."""
from tests.support import ROOT
import ast
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.source_paths import source_path
import demos.shadow.writer_descriptors as writer
import demos.shadow.compat.descriptor_native_config as reader
import demos.shadow.compat.native_config_delta as delta
import demos.shadow.reader_packet as cpu
import tests.shadow.test_writer_role_contracts as fixtures

PACKET = ROOT / 'results/workshop-shadow-reader-v5-cpu-packet-20261105-a1'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReaderV5ReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = fixtures.IndependentRoleReviewTests()
        self.fixtures.setUp()

    def source(self, name): return (source_path(name, root=ROOT)).read_text()

    def runtime(self, builder_error=None):
        model, modules, manager, manifest, fake, hook = self.fixtures.runtime()
        saved, calls = {}, []
        for layer in modules.values():
            if reader._kind(layer) != 'humming-moe': continue
            saved[id(layer)] = layer.quant_method.get_fused_moe_quant_config
            layer.quant_method.get_fused_moe_quant_config = lambda *_: self.fail('Checkpoint wrapper invoked')
        humming = self.fixtures.legacy.imports['vllm.model_executor.layers.quantization.utils.humming.moe']
        def builder(layer, **kwargs):
            calls.append((layer, kwargs))
            if builder_error: raise builder_error
            return saved[id(layer)](layer)
        humming.get_humming_moe_quant_config = builder
        return model, modules, manager, manifest, fake, hook, calls

    def restore(self, runtime):
        model, modules, manager, manifest, fake, hook, calls = runtime
        with patch.dict(sys.modules, {'torch': fake,
                'gpu_memory_service.integrations.vllm.workshop_humming': hook}), \
                patch.object(reader.importlib, 'import_module', side_effect=lambda name: self.fixtures.legacy.imports[name]):
            return reader.restore_reader_runtime(model, manager, manifest)

    def test_whole_source_and_all_29_other_functions_are_exactly_preserved(self):
        old = self.source('workshop_shadow_descriptors_v4.py')
        new = self.source('workshop_shadow_descriptors_v5.py')
        self.assertEqual(new.replace(delta.REVISION_LINE, '', 1).replace(delta.NEW, delta.OLD, 1), old)
        before, after = ast.parse(old), ast.parse(new)
        functions = {n.name: n for n in before.body if isinstance(n, ast.FunctionDef)}
        actual = {n.name: n for n in after.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(functions), set(actual))
        self.assertEqual(len(functions) - 1, 29)
        for name in functions.keys() - {'restore_reader_runtime'}:
            self.assertEqual(ast.get_source_segment(old, functions[name]), ast.get_source_segment(new, actual[name]), name)
        self.assertEqual(writer.VERSION, reader.VERSION)
        self.assertEqual(delta.validate_reader_delta(old, new)['reader_helper_sha256'], sha(ROOT / 'demos/shadow/compat/descriptor_native_config.py'))

    def test_delta_refuses_any_guard_format_lifecycle_or_additional_reader_edit(self):
        old, new = self.source('workshop_shadow_descriptors_v4.py'), self.source('workshop_shadow_descriptors_v5.py')
        changes = (
            ("'requires_grad': False", "'requires_grad': True"),
            ("'torch.uint8', 'torch.int32'", "'torch.float64', 'torch.int32'"),
            ('if len(matches) != 1:', 'if False:'),
            ('if require_object_alias and gate_tensor is not tensor:', 'if False:'),
            ('    _pool_managers(manager)  # Refuse before allocating any reader workspace.',
             '    pass  # No private workspace guard'),
            ("if value.get('version') != VERSION", "if False"),
            ('gemm1_beta=getattr(layer, \'swiglu_beta\', None)', 'gemm1_beta=None'),
            ('# Deliberately DO NOT call any process_weights_after_loading hook.',
             'qm.process_weights_after_loading(layer)'),
        )
        for before, after in changes:
            self.assertIn(before, new)
            with self.subTest(guard=before), self.assertRaises(ValueError):
                delta.validate_reader_delta(old, new.replace(before, after, 1))
        with self.assertRaises(ValueError): delta.validate_reader_delta(old, new + '\n# extra source drift\n')

    def test_reader_uses_native_builder_for_missing_default_and_nondefault_swiglu_fields(self):
        for values in ((None, None, None), (0.0, 0.0, 0.0), (0.25, 1.5, 7.0)):
            with self.subTest(values=values):
                runtime = self.runtime()
                model, modules, manager, manifest, fake, hook, calls = runtime
                before = {id(t): (t.shape, t.stride(), t.dtype, t.requires_grad) for layer in modules.values()
                    for t in layer._parameters.values() if t is not None}
                for layer in modules.values():
                    if reader._kind(layer) != 'humming-moe': continue
                    self.assertFalse(hasattr(layer, 'w13_input_scale'))
                    self.assertFalse(hasattr(layer, 'w2_input_scale'))
                    if values != (None, None, None):
                        layer.swiglu_alpha, layer.swiglu_beta, layer.swiglu_limit = values
                self.assertEqual(self.restore(runtime), manifest['counts'])
                self.assertEqual(len(calls), 40)
                self.assertTrue(all(kwargs == dict(zip(('gemm1_alpha', 'gemm1_beta', 'gemm1_clamp_limit'), values))
                    for layer, kwargs in calls))
                after = {id(t): (t.shape, t.stride(), t.dtype, t.requires_grad) for layer in modules.values()
                    for t in layer._parameters.values() if t is not None}
                self.assertEqual(after, before)
                self.assertFalse(any(hasattr(layer, 'w13_input_scale') or hasattr(layer, 'w2_input_scale') for layer in modules.values()))

    def test_all_postimport_alias_layout_gradient_and_workspace_guards_still_fail(self):
        for case in ('ordinary-grad', 'ordinary-dtype', 'role-grad', 'role-pointer', 'gate-pointer', 'gate-dtype',
                'cuda', 'optional', 'foreign-scale', 'foreign-input', 'workspace'):
            with self.subTest(case=case):
                runtime = self.runtime()
                model, modules, manager, manifest, fake, hook, calls = runtime
                owner = sorted(reader.ROUTING_BIAS_OWNERS)[0]
                layer = modules[owner]
                bias = layer._parameters['e_score_correction_bias']
                if case == 'ordinary-grad': modules['linear0']._parameters['weight'].requires_grad = True
                elif case == 'ordinary-dtype': modules['linear0']._parameters['weight'].dtype = 'torch.float8_e8m0fnu'
                elif case == 'role-grad': bias.requires_grad = False
                elif case == 'role-pointer': bias.pointer += 4
                elif case in ('gate-pointer', 'gate-dtype'):
                    gate = reader.routing_bias_role(owner, 'e_score_correction_bias')['gate_parameter'].rsplit('.', 1)[0]
                    parameter = fixtures.Parameter()
                    if case == 'gate-pointer': parameter.pointer += 4
                    else: parameter.dtype = 'torch.bfloat16'
                    modules[gate]._parameters['e_score_correction_bias'] = parameter
                elif case == 'cuda': bias.is_cuda = False
                elif case == 'optional': layer._parameters['w13_input_scale'] = fixtures.Tensor()
                elif case in ('foreign-scale', 'foreign-input'):
                    humming = self.fixtures.legacy.imports['vllm.model_executor.layers.quantization.utils.humming.moe']
                    original = humming.get_humming_moe_quant_config
                    def foreign(layer, **kwargs):
                        config = original(layer, **kwargs)
                        if case == 'foreign-scale': config._w1.scale = object()
                        else: config.w1_input_scale = object()
                        return config
                    humming.get_humming_moe_quant_config = foreign
                elif case == 'workspace': hook.rebind_humming_locks = lambda *_: [{'already_private': False}]
                with self.assertRaises(ValueError): self.restore(runtime)

    def test_native_builder_error_has_no_checkpoint_or_weight_transform_fallback(self):
        error = RuntimeError('sentinel native builder failure')
        runtime = self.runtime(error)
        with self.assertRaisesRegex(RuntimeError, 'sentinel native builder failure'): self.restore(runtime)
        self.assertEqual(len(runtime[-1]), 1)

    @unittest.skipUnless((PACKET / 'fixtures.json').is_file(), 'Actual a6 CPU packet is local qualification evidence')
    def test_actual_packet_binds_all_80_unique_roles_to_exact_final_layout_and_source_bytes(self):
        packet = json.loads((PACKET / 'fixtures.json').read_text())
        for name, value in json.loads((PACKET / 'packet-manifest.json').read_text()).items():
            self.assertEqual(sha(PACKET / name), value['sha256'])
            self.assertEqual((PACKET / name).stat().st_size, value['bytes'])
        self.assertEqual((PACKET / 'cpu-program.py').read_text(), cpu.PROGRAM)
        self.assertEqual((PACKET / 'workshop_descriptors.py').read_text(), self.source('workshop_shadow_descriptors_v5.py'))
        basis = Path(packet['writer_basis'])
        self.assertEqual(sha(basis / 'descriptor-writer-spec.json'), packet['writer_spec_sha256'])
        for name, expected in packet['source_contracts'].items():
            self.assertEqual(sha(basis / 'runtime-contract-sources' / name), expected)
        manifests = {}
        for rank in ('0', '1'):
            path = basis / 'rank-manifests' / ('rank-' + rank + '.json')
            self.assertEqual(sha(path), packet['rank_manifest_sha256'][rank])
            manifests[rank] = json.loads(path.read_text())
        observed = []
        expected_params = {'e_score_correction_bias', 'w13_weight', 'w13_weight_scale', 'w13_weight_scale_2',
            'w2_weight', 'w2_weight_scale', 'w2_weight_scale_2'}
        for group in packet['runtime_groups']:
            signature = hashlib.sha256(json.dumps(group['fixture'], sort_keys=True).encode()).hexdigest()
            self.assertEqual(signature, group['runtime_signature_sha256'])
            for role in group['covered_roles']:
                observed.append((role['rank'], role['owner']))
                row = manifests[str(role['rank'])]['modules'][role['owner']]
                self.assertEqual(set(row['parameters']), expected_params)
                self.assertEqual(row['none_parameters'], [])
                normalized = {key: row[key] for key in ('weight_schemas', 'input_schemas', 'humming_configs')}
                normalized['parameters'] = {name: {key: layout[key] for key in
                    ('shape', 'stride', 'dtype', 'requires_grad', 'attrs')} for name, layout in row['parameters'].items()}
                self.assertEqual(normalized, group['fixture'])
        self.assertEqual(len(observed), 80)
        self.assertEqual(set(observed), {(rank, owner) for rank in (0, 1) for owner in reader.ROUTING_BIAS_OWNERS})

    @unittest.skipUnless((PACKET / 'fixtures.json').is_file(), 'Actual a6 CPU packet is local qualification evidence')
    def test_packet_preparation_refuses_source_rank_flag_or_checkpoint_layout_drift_before_output(self):
        packet = json.loads((PACKET / 'fixtures.json').read_text())
        original = Path(packet['writer_basis'])
        files = ['descriptor-writer-spec.json', 'workshop_descriptors.py',
            'rank-manifests/rank-0.json', 'rank-manifests/rank-1.json'] + [
                'runtime-contract-sources/' + name for name in packet['source_contracts']]
        for case in ('source', 'version', 'raw-checkpoint-param', 'gradient-flag', 'missing-rank'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                basis, output = Path(directory) / 'basis', Path(directory) / 'output'
                for name in files:
                    target = basis / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(original / name, target)
                if case == 'source':
                    (basis / 'runtime-contract-sources' / next(iter(packet['source_contracts']))).write_text('changed source')
                elif case == 'missing-rank': (basis / 'rank-manifests/rank-1.json').unlink()
                else:
                    path = basis / 'rank-manifests/rank-0.json'
                    manifest = json.loads(path.read_text())
                    owner = sorted(reader.ROUTING_BIAS_OWNERS)[0]
                    if case == 'version': manifest['version'] = 'unreviewed'
                    elif case == 'gradient-flag':
                        manifest['modules'][owner]['parameters']['e_score_correction_bias']['requires_grad'] = False
                    elif case == 'raw-checkpoint-param':
                        manifest['modules'][owner]['parameters']['w13_input_scale'] = {'unexpected': True}
                    path.write_text(json.dumps(manifest))
                with redirect_stdout(io.StringIO()), self.assertRaises((ValueError, OSError)):
                    cpu.prepare_packet(basis, output)
                self.assertFalse(output.exists())

    @unittest.skipUnless((PACKET / 'fixtures.json').is_file(), 'Actual a6 CPU packet is local qualification evidence')
    def test_pinned_oracle_uses_the_native_builder_while_generic_wrapper_reads_missing_raw_attrs(self):
        packet = json.loads((PACKET / 'fixtures.json').read_text())
        source = Path(packet['writer_basis']) / 'runtime-contract-sources/vllm/model_executor/layers'
        oracle_tree = ast.parse((source / 'fused_moe/oracle/nvfp4.py').read_text())
        factory = next(n for n in oracle_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_nvfp4_moe_quant_config')
        branch = next(n for n in factory.body if isinstance(n, ast.If) and ast.unparse(n.test) == 'backend == NvFp4MoeBackend.HUMMING')
        native = next(n.value for n in branch.body if isinstance(n, ast.Return))
        self.assertEqual(ast.unparse(native.func), 'get_humming_moe_quant_config')
        self.assertEqual({k.arg: ast.unparse(k.value) for k in native.keywords}, {
            'gemm1_alpha': "getattr(layer, 'swiglu_alpha', None)",
            'gemm1_beta': "getattr(layer, 'swiglu_beta', None)", 'gemm1_clamp_limit': 'swiglu_limit'})
        modelopt = ast.parse((source / 'quantization/modelopt.py').read_text())
        cls = next(n for n in modelopt.body if isinstance(n, ast.ClassDef) and n.name == 'ModelOptNvFp4FusedMoE')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'get_fused_moe_quant_config')
        eager_attrs = {ast.unparse(n) for n in ast.walk(method) if isinstance(n, ast.Attribute)}
        self.assertTrue({'layer.w13_input_scale', 'layer.w2_input_scale'} <= eager_attrs)


if __name__ == '__main__': unittest.main()
