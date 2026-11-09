"""Experimental, restricted writer/reader runtime descriptor prototype.

No live/deployment entrypoint. This needs new writer instrumentation and a
fresh composed candidate. It never runs weight postprocessing on RO tensors.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import importlib
import json
import math
import os
from pathlib import Path
import time

VERSION = 'workshop-super-vl-humming-runtime-v4-routing-bias'
READER_ADAPTER_REVISION = 'workshop-humming-reader-v5-native-config-builder'
MODEL_OPT = 'vllm.model_executor.layers.quantization.modelopt'
HUMMING_LINEAR = 'vllm.model_executor.kernels.linear.nvfp4.humming:HummingNvFp4LinearKernel'
CUTLASS_FP8 = 'vllm.model_executor.kernels.linear.scaled_mm.cutlass:CutlassFP8ScaledMMLinearKernel'
MOE_MODULE = 'vllm.model_executor.layers.fused_moe.experts.fused_humming_moe'
MOE_EXPERTS = frozenset(MOE_MODULE + ':' + n for n in (
    'HummingIndexedExperts', 'HummingGroupedExperts', 'BatchedHummingGroupedExperts'))
CLASSES = frozenset((
    'humming.config.config:LayerConfig',
    'humming.schema.humming:HummingWeightSchema',
    'humming.schema.humming:HummingInputSchema',
))
ENUMS = frozenset('humming.config.enum:' + n for n in (
    'InputQuantizationMode', 'WeightScaleType', 'WeightScale2Type', 'MmaType'))
DTYPES = frozenset(('humming.dtypes:IntegerType', 'humming.dtypes:FloatingPointType'))
TORCH_DTYPES = frozenset(('torch.uint8', 'torch.int32', 'torch.float8_e4m3fn',
    'torch.float32', 'torch.float16', 'torch.bfloat16'))
PARAM_ATTRS = ('input_dim', 'output_dim', 'packed_dim', 'packed_factor')
ROUTED_EXPERTS = 'vllm.model_executor.layers.fused_moe.routed_experts:RoutedExperts'
GATE_LINEAR = 'vllm.model_executor.layers.fused_moe.router.gate_linear:GateLinear'
ROUTING_BIAS_ROLE = 'nemotron-fp32-routing-correction-bias-v1'
# Exact 40 owners observed independently in both actual a5 TP-rank inventories.
# This prototype is bound to the frozen Super VL model/config/source identity.
ROUTING_BIAS_LAYER_IDS = (1, 3, 5, 8, 10, 12, 14, 17, 19, 21, 23, 26, 28, 30,
    32, 34, 37, 39, 41, 43, 45, 48, 50, 52, 54, 56, 59, 61, 63, 65, 67, 70,
    72, 74, 76, 79, 81, 83, 85, 87)
ROUTING_BIAS_OWNERS = frozenset('language_model.model.layers.' + str(index) +
    '.mixer.experts.routed_experts' for index in ROUTING_BIAS_LAYER_IDS)
ATTENTION_CLASS = 'vllm.model_executor.layers.attention.attention:Attention'
FLASHINFER_IMPL = 'vllm.v1.attention.backends.flashinfer:FlashInferImpl'
SCALE_BUFFERS = ('_q_scale', '_k_scale', '_v_scale', '_prob_scale')
SCALE_FLOATS = ('_q_scale_float', '_k_scale_float', '_v_scale_float', '_prob_scale_float', '_o_scale_float')
HOST_SCALE_TENSORS = ('_k_scale_cpu', '_v_scale_cpu')
_pending_manifest = None


def _valid_sha256(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def class_key(value):
    return type(value).__module__ + ':' + type(value).__name__


def _resolve(key, allowed):
    if key not in allowed:
        raise ValueError('Unreviewed runtime descriptor class: ' + str(key))
    module, name = key.split(':')
    return getattr(importlib.import_module(module), name)


def encode(value):
    """JSON-only encoding; never pickle, tensor-copy or dynamic class import."""
    key = class_key(value)
    if key in ENUMS:
        return {'enum': key, 'value': value.value}
    if key in DTYPES:
        return {'dtype': str(value)}
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return [encode(x) for x in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {'mapping': {k: encode(v) for k, v in value.items()}}
    if key in CLASSES and is_dataclass(value):
        return {'class': key, 'fields': {f.name: encode(getattr(value, f.name))
            for f in fields(value) if f.init}}
    raise ValueError('Unreviewed value in runtime descriptor: ' + key)


def decode(value):
    """Rebuild only fixed allowlisted classes and their exact dataclass fields."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [decode(x) for x in value]
    if type(value) is not dict:
        raise ValueError('Invalid runtime descriptor value.')
    keys = set(value)
    if keys == {'enum', 'value'}:
        cls = _resolve(value['enum'], ENUMS)
        if not issubclass(cls, Enum):
            raise ValueError('Runtime descriptor enum contract changed.')
        return cls(value['value'])
    if keys == {'dtype'}:
        dtype = importlib.import_module('humming.dtypes').DataType.from_str(value['dtype'])
        if class_key(dtype) not in DTYPES or str(dtype) != value['dtype']:
            raise ValueError('Noncanonical Humming dtype.')
        return dtype
    if keys == {'mapping'} and type(value['mapping']) is dict:
        if not all(type(k) is str for k in value['mapping']):
            raise ValueError('Descriptor mapping keys must be strings.')
        return {k: decode(v) for k, v in value['mapping'].items()}
    if keys == {'class', 'fields'} and type(value['fields']) is dict:
        cls = _resolve(value['class'], CLASSES)
        expected = {f.name for f in fields(cls) if f.init}
        if set(value['fields']) != expected:
            raise ValueError('Runtime descriptor dataclass fields changed: ' + value['class'])
        return cls(**{k: decode(v) for k, v in value['fields'].items()})
    raise ValueError('Unrecognized runtime descriptor tag.')


def save_runtime_manifest(manifest, path):
    """Publish one fresh rank manifest atomically; never reuse old generations."""
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists():
        raise ValueError('Refusing to overwrite an existing writer runtime manifest.')
    temporary = path.with_suffix('.pending-' + str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(manifest, sort_keys=True, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link creation also refuses races against an existing manifest.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_runtime_manifest(path, expected_identity):
    value = json.loads(Path(path).read_text())
    if value.get('version') != VERSION or value.get('identity') != expected_identity:
        raise ValueError('Stale, foreign or unknown writer runtime manifest.')
    return value


def runtime_identity():
    """Bind this process to the fresh candidate and the actual TP rank."""
    from vllm.distributed import get_tensor_model_parallel_rank
    value = json.loads(os.environ['DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY'])
    if 'tp_rank' in value:
        raise ValueError('TP rank must come from the actual vLLM process.')
    value['tp_rank'] = get_tensor_model_parallel_rank()
    return value


def runtime_manifest_path(identity):
    directory = Path(os.environ['DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR'])
    if not directory.is_absolute():
        raise ValueError('Descriptor directory must be an explicit Pod-shared absolute path.')
    return directory / ('rank-' + str(identity['tp_rank']) + '.json')


def gms_parameter_contracts(manager):
    """Read the independent, committed GMS tensor metadata without mapping it."""
    from gpu_memory_service.client.torch.tensor import GMSTensorSpec
    return {name: {'shape': list(spec.meta.shape), 'stride': list(spec.meta.stride),
                  'dtype': str(spec.meta.dtype), 'allocation_id': spec.allocation_id,
                  'offset_bytes': spec.offset_bytes}
            for name, spec in GMSTensorSpec.load_all(manager).items()
            if spec.meta.tensor_type == 'parameter'}


def gms_tensor_contracts(manager):
    from gpu_memory_service.client.torch.tensor import GMSTensorSpec
    return {name: {'shape': list(spec.meta.shape), 'stride': list(spec.meta.stride),
                  'dtype': str(spec.meta.dtype), 'allocation_id': spec.allocation_id,
                  'offset_bytes': spec.offset_bytes, 'tensor_type': spec.meta.tensor_type}
            for name, spec in GMSTensorSpec.load_all(manager).items()}


def prepare_writer_manifest(model, manager):
    global _pending_manifest
    if _pending_manifest is not None:
        raise ValueError('A writer runtime manifest is already awaiting GMS publication.')
    identity = runtime_identity()
    from gpu_memory_service.integrations.vllm.workshop_parameter_inventory import emit_writer_parameter_inventory
    emit_writer_parameter_inventory(model, identity, os.environ['DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR'])
    contracts = gms_tensor_contracts(manager)
    value = export_runtime_manifest(model, manager, identity, contracts=contracts)
    validate_tensor_contracts(value, contracts)
    _pending_manifest = value


def publish_writer_manifest(manager):
    """Publish only AFTER GMS commit, reconnect and remap have succeeded."""
    global _pending_manifest
    if _pending_manifest is None:
        raise ValueError('No prepared writer runtime descriptor.')
    value = _pending_manifest
    layout_hash = manager.get_memory_layout_hash()
    if not _valid_sha256(layout_hash):
        raise ValueError('Writer has no valid committed GMS memory-layout hash.')
    value['gms_memory_layout_hash'] = layout_hash
    validate_tensor_contracts(value, gms_tensor_contracts(manager))
    save_runtime_manifest(value, runtime_manifest_path(value['identity']))
    _pending_manifest = None


def read_committed_manifest(manager, timeout=15):
    identity = runtime_identity()
    path = runtime_manifest_path(identity)
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Committed GMS weights have no matching runtime descriptor.')
        time.sleep(0.1)
    value = load_runtime_manifest(path, identity)
    actual_hash = manager.get_memory_layout_hash()
    if not _valid_sha256(actual_hash) or value.get('gms_memory_layout_hash') != actual_hash:
        raise ValueError('Reader descriptor belongs to a different committed GMS layout.')
    contracts = gms_tensor_contracts(manager)
    validate_tensor_contracts(value, contracts)
    return value, contracts, identity


def tensor_layout(tensor, qualified_name='<unbound>'):
    if str(tensor.dtype) not in TORCH_DTYPES or tensor.requires_grad:
        raise ValueError('Unexpected inference parameter dtype/gradient contract: parameter=' +
            qualified_name + ', dtype=' + str(tensor.dtype) + ', requires_grad=' + str(tensor.requires_grad))
    shape, stride = tuple(tensor.shape), tuple(tensor.stride())
    if any(type(x) is not int or x < 0 for x in shape + stride):
        raise ValueError('Unsupported parameter shape/stride: parameter=' + qualified_name)
    attrs = {n: getattr(tensor, n) for n in PARAM_ATTRS if hasattr(tensor, n)}
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in attrs.values()):
        raise ValueError('Unexpected parameter layout attribute: parameter=' + qualified_name +
            ', attribute_types=' + str({name: class_key(value) for name, value in attrs.items()}))
    return {'shape': list(shape), 'stride': list(stride), 'dtype': str(tensor.dtype),
            'requires_grad': False, 'attrs': attrs}


def routing_bias_role(owner, attr):
    if owner not in ROUTING_BIAS_OWNERS or attr != 'e_score_correction_bias':
        return None
    mixer = owner.removesuffix('.experts.routed_experts')
    return {'role': ROUTING_BIAS_ROLE, 'gate_parameter': mixer + '.gate.e_score_correction_bias'}


def _validate_routing_bias_layout(layout, role, qualified_name):
    shape, stride, attrs = layout.get('shape'), layout.get('stride'), layout.get('attrs')
    if (layout.get('inference_role') != role or type(layout.get('dtype')) is not str or
            layout['dtype'] != 'torch.float32' or layout.get('requires_grad') is not True or
            type(shape) is not list or len(shape) != 1 or type(shape[0]) is not int or shape[0] != 512 or
            type(stride) is not list or len(stride) != 1 or type(stride[0]) is not int or stride[0] != 1 or
            type(attrs) is not dict or attrs):
        raise ValueError('Unreviewed Nemotron routing-correction metadata: ' + qualified_name)


def parameter_layout(layer, owner, attr, tensor, modules, *, require_object_alias=True):
    """Preserve the one observed true-gradient role; every other role stays strict.

    vLLM constructs this inference routing correction as a default nn.Parameter
    and passes the same object to gate and RoutedExperts. Do not mutate it or
    turn a general dtype/gradient guard into an unrestricted bool serializer.
    """
    qualified_name = owner + '.' + attr if owner else attr
    role = routing_bias_role(owner, attr)
    if role is None:
        return tensor_layout(tensor, qualified_name)
    gate_name, gate_attr = role['gate_parameter'].rsplit('.', 1)
    gate = modules.get(gate_name)
    if (class_key(layer) != ROUTED_EXPERTS or _kind(layer) != 'humming-moe' or
            getattr(layer, 'global_num_experts', None) != 512 or
            class_key(gate) != GATE_LINEAR or
            class_key(getattr(gate, 'quant_method', None)) !=
                'vllm.model_executor.layers.linear:UnquantizedLinearMethod'):
        raise ValueError('Unreviewed Nemotron routing-correction owner/backend: ' + qualified_name)
    gate_tensor = gate._parameters.get(gate_attr)
    if (class_key(tensor) != 'torch.nn.parameter:Parameter' or
            class_key(gate_tensor) != 'torch.nn.parameter:Parameter' or
            any(hasattr(tensor, name) or hasattr(gate_tensor, name) for name in PARAM_ATTRS)):
        raise ValueError('Unreviewed Nemotron routing-correction parameter type/attrs: ' + qualified_name)
    if require_object_alias and gate_tensor is not tensor:
        raise ValueError('Nemotron routing correction lost its gate object alias: ' + qualified_name)
    layout = {'shape': list(tensor.shape), 'stride': list(tensor.stride()),
        'dtype': str(tensor.dtype), 'requires_grad': tensor.requires_grad, 'attrs': {},
        'inference_role': role}
    _validate_routing_bias_layout(layout, role, qualified_name)
    gate_layout = {'shape': list(gate_tensor.shape), 'stride': list(gate_tensor.stride()),
        'dtype': str(gate_tensor.dtype), 'requires_grad': gate_tensor.requires_grad,
        'attrs': {}, 'inference_role': role}
    _validate_routing_bias_layout(gate_layout, role, role['gate_parameter'])
    return layout


def _validate_routing_bias_inventory(manifest):
    observed = set()
    for owner, row in manifest['modules'].items():
        for attr, layout in row['parameters'].items():
            role = routing_bias_role(owner, attr)
            if role is not None:
                _validate_routing_bias_layout(layout, role, owner + '.' + attr)
                if type(layout.get('offset_bytes')) is not int or layout['offset_bytes'] < 0:
                    raise ValueError('Unreviewed routing-correction byte offset: ' + owner + '.' + attr)
                observed.add(owner)
            elif layout.get('inference_role') is not None or layout.get('requires_grad') is not False:
                raise ValueError('Unreviewed gradient-bearing parameter role: ' + owner + '.' + attr)
    if observed != ROUTING_BIAS_OWNERS:
        raise ValueError('Nemotron routing-correction inventory differs from the exact 40 observed owners.')


def allocation_identity(tensor, manager):
    """Record/check the full parameter extent in one committed GMS allocation."""
    pointer = int(tensor.data_ptr())
    shape, stride = tuple(tensor.shape), tuple(tensor.stride())
    if any(x < 0 for x in shape + stride) or any(x == 0 for x in shape):
        raise ValueError('Empty or negative-stride parameters are unsupported.')
    extent = (1 + sum((s - 1) * st for s, st in zip(shape, stride))) * tensor.element_size()
    matches = [(base, m) for base, m in manager.mappings.items()
               if base <= pointer and pointer + extent <= base + m.aligned_size]
    if len(matches) != 1:
        raise ValueError('Parameter does not map unambiguously inside one GMS allocation.')
    base, mapping = matches[0]
    return {'allocation_id': mapping.allocation_id, 'offset_bytes': pointer - base}


def _kind(layer):
    qm = getattr(layer, 'quant_method', None)
    key = class_key(qm)
    if key == MODEL_OPT + ':ModelOptLinearMethod':
        kernel = class_key(qm.kernel)
        if kernel == HUMMING_LINEAR:
            return 'humming-linear'
        if kernel == CUTLASS_FP8:
            return 'cutlass-fp8'
        raise ValueError('Unreviewed ModelOpt linear reader backend: ' + kernel)
    if key == MODEL_OPT + ':ModelOptNvFp4FusedMoE':
        if getattr(getattr(qm, 'nvfp4_backend', None), 'name', None) != 'HUMMING':
            raise ValueError('Only the source-reviewed Humming MoE backend is supported.')
        if qm.moe_kernel is not None and class_key(qm.moe_kernel.fused_experts) not in MOE_EXPERTS:
            raise ValueError('Unreviewed Humming MoE expert class.')
        return 'humming-moe'
    if key == MODEL_OPT + ':ModelOptKVCacheMethod':
        if (class_key(layer) != ATTENTION_CLASS or class_key(layer.impl) != FLASHINFER_IMPL or
                layer.kv_cache_dtype not in ('fp8', 'fp8_e4m3') or layer.has_sink or
                getattr(layer.impl, 'sinks', None) is not None or
                getattr(layer.impl, '_sinks_source', None) is not None):
            raise ValueError('Only source-reviewed scalar FP8 FlashInfer attention without sinks is supported.')
        return 'modelopt-attention'
    return None


def _private_tensor(tensor, managers):
    if tensor.is_meta:
        raise ValueError('Attention scale tensor is still meta.')
    if not tensor.is_cuda:
        if tensor.device.type != 'cpu':
            raise ValueError('Unexpected attention scale device.')
        return
    pointer = int(tensor.data_ptr())
    size = tensor.numel() * tensor.element_size()
    if any(pointer < base + m.aligned_size and base < pointer + size
            for manager in managers for base, m in manager.mappings.items()):
        raise ValueError('Attention runtime scale still aliases a GMS allocation.')


def _attention_geometry(layer):
    window = layer.sliding_window
    if isinstance(window, tuple):
        window = list(window)
    return {'num_heads': layer.num_heads, 'num_kv_heads': layer.num_kv_heads,
            'head_size': layer.head_size, 'head_size_v': layer.head_size_v,
            'sliding_window': window, 'scale': layer.impl.scale,
            'dtype': str(layer.dtype), 'kv_cache_dtype': layer.kv_cache_dtype,
            'query_quant_class': class_key(layer.query_quant)}


def _export_attention(layer, manager, name, contracts):
    from gpu_memory_service.integrations.vllm.workshop_humming import _pool_managers
    managers = _pool_managers(manager)
    if set(layer._buffers) != set(SCALE_BUFFERS):
        raise ValueError('Unexpected attention buffer inventory: ' + name)
    result = {'geometry': _attention_geometry(layer), 'buffers': {}, 'host_floats': {}, 'host_tensors': {}}
    for attr in SCALE_BUFFERS:
        tensor = getattr(layer, attr)
        _private_tensor(tensor, managers)
        layout = tensor_layout(tensor)
        if (layout['dtype'] != 'torch.float32' or layout['shape'] not in ([], [1]) or
                tensor.numel() != 1):
            raise ValueError('Only scalar FP32 attention scales are supported.')
        contract = contracts[name + '.' + attr]
        if contract.get('tensor_type') != 'buffer' or any(contract[k] != layout[k] for k in ('shape', 'stride', 'dtype')):
            raise ValueError('Writer attention scale differs from registered GMS metadata.')
        value = float(tensor.item())
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid final attention scale.')
        result['buffers'][attr] = {'contract': contract, 'value': value}
    for attr in SCALE_FLOATS:
        value = getattr(layer, attr)
        if attr == '_o_scale_float' and value is None:
            result['host_floats'][attr] = None
        elif type(value) is float and math.isfinite(value) and value > 0:
            result['host_floats'][attr] = value
        else:
            raise ValueError('Unexpected attention host scale: ' + attr)
    for attr in HOST_SCALE_TENSORS:
        tensor = getattr(layer, attr)
        _private_tensor(tensor, managers)
        if str(tensor.dtype) != 'torch.float32' or tensor.numel() != 1:
            raise ValueError('Unexpected attention host scale tensor.')
        value = float(tensor.item())
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid attention host scale tensor value.')
        result['host_tensors'][attr] = {'shape': list(tensor.shape), 'value': value,
            'device_type': tensor.device.type,
            'contract': contracts.get(name + '.' + attr)}
    return result


def _restore_attention(layer, row, manager):
    import torch
    from gpu_memory_service.integrations.vllm.workshop_humming import _pool_managers
    managers = _pool_managers(manager)
    if _kind(layer) != 'modelopt-attention':
        raise ValueError('Unsupported reader attention runtime.')
    runtime = row['attention_runtime']
    if _attention_geometry(layer) != runtime['geometry']:
        raise ValueError('Reader/writer attention geometry or query-quant selection changed.')
    for attr in ('q_scale', 'k_scale', 'v_scale', 'prob_scale'):
        if hasattr(layer, attr):
            raise ValueError('Reader retained consumed attention checkpoint scale: ' + attr)
    for attr in SCALE_BUFFERS:
        tensor = getattr(layer, attr)
        _private_tensor(tensor, managers)
        contract = runtime['buffers'][attr]['contract']
        layout = tensor_layout(tensor)
        if any(layout[k] != contract[k] for k in ('shape', 'stride', 'dtype')):
            raise ValueError('Imported private attention scale layout changed.')
        if float(tensor.item()) != runtime['buffers'][attr]['value']:
            raise ValueError('Imported private attention scale value changed.')
    for attr in SCALE_FLOATS:
        setattr(layer, attr, runtime['host_floats'][attr])
    for attr in HOST_SCALE_TENSORS:
        value = runtime['host_tensors'][attr]
        if value['device_type'] not in ('cpu', 'cuda'):
            raise ValueError('Unsupported attention host scale placement.')
        device = 'cpu' if value['device_type'] == 'cpu' else layer._k_scale.device
        tensor = torch.full(value['shape'], value['value'], dtype=torch.float32, device=device)
        _private_tensor(tensor, managers)
        setattr(layer, attr, tensor)
    # In the reviewed FlashInfer implementation the post-load hook handles
    # sinks only. Both source and runtime guards require no sinks, so no
    # backend callback or tensor transform runs here.


def export_runtime_manifest(model, manager, identity, contracts=None):
    """Describe the FINAL writer, after postprocessing and before publication.

    identity must bind a fresh candidate nonce, image/model/source hashes and
    TP rank. The caller provides shared-file publication and GMS lifecycle.
    """
    required = {'candidate', 'image_sha256', 'model_revision', 'model_config_sha256', 'source_manifest_sha256',
                'tp_rank', 'tensor_parallel_size'}
    if set(identity) != required or identity['tensor_parallel_size'] != 2 or identity['tp_rank'] not in (0, 1):
        raise ValueError('Incomplete pinned TP2 descriptor identity.')
    if (not identity['candidate'] or not all(_valid_sha256(identity[key]) for key in
            ('image_sha256', 'model_config_sha256', 'source_manifest_sha256')) or
            type(identity['model_revision']) is not str or len(identity['model_revision']) != 40):
        raise ValueError('Descriptor identity lacks pinned image/model/config/source hashes.')
    records = {}
    unhandled = {}
    counts = {'humming-linear': 0, 'humming-moe': 0, 'cutlass-fp8': 0}
    modules = dict(model.named_modules())
    for name, layer in modules.items():
        kind = _kind(layer)
        if kind is None:
            qm = getattr(layer, 'quant_method', None)
            if class_key(qm).startswith(MODEL_OPT + ':'):
                unhandled[name] = {
                    'layer_class': class_key(layer), 'quant_method_class': class_key(qm),
                    'parameter_names': sorted(layer._parameters),
                    'none_parameters': sorted(k for k, p in layer._parameters.items() if p is None),
                }
            continue
        qm = layer.quant_method
        params = {}
        for attr, tensor in layer._parameters.items():
            if tensor is not None:
                if tensor.is_meta or not tensor.is_cuda:
                    raise ValueError('Writer manifest requires actual final CUDA parameters.')
                qualified_name = name + '.' + attr if name else attr
                params[attr] = dict(parameter_layout(layer, name, attr, tensor, modules),
                    **allocation_identity(tensor, manager))
        row = {'kind': kind, 'layer_class': class_key(layer), 'quant_method_class': class_key(qm),
               'parameters': params,
               'none_parameters': sorted(attr for attr, tensor in layer._parameters.items() if tensor is None)}
        if kind in ('humming-linear', 'cutlass-fp8'):
            row['quant_spec_repr'] = repr(qm.spec)
            if '0x' in row['quant_spec_repr']:
                raise ValueError('Quant spec contains process-specific identities.')
        if kind == 'humming-linear':
            row.update(kernel_class=HUMMING_LINEAR,
                weight_schema=encode(layer.weight_schema),
                layer_config=encode(qm.kernel.layer_config),
                compute_config=qm.kernel.compute_config,
                is_w4a16_nvfp4=layer.is_w4a16_nvfp4)
            if type(row['compute_config']) is not str or type(row['is_w4a16_nvfp4']) is not bool:
                raise ValueError('Unexpected Humming linear runtime fields.')
            json.loads(row['compute_config'])
        elif kind == 'humming-moe':
            expert_class = qm.experts_cls.__module__ + ':' + qm.experts_cls.__name__
            if qm.moe_kernel is None or expert_class not in MOE_EXPERTS:
                raise ValueError('Writer Humming MoE kernel is incomplete.')
            row.update(experts_class=expert_class,
                weight_schemas=encode(layer.weight_schemas),
                input_schemas=encode(layer.input_schemas),
                humming_configs=encode(layer.humming_configs))
        elif kind == 'cutlass-fp8':
            row.update(kernel_class=CUTLASS_FP8, logical_output_size=qm.kernel.logical_output_size,
                is_w4a16_nvfp4=layer.is_w4a16_nvfp4)
            shape = tuple(layer.weight.shape)
            if (len(shape) != 2 or any(dim % 16 for dim in shape) or
                    qm.kernel.logical_output_size != shape[1]):
                raise ValueError('Only source-reviewed unpadded Cutlass FP8 layers are supported.')
        elif kind == 'modelopt-attention':
            if params:
                raise ValueError('Writer attention still has consumed checkpoint parameters.')
            row['attention_runtime'] = _export_attention(layer, manager, name,
                gms_tensor_contracts(manager) if contracts is None else contracts)
        records[name] = row
        counts[kind] = counts.get(kind, 0) + 1
    if (counts['humming-linear'] != 80 or counts['humming-moe'] != 40 or
            counts['cutlass-fp8'] < 1):
        raise ValueError('Unexpected Super VL writer module inventory: ' + str(counts))
    manifest = {'version': VERSION, 'identity': identity, 'modules': records, 'counts': counts,
                'unhandled_modules': unhandled, 'reader_ready': not bool(unhandled)}
    _validate_routing_bias_inventory(manifest)
    if hasattr(model, 'process_weights_after_loading'):
        method = model.process_weights_after_loading
        manifest['unhandled_modules']['<model-post-load>'] = {
            'callable': method.__module__ + ':' + method.__qualname__}
        manifest['reader_ready'] = False
    json.dumps(manifest, allow_nan=False)
    return manifest


def validate_tensor_contracts(manifest, contracts):
    """Require a matching independent GMS layout for every recorded parameter.

    contracts is built from the actual GMSTensorSpec metadata by a reviewed
    version-specific adapter, not by reading this manifest back into itself.
    Its keys are fully qualified parameter names and its values contain
    shape/stride/dtype/allocation_id/offset_bytes from GMS.
    """
    if manifest.get('version') != VERSION:
        raise ValueError('Unknown runtime manifest version.')
    _validate_routing_bias_inventory(manifest)
    for name, row in manifest['modules'].items():
        prefix = name + '.'
        expected_names = {prefix + attr for attr in row['parameters']}
        observed_names = {n for n, contract in contracts.items() if n.startswith(prefix) and
            '.' not in n[len(prefix):] and contract.get('tensor_type', 'parameter') == 'parameter'}
        if expected_names != observed_names:
            raise ValueError('GMS/descriptor parameter inventory mismatch: ' + name)
        for attr, layout in row['parameters'].items():
            observed = contracts[prefix + attr]
            for key in ('shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes'):
                if observed[key] != layout[key]:
                    raise ValueError('GMS/descriptor parameter contract mismatch: ' + prefix + attr + ':' + key)
            role = routing_bias_role(name, attr)
            if role is not None:
                gate = contracts.get(role['gate_parameter'])
                if gate is None or gate.get('tensor_type', 'parameter') != 'parameter':
                    raise ValueError('GMS has no independent routing gate alias: ' + role['gate_parameter'])
                if any(type(value.get('offset_bytes')) is not int or value['offset_bytes'] < 0
                        for value in (gate, observed)):
                    raise ValueError('GMS routing gate/correction byte offsets must be exact nonnegative integers.')
                for key in ('shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes'):
                    if gate[key] != observed[key]:
                        raise ValueError('GMS routing gate/correction alias mismatch: ' + prefix + attr + ':' + key)
        if row['kind'] == 'modelopt-attention':
            runtime = row['attention_runtime']
            for attr in SCALE_BUFFERS:
                if contracts.get(prefix + attr) != runtime['buffers'][attr]['contract']:
                    raise ValueError('GMS/descriptor attention buffer contract mismatch: ' + prefix + attr)
            for attr in HOST_SCALE_TENSORS:
                if contracts.get(prefix + attr) != runtime['host_tensors'][attr]['contract']:
                    raise ValueError('GMS/descriptor attention host tensor contract mismatch: ' + prefix + attr)


def prepare_reader_skeleton(model, manifest, contracts, expected_identity):
    """Prepare allowlisted final meta layouts; keep the stock GMS guard intact."""
    import torch
    if manifest.get('identity') != expected_identity:
        raise ValueError('Stale or foreign reader descriptor identity.')
    if manifest.get('reader_ready') is not True or manifest.get('unhandled_modules'):
        raise ValueError('Writer manifest includes unsupported reader runtime state.')
    validate_tensor_contracts(manifest, contracts)
    modules = dict(model.named_modules())
    actual_names = {n for n, layer in modules.items() if _kind(layer) is not None}
    if actual_names != set(manifest['modules']):
        raise ValueError('Reader/writer complete ModelOpt module inventory differs.')
    plans = []
    for name, row in manifest['modules'].items():
        layer = modules[name]
        if (class_key(layer) != row['layer_class'] or
                class_key(layer.quant_method) != row['quant_method_class'] or _kind(layer) != row['kind']):
            raise ValueError('Reader model/backend differs from writer: ' + name)
        if row['kind'] in ('humming-linear', 'cutlass-fp8') and repr(layer.quant_method.spec) != row['quant_spec_repr']:
            raise ValueError('Reader/writer quantization scheme differs: ' + name)
        if any(p is not None and not p.is_meta for p in layer._parameters.values()):
            raise ValueError('Reader skeleton already contains materialized parameters.')
        params = {attr: None for attr in row['none_parameters']}
        for attr, layout in row['parameters'].items():
            dtype = layout['dtype']
            role = routing_bias_role(name, attr)
            if role is not None:
                parameter_layout(layer, name, attr, layer._parameters.get(attr), modules)
                _validate_routing_bias_layout(layout, role, name + '.' + attr)
            if dtype not in TORCH_DTYPES or (role is None and layout['requires_grad'] is not False):
                raise ValueError('Unreviewed reader parameter dtype/gradient contract.')
            tensor = torch.empty_strided(layout['shape'], layout['stride'],
                dtype=getattr(torch, dtype.removeprefix('torch.')), device='meta')
            param = torch.nn.Parameter(tensor, requires_grad=layout['requires_grad'])
            for key, value in layout['attrs'].items():
                if key not in PARAM_ATTRS or type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('Unreviewed reader parameter layout attribute.')
                setattr(param, key, value)
            params[attr] = param
        plans.append((layer, params))
    # Validate/allocate all meta plans before rebinding any layer.
    for layer, params in plans:
        layer._parameters.clear()
        layer._parameters.update(params)


def restore_reader_runtime(model, manager, manifest):
    """Rebuild runtime objects from final parameters without weight transforms.

    Must run after stock GMS materialization, outside every GMS pool. The
    caller must retain the manifest identity/GMS-contract checks and validate
    the private workspaces before allowing warm-up.
    """
    import torch
    from gpu_memory_service.integrations.vllm.workshop_humming import (
        _pool_managers, rebind_humming_locks,
    )
    _pool_managers(manager)  # Refuse before allocating any reader workspace.
    modules = dict(model.named_modules())
    counts = {'humming-linear': 0, 'humming-moe': 0, 'cutlass-fp8': 0}
    for name, row in manifest['modules'].items():
        layer, qm = modules[name], modules[name].quant_method
        if any(layer._parameters.get(attr, 'missing') is not None for attr in row['none_parameters']):
            raise ValueError('Reader retained an unexpected optional parameter: ' + name)
        for attr, layout in row['parameters'].items():
            tensor = layer._parameters[attr]
            if tensor.is_meta or not tensor.is_cuda:
                raise ValueError('Reader parameter is not materialized on CUDA: ' + name + '.' + attr)
            current = parameter_layout(layer, name, attr, tensor, modules, require_object_alias=False)
            if any(current[k] != layout[k] for k in ('shape', 'stride', 'dtype', 'requires_grad')):
                raise ValueError('Imported reader parameter layout mismatch: ' + name + '.' + attr)
            if allocation_identity(tensor, manager) != {k: layout[k] for k in ('allocation_id', 'offset_bytes')}:
                raise ValueError('Imported reader parameter allocation mismatch: ' + name + '.' + attr)
            role = routing_bias_role(name, attr)
            if role is not None:
                gate_name, gate_attr = role['gate_parameter'].rsplit('.', 1)
                gate_tensor = modules[gate_name]._parameters[gate_attr]
                if allocation_identity(gate_tensor, manager) != allocation_identity(tensor, manager):
                    raise ValueError('Imported routing correction lost its gate allocation alias: ' + name + '.' + attr)
            for key, value in layout['attrs'].items():
                setattr(tensor, key, value)
        if row['kind'] == 'humming-linear':
            layer.weight_schema = decode(row['weight_schema'])
            qm.kernel.layer_config = decode(row['layer_config'])
            qm.kernel.layer_config.check_device(layer.weight.device)
            qm.kernel.compute_config = row['compute_config']
            qm.kernel.locks = torch.zeros(1024, dtype=torch.int32, device=layer.weight.device)
            layer.is_w4a16_nvfp4 = row['is_w4a16_nvfp4']
        elif row['kind'] == 'humming-moe':
            layer.weight_schemas = decode(row['weight_schemas'])
            layer.input_schemas = decode(row['input_schemas'])
            layer.humming_configs = decode(row['humming_configs'])
            if qm.experts_cls.__module__ + ':' + qm.experts_cls.__name__ != row['experts_class']:
                raise ValueError('Reader MoE expert selection changed.')
            build_quant_config = importlib.import_module(
                'vllm.model_executor.layers.quantization.utils.humming.moe').get_humming_moe_quant_config
            qm.moe_quant_config = build_quant_config(layer,
                gemm1_alpha=getattr(layer, 'swiglu_alpha', None),
                gemm1_beta=getattr(layer, 'swiglu_beta', None),
                gemm1_clamp_limit=getattr(layer, 'swiglu_limit', None))
            config = qm.moe_quant_config
            for cfg_attr, layer_prefix in (('_w1', 'w13'), ('_w2', 'w2')):
                desc = getattr(config, cfg_attr)
                for desc_attr, param_suffix in (('scale', 'weight_scale'),
                        ('alpha_or_gscale', 'weight_scale_2'), ('zp', 'zero_point'), ('bias', 'bias')):
                    if getattr(desc, desc_attr) is not getattr(layer, layer_prefix + '_' + param_suffix, None):
                        raise ValueError('Reader MoE quant descriptor retains a foreign tensor alias.')
            for prefix, layer_prefix in (('w1', 'w13'), ('w2', 'w2')):
                for suffix in ('input_scale', 'input_scale_2'):
                    if getattr(config, prefix + '_' + suffix) is not getattr(layer, layer_prefix + '_' + suffix, None):
                        raise ValueError('Reader MoE input descriptor retains a foreign tensor alias.')
            build = importlib.import_module(
                'vllm.model_executor.layers.quantization.utils.humming.moe').make_humming_moe_kernel
            qm.moe_kernel = build(moe_quant_config=qm.moe_quant_config, moe_config=qm.moe,
                experts_cls=qm.experts_cls, routing_tables=layer._expert_routing_tables())
            # Deliberately DO NOT call any process_weights_after_loading hook.
        elif row['kind'] == 'cutlass-fp8':
            qm.kernel.logical_output_size = row['logical_output_size']
            layer.is_w4a16_nvfp4 = row['is_w4a16_nvfp4']
        elif row['kind'] == 'modelopt-attention':
            _restore_attention(layer, row, manager)
        else:
            raise ValueError('Unknown reader runtime kind.')
        counts[row['kind']] = counts.get(row['kind'], 0) + 1
    if counts != manifest['counts']:
        raise ValueError('Reader runtime reconstruction inventory mismatch.')
    incomplete = [n for n, t in model.named_parameters() if t.is_meta]
    incomplete += [n for n, t in model.named_buffers() if t.is_meta]
    if incomplete:
        raise ValueError('Reader still has unmaterialized model state: ' + str(incomplete[:10]))
    workspace_rows = rebind_humming_locks(model, manager)
    if any(not row['already_private'] for row in workspace_rows):
        raise ValueError('A reconstructed reader workspace was allocated in a GMS pool.')
    return counts


def patch_descriptor_loader(source):
    """Compose onto a NEW copy of the frozen a5 writer loader, never edit a5.

    The stock materializer is retained. Meta postprocessing is skipped because
    every supported transformed layout comes from the versioned writer manifest
    and must match independent committed GMS metadata before materialization.
    """
    replacements = [
        ('    _store_pending_gms_write(gms_client, stats, rebound_bytes, retained_gms_tensors)\n',
         '    from gpu_memory_service.integrations.vllm.workshop_descriptors import prepare_writer_manifest\n'
         '    prepare_writer_manifest(model, gms_client)\n'
         '    _store_pending_gms_write(gms_client, stats, rebound_bytes, retained_gms_tensors)\n'),
        ('        publish_gms_write(gms_client)\n',
         '        publish_gms_write(gms_client)\n'
         '        from gpu_memory_service.integrations.vllm.workshop_descriptors import publish_writer_manifest\n'
         '        publish_writer_manifest(gms_client)\n'),
        ('        model = _create_meta_model(vllm_config, model_config)\n'
         '        materialize_module_from_gms(gms_client, model, device_index=device_index)\n',
         '        model = _create_meta_model(vllm_config, model_config)\n'
         '        from gpu_memory_service.integrations.vllm.workshop_descriptors import (\n'
         '            read_committed_manifest, prepare_reader_skeleton, restore_reader_runtime)\n'
         '        manifest, contracts, identity = read_committed_manifest(gms_client)\n'
         '        prepare_reader_skeleton(model, manifest, contracts, identity)\n'
         '        materialize_module_from_gms(gms_client, model, device_index=device_index)\n'
         '        restore_reader_runtime(model, gms_client, manifest)\n'),
        ('    try:\n'
         '        process_weights_after_loading(model, model_config, meta_device)\n'
         '    except Exception as e:\n'
         '        logger.debug("[GMS] Post-processing on meta tensors: %s", e)\n',
         '    # The fresh writer manifest supplies final reviewed layouts; do not\n'
         '    # run a partially failing or duplicate weight transform on the reader.\n'),
    ]
    result = source
    for old, new in replacements:
        if result.count(old) != 1:
            raise ValueError('Unexpected pinned GMS loader descriptor integration anchor.')
        result = result.replace(old, new)
    compile(result, 'gpu_memory_service/integrations/vllm/model_loader.py', 'exec')
    return result
