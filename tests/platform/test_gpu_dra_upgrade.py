"""Offline guards for a cluster-wide GPU allocator transition."""
import copy
import unittest

from apply_gpu_dra_upgrade import gpu_resources, workload_blockers
from prepare_gpu_dra_upgrade import desired_values


def obj(spec, phase='Running'):
    return {'metadata': {'namespace': 'test', 'name': 'worker'},
            'spec': spec, 'status': {'phase': phase}}


class UpgradeGuards(unittest.TestCase):
    def test_gpu_label_does_not_count_as_allocation(self):
        self.assertFalse(gpu_resources({'nodeSelector': {'nvidia.com/gpu.product': 'H100',
                                                        'nvidia.com/gpu.present': 'true'}}))

    def test_pending_gpu_pod_blocks(self):
        pod = obj({'containers': [{'resources': {'limits': {'nvidia.com/gpu': 1}}}]}, 'Pending')
        self.assertTrue(workload_blockers({'pods': {'items': [pod]}}))

    def test_controller_can_recreate_gpu_pod(self):
        controller = obj({'template': {'spec': {'containers': [
            {'resources': {'requests': {'nvidia.com/mig-1g.10gb': '1'}}}]}}})
        self.assertTrue(workload_blockers({'deployments': {'items': [controller]}}))

    def test_finished_pod_does_not_block(self):
        pod = obj({'containers': [{'resources': {'limits': {'nvidia.com/gpu': '1'}}}]}, 'Succeeded')
        self.assertEqual(workload_blockers({'pods': {'items': [pod]}}), [])

    def test_claim_and_dgd_block_even_without_visible_gpu_pod(self):
        for kind in ('resourceclaims', 'dynamographdeployments', 'computedomain'):
            with self.subTest(kind=kind):
                self.assertTrue(workload_blockers({kind: {'items': [obj({})]}}))

    def test_efa_does_not_block_gpu_allocator_change(self):
        self.assertFalse(gpu_resources({'limits': {'vpc.amazonaws.com/efa': '4'}}))

    def test_target_preserves_other_operator_configuration(self):
        before = {'driver': {'enabled': True}, 'devicePlugin': {'enabled': True, 'version': 'pinned'},
                  'toolkit': {'version': 'pinned'}}
        unchanged = copy.deepcopy(before)
        desired = desired_values('gpu-operator', before)
        self.assertEqual(before, unchanged)
        desired['devicePlugin']['enabled'] = True
        self.assertEqual(desired, before)

    def test_dra_target_covers_all_nodes_and_preserves_custom_tolerations(self):
        before = {'resources': {'gpus': {'enabled': False}, 'computeDomains': {'enabled': True}},
                  'kubeletPlugin': {'nodeSelector': {'test-node': 'true'},
                                    'tolerations': [{'operator': 'Exists'}]},
                  'image': {'tag': 'pinned'}}
        desired = desired_values('gpu-dra', before)
        self.assertEqual(desired['kubeletPlugin']['nodeSelector'], {})
        self.assertEqual(desired['kubeletPlugin']['tolerations'], before['kubeletPlugin']['tolerations'])
        self.assertTrue(desired['resources']['gpus']['enabled'])
        self.assertFalse(desired['resources']['computeDomains']['enabled'])
        self.assertEqual(desired['image'], before['image'])


if __name__ == '__main__':
    unittest.main()
