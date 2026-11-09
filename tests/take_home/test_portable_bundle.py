"""Portable bundle invariants protect attendees from private-cluster assumptions."""
from tests.support import ROOT
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import yaml



def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'take-home' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


portable = load('take_home_render', 'render.py')
response_check = load('take_home_response', 'check-response.py')
qualification = load('take_home_qualification', 'qualify.py')
registry_probe = load('take_home_registry_probe', 'probe-public-registry.py')


class TakeHomeTests(unittest.TestCase):
    def args(self, **overrides):
        values = dict(namespace='attendee-case', name='coding-agent', cache_pvc='my-cache',
                      runtime_image='example.test/dynamo@sha256:' + 'a' * 64,
                      runtime_version='1.6.0', image_pull_secret=None, gpu_mode='device-plugin')
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_private_preparation_is_not_exported(self):
        objects, request, lock = portable.render(self.args())
        text = yaml.safe_dump(objects)
        for private in ('cp-0124', 'cp-0198', 'common-runtime-pull', 'feature-cache',
                        '/model-cache/feature-tests/', 'nvcr.io/nvidian/', 'feature-test-run'):
            self.assertNotIn(private, text)
        graph = objects['deployment.yaml']
        for component in graph['spec']['components']:
            spec = component['podTemplate']['spec']
            self.assertNotIn('imagePullSecrets', spec)
            main = spec['containers'][0]
            self.assertEqual(main['image'], self.args().runtime_image)
            self.assertIn({'name': 'HF_HOME', 'value': '/model-cache/hf'}, main['env'])
        worker = graph['spec']['components'][1]['podTemplate']['spec']
        self.assertNotIn('resourceClaims', worker)
        self.assertEqual(worker['containers'][0]['resources']['limits']['nvidia.com/gpu'], 2)
        self.assertEqual(request['model'], lock['model'])
        self.assertEqual(lock['revision'], json.loads(portable.intro.MODEL_LOCK.read_text())['revision'])

    def test_anonymous_registry_challenge_matches_observed_service_and_exact_pull_scope(self):
        observed = 'Bearer realm="https://nvcr.io/token",service="registry",scope="repository:nvidia/ai-dynamo/vllm-runtime-nightly:pull"'
        values, realm = registry_probe.parse_challenge(observed)
        self.assertEqual(values['service'], 'registry')
        self.assertEqual(realm.hostname, 'nvcr.io')
        for old, new in (('https://nvcr.io/token', 'http://nvcr.io/token'),
                         ('https://nvcr.io/token', 'https://other.test/token'),
                         ('service="registry"', 'service="other"'),
                         (':pull"', ':pull,push"')):
            with self.subTest(replacement=new), self.assertRaises(ValueError):
                registry_probe.parse_challenge(observed.replace(old, new))

    def test_service_matches_frontend_after_grove_overwrites_managed_by(self):
        objects, _, _ = portable.render(self.args())
        selector = objects['frontend-service.yaml']['spec']['selector']
        self.assertEqual(selector, {'workshop-service': 'coding-agent', 'workshop-role': 'frontend'})
        actual = []
        for component in objects['deployment.yaml']['spec']['components']:
            labels = dict(component['podTemplate']['metadata']['labels'])
            labels['app.kubernetes.io/managed-by'] = 'grove-operator'
            actual.append((component['type'], labels))
        matches = [kind for kind, labels in actual if all(labels.get(k) == v for k, v in selector.items())]
        self.assertEqual(matches, ['frontend'])
        self.assertFalse(all({'workshop-service': 'another-service', 'workshop-role': 'frontend'}.get(k) == v
                             for k, v in selector.items()))

    def test_dra_gpu_identity_and_download_are_explicit(self):
        objects, _, lock = portable.render(self.args(gpu_mode='dra', image_pull_secret='my-pull'))
        claim = objects['gpu-claim-template.yaml']
        worker = objects['deployment.yaml']['spec']['components'][1]['podTemplate']['spec']
        self.assertEqual(worker['resourceClaims'][0]['resourceClaimTemplateName'], claim['metadata']['name'])
        self.assertEqual(claim['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
        self.assertNotIn('nvidia.com/gpu', worker['containers'][0]['resources']['limits'])
        job = objects['download-job.yaml']['spec']['template']['spec']
        main = job['containers'][0]
        self.assertIn(lock['revision'], main['command'][-1])
        self.assertNotIn('resourceClaims', job)
        self.assertNotIn('nvidia.com/gpu', main['resources']['requests'])
        self.assertEqual(job['imagePullSecrets'], [{'name': 'my-pull'}])

    def test_fresh_output_and_rejected_ambiguous_inputs(self):
        for override in ({'runtime_image': 'example.test/dynamo:latest'}, {'namespace': 'default'},
                         {'name': 'wrong/name'}, {'runtime_version': '1.6.0 --flag'}):
            with self.assertRaises(ValueError):
                portable.render(self.args(**override))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            command = [sys.executable, str(ROOT / 'take-home/render.py'), '--namespace', 'attendee-case',
                       '--runtime-image', self.args().runtime_image, '--runtime-version', '1.6.0',
                       '--cache-pvc', 'my-cache', '--output', str(target)]
            first = subprocess.run(command, text=True, capture_output=True, check=True)
            self.assertIn('No Kubernetes calls', first.stdout)
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in target.iterdir()})

    def test_serving_smoke_rejects_wrong_model_empty_or_truncated_response(self):
        profile = {'model': 'expected/model'}
        models = {'data': [{'id': profile['model']}]}
        response = {'model': profile['model'], 'choices': [{'message': {'content': 'def add(a, b): return a + b'},
                                                         'finish_reason': 'stop'}]}
        self.assertIn('def add', response_check.check(profile, models, response))
        for bad in ({**response, 'model': 'other/model'},
                    {**response, 'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]},
                    {**response, 'choices': [{'message': {'content': 'unfinished'}, 'finish_reason': 'length'}]}):
            with self.assertRaises(ValueError):
                response_check.check(profile, models, bad)
        with self.assertRaises(ValueError):
            response_check.check(profile, {'data': []}, response)

    def test_fresh_cache_pins_metadata_but_preserves_a_foreign_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_home = Path(directory)
            model_root = cache_home / 'hub/models--fixture--model'
            snapshot = model_root / 'snapshots' / ('a' * 40)
            snapshot.mkdir(parents=True)
            metadata = {'config.json': '{}', 'tokenizer_config.json': '{}',
                        'model.safetensors.index.json': json.dumps({'weight_map': {'w': 'weights.safetensors'}})}
            for name, value in metadata.items():
                (snapshot / name).write_text(value)
            (snapshot / 'weights.safetensors').write_bytes(b'fixture-not-real-weights')
            lock = {'model': 'fixture/model', 'revision': 'a' * 40, 'checkpoint_weight_files': 1,
                    'model_metadata_sha256': {name: hashlib.sha256(value.encode()).hexdigest()
                                             for name, value in metadata.items()}}
            fake_hub = types.ModuleType('huggingface_hub')
            fake_hub.snapshot_download = mock.Mock(return_value=str(snapshot))
            with mock.patch.dict(sys.modules, {'huggingface_hub': fake_hub}), \
                    mock.patch.dict('os.environ', {'HF_HOME': str(cache_home)}), \
                    mock.patch('subprocess.run') as offline_probe:
                exec(compile(portable.download_program(lock), '<download-fixture>', 'exec'), {})
                self.assertEqual((model_root / 'refs/main').read_text().strip(), lock['revision'])
                self.assertEqual(offline_probe.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1')
                self.assertIn('dynamo.common.model_fetch', offline_probe.call_args.args[0][-1])
                fake_hub.snapshot_download.reset_mock()
                offline_probe.reset_mock()
                (model_root / 'refs/main').write_text('b' * 40)
                with self.assertRaisesRegex(RuntimeError, 'nothing was overwritten'):
                    exec(compile(portable.download_program(lock), '<download-fixture>', 'exec'), {})
                fake_hub.snapshot_download.assert_not_called()
                offline_probe.assert_not_called()
                self.assertEqual((model_root / 'refs/main').read_text(), 'b' * 40)

    def test_presenter_allocation_environment_is_ignored_and_preserved(self):
        import demos.common.runtime as ordinary
        from demos.common.allocation import Allocation
        assignment = {'schema': 1, 'assignment_id': 'fixture',
                      'lease': '.local/fixture.gpu-lease',
                      'targets': {'intro': {'node': 'private-node-fixture', 'gpu_uuids': [
                          'GPU-11111111-1111-1111-1111-111111111111',
                          'GPU-22222222-2222-2222-2222-222222222222']}}}
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            valid, malformed = directory / 'allocation.json', directory / 'malformed.json'
            valid.write_text(json.dumps(assignment))
            malformed.write_text('{bad-json')
            for index, env_path in enumerate((valid, malformed, directory / 'missing.json')):
                with self.subTest(path=env_path), mock.patch.dict(os.environ, {'WORKSHOP_ALLOCATION': str(env_path)}), \
                        mock.patch.object(ordinary, 'ALLOCATION', Allocation(ROOT, assignment)):
                    prior = ordinary.ALLOCATION
                    isolated = load('take_home_render_isolated_' + str(index), 'render.py')
                    objects, _, _ = isolated.render(self.args(gpu_mode='dra'))
                    rendered = yaml.safe_dump(objects)
                    self.assertNotIn('private-node-fixture', rendered)
                    self.assertNotIn('GPU-11111111', rendered)
                    self.assertNotIn('selectors:', rendered)
                    self.assertIsNone(isolated.intro.ALLOCATION)
                    self.assertIs(ordinary.ALLOCATION, prior)
                    self.assertEqual(os.environ['WORKSHOP_ALLOCATION'], str(env_path))

    def test_shared_cache_subpath_is_consistent_and_cannot_escape_pvc(self):
        args = self.args(cache_subpath='prepared/model-cache', gpu_mode='dra')
        objects, _, _ = portable.render(args)
        graph = objects['deployment.yaml']
        mounts = [mount for component in graph['spec']['components']
                  for mount in component['podTemplate']['spec']['containers'][0]['volumeMounts']
                  if mount['name'] == 'shared-model-cache']
        mounts += objects['download-job.yaml']['spec']['template']['spec']['containers'][0]['volumeMounts']
        self.assertEqual(len(mounts), 3)
        self.assertTrue(all(mount.get('subPath') == args.cache_subpath for mount in mounts))
        self.assertTrue(all(mount['mountPath'] == '/model-cache' for mount in mounts))
        for bad in ('', '/absolute', '..', '../other', 'a/../other', './cache', 'a//b', 'a/./b', 'a\\b', 'a/$(pwd)'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                portable.render(self.args(cache_subpath=bad))

    def test_qualification_fences_only_test_placement_and_freezes_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new-run'
            args = argparse.Namespace(run=path, allocations=ROOT / 'reports/overnight-2026-11-04/allocations.json',
                slot='migration', node='kubecon-nke-site-cp-0942', public_candidate=True,
                runtime_image='nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:' + 'a' * 64,
                runtime_version='1.7.0', expected_dynamo_package_version='1.7.0.dev20261103', run_as_user=0)
            with mock.patch.object(qualification.Run, 'command', side_effect=AssertionError('freeze must be offline')):
                qualification.freeze(args)
                run, spec = qualification.load(path)
            portable_graph = yaml.safe_load((path / 'bundle/deployment.yaml').read_text())
            actual_graph = json.loads((path / 'effective-deployment.json').read_text())
            portable_worker = portable_graph['spec']['components'][1]['podTemplate']['spec']
            actual_worker = actual_graph['spec']['components'][1]['podTemplate']['spec']
            self.assertNotIn('nodeSelector', portable_worker)
            self.assertEqual(actual_worker.pop('nodeSelector'), {'kubernetes.io/hostname': args.node})
            self.assertEqual(portable_graph, actual_graph)
            self.assertEqual(spec['runtime_image'], args.runtime_image)
            self.assertEqual(spec['runtime_version'], '1.7.0')
            self.assertEqual(spec['expected_dynamo_package_version'], '1.7.0.dev20261103')
            self.assertEqual(spec['run_as_user'], 0)
            self.assertEqual(len(spec['gpu_uuids']), 2)
            self.assertEqual(len(spec['inputs']), 10)
            claim = path / 'effective-claim.json'
            claim.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Input changed'):
                qualification.load(path)
            with self.assertRaisesRegex(ValueError, 'new qualification'):
                qualification.freeze(args)

    def test_qualification_cleanup_rejects_a_reused_dgd(self):
        run = types.SimpleNamespace(ns='owned-namespace', state={'dgd_uid': 'original'},
            k=mock.Mock(return_value=types.SimpleNamespace(returncode=0, stdout=json.dumps({
                'metadata': {'name': 'coding-agent', 'uid': 'replacement',
                             'labels': {'workshop-service': 'coding-agent'}}}))))
        with mock.patch.object(qualification, 'require_namespace'), self.assertRaisesRegex(ValueError, 'DGD UID changed'):
            qualification.cleanup(run, {})
        self.assertEqual(run.k.call_count, 1)

    def test_operator_runtime_override_rejects_package_prereleases_before_rendering(self):
        for version in ('1.7.0.dev20261103', '1.7.0-rc1', '1.7', '01.7.0', '10000.0.0', 'latest'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'operator-compatible X.Y.Z'):
                portable.render(self.args(runtime_version=version))

    def test_explicit_uid_is_consistent_without_changing_capabilities_or_data(self):
        objects, _, _ = portable.render(self.args(run_as_user=0))
        containers = [c['podTemplate']['spec']['containers'][0] for c in objects['deployment.yaml']['spec']['components']]
        containers += objects['download-job.yaml']['spec']['template']['spec']['containers']
        self.assertTrue(all(c['securityContext']['runAsUser'] == 0 for c in containers))
        self.assertEqual(containers[1]['securityContext']['capabilities']['add'], ['IPC_LOCK', 'SYS_RESOURCE'])
        self.assertNotIn('chown', objects['download-job.yaml']['spec']['template']['spec']['containers'][0]['command'][-1])
        for uid in (-1, 4294967295, '0', True):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                portable.render(self.args(run_as_user=uid))

    def test_cache_job_terminal_failure_and_reused_uid_fail_without_waiting(self):
        metadata = {'uid': 'original-job', 'labels': {'workshop-service': 'coding-agent'}}
        run = types.SimpleNamespace(ns='owned', state={'cache_job_uid': 'original-job'}, get=mock.Mock())
        for condition in ('Failed', 'FailureTarget'):
            run.get.return_value = {'metadata': metadata, 'status': {'conditions': [
                {'type': condition, 'status': 'True', 'reason': 'BackoffLimitExceeded', 'message': 'Pod failed'}]}}
            with mock.patch.object(qualification.time, 'sleep') as sleep, self.assertRaisesRegex(RuntimeError, 'Generated cache Job failed'):
                qualification.wait_cache_job(run, 30)
            sleep.assert_not_called()
        run.get.return_value = {'metadata': {**metadata, 'uid': 'reused-job-name'}, 'status': {}}
        with self.assertRaisesRegex(ValueError, 'Cache Job UID changed'):
            qualification.wait_cache_job(run, 30)
        run.get.return_value = {'metadata': metadata, 'status': {'conditions': [{'type': 'Complete', 'status': 'True'}]}}
        qualification.wait_cache_job(run, 30)

    def test_qualification_never_adopts_namespace_names_and_rejects_reuse(self):
        old = {'metadata': {'uid': 'old', 'labels': {'app.kubernetes.io/managed-by': 'owned'}}}
        run = types.SimpleNamespace(ns='owned-namespace', state={'owner': 'owned'},
            k=mock.Mock(return_value=types.SimpleNamespace(returncode=0)), get=mock.Mock(return_value=old))
        with self.assertRaisesRegex(ValueError, 'Namespace already exists'):
            qualification.create_namespace(run)
        self.assertEqual(run.k.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'creating namespace UID'):
            qualification.require_namespace(run)
        run.state['namespace_uid'] = 'old'
        qualification.require_namespace(run)
        run.get.return_value = {'metadata': {**old['metadata'], 'uid': 'reused-name'}}
        with self.assertRaisesRegex(ValueError, 'identity/ownership changed'):
            qualification.cleanup(run, {})
        self.assertEqual(run.k.call_count, 1)


if __name__ == '__main__':
    unittest.main()
