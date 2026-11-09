"""Owned capture lifetime changes must preserve every identity and engine spec."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import demos.snapshot.capture_deadline as subject


def fixture(deadline=3600):
    ns = 'dynamo-ft-test'
    state = {'namespace': ns, 'snapshot_dgd_uid': 'dgd-uid'}
    def meta(name, uid):
        return {'name': name, 'namespace': ns, 'uid': uid, 'resourceVersion': '1'}
    labels = {'feature-test-run': ns, 'app.kubernetes.io/managed-by': subject.OWNER,
        'nvidia.com/dynamo-component': subject.COMPONENT, 'nvidia.com/dynamo-graph-deployment-name': subject.GRAPH}
    graph = {'metadata': {**meta(subject.GRAPH, 'dgd-uid'), 'labels': labels},
        'status': {'checkpoints': {subject.COMPONENT: {'checkpointName': 'capture'}}}}
    snapshot = {'metadata': {**meta('capture', 'snapshot-uid'), 'labels': copy.deepcopy(labels),
        'annotations': {'nvidia.com/dynamo-checkpoint-owner-uid': 'dgd-uid'}},
        'spec': {'activeDeadlineSeconds': deadline, 'podTemplate': {'spec': {}}},
        'status': {'sourceJobUID': 'job-uid'}}
    source_labels = {**labels, 'nvidia.com/snapshot-job': 'capture', 'nvidia.com/snapshot-job-uid': 'snapshot-uid'}
    source = {'metadata': {**meta('capture', 'job-uid'), 'labels': source_labels,
        'ownerReferences': [{'controller': True, 'kind': 'SnapshotJob', 'name': 'capture', 'uid': 'snapshot-uid'}]},
        'spec': {'activeDeadlineSeconds': deadline, 'template': {'spec': {'containers': [{'name': 'main', 'image': 'same-image'}]}}}}
    pod = {'metadata': {**meta('capture-pod', 'pod-uid'), 'labels': {**source_labels, 'batch.kubernetes.io/controller-uid': 'job-uid'},
        'ownerReferences': [{'controller': True, 'kind': 'Job', 'name': 'capture', 'uid': 'job-uid'}]},
        'spec': {'containers': [{'name': 'main', 'image': 'same-image'}]}, 'status': {'phase': 'Pending'}}
    return state, [graph, snapshot, source, [pod]]


class FakeClient:
    def __init__(self, bundle):
        self.current = copy.deepcopy(bundle)
        self.calls = []

    def bundle(self, state):
        return copy.deepcopy(self.current)

    def patch(self, kind, before, patch, *, dry_run):
        self.calls.append((kind, copy.deepcopy(patch), dry_run))
        index = 1 if kind == 'snapshotjob' else 2
        actual = self.current[index]
        for operation in patch:
            if operation['op'] == 'test':
                value = actual
                for part in operation['path'].strip('/').split('/'):
                    value = value[part]
                if value != operation['value']:
                    raise RuntimeError('resourceVersion/UID JSON test conflict')
        result = copy.deepcopy(actual)
        result['spec']['activeDeadlineSeconds'] = 7200
        if not dry_run:
            result['metadata']['resourceVersion'] = str(int(result['metadata']['resourceVersion']) + 1)
            self.current[index] = result
        return result


class Ownership(unittest.TestCase):
    def test_exact_owned_chain_accepts_pending_source_pod(self):
        state, bundle = fixture()
        identity = subject.validate(state, *bundle)
        self.assertEqual(identity['source_pod_uids'], ['pod-uid'])

    def test_foreign_owner_or_reused_uid_rejected_before_any_patch(self):
        for index, change in [(0, lambda x: x['metadata'].update(uid='other')),
                              (1, lambda x: x['metadata']['annotations'].update({'nvidia.com/dynamo-checkpoint-owner-uid': 'other'})),
                              (2, lambda x: x['metadata']['ownerReferences'][0].update(uid='other')),
                              (2, lambda x: x['metadata'].update(uid='other'))]:
            state, bundle = fixture();change(bundle[index]);client = FakeClient(bundle)
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
                subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
            self.assertFalse(client.calls)

    def test_terminal_capture_or_source_job_refused(self):
        for index in (1, 2):
            for condition in ('Failed', 'FailureTarget', 'Complete', 'Completed'):
                state, bundle = fixture()
                bundle[index].setdefault('status', {})['conditions'] = [{'type': condition, 'status': 'True'}]
                with self.assertRaisesRegex(ValueError, 'terminal'):
                    subject.validate(state, *bundle)

    def test_shorter_source_pod_or_template_deadline_reported_without_patch(self):
        state, bundle = fixture()
        bundle[3][0]['spec']['activeDeadlineSeconds'] = 3600
        client = FakeClient(bundle)
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, 'shorter deadline'):
            subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
        self.assertFalse(client.calls)
        state, bundle = fixture();bundle[2]['spec']['template']['spec']['activeDeadlineSeconds'] = 3600
        with self.assertRaisesRegex(ValueError, 'shorter deadline'):
            subject.validate(state, *bundle)

    def test_missing_source_pod_waits_and_conflicting_pod_owner_refuses(self):
        state, bundle = fixture();bundle[3] = []
        with self.assertRaises(subject.NotCreatedYet):
            subject.validate(state, *bundle)
        state, bundle = fixture();bundle[3][0]['metadata']['ownerReferences'][0]['uid'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'Source Pod'):
            subject.validate(state, *bundle)


class GuardedWrites(unittest.TestCase):
    def test_both_jobs_extend_only_lifetime_with_uid_rv_tests_and_server_dryrun(self):
        state, bundle = fixture();client = FakeClient(bundle)
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'require_lease'):
            policy = subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
            self.assertEqual(policy['status'], 'passed')
            self.assertEqual([(kind, dry) for kind, _, dry in client.calls],
                             [('snapshotjob', True), ('snapshotjob', False), ('job', True), ('job', False)])
            for _, operations, _ in client.calls:
                self.assertEqual([x['path'] for x in operations[:3]],
                                 ['/metadata/uid', '/metadata/resourceVersion', '/spec/activeDeadlineSeconds'])
                self.assertEqual(operations[-1], {'op': 'replace', 'path': '/spec/activeDeadlineSeconds', 'value': 7200})
            for change in policy['changes']:
                self.assertEqual(change['before_deadline'], 3600)
                self.assertEqual(change['after_deadline'], 7200)
                self.assertTrue(change['before_sha256']);self.assertTrue(change['after_sha256'])
            self.assertTrue((Path(temp) / 'capture-deadline-before.json').exists())
            self.assertTrue((Path(temp) / 'capture-deadline-after.json').exists())

    def test_already_7200_is_idempotent_without_any_patch(self):
        state, bundle = fixture(7200);client = FakeClient(bundle)
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'require_lease'):
            result = subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(client.calls)
        self.assertTrue(all(x['status'] == 'already_7200' for x in result['changes']))

    def test_dryrun_admission_rejection_prevents_real_patch(self):
        state, bundle = fixture();client = FakeClient(bundle)
        def reject(kind, before, operations, *, dry_run):
            self.assertTrue(dry_run)
            raise RuntimeError('Admission rejected')
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'require_lease'), \
                patch.object(client, 'patch', side_effect=reject), self.assertRaisesRegex(RuntimeError, 'Admission'):
            subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
        self.assertEqual(client.current[1]['spec']['activeDeadlineSeconds'], 3600)

    def test_resource_version_conflict_has_no_automatic_retry_or_second_job_patch(self):
        state, bundle = fixture();client = FakeClient(bundle)
        original = client.patch
        def conflict(kind, before, operations, *, dry_run):
            if dry_run:
                result = original(kind, before, operations, dry_run=True)
                client.current[1]['metadata']['resourceVersion'] = '2'
                return result
            return original(kind, before, operations, dry_run=False)
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'require_lease'), \
                patch.object(client, 'patch', side_effect=conflict), self.assertRaisesRegex(RuntimeError, 'test conflict'):
            subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
        self.assertEqual(len(client.calls), 2)
        self.assertFalse(any(kind == 'job' for kind, _, _ in client.calls))

    def test_server_cannot_change_engine_settings(self):
        state, bundle = fixture()
        after = copy.deepcopy(bundle[2]);after['spec']['activeDeadlineSeconds'] = 7200
        after['spec']['template']['spec']['containers'][0]['image'] = 'another-image'
        with self.assertRaisesRegex(ValueError, 'beyond'):
            subject.confirm_only_deadline(bundle[2], after)

    def test_lease_loss_prevents_all_patch_commands(self):
        state, bundle = fixture();client = FakeClient(bundle)
        with tempfile.TemporaryDirectory() as temp, patch.object(subject, 'require_lease', side_effect=ValueError('foreign reservation')), \
                self.assertRaisesRegex(ValueError, 'foreign reservation'):
            subject.apply_policy(Path(temp), state, bundle, client, {'changes': []})
        self.assertFalse(client.calls)

    def test_watch_records_terminal_refusal_as_failed_without_mutation(self):
        state, bundle = fixture();bundle[2]['status'] = {'conditions': [{'type': 'Failed', 'status': 'True'}]}
        client = FakeClient(bundle)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp);(path / 'state.json').write_text(json.dumps(state))
            with patch.object(subject, 'Client', return_value=client), patch.object(subject, 'require_lease'), \
                    self.assertRaisesRegex(ValueError, 'terminal'):
                subject.watch(path)
            policy = json.loads((path / subject.POLICY).read_text())
            self.assertEqual(policy['status'], 'failed')
            self.assertIn('terminal', policy['error'])
            self.assertFalse(client.calls)

    def test_partial_first_patch_is_reported_if_source_identity_changes(self):
        state, bundle = fixture();client = FakeClient(bundle)
        original = client.bundle
        def changed(current_state):
            result = original(current_state)
            if client.calls:
                result[2]['metadata']['uid'] = 'reused-source-job'
            return result
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp);(path / 'state.json').write_text(json.dumps(state))
            with patch.object(subject, 'Client', return_value=client), patch.object(client, 'bundle', side_effect=changed), \
                    patch.object(subject, 'require_lease'), self.assertRaisesRegex(ValueError, 'ownership'):
                subject.watch(path)
            policy = json.loads((path / subject.POLICY).read_text())
            self.assertEqual(policy['status'], 'failed')
            self.assertEqual(len(policy['changes']), 1)
            self.assertEqual(policy['changes'][0]['status'], 'patched')
            self.assertEqual(client.current[1]['spec']['activeDeadlineSeconds'], 7200)
            self.assertEqual(client.current[2]['spec']['activeDeadlineSeconds'], 3600)
            self.assertFalse(any(kind == 'job' for kind, _, _ in client.calls))

    def test_source_disappearance_after_first_patch_never_retries_application(self):
        state, bundle = fixture();client = FakeClient(bundle)
        original = client.bundle
        observations = []
        def disappear(current_state):
            observations.append(True)
            if client.calls:
                raise subject.NotCreatedYet('Source identity disappeared after first patch')
            return original(current_state)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp);(path / 'state.json').write_text(json.dumps(state))
            with patch.object(subject, 'Client', return_value=client), patch.object(client, 'bundle', side_effect=disappear), \
                    patch.object(subject, 'require_lease'), self.assertRaises(subject.NotCreatedYet):
                subject.watch(path)
            policy = json.loads((path / subject.POLICY).read_text())
            self.assertEqual(policy['status'], 'failed')
            self.assertEqual(len(policy['changes']), 1)
            self.assertEqual(len(observations), 2)
            self.assertEqual(client.current[1]['spec']['activeDeadlineSeconds'], 7200)
            self.assertEqual(client.current[2]['spec']['activeDeadlineSeconds'], 3600)


if __name__ == '__main__':
    unittest.main()
