"""Main-panel recording, mode boundaries, immutable attempts, and sanitization."""
from tests.support import ROOT
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.capture as capture


class CaptureTests(unittest.TestCase):
    def args(self, root, **kwargs):
        values = dict(demo='01-single-replica', run=Path(root) / 'run', output=Path(root) / 'attempt',
                      raw_output=Path(root) / 'private', rehearsal=True, quiet=True,
                      startup_timeout=60, capture_timeout=20, width=180, port=None)
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_intro_evidence_keeps_aiperf_receipts_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for name in ('demo.json', 'aiperf-c1.json', 'aiperf-c8-2.json', 'aiperf-c1/profile_export_aiperf.json',
                         'aiperf-c8-2/logs/aiperf.log', 'aiperf-notes.txt'):
                (run / name).parent.mkdir(parents=True, exist_ok=True)
                (run / name).write_text('{}')
            names = {str(p.relative_to(run)) for p in capture.evidence_files('01-single-replica', run)}
            self.assertEqual(names, {'demo.json', 'aiperf-c1.json', 'aiperf-c8-2.json',
                                     'aiperf-c1/profile_export_aiperf.json', 'aiperf-c8-2/logs/aiperf.log'})

    def test_cleared_screens_and_carriage_updates_are_preserved(self):
        raw = b'first\r\n\x1b[2J\x1b[Hsecond\rprogress 1\rprogress 2\r\n\x1b[32mREADY\x1b[0m\n'
        text = capture.plain_text(raw)
        self.assertEqual(text, 'first\nsecond\nprogress 1\nprogress 2\nREADY\n')
        self.assertNotIn('\x1b', capture.plain_text(b'\x1b]0;title\x07body\n'))

    def test_kvcr_capture_binds_preflight_to_measured_request_pair(self):
        from demos.kvcr.demo import object_sha256, prompt_preflight_proof
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            def write(name, value):
                path = run / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            requests = {role: {'messages': [{'role': 'user', 'content': role}],
                               'max_completion_tokens': 16} for role in ('source', 'target')}
            payload = {'model': 'fixture', 'revision': 'pinned', 'requests': requests}
            geometry = {role: {'effective_page_tokens': 4224, 'context_limit_tokens': 8192}
                        for role in ('a', 'b')}
            tokenized = {'model': 'fixture', 'revision': 'pinned', 'input_sha256': object_sha256(payload),
                         'request_sha256': {role: object_sha256(body) for role, body in requests.items()},
                         'source_prompt_tokens': 6500, 'target_prompt_tokens': 6510,
                         'common_prefix_tokens': 6400}
            proof = prompt_preflight_proof(payload, tokenized, geometry)
            proof.update(completed_at='2026-11-05T19:00:00+00:00', evidence_sha256={},
                         worker_pod_uids={'a': 'pod-a', 'b': 'pod-b'})
            write('prompt-preflight-input.json', payload)
            write('prompt-preflight.json', proof)
            write('ready-pods.json', {'items': [
                {'metadata': {'uid': 'pod-' + p, 'labels': {'kvcr-peer': p}}} for p in ('a', 'b')]})
            for role, body in requests.items():
                write(role + '/request.json', body)
                write(role + '/response.json', {'usage': {'prompt_tokens': proof[role + '_prompt_tokens']}})
            state = {'source_request_started_at': '2026-11-05T19:00:01+00:00',
                     'prompt_preflight_sha256': capture.sha256(run / 'prompt-preflight.json')}
            capture.validate_kvcr_preflight(run, state)
            for key, value in [('common_prefix_tokens', 3247), ('checked_before_source_request', False),
                               ('completed_at', '2026-11-05T19:00:02+00:00'),
                               ('worker_pod_uids', {'a': 'foreign', 'b': 'pod-b'})]:
                with self.subTest(key=key):
                    write('prompt-preflight.json', {**proof, key: value})
                    state['prompt_preflight_sha256'] = capture.sha256(run / 'prompt-preflight.json')
                    with self.assertRaises(ValueError):
                        capture.validate_kvcr_preflight(run, state)
            write('prompt-preflight.json', proof)
            state['prompt_preflight_sha256'] = capture.sha256(run / 'prompt-preflight.json')
            write('target/response.json', {'usage': {'prompt_tokens': 6509}})
            with self.assertRaises(ValueError):
                capture.validate_kvcr_preflight(run, state)

    def test_kvcr_speedup_capture_binds_preflight_to_every_measured_request(self):
        from demos.kvcr.demo import PAIRS, PROFILE, ROLES, object_sha256, speedup_preflight_proof
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            def write(name, value):
                path = run / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value))
            requests = {role: {'messages': [{'role': 'user', 'content': role}],
                               'max_completion_tokens': 32} for role in ROLES}
            payload = {'model': 'fixture', 'revision': 'pinned', 'requests': requests, 'pairs': PAIRS}
            geometry = {role: {'effective_page_tokens': 4224, 'context_limit_tokens': 65536} for role in ('a', 'b')}
            prompts = {'warmup_main': 9330, 'warmup_sub': 9340, 'main': 52030, 'control': 52050, 'sub': 52040}
            tokenized = {'model': 'fixture', 'revision': 'pinned', 'input_sha256': object_sha256(payload),
                         'request_sha256': {role: object_sha256(body) for role, body in requests.items()},
                         'prompt_tokens': prompts,
                         'common_prefix_tokens': {'main/sub': 52000, 'warmup_main/warmup_sub': 9300,
                                                  'control/sub': 12, 'control/main': 12}}
            proof = speedup_preflight_proof(payload, tokenized, geometry)
            proof.update(completed_at='2026-11-08T07:00:00+00:00', evidence_sha256={},
                         worker_pod_uids={'a': 'pod-a', 'b': 'pod-b'})
            write('prompt-preflight-input.json', payload)
            write('prompt-preflight.json', proof)
            write('ready-pods.json', {'items': [
                {'metadata': {'uid': 'pod-' + p, 'labels': {'kvcr-peer': p}}} for p in ('a', 'b')]})
            for role, body in requests.items():
                write(role + '/request.json', body)
                write(role + '/response.json', {'usage': {'prompt_tokens': prompts[role]}})
            state = {'kvcr_profile': PROFILE, 'warmup_main_started_at': '2026-11-08T07:00:01+00:00',
                     'prompt_preflight_sha256': capture.sha256(run / 'prompt-preflight.json')}
            capture.validate_kvcr_preflight(run, state)
            write('control/response.json', {'usage': {'prompt_tokens': 52049}})
            with self.assertRaisesRegex(ValueError, 'control'):
                capture.validate_kvcr_preflight(run, state)
            write('control/response.json', {'usage': {'prompt_tokens': prompts['control']}})
            state['warmup_main_started_at'] = '2026-11-08T06:59:59+00:00'
            with self.assertRaisesRegex(ValueError, 'precede'):
                capture.validate_kvcr_preflight(run, state)

    def test_common_credentials_are_removed_without_changing_nonsecret_metrics(self):
        text = ('HF_TOKEN=hf_' + 'a' * 20 + '\n"AWS_SECRET_ACCESS_KEY": "aws-secret"\n'
                'Authorization: Bearer bearer-secret\nname: NGC_API_KEY\n  value: another-secret\n'
                'max_tokens: 64\ncheckpoint: sha256:123\n')
        cleaned, changes = capture.sanitize(text)
        self.assertGreaterEqual(changes, 4)
        for secret in ('hf_' + 'a' * 20, 'aws-secret', 'bearer-secret', 'another-secret'):
            self.assertNotIn(secret, cleaned)
        self.assertIn('max_tokens: 64', cleaned)
        self.assertIn('checkpoint: sha256:123', cleaned)

    def test_all_rehearsals_capture_real_pty_output_but_never_live_file(self):
        for demo in (name for name in capture.DEMOS if name not in ('07-kvcr-prepared', capture.COMPOSED_SHADOW)):
            with self.subTest(demo=demo), tempfile.TemporaryDirectory() as root:
                args = self.args(root, demo=demo)
                self.assertEqual(capture.capture(args), 0)
                self.assertFalse((args.output / 'main.txt').exists())
                text = (args.output / 'rehearsal-main.txt').read_text()
                self.assertIn('NO CLUSTER CALLS', text)
                completion = {'06-routing': 'Recorded investigation complete.',
                              '09-agentx-metrics': 'Recorded metrics investigation complete.'}.get(demo, 'Demo complete.')
                self.assertIn(completion, text)
                self.assertNotIn('\x1b', text)
                meta = json.loads((args.output / 'capture.json').read_text())
                self.assertEqual(meta['status'], 'rehearsal_passed')
                self.assertEqual(meta['transcript_sha256'], capture.sha256(args.output / 'rehearsal-main.txt'))
                raw = args.raw_output / 'main-panel.ansi'
                self.assertIn(b'\x1b[2J\x1b[H', raw.read_bytes())
                self.assertEqual(raw.stat().st_mode & 0o777, 0o600)
                timeline = [json.loads(line) for line in (args.raw_output / 'timeline.jsonl').read_text().splitlines()]
                self.assertEqual(sum(e['bytes'] for e in timeline), raw.stat().st_size)
                self.assertTrue(all(e['offset'] == sum(v['bytes'] for v in timeline[:i]) for i, e in enumerate(timeline)))
                self.assertTrue(all('--plain' in meta['command'] and '--auto' in meta['command'] for _ in [0]))
                self.assertIn('capture_workshop_demo.py', meta['source_sha256'])
                self.assertIn('workshop_demo_support.py', meta['source_sha256'])
                self.assertEqual(meta['evidence_sha256']['demo.json'],
                                 capture.sha256(args.raw_output / 'evidence/demo.json'))
                if demo == '05-request-continuity':
                    self.assertIn('disabled/proof.json', meta['evidence_sha256'])
                    self.assertIn('enabled/proof.json', meta['evidence_sha256'])
                    saved = args.raw_output / 'evidence/enabled/proof.json'
                    original = saved.read_bytes()
                    (args.run / 'enabled/proof.json').write_text('{}')
                    self.assertEqual(saved.read_bytes(), original)
                    self.assertEqual(saved.stat().st_mode & 0o777, 0o400)

    def test_continuity_capture_requires_both_distinct_outcomes(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, demo='05-request-continuity')
            self.assertEqual(capture.capture(args), 0)
            proof = args.run / 'disabled/proof.json'
            value = json.loads(proof.read_text()); value['successful_completion'] = True
            proof.write_text(json.dumps(value))
            ok, reason = capture.completed(args.demo, args.run, True)
            self.assertFalse(ok, reason)

    def test_unprepared_recorded_capture_refuses_before_creating_attempt(self):
        for demo in ('06-routing', '09-agentx-metrics'):
            with self.subTest(demo=demo), tempfile.TemporaryDirectory() as directory:
                args = self.args(directory, demo=demo, rehearsal=False)
                with mock.patch.object(capture, 'record') as record:
                    with self.assertRaisesRegex(ValueError, 'Prepare the recorded walkthrough offstage'):
                        capture.capture(args)
                record.assert_not_called()
                self.assertFalse(args.output.exists())
                self.assertFalse(args.raw_output.exists())
                self.assertFalse(args.run.exists())

    def test_routing_playback_never_becomes_a_live_measurement(self):
        from demos.routing.demo import RoutingDemo, PROFILE, C16_PROFILE
        record = capture.record

        def record_native_demo(command, *arguments, **options):
            # Exercise actual recorded playback without changing the user's
            # prepared-run selection. Selection has its own CLI tests.
            self.assertEqual(command[2:5], ['-m', 'demos', 'routing'])
            native_command = command[:3] + ['demos.routing.demo'] + command[5:]
            return record(native_command, *arguments, **options)

        for profile, expected_profile, analysis_file in (
                (None, C16_PROFILE, 'analysis.json'),
                ('historical', PROFILE, 'policy-analysis.json')):
            with self.subTest(profile=profile or 'default-c16'), tempfile.TemporaryDirectory() as root:
                args = self.args(root, demo='06-routing', rehearsal=False)
                # Capture presents an explicitly prepared recording; it never
                # performs offstage validation in the projected walkthrough.
                demo = RoutingDemo(SimpleNamespace(run=args.run, rehearsal=False, recording_profile=profile,
                                                    action='prepare', preview=False, auto=True))
                demo.prepare()
                with mock.patch.object(capture, 'record', side_effect=record_native_demo):
                    self.assertEqual(capture.capture(args), 0)
                meta = json.loads((args.output / 'capture.json').read_text())
                self.assertEqual(meta['status'], 'recorded_evidence_passed')
                self.assertEqual(meta['mode'], 'recorded-evidence')
                self.assertEqual(meta['transcript'], 'recorded-main.txt')
                self.assertIn('No live deployment', meta['startup_scope'])
                self.assertFalse((args.output / 'main.txt').exists())
                recording = json.loads((args.run / 'recording/recording.json').read_text())
                self.assertEqual(recording['profile'], expected_profile)
                name = 'recording/' + analysis_file
                frozen = args.raw_output / 'evidence' / name
                original = frozen.read_bytes()
                self.assertEqual(meta['evidence_sha256'][name], capture.sha256(frozen))
                self.assertTrue(capture.completed(args.demo, args.run, False)[0])
                (args.run / name).write_text('{}')
                self.assertEqual(frozen.read_bytes(), original)
                self.assertFalse(capture.completed(args.demo, args.run, False)[0])

    def test_live_shadow_completion_requires_the_runs_own_locked_tp(self):
        proof = {'status': 'passed', 'new_standby_confirmed': True, 'tensor_parallel_size': 1,
                 'worker_before': {'decode_worker_id': 1}, 'worker_after': {'decode_worker_id': 2}}
        for locked, expected in ((1, True), (2, False), (None, False)):
            with self.subTest(locked=locked), tempfile.TemporaryDirectory() as root:
                run = Path(root)
                (run / 'demo.json').write_text(json.dumps({'rehearsal': False, 'step': 4, 'ready_observed_at': 'now'}))
                (run / 'recovery-proof.json').write_text(json.dumps(proof))
                if locked is not None:
                    (run / 'model-lock.json').write_text(json.dumps({'tensor_parallel_size': locked}))
                # Without a lock the check keeps its original Super VL TP2 expectation.
                self.assertEqual(capture.completed('08-shadow-engine', run, False)[0], expected)

    def test_mx_rehearsal_capture_freezes_target_and_simulated_source_binding(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, demo='02-modelexpress')
            self.assertEqual(capture.capture(args), 0)
            # The first replica is an illustrative existing record in rehearsal;
            # no separate storage worker or source manifest is launched.
            folder = args.run / 'arms/storage'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'record.json').write_text('{"simulated": true}\n')
            second = self.args(root, demo=args.demo, output=Path(root) / 'attempt-2',
                               raw_output=Path(root) / 'private-2')
            self.assertEqual(capture.capture(second), 0)
            saved = second.raw_output / 'evidence'
            for name in ('peer.yaml', 'deployment.yaml', 'gpu-claim-template.yaml',
                         'source-binding.json', 'modelexpress-settings.yaml', 'arms/storage/record.json'):
                self.assertTrue((saved / name).is_file(), name)
                self.assertEqual((saved / name).read_bytes(), (args.run / name).read_bytes())
            self.assertIsNone(json.loads((saved / 'source-binding.json').read_text()))
            self.assertFalse((saved / 'source-intro').exists())
            self.assertFalse((saved / 'native.yaml').exists())
            self.assertFalse((saved / 'source.yaml').exists())
            previous = (saved / 'peer.yaml').read_bytes()
            (args.run / 'peer.yaml').write_text('changed after capture')
            self.assertEqual((saved / 'peer.yaml').read_bytes(), previous)

    def test_mx_capture_seals_bound_intro_evidence_before_peer_recording(self):
        from demos.modelexpress import source
        from tests.modelexpress.test_source import SourceFixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / 'intro'
            parent.mkdir()
            SourceFixture(parent)
            (parent / 'allocation.json').write_text('{"assignment_id":"capture-fixture"}\n')
            binding = source.snapshot(parent)
            args = self.args(root, demo='02-modelexpress', rehearsal=False)
            args.run.mkdir()
            (args.run / 'source-binding.json').write_text(json.dumps(binding))
            state = {'rehearsal': False, 'source_binding': binding, 'arms': {'storage': binding['baseline']},
                     'mx_inputs': {'source-binding.json': capture.sha256(args.run / 'source-binding.json')}}
            (args.run / 'demo.json').write_text(json.dumps(state))
            original = {name: (parent / name).read_bytes() for name in binding['inputs']}
            record = capture.record

            def record_peer(*arguments, **options):
                # Parent changes after capture's validated preflight must not
                # replace the exact first startup that the child was bound to.
                (parent / 'worker.log').write_text('changed after preflight\n')
                return record([sys.executable, '-c', 'print("peer recording fixture")'],
                              arguments[1], **options)

            with mock.patch.object(capture, 'record', side_effect=record_peer), \
                    mock.patch.object(capture, 'completed', return_value=(True, 'fixture completion')):
                self.assertEqual(capture.capture(args), 0)
            meta = json.loads((args.output / 'capture.json').read_text())
            self.assertEqual(meta['startup_arms_before'], ['storage'])
            self.assertIn('pre-existing evidence from demo 1', meta['startup_scope'])
            self.assertIn('Peer-arm startup begins', meta['startup_scope'])
            provenance = meta['startup_provenance']
            self.assertEqual(provenance['source_run'], str(parent.resolve()))
            self.assertFalse(provenance['startup_measured_in_capture'])
            self.assertEqual(provenance['source_binding_sha256'], capture.sha256(args.run / 'source-binding.json'))
            saved = args.raw_output / 'evidence/source-intro'
            for name, data in original.items():
                self.assertEqual((saved / name).read_bytes(), data)
                self.assertEqual((saved / name).stat().st_mode & 0o777, 0o400)
                self.assertEqual(meta['evidence_sha256']['source-intro/' + name], binding['inputs'][name])

    def test_mx_capture_refuses_bound_source_drift_before_recording(self):
        from demos.modelexpress import source
        from tests.modelexpress.test_source import SourceFixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / 'intro'
            parent.mkdir()
            SourceFixture(parent)
            binding = source.snapshot(parent)
            args = self.args(root, demo='02-modelexpress', rehearsal=False)
            args.run.mkdir()
            (args.run / 'source-binding.json').write_text(json.dumps(binding))
            (args.run / 'demo.json').write_text(json.dumps({
                'rehearsal': False, 'source_binding': binding,
                'mx_inputs': {'source-binding.json': capture.sha256(args.run / 'source-binding.json')}}))
            (parent / 'worker.log').write_text('unbound replacement log')
            with mock.patch.object(capture, 'record') as record, \
                    self.assertRaisesRegex(ValueError, 'first-replica evidence changed'):
                capture.capture(args)
            record.assert_not_called()
            self.assertFalse(args.output.exists())

    def test_existing_attempt_is_never_overwritten_or_executed(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            args.output.mkdir()
            (args.output / 'existing.txt').write_text('keep')
            with mock.patch.object(capture, 'record') as record, self.assertRaises(ValueError):
                capture.capture(args)
            record.assert_not_called()
            self.assertEqual((args.output / 'existing.txt').read_text(), 'keep')

    def test_historical_nonempty_directory_cannot_become_demo_run(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            args.run.mkdir()
            (args.run / 'state.json').write_text('{}')
            with mock.patch.object(capture, 'record') as record, self.assertRaises(ValueError):
                capture.capture(args)
            record.assert_not_called()

    def test_mode_mismatch_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, rehearsal=False)
            args.run.mkdir()
            (args.run / 'demo.json').write_text('{"rehearsal": true}')
            with mock.patch.object(capture, 'record') as record, self.assertRaises(ValueError):
                capture.capture(args)
            record.assert_not_called()

    def test_failed_capture_has_no_success_main_and_retains_output(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            args.raw_output.mkdir()
            # Let record create its own directory, with an actual failing process.
            args.raw_output.rmdir()
            original = capture.record
            def fail(command, raw_directory, **kwargs):
                return original([sys.executable, '-c', 'print("actual failure output"); raise SystemExit(7)'],
                                raw_directory, **kwargs)
            with mock.patch.object(capture, 'record', side_effect=fail):
                self.assertEqual(capture.capture(args), 7)
            self.assertEqual(json.loads((args.output / 'capture.json').read_text())['status'], 'failed')
            self.assertIn('actual failure output', (args.output / 'failed-main.txt').read_text())
            self.assertFalse((args.output / 'main.txt').exists())
            self.assertTrue((args.raw_output / 'main-panel.ansi').exists())

    def test_preexisting_startup_is_not_labeled_new_measurement(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            self.assertEqual(capture.capture(args), 0)
            second = self.args(root, output=Path(root) / 'attempt-2', raw_output=Path(root) / 'private-2')
            self.assertEqual(capture.capture(second), 0)
            meta = json.loads((second.output / 'capture.json').read_text())
            self.assertTrue(meta['preexisting_startup'])
            self.assertIn('not a new startup measurement', meta['startup_scope'])
            self.assertTrue((second.raw_output / 'demo-before.json').exists())

    def test_offstage_snapshot_prime_is_labeled_preexisting_startup(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, demo='04-snapshot-dgd')
            self.assertEqual(capture.capture(args), 0)
            second = self.args(root, demo=args.demo, output=Path(root) / 'attempt-2', raw_output=Path(root) / 'private-2')
            self.assertEqual(capture.capture(second), 0)
            meta = json.loads((second.output / 'capture.json').read_text())
            self.assertTrue(meta['preexisting_startup'])
            self.assertIn('Pre-existing startup', meta['startup_scope'])

    def test_mx_offstage_prime_does_not_mislabel_new_peer_startup(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root, demo='02-modelexpress')
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'modelexpress',
                'prime', '--rehearsal', '--auto', '--run', str(args.run)], cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(capture.capture(args), 0)
            meta = json.loads((args.output / 'capture.json').read_text())
            self.assertTrue(meta['preexisting_startup'])
            self.assertEqual(meta['startup_arms_before'], ['storage'])
            self.assertIn('Peer-arm startup begins during this recording', meta['startup_scope'])
            self.assertNotIn('recording is not a new startup measurement', meta['startup_scope'])

    def test_cleanup_mutation_cannot_change_saved_capture_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            args = self.args(root)
            self.assertEqual(capture.capture(args), 0)
            meta = json.loads((args.output / 'capture.json').read_text())
            saved = args.raw_output / 'evidence/demo.json'
            original = saved.read_bytes()
            state = json.loads((args.run / 'demo.json').read_text())
            state['cleaned_at'] = 'later cleanup'
            (args.run / 'demo.json').write_text(json.dumps(state))
            self.assertEqual(saved.read_bytes(), original)
            self.assertNotEqual(capture.sha256(saved), capture.sha256(args.run / 'demo.json'))
            self.assertEqual(meta['evidence_sha256']['demo.json'], capture.sha256(saved))
            self.assertEqual(saved.stat().st_mode & 0o777, 0o400)

    def test_sources_are_copied_before_the_recorded_child_can_change_them(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'source.py'
            source.write_text('original source\n')
            result = capture.record([sys.executable, '-c',
                                     'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("changed by child\\n")',
                                     str(source)], root / 'raw', mirror=False, timeout=10, source_files=[source])
            saved = root / 'raw/sources/source.py'
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(saved.read_text(), 'original source\n')
            self.assertEqual(source.read_text(), 'changed by child\n')
            self.assertEqual(result['source_sha256']['source.py'], capture.sha256(saved))
            self.assertEqual(saved.stat().st_mode & 0o777, 0o400)


if __name__ == '__main__':
    unittest.main()
