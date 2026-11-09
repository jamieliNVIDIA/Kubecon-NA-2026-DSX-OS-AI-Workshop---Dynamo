"""Writer-only experiment contracts; all checks run without cluster access."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import demos.shadow.writer as writer


class WriterExperimentTests(unittest.TestCase):
    def setUp(self):
        # Unit checks must also work in a clean clone without private run data.
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        source = Path(self.fixture.name) / 'source'
        runtime = source / 'runtime'
        source.mkdir()
        (source / 'runtime-sources').mkdir()
        from demos.shadow.demo import render
        graph, _ = render('dynamo-ft-fixture', writer.ui.read_json(writer.ui.MODEL_LOCK), overlay='old')
        (source / 'deployment.yaml').write_text(yaml.safe_dump(graph))
        (source / 'runtime-sources/patches.py').write_text('def patched_request_memory(a, b): pass\n')
        (source / 'patched-patches.py').write_text('def patched_request_memory(a, b, external_weight_memory=0): pass\n')
        loader = runtime / 'gpu_memory_service/integrations/vllm/model_loader.py'
        loader.parent.mkdir(parents=True)
        loader.write_text('def load(model, gms_client):\n'
                          '    stats = prepare_gms_write(gms_client, model)\n'
                          '    retained_gms_tensors: list[torch.Tensor] = []\n'
                          '    return stats\n')
        for name in [writer.KERNEL_MODULE.replace('.', '/') + '.py',
                     writer.MOE_MODULE.replace('.', '/') + '.py',
                     writer.WRAPPER_MODULE.replace('.', '/') + '.py',
                     'gpu_memory_service/client/torch/allocator.py']:
            target = runtime / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('# Frozen CPU unit fixture for ' + name + '\n')
        self.source_patch = patch.object(writer, 'SOURCE', source)
        self.runtime_patch = patch.object(writer, 'RUNTIME', runtime)
        self.extra_patch = patch.object(writer, 'EXTRA_RUNTIME', runtime)
        self.source_patch.start()
        self.runtime_patch.start()
        self.extra_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self.runtime_patch.stop)
        self.addCleanup(self.extra_patch.stop)

    def test_frozen_candidate_has_no_reader_or_shadow_and_keeps_exact_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fresh-candidate'
            with redirect_stdout(io.StringIO()):
                writer.freeze(path)
            graph = json.loads((path / 'deployment.json').read_text())
            worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
            self.assertEqual(set(worker['experimental']), {'gpuMemoryService'})
            spec = worker['podTemplate']['spec']
            self.assertEqual(spec['nodeSelector'], {'kubernetes.io/hostname': writer.NODE})
            mounts = {v['subPath'] for v in spec['containers'][0]['volumeMounts'] if 'subPath' in v}
            self.assertEqual(mounts, {'model_loader.py', 'workshop_humming.py', 'patches.py'})
            self.assertNotIn('module.py', mounts)
            args = spec['containers'][0]['args']
            self.assertEqual(args[args.index('--kv-cache-memory-bytes') + 1], '2147483648')
            dc = json.loads((path / 'device-class.json').read_text())
            expression = dc['spec']['selectors'][0]['cel']['expression']
            for uuid in writer.UUIDS:
                self.assertIn(uuid, expression)
            source = (path / 'model_loader.py').read_text()
            hook = source.index('    rebind_humming_locks(model, gms_client,')
            prepare = source.index('    stats = prepare_gms_write(gms_client, model)')
            self.assertLess(hook, prepare)
            self.assertEqual(source.count('    retained_gms_tensors: list[torch.Tensor] = []'), 1)
            frozen = json.loads((path / 'writer-spec.json').read_text())
            self.assertEqual(frozen['workspace_owner_kinds'], ['linear', 'moe'])
            self.assertEqual(len(frozen['runtime_contract_hashes']), 4)
            writer.load(path)  # Fresh frozen provenance passes before any network action.

    def test_changed_manifest_is_rejected_before_cluster_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fresh-candidate'
            with redirect_stdout(io.StringIO()): writer.freeze(path)
            (path / 'deployment.yaml').write_text('changed\n')
            with self.assertRaisesRegex(ValueError, 'Frozen writer input changed'):
                writer.load(path)

    def test_deployment_requires_completed_exact_pair_cuda_probe(self):
        with self.assertRaisesRegex(ValueError, 'CUDA smoke'):
            writer.deploy(SimpleNamespace(state={'checks': {}}), {}, None)

    def test_finalization_requires_actual_correct_serving(self):
        with self.assertRaisesRegex(ValueError, 'coding verification'):
            writer.finalize(SimpleNamespace(state={'checks': {}}), None)

    def lock_rows(self):
        return [{'kind': kind, 'owner_path': 'quant_method.kernel.locks' if kind == 'linear' else
                 'quant_method.moe_kernel.fused_experts.locks', 'tp_rank': rank,
                 'bytes': 4096, 'already_private': False, 'old_pointer': '0x1000',
                 'new_pointer': '0x10000', 'gms_mapping': '0x0', 'gms_mapping_size': 8192}
                for rank in (0, 1) for kind in ('linear', 'moe')]

    def test_proof_requires_actual_moe_and_linear_copies_on_both_tp_ranks(self):
        rows = self.lock_rows()
        writer.validate_lock_proof(rows)
        with self.assertRaisesRegex(ValueError, 'Missing actual'):
            writer.validate_lock_proof(rows[:-1])

    def test_proof_rejects_private_tensor_extent_intersecting_gms(self):
        rows = self.lock_rows()
        rows[0]['new_pointer'] = '0x100'
        with self.assertRaisesRegex(ValueError, 'range proof'):
            writer.validate_lock_proof(rows)


if __name__ == '__main__': unittest.main()
