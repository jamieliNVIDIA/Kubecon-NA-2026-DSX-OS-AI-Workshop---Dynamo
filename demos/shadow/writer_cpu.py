"""CPU-only descriptor, attention, inventory and routing-bias qualification.

Run PROGRAM in the pinned runtime image with frozen descriptor/inventory source
bytes and hashes plus EXPECTED_ROUTING_BIAS_SOURCE_HASHES. The payload checks
real Humming codecs, attention defaults, parameter inventory and stock GMS
materialization without initializing CUDA. This module never schedules work.

The payload is kept in execution order so changes do not require a chain of
versioned source patches. Its bytes match the previously composed v4 program.
"""

PROGRAM = r'''import base64,dataclasses,hashlib,json,os,types
import torch
assert not torch.cuda.is_initialized(), 'CPU probe unexpectedly has a CUDA context'
source=base64.b64decode(os.environ['DESCRIPTOR_SOURCE_B64']).decode()
assert hashlib.sha256(source.encode()).hexdigest()==os.environ['DESCRIPTOR_SOURCE_SHA256']
candidate=types.ModuleType('workshop_shadow_descriptors_cpu_candidate')
exec(compile(source,'workshop_shadow_descriptors_cpu_candidate.py','exec'),candidate.__dict__)
from humming import dtypes
from humming.config import LayerConfig,InputQuantizationMode,MmaType,WeightScaleType,WeightScale2Type
from humming.schema.humming import HummingWeightSchema,HummingInputSchema
config=LayerConfig(sm_version=90,shape_n=256,shape_k=128,b_dtype=dtypes.float4e2m1,
    a_dtype=dtypes.bfloat16,c_dtype=dtypes.bfloat16,bs_dtype=dtypes.float8e4m3,
    weight_scale_group_size=16,weight_scale_type=WeightScaleType.GROUP,
    weight_scale_2_type=WeightScale2Type.TENSOR,input_quant_mode=InputQuantizationMode.Disabled,
    mma_type=MmaType.WGMMA)
weight=HummingWeightSchema(b_dtype=dtypes.float4e2m1,bs_dtype=dtypes.float8e4m3,
    weight_scale_group_size=16,weight_scale_type=WeightScaleType.GROUP,
    weight_scale_2_type=WeightScale2Type.TENSOR,hadamard_block_size=0)
inputs=HummingInputSchema(a_dtype=dtypes.bfloat16,input_quant_mode=InputQuantizationMode.Disabled)
results={}
for name,value in [('LayerConfig',config),('HummingWeightSchema',weight),('HummingInputSchema',inputs)]:
    encoded=candidate.encode(value)
    restored=candidate.decode(json.loads(json.dumps(encoded,allow_nan=False)))
    assert type(value) is type(restored)
    assert candidate.encode(restored)==encoded, name
    results[name]={'fields':len(dataclasses.fields(value)),'roundtrip':'passed'}
tensor=torch.nn.Parameter(torch.empty_strided((4096,65536),(1,4096),
    dtype=torch.float8_e4m3fn,device='meta'),requires_grad=False)
layout=candidate.tensor_layout(tensor)
assert layout['shape']==[4096,65536] and layout['stride']==[1,4096]
assert tensor.is_meta and not torch.cuda.is_initialized()

import ast,importlib.metadata as metadata,textwrap
from pathlib import Path
root=Path(metadata.distribution('vllm').locate_file(''))
attention_path=root/'vllm/model_executor/layers/attention/attention.py'
kv_path=root/'vllm/model_executor/layers/quantization/kv_cache.py'
flashinfer_path=root/'vllm/v1/attention/backends/flashinfer.py'
def extract(path,name,parent=None):
    tree=ast.parse(path.read_text())
    nodes=tree.body
    if parent is not None:
        nodes=next(n for n in nodes if isinstance(n,ast.ClassDef) and n.name==parent).body
    node=next(n for n in nodes if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name)
    return node
defaults=extract(attention_path,'set_default_quant_scales')
cache_parameter=extract(kv_path,'KVCacheScaleParameter')
namespace={'torch':torch,'nn':torch.nn}
exec(compile(ast.Module(body=[defaults,cache_parameter],type_ignores=[]),str(attention_path),'exec'),namespace)
layer=torch.nn.Module()
with torch.device('meta'):
    namespace['set_default_quant_scales'](layer,register_buffer=True)
    placeholder=namespace['KVCacheScaleParameter']()
assert set(layer._buffers)==set(candidate.SCALE_BUFFERS)
assert all(t.is_meta and t.dtype==torch.float32 and t.numel()==1 for t in layer._buffers.values())
assert placeholder.is_meta and placeholder.numel()==1
assert all(getattr(layer,n)==1.0 for n in candidate.SCALE_FLOATS if n!='_o_scale_float')
initializer=extract(attention_path,'_init_kv_cache_quant')
o_default=next(node for node in initializer.body if isinstance(node,ast.Assign)
    and any(isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name)
            and target.value.id=='layer' and target.attr=='_o_scale_float' for target in node.targets))
assert isinstance(o_default.value,ast.Constant) and o_default.value.value is None
exec(compile(ast.Module(body=[o_default],type_ignores=[]),str(attention_path),'exec'),{'layer':layer})
assert layer._o_scale_float is None
postload=extract(flashinfer_path,'process_weights_after_loading','FlashInferImpl')
assert isinstance(postload.body[0],ast.Assign)
assert ast.unparse(postload.body[0])=='source_sinks = self._sinks_source'
assert isinstance(postload.body[1],ast.If)
assert ast.unparse(postload.body[1].test)=='source_sinks is None'
assert len(postload.body[1].body)==1 and isinstance(postload.body[1].body[0],ast.Return)
assert postload.body[1].body[0].value is None
post_namespace={'torch':torch}
exec(compile(ast.Module(body=[postload],type_ignores=[]),str(flashinfer_path),'exec'),post_namespace)
class NoSink:
    _sinks_source=None
    def __setattr__(self,name,value): raise AssertionError('No-sink hook attempted a mutation')
post_namespace['process_weights_after_loading'](NoSink(),torch.bfloat16)
assert not torch.cuda.is_initialized()

import contextlib,io,tempfile
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path
inventory_source=base64.b64decode(os.environ['PARAMETER_INVENTORY_SOURCE_B64']).decode()
assert hashlib.sha256(inventory_source.encode()).hexdigest()==os.environ['PARAMETER_INVENTORY_SOURCE_SHA256']
inventory=types.ModuleType('workshop_parameter_inventory_cpu_candidate')
exec(compile(inventory_source,'workshop_parameter_inventory_cpu_candidate.py','exec'),inventory.__dict__)
root_model=torch.nn.Module()
root_model.branch=torch.nn.Module()
root_model.branch.weight=torch.nn.Parameter(torch.empty_strided((8,16),(1,8),device='meta'),requires_grad=False)
root_model.branch.weight.input_dim=None
root_model.branch.weight.packed_factor=Fraction(1,2)
root_model.branch.alias=root_model.branch.weight
root_model.branch.register_parameter('empty',None)
root_model.cpu_weight=torch.nn.Parameter(torch.empty(2,device='cpu'),requires_grad=False)
root_model.grad_weight=torch.nn.Parameter(torch.empty(2,device='meta'),requires_grad=True)
identity={'candidate':'actual-image-cpu-v3','tp_rank':0,'tensor_parallel_size':2}
observed=inventory.parameter_inventory(root_model,identity)
by_name={row['name']:row for row in observed['parameters']}
assert by_name['branch.alias']['alias_of']=='branch.weight'
assert by_name['branch.weight']['layout_attributes']['input_dim']=={'type':'builtins:NoneType','value':None}
assert by_name['branch.weight']['layout_attributes']['packed_factor']=={
    'type':'fractions:Fraction','numerator':1,'denominator':2}
assert by_name['branch.weight']['shape']==[8,16] and by_name['branch.weight']['stride']==[1,8]
assert by_name['branch.empty']['is_none'] is True and by_name['grad_weight']['requires_grad'] is True
assert by_name['cpu_weight']['is_cuda'] is False and by_name['cpu_weight']['is_meta'] is False
assert observed['summary']['parameters']==4 and observed['summary']['slots']==5
assert not observed['summary']['inspection_errors']
guard_checks={}
for name,parameter in [('grad',root_model.grad_weight),('fraction-or-none-attrs',root_model.branch.weight)]:
    try:
        candidate.tensor_layout(parameter,'actual_cpu.'+name)
    except ValueError as error:
        assert 'actual_cpu.'+name in str(error)
        guard_checks[name]='strict rejection unchanged'
    else:
        raise AssertionError('v3 diagnostic relaxed '+name+' guard')
if hasattr(torch,'float8_e8m0fnu'):
    unknown=torch.nn.Parameter(torch.empty(2,dtype=torch.float8_e8m0fnu,device='meta'),requires_grad=False)
    try:
        candidate.tensor_layout(unknown,'actual_cpu.e8m0')
    except ValueError as error:
        assert 'actual_cpu.e8m0' in str(error) and 'torch.float8_e8m0fnu' in str(error)
        guard_checks['e8m0']='strict rejection unchanged'
    else:
        raise AssertionError('v3 diagnostic added an unreviewed dtype')
with tempfile.TemporaryDirectory() as directory:
    streams=[io.StringIO(),io.StringIO()]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(inventory.emit_writer_parameter_inventory,root_model,
            dict(identity,tp_rank=rank),directory,timeout=3,stream=streams[rank]) for rank in (0,1)]
        [future.result() for future in futures]
    stream=streams[0]
    rows=[json.loads(line.removeprefix(inventory.PREFIX)) for line in stream.getvalue().splitlines()]
    assert rows[0]['event']=='begin' and rows[-1]['event']=='all-ranks-ready'
    assert sum(row['event']=='parameter' for row in rows)==5
    assert (Path(directory)/'parameter-inventory-rank-0.json').is_file()
assert not torch.cuda.is_initialized()

import logging,typing
expected_role_sources=json.loads(os.environ['EXPECTED_ROUTING_BIAS_SOURCE_HASHES'])
required_role_sources={
 'vllm/model_executor/models/nemotron_h.py',
 'vllm/model_executor/layers/fused_moe/routed_experts.py',
 'gpu_memory_service/client/torch/module.py',
 'vllm/v1/worker/gpu_model_runner.py',
 'vllm/v1/worker/gpu_worker.py'}
assert set(expected_role_sources)==required_role_sources
actual_role_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in required_role_sources}
assert actual_role_hashes==expected_role_sources
nemotron_tree=ast.parse((root/'vllm/model_executor/models/nemotron_h.py').read_text())
routed_tree=ast.parse((root/'vllm/model_executor/layers/fused_moe/routed_experts.py').read_text())
def assignment(tree,attribute):
    matches=[node for node in ast.walk(tree) if isinstance(node,ast.Assign)
      and any(ast.unparse(target)==attribute for target in node.targets)]
    assert len(matches)==1,(attribute,len(matches))
    return matches[0]
create_bias=assignment(nemotron_tree,'self.gate.e_score_correction_bias')
assert ast.unparse(create_bias.value)=='nn.Parameter(torch.empty(config.n_routed_experts, dtype=torch.float32))'
assign_bias=assignment(routed_tree,'self.e_score_correction_bias')
assert ast.unparse(assign_bias.value)=='e_score_correction_bias'
inference_methods=[]
for name,required_names in [('vllm/v1/worker/gpu_model_runner.py',{'execute_model','_dummy_run'}),
                           ('vllm/v1/worker/gpu_worker.py',{'execute_model'})]:
    found=[]
    for node in ast.walk(ast.parse((root/name).read_text())):
        if isinstance(node,ast.FunctionDef) and node.name in required_names:
            decorators=[ast.unparse(value) for value in node.decorator_list]
            if 'torch.inference_mode()' in decorators:
                found.append(node.name)
                inference_methods.append({'file':name,'method':node.name,'line':node.lineno,
                  'decorators':decorators})
    assert set(found)==required_names
def runtime_class(key):
    module,name=key.split(':')
    return type(name,(torch.nn.Module,),{'__module__':module})
def plain_class(key):
    module,name=key.split(':')
    return type(name,(),{'__module__':module})
def install(model,name,module):
    pieces=name.split('.')
    for piece in pieces[:-1]:
        if not hasattr(model,piece): setattr(model,piece,torch.nn.Module())
        model=getattr(model,piece)
    setattr(model,pieces[-1],module)
def source_model():
    model=torch.nn.Module()
    for owner in sorted(candidate.ROUTING_BIAS_OWNERS):
        role=candidate.routing_bias_role(owner,'e_score_correction_bias')
        gate_name=role['gate_parameter'].rsplit('.',1)[0]
        gate=runtime_class(candidate.GATE_LINEAR)()
        context=types.SimpleNamespace(gate=gate)
        with torch.device('meta'):
            exec(compile(ast.Module(body=[create_bias],type_ignores=[]),'actual-nemotron-bias-assignment','exec'),
                {'self':context,'nn':torch.nn,'torch':torch,'config':types.SimpleNamespace(n_routed_experts=512)})
        assert gate.e_score_correction_bias.is_meta and gate.e_score_correction_bias.requires_grad is True
        gate.quant_method=plain_class('vllm.model_executor.layers.linear:UnquantizedLinearMethod')()
        layer=runtime_class(candidate.ROUTED_EXPERTS)()
        layer.quant_method=plain_class(candidate.MODEL_OPT+':ModelOptNvFp4FusedMoE')()
        layer.quant_method.nvfp4_backend=types.SimpleNamespace(name='HUMMING')
        layer.quant_method.moe_kernel=None
        layer.global_num_experts=512
        exec(compile(ast.Module(body=[assign_bias],type_ignores=[]),'actual-routed-bias-assignment','exec'),
            {'self':layer,'e_score_correction_bias':gate.e_score_correction_bias})
        assert layer.e_score_correction_bias is gate.e_score_correction_bias
        install(model,gate_name,gate);install(model,owner,layer)
    return model
role_model=source_model()
role_modules=dict(role_model.named_modules())
role_records={};role_contracts={};role_specs={};role_tensors={}
for index,owner in enumerate(sorted(candidate.ROUTING_BIAS_OWNERS)):
    layer=role_modules[owner]
    layout=candidate.parameter_layout(layer,owner,'e_score_correction_bias',layer.e_score_correction_bias,role_modules)
    layout.update(allocation_id='cpu-fixture-'+str(index),offset_bytes=0)
    role_records[owner]={'kind':'humming-moe','layer_class':candidate.ROUTED_EXPERTS,
      'quant_method_class':candidate.class_key(layer.quant_method),
      'parameters':{'e_score_correction_bias':layout},'none_parameters':[]}
    contract={key:layout[key] for key in ('shape','stride','dtype','allocation_id','offset_bytes')}
    for name in (owner+'.e_score_correction_bias',layout['inference_role']['gate_parameter']):
        role_contracts[name]=dict(contract,tensor_type='parameter')
    role_tensors[owner]=torch.empty(512,dtype=torch.float32,device='cpu')
role_identity={'candidate':'actual-image-cpu-v4'}
role_manifest={'version':candidate.VERSION,'identity':role_identity,'reader_ready':True,
 'unhandled_modules':{},'modules':role_records,
 'counts':{'humming-linear':0,'humming-moe':40,'cutlass-fp8':0}}
role_manifest=json.loads(json.dumps(role_manifest,allow_nan=False))
candidate.validate_tensor_contracts(role_manifest,role_contracts)
candidate.prepare_reader_skeleton(role_model,role_manifest,role_contracts,role_identity)
assert all(role_modules[owner].e_score_correction_bias.is_meta and
           role_modules[owner].e_score_correction_bias.requires_grad is True for owner in candidate.ROUTING_BIAS_OWNERS)
for owner in candidate.ROUTING_BIAS_OWNERS:
    tensor=role_tensors[owner]
    layout=role_records[owner]['parameters']['e_score_correction_bias']
    for name in (owner+'.e_score_correction_bias',layout['inference_role']['gate_parameter']):
        role_specs[name]=types.SimpleNamespace(meta=types.SimpleNamespace(tensor_type='parameter'),
            materialize=lambda manager,index,tensor=tensor:tensor)
module_tree=ast.parse((root/'gpu_memory_service/client/torch/module.py').read_text())
module_functions=[node for node in module_tree.body if isinstance(node,ast.FunctionDef)
  and node.name in ('_resolve_module_attr','materialize_module_from_gms')]
assert {node.name for node in module_functions}=={'_resolve_module_attr','materialize_module_from_gms'}
materializer_namespace={'torch':torch,'Tuple':typing.Tuple,
 'GMSTensorSpec':types.SimpleNamespace(load_all=lambda manager:role_specs),
 'logger':logging.getLogger('actual-cpu-v4-stock-materializer')}
exec(compile(ast.Module(body=module_functions,type_ignores=[]),'actual-unchanged-gms-materializer','exec'),
    materializer_namespace)
materializer_namespace['materialize_module_from_gms'](object(),role_model,device_index=0)
for owner in candidate.ROUTING_BIAS_OWNERS:
    layer=role_modules[owner]
    role=candidate.routing_bias_role(owner,'e_score_correction_bias')
    gate_name=role['gate_parameter'].rsplit('.',1)[0]
    gate=role_modules[gate_name]
    assert layer.e_score_correction_bias.device.type=='cpu'
    assert layer.e_score_correction_bias.requires_grad is True and gate.e_score_correction_bias.requires_grad is True
    assert layer.e_score_correction_bias.data_ptr()==gate.e_score_correction_bias.data_ptr()==role_tensors[owner].data_ptr()
    candidate.parameter_layout(layer,owner,'e_score_correction_bias',layer.e_score_correction_bias,
        role_modules,require_object_alias=False)
    with torch.inference_mode():
        inference_value=layer.e_score_correction_bias+1
        assert not inference_value.requires_grad and torch.is_inference_mode_enabled()
first=next(iter(role_specs))
role_specs[first].materialize=lambda manager,index:torch.empty(513,dtype=torch.float32,device='cpu')
try:
    materializer_namespace['materialize_module_from_gms'](object(),role_model,device_index=0)
except RuntimeError as error:
    assert 'Shape/dtype mismatch' in str(error)
    stock_shape_guard='unchanged strict rejection'
else:
    raise AssertionError('Stock GMS shape/dtype guard was bypassed')
assert not torch.cuda.is_initialized()
print(json.dumps({'routing_bias_roles_real_meta_stock_cpu':40,'stock_shape_dtype_guard':stock_shape_guard,'routing_bias_source_hashes':actual_role_hashes,'inference_mode_source_methods':inference_methods,'parameter_inventory_real_torch_meta_cpu':'passed','strict_diagnostic_guards':guard_checks,'inventory_summary':observed['summary'],'parameter_inventory_source_sha256':hashlib.sha256(inventory_source.encode()).hexdigest(),'codec_roundtrips':results,'real_meta_layout':layout,
    'attention_real_source_meta_buffers':'passed','real_KVCacheScaleParameter_meta':'passed',
    'flashinfer_no_sink_postload_source_and_no_mutation':'passed',
    'attention_source_sha256':hashlib.sha256(attention_path.read_bytes()).hexdigest(),
    'kv_cache_source_sha256':hashlib.sha256(kv_path.read_bytes()).hexdigest(),
    'flashinfer_source_sha256':hashlib.sha256(flashinfer_path.read_bytes()).hexdigest(),
    'cuda_initialized':torch.cuda.is_initialized(),
    'descriptor_source_sha256':hashlib.sha256(source.encode()).hexdigest(),
    'scope':'Actual-image CPU codec, real meta constructors and exact no-sink FlashInfer source only; no GPU reader or numerical qualification'}))
'''

compile(PROGRAM, 'workshop-shadow-descriptor-cpu-v4', 'exec')
