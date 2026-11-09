"""Evidence and lifecycle gates for the P/D and Snapshot presenter runners."""
from tests.support import ROOT
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

import demos.common.placement as placement
import demos.common.runtime as ui
import demos.common.support as support
from demos.registry import by_script
import demos.disaggregated.demo as pd
import demos.snapshot.demo as snap


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18003, timeout=60, storage=None)


class EvidenceTests(unittest.TestCase):
    def test_teaching_settings_project_effective_frontend_and_worker_fields(self):
        graph, claims = pd.render('dynamo-ft-test', ui.read_json(ui.MODEL_LOCK))
        frontend, prefill, decode = graph['spec']['components']
        frontend['replicas'] = 2
        frontend['podTemplate']['spec']['containers'][0]['args'] = ['--router-mode', 'round-robin']
        claims[0]['spec']['spec']['devices']['requests'][0]['exactly']['count'] = 3
        settings = pd.teaching_settings(graph, claims)['components']
        self.assertEqual(settings[0]['replicas'], 2)
        self.assertEqual(settings[0]['command'], frontend['podTemplate']['spec']['containers'][0]['command'])
        self.assertEqual(settings[0]['args'], ['--router-mode', 'round-robin'])
        self.assertEqual(settings[1]['GPUs_per_replica'], 3)
        self.assertEqual(settings[2]['GPUs_per_replica'], 2)
        for shown, actual in zip(settings[1:], (prefill, decode)):
            pod = actual['podTemplate']['spec']
            self.assertEqual(shown['node'], pod['nodeSelector']['kubernetes.io/hostname'])
            connector = json.loads(shown['args']['--kv-transfer-config'])
            self.assertEqual(connector['kv_role'], 'kv_producer' if actual['type'] == 'prefill' else 'kv_consumer')

    def test_pd_keeps_qualified_transfer_contract_and_four_gpus(self):
        lock = ui.read_json(ui.MODEL_LOCK)
        graph, claims = pd.render('dynamo-ft-test', lock)
        self.assertEqual(len(claims), 2)
        self.assertEqual(sum(c['spec']['spec']['devices']['requests'][0]['exactly']['count'] for c in claims), 4)
        for component in graph['spec']['components']:
            main = component['podTemplate']['spec']['containers'][0]
            self.assertEqual(main['image'], lock['runtime_image'])
            if component['type'] == 'frontend':
                continue
            argv = main['args']
            self.assertNotIn('--enforce-eager', argv)
            self.assertIn('--language-model-only', argv)
            self.assertEqual(argv[argv.index('--revision') + 1], lock['revision'])
            self.assertEqual(argv[argv.index('--disaggregation-mode') + 1], component['type'])
            connector = json.loads(argv[argv.index('--kv-transfer-config') + 1])
            self.assertEqual(connector['kv_connector_extra_config']['backends'], ['LIBFABRIC'])
            self.assertEqual({e['name']: e.get('value') for e in main['env']}['VLLM_SSM_CONV_STATE_LAYOUT'], 'DS')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'manifest.yaml'
            support.write_yaml(path, graph)
            self.assertIn("value: 'y'", path.read_text())
            self.assertEqual(yaml.safe_load(path.read_text()), graph)

    def test_pd_readiness_needs_all_three_unique_roles(self):
        pods = [{'metadata': {'labels': {'workshop-role': r}},
                 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for r in pd.ROLES]
        self.assertTrue(pd.ready(pods))
        self.assertFalse(pd.ready(pods[:-1]))
        self.assertFalse(pd.ready(pods + [copy.deepcopy(pods[-1])]))
        pods[-1]['metadata']['deletionTimestamp'] = 'now'
        self.assertFalse(pd.ready(pods))

    def test_handoff_requires_positive_bytes_no_errors_and_unchanged_pod(self):
        def record(values):
            return {'pod_uid': 'same', 'node': 'decode-node', 'metrics': {'9090': '\n'.join(
                name + '{worker="d"} ' + str(v) for name, v in zip(pd.COUNTERS, values))}}
        before, after = record([10, 1, 0, 0]), record([1024, 2, 0, 0])
        response = {'worker': {'prefill_worker_id': 'p', 'decode_worker_id': 'd'}}
        self.assertEqual(pd.transfer_proof(before, after, response)['metric_deltas'][pd.COUNTERS[0]], 1014)
        for invalid in [record([10, 1, 0, 0]), record([1024, 2, 1, 0]),
                        {**after, 'pod_uid': 'replacement'}, {**after, 'metrics': {}}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                pd.transfer_proof(before, invalid, response)
        with self.assertRaises(ValueError):
            pd.transfer_proof(before, after, {'worker': {'prefill_worker_id': 'p', 'decode_worker_id': 'p'}})

    def test_sse_must_finish_and_identify_distinct_workers(self):
        chunk = {'model': 'model', 'choices': [{'delta': {'content': 'code'}}],
                 'nvext': {'worker_id': {'prefill_worker_id': 'p', 'decode_worker_id': 'd'}},
                 'usage': {'completion_tokens': 1}}
        raw = 'data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n'
        self.assertEqual(pd.decode_stream(raw, 'model')['content'], 'code')
        for invalid in [raw.replace('data: [DONE]', ''), raw.replace('"decode_worker_id": "d"', '"decode_worker_id": "p"')]:
            with self.assertRaises(ValueError):
                pd.decode_stream(invalid, 'model')

    def test_snapshot_requires_exact_content_binding_and_fresh_uid(self):
        source = ui.read_json(snap.SOURCE)
        snapshot = {'metadata': {'uid': source['snapshot_uid']},
                    'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        content = {'metadata': {'uid': source['content_uid']}, 'status': copy.deepcopy(snapshot['status']),
                   'spec': {'snapshotRef': {'uid': source['snapshot_uid']},
                            'source': {'nodeName': source['node'], 'podRef': {'uid': source['source_pod_uid']}}}}
        snap.validate_source(snapshot, content, source)
        content['spec']['snapshotRef']['uid'] = 'other'
        with self.assertRaises(ValueError):
            snap.validate_source(snapshot, content, source)
        lock = ui.read_json(ui.MODEL_LOCK)
        pod = {'metadata': {'uid': 'replacement', 'name': 'pod', 'annotations': {'nvidia.com/restore-from': source['snapshot_name']}},
               'spec': {'nodeName': source['node']}, 'status': {
                   'conditions': [{'type': t, 'status': 'True'} for t in ('Ready', 'nvidia.com/Restored')],
                   'containerStatuses': [{'name': 'main', 'imageID': lock['runtime_image'], 'restartCount': 0}]}}
        claim = {'status': {'allocation': {'devices': {'results': [{'pool': p, 'device': d} for p, d in source['physical_gpu_pair']]}}}}
        self.assertTrue(snap.validate_pod(pod, claim, source, lock, 'previous')['restored'])
        with self.assertRaises(ValueError):
            snap.validate_pod(pod, claim, source, lock, 'replacement')
        claim['status']['allocation']['devices']['results'][0]['device'] = 'gpu-0'
        with self.assertRaises(ValueError):
            snap.validate_pod(pod, claim, source, lock)

    def test_snapshot_timing_ignores_other_pods_and_rejects_wrong_artifact(self):
        def line(pod, uid):
            return 'Restore timing summary ' + json.dumps({'pod': pod, 'content_uid': uid,
                'restore': {'duration': '37.5s', 'phases': {'criu_restore': '20s', 'cuda_restore': '15.5s'}}})
        log = line('ns/other', 'other') + '\n' + line('ns/pod', 'artifact')
        self.assertEqual(snap.restore_timing(log, 'ns', 'pod', 'artifact')['agent_seconds'], 37.5)
        with self.assertRaises(ValueError):
            snap.restore_timing(log, 'ns', 'pod', 'different')
        with self.assertRaises(ValueError):
            snap.restore_timing(log + '\n' + line('ns/pod', 'artifact'), 'ns', 'pod', 'artifact')


class PlacementTests(unittest.TestCase):
    DAY = ROOT / 'demos/allocations/workshop-disaggregated.json'

    def test_workshop_placement_pins_each_pool_on_its_qualified_node(self):
        day = json.loads(self.DAY.read_text())
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {placement.ENV: str(self.DAY)}):
            presenter = pd.DisaggDemo(args(Path(directory) / 'run'))
            graph = ui.read_json(presenter.path / 'deployment.json')
            claims = {c['metadata']['name']: c for c in ui.read_json(presenter.path / 'gpu-claims.json')['items']}
            self.assertEqual(presenter.data['placement'], day)
            for component in graph['spec']['components']:
                role = component['type']
                if role == 'frontend':
                    continue
                target = day['targets'][role][0]
                spec = component['podTemplate']['spec']
                self.assertEqual(spec['nodeSelector'], {'kubernetes.io/hostname': target['node']})
                request = claims[pd.GRAPH + '-' + role + '-gpus']['spec']['spec']['devices']['requests'][0]['exactly']
                self.assertTrue(request['selectors'][0]['cel']['expression'].endswith(json.dumps(target['gpu_uuids'])))
            pd.DisaggDemo(args(presenter.path))
        with mock.patch.dict(os.environ, {placement.ENV: str(self.DAY)}), tempfile.TemporaryDirectory() as directory:
            unpinned = Path(directory) / 'run'
            with mock.patch.dict(os.environ):
                os.environ.pop(placement.ENV)
                pd.DisaggDemo(args(unpinned))
            with self.assertRaisesRegex(ValueError, 'has no GPU placement'):
                pd.DisaggDemo(args(unpinned))

    def test_placement_cannot_move_the_qualified_node_split(self):
        moved = json.loads(self.DAY.read_text())
        moved['targets']['prefill'][0]['node'] = 'kubecon-nke-site-cp-0942'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'moved.json'
            path.write_text(json.dumps(moved))
            with mock.patch.dict(os.environ, {placement.ENV: str(path)}):
                with self.assertRaisesRegex(ValueError, 'keeps the qualified nodes'):
                    pd.DisaggDemo(args(Path(directory) / 'run'))

    def test_scheduled_workers_must_hold_their_pinned_gpus(self):
        day = json.loads(self.DAY.read_text())
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {placement.ENV: str(self.DAY)}):
            presenter = pd.DisaggDemo(args(Path(directory) / 'run'))
        image = ui.read_json(ui.MODEL_LOCK)['runtime_image']
        slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'nodeName': t[0]['node'], 'pool': {'name': role},
                                      'devices': [{'name': 'gpu-' + str(i), 'attributes': {'uuid': {'string': u}}}
                                                  for i, u in enumerate(t[0]['gpu_uuids'] + ['GPU-00000000-0000-0000-0000-000000000000'])]}}
                            for role, t in day['targets'].items()]}

        def pods(devices):
            return [{'metadata': {'uid': role + '-pod', 'labels': {'workshop-role': role}},
                     'spec': {'nodeName': day['targets'][role][0]['node'], 'containers': [{}]},
                     'status': {'containerStatuses': [{'name': 'main', 'imageID': image}]},
                     'claim': {'metadata': {'uid': role + '-claim'}, 'status': {'allocation': {'devices': {'results': [
                         {'driver': 'gpu.nvidia.com', 'pool': role, 'device': 'gpu-' + str(i)} for i in devices]}}}}}
                    for role in ('prefill', 'decode')]

        reader = SimpleNamespace(get=lambda *a: slices)
        verify = mock.patch('gpu_claims.verify_allocation', side_effect=lambda run, pod, container, count: pod['claim'])
        with verify:
            presenter.validate_workers(pods([0, 1]), reader=reader)
            self.assertEqual({r: p['gpu_uuids'] for r, p in presenter.data['placement_observed'].items()},
                             {r: sorted(t[0]['gpu_uuids']) for r, t in day['targets'].items()})
            with self.assertRaisesRegex(ValueError, 'differ from the pinned pair'):
                presenter.validate_workers(pods([0, 2]), reader=reader)


class LifecycleTests(unittest.TestCase):
    def test_live_pd_walkthrough_requires_offstage_preparation_without_applying(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = pd.DisaggDemo(args(Path(directory) / 'run'))
            presenter.args.rehearsal = False
            with mock.patch.object(presenter, 'prepare') as prepare, \
                    mock.patch.object(presenter.run, 'apply') as apply, \
                    self.assertRaisesRegex(RuntimeError, 'Prepare this run offstage'):
                presenter.guided()
            prepare.assert_not_called()
            apply.assert_not_called()

    def test_pd_prime_starts_pools_offstage_and_guided_does_not_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = pd.DisaggDemo(args(Path(directory) / 'run'))
            calls = []
            with mock.patch.object(presenter, 'prepare', side_effect=lambda: calls.append('prepare')), \
                    mock.patch.object(presenter, 'startup', side_effect=lambda: calls.append('startup')), \
                    contextlib.redirect_stdout(io.StringIO()):
                presenter.prime()
            self.assertEqual(calls, ['prepare', 'startup'])
            self.assertTrue(presenter.data['primed_at'])
            presenter.args.rehearsal = False
            presenter.data['prepared'] = True
            output = io.StringIO()
            with mock.patch.object(presenter, 'prepare') as prepare, \
                    mock.patch.object(presenter, 'run_steps') as run_steps, \
                    contextlib.redirect_stdout(output):
                presenter.guided()
            prepare.assert_not_called()
            run_steps.assert_called_once()
            self.assertNotIn('Preparation', output.getvalue())

    def test_pd_retained_startup_keeps_original_clock_and_checks_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            presenter = pd.DisaggDemo(args(Path(directory) / 'run'))
            presenter.data.update(ready_observed_at='original-ready', apply_started_at='original-apply')
            output = io.StringIO()
            with mock.patch.object(presenter, 'check_identity') as identity, \
                    mock.patch.object(presenter, 'deploy') as deploy, \
                    mock.patch.object(presenter, 'wait') as wait, \
                    mock.patch.object(presenter, 'summary') as summary, \
                    contextlib.redirect_stdout(output):
                presenter.startup()
            identity.assert_called_once()
            summary.assert_called_once()
            deploy.assert_not_called()
            wait.assert_not_called()
            self.assertEqual(presenter.data['apply_started_at'], 'original-apply')
            self.assertEqual(presenter.data['ready_observed_at'], 'original-ready')
            self.assertIn('no new startup is measured', output.getvalue())

    def test_offline_walkthroughs_no_cluster_and_timing_before_inference(self):
        for cls, marker, proof in [(pd.DisaggDemo, 'Startup timing', 'transfer-proof.json'),
                                   (snap.SnapshotDemo, 'Restore timing', 'recovery-proof.json')]:
            with self.subTest(cls=cls), tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'run with spaces'
                result = subprocess.run([sys.executable, '-B', '-m', 'demos', by_script(cls.entrypoint).selector, '--plain', '--rehearsal',
                                         '--auto', '--run', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('NO CLUSTER CALLS', result.stdout)
                self.assertNotIn('Enter or Space', result.stdout)
                self.assertNotIn('Offstage preparation / prime', result.stdout)
                self.assertNotIn('\nPreparation\n', result.stdout)
                self.assertNotIn('Step finished in', result.stdout)
                self.assertLess(result.stdout.index(marker), result.stdout.index('$ curl'))
                self.assertTrue(ui.read_json(path / 'response.json')['simulated'])
                self.assertTrue(ui.read_json(path / proof)['simulated'])
                self.assertTrue(all(ui.read_json(p)['args'][0] == 'cat' for p in path.glob('command-*.json')))
                saved = (path / 'demo.json').read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    support.observe(path, 'resources', once=True)
                self.assertEqual(saved, (path / 'demo.json').read_bytes())
                self.assertIn('REHEARSAL / SIMULATED', output.getvalue())
                if cls is pd.DisaggDemo:
                    self.assertIn('$ cat disagg-settings.yaml', result.stdout)
                    self.assertLessEqual(len((path / 'disagg-settings.yaml').read_text().splitlines()), 40)
                    self.assertLessEqual(max(map(len, (path / 'disagg-settings.yaml').read_text().splitlines())), 100)
                    settings = yaml.safe_load((path / 'disagg-settings.yaml').read_text())['components']
                    graph = ui.read_json(path / 'deployment.json')['spec']['components']
                    for shown, actual in zip(settings[1:], graph[1:]):
                        argv = actual['podTemplate']['spec']['containers'][0]['args']
                        self.assertEqual(shown['args']['--kv-transfer-config'], argv[argv.index('--kv-transfer-config') + 1])
                    self.assertIn('prefill', output.getvalue())
                    self.assertIn('decode', output.getvalue())
                if cls is snap.SnapshotDemo:
                    self.assertLessEqual(len(ui.read_json(path / 'demo.json')['resource_note']), 73)
                    self.assertIn('$ cat recovery-summary.txt', result.stdout)
                    self.assertIn('Prepared Snapshot/content', result.stdout)
                    self.assertNotEqual(ui.read_json(path / proof)['before_uid'], ui.read_json(path / proof)['after_uid'])

    def test_both_runners_preserve_foreign_measurement_fence(self):
        with tempfile.TemporaryDirectory() as d:
            lease = Path(d) / 'lease'
            lease.mkdir()
            original = json.dumps({'agent': 'remote-controller', 'run': '/other/run'})
            (lease / 'owner.json').write_text(original)
            for cls in (pd.DisaggDemo, snap.SnapshotDemo):
                demo = cls(args(Path(d) / cls.__name__))
                demo.args.rehearsal = False
                with mock.patch.object(ui, 'LEASE', lease), mock.patch.object(demo.run, 'k') as k:
                    with self.assertRaises(RuntimeError):
                        demo.prepare()
                    with self.assertRaises(RuntimeError):
                        demo.cleanup()
                    k.assert_not_called()
            self.assertEqual((lease / 'owner.json').read_text(), original)

    def test_snapshot_manifest_keeps_captured_engine_and_owns_only_new_pod(self):
        with tempfile.TemporaryDirectory() as d:
            demo = snap.SnapshotDemo(args(Path(d) / 'run'))
            manifest = demo.make_manifest('new-restore')
            pod = next(o for o in manifest['items'] if o['kind'] == 'Pod')
            job = ui.read_json(demo.path / 'snapshotjob.json')
            self.assertEqual(pod['spec']['containers'][0]['args'], job['spec']['podTemplate']['spec']['containers'][0]['args'])
            self.assertEqual([c['name'] for c in pod['spec']['containers']], ['main'])
            self.assertEqual(pod['metadata']['labels']['snapshot-storage-experiment'], demo.run.state['run_id'])
            self.assertEqual(pod['metadata']['annotations']['nvidia.com/restore-from'], demo.source['snapshot_name'])
            self.assertNotIn('nvidia.com/gpu', pod['spec']['containers'][0]['resources']['limits'])
            self.assertEqual(len(manifest['items']), 2)
            claim = next(o for o in manifest['items'] if o['kind'] == 'ResourceClaimTemplate')
            expression = claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'][0]['cel']['expression']
            for uuid in demo.source['physical_gpu_uuids']:
                self.assertIn(uuid, expression)

    def test_snapshot_cleanup_refuses_unowned_pods_and_keeps_lease(self):
        with tempfile.TemporaryDirectory() as d:
            demo = snap.SnapshotDemo(args(Path(d) / 'run'))
            demo.args.rehearsal = False
            demo.run.state['workers'] = ['foreign']
            lease = Path(d) / 'lease'
            with mock.patch.object(ui, 'LEASE', lease):
                ui.acquire(demo.path, snap.OWNER)
                foreign = subprocess.CompletedProcess([], 0, json.dumps({'metadata': {'labels': {}}}), '')
                with mock.patch.object(demo.run, 'k', return_value=foreign) as k:
                    with self.assertRaises(ValueError):
                        demo.cleanup()
                    self.assertEqual(k.call_count, 1)
                self.assertTrue(ui.lease_owned(demo.path, snap.OWNER))

    def test_interrupted_snapshot_restore_resumes_same_pod_without_reapplying(self):
        with tempfile.TemporaryDirectory() as d:
            demo = snap.SnapshotDemo(args(Path(d) / 'run'))
            demo.args.rehearsal = False
            name = demo.run.state['run_id'] + '-1'
            applied = '2026-11-03T00:00:00+00:00'
            demo.data['pending_restore'] = {'name': name, 'applied_at': applied, 'pod_uid': 'same-uid'}
            pod = {'metadata': {'uid': 'same-uid', 'labels': {'snapshot-storage-experiment': demo.run.state['run_id']}}}
            record = {'pod': name, 'pod_uid': 'same-uid', 'simulated': False}
            result = subprocess.CompletedProcess([], 0, json.dumps(pod), '')
            with mock.patch.object(ui, 'lease_owned', return_value=True), \
                    mock.patch.object(demo, 'storage_ready'), mock.patch.object(demo, 'wait'), \
                    mock.patch.object(demo, 'validate_live', return_value=record), \
                    mock.patch.object(demo.run, 'k', return_value=result), \
                    mock.patch.object(demo.run, 'apply') as apply, mock.patch.object(demo, 'show_command') as show:
                demo.start_restore()
                apply.assert_not_called()
                show.assert_not_called()
            self.assertEqual(demo.data['apply_started_at'], applied)
            self.assertNotIn('pending_restore', demo.data)
            self.assertEqual(demo.data['restores'], [record])

    def test_snapshot_pending_restore_rejects_another_uid(self):
        with tempfile.TemporaryDirectory() as d:
            demo = snap.SnapshotDemo(args(Path(d) / 'run'))
            demo.args.rehearsal = False
            demo.data['pending_restore'] = {'name': 'restore', 'applied_at': ui.now(), 'pod_uid': 'expected'}
            pod = {'metadata': {'uid': 'changed', 'labels': {'snapshot-storage-experiment': demo.run.state['run_id']}}}
            result = subprocess.CompletedProcess([], 0, json.dumps(pod), '')
            with mock.patch.object(ui, 'lease_owned', return_value=True), \
                    mock.patch.object(demo, 'storage_ready'), mock.patch.object(demo.run, 'k', return_value=result), \
                    mock.patch.object(demo.run, 'apply') as apply, self.assertRaises(ValueError):
                demo.start_restore()
            apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
