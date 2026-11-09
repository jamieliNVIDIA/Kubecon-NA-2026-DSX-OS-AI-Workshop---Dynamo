import copy
import json
from pathlib import Path
import tempfile
import unittest

from prepare_driver_upgrade import CLIENT_LABEL, TARGET_VERSION, command, desired, sha
from apply_driver_upgrade import node_healthy, verify_bundle


class DriverUpgradeGuards(unittest.TestCase):
    def test_policy_readiness_cannot_block_canary_release(self):
        self.assertNotIn('--wait', command('gpu-operator', Path('chart'), Path('values')))
        self.assertIn('--wait', command('nvidia-dra-driver-gpu', Path('chart'), Path('values')))

    def test_only_driver_version_changes(self):
        before = {'driver': {'version': '580.173.02', 'upgradePolicy': {
            'autoUpgrade': True, 'maxParallelUpgrades': 1, 'drain': {'enable': False}}},
            'devicePlugin': {'enabled': False}, 'unrelated': {'keep': [1, 2]}}
        saved = copy.deepcopy(before)
        after = desired('gpu-operator', before)
        expected = copy.deepcopy(before)
        expected['driver']['version'] = TARGET_VERSION
        self.assertEqual(after, expected)
        self.assertEqual(before, saved)

    def test_reject_competing_allocator_or_parallel_upgrade(self):
        for plugin, parallel in [(True, 1), (False, 2)]:
            with self.assertRaises(ValueError):
                desired('gpu-operator', {'driver': {'upgradePolicy': {
                    'autoUpgrade': True, 'maxParallelUpgrades': parallel}}, 'devicePlugin': {'enabled': plugin}})

    def test_dra_eviction_preserves_other_configuration(self):
        before = {'resources': {'computeDomains': {'enabled': True}, 'gpus': {'enabled': True}},
                  'kubeletPlugin': {'nodeSelector': {'existing': 'true'}, 'affinity': {'keep': 1}}}
        after = desired('nvidia-dra-driver-gpu', before)
        expected = copy.deepcopy(before)
        expected['kubeletPlugin']['nodeSelector'][CLIENT_LABEL] = 'true'
        self.assertEqual(after, expected)

    def test_old_driver_or_incomplete_dra_cannot_pass(self):
        good = {'node_ready': True, 'unschedulable': False, 'state': 'upgrade-done',
                'client_label': 'true', 'dra_ready': True, 'dra_devices': 8,
                'driver_pods': [{'ready': True, 'images': [f'nvcr.io/nvidia/driver:{TARGET_VERSION}-ubuntu24.04']}]}
        self.assertTrue(node_healthy(good))
        for key, value in [('dra_devices', 7), ('dra_ready', False), ('unschedulable', True),
                           ('state', 'pod-restart-required'), ('client_label', 'false')]:
            with self.subTest(key=key):
                bad = copy.deepcopy(good)
                bad[key] = value
                self.assertFalse(node_healthy(bad))
        bad = copy.deepcopy(good)
        bad['driver_pods'][0]['images'] = ['nvcr.io/nvidia/driver:580.173.02-ubuntu24.04']
        self.assertFalse(node_healthy(bad))

    def test_reject_tampered_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            chart, values = folder / 'chart', folder / 'values'
            chart.write_text('chart')
            values.write_text('values')
            lock = {'status': 'server-dry-run-passed', 'target_driver': TARGET_VERSION, 'releases': {'gpu-operator': {
                'chart_path': str(chart), 'chart_sha256': sha(chart),
                'values_path': str(values), 'values_sha256': sha(values)}}}
            (folder / 'lock.json').write_text(json.dumps(lock))
            verify_bundle(folder)
            values.write_text('changed after dry-run')
            with self.assertRaises(ValueError):
                verify_bundle(folder)


if __name__ == '__main__':
    unittest.main()
