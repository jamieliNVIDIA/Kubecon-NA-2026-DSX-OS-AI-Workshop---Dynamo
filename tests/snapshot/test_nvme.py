"""Artifact, lease, and source-fence guards for DGD node-local Snapshot staging."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.snapshot.nvme as subject


SNAPSHOT_UID = '11111111-1111-4111-8111-111111111111'
CONTENT_UID = '22222222-2222-4222-8222-222222222222'
SOURCE_UID = '33333333-3333-4333-8333-333333333333'
AGENT_UID = '44444444-4444-4444-8444-444444444444'
GRAPH_UID = '55555555-5555-4555-8555-555555555555'
PENDING_UID = '66666666-6666-4666-8666-666666666666'


def objects(namespace):
    conditions = [{'type': 'Ready', 'status': 'True'}]
    snapshot = {'metadata': {'name': 'checkpoint-test', 'namespace': namespace, 'uid': SNAPSHOT_UID},
                'status': {'boundSnapshotContentName': 'content-test', 'conditions': conditions}}
    content = {'metadata': {'name': 'content-test', 'uid': CONTENT_UID},
               'spec': {'snapshotRef': {'name': 'checkpoint-test', 'namespace': namespace, 'uid': SNAPSHOT_UID},
                        'source': {'nodeName': subject.nvme.NODE,
                                   'podRef': {'name': 'source-pod', 'uid': SOURCE_UID, 'containers': ['main']}}},
               'status': {'conditions': conditions}}
    agent = {'metadata': {'name': 'dynamo-platform-snapshot-agent-test', 'uid': AGENT_UID},
             'spec': {'nodeName': subject.nvme.NODE, 'containers': [{'name': 'agent'}, {'name': 'pagebroker'}]},
             'status': {'phase': 'Running', 'conditions': conditions,
                        'containerStatuses': [{'name': name, 'ready': True, 'restartCount': 0}
                                              for name in ('agent', 'pagebroker')]}}
    source = {'metadata': {'name': 'source-pod', 'uid': SOURCE_UID, 'labels': {'feature-test-run': namespace}},
              'spec': {'nodeName': subject.nvme.NODE, 'resourceClaims': [{'name': 'gpu-main', 'resourceClaimName': 'source-gpus'}]},
              'status': {'phase': 'Running', 'containerStatuses': [
                  {'name': 'main', 'state': {'terminated': {'exitCode': 0}}},
                  {'name': 'capture-keepalive', 'state': {'running': {'startedAt': 'now'}}}]}}
    pending = {'metadata': {'name': 'worker-pending', 'uid': PENDING_UID,
                           'labels': {'nvidia.com/dynamo-component-type': 'worker'}},
               'status': {'phase': 'Pending'}}
    claims = [{'metadata': {'name': 'source-gpus'}, 'status': {
        'allocation': {'devices': {'results': [{'device': 'gpu-1'}, {'device': 'gpu-3'}]}},
        'reservedFor': [{'uid': SOURCE_UID}]}}, {'metadata': {'name': 'worker-gpus'}, 'status': {}}]
    graph = {'metadata': {'uid': GRAPH_UID, 'namespace': namespace},
             'status': {'checkpoints': {'VllmSnapshotWorker': {'checkpointName': 'checkpoint-test'}}}}
    return SimpleNamespace(snapshot=snapshot, content=content, agent=agent, source=source,
                           pending=pending, claims=claims, graph=graph)


class FakeRun:
    def __init__(self, path):
        self.path = Path(path)
        self.ns = 'dynamo-ft-nvme-test'
        self.state = {'run_id': 'nvme-test', 'namespace': self.ns, 'snapshot_dgd_node': subject.nvme.NODE,
                      'snapshot_dgd_uid': GRAPH_UID, 'checks': {}}
        self.objects = objects(self.ns)
        self.saves = 0

    def save(self):
        # Match the important Run.save behavior: every save invalidates nested
        # references retained by the caller, including the NVMe record dict.
        self.state = copy.deepcopy(self.state)
        self.saves += 1

    def result(self, feature, status, **details):
        self.state['checks'][feature] = {'status': status, **details}
        self.save()

    def get(self, *args):
        kind = args[1]
        if kind == 'podsnapshot':
            return copy.deepcopy(self.objects.snapshot)
        if kind == 'podsnapshotcontent':
            return copy.deepcopy(self.objects.content)
        if kind == 'dgd':
            return copy.deepcopy(self.objects.graph)
        if kind == 'pod':
            return copy.deepcopy(self.objects.source)
        if kind == 'resourceclaims':
            return {'items': copy.deepcopy(self.objects.claims)}
        if kind == 'pods':
            return {'items': copy.deepcopy([self.objects.source, self.objects.pending])}
        raise AssertionError(args)

    def k(self, *args, **kwargs):
        raise AssertionError('Unexpected cluster command')


class Guards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = FakeRun(self.temp.name)
        self.data = self.run.objects

    def identity(self):
        return subject.source_identity(self.run, self.data.snapshot, self.data.content)

    def test_binding_uuid_node_storage_and_readiness_refused_before_mutation(self):
        changes = [lambda s, c: c['spec']['snapshotRef'].update(uid=CONTENT_UID),
                   lambda s, c: c['metadata'].update(uid='../../unsafe'),
                   lambda s, c: c['spec']['source'].update(nodeName='another-node'),
                   lambda s, c: c['spec'].update(storage={}),
                   lambda s, c: c['spec']['source']['podRef'].update(containers=['main', 'helper']),
                   lambda s, c: s['status'].update(conditions=[]),
                   lambda s, c: s['metadata'].update(namespace='foreign'),
                   lambda s, c: s['status'].update(boundSnapshotContentName='different')]
        for change in changes:
            snapshot, content = copy.deepcopy(self.data.snapshot), copy.deepcopy(self.data.content)
            change(snapshot, content)
            with self.subTest(change=change), patch.object(subject, 'require_lease') as lease:
                with self.assertRaises((ValueError, AttributeError)):
                    subject.ensure(self.run, snapshot, content)
                lease.assert_not_called()

    def test_unsafe_run_identifier_refused_before_any_agent_operation(self):
        for identifier in ['../outside', 'unsafe;echo', 'has space', 'x' * 97]:
            self.run.state['run_id'] = identifier
            with self.assertRaisesRegex(ValueError, 'run identifier'):
                self.identity()

    def test_initial_capture_gate_accepts_pending_unallocated_serving_worker(self):
        subject.initial_capture_gate(self.run, self.identity())

    def test_initial_capture_gate_refuses_lost_helper_claim_or_foreign_graph(self):
        mutations = [lambda: self.data.source['status']['containerStatuses'][1].update(state={'terminated': {}}),
                     lambda: self.data.source['metadata'].update(uid=CONTENT_UID),
                     lambda: self.data.claims[0]['status'].update(reservedFor=[]),
                     lambda: self.data.claims[1]['status'].update(allocation={'devices': {}}),
                     lambda: self.data.pending['status'].update(phase='Running'),
                     lambda: self.data.graph['metadata'].update(uid=CONTENT_UID),
                     lambda: self.data.graph['status']['checkpoints']['VllmSnapshotWorker'].update(checkpointName='other')]
        for mutation in mutations:
            self.run.objects = objects(self.run.ns)
            self.data = self.run.objects
            mutation()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                subject.initial_capture_gate(self.run, self.identity())

    def test_foreign_lease_refused_before_mutating_agent(self):
        with patch.object(subject, 'require_lease', side_effect=RuntimeError('foreign lease')):
            with patch.object(subject, 'execute') as execute:
                with self.assertRaisesRegex(RuntimeError, 'foreign lease'):
                    subject.ensure(self.run, self.data.snapshot, self.data.content)
                with self.assertRaisesRegex(RuntimeError, 'foreign lease'):
                    subject.cleanup(self.run)
                execute.assert_not_called()

    def test_agent_spec_and_restart_pin_are_enforced(self):
        subject.write_json(self.run, subject.BASELINE, self.data.agent)
        with patch.object(subject, 'agent', return_value=copy.deepcopy(self.data.agent)):
            subject.checked_agent(self.run)
        changed = copy.deepcopy(self.data.agent)
        changed['spec']['containers'][0]['image'] = 'changed'
        with patch.object(subject, 'agent', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'specification changed'):
                subject.checked_agent(self.run)
        changed = copy.deepcopy(self.data.agent)
        changed['status']['containerStatuses'][0]['restartCount'] = 1
        with patch.object(subject, 'agent', return_value=changed):
            with self.assertRaisesRegex(ValueError, 'restart history'):
                subject.checked_agent(self.run)

    def test_inventory_rejects_traversal_special_paths_and_duplicate_files(self):
        for text in ['f\t1\t../escape\n', 'f\t1\t/absolute\n', 'f\t1\ta b\n',
                     'f\t1\ta\nf\t2\ta\n', 'l\t1\tlink\n', 'f\t0\tempty\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                subject.parse_inventory(text)
        expected = subject.parse_inventory('f\t1\tmain/core.img\nd\t0\tmain\n')
        with self.assertRaisesRegex(ValueError, 'exact checkpoint inventory'):
            subject.parse_manifest('a' * 64 + '  ./different.img\n', expected)


    def test_capacity_read_enters_host_namespace_and_checks_df_result(self):
        result = SimpleNamespace(stdout='          Avail\n  123456789\n', stderr='', returncode=0)
        with patch.object(subject, 'execute', return_value=result) as execute:
            self.assertEqual(subject.available_bytes(self.run), 123456789)
        command = execute.call_args.args[1]
        self.assertIn('nsenter --target 1 --mount --root=/proc/1/root --wd=/', command)
        self.assertNotIn('|', command)
        for stdout, returncode in [('', 1), ('', 0), ('Avail\n', 0), ('Avail\n1\n2\n', 0), ('Avail\ninvalid\n', 0)]:
            bad = SimpleNamespace(stdout=stdout, stderr='df: no file systems processed', returncode=returncode)
            with self.subTest(stdout=stdout, returncode=returncode), patch.object(subject, 'execute', return_value=bad):
                with self.assertRaises((RuntimeError, ValueError)):
                    subject.available_bytes(self.run)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        Guards.setUp(self)
        self.inventory = {'files': {'inventory.img': 3, 'main/core.img': 7}, 'directories': ['main']}
        self.manifest = 'a' * 64 + '  ./inventory.img\n' + 'b' * 64 + '  ./main/core.img\n'
        self.source = '/checkpoints/artifacts/' + CONTENT_UID
        self.target = '/proc/1/root/mnt/dynamo-snapshot/artifacts/' + CONTENT_UID
        self.partial = self.target + '.partial-nvme-test'
        self.paths = {self.source: copy.deepcopy(self.inventory)}
        self.events = []
        self.lease_calls = []
        patches = [patch.object(subject, 'agent', side_effect=lambda run: copy.deepcopy(self.data.agent)),
                   patch.object(subject.nvme, 'verify_disk', side_effect=lambda run: self.events.append('disk-read')),
                   patch.object(subject, 'require_lease', side_effect=lambda run: self.lease_calls.append(True)),
                   patch.object(subject, 'execute', side_effect=self.execute),
                   patch.object(subject, 'inventory', side_effect=lambda run, path: copy.deepcopy(self.paths[path])),
                   patch.object(subject, 'verify_local', side_effect=self.verify),
                   patch.object(subject.nvme, 'build_helper', side_effect=self.build_helper),
                   patch.object(subject.nvme, 'nvme_view', side_effect=self.attach),
                   patch.object(subject.nvme, 'efs_view', side_effect=self.detach),
                   patch.object(subject, 'validate_overlay', side_effect=self.overlay)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def execute(self, run, script, *args, **kwargs):
        output = ''
        if 'df -B1' in script:
            output = 'Avail\n' + str(10 + subject.MIN_FREE_MARGIN + 1) + '\n'
        elif 'xargs -0 -r sha256sum' in script:
            self.events.append('source-hash')
            output = self.manifest
        elif 'printf yes' in script:
            output = 'yes' if args[0] in self.paths else 'no'
        elif 'cp -a' in script:
            self.events.append('copy')
            self.paths[args[2]] = copy.deepcopy(self.paths[args[0]])
        elif 'mv -T -n' in script:
            self.events.append('promote')
            if args[1] in self.paths:
                raise RuntimeError('Target exists')
            self.paths[args[1]] = self.paths.pop(args[0])
        elif 'rm -f' in script:
            self.events.append('helper-remove')
        return SimpleNamespace(stdout=output, stderr='', returncode=0)

    def verify(self, run, path, expected, manifest):
        self.events.append('verify-' + path)
        if self.paths[path] != expected or manifest != self.manifest:
            raise ValueError('NVMe checkpoint mismatch')
        return 0.5

    def build_helper(self, run):
        self.events.append('helper-build')
        run.state['nvme_mount_helper'] = '/tmp/snapshot-nvme-tools-nvme-test/nvme-bind'
        run.save()

    def attach(self, run):
        self.events.append('attach')
        run.state['nvme_overlay'] = True
        run.save()

    def detach(self, run):
        self.events.append('detach')
        run.state['nvme_overlay'] = False
        run.save()

    def overlay(self, run):
        self.events.append('overlay-check')
        if not run.state.get('nvme_overlay'):
            raise ValueError('No readonly overlay')

    def test_complete_stage_with_deepcopy_save_then_reuse_and_cleanup(self):
        self.run.path.joinpath('agent-before.json').write_text('root harness evidence')
        subject.inspect(self.run)
        record = subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertEqual(self.run.state[subject.KEY]['hash_manifest_sha256'], subject.digest(self.manifest.encode()))
        self.assertEqual(self.run.state[subject.KEY]['expected_files'], 2)
        self.assertEqual(self.run.state[subject.KEY]['expected_bytes'], 10)
        self.assertTrue(self.run.state[subject.KEY]['staged'])
        self.assertTrue(self.run.state[subject.KEY]['overlay_verified'])
        self.assertTrue(record['staging_complete_at'].endswith('+00:00'))
        self.assertTrue(record['overlay_activated_at'].endswith('+00:00'))
        first_events = list(self.events)
        subject.ensure(self.run, self.data.snapshot, self.data.content)
        repeated = self.events[len(first_events):]
        self.assertNotIn('copy', repeated)
        self.assertNotIn('source-hash', repeated)
        self.assertFalse(any(item.startswith('verify-') for item in repeated))
        self.assertNotIn('helper-build', repeated)
        self.assertIn('overlay-check', repeated)
        subject.cleanup(self.run)
        self.assertFalse(self.run.state['nvme_overlay'])
        self.assertNotIn('nvme_mount_helper', self.run.state)
        self.assertIn(self.target, self.paths)
        self.assertIn(self.source, self.paths)
        self.assertEqual(self.run.path.joinpath('agent-before.json').read_text(), 'root harness evidence')
        self.assertIn('helper-remove', self.events)
        self.assertGreaterEqual(len(self.lease_calls), 6)

    def test_initial_staging_requires_a_pinned_inspection(self):
        with self.assertRaisesRegex(ValueError, 'Inspect and pin'):
            subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertNotIn('copy', self.events)

    def test_insufficient_space_stops_before_source_hash_or_copy(self):
        subject.inspect(self.run)
        with patch.object(subject, 'available_bytes', return_value=0):
            with self.assertRaisesRegex(ValueError, 'Insufficient free space'):
                subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertNotIn('copy', self.events)
        self.assertNotIn('source-hash', self.events)

    def test_existing_unrecorded_final_path_is_not_overwritten(self):
        subject.inspect(self.run)
        self.paths[self.target] = copy.deepcopy(self.inventory)
        with self.assertRaisesRegex(ValueError, 'unrecorded NVMe artifact'):
            subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertNotIn('copy', self.events)
        self.assertNotIn('promote', self.events)

    def test_checksum_failure_leaves_partial_and_never_attaches(self):
        subject.inspect(self.run)
        with patch.object(subject, 'verify_local', side_effect=ValueError('checksum failure')):
            with self.assertRaisesRegex(ValueError, 'checksum failure'):
                subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertIn(self.partial, self.paths)
        self.assertNotIn(self.target, self.paths)
        self.assertNotIn('attach', self.events)

    def test_completed_partial_can_resume_without_copy_or_new_source_hash(self):
        subject.inspect(self.run)
        with patch.object(subject, 'verify_local', side_effect=ValueError('interrupted verify')):
            with self.assertRaisesRegex(ValueError, 'interrupted verify'):
                subject.ensure(self.run, self.data.snapshot, self.data.content)
        before = list(self.events)
        subject.ensure(self.run, self.data.snapshot, self.data.content)
        resumed = self.events[len(before):]
        self.assertNotIn('copy', resumed)
        self.assertNotIn('source-hash', resumed)
        self.assertIn('promote', resumed)
        self.assertIn('attach', resumed)

    def test_corrupt_saved_manifest_fails_reuse_without_copy(self):
        subject.inspect(self.run)
        subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.run.path.joinpath(subject.MANIFEST).write_text('corrupt')
        before = self.events.count('copy')
        with self.assertRaises(ValueError):
            subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertEqual(self.events.count('copy'), before)

    def test_cleanup_refuses_foreign_helper_path_without_removal(self):
        subject.inspect(self.run)
        subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.run.state['nvme_mount_helper'] = '/tmp/another-run/nvme-bind'
        with self.assertRaisesRegex(ValueError, 'unexpected NVMe helper'):
            subject.cleanup(self.run)
        self.assertNotIn('helper-remove', self.events)
        self.assertNotIn('detach', self.events)

    def test_ensure_refuses_foreign_helper_before_hash_or_copy(self):
        subject.inspect(self.run)
        self.run.state['nvme_mount_helper'] = '/tmp/another-run/nvme-bind'
        with self.assertRaisesRegex(ValueError, 'unexpected NVMe helper'):
            subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.assertNotIn('source-hash', self.events)
        self.assertNotIn('copy', self.events)

    def test_saved_foreign_staging_paths_fail_before_copy_or_unmount(self):
        subject.inspect(self.run)
        for key in ('nvme_staging_target', 'nvme_partial'):
            with self.subTest(key=key):
                self.run.state[key] = '/another-artifact'
                with self.assertRaisesRegex(ValueError, 'Saved NVMe staging path'):
                    subject.ensure(self.run, self.data.snapshot, self.data.content)
                self.run.state.pop(key)
        subject.ensure(self.run, self.data.snapshot, self.data.content)
        self.run.state['nvme_staging_target'] = '/another-artifact'
        with self.assertRaisesRegex(ValueError, 'Saved NVMe staging path'):
            subject.cleanup(self.run)
        self.assertNotIn('detach', self.events)


if __name__ == '__main__':
    unittest.main()
