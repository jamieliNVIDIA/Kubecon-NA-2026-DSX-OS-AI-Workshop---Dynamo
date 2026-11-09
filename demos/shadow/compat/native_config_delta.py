"""Prove a source-reviewed reader-only change preserves writer format and code.

Pure offline validation. It never loads a model, deploys or accepts a new writer
qualification. The accepted v4 writer receipts remain the basis; the full
candidate must additionally freeze and review this exact reader delta.
"""
from __future__ import annotations

import ast
import hashlib

BASE_VERSION = 'workshop-super-vl-humming-runtime-v4-routing-bias'
READER_REVISION = 'workshop-humming-reader-v5-native-config-builder'
OLD = '            qm.moe_quant_config = qm.get_fused_moe_quant_config(layer)\n'
NEW = (
    '            build_quant_config = importlib.import_module(\n'
    "                'vllm.model_executor.layers.quantization.utils.humming.moe').get_humming_moe_quant_config\n"
    '            qm.moe_quant_config = build_quant_config(layer,\n'
    "                gemm1_alpha=getattr(layer, 'swiglu_alpha', None),\n"
    "                gemm1_beta=getattr(layer, 'swiglu_beta', None),\n"
    "                gemm1_clamp_limit=getattr(layer, 'swiglu_limit', None))\n"
)
REVISION_LINE = 'READER_ADAPTER_REVISION = ' + repr(READER_REVISION) + '\n'


def validate_reader_delta(original, candidate):
    if original.count(OLD) != 1:
        raise ValueError('Accepted writer helper has an unexpected reader callback anchor.')
    expected = original.replace(OLD, NEW)
    anchor = 'VERSION = ' + repr(BASE_VERSION) + '\n'
    if expected.count(anchor) != 1:
        raise ValueError('Accepted writer descriptor format version differs.')
    expected = expected.replace(anchor, anchor + REVISION_LINE)
    if candidate != expected:
        raise ValueError('Reader delta includes unreviewed writer/schema/code changes.')
    original_tree, candidate_tree = ast.parse(original), ast.parse(candidate)
    functions = [node.name for node in original_tree.body if isinstance(node, ast.FunctionDef)]
    for name in functions:
        if name == 'restore_reader_runtime':
            continue
        before = next(node for node in original_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        after = next(node for node in candidate_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        if ast.get_source_segment(original, before) != ast.get_source_segment(candidate, after):
            raise ValueError('Writer/codec/lifecycle function changed: ' + name)
    compile(candidate, 'reviewed-reader-only-helper', 'exec')
    return {'descriptor_version': BASE_VERSION, 'reader_adapter_revision': READER_REVISION,
        'writer_helper_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'reader_helper_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
        'unchanged_functions': [name for name in functions if name != 'restore_reader_runtime'],
        'writer_export_and_schema_unchanged': True,
        'change': 'Only Humming MoE reader config callback and explicit adapter revision metadata',
        'scope': 'Source equivalence only; actual-source CPU and GPU reader/promotion gates remain separate'}
