"""Exercise the actual mounted GMS memory-budget shim without importing CUDA."""
from tests.support import ROOT
import ast
import hashlib
import json
from types import SimpleNamespace
import unittest

PATCH = ROOT / 'configs/patches/shadow-gms-vllm031/patches.py'


class MemoryCompatibilityTests(unittest.TestCase):
    def test_committed_overlay_matches_its_pinned_image_manifest(self):
        manifest = json.loads(PATCH.with_name('manifest.json').read_text())
        self.assertEqual(hashlib.sha256(PATCH.read_bytes()).hexdigest(), manifest['patch']['sha256'])
        root = ROOT
        lock = json.loads((root / 'configs/super-vl-tp2-lock.json').read_text())
        self.assertEqual(manifest['runtime_image'], lock['runtime_image'])
        self.assertEqual(root / manifest['patch']['path'], PATCH)

    def setUp(self):
        tree = ast.parse(PATCH.read_text())
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                        and n.name == 'patched_request_memory')
        namespace = {'logger': SimpleNamespace(info=lambda *a: None)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(PATCH), 'exec'), namespace)
        self.request = namespace['patched_request_memory']
        self.snapshot = SimpleNamespace(total_memory=1000, free_memory=1)
        self.cache = SimpleNamespace(gpu_memory_utilization=0.65)

    def test_old_two_argument_signature_preserves_shadow_budget(self):
        self.assertEqual(self.request(self.snapshot, self.cache), 650)

    def test_new_three_argument_call(self):
        self.assertEqual(self.request(self.snapshot, self.cache, 0), 650)

    def test_external_weights_are_excluded_from_private_budget(self):
        self.assertEqual(self.request(self.snapshot, self.cache, 100), 550)

    def test_external_weights_cannot_exhaust_budget(self):
        with self.assertRaises(ValueError):
            self.request(self.snapshot, self.cache, 650)


if __name__ == '__main__':
    unittest.main()
