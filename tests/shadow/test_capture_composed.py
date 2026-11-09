"""Synthetic offline evidence tests for the first-fault capture lifecycle.

Every PTY used here prints an explicitly synthetic test message. No cluster,
model, actual failure injection or GPU measurement is performed by these tests.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import demos.common.capture as capture
import demos.shadow.composed as full
import tests.shadow.test_composed as full_tests


def health(at):
    return {'receipt': {'node': full.NODE, 'observed_at': at, 'changed_conditions': [],
        'driver_pod_uid': 'driver', 'node_status': {'nodeInfo': {'bootID': 'boot'}},
        'outputs': {'kernel-xids': {'exit_code': 0, 'file': 'xids.txt'}}}, 'xids': []}


def coding(worker='old'):
    content, worker = 'def add(a, b):\n    return a + b', {'decode_worker_id': worker}
    chunks = [{'model': 'fixture', 'choices': [{'finish_reason': 'stop', 'delta': {'content': content}}],
        'nvext': {'worker_id': worker}}]
    return {'request': {'model': 'fixture'}, 'worker': worker, 'content': content,
        'sse': '\n'.join('data: ' + json.dumps(chunk) for chunk in chunks) + '\ndata: [DONE]', 'chunks': chunks}


def metric(engine, value):
    return '\n'.join('dynamo_component_engine_failover_' + suffix + '{engine_id="' + engine + '"} ' + str(value)
        for suffix in ('switch_success_total', 'switch_attempts_total'))


@contextmanager
def fixture():
    with full_tests.FullShadowTests().collected_fixture() as writer:
        _, source_spec, receipts, counts = full.qualified_basis(writer.source, writer.audit)
        run = writer.root / 'results/full-capture'
        run.mkdir()
        save = writer.save
        for name, path in receipts.items(): save(run / 'writer-basis' / name, path.read_bytes())
        shutil.copytree(writer.source / 'source-snapshot', run / 'source-snapshot')
        shutil.copytree(writer.source / 'runtime-contract-sources', run / 'runtime-contract-sources')
        namespace = 'dynamo-ft-capture-fixture'
        graph = {'metadata': {'uid': 'dgd-uid', 'generation': 1}, 'spec': {'components': []}}
        save(run / 'full-applied-dgd.json', graph)
        save(run / 'deployment.yaml', b'fixture manifest\n')
        spec = dict(source_spec, profile=full.PROFILE, namespace=namespace, reader_enabled=True,
            source_writer_collected=True, source_writer_run=str(writer.source),
            source_writer_original_run=str(writer.original), source_writer_namespace=writer.state['namespace'],
            writer_basis_receipts={name: capture.sha256(path) for name, path in receipts.items()},
            expected_runtime_counts=counts, inputs={'deployment.yaml': capture.sha256(run / 'deployment.yaml')})
        save(run / 'full-spec.json', spec)
        states = {'engine-0': 'active', 'engine-1': 'standby'}
        ready = {'pod_uid': 'full-pod', 'node': full.NODE, 'states': states,
            'container_statuses': {name: {'containerID': name + '-id', 'restartCount': 0}
                for name in ('engine-0', 'engine-1', 'gms-server')},
            'engines': {'engine-' + str(i): {'engine_id': str(i), 'gpu_uuids': list(full.UUIDS),
                'metrics': metric(str(i), 0), 'lock_held': True, 'lock_owner': 'engine-0'} for i in (0, 1)},
            'gms': {}}
        for rank in (0, 1):
            ready['gms']['gms_' + str(rank) + '_weights.sock'] = {
                'state': {'memory_layout_hash': 'a' * 64},
                'events': {'events': [{'kind': 'rw_connected'}, {'kind': 'committed'}]}}
            ready['gms']['gms_' + str(rank) + '_kv_cache.sock'] = {'events': {'events': []}}
        for name in ('full-ready-before.json', 'full-ready-after.json'): save(run / name, ready)
        save(run / 'full-ready-coding.json', [coding(), coding(), coding()])
        state = {'namespace': namespace, 'shadow_full_profile': full.PROFILE,
            'shadow_full_spec_sha256': capture.sha256(run / 'full-spec.json'),
            'shadow_full_dgd_uid': 'dgd-uid', 'shadow_full_dgd_generation': 1,
            'shadow_full_dgd_spec_sha256': hashlib.sha256(json.dumps(graph['spec'], sort_keys=True).encode()).hexdigest(),
            'checks': {'shadow-full-ready': {'status': 'passed', 'updated_at': '2026-11-05T00:02:00Z',
                'pod_uid': 'full-pod', 'dgd_uid': 'dgd-uid', 'states': states, 'responses': 3}},
            'attempts': [{'fixture': True}]}
        save(run / 'state.json', state)
        demo = {'profile': full.PROFILE, 'shadow_profile': full.PROFILE, 'rehearsal': False,
            'namespace': namespace, 'model': 'fixture', 'step': 0, 'prepared': True,
            'ready_observed_at': '2026-11-05T00:02:00Z', 'apply_started_at': '2026-11-05T00:00:00Z'}
        save(run / 'demo.json', demo)
        save(run / 'health-before.json', health('2026-11-05T00:01:00Z'))
        pre_fault_source = writer.root / 'pre-fault-health.json'
        pre_fault = health('2026-11-05T00:03:00Z')
        save(pre_fault_source, pre_fault['receipt'])
        pre_fault.update(source=str(pre_fault_source), source_sha256=capture.sha256(pre_fault_source))
        save(run / 'health-before-fault.json', pre_fault)
        yield SimpleNamespace(run=run, root=writer.root, writer=writer, save=save, ready=ready, demo=demo,
            state=state, pre_fault_source=pre_fault_source)


def fault(f):
    after = copy.deepcopy(f.ready)
    after['states'] = {'engine-0': 'standby', 'engine-1': 'active'}
    after['container_statuses']['engine-0'] = {'containerID': 'restarted', 'restartCount': 1}
    after['engines']['engine-1'].update(metrics=metric('1', 1), lock_owner='engine-1')
    for name, value in after['gms'].items():
        if name.endswith('_kv_cache.sock'):
            value['events']['events'].append({'kind': 'allocations_cleared', 'allocation_count': 8})
    f.save(f.run / 'shadow-observation-100.json', after)
    proof = {'status': 'passed', 'updated_at': '2026-11-05T00:05:00Z', 'model': 'fixture',
        'tensor_parallel_size': 2, 'new_standby_confirmed': True, 'pod_uid': 'full-pod',
        'active_before': 'engine-0', 'active_after': 'engine-1',
        'fault_command_to_first_verified_response_seconds': 2.5,
        'worker_before': coding()['worker'], 'worker_after': coding('new')['worker']}
    f.save(f.run / 'recovery-proof.json', dict(proof, timing_scope='synthetic test boundary'))
    f.save(f.run / 'shadow-baseline-response.json', coding())
    f.save(f.run / 'shadow-recovered-response.json', coding('new'))
    f.save(f.run / 'shadow-fault-intent.json', {'pod_uid': 'full-pod', 'container': 'engine-0',
        'container_id': 'engine-0-id', 'engine_id': '0', 'signal': 'SIGKILL'})
    f.save(f.run / 'shadow-fault.json', {'engine_id': '0', 'signal': 'SIGKILL', 'pid': 42,
        'command': 'VLLM::EngineCore_test', 'sent_at_unix': 1})
    f.state['checks']['shadow-failover'] = proof
    f.save(f.run / 'state.json', f.state)
    f.demo['step'] = 4
    f.save(f.run / 'demo.json', f.demo)


def qualify(f):
    f.save(f.run / 'health-after.json', health('2026-11-05T00:06:00Z'))
    f.state['checks']['shadow-full-qualification'] = {'status': 'passed', 'updated_at': '2026-11-05T00:07:00Z'}
    f.save(f.run / 'check-shadow-full-qualification-100.json', f.state['checks']['shadow-full-qualification'])
    f.state['attempts'].append({'finalize': True})
    f.save(f.run / 'state.json', f.state)


class ComposedCaptureTests(unittest.TestCase):
    def args(self, f, **changes):
        args = dict(demo=capture.COMPOSED_SHADOW, run=f.run, output=f.root / 'attempt', raw_output=f.root / 'private',
            rehearsal=False, quiet=True, startup_timeout=60, capture_timeout=10, width=180, port=None,
            defer_qualification=True, finalize_pending=False, pre_fault_health=f.pre_fault_source)
        args.update(changes)
        return SimpleNamespace(**args)

    def pending(self, f):
        args = self.args(f)
        original = capture.record
        def recorded(command, private, **kwargs):
            self.assertEqual(command[2:5], ['-m', 'demos', 'shadow-composed'])
            self.assertEqual(command[command.index('--health-after') + 1], str(f.pre_fault_source))
            fault(f)
            return original([sys.executable, '-c', 'print("SYNTHETIC UNIT TEST: first fault main panel")'], private, **kwargs)
        with patch.object(capture, 'record', side_effect=recorded): self.assertEqual(capture.capture(args), 0)
        return args

    def test_mapping_requires_actual_frozen_primed_run_and_never_rehearsal(self):
        self.assertEqual(capture.DEMOS[capture.COMPOSED_SHADOW].module, 'demos.shadow.composed')
        with fixture() as f:
            with patch.object(capture, 'record') as record, self.assertRaises(ValueError):
                capture.capture(self.args(f, rehearsal=True))
            record.assert_not_called()

    def test_writer_acceptance_initial_streams_and_ready_identity_are_required(self):
        for change in ('audit', 'rank', 'ready', 'stream', 'dgd'):
            with self.subTest(change=change), fixture() as f:
                if change == 'audit': (f.run / 'writer-basis/root-acceptance.json').write_text('{}')
                elif change == 'rank': (f.run / 'writer-basis/rank-manifests/rank-1.json').unlink()
                elif change == 'ready':
                    ready = copy.deepcopy(f.ready); ready['states']['engine-1'] = 'init'
                    f.save(f.run / 'full-ready-after.json', ready)
                elif change == 'stream': f.save(f.run / 'full-ready-coding.json', [coding()])
                elif change == 'dgd':
                    graph = json.loads((f.run / 'full-applied-dgd.json').read_text()); graph['metadata']['generation'] += 1
                    f.save(f.run / 'full-applied-dgd.json', graph)
                with patch.object(capture, 'record') as record, self.assertRaises((ValueError, OSError)):
                    capture.capture(self.args(f))
                record.assert_not_called()

    def test_explicit_prefault_health_must_match_ready_node_driver_and_time(self):
        for change in ('absent', 'stale', 'driver', 'boot', 'output'):
            with self.subTest(change=change), fixture() as f:
                args = self.args(f)
                if change == 'absent': args.pre_fault_health = None
                else:
                    value = json.loads(f.pre_fault_source.read_text())
                    if change == 'stale': value['observed_at'] = '2026-11-05T00:01:00Z'
                    elif change == 'driver': value['driver_pod_uid'] = 'replacement'
                    elif change == 'boot': value['node_status']['nodeInfo']['bootID'] = 'reboot'
                    elif change == 'output': value['outputs']['kernel-xids']['exit_code'] = 1
                    f.save(f.pre_fault_source, value)
                with patch.object(capture, 'record') as record, self.assertRaises(ValueError): capture.capture(args)
                record.assert_not_called()

    def test_actual_fault_replenishment_and_health_have_separate_gates(self):
        with fixture() as f:
            fault(f)
            capture.validate_shadow_composed_capture(f.run, f.demo, require_health=False)
            self.assertFalse(capture.completed(capture.COMPOSED_SHADOW, f.run, False)[0])
            qualify(f)
            self.assertTrue(capture.completed(capture.COMPOSED_SHADOW, f.run, False)[0])

    def test_missing_or_tampered_fault_promotion_weights_and_health_are_rejected(self):
        for change in ('intent', 'pid', 'same-worker', 'counter', 'weight-events', 'replenishment',
                'gms-restart', 'kv-reclaim', 'stale-health', 'new-xid', 'boot'):
            with self.subTest(change=change), fixture() as f:
                fault(f); qualify(f)
                if change == 'intent': (f.run / 'shadow-fault-intent.json').unlink()
                elif change == 'pid':
                    value = json.loads((f.run / 'shadow-fault.json').read_text()); value['pid'] = 1
                    f.save(f.run / 'shadow-fault.json', value)
                elif change == 'same-worker': f.save(f.run / 'shadow-recovered-response.json', coding())
                elif change in ('counter', 'weight-events', 'replenishment', 'gms-restart', 'kv-reclaim'):
                    value = json.loads((f.run / 'shadow-observation-100.json').read_text())
                    if change == 'counter': value['engines']['engine-1']['metrics'] = metric('1', 2)
                    elif change == 'weight-events': value['gms']['gms_0_weights.sock']['events']['events'].append({'kind': 'committed'})
                    elif change == 'replenishment': value['states']['engine-0'] = 'init'
                    elif change == 'gms-restart': value['container_statuses']['gms-server']['restartCount'] = 1
                    elif change == 'kv-reclaim': value['gms']['gms_0_kv_cache.sock']['events']['events'] = []
                    f.save(f.run / 'shadow-observation-100.json', value)
                else:
                    value = json.loads((f.run / 'health-after.json').read_text())
                    if change == 'stale-health': value['receipt']['observed_at'] = '2026-11-05T00:04:00Z'
                    elif change == 'new-xid': value['xids'] = ['NVRM: Xid 31']
                    elif change == 'boot': value['receipt']['node_status']['nodeInfo']['bootID'] = 'rebooted'
                    f.save(f.run / 'health-after.json', value)
                ok, reason = capture.completed(capture.COMPOSED_SHADOW, f.run, False)
                self.assertFalse(ok, reason)

    def test_pending_seals_original_main_sources_and_private_provenance(self):
        with fixture() as f:
            args = self.pending(f)
            meta = json.loads((args.output / 'capture.json').read_text())
            self.assertEqual(meta['status'], 'pending_qualification')
            self.assertIn('prepared offstage', meta['startup_scope'])
            self.assertFalse(meta['startup_provenance']['startup_measured_in_capture'])
            self.assertTrue((args.output / 'pending-main.txt').exists())
            self.assertFalse((args.output / 'main.txt').exists())
            self.assertEqual(meta['pre_fault_health']['source_sha256'], capture.sha256(args.raw_output / 'pre-fault-health-source.json'))
            for name in ('full-spec.json', 'full-ready-after.json', 'shadow-fault.json',
                    'writer-basis/root-acceptance.json', 'writer-basis/rank-manifests/rank-1.json'):
                path = args.raw_output / 'evidence' / name
                self.assertEqual(meta['evidence_sha256'][name], capture.sha256(path))
                self.assertEqual(path.stat().st_mode & 0o777, 0o400)

    def test_nonzero_first_fault_run_stays_failed_and_cannot_be_finalized(self):
        with fixture() as f:
            args, original = self.args(f), capture.record
            def recorded(command, private, **kwargs):
                fault(f)
                return original([sys.executable, '-c', 'print("SYNTHETIC FAILED RUN"); raise SystemExit(7)'], private, **kwargs)
            with patch.object(capture, 'record', side_effect=recorded): self.assertEqual(capture.capture(args), 7)
            self.assertEqual(json.loads((args.output / 'capture.json').read_text())['status'], 'failed')
            self.assertFalse((args.output / 'pending-main.txt').exists())
            qualify(f)
            args.defer_qualification, args.finalize_pending = False, True
            with patch.object(capture, 'record') as record, self.assertRaises(ValueError): capture.capture(args)
            record.assert_not_called()

    def test_finalize_appends_health_without_child_and_preserves_main_bytes(self):
        with fixture() as f:
            args = self.pending(f)
            original = (args.output / 'pending-main.txt').read_bytes()
            original_evidence = capture.sha256(args.raw_output / 'evidence/state.json')
            qualify(f)
            args.defer_qualification, args.finalize_pending = False, True
            with patch.object(capture, 'record', side_effect=AssertionError('Finalization cannot launch a child')):
                self.assertEqual(capture.capture(args), 0)
            self.assertEqual((args.output / 'main.txt').read_bytes(), original)
            self.assertEqual(capture.sha256(args.raw_output / 'evidence/state.json'), original_evidence)
            meta = json.loads((args.output / 'capture.json').read_text())
            self.assertEqual(meta['status'], 'live_passed')  # Synthetic lifecycle classification only.
            shutil.rmtree(f.run); shutil.rmtree(f.writer.source)
            self.assertTrue(capture.completed(capture.COMPOSED_SHADOW, args.raw_output / 'final-evidence', False)[0])
            with self.assertRaises(ValueError): capture.capture(args)

    def test_pending_finalization_rejects_raw_transcript_receipt_proof_and_run_drift(self):
        for change in ('raw', 'timeline', 'text', 'receipt', 'proof', 'state', 'wrong-run', 'terminal-failed',
                'missing-health', 'extra-observation', 'source'):
            with self.subTest(change=change), fixture() as f:
                args = self.pending(f)
                if change != 'missing-health': qualify(f)
                args.defer_qualification, args.finalize_pending = False, True
                if change == 'raw': (args.raw_output / 'main-panel.ansi').write_text('changed')
                elif change == 'timeline': (args.raw_output / 'timeline.jsonl').write_text('changed')
                elif change == 'text': (args.output / 'pending-main.txt').write_text('changed')
                elif change in ('receipt', 'terminal-failed'):
                    value = json.loads((args.output / 'capture.json').read_text())
                    value['status' if change == 'terminal-failed' else 'run'] = 'failed' if change == 'terminal-failed' else 'changed'
                    f.save(args.output / 'capture.json', value)
                elif change == 'proof': (f.run / 'shadow-fault.json').write_text('{}')
                elif change == 'state':
                    f.state['shadow_full_dgd_uid'] = 'changed'; f.save(f.run / 'state.json', f.state)
                elif change == 'wrong-run': args.run = f.root / 'other'
                elif change == 'extra-observation': f.save(f.run / 'shadow-observation-200.json', f.ready)
                elif change == 'source':
                    path = args.raw_output / 'sources/capture_workshop_demo.py'
                    path.chmod(0o600); path.write_text('changed source')
                with patch.object(capture, 'record') as record, self.assertRaises((ValueError, OSError)):
                    capture.capture(args)
                record.assert_not_called()
                self.assertFalse((args.output / 'main.txt').exists())


if __name__ == '__main__': unittest.main()
