"""Narrow, inspectable experimental GMS adaptations for Super VL.

These are source transformations, not a promise that the resulting engine is
compatible. Every candidate must pass active/standby and recovery separately.
"""
from __future__ import annotations


def singleton_meta_scale(source):
    """Accept a postprocessed scalar only for an unmaterialized one-element scale.

    NVFP4 postprocessing reduces input_scale from (1,) to (). Some meta-device
    postprocessing paths stop before that reduction. Committed writer metadata
    supplies the final shape. Do not relax dtype or non-scale tensor checks.
    """
    anchor = '                if param.shape != tensor.shape or param.dtype != tensor.dtype:\n'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected installed GMS shape guard; inspect source before patching.')
    replacement = (
        '                singleton_scale = (param.is_meta and attr.endswith("scale")\n'
        '                    and param.numel() == tensor.numel() == 1\n'
        '                    and param.dtype == tensor.dtype)\n'
        '                if (param.shape != tensor.shape and not singleton_scale) or param.dtype != tensor.dtype:\n'
    )
    result = source.replace(anchor, replacement)
    compile(result, 'gpu_memory_service/client/torch/module.py', 'exec')
    return result
