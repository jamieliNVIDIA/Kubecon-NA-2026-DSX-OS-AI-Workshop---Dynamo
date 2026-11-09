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

VERSION = 'workshop-super-vl-humming-runtime-v1'
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


def prepare_writer_manifest(model, manager):
    global _pending_manifest
    if _pending_manifest is not None:
        raise ValueError('A writer runtime manifest is already awaiting GMS publication.')
    value = export_runtime_manifest(model, manager, runtime_identity())
    validate_tensor_contracts(value, gms_parameter_contracts(manager))
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
    validate_tensor_contracts(value, gms_parameter_contracts(manager))
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
    contracts = gms_parameter_contracts(manager)
    validate_tensor_contracts(value, contracts)
    return value, contracts, identity


def tensor_layout(tensor):
    if str(tensor.dtype) not in TORCH_DTYPES or tensor.requires_grad:
        raise ValueError('Unexpected inference parameter dtype/gradient contract.')
    shape, stride = tuple(tensor.shape), tuple(tensor.stride())
    if any(type(x) is not int or x < 0 for x in shape + stride):
        raise ValueError('Unsupported parameter shape/stride.')
    attrs = {n: getattr(tensor, n) for n in PARAM_ATTRS if hasattr(tensor, n)}
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in attrs.values()):
        raise ValueError('Unexpected parameter layout attribute.')
    return {'shape': list(shape), 'stride': list(stride), 'dtype': str(tensor.dtype),
            'requires_grad': False, 'attrs': attrs}


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
    return None


def export_runtime_manifest(model, manager, identity):
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
    for name, layer in model.named_modules():
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
                params[attr] = dict(tensor_layout(tensor), **allocation_identity(tensor, manager))
        row = {'kind': kind, 'layer_class': class_key(layer), 'quant_method_class': class_key(qm),
               'parameters': params,
               'none_parameters': sorted(attr for attr, tensor in layer._parameters.items() if tensor is None)}
        if kind != 'humming-moe':
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
        else:
            row.update(kernel_class=CUTLASS_FP8, logical_output_size=qm.kernel.logical_output_size,
                is_w4a16_nvfp4=layer.is_w4a16_nvfp4)
            shape = tuple(layer.weight.shape)
            if (len(shape) != 2 or any(dim % 16 for dim in shape) or
                    qm.kernel.logical_output_size != shape[1]):
                raise ValueError('Only source-reviewed unpadded Cutlass FP8 layers are supported.')
        records[name] = row
        counts[kind] += 1
    if (counts['humming-linear'] != 80 or counts['humming-moe'] != 40 or
            counts['cutlass-fp8'] < 1):
        raise ValueError('Unexpected Super VL writer module inventory: ' + str(counts))
    manifest = {'version': VERSION, 'identity': identity, 'modules': records, 'counts': counts,
                'unhandled_modules': unhandled, 'reader_ready': not bool(unhandled)}
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
    for name, row in manifest['modules'].items():
        prefix = name + '.'
        expected_names = {prefix + attr for attr in row['parameters']}
        observed_names = {n for n in contracts if n.startswith(prefix) and '.' not in n[len(prefix):]}
        if expected_names != observed_names:
            raise ValueError('GMS/descriptor parameter inventory mismatch: ' + name)
        for attr, layout in row['parameters'].items():
            observed = contracts[prefix + attr]
            for key in ('shape', 'stride', 'dtype', 'allocation_id', 'offset_bytes'):
                if observed[key] != layout[key]:
                    raise ValueError('GMS/descriptor parameter contract mismatch: ' + prefix + attr + ':' + key)


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
        if row['kind'] != 'humming-moe' and repr(layer.quant_method.spec) != row['quant_spec_repr']:
            raise ValueError('Reader/writer quantization scheme differs: ' + name)
        if any(p is not None and not p.is_meta for p in layer._parameters.values()):
            raise ValueError('Reader skeleton already contains materialized parameters.')
        params = {attr: None for attr in row['none_parameters']}
        for attr, layout in row['parameters'].items():
            dtype = layout['dtype']
            if dtype not in TORCH_DTYPES or layout['requires_grad'] is not False:
                raise ValueError('Unreviewed reader parameter dtype/gradient contract.')
            tensor = torch.empty_strided(layout['shape'], layout['stride'],
                dtype=getattr(torch, dtype.removeprefix('torch.')), device='meta')
            param = torch.nn.Parameter(tensor, requires_grad=False)
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
            current = tensor_layout(tensor)
            if any(current[k] != layout[k] for k in ('shape', 'stride', 'dtype', 'requires_grad')):
                raise ValueError('Imported reader parameter layout mismatch: ' + name + '.' + attr)
            if allocation_identity(tensor, manager) != {k: layout[k] for k in ('allocation_id', 'offset_bytes')}:
                raise ValueError('Imported reader parameter allocation mismatch: ' + name + '.' + attr)
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
            qm.moe_quant_config = qm.get_fused_moe_quant_config(layer)
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
        else:
            raise ValueError('Unknown reader runtime kind.')
        counts[row['kind']] += 1
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
