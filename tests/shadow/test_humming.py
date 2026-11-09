"""Safety tests for the proposed private Humming workspace hook, without CUDA."""
import copy
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

import demos.shadow.humming as hook
from demos.shadow.humming import KERNEL_MODULE, KERNEL_NAME, rebind_humming_locks, patch_writer_loader
from demos.shadow.humming import _pool_managers as real_pool_managers


class Tensor:
    is_cuda, is_meta, dtype, shape, device = True, False, 'int32', (1024,), 'cuda:0'
    def __init__(self, pointer, copied_pointer=20000):
        self.pointer, self.copied_pointer = pointer, copied_pointer
    def data_ptr(self): return self.pointer
    def numel(self): return 1024
    def element_size(self): return 4
    def is_contiguous(self): return True
    def stride(self): return (1,)
    def detach(self): return self
    def clone(self):
        tensor = copy.copy(self)
        tensor.pointer = self.copied_pointer
        return tensor


class HummingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        cls = type(KERNEL_NAME, (), {'__module__': KERNEL_MODULE})
        self.kernel = cls()
        self.kernel.locks = Tensor(2000)
        layer = SimpleNamespace(quant_method=SimpleNamespace(kernel=self.kernel))
        self.model = SimpleNamespace(named_modules=lambda: iter([('up_proj', layer), ('same_alias', layer)]))
        self.manager = SimpleNamespace(mappings={1000: SimpleNamespace(aligned_size=8192, allocation_id='weights-1')})
        self.torch = SimpleNamespace(is_tensor=lambda x: isinstance(x, Tensor), int32='int32')
        patcher = patch.object(hook, '_pool_managers', side_effect=lambda _: [self.manager])
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, **kwargs):
        kwargs.setdefault('required_kinds', ('linear',))
        with patch.dict(sys.modules, {'torch': self.torch}):
            return rebind_humming_locks(self.model, self.manager, **kwargs)

    def test_mutable_helper_tensor_moves_out_of_shared_weight_mapping(self):
        original = self.kernel.locks
        reports = self.call()
        self.assertEqual(len(reports), 1)  # Shared helper alias is rebound once.
        self.assertIsNot(self.kernel.locks, original)
        self.assertEqual(original.data_ptr(), 2000)
        self.assertEqual(self.kernel.locks.data_ptr(), 20000)
        self.assertEqual(reports[0]['bytes'], 4096)
        self.assertEqual(reports[0]['gms_offset'], 1000)

    def test_clone_in_shared_pool_is_rejected_before_binding(self):
        original = self.kernel.locks
        original.copied_pointer = 3000
        with self.assertRaisesRegex(RuntimeError, 'not outside GMS'):
            self.call()
        self.assertIs(self.kernel.locks, original)

    def test_unexpected_workspace_dtype_is_rejected(self):
        self.kernel.locks.dtype = 'float32'
        with self.assertRaisesRegex(RuntimeError, 'lock contract'):
            self.call()

    def test_existing_private_workspace_is_preserved(self):
        original = self.kernel.locks
        original.pointer = 20000
        report = self.call()
        self.assertIs(self.kernel.locks, original)
        self.assertTrue(report[0]['already_private'])

    def test_unknown_backend_does_not_get_silently_patched(self):
        self.kernel.__class__ = type('OtherKernel', (), {})
        with self.assertRaisesRegex(RuntimeError, 'Expected the pinned'):
            self.call()

    def test_original_lock_stays_alive_until_pending_publication_release(self):
        original = self.kernel.locks
        retained = []
        self.call(retain_gms_tensors=retained)
        self.assertEqual(retained, [original])
        self.assertIsNot(self.kernel.locks, original)

    def test_unrecognized_loader_source_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_writer_loader('def changed_contract(): pass\n')

    def add_moe(self, name='HummingIndexedExperts', lock=None):
        expert_cls = type(name, (), {'__module__': hook.MOE_MODULE})
        expert = expert_cls()
        expert.locks = lock or Tensor(10500, 60000)
        impl_cls = type(hook.IMPL_NAME, (), {'__module__': hook.WRAPPER_MODULE})
        impl = impl_cls()
        impl.fused_experts = expert
        wrapper_cls = type(hook.WRAPPER_NAME, (), {'__module__': hook.WRAPPER_MODULE,
            'fused_experts': property(lambda self: self.impl.fused_experts)})
        wrapper = wrapper_cls()
        wrapper.impl = impl
        layer = SimpleNamespace(quant_method=SimpleNamespace(moe_kernel=wrapper,
            nvfp4_backend=SimpleNamespace(name='HUMMING')))
        self.manager.mappings[10000] = SimpleNamespace(aligned_size=8192, allocation_id='weights-2')
        linear_layer = SimpleNamespace(quant_method=SimpleNamespace(kernel=self.kernel))
        self.model = SimpleNamespace(named_modules=lambda: iter([('up_proj', linear_layer), ('experts', layer)]))
        return expert, wrapper

    def test_concrete_moe_and_linear_owner_paths_are_both_rebound(self):
        expert, wrapper = self.add_moe()
        old = expert.locks
        rows = self.call(required_kinds=('linear', 'moe'))
        self.assertEqual({r['kind'] for r in rows}, {'linear', 'moe'})
        self.assertIs(wrapper.fused_experts, expert)
        self.assertIsNot(expert.locks, old)
        self.assertEqual(expert.locks.data_ptr(), 60000)
        self.assertEqual(rows[1]['owner_path'], 'quant_method.moe_kernel.fused_experts.locks')

    def test_all_three_reviewed_moe_expert_types_are_supported(self):
        for name in sorted(hook.MOE_NAMES):
            with self.subTest(name=name):
                expert, _ = self.add_moe(name=name)
                self.call(required_kinds=('linear', 'moe'))
                self.assertEqual(expert.locks.data_ptr(), 60000)

    def test_missing_moe_owner_fails_before_any_linear_binding_changes(self):
        old = self.kernel.locks
        with self.assertRaisesRegex(RuntimeError, 'owner kinds'):
            self.call(required_kinds=('linear', 'moe'))
        self.assertIs(self.kernel.locks, old)

    def test_moe_public_property_and_impl_owner_must_agree(self):
        _, wrapper = self.add_moe()
        type(wrapper).fused_experts = property(lambda self: SimpleNamespace())
        with self.assertRaisesRegex(RuntimeError, 'expert contract'):
            self.call(required_kinds=('linear', 'moe'))

    def test_unreviewed_moe_type_fails_before_any_binding_changes(self):
        self.add_moe(name='NewHummingExperts')
        old = self.kernel.locks
        with self.assertRaisesRegex(RuntimeError, 'expert contract'):
            self.call(required_kinds=('linear', 'moe'))
        self.assertIs(self.kernel.locks, old)

    def test_shared_workspace_alias_between_distinct_owners_stays_shared(self):
        old = self.kernel.locks
        expert, _ = self.add_moe(lock=old)
        retained = []
        rows = self.call(required_kinds=('linear', 'moe'), retain_gms_tensors=retained)
        self.assertIs(self.kernel.locks, expert.locks)
        self.assertEqual(retained, [old])
        self.assertEqual(rows[1]['alias_of'], 'up_proj.quant_method.kernel.locks')

    def test_old_workspace_extent_must_fit_one_mapping(self):
        self.kernel.locks.pointer = 8000
        with self.assertRaisesRegex(RuntimeError, 'Incomplete/ambiguous'):
            self.call()

    def test_clone_start_outside_gms_but_extent_overlaps_is_rejected(self):
        self.kernel.locks.copied_pointer = 500
        with self.assertRaisesRegex(RuntimeError, 'not outside GMS'):
            self.call()

    def test_partial_workspace_aliases_are_rejected(self):
        self.add_moe(lock=Tensor(3000, 60000))
        with self.assertRaisesRegex(RuntimeError, 'Partially aliased'):
            self.call(required_kinds=('linear', 'moe'))

    def test_other_gms_pool_cannot_receive_a_private_copy(self):
        other = SimpleNamespace(mappings={19500: SimpleNamespace(aligned_size=8192, allocation_id='kv')})
        with patch.object(hook, '_pool_managers', return_value=[self.manager, other]):
            with self.assertRaisesRegex(RuntimeError, 'not outside GMS'):
                self.call()

    def test_active_gms_pool_is_rejected(self):
        allocator = ModuleType('gpu_memory_service.client.torch.allocator')
        allocator._active_tag = SimpleNamespace(get=lambda: 'weights')
        allocator.get_gms_client_memory_managers = lambda: [self.manager]
        with patch.dict(sys.modules, {'gpu_memory_service.client.torch.allocator': allocator}):
            with self.assertRaisesRegex(RuntimeError, 'outside every GMS pool'):
                real_pool_managers(self.manager)


if __name__ == '__main__':
    unittest.main()
