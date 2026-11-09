"""Retained-parent adoption, request gates and conditional reset safety."""
from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError

import demos.common.runtime as ui
import demos.kvcr.demo as base
import demos.kvcr.guard as guard
import demos.kvcr.prepared as prepared
from testlib import Run


def arguments(path, **changes):
    result = dict(run=Path(path), action='run', rehearsal=True, preview=False, auto=True, plain=True,
                  detach=False, port=18007, timeout=60, placement=None, source_bundle=None)
    result.update(changes)
    return SimpleNamespace(**result)


def pod(role, uid, namespace, node):
    name = 'demo-kvcr-0-' + ('frontend' if role == 'frontend' else 'engine-' + role) + '-' + uid
    labels = {'workshop-kvcr-guard': 'true', 'feature-test-run': namespace,
              'workshop-role': 'frontend' if role == 'frontend' else 'worker'}
    if role != 'frontend': labels['kvcr-peer'] = role
    names = ['main'] if role == 'frontend' else ['main', 'kvcr-services']
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace, 'uid': uid,
             'labels': labels, 'ownerReferences': [{'kind': 'PodClique', 'name': role + '-clique', 'uid': role + '-clique-uid', 'controller': True}]},
            'spec': {'nodeName': node, 'nodeSelector': {'kubernetes.io/hostname': node}, 'terminationGracePeriodSeconds': 45,
                     'volumes': [{'name': 'model', 'persistentVolumeClaim': {'claimName': 'feature-cache'}},
                                 {'name': 'kube-api-access-old', 'projected': {}}],
                     'containers': [{'name': n, 'image': 'runtime@sha256:locked', 'command': ['python3', '/frozen/runtime.py'],
                                     'resources': {'requests': {'cpu': '1'}},
                                     'volumeMounts': [{'name': 'model', 'mountPath': '/model-cache'},
                                                      {'name': 'kube-api-access-old', 'mountPath': '/var/run/secrets/kubernetes.io/serviceaccount'}]} for n in names]},
            'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                       'containerStatuses': [{'name': n, 'ready': True, 'containerID': uid + '-' + n,
                                              'imageID': 'runtime@sha256:locked', 'restartCount': 0,
                                              'state': {'running': {'startedAt': '2026-11-05T20:00:00Z'}}} for n in names]}}


def replacement(original, uid):
    value = copy.deepcopy(original)
    value['metadata']['name'] += '-replacement'
    value['metadata']['uid'] = uid
    for c in value['status']['containerStatuses']: c['containerID'] = uid + '-' + c['name']
    value['spec']['volumes'][1]['name'] = 'kube-api-access-new'
    for c in value['spec']['containers']: c['volumeMounts'][1]['name'] = 'kube-api-access-new'
    return value


def card(host, *, full):
    def checked(name): return {'path': 'http://' + host + ':9090/metadata/' + name, 'checksum': 'blake3:' + name, 'size': 10}
    return {'display_name': 'model', 'source_path': 'model', 'context_length': 8192, 'kv_cache_block_size': 4224,
            'model_info': {'hf_config_json': checked('config.json')}, 'tokenizer': {'hf_tokenizer_json': checked('tokenizer.json')},
            'extra_files': [checked('core.py')] + ([checked('bias.md')] if full else []),
            'runtime_config': {'context_length': 8192}, 'worker_type': 'aggregated', 'needs': []}


def metadata(pods, cards, ids):
    return {'items': [{'metadata': {'name': pods[r]['metadata']['name'], 'uid': 'metadata-' + pods[r]['metadata']['uid'],
                     'ownerReferences': [{'kind': 'Pod', 'uid': pods[r]['metadata']['uid']}]},
                      'spec': {'data': {'endpoints': {'endpoint': {'component': 'backend', 'endpoint': 'generate', 'instance_id': ids[r]}},
                                        'model_cards': {'model': {'instance_id': ids[r], 'card_json': cards[r]}}}}} for r in ('a', 'b')]}


def readiness(namespace, count=2):
    return {'status_code': 200, 'body': {'ready': True, 'namespaces': {
        namespace: {'ready': True, 'worker_types': {'aggregated': {'workers': count, 'needs': []}}}}}}


class Fixture:
    """Explicitly synthetic local artifacts; none are cluster evidence."""
    def __init__(self, root):
        self.root = Path(root)
        self.parent, self.capture, self.assets, self.reset = [self.root / n for n in ('parent', 'failed-capture', 'assets', 'reset')]
        d = base.KVCRDemo(arguments(self.parent))
        self.ns = d.data['namespace']
        self.model = ui.read_json(ui.MODEL_LOCK)
        self.capture.mkdir(); (self.capture / 'failed-main.txt').write_text('SYNTHETIC FAILED SOURCE 400\n')
        self.assets.mkdir(); self.lease = self.root / 'parent-lease'; self.lease.mkdir()
        ui.write_json(self.lease / 'owner.json', {'agent': base.OWNER, 'run': str(self.parent)})
        # Retained parents predate the speedup profile; they ran the two-request walkthrough.
        d.data.update(kvcr_profile=base.LEGACY_PROFILE, fixture_functions=base.FIXTURE_FUNCTIONS,
                      rehearsal=False, prepared=True, lease=str(self.lease),
                      ready_observed_at='2026-11-05T20:00:00+00:00', source_request_started_at='2026-11-05T20:01:00+00:00')
        d.save(); ui.write_json(self.parent / 'model-lock.json', self.model)
        (self.parent / 'source').mkdir(); ui.write_json(self.parent / 'source/response.json', {'status': 400})
        self.geometry = {r: {'effective_page_tokens': 4224, 'context_limit_tokens': 8192} for r in ('a', 'b')}
        ui.write_json(self.parent / 'prompt-preflight.json', {'geometry_by_worker': self.geometry})
        placement = d.data['placement']
        self.pods = {r: pod(r, r + '-old', self.ns, placement['b' if r == 'b' else 'a']['node']) for r in ('a', 'b', 'frontend')}
        ui.write_json(self.parent / 'ready-pods.json', {'items': list(self.pods.values())})
        self.graph = {'kind': 'DynamoGraphDeployment', 'metadata': {'name': base.GRAPH, 'namespace': self.ns, 'uid': 'graph-uid'},
                      'spec': {'components': [{'name': r, 'replicas': 1} for r in ('a', 'b', 'frontend')]}}
        self.claims = {r: {'metadata': {'name': r + '-claim', 'uid': r + '-claim-old',
                                     'ownerReferences': [{'kind': 'Pod', 'uid': self.pods[r]['metadata']['uid']}]},
                           'status': {'allocation': {'devices': {'results': [
                               {'pool': placement[r]['node'], 'device': r + '-' + str(i)} for i in range(2)]}}}} for r in ('a', 'b')}
        self.cards, self.ids = {'a': card('1.1.1.1', full=True), 'b': card('2.2.2.2', full=False)}, {'a': '808', 'b': '909'}
        ui.write_json(self.parent / 'worker-ids.json', self.ids)
        self.native = {'status': 'passed', 'runtime_version': '1.7.0.dev20261103', 'cards': {
            'a': {'mdcsum': 'a' * 64}, 'b': {'mdcsum': 'b' * 64}}}
        names = ['config.json', 'tokenizer.json', 'core.py', 'bias.md', 'README.md']
        self.inventory = {n: {'bytes': 10, 'sha256': 'c' * 64} for n in names}
        self.dyn_ns = self.ns + '-guard'
        for r, p in self.pods.items(): ui.write_json(self.assets / ('before-' + r + '-pod.json'), p)
        ui.write_json(self.assets / 'before-dgd.json', self.graph)
        ui.write_json(self.assets / 'before-claims.json', {'items': list(self.claims.values())})
        ui.write_json(self.assets / 'current-metadata.json', metadata(self.pods, self.cards, self.ids))
        ui.write_json(self.assets / 'native-mdcsum.json', self.native)
        for r in ('a', 'b'): ui.write_json(self.assets / (r + '-cached-assets.json'), {'status': 'passed', 'nonweight_files': self.inventory})
        ui.write_json(self.assets / 'terminal.json', {'status': 'read_only_diagnostic_completed', 'current_cached_assets_match': True,
            'advertised_mdcsums_match': False, 'original_parent_and_capture_unchanged': True, 'workers_and_DGD_unchanged': True,
            'frontend_status': 200, 'frontend_admitted_aggregated_counts': {self.dyn_ns: 1},
            'current_asset_count': {'a': len(names), 'b': len(names)}, 'advertised_mdcsum': self.native['cards']})
        self.plan = prepared.plan_refresh(self.parent, self.capture, self.assets, self.reset)

    def repair(self):
        current = {'a': copy.deepcopy(self.pods['a']), 'b': replacement(self.pods['b'], 'b-new'),
                   'frontend': replacement(self.pods['frontend'], 'frontend-new')}
        cards = {'a': copy.deepcopy(self.cards['a']), 'b': card('2.2.2.2', full=True)}
        native = copy.deepcopy(self.native); native['cards']['b']['mdcsum'] = 'a' * 64
        self.selected = {'status': 'passed', 'completed_at': '2026-11-05T21:00:00+00:00', 'pods': current,
            'pod_signatures': {r: prepared.signature(p) for r, p in current.items()}, 'graph': self.graph,
            'cards': cards, 'native_checksums': native, 'worker_ids': {'a': '808', 'b': '910'},
            'geometry': self.geometry, 'frontend_readiness': readiness(self.dyn_ns),
            'replace_b': True, 'replace_frontend': True, 'two_workers_admitted': True}
        folder = self.reset / 'after-refresh'; folder.mkdir()
        ui.write_json(folder / 'snapshot.json', self.selected)
        self.proof = {'schema': 1, 'status': 'passed', 'kind': 'kvcr-supported-refresh-proof-v1',
            'plan': str(self.reset / 'plan.json'), 'plan_sha256': ui.digest(self.reset / 'plan.json'),
            'qualified_snapshot': str(folder / 'snapshot.json'), 'qualified_snapshot_sha256': ui.digest(folder / 'snapshot.json'),
            'source_retained': True, 'replaced_roles': ['b', 'frontend'], 'two_workers_admitted': True,
            'generation_requests': 0, 'metadata_patches': 0, 'registry_changes': 0, 'checksum_bypassed': False,
            'evidence_sha256': prepared.tree_hashes(self.reset)}
        ui.write_json(self.reset / 'repair.json', self.proof)
        return self.reset / 'repair.json'

    def snapshot_run(self):
        """Drive the actual snapshot gate with a fake read-only cluster transport."""
        current = self.selected['pods']
        claims = copy.deepcopy(self.claims)
        claims['b']['metadata'].update(name='b-claim-new', uid='b-claim-new')
        claims['b']['metadata']['ownerReferences'][0]['uid'] = current['b']['metadata']['uid']
        slices = {'items': [{'spec': {'driver': 'gpu.nvidia.com', 'pool': {'name': self.plan['placement'][r]['node']},
                    'devices': [{'name': r + '-' + str(i), 'attributes': {'uuid': {'string': gpu}}}
                                for i, gpu in enumerate(self.plan['placement'][r]['gpu_uuids'])]}} for r in ('a', 'b')]}
        objects = {'pods': {'items': list(current.values())}, 'dgd': self.graph,
                   'resourceclaims': {'items': list(claims.values())}, 'resourceslices': slices,
                   'dynamoworkermetadatas': metadata(current, self.selected['cards'], self.selected['worker_ids'])}
        queries = []
        def get(*args):
            queries.append(args)
            return copy.deepcopy(objects[args[1]])
        run = SimpleNamespace(path=self.reset, ns=self.ns, get=get,
                              k=lambda *a, **k: SimpleNamespace(stdout='Using max model len 8192\nSetting attention block size to 4224 tokens\n'))
        return run, objects, queries


class PreparedKVCRTests(unittest.TestCase):
    def test_native_probe_uses_internal_core_export_and_never_synthesizes_a_checksum(self):
        dynamo = ModuleType('dynamo'); dynamo.__path__ = []
        core = ModuleType('dynamo._core')
        core.__file__ = '/tmp/kvcr-guard-candidate/installed/dynamo/_core.abi3.so'
        payload = {'a': {'test_role': 'a'}, 'b': {'test_role': 'b'}}
        seen = []
        class NativeCard:
            @staticmethod
            def from_json_str(serialized):
                record = json.loads(serialized); seen.append(record)
                return SimpleNamespace(local_dir=lambda: '/cache/by-slug/model/' + record['test_role'] * 64)
        core.ModelDeploymentCard = NativeCard
        with mock.patch.dict(sys.modules, {'dynamo': dynamo, 'dynamo._core': core}), \
                mock.patch('importlib.metadata.version', return_value='1.7.0.dev20261103'), \
                mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(prepared.NATIVE_CHECKSUM_PROGRAM, 'native-mdc-probe', 'exec'), {})
        self.assertEqual(seen, list(payload.values()))
        self.assertEqual(json.loads(output.getvalue())['cards']['b']['mdcsum'], 'b' * 64)
        del core.ModelDeploymentCard
        with mock.patch.dict(sys.modules, {'dynamo': dynamo, 'dynamo._core': core}), self.assertRaises(AttributeError):
            exec(compile(prepared.NATIVE_CHECKSUM_PROGRAM, 'native-mdc-probe', 'exec'), {})

    def test_binding_creates_fresh_requests_without_touching_parent_capture_or_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair()
            original = prepared.tree_hashes(f.parent), prepared.tree_hashes(f.capture), ui.digest(f.lease / 'owner.json')
            child = Path(folder) / 'child'
            prepared.bind(repair, child)
            d = prepared.PreparedKVCRDemo(arguments(child, rehearsal=False))
            self.assertEqual((prepared.tree_hashes(f.parent), prepared.tree_hashes(f.capture), ui.digest(f.lease / 'owner.json')), original)
            self.assertEqual(ui.read_json(f.lease / 'owner.json')['run'], str(f.parent))
            self.assertEqual(d.run.ns, f.ns)
            self.assertNotEqual((child / 'shared-context.txt').read_text(), (f.parent / 'shared-context.txt').read_text())
            self.assertFalse((child / 'source').exists()); self.assertFalse((child / 'target').exists())
            self.assertEqual(ui.read_json(child / 'worker-ids.json'), {'a': '808', 'b': '910'})
            self.assertIsNone(ui.read_json(child / 'timing.json')['apply_to_observed_ready_seconds'])

    def test_child_rejects_parent_lease_reassignment_and_original_capture_mutation(self):
        for what in ('lease', 'capture', 'parent'):
            with self.subTest(what=what), tempfile.TemporaryDirectory() as folder:
                f = Fixture(folder); repair = f.repair(); child = Path(folder) / 'child'; prepared.bind(repair, child)
                d = prepared.PreparedKVCRDemo(arguments(child, rehearsal=False))
                if what == 'lease': ui.write_json(f.lease / 'owner.json', {'agent': base.OWNER, 'run': str(child)})
                elif what == 'capture': (f.capture / 'failed-main.txt').write_text('replaced failure')
                else: (f.parent / 'source/response.json').write_text('{"status": 200}')
                with mock.patch.object(Run, 'k') as live, self.assertRaises(ValueError): d.require_lease()
                live.assert_not_called()

    def test_child_never_deploys_prepares_gpus_or_cleans_owning_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair(); child = Path(folder) / 'child'; prepared.bind(repair, child)
            d = prepared.PreparedKVCRDemo(arguments(child, rehearsal=False))
            with mock.patch.object(Run, 'k') as live:
                for method in (d.deploy, d.wait, d.cpu_gate, d.native_gate, d.cleanup):
                    with self.assertRaises(RuntimeError): method()
                with self.assertRaisesRegex(ValueError, 'cannot clean'):
                    prepared.PreparedKVCRDemo(arguments(child, rehearsal=False, action='cleanup'))
                live.assert_not_called()

    def test_child_requires_its_fresh_preflight_before_visible_walkthrough(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair(); child = Path(folder) / 'child'; prepared.bind(repair, child)
            d = prepared.PreparedKVCRDemo(arguments(child, rehearsal=False))
            output = io.StringIO()
            with (mock.patch.object(Run, 'k') as live,
                  mock.patch.object(d, 'prepare') as preparation,
                  mock.patch.object(d, 'run_steps') as steps,
                  contextlib.redirect_stdout(output),
                  self.assertRaisesRegex(RuntimeError, '-m demos kvcr-prepared prime --run')):
                d.guided()
            live.assert_not_called()
            preparation.assert_not_called()
            steps.assert_not_called()
            self.assertNotIn('Dynamo workshop', output.getvalue())

    def test_missing_admission_gate_prevents_both_source_and_receiver_http(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair(); child = Path(folder) / 'child'; prepared.bind(repair, child)
            d = prepared.PreparedKVCRDemo(arguments(child, rehearsal=False))
            with mock.patch.object(prepared, 'snapshot', side_effect=ValueError('only one admitted worker')), \
                    mock.patch.object(guard, 'response') as http, mock.patch.object(d, 'endpoint') as endpoint:
                for method in (d.source, d.target):
                    with self.assertRaisesRegex(ValueError, 'only one admitted'): method()
                http.assert_not_called(); endpoint.assert_not_called()
            self.assertFalse((child / 'source').exists()); self.assertFalse((child / 'target').exists())

    def test_only_declared_b_and_frontend_uid_changes_are_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); f.repair()
            prepared.check_pod_transition(f.pods, f.selected['pods'], replace_b=True, replace_frontend=True)
            for role in ('a', 'b', 'frontend'):
                bad = copy.deepcopy(f.selected['pods'])
                if role == 'a': bad['a'] = replacement(bad['a'], 'a-unapproved')
                else: bad[role] = copy.deepcopy(f.pods[role])
                with self.subTest(role=role), self.assertRaises(ValueError):
                    prepared.check_pod_transition(f.pods, bad, replace_b=True, replace_frontend=True)
            bad = copy.deepcopy(f.selected['pods']); bad['b']['spec']['containers'][0]['command'].append('--changed-runtime')
            with self.assertRaisesRegex(ValueError, 'execution spec changed'):
                prepared.check_pod_transition(f.pods, bad, replace_b=True, replace_frontend=True)

    def test_readiness_requires_exactly_two_admitted_aggregated_workers(self):
        prepared.readiness_two_workers(readiness('ns'), 'ns')
        cases = [readiness('ns', n) for n in (0, 1, 3, True)]
        cases += [readiness('foreign'), {'status_code': 503, 'body': readiness('ns')['body']}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError): prepared.readiness_two_workers(value, 'ns')

    def test_native_checksums_cannot_be_substituted_with_equal_looking_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); f.repair(); native = f.selected['native_checksums']; cards = f.selected['cards']
            prepared.check_native_cards(cards, native, 'a' * 64, matching=True)
            reordered = copy.deepcopy(cards); reordered['b']['extra_files'].reverse()
            prepared.check_native_cards(reordered, native, 'a' * 64, matching=True)
            wrong = copy.deepcopy(native); wrong['cards']['b']['mdcsum'] = 'b' * 64
            with self.assertRaisesRegex(ValueError, 'matching native'): prepared.check_native_cards(cards, wrong, 'a' * 64, matching=True)
            changed = copy.deepcopy(cards); changed['b']['extra_files'].pop()
            with self.assertRaisesRegex(ValueError, 'matching native'): prepared.check_native_cards(changed, native, 'a' * 64, matching=True)

    def test_unsettled_assets_stop_refresh_before_any_api_or_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            terminal = ui.read_json(f.assets / 'terminal.json'); terminal['current_cached_assets_match'] = False
            ui.write_json(f.assets / 'terminal.json', terminal)
            with mock.patch.object(Run, 'k') as live, mock.patch.object(prepared, 'delete_pod_once') as delete, \
                    self.assertRaises(ValueError): prepared.refresh(f.reset)
            live.assert_not_called(); delete.assert_not_called()
            self.assertFalse((f.reset / 'started.json').exists())

    def test_refresh_plan_rejects_assets_from_different_parent_pods(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            wrong = copy.deepcopy(f.pods['b']); wrong['metadata']['uid'] = 'another-run-b'
            ui.write_json(f.assets / 'before-b-pod.json', wrong)
            with mock.patch.object(Run, 'k') as live, self.assertRaisesRegex(ValueError, 'exact original parent Pods'):
                prepared.plan_refresh(f.parent, f.capture, f.assets, Path(folder) / 'new-reset')
            live.assert_not_called()

    def test_uid_delete_uses_precondition_and_a_conflict_is_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            run = SimpleNamespace(path=f.reset, ns=f.ns, get=lambda *args: copy.deepcopy(f.pods['b']))
            calls = []
            def rejected(request, timeout):
                calls.append(request)
                self.assertEqual(request.method, 'DELETE')
                self.assertEqual(json.loads(request.data)['preconditions'], {'uid': 'b-old'})
                self.assertEqual(json.loads(request.data)['gracePeriodSeconds'], 45)
                raise HTTPError(request.full_url, 409, 'UID precondition failed', {}, io.BytesIO(b'conflict'))
            with mock.patch.object(prepared, 'urlopen', side_effect=rejected), self.assertRaises(HTTPError):
                prepared.delete_pod_once(run, f.plan, 'b', f.pods['b'], 'http://127.0.0.1:12345')
            self.assertEqual(len(calls), 1)
            self.assertFalse(ui.read_json(f.reset / 'delete-b-failure.json')['retried'])
            with mock.patch.object(prepared, 'urlopen') as live, self.assertRaises(FileExistsError):
                prepared.delete_pod_once(run, f.plan, 'b', f.pods['b'], 'http://127.0.0.1:12345')
            live.assert_not_called()

    def test_stale_uid_or_source_delete_is_rejected_before_delete_http(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            run = SimpleNamespace(path=f.reset, ns=f.ns, get=lambda *args: replacement(f.pods['b'], 'b-raced'))
            with mock.patch.object(prepared, 'urlopen') as live:
                with self.assertRaisesRegex(ValueError, 'immediately before'):
                    prepared.delete_pod_once(run, f.plan, 'b', f.pods['b'], 'http://127.0.0.1:12345')
                with self.assertRaisesRegex(ValueError, 'Only B'):
                    prepared.delete_pod_once(run, f.plan, 'a', f.pods['a'], 'http://127.0.0.1:12345')
                live.assert_not_called()

    def test_forged_repair_modes_and_tampered_repair_evidence_are_rejected(self):
        for field, value in [('source_retained', False), ('replaced_roles', ['a', 'b', 'frontend']),
                             ('metadata_patches', 1), ('checksum_bypassed', True), ('two_workers_admitted', False)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                f = Fixture(folder); repair = f.repair(); proof = ui.read_json(repair); proof[field] = value; ui.write_json(repair, proof)
                with self.assertRaises(ValueError): prepared.bind(repair, Path(folder) / 'child')
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair(); (f.reset / 'after-refresh/snapshot.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Repair evidence changed'):
                prepared.bind(repair, Path(folder) / 'child')

    def test_evidence_child_cannot_live_inside_parent_capture_or_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); repair = f.repair()
            for output in (f.parent / 'new-child', f.capture / 'new-child', f.reset / 'new-child'):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'inside protected'):
                    prepared.bind(repair, output)
                self.assertFalse(output.exists())

    def test_current_worker_metadata_requires_matching_pod_and_endpoint_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            record = metadata(f.pods, f.cards, f.ids)
            self.assertEqual(prepared.worker_cards(record, f.pods)[1], f.ids)
            record['items'][0]['metadata']['ownerReferences'][0]['uid'] = 'old-deleted-pod'
            with self.assertRaisesRegex(ValueError, 'another Pod UID'): prepared.worker_cards(record, f.pods)

    def test_actual_snapshot_gate_checks_admission_native_cards_and_physical_claims(self):
        for mutation in ('none', 'one_worker', 'native_mismatch', 'stale_metadata', 'wrong_gpu', 'old_claim'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                f = Fixture(folder); f.repair(); run, objects, queries = f.snapshot_run()
                native, ready = copy.deepcopy(f.selected['native_checksums']), readiness(f.dyn_ns)
                if mutation == 'one_worker': ready = readiness(f.dyn_ns, 1)
                elif mutation == 'native_mismatch': native['cards']['b']['mdcsum'] = 'b' * 64
                elif mutation == 'stale_metadata': objects['dynamoworkermetadatas']['items'][1]['metadata']['ownerReferences'][0]['uid'] = 'deleted-b'
                elif mutation == 'wrong_gpu': objects['resourceslices']['items'][1]['spec']['devices'][0]['attributes']['uuid']['string'] = 'GPU-unreserved'
                elif mutation == 'old_claim': objects['resourceclaims']['items'].append(f.claims['b'])
                def cpu(_run, _pod, program, _payload, **kwargs):
                    return native if program == prepared.NATIVE_CHECKSUM_PROGRAM else ready
                with mock.patch.object(prepared, 'owner_chain', return_value=[f.graph]), mock.patch.object(prepared, 'exec_json', side_effect=cpu):
                    if mutation == 'none':
                        result = prepared.snapshot(run, f.plan, 'admission-test', replace_b=True, replace_frontend=True,
                                                   two_workers=True, bound=f.selected)
                        self.assertTrue(result['two_workers_admitted'])
                        self.assertEqual(result['worker_ids'], {'a': '808', 'b': '910'})
                    else:
                        with self.assertRaises(ValueError):
                            prepared.snapshot(run, f.plan, 'admission-test', replace_b=True, replace_frontend=True,
                                              two_workers=True, bound=f.selected)
                self.assertTrue(all(q[0] == 'get' for q in queries))

    def test_conditional_refresh_deletes_only_b_then_frontend_and_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder); f.repair()
            # This synthetic snapshot is test input, not a recorded successful refresh.
            (f.reset / 'repair.json').unlink()
            old = prepared.tree_hashes(f.parent), prepared.tree_hashes(f.capture), ui.digest(f.lease / 'owner.json')
            before = {'pods': f.pods}
            after_b = {'pods': {**f.pods, 'b': f.selected['pods']['b']}}
            with mock.patch.object(prepared, 'snapshot', side_effect=[before, after_b, f.selected]), \
                    mock.patch.object(prepared, 'exec_json', return_value={'status': 'passed', 'nonweight_files': f.inventory}), \
                    mock.patch.object(prepared, 'ApiProxy') as proxy, mock.patch.object(prepared, 'delete_pod_once') as deletion, \
                    mock.patch.object(prepared, 'wait_replacement'):
                proxy.return_value.__enter__.return_value = 'http://127.0.0.1:test'
                proof = prepared.refresh(f.reset, timeout=2)
            self.assertEqual([c.args[2] for c in deletion.call_args_list], ['b', 'frontend'])
            self.assertEqual(proof['generation_requests'], 0)
            self.assertFalse(proof['checksum_bypassed'])
            self.assertEqual((prepared.tree_hashes(f.parent), prepared.tree_hashes(f.capture), ui.digest(f.lease / 'owner.json')), old)
            with mock.patch.object(prepared, 'delete_pod_once') as deletion, self.assertRaises(FileExistsError):
                prepared.refresh(f.reset, timeout=2)
            deletion.assert_not_called()

    def test_failed_b_registration_stops_before_frontend_delete_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            with mock.patch.object(prepared, 'snapshot', side_effect=[{'pods': f.pods}, ValueError('new B card differs')]), \
                    mock.patch.object(prepared, 'exec_json', return_value={'status': 'passed', 'nonweight_files': f.inventory}), \
                    mock.patch.object(prepared, 'ApiProxy') as proxy, mock.patch.object(prepared, 'delete_pod_once') as deletion, \
                    mock.patch.object(prepared, 'wait_replacement'), self.assertRaisesRegex(ValueError, 'new B card differs'):
                proxy.return_value.__enter__.return_value = 'http://127.0.0.1:test'
                prepared.refresh(f.reset, timeout=2)
            self.assertEqual([c.args[2] for c in deletion.call_args_list], ['b'])
            failures = list(f.reset.glob('failure-*.json'))
            self.assertEqual(len(failures), 1)
            self.assertIn('new B card differs', ui.read_json(failures[0])['error'])
            self.assertFalse((f.reset / 'repair.json').exists())


if __name__ == '__main__':
    unittest.main()
