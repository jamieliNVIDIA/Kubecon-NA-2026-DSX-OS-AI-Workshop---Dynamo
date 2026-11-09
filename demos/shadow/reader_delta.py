"""Exact source-equivalence proof for the narrow native-warmup reader repair."""
from __future__ import annotations

import ast
import hashlib

import demos.shadow.compat.native_config_delta as v5

READER_REVISION = 'workshop-humming-reader-v6-optional-input-state'
RESTORE_SOURCE = '''def restore_humming_optional_input_state(layer, row):
    """Restore the exact source-prescribed plain None state for this final layout.

    Humming removes raw input-scale parameters; ModelOpt then calls its imported
    vllm.model_executor.utils.replace_parameter(..., None), whose None branch
    sets ordinary attributes. Native warmup still queries that generic wrapper.
    This is not a checkpoint parameter or permission to replace live tensors.
    """
    expected = {'e_score_correction_bias', 'w13_weight', 'w13_weight_scale', 'w13_weight_scale_2',
                'w2_weight', 'w2_weight_scale', 'w2_weight_scale_2'}
    if (row.get('kind') != 'humming-moe' or set(row['parameters']) != expected or
            row['none_parameters'] or set(layer._parameters) != expected):
        raise ValueError('Optional input-state restoration requires the exact final seven-parameter Humming layout.')
    plan = []
    for prefix in ('w13', 'w2'):
        schema = layer.input_schemas[prefix]
        if (class_key(schema) != 'humming.schema.humming:HummingInputSchema' or
                schema.quant_method != 'humming' or schema.a_dtype is not None or schema.input_quant_mode is not None or
                schema.input_scale_dtype is not None or type(schema.input_scale_group_size) is not int or
                schema.input_scale_group_size != 0 or
                schema.static_tensor_scale_name is not None):
            raise ValueError('Only observed disabled/null Humming input schemas may restore optional None state.')
        name = prefix + '_input_scale'
        if (name in layer._parameters or name in layer._buffers or getattr(layer, name, None) is not None or
                (hasattr(layer, name) and name not in layer.__dict__)):
            raise ValueError('Refusing to replace registered or non-None Humming input state: ' + name)
        plan.append(name)
    # Check both sublayers before any mutation. Setting None after the old
    # parameter was removed matches the exact imported native helper's branch.
    for name in plan:
        setattr(layer, name, None)
        if name not in layer.__dict__ or layer.__dict__[name] is not None:
            raise ValueError('Humming optional input state was not restored as an ordinary None attribute: ' + name)


'''


def validate_reader_delta(original, candidate):
    intermediate = original.replace(v5.OLD, v5.NEW)
    anchor = 'VERSION = ' + repr(v5.BASE_VERSION) + '\n'
    intermediate = intermediate.replace(anchor, anchor + v5.REVISION_LINE)
    proof = v5.validate_reader_delta(original, intermediate)
    expected = intermediate.replace(v5.REVISION_LINE,
        'READER_ADAPTER_REVISION = ' + repr(READER_REVISION) + '\n')
    marker = 'def restore_reader_runtime(model, manager, manifest):\n'
    if expected.count(marker) != 1:
        raise ValueError('Accepted reader has an unexpected runtime restoration anchor.')
    expected = expected.replace(marker, RESTORE_SOURCE + marker)
    marker = "            layer.humming_configs = decode(row['humming_configs'])\n"
    if expected.count(marker) != 1:
        raise ValueError('Accepted reader has an unexpected Humming schema anchor.')
    expected = expected.replace(marker, marker + '            restore_humming_optional_input_state(layer, row)\n')
    if candidate != expected:
        raise ValueError('v6 reader delta includes unreviewed writer/schema/reader changes.')
    before, after = ast.parse(original), ast.parse(candidate)
    for name in proof['unchanged_functions']:
        old = next(node for node in before.body if isinstance(node, ast.FunctionDef) and node.name == name)
        new = next(node for node in after.body if isinstance(node, ast.FunctionDef) and node.name == name)
        if ast.get_source_segment(original, old) != ast.get_source_segment(candidate, new):
            raise ValueError('v6 changed a writer/codec/layout/lifecycle function: ' + name)
    compile(candidate, 'reviewed-native-warmup-reader-only-helper', 'exec')
    return dict(proof, reader_adapter_revision=READER_REVISION,
        reader_helper_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
        new_reader_functions=['restore_humming_optional_input_state'],
        change='v5 native Humming config callback plus exact final ordinary None input state for native warmup',
        scope='Source equivalence only; actual imported None helper/generic/native warmup CPU and GPU gates remain separate')
