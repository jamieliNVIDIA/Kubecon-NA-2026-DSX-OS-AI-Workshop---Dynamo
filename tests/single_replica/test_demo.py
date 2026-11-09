"""Guard the demo's key gates, ownership, readiness and timing boundaries."""
from tests.support import ROOT
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import yaml

import demos.common.runtime as demo
from demos.single_replica import demo as intro


class DemoTests(unittest.TestCase):
    def test_prepare_selects_run_for_bare_run_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pointer = root / 'current.json'

            def prepare(instance):
                instance.data['prepared'] = True
                instance.save()

            with mock.patch.object(demo, 'CURRENT_RUN', pointer), mock.patch.object(demo, 'ROOT', root), \
                    mock.patch.object(demo.Demo, 'prepare', autospec=True, side_effect=prepare), \
                    mock.patch.object(demo, 'tmux_layout') as layout, \
                    contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(sys, 'argv', ['demo', 'prepare']):
                    intro.main()
                run_path = demo.current_run()
                self.assertEqual(run_path.parent, root / 'results')
                self.assertTrue(run_path.name.startswith('demo-01-'))
                with mock.patch.object(sys, 'argv', ['demo']):
                    intro.main()
                self.assertEqual(layout.call_args.args[0].path, run_path)
                with mock.patch.object(demo.Demo, 'cleanup') as cleanup, \
                        mock.patch.object(sys, 'argv', ['demo', 'cleanup']):
                    intro.main()
                cleanup.assert_called_once()
                self.assertFalse(pointer.exists())

    def test_failed_prepare_and_rehearsal_do_not_replace_current_live_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer = root / 'current.json'
            original = root / 'original'
            with mock.patch.object(demo, 'CURRENT_RUN', pointer):
                demo.write_json(pointer, {'run': str(original)})
                before = pointer.read_bytes()
                with mock.patch.object(demo.Demo, 'prepare', side_effect=RuntimeError('cache check failed')), \
                        mock.patch.object(sys, 'argv', ['demo', 'prepare', '--run', str(root / 'failed')]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeError, 'cache check failed'):
                        intro.main()
                demo.remember_prepared(SimpleNamespace(args=SimpleNamespace(rehearsal=True)))
                self.assertEqual(pointer.read_bytes(), before)
                demo.forget_cleaned(root / 'different-run')
                self.assertEqual(pointer.read_bytes(), before)

    def test_missing_or_cleaned_current_run_requires_prepare_without_creating_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(demo, 'CURRENT_RUN', root / 'current.json'):
                with self.assertRaisesRegex(RuntimeError, 'No prepared demo selected'):
                    demo.current_run()
                old = root / 'cleaned'
                old.mkdir()
                demo.write_json(old / 'demo.json', {'prepared': True, 'profile': demo.PROFILE, 'cleaned_at': demo.now()})
                demo.write_json(demo.CURRENT_RUN, {'run': str(old)})
                with self.assertRaisesRegex(RuntimeError, 'no longer prepared'):
                    demo.current_run()

    def test_cleanup_of_missing_run_fails_before_creating_files_or_calling_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'misspelled-run'
            with mock.patch('testlib.Run') as run:
                with self.assertRaisesRegex(ValueError, 'Cleanup requires an existing demo run'):
                    demo.Demo(SimpleNamespace(run=path, rehearsal=False, action='cleanup', preview=False, auto=True))
            run.assert_not_called()
            self.assertFalse(path.exists())

    def test_prepare_lease_error_names_original_run_and_cleanup_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = root / 'lease'
            lease.mkdir()
            original = root / 'original-run'
            demo.write_json(lease / 'owner.json', {'agent': demo.OWNER, 'run': str(original)})
            instance = demo.Demo(SimpleNamespace(run=root / 'new-run', rehearsal=False,
                                                action='prepare', preview=False, auto=True))
            with mock.patch.object(demo, 'LEASE', lease):
                with self.assertRaises(RuntimeError) as error:
                    instance.prepare()
            self.assertIn(str(original), str(error.exception))
            self.assertIn('cleanup --run', str(error.exception))
            self.assertTrue((lease / 'owner.json').exists())

    def test_tmux_layout_forwards_pull_secret_reference_and_uses_supported_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = SimpleNamespace(path=Path(directory), args=SimpleNamespace(
                port=18000, timeout=2700, rehearsal=False, auto=False, detach=True))

            def tmux(command, **kwargs):
                if 'has-session' in command:
                    return subprocess.CompletedProcess(command, 1, '', '')
                output = '$1 @2 %3' if 'new-session' in command else (
                    '%4' if '-h' in command else '%5') if 'split-window' in command else ''
                return subprocess.CompletedProcess(command, 0, output, '')

            with mock.patch.dict(os.environ, {'WORKSHOP_TMUX': '/usr/bin/tmux',
                                              'WORKSHOP_PULL_SECRET_SOURCE': 'source/pull'}, clear=True), \
                    mock.patch.object(demo, 'ALLOCATION', None), \
                    mock.patch.object(demo.subprocess, 'run', side_effect=tmux) as execute, \
                    contextlib.redirect_stdout(io.StringIO()):
                demo.tmux_layout(instance)
            commands = [call.args[0] for call in execute.call_args_list]
            splits = [cmd for cmd in commands if 'split-window' in cmd]
            self.assertEqual([cmd[cmd.index('-l') + 1] for cmd in splits], ['42%', '50%'])
            for cmd in splits + [cmd for cmd in commands if 'respawn-pane' in cmd]:
                self.assertIn('WORKSHOP_PULL_SECRET_SOURCE=source/pull', cmd[-1])
            self.assertEqual(json.loads((instance.path / 'tmux.json').read_text())['panes'], ['%3', '%4', '%5'])

    def test_excerpt_preserves_real_model_parallelism_and_gpu_claim_binding(self):
        lock = json.loads(demo.MODEL_LOCK.read_text())
        graph, claim = demo.render('dynamo-ft-example', lock)
        before = copy.deepcopy((graph, claim))
        text = demo.deployment_excerpt(graph, claim)
        self.assertEqual((graph, claim), before)
        self.assertLessEqual(len(text.splitlines()), 40)
        dgd_excerpt, claim_excerpt = list(yaml.safe_load_all(text))
        frontend, worker = dgd_excerpt['spec']['components']
        self.assertEqual((frontend['type'], frontend['replicas']), ('frontend', 1))
        frontend_main = frontend['podTemplate']['spec']['containers'][0]
        self.assertEqual(frontend_main['command'], ['python3', '-m', 'dynamo.frontend'])
        self.assertEqual(frontend_main['args'], ['--router-mode', 'round-robin', '--trust-remote-code'])
        pod = worker['podTemplate']['spec']
        main = pod['containers'][0]
        self.assertEqual(main['args'][main['args'].index('--model') + 1], lock['model'])
        self.assertEqual(main['args'][main['args'].index('--tensor-parallel-size') + 1], '2')
        self.assertEqual(main['resources']['claims'][0]['name'], pod['resourceClaims'][0]['name'])
        self.assertEqual(pod['resourceClaims'][0]['resourceClaimTemplateName'], claim['metadata']['name'])
        self.assertEqual(claim_excerpt['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
        self.assertNotIn('persistentVolumeClaim', text)
        self.assertNotIn('image:', text)

    def test_short_command_display_keeps_actual_execution_and_quoting(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.Demo(SimpleNamespace(run=Path(directory), rehearsal=True, action='run', preview=False, auto=True))
            path = d.path / 'file with spaces.txt'
            path.write_text('actual file contents\n')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                d.command(['cat', path])
            self.assertIn("$ cat 'file with spaces.txt'", output.getvalue())
            self.assertIn('actual file contents', output.getvalue())
            receipt = json.loads(next(d.path.glob('command-*.json')).read_text())
            self.assertEqual(receipt['args'], ['cat', str(path)])
            args = d.run.kbase + ['apply', '--dry-run=server', '-f', str(d.path / 'deployment.yaml'), '-n', d.ns]
            self.assertEqual(d.command_text(args), 'kubectl apply --dry-run=server -f deployment.yaml -n ' + d.ns)
            foreign = ['kubectl', '--kubeconfig=/another/cluster', 'get', 'pods']
            self.assertIn('--kubeconfig=/another/cluster', d.command_text(foreign))
            self.assertIn('@request.json', d.command_text(['curl', '--data-binary', '@' + str(d.path / 'request.json')]))

    def test_resource_summary_uses_observed_readiness_and_gpu_allocations(self):
        items = [
            {'kind': 'DynamoGraphDeployment', 'metadata': {'name': demo.GRAPH},
             'status': {'conditions': [{'type': 'Ready', 'status': 'False', 'reason': 'NotReady'}]}},
            {'kind': 'Pod', 'metadata': {'name': 'long-generated-worker-name', 'uid': 'worker-uid',
             'labels': {'workshop-role': 'worker', 'nvidia.com/dynamo-component': 'agg'}},
             'spec': {'containers': [{'name': 'main'}]},
             'status': {'phase': 'Running', 'containerStatuses': [{'name': 'main', 'ready': False}], 'podIP': '1.2.3.4'}},
            {'kind': 'Deployment', 'metadata': {'name': 'long-generated-deployment',
             'labels': {'nvidia.com/dynamo-component': 'agg'}}, 'spec': {'replicas': 1}, 'status': {}},
            {'kind': 'PodCliqueSet', 'metadata': {'name': demo.GRAPH},
             'spec': {'replicas': 1}, 'status': {'availableReplicas': 1}},
            {'kind': 'Service', 'metadata': {'name': 'long-generated-service', 'labels': {'workshop-role': 'frontend'}},
             'spec': {'ports': [{'port': 8000}]}},
            {'kind': 'Service', 'metadata': {'name': 'long-generated-worker-service', 'labels': {'workshop-role': 'worker'}},
             'spec': {'ports': [{'port': 9090}]}},
            {'kind': 'Service', 'metadata': {'name': 'long-generated-headless'},
             'spec': {'clusterIP': 'None'}},
            {'kind': 'ResourceClaim', 'metadata': {'ownerReferences': [{'uid': 'worker-uid'}]},
             'status': {'allocation': {'devices': {'results': [
                 {'driver': 'gpu.nvidia.com'}, {'driver': 'gpu.nvidia.com'}]}}}},
            {'kind': 'Pod', 'metadata': {'name': 'offstage-probe'}, 'spec': {'containers': []}, 'status': {}}]
        text = demo.compact_resource_table(items)
        self.assertIn('NotReady', text)
        self.assertIn('0/1 Running', text)
        self.assertIn('2 GPUs allocated', text)
        self.assertIn('0/1 ready', text)
        self.assertIn('PodCliqueSet', text)
        self.assertIn('1/1 available', text)
        self.assertIn('8000/TCP HTTP', text)
        self.assertIn('9090/TCP system', text)
        self.assertIn('Headless DNS', text)
        self.assertIn('discovery', text)
        self.assertNotIn('long-generated', text)
        self.assertNotIn('1.2.3.4', text)
        self.assertNotIn('offstage-probe', text)
        self.assertNotIn('GPU claim', demo.compact_resource_table(items, pods_only=True))
        labels = items[1]['metadata']['labels']
        labels['nvidia.com/dynamo-component-type'] = labels.pop('workshop-role')
        self.assertEqual(demo.compact_resource_table(items), text)

    def test_single_replica_preserves_pins_and_context_with_mx_enabled(self):
        lock = json.loads(demo.MODEL_LOCK.read_text())
        graph, claim = demo.render('dynamo-ft-example', lock)
        self.assertEqual(claim['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
        self.assertEqual(len(graph['spec']['components']), 2)
        for component in graph['spec']['components']:
            self.assertEqual(component['replicas'], 1)
            container = component['podTemplate']['spec']['containers'][0]
            self.assertEqual(container['image'], lock['runtime_image'])
            if component['type'] == 'worker':
                args = container['args']
                self.assertEqual(args[args.index('--model') + 1], lock['model'])
                self.assertEqual(args[args.index('--revision') + 1], lock['revision'])
                self.assertNotIn('--max-model-len', args)
                self.assertNotIn('--kv-events-config', args)
                self.assertEqual(args[args.index('--load-format') + 1], 'modelexpress')
                self.assertEqual(component['podTemplate']['metadata']['labels']['mx-role'], 'source')
                env = {entry['name']: entry.get('value') for entry in container['env']}
                self.assertEqual(env['MX_MODEL_REVISION'], lock['revision'])
                self.assertEqual(env['MX_ARTIFACT_TRANSFER'], '0')
                self.assertEqual(container['resources']['requests']['vpc.amazonaws.com/efa'], '8')
                self.assertIn('--enforce-eager', args)
                self.assertIn('--language-model-only', args)
                for flag in ('--enable-prefix-caching', '--block-size', '--max-num-batched-tokens',
                             '--mamba-backend', '--mamba-ssm-cache-dtype', '--mamba-cache-mode'):
                    self.assertNotIn(flag, args)
                self.assertEqual(args[args.index('--max-num-seqs') + 1], '4')
            else:
                self.assertIn('round-robin', container['args'])

        excerpt = demo.deployment_excerpt(graph, claim)
        self.assertNotIn('--load-format', excerpt)
        self.assertNotIn('MX_', excerpt)

    def test_intro_freezes_discovery_service_before_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.Demo(SimpleNamespace(run=Path(directory), rehearsal=True,
                                                action='prepare', preview=False, auto=True))
            service_path = instance.path / 'source-service.yaml'
            service = yaml.safe_load(service_path.read_text())
            self.assertEqual(service['metadata']['namespace'], instance.ns)
            self.assertEqual(service['spec']['selector'], {'mx-role': 'source', 'workshop-role': 'worker'})
            self.assertEqual([port['port'] for port in service['spec']['ports']], [6555, 6556])
            self.assertEqual(instance.data['mx_source_service_sha256'], demo.digest(service_path))
            service_path.write_text(service_path.read_text() + '\n# drift\n')
            with mock.patch.object(instance.run, 'apply') as apply, \
                    self.assertRaisesRegex(ValueError, 'source service changed'):
                instance.prepare()
            apply.assert_not_called()

    def test_intro_observer_selects_its_own_replica_in_the_shared_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.Demo(SimpleNamespace(run=Path(directory), rehearsal=False,
                                                action='prepare', preview=False, auto=True))
            graph = yaml.safe_load((instance.path / 'deployment.yaml').read_text())
            self.assertEqual(instance.data['pod_selector'], 'workshop-demo=single-replica')
            for component in graph['spec']['components']:
                self.assertEqual(component['podTemplate']['metadata']['labels']['workshop-demo'], 'single-replica')
            response = subprocess.CompletedProcess([], 0, '{"items": []}', '')
            with mock.patch.object(demo, 'panel_read', return_value=response) as read, \
                    contextlib.redirect_stdout(io.StringIO()):
                demo.observe(instance.path, 'logs', once=True)
            command = read.call_args.args[0]
            self.assertEqual(command[command.index('-l') + 1],
                             'workshop-demo=single-replica,workshop-role=worker')

    def completed_intro(self, directory):
        instance = demo.Demo(SimpleNamespace(run=Path(directory), rehearsal=False, timeout=90,
                                            action='run', preview=False, auto=True))
        graph = yaml.safe_load((instance.path / 'deployment.yaml').read_text())
        pods = []
        for component in graph['spec']['components']:
            role = component['type']
            pod = copy.deepcopy(component['podTemplate'])
            pod['metadata'].update(name=role + '-pod', uid=role + '-uid')
            pod['spec']['nodeName'] = 'node-a'
            pod['status'] = {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True',
                'lastTransitionTime': '2026-11-07T03:00:30Z'}], 'containerStatuses': [
                    {'name': 'main', 'restartCount': 0, 'imageID': demo.read_json(demo.MODEL_LOCK)['runtime_image'],
                     'state': {'running': {'startedAt': '2026-11-07T03:00:01Z'}}}]}
            if role == 'worker':
                pod['status']['resourceClaimStatuses'] = [{'name': 'gpu-main', 'resourceClaimName': 'intro-gpus'}]
            pods.append(pod)
        claim = {'metadata': {'name': 'intro-gpus', 'uid': 'claim-uid',
                             'ownerReferences': [{'kind': 'Pod', 'uid': 'worker-uid'}]},
                 'status': {'reservedFor': [{'uid': 'worker-uid'}], 'allocation': {'devices': {'results': [
                     {'driver': 'gpu.nvidia.com', 'pool': 'node-a', 'device': 'gpu-' + str(i)} for i in range(2)]}}}}
        slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': 'node-a', 'pool': {'name': 'node-a'},
            'devices': [{'name': 'gpu-' + str(i), 'attributes': {'uuid': {'string': 'physical-gpu-' + str(i)}}}
                        for i in range(2)]}}]}
        logs = ('2026-11-07T03:00:02Z Trying strategy: default\n'
                '2026-11-07T03:00:03Z MxModelLoader starting\n'
                '2026-11-07T03:00:13Z (Worker_TP0) Model loading took 40 GiB and 10.0 seconds\n'
                '2026-11-07T03:00:13Z (Worker_TP1) Model loading took 40 GiB and 10.0 seconds\n')
        instance.data.update(prepared=True, apply_started_at='2026-11-07T03:00:00Z',
                             ready_observed_at='2026-11-07T03:00:30Z', worker_pod='worker-pod',
                             worker_ready_transition_at='2026-11-07T03:00:30Z')
        instance.data['startup'] = demo.startup_progress(pods, logs, instance.data['apply_started_at'],
                                                       instance.data['ready_observed_at'])
        instance.save_startup_observation(next(p for p in pods if p['metadata']['uid'] == 'worker-uid'),
                                          logs, demo.startup_context(instance.data))
        demo.write_json(instance.path / 'ready-pods.json', {'items': pods})
        (instance.path / 'worker.log').write_text(logs)
        with contextlib.redirect_stdout(io.StringIO()):
            instance.summary()
        instance.save()

        def read(*args, **kwargs):
            value = {'pods': {'items': pods}, 'resourceclaim': claim, 'resourceslices': slices}[args[1]]
            return subprocess.CompletedProcess([], 0, json.dumps(value), '')

        instance.run.k = mock.Mock(side_effect=read)
        return instance, pods, claim, slices

    def test_completed_intro_replay_preserves_mx_bound_startup_evidence(self):
        from demos.modelexpress import source
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(demo, 'ALLOCATION', None):
            instance, _, _, _ = self.completed_intro(directory)
            binding = source.snapshot(instance.path)
            before = {name: (instance.path / name).read_bytes() for name in source.INPUTS}
            original_data = copy.deepcopy(instance.data)
            output = io.StringIO()
            with mock.patch.object(demo, 'lease_owned', return_value=True), \
                    mock.patch.object(instance, 'wait') as wait, mock.patch.object(instance, 'resources') as resources, \
                    mock.patch.object(instance, 'summary') as summary, contextlib.redirect_stdout(output):
                instance.startup()
            wait.assert_not_called()
            resources.assert_not_called()
            summary.assert_not_called()
            self.assertIn('Retained startup timing', output.getvalue())
            self.assertIn('Ready first observed: 30.0s since apply', output.getvalue())
            self.assertEqual(instance.data, original_data)
            self.assertEqual(before, {name: (instance.path / name).read_bytes() for name in source.INPUTS})
            source.validate_files(binding)
            for call in instance.run.k.call_args_list:
                self.assertIn('timeout', call.kwargs)
                self.assertFalse(call.kwargs['check'])

    def test_completed_intro_replay_refuses_identity_readiness_image_and_claim_drift(self):
        def worker(pods):
            return next(p for p in pods if p['metadata']['labels']['workshop-role'] == 'worker')

        mutations = {
            'worker replacement': lambda pods, claim, slices: worker(pods)['metadata'].update(uid='replacement'),
            'frontend replacement': lambda pods, claim, slices: pods[0]['metadata'].update(uid='replacement'),
            'not Ready': lambda pods, claim, slices: worker(pods)['status']['conditions'][0].update(status='False'),
            'restart': lambda pods, claim, slices: worker(pods)['status']['containerStatuses'][0].update(restartCount=1),
            'image': lambda pods, claim, slices: worker(pods)['status']['containerStatuses'][0].update(imageID='other@sha256:wrong'),
            'claim reference': lambda pods, claim, slices: worker(pods)['status']['resourceClaimStatuses'][0].update(resourceClaimName='other'),
            'claim owner': lambda pods, claim, slices: claim['metadata']['ownerReferences'][0].update(uid='other'),
            'GPU node': lambda pods, claim, slices: slices['items'][0]['spec'].update(nodeName='node-b'),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory, \
                    mock.patch.object(demo, 'ALLOCATION', None), mock.patch.object(demo, 'lease_owned', return_value=True):
                instance, pods, claim, slices = self.completed_intro(directory)
                before = {name: demo.digest(instance.path / name) for name in ('ready-pods.json', 'worker.log', 'timing.json')}
                mutate(pods, claim, slices)
                with self.assertRaises((RuntimeError, ValueError)), contextlib.redirect_stdout(io.StringIO()):
                    instance.startup()
                self.assertEqual(before, {name: demo.digest(instance.path / name) for name in before})

    def test_completed_intro_replay_fails_closed_on_transport_outage(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(demo, 'ALLOCATION', None), \
                mock.patch.object(demo, 'lease_owned', return_value=True):
            instance, _, _, _ = self.completed_intro(directory)
            before = {name: demo.digest(instance.path / name) for name in ('ready-pods.json', 'worker.log', 'timing.json')}
            instance.run.k = mock.Mock(return_value=subprocess.CompletedProcess([], 124, '', 'Unable to connect to the server'))
            with self.assertRaises(demo.StartupTransportError), mock.patch.object(instance, 'wait') as wait, \
                    mock.patch.object(demo, 'StartupDisplay') as display, contextlib.redirect_stdout(io.StringIO()):
                instance.startup()
            wait.assert_not_called()
            display.assert_not_called()
            self.assertEqual(before, {name: demo.digest(instance.path / name) for name in before})

    def test_shared_mx_configuration_can_switch_roles_without_duplicate_setup(self):
        lock = demo.read_json(demo.MODEL_LOCK)
        source, _ = demo.render('test', lock)
        target = copy.deepcopy(source)
        demo.weights.configure(target, lock, role='target')
        demo.weights.configure(target, lock, role='target')
        self.assertEqual(demo.weights.engine_signature(source), demo.weights.engine_signature(target))
        worker = next(c for c in target['spec']['components'] if c['type'] == 'worker')
        spec = worker['podTemplate']['spec']
        self.assertEqual(worker['podTemplate']['metadata']['labels']['mx-role'], 'target')
        self.assertEqual(demo.weights.worker_config(target)['args'].count('--load-format'), 1)
        self.assertEqual([v['name'] for v in spec['volumes']].count('efa'), 1)
        native, _ = demo.render('test', lock, enable_mx=False)
        self.assertNotIn('--load-format', demo.weights.worker_config(native)['args'])

    def test_readiness_requires_both_roles_and_ready_conditions(self):
        def pod(role, ready):
            return {'metadata': {'labels': {'workshop-role': role}},
                    'status': {'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]}}
        frontend, worker = pod('frontend', True), pod('worker', False)
        self.assertFalse(demo.ready_pods([frontend]))
        self.assertFalse(demo.ready_pods([frontend, worker]))
        worker['status']['conditions'][0]['status'] = 'True'
        self.assertTrue(demo.ready_pods([frontend, worker]))
        self.assertFalse(demo.ready_pods([frontend, worker, copy.deepcopy(worker)]))

    def test_log_phases_use_slowest_rank_and_unknown_stays_unknown(self):
        text = ('Model loading took 38.2 GiB and 51.2 seconds\n'
                'Model loading took 38.2 GiB and 53.7 seconds\n'
                'init engine (profile, create kv cache, warmup model) took 150.3 s\n')
        result = demo.phase_timings(text)
        self.assertEqual(result['model_loading'], 53.7)
        self.assertEqual(result['engine_initialization'], 150.3)
        self.assertIsNone(result['compilation'])

    def test_other_workstream_lease_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            lease = Path(directory) / 'lease'
            lease.mkdir()
            original = json.dumps({'agent': 'other-controller', 'run': '/some/run'})
            (lease / 'owner.json').write_text(original)
            with mock.patch.object(demo, 'LEASE', lease):
                with self.assertRaises(RuntimeError):
                    demo.acquire('/another/run')
            self.assertEqual((lease / 'owner.json').read_text(), original)

    def test_startup_timing_uses_pod_and_log_boundaries(self):
        pods = [{'metadata': {'labels': {'workshop-role': role}}, 'status': {
            'conditions': [{'type': 'Ready', 'status': 'True', 'lastTransitionTime': '2026-11-03T00:01:05Z'}],
            'containerStatuses': [{'name': 'main', 'state': {'running': {'startedAt': '2026-11-03T00:00:12Z'}}}]}}
            for role in ('worker', 'frontend')]
        logs = ('2026-11-03T00:00:20Z Loading model from scratch...\n'
                '2026-11-03T00:00:40Z Model loading took 38 GiB and 20 seconds\n'
                '2026-11-03T00:01:00Z init engine (profile, create kv cache, warmup model) took 20 s\n')
        progress = demo.startup_progress(pods, logs, '2026-11-03T00:00:00Z', '2026-11-03T00:02:00Z')
        self.assertTrue(progress['ready'])
        self.assertEqual(progress['total_seconds'], 65)
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(phases['Pod startup']['seconds'], 12)
        self.assertEqual(phases['Engine init']['seconds'], 20)
        self.assertEqual(phases['Readiness']['seconds'], 5)
        self.assertEqual(phases['Weight loading']['status'], 'unknown')
        self.assertIsNone(phases['Weight loading']['seconds'])
        self.assertEqual(progress['logged_seconds_slowest_rank']['model_loading'], 20)
        for pod in pods:
            pod['status']['conditions'][0]['status'] = 'False'
        running = demo.startup_progress(pods, logs.splitlines()[0], '2026-11-03T00:00:00Z',
                                        '2026-11-03T00:00:30Z')
        phases = {p['name']: p for p in running['phases']}
        self.assertEqual(phases['Model setup']['status'], 'running')
        self.assertEqual(phases['Model setup']['seconds'], 10)
        self.assertEqual(phases['Weight loading']['status'], 'pending')
        self.assertIsNone(phases['Weight loading']['seconds'])
        prefetch = demo.startup_progress(pods,
            '2026-11-03T00:00:20Z Prefetching checkpoint files into page cache started (in background)',
            '2026-11-03T00:00:00Z', '2026-11-03T00:00:30Z')
        phase = next(p for p in prefetch['phases'] if p['name'] == 'Weight loading')
        self.assertEqual((phase['status'], phase['seconds']), ('running', 10))
        nano = demo.startup_progress(pods,
            '2026-11-03T00:00:20.123456789Z Prefetching checkpoint files into page cache started (in background)',
            '2026-11-03T00:00:00Z', '2026-11-03T00:00:30Z')
        phase = next(p for p in nano['phases'] if p['name'] == 'Weight loading')
        self.assertEqual(phase['status'], 'running')
        self.assertAlmostEqual(phase['seconds'], 9.876544)

    def test_duplicate_presenter_cannot_run_the_same_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            with demo.presenter_lock(directory):
                with self.assertRaises(RuntimeError):
                    with demo.presenter_lock(directory):
                        self.fail('A duplicate presenter acquired the run lock.')

    def test_rehearsal_completes_without_kubectl_or_fake_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run with spaces'
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'single-replica', '--plain', '--rehearsal', '--auto',
                                     '--run', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NO CLUSTER CALLS', result.stdout)
            self.assertNotIn('Enter or Space', result.stdout)
            self.assertNotIn('Preparation', result.stdout)
            self.assertNotIn('Commands shown relative', result.stdout)
            opening = result.stdout.split('Next: 2/6', 1)[0]
            self.assertNotIn('Step finished in', opening)
            self.assertNotIn('Step finished in', result.stdout)
            self.assertLess(result.stdout.index('Startup timing'), result.stdout.index('3/6  The HTTP endpoint'))
            self.assertLess(result.stdout.index('Startup timing'), result.stdout.index('Request body:'))
            self.assertLess(result.stdout.index('Assistant response:'), result.stdout.index('5/6  AIPerf: one agent'))
            self.assertLess(result.stdout.index('--concurrency 1'), result.stdout.index('6/6  AIPerf: eight agents'))
            self.assertLess(result.stdout.index('6/6  AIPerf: eight agents'), result.stdout.index('--concurrency 8'))
            self.assertEqual(result.stdout.count('[REHEARSAL] AIPerf is not run'), 2)
            self.assertFalse(list(path.glob('aiperf-c*')))
            self.assertTrue(json.loads((path / 'response.json').read_text())['simulated'])
            timing = json.loads((path / 'timing.json').read_text())
            self.assertTrue(timing['rehearsal'])
            self.assertTrue(all(value is None for value in timing['observed_seconds_since_apply'].values()))
            receipts = [json.loads(p.read_text()) for p in path.glob('command-*.json')]
            self.assertTrue(receipts)
            self.assertTrue(all(receipt['args'][0] == 'cat' for receipt in receipts))
            self.assertEqual(Path(receipts[0]['args'][1]).name, 'deployment-excerpt.yaml')
            self.assertNotIn('image:', result.stdout)
            self.assertIn('Full executable files: deployment.yaml + gpu-claim-template.yaml', result.stdout)
            self.assertEqual(demo.digest(path / 'deployment.yaml'), json.loads((path / 'demo.json').read_text())['manifest_sha256'])

    def test_full_manifest_flag_is_read_only_and_preserves_executable_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            args = [sys.executable, '-B', '-m', 'demos', 'single-replica', '--full-manifest', '--run', directory]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('image:', result.stdout)
            self.assertIn(Path(directory, 'deployment.yaml').read_text(), result.stdout)
            self.assertFalse(list(Path(directory).glob('command-*.json')))
            self.assertNotIn('apply_started_at', json.loads(Path(directory, 'demo.json').read_text()))

    def test_compact_live_observer_does_not_write_run_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            demo.write_json(path / 'demo.json', {'namespace': 'example', 'rehearsal': False, 'step': 1, 'prepared': True})
            before = (path / 'demo.json').read_bytes()
            payload = {'items': [{'kind': 'DynamoGraphDeployment', 'metadata': {'name': demo.GRAPH}, 'status': {}}]}
            with mock.patch.object(demo.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps(payload), stderr='')) as command, contextlib.redirect_stdout(io.StringIO()) as out:
                demo.observe(path, 'resources', once=True)
            self.assertIn('KIND', out.getvalue())
            self.assertIn('Starting', out.getvalue())
            self.assertIn(demo.INTRO_RESOURCES, command.call_args.args[0])
            self.assertEqual((path / 'demo.json').read_bytes(), before)
            self.assertEqual({p.name for p in path.iterdir()}, {'demo.json'})

    def test_observer_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            demo.write_json(path / 'demo.json', {'namespace': 'example', 'rehearsal': True, 'step': 1})
            before = (path / 'demo.json').read_bytes()
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'single-replica', 'observe', '--once', '--run', directory],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((path / 'demo.json').read_bytes(), before)
            self.assertEqual(set(p.name for p in path.iterdir()), {'demo.json'})

    def test_space_advances_one_step_and_q_stops_before_deploy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run'
            master, slave = pty.openpty()
            process = subprocess.Popen([sys.executable, '-B', '-m', 'demos', 'single-replica', '--rehearsal', '--plain', '--run', str(path)],
                                       cwd=ROOT, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
            os.close(slave)
            output = bytearray()
            def until_state(predicate):
                end = time.monotonic() + 10
                while time.monotonic() < end:
                    if select.select([master], [], [], 0.2)[0]:
                        output.extend(os.read(master, 65536))
                    if (path / 'demo.json').exists() and predicate(json.loads((path / 'demo.json').read_text())):
                        return
                self.fail('Presenter did not reach the expected state: ' + output.decode(errors='replace')[-1000:])
            try:
                until_state(lambda d: d.get('awaiting_key') and d['prepared'] and d['step'] == 0)
                self.assertTrue(json.loads((path / 'demo.json').read_text())['prepared'])
                os.write(master, b' ')
                until_state(lambda d: d.get('awaiting_key') and d['step'] == 1)
                self.assertFalse(list(path.glob('command-*.json')))
                os.write(master, b' ')
                until_state(lambda d: d.get('awaiting_key') and d['step'] == 1 and
                            bool(list(path.glob('command-*.json'))))
                os.write(master, b' ')
                until_state(lambda d: d.get('awaiting_key') and d['step'] == 2)
                os.write(master, b'q')
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 130)
                self.assertNotIn('apply_started_at', json.loads((path / 'demo.json').read_text()))
                self.assertNotIn(b'Enter or Space', output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)

    def test_live_run_requires_offstage_preparation_before_opening_panes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'single-replica', '--detach', '--run', directory],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Prepare this run offstage', result.stderr)
            self.assertIn('prepare --run', result.stderr)
            self.assertFalse((Path(directory) / 'tmux.json').exists())

    def test_request_is_visible_but_not_submitted_until_keypress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run'
            program = '''from argparse import Namespace
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from demos.common.runtime import Demo
d=Demo(Namespace(run=Path(sys.argv[2]),rehearsal=True,action='run',preview=False,auto=False))
d.data['base_url']='http://127.0.0.1:18000'
d.request()
'''
            master, slave = pty.openpty()
            process = subprocess.Popen([sys.executable, '-B', '-c', program, str(ROOT), str(path)],
                                       cwd=ROOT, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
            os.close(slave)
            output = bytearray()
            try:
                end = time.monotonic() + 10
                while time.monotonic() < end:
                    if select.select([master], [], [], 0.1)[0]:
                        output.extend(os.read(master, 65536))
                    if (path / 'demo.json').exists():
                        state = json.loads((path / 'demo.json').read_text())
                        if state.get('awaiting_key') and b'$ curl' in output and b'Request body:' in output:
                            break
                else:
                    self.fail('Request command was not presented: ' + output.decode(errors='replace'))
                self.assertFalse((path / 'response.json').exists())
                self.assertNotIn('response_observed_at', state)
                os.write(master, b'\r')
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 0)
                self.assertTrue(json.loads((path / 'response.json').read_text())['simulated'])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
