"""Prepare actual v4 MoE fixtures and an actual-image CPU-only reader probe.

The root executor schedules PROGRAM using the existing bounded cpu_probe with
DESCRIPTOR_SOURCE_B64/SHA256 and MOE_PACKET_B64/SHA256. No scheduling here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from demos.shadow.writer_descriptors import VERSION, ROUTING_BIAS_OWNERS, _validate_routing_bias_inventory
from demos.shadow.compat.native_config_delta import validate_reader_delta
from demos.shadow.compat import descriptor_native_config


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_packet(basis):
    """Recompute CPU fixture provenance without writing/adopting writer state."""
    basis = Path(basis).resolve()
    spec = json.loads((basis / 'descriptor-writer-spec.json').read_text())
    original = (basis / 'workshop_descriptors.py').read_text()
    reader = Path(descriptor_native_config.__file__).read_text()
    delta = validate_reader_delta(original, reader)
    groups, ranks = {}, {}
    for rank in ('0', '1'):
        path = basis / 'rank-manifests' / ('rank-' + rank + '.json')
        manifest = json.loads(path.read_text())
        if manifest['version'] != VERSION or manifest['reader_ready'] is not True or manifest['unhandled_modules']:
            raise ValueError('Need accepted v4 writer rank manifests with complete runtime state.')
        _validate_routing_bias_inventory(manifest)
        ranks[rank] = digest(path.read_bytes())
        for owner in sorted(ROUTING_BIAS_OWNERS):
            row = manifest['modules'][owner]
            expected = {'e_score_correction_bias', 'w13_weight', 'w13_weight_scale', 'w13_weight_scale_2',
                        'w2_weight', 'w2_weight_scale', 'w2_weight_scale_2'}
            if set(row['parameters']) != expected or row['none_parameters']:
                raise ValueError('Actual final MoE fixture is not the observed seven-parameter layout.')
            normalized = {key: row[key] for key in ('weight_schemas', 'input_schemas', 'humming_configs')}
            normalized['parameters'] = {name: {key: layout[key] for key in
                ('shape', 'stride', 'dtype', 'requires_grad', 'attrs')} for name, layout in row['parameters'].items()}
            signature = digest(json.dumps(normalized, sort_keys=True).encode())
            group = groups.setdefault(signature, {'runtime_signature_sha256': signature, 'fixture': normalized,
                                                'covered_roles': []})
            group['covered_roles'].append({'rank': int(rank), 'owner': owner})
    names = ('vllm/model_executor/layers/quantization/utils/humming/moe.py',
        'vllm/model_executor/layers/fused_moe/config.py', 'vllm/model_executor/layers/fused_moe/oracle/nvfp4.py',
        'vllm/model_executor/layers/quantization/modelopt.py')
    sources = {name: spec['runtime_contract_hashes'][name] for name in names}
    for name, expected in sources.items():
        if digest((basis / 'runtime-contract-sources' / name).read_bytes()) != expected:
            raise ValueError('Actual Humming/config/oracle source evidence changed.')
    packet = {'schema': 1, 'descriptor_version': VERSION, 'writer_basis': str(basis),
        'writer_spec_sha256': digest((basis / 'descriptor-writer-spec.json').read_bytes()),
        'rank_manifest_sha256': ranks, 'source_contracts': sources,
        'reader_delta': delta, 'runtime_groups': list(groups.values()),
        'covered_roles': sum(len(value['covered_roles']) for value in groups.values()),
        'scope': 'Actual final seven-parameter schemas; source-only CPU builder preflight, no GPU reader qualification'}
    return packet


def prepare_packet(basis, output):
    packet, output = build_packet(basis), Path(output).resolve()
    reader = Path(descriptor_native_config.__file__).read_text()
    delta = packet['reader_delta']
    output.mkdir(parents=True, exist_ok=False)
    (output / 'fixtures.json').write_text(json.dumps(packet, indent=2, sort_keys=True) + '\n')
    (output / 'reader-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
    (output / 'workshop_descriptors.py').write_text(reader)
    (output / 'cpu-program.py').write_text(PROGRAM)
    (output / 'packet-manifest.json').write_text(json.dumps({
        path.name: {'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())}
        for path in output.iterdir()}, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'runtime_groups': len(packet['runtime_groups']), 'covered_roles': packet['covered_roles'],
        'reader_helper_sha256': delta['reader_helper_sha256'], 'cpu_program_sha256': digest(PROGRAM.encode()),
        'live_actions': False}, indent=2))


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
candidate=types.ModuleType('actual_humming_reader_v5_cpu')
exec(compile(source,'actual_humming_reader_v5_cpu.py','exec'),candidate.__dict__)
assert candidate.VERSION==packet['descriptor_version']
assert candidate.READER_ADAPTER_REVISION==packet['reader_delta']['reader_adapter_revision']
root=Path(metadata.distribution('vllm').locate_file(''))
source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in packet['source_contracts']}
assert source_hashes==packet['source_contracts']
oracle=ast.parse((root/'vllm/model_executor/layers/fused_moe/oracle/nvfp4.py').read_text())
factory=next(node for node in oracle.body if isinstance(node,ast.FunctionDef) and node.name=='make_nvfp4_moe_quant_config')
humming_branch=next(node for node in factory.body if isinstance(node,ast.If) and
    ast.unparse(node.test)=='backend == NvFp4MoeBackend.HUMMING')
native_call=next(node.value for node in humming_branch.body if isinstance(node,ast.Return))
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
callback_program=compile(ast.Module(body=callback,type_ignores=[]),'frozen-reader-v5-callback','exec')
humming=importlib.import_module('vllm.model_executor.layers.quantization.utils.humming.moe')
RoutedExperts=importlib.import_module('vllm.model_executor.layers.fused_moe.routed_experts').RoutedExperts
assert not torch.cuda.is_initialized()
def forbidden(*args,**kwargs): raise AssertionError('Weight transform or generic checkpoint callback executed')
for name in ('convert_to_humming_moe_kernel_format','_prepare_and_transform_sublayer','_replace_layer_parameters',
             'make_humming_moe_kernel'):
    assert hasattr(humming,name),name
    setattr(humming,name,forbidden)
results=[]
for group in packet['runtime_groups']:
    fixture=group['fixture']
    assert len(fixture['parameters'])==7
    for alpha,beta,limit in ((None,None,None),(0.25,1.5,7.0)):
        layer=RoutedExperts.__new__(RoutedExperts);torch.nn.Module.__init__(layer)
        for name,layout in fixture['parameters'].items():
            tensor=torch.empty_strided(layout['shape'],layout['stride'],
                dtype=getattr(torch,layout['dtype'].removeprefix('torch.')),device='meta')
            layer.register_parameter(name,torch.nn.Parameter(tensor,requires_grad=layout['requires_grad']))
        layer.weight_schemas=candidate.decode(fixture['weight_schemas'])
        layer.input_schemas=candidate.decode(fixture['input_schemas'])
        layer.humming_configs=candidate.decode(fixture['humming_configs'])
        layer.swiglu_alpha,layer.swiglu_beta,layer.swiglu_limit=alpha,beta,limit
        assert not hasattr(layer,'w13_input_scale') and not hasattr(layer,'w2_input_scale')
        before={name:(id(tensor),tuple(tensor.shape),tuple(tensor.stride()),str(tensor.dtype),tensor.requires_grad)
                for name,tensor in layer._parameters.items()}
        qm=types.SimpleNamespace(get_fused_moe_quant_config=forbidden)
        exec(callback_program,{'importlib':importlib,'layer':layer,'qm':qm})
        config=qm.moe_quant_config
        assert isinstance(config,humming.HummingMoEQuantConfig)
        for config_attr,prefix in (('_w1','w13'),('_w2','w2')):
            descriptor=getattr(config,config_attr)
            for field,suffix in (('scale','weight_scale'),('alpha_or_gscale','weight_scale_2'),
                                 ('zp','zero_point'),('bias','bias')):
                assert getattr(descriptor,field) is getattr(layer,prefix+'_'+suffix,None)
        assert config.w1_humming_config is layer.humming_configs['w13']
        assert config.w2_humming_config is layer.humming_configs['w2']
        assert (config.gemm1_alpha,config.gemm1_beta,config.gemm1_clamp_limit)==(alpha,beta,limit)
        assert all(getattr(config,prefix+'_'+field) is None for prefix in ('w1','w2')
                   for field in ('input_scale','input_scale_2'))
        assert not hasattr(layer,'w13_input_scale') and not hasattr(layer,'w2_input_scale')
        after={name:(id(tensor),tuple(tensor.shape),tuple(tensor.stride()),str(tensor.dtype),tensor.requires_grad)
               for name,tensor in layer._parameters.items()}
        assert before==after and all(tensor.is_meta for tensor in layer._parameters.values())
        results.append({'runtime_signature_sha256':group['runtime_signature_sha256'],
            'covered_roles':len(group['covered_roles']),'swiglu':[alpha,beta,limit],
            'real_HummingMoEQuantConfig':True,'exact_parameter_aliases':True,
            'no_input_scale_attrs':True,'parameters_unchanged':True})
assert not torch.cuda.is_initialized()
print(json.dumps({'reader_adapter_revision':candidate.READER_ADAPTER_REVISION,
 'descriptor_version':candidate.VERSION,'descriptor_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
 'fixture_packet_sha256':hashlib.sha256(raw_packet).hexdigest(),'source_hashes':source_hashes,
 'runtime_groups':len(packet['runtime_groups']),'covered_roles':packet['covered_roles'],
 'builder_cases':results,'cuda_initialized':torch.cuda.is_initialized(),
 'scope':'Actual source Humming config builder with decoded final meta schemas only; no GPU materialization, kernel, parked reader or recovery qualification'}))
'''

compile(PROGRAM, 'actual-humming-reader-v5-cpu-probe', 'exec')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    prepare_packet(args.basis, args.output)
