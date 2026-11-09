"""Allocation and source-lifecycle guards for the CuInterpose test variant."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

import snapshot_cuinterpose_tests as subject


class Guards(unittest.TestCase):
    def test_upstream_source_is_adapted_to_two_dra_gpus_and_frozen_model(self):
        original_root = subject.ROOT
        lock = json.loads((original_root / 'configs/super-vl-tp2-lock.json').read_text())
        lock.update(snapshot_cuinterpose=True, capture_keepalive=True, manifest_directory='test-cuinterpose')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'configs/dgd').mkdir(parents=True)
            upstream = root / 'configs/upstream/snapshot-cuinterpose'
            upstream.parent.mkdir(parents=True)
            upstream.symlink_to(original_root / 'configs/upstream/snapshot-cuinterpose')

            class FakeRun:
                ns = 'dynamo-ft-unit-test'
                path = root
                state = {'run_id': 'unit-test'}
                applied = []
                def labels(self):
                    return {'feature-test-run': self.ns}
                def apply(self, objects):
                    self.applied.extend(copy.deepcopy(objects))

            run = FakeRun()
            with patch.object(subject, 'ROOT', root), patch.object(subject, 'lock_model', return_value=lock):
                job = subject.render(run)
            spec = job['spec']['podTemplate']['spec']
            main = spec['containers'][0]
            claim = run.applied[0]['spec']['spec']['devices']['requests'][0]['exactly']
            self.assertEqual(claim['count'], 2)
            self.assertEqual(claim['deviceClassName'], 'gpu.nvidia.com')
            self.assertNotIn('nvidia.com/gpu', main['resources']['limits'])
            self.assertEqual(main['image'], lock['runtime_image'])
            args = json.loads(main['args'][0])
            self.assertEqual((args['model'], args['revision'], args['tensor_parallel_size']),
                             (lock['model'], lock['revision'], 2))
            self.assertEqual(job['spec']['podTemplate']['metadata']['annotations']['nvidia.com/snapshot-multi-gpu'], 'enabled')
            env = {e['name']: e['value'] for e in main['env']}
            self.assertEqual(env['VLLM_WORKER_MULTIPROC_METHOD'], 'spawn')
            self.assertNotIn('snapshot-bootstrap', json.dumps(spec))
            companion = spec['containers'][1]
            self.assertEqual(companion['name'], 'capture-keepalive')
            self.assertNotIn('claims', companion['resources'])
            self.assertEqual(job['spec']['podSnapshotTemplate']['targetContainers'], ['main'])

    def test_capture_gate_requires_current_source_inspection(self):
        class Run:
            state = {'checks': {'cuinterpose-preparation-inspect': {'status': 'passed', 'pod_uid': 'old'}}}
            def k(self, *a, **kw):
                raise AssertionError('Must refuse before cluster mutation')
        with patch.object(subject, 'source_pod', return_value={'metadata': {'uid': 'new'}}):
            with self.assertRaisesRegex(ValueError, 'this source Pod'):
                subject.capture(Run())

    def test_companion_cannot_stop_before_artifact_is_ready(self):
        class Run:
            ns = 'dynamo-ft-unit-test'
            def get(self, *args):
                if args[1] == 'snapshotjob':
                    return {'metadata': {'labels': {'feature-test-run': self.ns}}}
                return {'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}}
            def k(self, *a, **kw):
                raise AssertionError('Must refuse before signaling any container')
        with self.assertRaisesRegex(ValueError, 'before durable capture readiness'):
            subject.finish_source(Run())

    def test_repeat_restore_has_new_claims_and_no_capture_companion(self):
        original = yaml.safe_load((subject.ROOT / 'configs/dgd/snapshot-super-vl-tp2-cuinterpose-keepalive/snapshotjob.yaml').read_text())
        frozen = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as temp:
            class Run:
                path = Path(temp)
            (Run.path / 'snapshotjob.json').write_text(json.dumps(original))
            pod = subject.restore_manifest(Run(), 'independent-storage-control')
        self.assertEqual(original, frozen)
        self.assertEqual(pod['metadata']['name'], 'independent-storage-control')
        self.assertEqual([c['name'] for c in pod['spec']['containers']], ['main'])
        self.assertNotIn('resourceClaims', pod['spec'])
        self.assertNotIn('claims', pod['spec']['containers'][0]['resources'])
        self.assertEqual(pod['spec']['containers'][0]['resources']['limits']['nvidia.com/gpu'], '2')
        self.assertEqual(pod['spec']['containers'][0]['args'], original['spec']['podTemplate']['spec']['containers'][0]['args'])


if __name__ == '__main__':
    unittest.main()
