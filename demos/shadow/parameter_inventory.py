"""Metadata-only final-parameter diagnostic, before any descriptor validation.

This does not serialize tensor contents, call CUDA/NCCL, relax contracts, or
produce reader descriptors. JSONL is flushed before the strict exporter can
fail; fresh rank files coordinate a bounded CPU/filesystem-only rendezvous.
"""
from __future__ import annotations

from collections import Counter
from enum import Enum
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time

VERSION = 'workshop-final-parameter-inventory-v1'
PREFIX = 'WORKSHOP_PARAMETER_INVENTORY_V1 '
LAYOUT_ATTRS = ('input_dim', 'output_dim', 'packed_dim', 'packed_factor',
    '_input_dim', '_output_dim', '_packed_dim', '_packed_factor',
    'marlin_tile_size', '_marlin_tile_size', 'group_size', 'is_transposed',
    'needs_scalar_to_array', 'is_metadata', 'is_sharded_weight')


def class_key(value):
    return type(value).__module__ + ':' + type(value).__name__


def typed_value(value):
    """Record scalar metadata exactly; never repr/item/copy a tensor or object."""
    result = {'type': class_key(value)}
    if value is None or type(value) in (bool, int, str):
        result['value'] = value
    elif type(value) is float:
        result['value'] = value if math.isfinite(value) else str(value)
    elif type(value) is Fraction:
        result.update(numerator=value.numerator, denominator=value.denominator)
    elif isinstance(value, Enum):
        result.update(name=value.name, value=typed_value(value.value))
    elif type(value) in (list, tuple) and len(value) <= 32:
        result['value'] = [typed_value(item) for item in value]
    else:
        # Tensor/function/opaque metadata is identified by type only. Its repr
        # can copy CUDA data, invoke arbitrary code or contain mutable IDs.
        result['value_not_read'] = True
    return result


def _exception_metadata(field, error):
    args = list(error.args[:8])
    return {'field': field, 'exception_type': class_key(error),
        'message': args[0] if len(args) == 1 and type(args[0]) is str else '<non-string exception arguments not rendered>',
        'arguments': [typed_value(arg) for arg in args]}


def _json_metadata(value, field, errors):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return [_json_metadata(item, field + '[' + str(index) + ']', errors) for index, item in enumerate(value)]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _json_metadata(item, field + '.' + key, errors) for key, item in value.items()}
    errors.append({'field': field, 'unexpected_metadata_type': class_key(value)})
    return typed_value(value)


def _metadata_text(value):
    if type(value) is str or class_key(value) in ('torch:dtype', 'torch:device', 'torch:layout'):
        return str(value)
    raise TypeError('Metadata text field returned an unreviewed object type: ' + class_key(value))


def _read(errors, field, callback):
    try:
        return _json_metadata(callback(), field, errors)
    except Exception as error:
        record = _exception_metadata(field, error)
        errors.append(record)
        return {'inspection_error': record}


def parameter_inventory(model, identity):
    """Inspect all direct parameter slots, retaining shared module/param aliases."""
    rows, seen, inspection_errors = [], {}, []
    # Default named_parameters() de-duplicates aliases. Direct owned slots plus
    # remove_duplicate=False retain both tied parameters and module aliases.
    for owner, layer in model.named_modules(remove_duplicate=False):
        errors = []
        # These objects are never rendered, serialized or run. Only their
        # fixed Python type names belong in the diagnostic rows.
        try:
            quant = getattr(layer, 'quant_method', None)
            kernel = getattr(quant, 'kernel', None)
            moe_kernel = getattr(quant, 'moe_kernel', None)
        except Exception as error:
            errors.append(_exception_metadata('quant_method/kernel', error))
            quant = kernel = moe_kernel = None
        common = {'owner': owner, 'module_class': class_key(layer),
            'quant_method_class': class_key(quant), 'kernel_class': class_key(kernel),
            'moe_kernel_class': class_key(moe_kernel)}
        for attr, tensor in layer._parameters.items():
            row_errors = list(errors)
            full_name = owner + '.' + attr if owner else attr
            row = dict(common, parameter=attr, name=full_name, is_none=tensor is None)
            if tensor is not None:
                row['parameter_class'] = class_key(tensor)
                row['alias_of'] = seen.get(id(tensor))
                seen.setdefault(id(tensor), full_name)
                for field, callback in (
                    ('dtype', lambda: _metadata_text(tensor.dtype)),
                    ('requires_grad', lambda: tensor.requires_grad),
                    ('shape', lambda: list(tensor.shape)),
                    ('stride', lambda: list(tensor.stride())),
                    ('device', lambda: _metadata_text(tensor.device)),
                    ('is_cuda', lambda: tensor.is_cuda),
                    ('is_meta', lambda: tensor.is_meta),
                    ('layout', lambda: _metadata_text(tensor.layout)),
                    ('storage_offset', lambda: tensor.storage_offset()),
                    ('element_size', lambda: tensor.element_size()),
                    ('is_contiguous', lambda: tensor.is_contiguous()),
                ):
                    row[field] = _read(row_errors, field, callback)
                attributes = {}
                for name in LAYOUT_ATTRS:
                    try:
                        value = getattr(tensor, name)
                    except AttributeError:
                        continue
                    except Exception as error:
                        issue = _exception_metadata(name, error)
                        row_errors.append(issue)
                        attributes[name] = {'inspection_error': issue}
                    else:
                        attributes[name] = typed_value(value)
                row['layout_attributes'] = attributes
                row['instance_attribute_types'] = _read(row_errors, '__dict__', lambda: {
                    name: class_key(value) for name, value in vars(tensor).items()})
            if row_errors:
                row['inspection_errors'] = row_errors
                inspection_errors.extend(dict(error, parameter=full_name) for error in row_errors)
            # Refuse non-JSON metadata without hiding which property failed.
            # The ordinary shape/stride/device paths are scalar-only PyTorch
            # metadata; this never touches tensor contents.
            json.dumps(row, allow_nan=False)
            rows.append(row)
    actual = [row for row in rows if not row['is_none']]
    summary = {'slots': len(rows), 'parameters': len(actual),
        'cuda_parameters': sum(row.get('is_cuda') is True for row in actual),
        'meta_parameters': sum(row.get('is_meta') is True for row in actual),
        'none_slots': len(rows) - len(actual),
        'aliases': sum(row['alias_of'] is not None for row in actual),
        'dtypes': dict(Counter(str(row.get('dtype')) for row in actual)),
        'requires_grad': dict(Counter(str(row.get('requires_grad')) for row in actual)),
        'inspection_errors': inspection_errors}
    return {'version': VERSION, 'identity': identity, 'pid': os.getpid(),
        'generation': secrets.token_hex(16),
        'created_at_ns': time.time_ns(), 'stage': 'final-after-humming-rebind-and-gms-prune-before-export',
        'metadata_only': True, 'tensor_contents_read': False, 'cuda_operations': False,
        'summary': summary, 'parameters': rows}


def _publish(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()
    temporary = path.with_suffix('.pending-' + str(os.getpid()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Never replace another generation's inventory.
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def emit_writer_parameter_inventory(model, identity, directory, timeout=60, stream=None):
    """Flush every row, publish rank file, then wait for both TP rank inventories.

    All ranks complete this before any exporter dtype/grad/layout guard. A
    process-generation mismatch, stale file, inspection error or peer timeout
    stops the diagnostic; it does not make a reader-ready assertion.
    """
    if (identity.get('tensor_parallel_size') != 2 or
            type(identity.get('tp_rank')) is not int or identity['tp_rank'] not in (0, 1)):
        raise ValueError('Final parameter inventory requires the actual pinned TP2 identity.')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Final parameter inventory timeout must be finite and positive.')
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError('Final parameter inventory needs an explicit Pod-shared absolute path.')
    stream = sys.stdout if stream is None else stream
    inventory = parameter_inventory(model, identity)
    rank = identity['tp_rank']
    def emit(event, **values):
        print(PREFIX + json.dumps(dict(event=event, tp_rank=rank,
            candidate=identity['candidate'], **values), sort_keys=True, allow_nan=False),
            file=stream, flush=True)
    emit('begin', version=VERSION, pid=inventory['pid'], stage=inventory['stage'])
    for row in inventory['parameters']:
        emit('parameter', **row)
    emit('summary', **inventory['summary'])
    path = directory / ('parameter-inventory-rank-' + str(rank) + '.json')
    digest = _publish(path, inventory)
    emit('published', path=str(path), sha256=digest)
    deadline = time.monotonic() + timeout
    acknowledged = False
    while True:
        peers = []
        for other in (0, 1):
            peer = directory / ('parameter-inventory-rank-' + str(other) + '.json')
            if not peer.exists():
                break
            value = json.loads(peer.read_text())
            expected = dict(identity, tp_rank=other)
            if value.get('version') != VERSION or value.get('identity') != expected:
                raise ValueError('Stale or foreign final-parameter inventory at ' + str(peer))
            generation = value.get('generation')
            if (type(generation) is not str or len(generation) != 32 or
                    any(char not in '0123456789abcdef' for char in generation)):
                raise ValueError('Final-parameter inventory has no process generation nonce.')
            if other == rank and value.get('pid') != os.getpid():
                raise ValueError('Final-parameter inventory belongs to another local process generation.')
            peers.append(value)
        if len(peers) == 2:
            if any(peer['summary']['inspection_errors'] for peer in peers):
                raise ValueError('Final-parameter inventory recorded metadata inspection errors; inspect all rank rows.')
            generations = {str(other): value['generation'] for other, value in enumerate(peers)}
            if not acknowledged:
                # An inventory alone cannot prove that its process is still
                # alive. Both ranks must acknowledge the fresh token pair; a
                # same-candidate leftover peer cannot acknowledge a new rank.
                ack = {'version': VERSION, 'identity': identity, 'generations': generations}
                _publish(directory / ('parameter-inventory-ack-rank-' + str(rank) + '.json'), ack)
                acknowledged = True
            acks = []
            for other in (0, 1):
                peer_ack = directory / ('parameter-inventory-ack-rank-' + str(other) + '.json')
                if not peer_ack.exists():
                    break
                value = json.loads(peer_ack.read_text())
                if (value.get('version') != VERSION or value.get('identity') != dict(identity, tp_rank=other) or
                        value.get('generations') != generations):
                    raise ValueError('Stale or foreign final-parameter inventory acknowledgement at ' + str(peer_ack))
                acks.append(value)
            if len(acks) == 2:
                emit('all-ranks-ready', ranks=[0, 1], generations=generations,
                    scope='Diagnostics only; strict exporter validation follows unchanged')
                return inventory
        if time.monotonic() >= deadline:
            raise TimeoutError('Peer final-parameter inventory did not complete before the strict exporter guard.')
        time.sleep(0.05)
