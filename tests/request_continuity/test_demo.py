"""Fault-target identity, real SSE capture, and continuity evidence gates."""
from tests.support import ROOT
import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

import demos.common.placement as placement
import demos.common.runtime as ui
import demos.common.support as support
import demos.request_continuity.demo as demo
import demos.request_continuity.probe as probe
from demos.request_continuity.evidence import retry_proof


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18004, timeout=60)


def pod(name, role='worker'):
    return {'metadata': {'name': name, 'uid': name + '-uid', 'namespace': 'ns',
                         'labels': {'feature-test-run': 'ns', 'workshop-role': role}},
            'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                       'containerStatuses': [{'name': 'main', 'containerID': name, 'restartCount': 0}]}}


WORKERS = {'1': {'uid': 'a-uid', 'pod': 'a'}, '2': {'uid': 'b-uid', 'pod': 'b'}}


def chunk(worker='1', text='x', finish=None):
    return {'id': 'one-response', 'model': 'model',
            'nvext': {'worker_id': {'decode_worker_id': int(worker)}},
            'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': finish}]}


def stream(enabled=True):
    events = [{'type': 'chunk', 'seconds': i, 'chunk': chunk(), 'worker': '1', 'content': 'x'}
              for i in range(16)]
    events.append({'type': 'fault_gate', 'seconds': 15.1, 'worker': '1'})
    if enabled:
        events += [{'type': 'chunk', 'seconds': 18, 'chunk': chunk('2', 'y'), 'worker': '2', 'content': 'y'},
                   {'type': 'chunk', 'seconds': 19, 'chunk': chunk('2', '', 'stop'), 'worker': '2', 'content': ''}]
    else:
        events.append({'type': 'chunk', 'seconds': 18, 'chunk': {'error': {'message': 'engine died'}},
                       'worker': '1', 'content': ''})
    events.append({'type': 'done', 'seconds': 20})
    return {'events': events, 'http_status': 200, 'request_count': 1, 'read_error': None,
            'fault': {'submitted_at_seconds': 15.2, 'acknowledged_at_seconds': 17,
                      'receipt': {'worker_id': '1', 'pod_uid': 'a-uid', 'signal': 'SIGKILL', 'signal_sent': True}}}


class ProofTests(unittest.TestCase):
    def retry_log(self, response='one-response'):
        outer = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        # Use a realistic response UUID so it can be correlated with the HTTP span.
        response = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        return (f'route request failed request_id={outer} request_id={response} worker_id=1 request.attempt=0\n'
                f'migration retry scheduled request.attempt=1 migration.is_retry=true migration.from_worker_id=1 '
                f'migration.tokens_completed=31 request_id={outer}\n'
                f'Conflicting request tracker write field="decode_worker_id" existing=1 new=2 request_id={outer}')

    def test_sticky_sse_requires_response_correlated_retry_and_known_peer(self):
        result = stream()
        response = 'chatcmpl-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
        for e in result['events']:
            if e['type'] == 'chunk':
                e['chunk']['id'] = response
                e['worker'] = '1'
                e['chunk']['nvext']['worker_id']['decode_worker_id'] = 1
        with self.assertRaises(ValueError):
            demo.validate_stream(result, 'enabled', 'model', WORKERS)
        proof = demo.validate_stream(result, 'enabled', 'model', WORKERS, frontend_log=self.retry_log())
        self.assertEqual(proof['continuation_workers'], ['2'])
        self.assertEqual(proof['migration_trace']['retained_output_tokens'], 31)
        self.assertIsNone(proof['client_recovery_gap_seconds'])
        self.assertEqual(proof['worker_attribution'], 'correlated_frontend_trace_sse_sticky')
        for invalid in (self.retry_log().replace('new=2', 'new=3'),
                        self.retry_log().replace('tokens_completed=31', 'tokens_completed=0'),
                        self.retry_log().replace('migration.from_worker_id=1', 'migration.from_worker_id=2'),
                        self.retry_log().replace('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'cccccccc-cccc-cccc-cccc-cccccccccccc'),
                        self.retry_log() + '\nmigration retry scheduled request_id=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                demo.validate_stream(result, 'enabled', 'model', WORKERS, frontend_log=invalid)

    def test_broken_and_continued_outcomes(self):
        broken = demo.validate_stream(stream(False), 'disabled', 'model', WORKERS)
        self.assertFalse(broken['successful_completion'])
        continued = demo.validate_stream(stream(), 'enabled', 'model', WORKERS)
        self.assertTrue(continued['successful_completion'])
        self.assertEqual(continued['client_recovery_gap_seconds'], 3)
        self.assertEqual(continued['continuation_workers'], ['2'])

    def test_rejects_false_success(self):
        cases = []
        value = stream(); value['fault']['receipt']['signal_sent'] = False; cases.append(value)
        value = stream(); value['fault']['receipt']['pod_uid'] = 'replacement'; cases.append(value)
        value = stream(); value['request_count'] = 2; cases.append(value)
        value = stream(); value['events'][0]['chunk']['id'] = 'other'; cases.append(value)
        value = stream(); value['events'][0]['chunk']['model'] = 'other'; cases.append(value)
        value = stream(); value['events'][0]['chunk']['choices'][0]['finish_reason'] = 'stop'; cases.append(value)
        value = stream(); value['events'][17]['worker'] = 'unknown'; cases.append(value)
        value = stream(); value['events'][17]['worker'] = '1'; cases.append(value)
        value = stream(); value['events'][18]['chunk']['error'] = {'message': 'failed'}; cases.append(value)
        value = stream(); value['read_error'] = {'message': 'truncated'}; cases.append(value)
        value = stream(); value['events'].pop(); cases.append(value)
        value = stream(); value['events'][-1]['seconds'] = 18.5; cases.append(value)
        value = stream(); value['events'][18]['chunk']['choices'][0]['finish_reason'] = 'error'; cases.append(value)
        for index, invalid in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                demo.validate_stream(invalid, 'enabled', 'model', WORKERS)
        with self.assertRaises(ValueError):
            demo.validate_stream(stream(), 'disabled', 'model', WORKERS)

    def test_survivors_cannot_disappear_restart_or_be_replaced(self):
        before = [pod('a'), pod('b'), pod('f', 'frontend')]
        demo.verify_survivors(before, copy.deepcopy(before), 'a-uid')
        bad = copy.deepcopy(before); bad[1]['metadata']['uid'] = 'new'
        restarted = copy.deepcopy(before); restarted[2]['status']['containerStatuses'][0]['restartCount'] = 1
        changed = copy.deepcopy(before); changed[1]['status']['containerStatuses'][0]['containerID'] = 'new'
        for after in (before[:2], bad, restarted, changed):
            with self.assertRaises((ValueError, RuntimeError)):
                demo.verify_survivors(before, after, 'a-uid')

    def test_metadata_requires_current_owner_uid_and_unique_worker_ids(self):
        pods = [pod('a'), pod('b'), pod('f', 'frontend')]
        metadata = [{'metadata': {'name': n, 'namespace': 'ns',
                                 'ownerReferences': [{'kind': 'Pod', 'uid': n + '-uid'}]},
                     'spec': {'data': {'endpoints': {'generate': {
                         'component': 'backend', 'endpoint': 'generate', 'instance_id': i}}}}}
                    for i, n in enumerate(('a', 'b'), 1)]
        self.assertEqual(set(demo.registered_workers(pods, metadata, 'ns')), {'1', '2'})
        for field, value in [('uid', 'old'), ('kind', 'Deployment')]:
            stale = copy.deepcopy(metadata); stale[0]['metadata']['ownerReferences'][0][field] = value
            with self.assertRaises(ValueError):
                demo.registered_workers(pods, stale, 'ns')


class ProbeTests(unittest.TestCase):
    def process(self, root, pid, command='VLLM::EngineCore', ticks='123'):
        path = root / str(pid); path.mkdir()
        (path / 'cmdline').write_bytes(command.encode() + b'\0')
        # stat field 22 is index 19 after the closing command parenthesis.
        (path / 'stat').write_text(str(pid) + ' (process name) ' + ' '.join(['0'] * 19 + [ticks]))

    def test_only_inspected_engine_is_killed_and_pid_reuse_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.process(root, 1); self.process(root, 10, 'python'); self.process(root, 20)
            expected = probe.inspect(root)
            self.assertEqual(expected['pid'], 20)
            with mock.patch.object(probe.os, 'kill') as kill:
                self.assertTrue(probe.kill(expected, root)['signal_sent'])
                kill.assert_called_once_with(20, signal.SIGKILL)
                kill.reset_mock()
                with self.assertRaises(ValueError):
                    probe.kill({**expected, 'start_ticks': 'different'}, root)
                kill.assert_not_called()
            self.process(root, 21)
            with self.assertRaises(ValueError):
                probe.inspect(root)


class StreamReaderTests(unittest.TestCase):
    def capture(self, tail, fault_error=False):
        invoked = threading.Event()
        requests = []
        def inject(worker):
            self.assertEqual(worker, '1')
            invoked.set()
            if fault_error:
                raise RuntimeError('target changed')
            return {'worker_id': worker, 'pod_uid': 'a-uid', 'signal': 'SIGKILL', 'signal_sent': True}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(handler):
                requests.append(json.loads(handler.rfile.read(int(handler.headers['Content-Length']))))
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/event-stream')
                handler.end_headers()
                for i in range(16):
                    handler.wfile.write(('data: ' + json.dumps(chunk()) + '\r\n\r\n').encode())
                handler.wfile.flush()
                if not invoked.wait(3):
                    return
                handler.wfile.write(tail)
                handler.wfile.flush()
            def log_message(*a):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                result = demo.capture_stream('http://127.0.0.1:' + str(server.server_port),
                                             {'stream': True}, Path(d), inject, echo=False)
                self.assertEqual(len(requests), 1)
                self.assertTrue((Path(d) / 'response.sse').read_bytes().endswith(tail))
                self.assertEqual(len((Path(d) / 'events.jsonl').read_text().splitlines()), len(result['events']))
                self.assertTrue((Path(d) / 'fault-result.json').exists())
                return result
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_real_http_reader_works_while_fault_callback_executes(self):
        tail = ''.join('data: ' + json.dumps(c) + '\n\n'
                       for c in (chunk('2', 'y'), chunk('2', '', 'stop'))) + 'data: [DONE]\n\n'
        result = self.capture(tail.encode())
        self.assertTrue(demo.validate_stream(result, 'enabled', 'model', WORKERS)['successful_completion'])

    def test_truncation_and_failed_fault_cannot_qualify(self):
        for tail, error in [(b'data: {"partial":', False), (b'data: [DONE]\n\n', True),
                            (b'data: {"error":{"message":"failed"}}\n\ndata: [DONE]\n\n', False)]:
            with self.subTest(tail=tail):
                result = self.capture(tail, error)
                with self.assertRaises(ValueError):
                    demo.validate_stream(result, 'enabled', 'model', WORKERS)


class PlacementTests(unittest.TestCase):
    DAY = ROOT / 'demos/allocations/workshop-request-continuity.json'

    def test_workshop_placement_pins_each_case_to_its_two_nodes(self):
        day = json.loads(self.DAY.read_text())
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {placement.ENV: str(self.DAY)}):
            instance = demo.MigrationDemo(args(Path(directory) / 'run'))
            self.assertEqual(instance.data['placement'], day)
            for arm in demo.ARMS:
                graph = ui.read_json(instance.path / (arm + '-deployment.json'))
                claim = ui.read_json(instance.path / (arm + '-claim.json'))
                worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
                spec = worker['podTemplate']['spec']
                self.assertEqual(worker['replicas'], 2)
                self.assertIn('podAntiAffinity', spec['affinity'])
                terms = spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
                self.assertTrue(all({'key': 'kubernetes.io/hostname', 'operator': 'In',
                                     'values': [t['node'] for t in day['targets'][arm]]} in term['matchExpressions']
                                    for term in terms))
                expression = claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'][0]['cel']['expression']
                self.assertTrue(expression.endswith(json.dumps([u for t in day['targets'][arm] for u in t['gpu_uuids']])))
            # Pins live in the frozen, digest-checked inputs, so a resumed run cannot drift.
            self.assertTrue({arm + '-claim.json' for arm in demo.ARMS} <= set(instance.data['inputs']))
            demo.MigrationDemo(args(instance.path))

    def test_continuity_refuses_the_intro_allocation(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(ui, 'ALLOCATION', object()):
            with self.assertRaisesRegex(ValueError, 'Continuity takes WORKSHOP_PLACEMENT'):
                demo.MigrationDemo(args(Path(directory) / 'run'))

class LifecycleTests(unittest.TestCase):
    def test_live_presentation_requires_offstage_priming_before_any_cluster_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.MigrationDemo(args(Path(directory) / 'run'))
            instance.args.rehearsal = False
            with (mock.patch.object(instance, 'prime') as prime,
                  mock.patch.object(instance, 'prepare') as prepare,
                  mock.patch.object(instance.run, 'apply') as apply,
                  mock.patch.object(instance.run, 'k') as kubectl,
                  self.assertRaisesRegex(RuntimeError, 'Prime both continuity cases offstage')):
                instance.guided()
            for operation in (prime, prepare, apply, kubectl):
                operation.assert_not_called()

    def test_primed_presentation_never_reloads_a_completed_faulted_case(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.MigrationDemo(args(Path(directory) / 'run'))
            instance.args.rehearsal = False
            instance.data.update(prepared=True, cases={
                'disabled': {'completed_at': ui.now()}, 'enabled': {'ready_at': ui.now()}})
            output = io.StringIO()
            with (mock.patch.object(ui, 'lease_owned', return_value=True),
                  mock.patch.object(instance, 'verify_case') as verify,
                  mock.patch.object(instance, 'prime') as prime,
                  mock.patch.object(instance, 'run_steps') as walkthrough,
                  mock.patch.object(instance.run, 'apply') as apply,
                  contextlib.redirect_stdout(output)):
                instance.guided()
            verify.assert_called_once_with('enabled')
            prime.assert_not_called()
            apply.assert_not_called()
            walkthrough.assert_called_once()
            self.assertNotIn('Preparation', output.getvalue())
            self.assertTrue(instance.compact_output)

    def test_presentation_refuses_lost_lease_before_readiness_or_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.MigrationDemo(args(Path(directory) / 'run'))
            instance.args.rehearsal = False
            instance.data.update(prepared=True, cases={arm: {'ready_at': ui.now()} for arm in demo.ARMS})
            with (mock.patch.object(ui, 'lease_owned', return_value=False),
                  mock.patch.object(instance, 'verify_case') as verify,
                  mock.patch.object(instance, 'run_steps') as walkthrough,
                  self.assertRaisesRegex(RuntimeError, 'does not own the GPU lease')):
                instance.guided()
            verify.assert_not_called()
            walkthrough.assert_not_called()

    def test_settings_projection_tracks_the_actual_frozen_frontend_and_worker_flags(self):
        graphs = {arm: demo.render('ns', ui.read_json(ui.MODEL_LOCK), arm)[0] for arm in demo.ARMS}
        frontend = next(c for c in graphs['enabled']['spec']['components'] if c['type'] == 'frontend')
        worker = next(c for c in graphs['enabled']['spec']['components'] if c['type'] == 'worker')
        value = next(e for e in frontend['podTemplate']['spec']['containers'][0]['env']
                     if e['name'] == 'DYN_MIGRATION_LIMIT')
        value['value'] = '7'
        worker['replicas'] = 3
        before = copy.deepcopy(graphs)
        excerpt = demo.settings_excerpt(graphs)
        self.assertEqual(graphs, before)
        self.assertEqual(excerpt['cases']['enabled']['frontend']['DYN_MIGRATION_LIMIT'], '7')
        self.assertEqual(excerpt['cases']['disabled']['frontend']['DYN_MIGRATION_LIMIT'], '0')
        self.assertEqual(excerpt['cases']['enabled']['worker_replicas'], 3)
        self.assertEqual(excerpt['cases']['enabled']['tensor_parallel_size'], 2)
        self.assertLessEqual(len(yaml.safe_dump(excerpt).splitlines()), 30)

    def test_changed_frozen_input_and_interrupted_case_are_never_reused(self):
        with tempfile.TemporaryDirectory() as d:
            instance = demo.MigrationDemo(args(Path(d) / 'run'))
            original = (instance.path / 'request.json').read_bytes()
            (instance.path / 'request.json').write_text('{}')
            with self.assertRaises(ValueError):
                instance.prepare()
            (instance.path / 'request.json').write_bytes(original)
            (instance.path / 'disabled').mkdir()
            with self.assertRaises(ValueError):
                instance.prime()

    def test_process_access_requires_owned_isolated_worker(self):
        with tempfile.TemporaryDirectory() as d:
            instance = demo.MigrationDemo(args(Path(d) / 'run'))
            good = pod('a'); good['metadata']['namespace'] = instance.ns
            good['metadata']['labels'].update({'feature-test-run': instance.ns, 'workshop-demo': 'continuity'})
            good['spec'] = {}
            foreign = copy.deepcopy(good); foreign['metadata']['labels']['feature-test-run'] = 'other'
            host = copy.deepcopy(good); host['spec']['hostPID'] = True
            shared = copy.deepcopy(good); shared['spec']['shareProcessNamespace'] = True
            with mock.patch.object(instance.run, 'k') as k:
                for invalid in (foreign, host, shared):
                    with self.assertRaises(ValueError):
                        instance.probe(invalid, 'inspect')
                k.assert_not_called()

    def test_cleanup_requires_graph_ownership_and_retains_lease_on_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            instance = demo.MigrationDemo(args(Path(d) / 'run')); instance.args.rehearsal = False
            lease = Path(d) / 'lease'
            with mock.patch.object(ui, 'LEASE', lease):
                ui.acquire(instance.path, demo.OWNER)
                foreign = subprocess.CompletedProcess([], 0, '{"metadata":{"labels":{}}}', '')
                with mock.patch.object(instance.run, 'k', return_value=foreign) as k:
                    with self.assertRaises(ValueError):
                        instance.cleanup()
                    k.assert_called_once()
                self.assertTrue(ui.lease_owned(instance.path, demo.OWNER))

    def test_renderer_matches_qualified_runtime_and_only_changes_migration_setting(self):
        lock = ui.read_json(ui.MODEL_LOCK)
        for arm, limit in demo.ARMS.items():
            graph, claim = demo.render('ns', lock, arm)
            self.assertEqual(claim['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
            for component in graph['spec']['components']:
                worker = component['type'] == 'worker'
                self.assertEqual(component['replicas'], 2 if worker else 1)
                pod = component['podTemplate']; main = pod['spec']['containers'][0]
                self.assertEqual(pod['metadata']['labels']['feature-test-run'], 'ns')
                self.assertEqual(main['image'], lock['runtime_image'])
                if worker:
                    self.assertIn(lock['revision'], main['args'])
                    self.assertIn('--enforce-eager', main['args'])
                    self.assertIn('--language-model-only', main['args'])
                else:
                    env = {e['name']: e.get('value') for e in main['env']}
                    self.assertEqual(env['DYN_MIGRATION_LIMIT'], str(limit))

    def test_rehearsal_resume_readonly_observer_and_foreign_lease(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'run with spaces'
            command = [sys.executable, '-B', '-m', 'demos', 'request-continuity', '--rehearsal',
                       '--plain', '--auto', '--run', str(path)]
            for _ in range(2):
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('Preparation', result.stdout)
                self.assertNotIn('client recovery gap=None', result.stdout)
                self.assertNotIn('Step finished in', result.stdout)
            self.assertTrue(ui.read_json(path / 'comparison.json')['simulated'])
            saved = (path / 'demo.json').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                support.observe(path, 'resources', once=True)
            self.assertEqual(saved, (path / 'demo.json').read_bytes())
            instance = demo.MigrationDemo(args(path)); instance.args.rehearsal = False
            lease = Path(d) / 'lease'; lease.mkdir()
            original = '{"agent":"another-workstream","run":"/foreign"}'
            (lease / 'owner.json').write_text(original)
            with mock.patch.object(ui, 'LEASE', lease), mock.patch.object(instance.run, 'k') as k:
                for action in (instance.prepare, instance.cleanup):
                    with self.assertRaises(RuntimeError):
                        action()
                k.assert_not_called()
            self.assertEqual((lease / 'owner.json').read_text(), original)


class PresentationTests(unittest.TestCase):
    def test_sticky_worker_summary_distinguishes_unavailable_handoff_from_whole_response_gap(self):
        proof = {'simulated': False, 'successful_completion': True, 'http_requests': 1,
                 'worker_attribution': 'correlated_frontend_trace_sse_sticky',
                 'migration_trace': {'retained_output_tokens': 31},
                 'continuation_workers': ['2'], 'finish_reasons': ['stop'],
                 'client_recovery_gap_seconds': None, 'max_client_inter_content_gap_seconds': 6.25}
        summary = demo.outcome_summary(proof)
        self.assertEqual(summary['Exact handoff gap'], 'unavailable (sticky SSE)')
        self.assertEqual(summary['Max client content gap'], '6.25s')
        self.assertEqual(summary['Accepted output retained'], '31 tokens')
        self.assertEqual(summary['Client response ID'], 'stable')
        self.assertNotIn('None', ' '.join(summary.values()))

    def test_completed_case_replay_keeps_full_proof_private_and_injects_no_new_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = demo.MigrationDemo(args(Path(directory) / 'run'))
            case = instance.path / 'enabled'
            case.mkdir()
            proof = {'simulated': False, 'arm': 'enabled', 'successful_completion': True,
                     'http_requests': 1, 'response_id': 'the-stable-response', 'failed_worker': '1',
                     'continuation_workers': ['2'], 'finish_reasons': ['length'],
                     'client_recovery_gap_seconds': None, 'worker_attribution': 'correlated_frontend_trace_sse_sticky',
                     'migration_trace': {'retained_output_tokens': 31, 'lines': ['private verbose trace']},
                     'content': 'the generated module should remain in evidence',
                     'prefix_before_fault': 'the generated prefix should remain in evidence'}
            ui.write_json(case / 'proof.json', proof)
            saved = (case / 'proof.json').read_bytes()
            output = io.StringIO()
            with (mock.patch.object(instance, 'verify_case') as verify,
                  mock.patch.object(instance, 'inject') as inject,
                  contextlib.redirect_stdout(output)):
                instance.run_case('enabled')
            verify.assert_not_called()
            inject.assert_not_called()
            self.assertEqual((case / 'proof.json').read_bytes(), saved)
            self.assertIn('the-stable-response', output.getvalue())
            self.assertIn('31 tokens', output.getvalue())
            self.assertNotIn('private verbose trace', output.getvalue())
            self.assertNotIn('the generated module', output.getvalue())
            self.assertNotIn('the generated prefix', output.getvalue())


if __name__ == '__main__':
    unittest.main()
