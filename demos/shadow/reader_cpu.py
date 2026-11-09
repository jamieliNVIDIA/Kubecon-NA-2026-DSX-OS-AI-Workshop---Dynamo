"""Build a reader-only native optional-state CPU preflight from accepted v4 data.

This writes offline inputs only. The root executor runs PROGRAM in the pinned
image using the existing bounded cpu_probe. CUDA must stay uninitialized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import demos.shadow.reader_packet as v5
from demos.shadow.reader_delta import validate_reader_delta

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'results/workshop-shadow-native-replace-source-20261105-a1'
WARMUP = ROOT / 'results/workshop-shadow-mx-runtime-sources-20261105-a2'
EXTRA_SOURCES = {
    'vllm/model_executor/utils.py': (NATIVE, '9d7d6bee0331cbac232a0f542096d779e28a7c158d092afe3756317395f4b46d'),
    'vllm/model_executor/warmup/deep_gemm_warmup.py': (WARMUP, 'e8ce6642ea5266805aa8a5c4edbbca562fed5bcd4d3013f268a061710c937814'),
    'vllm/model_executor/warmup/kernel_warmup.py': (WARMUP, 'cd6e80bbee0103ac6faa568b4da1ac85d2d720bc4743d9c958779a932f0f292a'),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_packet(basis):
    packet = v5.build_packet(basis)
    basis = Path(basis).resolve()
    spec = json.loads((basis / 'descriptor-writer-spec.json').read_text())
    candidate = (ROOT / 'demos/shadow/reader_descriptors.py').read_text()
    packet['reader_delta'] = validate_reader_delta((basis / 'workshop_descriptors.py').read_text(), candidate)
    receipts = {}
    for name, (directory, expected) in EXTRA_SOURCES.items():
        receipt = json.loads((directory / 'result.json').read_text())
        if (receipt['source_sha256'][name] != expected or receipt['missing'] or
                receipt['image_id'].rsplit('@sha256:', 1)[-1] != spec['descriptor_identity']['image_sha256'] or
                digest((directory / 'sources' / name).read_bytes()) != expected):
            raise ValueError('Native helper/warmup source receipt is not the accepted exact image.')
        packet['source_contracts'][name] = expected
        receipts[name] = {'receipt_sha256': digest((directory / 'result.json').read_bytes()),
                         'image_id': receipt['image_id']}
    packet['extra_source_receipts'] = receipts
    packet['scope'] = ('Actual final seven-parameter schemas plus source-prescribed ordinary None state, '
        'generic ModelOpt metadata callback and native DeepGEMM warmup selection/count; CPU only, no GPU qualification')
    return packet


def prepare_packet(basis, output):
    packet, output = build_packet(basis), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures.json').write_text(json.dumps(packet, indent=2, sort_keys=True) + '\n')
    (output / 'reader-delta.json').write_text(json.dumps(packet['reader_delta'], indent=2) + '\n')
    (output / 'workshop_descriptors.py').write_text((ROOT / 'demos/shadow/reader_descriptors.py').read_text())
    (output / 'cpu-program.py').write_text(PROGRAM)
    (output / 'packet-manifest.json').write_text(json.dumps({
        path.name: {'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())}
        for path in output.iterdir()}, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'runtime_groups': len(packet['runtime_groups']),
        'covered_roles': packet['covered_roles'],
        'reader_helper_sha256': packet['reader_delta']['reader_helper_sha256'],
        'cpu_program_sha256': digest(PROGRAM.encode()), 'live_actions': False}, indent=2))


PROGRAM = r'''import ast,base64,hashlib,importlib,importlib.metadata as metadata,json,os,types
from pathlib import Path
import torch
assert not torch.cuda.is_initialized()
source=base64.b64decode(os.environ['DESCRIPTOR_SOURCE_B64']).decode()
assert hashlib.sha256(source.encode()).hexdigest()==os.environ['DESCRIPTOR_SOURCE_SHA256']
raw_packet=base64.b64decode(os.environ['MOE_PACKET_B64'])
assert hashlib.sha256(raw_packet).hexdigest()==os.environ['MOE_PACKET_SHA256']
packet=json.loads(raw_packet)
assert packet['schema']==1 and packet['covered_roles']==80
assert packet['reader_delta']['reader_helper_sha256']==hashlib.sha256(source.encode()).hexdigest()
candidate=types.ModuleType('actual_humming_reader_v6_cpu')
exec(compile(source,'actual_humming_reader_v6_cpu.py','exec'),candidate.__dict__)
assert candidate.VERSION==packet['descriptor_version']
assert candidate.READER_ADAPTER_REVISION==packet['reader_delta']['reader_adapter_revision']
root=Path(metadata.distribution('vllm').locate_file(''))
source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in packet['source_contracts']}
assert source_hashes==packet['source_contracts']

def native_function(path,name,globals_):
    tree=ast.parse((root/path).read_text())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
    assert not function.decorator_list
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),function],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(root/path)+'::'+name,'exec'),globals_)
    return globals_[name]

modelopt_path='vllm/model_executor/layers/quantization/modelopt.py'
modelopt_tree=ast.parse((root/modelopt_path).read_text())
imports=[node for node in modelopt_tree.body if isinstance(node,ast.ImportFrom) and
    any(alias.name=='replace_parameter' for alias in node.names)]
assert len(imports)==1 and imports[0].module=='vllm.model_executor.utils'
native_replace_globals={'torch':torch}
native_replace=native_function('vllm/model_executor/utils.py','replace_parameter',native_replace_globals)

oracle=importlib.import_module('vllm.model_executor.layers.fused_moe.oracle.nvfp4')
modelopt=importlib.import_module('vllm.model_executor.layers.quantization.modelopt')
humming=importlib.import_module('vllm.model_executor.layers.quantization.utils.humming.moe')
fused_moe=importlib.import_module('vllm.model_executor.layers.fused_moe')
RoutedExperts=importlib.import_module('vllm.model_executor.layers.fused_moe.routed_experts').RoutedExperts
MoERunner=fused_moe.MoERunner
ModelOpt=modelopt.ModelOptNvFp4FusedMoE
assert not torch.cuda.is_initialized()

oracle_tree=ast.parse((root/'vllm/model_executor/layers/fused_moe/oracle/nvfp4.py').read_text())
factory=next(node for node in oracle_tree.body if isinstance(node,ast.FunctionDef) and node.name=='make_nvfp4_moe_quant_config')
branch=next(node for node in factory.body if isinstance(node,ast.If) and ast.unparse(node.test)=='backend == NvFp4MoeBackend.HUMMING')
native_call=next(node.value for node in branch.body if isinstance(node,ast.Return))
assert ast.unparse(native_call.func)=='get_humming_moe_quant_config'
assert [ast.unparse(arg) for arg in native_call.args]==['layer']
assert {keyword.arg:ast.unparse(keyword.value) for keyword in native_call.keywords}=={
 'gemm1_alpha':"getattr(layer, 'swiglu_alpha', None)",
 'gemm1_beta':"getattr(layer, 'swiglu_beta', None)",
 'gemm1_clamp_limit':'swiglu_limit'}

helper_ast=ast.parse(source)
restore=next(node for node in helper_ast.body if isinstance(node,ast.FunctionDef) and node.name=='restore_reader_runtime')
callback=[node for node in ast.walk(restore) if isinstance(node,ast.Assign) and any(
    isinstance(target,ast.Name) and target.id=='build_quant_config' or
    isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='qm'
      and target.attr=='moe_quant_config' for target in node.targets)]
assert len(callback)==2
callback_program=compile(ast.Module(body=callback,type_ignores=[]),'frozen-reader-v6-callback','exec')
assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and
    node.func.id=='restore_humming_optional_input_state' for node in ast.walk(restore))

def forbidden(*args,**kwargs): raise AssertionError('Weight transform, kernel, or unexpected hardware path executed')
for name in ('convert_to_humming_moe_kernel_format','_prepare_and_transform_sublayer',
             '_replace_layer_parameters','make_humming_moe_kernel'):
    assert hasattr(humming,name),name
    setattr(humming,name,forbidden)
for name in ('convert_to_nvfp4_moe_kernel_format','make_nvfp4_moe_kernel'):
    assert hasattr(modelopt,name),name
    setattr(modelopt,name,forbidden)

# Execute the unmodified installed native metadata bodies, using real runner,
# expert, quant-method and quant-config classes. The CUDA kernel selection
# helpers are explicit tripwires: the disabled Humming schemas must return
# before alignment, shape generation, workspace or kernel paths are reached.
warmup_path='vllm/model_executor/warmup/deep_gemm_warmup.py'
class NeverLinearProvider: pass
warmup={'torch':torch,'MoERunner':MoERunner,
    'envs':types.SimpleNamespace(VLLM_USE_DEEP_GEMM=True,VLLM_MOE_USE_DEEP_GEMM=True),
    'DeepGemmFp8BlockScaledMMKernel':NeverLinearProvider,
    'DeepGemmExperts':type('NeverDeepGemmExpert',(),{}),
    'TritonOrDeepGemmExperts':type('NeverTritonDeepGemmExpert',(),{}),
    'FP8_GEMM_NT_WARMUP_CACHE':set(),'GROUPED_FP8_GEMM_NT_CONTIGUOUS_WARMUP_CACHE':set(),
    'get_mk_alignment_for_contiguous_layout':forbidden,
    '_get_fp8_gemm_nt_m_values':forbidden,'_extract_data_from_fused_moe_module':forbidden,
    '_get_grouped_gemm_params':forbidden}
for name in ('_deep_gemm_linear_data','_fused_moe_grouped_gemm_may_use_deep_gemm','_count_warmup_iterations'):
    native_function(warmup_path,name,warmup)
kernel_tree=ast.parse((root/'vllm/model_executor/warmup/kernel_warmup.py').read_text())
assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='deep_gemm_warmup'
    for node in ast.walk(kernel_tree))

def layout_state(layer):
    return {name:(id(tensor),tuple(tensor.shape),tuple(tensor.stride()),str(tensor.dtype),tensor.requires_grad)
        for name,tensor in layer._parameters.items()}

def fixture_layer(fixture,swiglu):
    layer=RoutedExperts.__new__(RoutedExperts);torch.nn.Module.__init__(layer)
    for name,layout in fixture['parameters'].items():
        tensor=torch.empty_strided(layout['shape'],layout['stride'],
            dtype=getattr(torch,layout['dtype'].removeprefix('torch.')),device='meta')
        param=torch.nn.Parameter(tensor,requires_grad=layout['requires_grad'])
        for key,value in layout['attrs'].items():setattr(param,key,value)
        layer.register_parameter(name,param)
    layer.weight_schemas=candidate.decode(fixture['weight_schemas'])
    layer.input_schemas=candidate.decode(fixture['input_schemas'])
    layer.humming_configs=candidate.decode(fixture['humming_configs'])
    if swiglu is not None: layer.swiglu_alpha,layer.swiglu_beta,layer.swiglu_limit=swiglu
    qm=ModelOpt.__new__(ModelOpt)
    qm.nvfp4_backend=oracle.NvFp4MoeBackend.HUMMING
    qm.use_a16=False
    layer.quant_method=qm
    runner=MoERunner.__new__(MoERunner);torch.nn.Module.__init__(runner)
    runner.routed_experts=layer
    assert runner._quant_method is qm
    return layer,qm,runner

results=[]
for group in packet['runtime_groups']:
    fixture=group['fixture'];assert len(fixture['parameters'])==7
    row={'kind':'humming-moe','parameters':fixture['parameters'],'none_parameters':[]}
    for swiglu in (None,(0.0,0.0,0.0),(0.25,1.5,7.0)):
        layer,qm,runner=fixture_layer(fixture,swiglu)
        assert not hasattr(layer,'w13_input_scale') and not hasattr(layer,'w2_input_scale')
        before=layout_state(layer)
        gate=torch.nn.Module();gate.register_parameter('e_score_correction_bias',layer.e_score_correction_bias)
        try: warmup['_count_warmup_iterations'](runner,128)
        except AttributeError as error:
            assert 'w13_input_scale' in str(error),str(error)
            counterfactual=str(error)
        else: raise AssertionError('Unrepaired actual native warmup did not reproduce missing w13_input_scale')
        assert before==layout_state(layer)
        reference,_,_=fixture_layer(fixture,swiglu)
        reference_before=layout_state(reference)
        for name in ('w13_input_scale','w2_input_scale'):
            native_replace(reference,name,None)
            assert name in reference.__dict__ and reference.__dict__[name] is None
            assert name not in reference._parameters and name not in reference._buffers
        assert reference_before==layout_state(reference)
        candidate.restore_humming_optional_input_state(layer,row)
        candidate.restore_humming_optional_input_state(layer,row)
        for name in ('w13_input_scale','w2_input_scale'):
            assert name in layer.__dict__ and layer.__dict__[name] is reference.__dict__[name] is None
            assert name not in layer._parameters and name not in layer._buffers
        exec(callback_program,{'importlib':importlib,'layer':layer,'qm':qm})
        config=qm.moe_quant_config
        native_config=qm.get_fused_moe_quant_config(layer)
        assert isinstance(config,humming.HummingMoEQuantConfig)
        assert isinstance(native_config,humming.HummingMoEQuantConfig)
        for current in (config,native_config):
            assert current.quant_dtype is None
            for config_attr,prefix in (('_w1','w13'),('_w2','w2')):
                descriptor=getattr(current,config_attr)
                for field,suffix in (('scale','weight_scale'),('alpha_or_gscale','weight_scale_2'),('zp','zero_point'),('bias','bias')):
                    assert getattr(descriptor,field) is getattr(layer,prefix+'_'+suffix,None)
            assert current.w1_humming_config is layer.humming_configs['w13']
            assert current.w2_humming_config is layer.humming_configs['w2']
            assert (current.gemm1_alpha,current.gemm1_beta,current.gemm1_clamp_limit)==(swiglu or (None,None,None))
            assert all(getattr(current,prefix+'_'+field) is None for prefix in ('w1','w2') for field in ('input_scale','input_scale_2'))
        assert warmup['envs'].VLLM_USE_DEEP_GEMM is True and warmup['envs'].VLLM_MOE_USE_DEEP_GEMM is True
        assert warmup['_fused_moe_grouped_gemm_may_use_deep_gemm'](runner) is False
        assert warmup['_count_warmup_iterations'](runner,128)==0
        assert gate.e_score_correction_bias is layer.e_score_correction_bias
        assert before==layout_state(layer) and all(tensor.is_meta for tensor in layer._parameters.values())
        assert not layer._buffers
        results.append({'runtime_signature_sha256':group['runtime_signature_sha256'],'covered_roles':len(group['covered_roles']),
            'swiglu':swiglu,'counterfactual_error':counterfactual,'native_ordinary_none_matches':True,
            'real_HummingMoEQuantConfig':True,'generic_ModelOpt_callback':True,
            'exact_parameter_and_gate_aliases':True,'parameters_unchanged':True,
            'deep_gemm_flags':[True,True],'native_warmup_predicate':False,'native_warmup_count':0})
assert not torch.cuda.is_initialized()
print(json.dumps({'reader_adapter_revision':candidate.READER_ADAPTER_REVISION,'descriptor_version':candidate.VERSION,
 'descriptor_source_sha256':hashlib.sha256(source.encode()).hexdigest(),'fixture_packet_sha256':hashlib.sha256(raw_packet).hexdigest(),
 'source_hashes':source_hashes,'runtime_groups':len(packet['runtime_groups']),'covered_roles':packet['covered_roles'],
 'builder_cases':results,'cuda_initialized':torch.cuda.is_initialized(),
 'native_functions_executed':['vllm.model_executor.utils.replace_parameter',
   'ModelOptNvFp4FusedMoE.get_fused_moe_quant_config','make_nvfp4_moe_quant_config','get_humming_moe_quant_config',
   '_deep_gemm_linear_data','_fused_moe_grouped_gemm_may_use_deep_gemm','_count_warmup_iterations'],
 'metadata_test_doubles':['DeepGEMM env flags forced true','ineligible linear-provider/expert classes',
   'unreachable hardware helpers raise AssertionError','empty DeepGEMM warmup caches'],
 'scope':'Actual source metadata bodies and final meta schemas; no GPU materialization, kernel, parked reader, recovery or SLO qualification'}))
'''

compile(PROGRAM, 'actual-humming-reader-v6-cpu-probe', 'exec')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    prepare_packet(args.basis, args.output)
