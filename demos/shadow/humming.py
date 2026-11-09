"""Experimental GMS isolation of the two verified mutable Humming lock owners.

Only the pinned linear-kernel and MoE fused-expert owner paths are visited.
Call after leaving the weights pool and before registration/pruning/commit.
Parameters and reader materialization/shape checks are never changed.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
KERNEL_MODULE = 'vllm.model_executor.kernels.linear.nvfp4.humming'
KERNEL_NAME = 'HummingNvFp4LinearKernel'
MOE_MODULE = 'vllm.model_executor.layers.fused_moe.experts.fused_humming_moe'
MOE_NAMES = frozenset(('HummingIndexedExperts', 'HummingGroupedExperts', 'BatchedHummingGroupedExperts'))
WRAPPER_MODULE = 'vllm.model_executor.layers.fused_moe.modular_kernel'
WRAPPER_NAME = 'FusedMoEKernel'
IMPL_NAME = 'FusedMoEKernelModularImpl'
REQUIRED_KINDS = frozenset(('linear', 'moe'))


def _type_is(value, module, names):
    return type(value).__module__ == module and type(value).__name__ in names


def _pool_managers(manager):
    # Refuse a misplaced hook instead of cloning into a GMS pool. This is the
    # pinned allocator's registry, not an unchecked walk of model objects.
    from gpu_memory_service.client.torch.allocator import (
        _active_tag, get_gms_client_memory_managers,
    )
    if _active_tag.get() is not None:
        raise RuntimeError('Humming lock rebinding must run outside every GMS pool.')
    managers = get_gms_client_memory_managers()
    if not any(item is manager for item in managers):
        raise RuntimeError('Writer GMS manager is not in the allocator registry.')
    return managers


def _overlaps(pointer, size, mappings):
    return [(va, mapping) for va, mapping in mappings.items()
            if pointer < va + mapping.aligned_size and va < pointer + size]


def _owners(model):
    """Yield only the reviewed helper paths; do not walk arbitrary objects."""
    seen = set()
    for name, layer in model.named_modules():
        method = getattr(layer, 'quant_method', None)
        kernel = getattr(method, 'kernel', None)
        if _type_is(kernel, KERNEL_MODULE, (KERNEL_NAME,)):
            if id(kernel) not in seen:
                seen.add(id(kernel))
                yield name, 'linear', 'quant_method.kernel.locks', kernel
        elif kernel is not None and type(kernel).__module__ == KERNEL_MODULE:
            raise RuntimeError('Unknown Humming linear helper contract: ' + name)

        wrapper = getattr(method, 'moe_kernel', None)
        humming_backend = getattr(getattr(method, 'nvfp4_backend', None), 'name', None) == 'HUMMING'
        if wrapper is None:
            if humming_backend:
                raise RuntimeError('Humming MoE kernel was not built: ' + name)
            continue
        if not _type_is(wrapper, WRAPPER_MODULE, (WRAPPER_NAME,)):
            if humming_backend:
                raise RuntimeError('Unknown Humming MoE wrapper contract: ' + name)
            continue
        expert = wrapper.fused_experts
        if not _type_is(expert, MOE_MODULE, MOE_NAMES):
            if humming_backend or type(expert).__module__ == MOE_MODULE:
                raise RuntimeError('Unknown Humming MoE expert contract: ' + name)
            continue
        impl = getattr(wrapper, 'impl', None)
        if (not _type_is(impl, WRAPPER_MODULE, (IMPL_NAME,)) or
                getattr(impl, 'fused_experts', None) is not expert):
            raise RuntimeError('Humming MoE expert ownership changed: ' + name)
        if id(expert) not in seen:
            seen.add(id(expert))
            yield name, 'moe', 'quant_method.moe_kernel.fused_experts.locks', expert


def rebind_humming_locks(model, manager, *, retain_gms_tensors=None,
                         required_kinds=('linear', 'moe')):
    import torch

    managers = _pool_managers(manager)
    required = frozenset(required_kinds)
    if not required or not required <= REQUIRED_KINDS:
        raise ValueError('Unknown required Humming workspace owner kinds.')
    owners = list(_owners(model))
    if not required <= {kind for _, kind, _, _ in owners}:
        raise RuntimeError('Expected the pinned Humming workspace owner kinds: ' + str(sorted(required)))

    # Validate every owner before allocation or rebinding. Separate helper
    # objects can alias one workspace; preserve that sharing with one copy.
    plans, copies = [], {}
    for name, kind, owner_path, owner in owners:
        lock = getattr(owner, 'locks', None)
        if (not torch.is_tensor(lock) or not lock.is_cuda or lock.is_meta or
                lock.dtype != torch.int32 or tuple(lock.shape) != (1024,) or
                not lock.is_contiguous() or tuple(lock.stride()) != (1,)):
            raise RuntimeError('Unexpected Humming GEMM lock contract: ' + name + ':' + owner_path)
        size = lock.numel() * lock.element_size()
        pointer = int(lock.data_ptr())
        matches = _overlaps(pointer, size, manager.mappings)
        if matches and (len(matches) != 1 or pointer < matches[0][0] or
                        pointer + size > matches[0][0] + matches[0][1].aligned_size):
            raise RuntimeError('Incomplete/ambiguous GMS lock mapping: ' + name)
        if any(_overlaps(pointer, size, m.mappings) for m in managers if m is not manager):
            raise RuntimeError('Humming lock belongs to an unexpected GMS pool: ' + name)
        key = (str(lock.device), pointer, size)
        plans.append((name, kind, owner_path, owner, lock, key, matches))

    keys = list({plan[5] for plan in plans if plan[6]})
    for index, key in enumerate(keys):
        if any(key[0] == other[0] and key[1] < other[1] + other[2] and other[1] < key[1] + key[2]
               for other in keys[index + 1:]):
            raise RuntimeError('Partially aliased Humming lock workspaces are unsupported.')

    for name, kind, owner_path, owner, lock, key, matches in plans:
        if not matches or key in copies:
            continue
        private = lock.detach().clone()
        pointer = int(private.data_ptr())
        if (private.device != lock.device or private.dtype != lock.dtype or
                private.shape != lock.shape or not private.is_contiguous() or
                tuple(private.stride()) != (1,) or pointer == key[1] or
                any(_overlaps(pointer, key[2], m.mappings) for m in _pool_managers(manager))):
            raise RuntimeError('Humming GEMM lock copy is not outside GMS: ' + name)
        if any(str(other.device) == str(private.device) and pointer < int(other.data_ptr()) + other.numel() * other.element_size()
               and int(other.data_ptr()) < pointer + key[2] for other in copies.values()):
            raise RuntimeError('Separate Humming lock copies overlap: ' + name)
        copies[key] = private

    reports, retained, first_paths = [], set(), {}
    distributed = getattr(torch, 'distributed', None)
    rank = distributed.get_rank() if distributed is not None and distributed.is_initialized() else None
    for name, kind, owner_path, owner, lock, key, matches in plans:
        path = (name + '.' if name else '') + owner_path
        row = {'module': name, 'kind': kind, 'owner_path': owner_path, 'tp_rank': rank,
               'device': str(lock.device), 'bytes': key[2], 'already_private': not bool(matches)}
        if not matches:
            row['pointer'] = hex(key[1])
        else:
            owner.locks = copies[key]
            if retain_gms_tensors is not None and key not in retained:
                retain_gms_tensors.append(lock)
                retained.add(key)
            va, mapping = matches[0]
            row.update(old_pointer=hex(key[1]), new_pointer=hex(int(owner.locks.data_ptr())),
                       gms_mapping=hex(va), gms_mapping_size=mapping.aligned_size,
                       gms_offset=key[1] - va, allocation_id=mapping.allocation_id)
            if key in first_paths:
                row['alias_of'] = first_paths[key]
            else:
                first_paths[key] = path
        reports.append(row)
        logger.info('[WORKSHOP GMS] Private Humming GEMM locks: %s', row)
    logger.info('[WORKSHOP GMS] Humming lock rebinding: %d owners, %d unique copies, %d private bytes',
                len(reports), len(copies), sum(key[2] for key in copies))
    return reports


def patch_writer_loader(source):
    """Insert the bounded hook outside the weights pool, before GMS pruning."""
    anchor = '    stats = prepare_gms_write(gms_client, model)\n'
    retained = '    retained_gms_tensors: list[torch.Tensor] = []\n'
    if source.count(anchor) != 1 or source.count(retained) != 1:
        raise ValueError('Unexpected GMS writer preparation; inspect source before patching.')
    replacement = (retained +
                   '    from gpu_memory_service.integrations.vllm.workshop_humming import rebind_humming_locks\n'
                   '    rebind_humming_locks(model, gms_client, retain_gms_tensors=retained_gms_tensors)\n' + anchor)
    output = source.replace(retained, '').replace(anchor, replacement)
    compile(output, 'gpu_memory_service/integrations/vllm/model_loader.py', 'exec')
    return output
