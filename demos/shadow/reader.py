"""Offline reader candidate: reproduce one source-verified FP8 meta layout.

This is deliberately NOT a complete GMS reader implementation. In particular,
it does not rebuild Humming linear/MoE runtime objects, authorize a deployment,
or establish that a reader can park, promote, or serve correct responses.
"""
from __future__ import annotations

import logging

MODEL_OPT = 'vllm.model_executor.layers.quantization.modelopt'
QUANT_UTILS = 'vllm.model_executor.layers.quantization.utils.quant_utils'
LM_HEAD_MODULE = 'vllm.model_executor.layers.vocab_parallel_embedding'
LM_HEAD = 'language_model.lm_head'
RAW_WEIGHT_SHAPE = (65536, 4096)
FINAL_WEIGHT_SHAPE = (4096, 65536)
FINAL_WEIGHT_STRIDE = (1, 4096)
logger = logging.getLogger(__name__)


def _exact_type(value, module, name):
    return type(value).__module__ == module and type(value).__name__ == name


def prepare_known_meta_parameter(name, layer, attr, param, tensor):
    """Return a layout-correct *meta* parameter for the pinned TP2 lm_head.

    The existing GMS shape/dtype guard must still run after this function.
    No committed tensor is reshaped, transposed, copied, or changed here.
    Unknown tensors retain the original parameter and the original guard.

    ModelOpt KFp8StaticTensor.process performs the transpose and scalar
    reductions on the writer. Meta processing aborts at its value-dependent
    branches. Reproduce only the layout effect established by that source,
    checking the specific quant method, both QuantKeys, dimensions and strides.
    """
    if (name != LM_HEAD + '.' + attr or
            attr not in ('weight', 'input_scale', 'weight_scale') or
            not param.is_meta or param.shape == tensor.shape):
        return param
    import torch
    from importlib import import_module
    qm = getattr(layer, 'quant_method', None)
    spec = getattr(qm, 'spec', None)
    key = import_module(QUANT_UTILS).kFp8StaticTensorSym
    known_scheme = (
        _exact_type(layer, LM_HEAD_MODULE, 'ParallelLMHead') and
        _exact_type(qm, MODEL_OPT, 'ModelOptLinearMethod') and
        getattr(spec, 'weight', None) is key and
        getattr(spec, 'activation', None) is key and
        _exact_type(getattr(qm, 'wkey', None), MODEL_OPT, 'KFp8StaticTensor') and
        _exact_type(getattr(qm, 'akey', None), MODEL_OPT, 'KFp8StaticTensor') and
        getattr(layer, 'input_size_per_partition', None) == 4096 and
        getattr(layer, 'output_size_per_partition', None) == 65536)
    if not known_scheme or not tensor.is_cuda or tensor.is_meta:
        return param
    if attr == 'weight':
        known_layout = (
            tuple(param.shape) == RAW_WEIGHT_SHAPE and
            tuple(tensor.shape) == FINAL_WEIGHT_SHAPE and
            param.dtype == tensor.dtype == torch.float8_e4m3fn and
            tuple(param.stride()) == (4096, 1) and
            tuple(tensor.stride()) == FINAL_WEIGHT_STRIDE and
            getattr(param, 'input_dim', None) == 1 and
            getattr(param, 'output_dim', None) == 0)
        if not known_layout:
            return param
        replacement = torch.nn.Parameter(param.t(), requires_grad=param.requires_grad)
        replacement.input_dim, replacement.output_dim = 0, 1
    else:
        known_layout = (
            tuple(param.shape) == (1,) and tuple(tensor.shape) == () and
            param.dtype == tensor.dtype == torch.float32 and
            param.numel() == tensor.numel() == 1 and
            tuple(param.stride()) == (1,) and tuple(tensor.stride()) == ())
        if not known_layout:
            return param
        replacement = torch.nn.Parameter(param.reshape(()), requires_grad=param.requires_grad)
    logger.info('[WORKSHOP GMS] Verified FP8 meta layout: %s %s -> %s, stride=%s',
                name, tuple(param.shape), tuple(replacement.shape), tuple(replacement.stride()))
    return replacement


def patch_materializer(source):
    """Insert the narrow meta preparation before the unchanged GMS guard."""
    anchor = ('            param = mod._parameters[attr]\n'
              '            if param is not None:\n'
              '                if param.shape != tensor.shape or param.dtype != tensor.dtype:\n')
    if source.count(anchor) != 1:
        raise ValueError('Unexpected original GMS parameter materialization contract.')
    replacement = (
        '            param = mod._parameters[attr]\n'
        '            if param is not None:\n'
        '                from gpu_memory_service.integrations.vllm.workshop_reader import prepare_known_meta_parameter\n'
        '                param = prepare_known_meta_parameter(name, mod, attr, param, tensor)\n'
        '                if param.shape != tensor.shape or param.dtype != tensor.dtype:\n')
    result = source.replace(anchor, replacement)
    compile(result, 'gpu_memory_service/client/torch/module.py', 'exec')
    return result
