"""Prepared KVCR capture: offstage provenance, request gates, immutable evidence."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.capture as capture
import demos.common.runtime as ui
import demos.kvcr.demo as base
import demos.kvcr.prepared as prepared
from tests.kvcr.test_prepared import Fixture


def completed_fixture(folder):
    """Synthetic unit-test evidence; no cluster/runtime measurement is performed."""
    f = Fixture(folder)
    repair = f.repair()
    child = Path(folder) / 'child'
    prepared.bind(repair, child)
    payload = ui.read_json(child / 'prompt-preflight-input.json')
    tokenized = {'model': payload['model'], 'revision': payload['revision'], 'input_sha256': base.object_sha256(payload),
                 'request_sha256': {r: base.object_sha256(b) for r, b in payload['requests'].items()},
                 'source_prompt_tokens': 6467, 'target_prompt_tokens': 6468, 'common_prefix_tokens': 6453}
    proof = base.prompt_preflight_proof(payload, tokenized, f.geometry)
    proof.update(completed_at='2026-11-05T21:01:00+00:00', evidence_sha256={},
                 worker_pod_uids={r: f.selected['pods'][r]['metadata']['uid'] for r in ('a', 'b')})
    ui.write_json(child / 'prompt-preflight.json', proof)
    for role, peer in (('source', 'a'), ('target', 'b')):
        path = child / role; path.mkdir()
        ui.write_json(path / 'request.json', payload['requests'][role])
        ui.write_json(path / 'response.json', {'http_requests': 1, 'status': 200, 'workers': [f.selected['worker_ids'][peer]],
            'usage': {'prompt_tokens': proof[role + '_prompt_tokens']}, 'content': 'READY'})
    ui.write_json(child / 'response.json', ui.read_json(child / 'target/response.json'))
    ui.write_json(child / 'peer-proof.json', {'status': 'passed', 'simulated': False, 'blocks': 6, 'bytes': 103809024,
        'external_cache_tokens': 4224, 'cached_prompt_tokens': 4224, 'matched_transfers': [{'source': 'fixture', 'target': 'fixture'}],
        'source_workers': ['808'], 'target_workers': ['910']})
    for name, at in (('admission-source', '2026-11-05T21:01:59+00:00'), ('admission-target', '2026-11-05T21:03:59+00:00')):
        path = child / name; path.mkdir()
        ui.write_json(path / 'snapshot.json', {**f.selected, 'completed_at': at})
        (path / 'a-main.log').write_text('Synthetic cached worker log\n')
    state = ui.read_json(child / 'demo.json')
    state.update(step=5, prompt_preflight_sha256=capture.sha256(child / 'prompt-preflight.json'),
                 source_request_started_at='2026-11-05T21:02:00+00:00', source_completed_at='2026-11-05T21:03:00+00:00',
                 target_request_started_at='2026-11-05T21:04:00+00:00', target_completed_at='2026-11-05T21:05:00+00:00')
    ui.write_json(child / 'demo.json', state)
    return f, child, state


class PreparedCaptureTests(unittest.TestCase):
    def args(self, folder, run, **changes):
        result = dict(demo='07-kvcr-prepared', run=run, output=Path(folder) / 'attempt', raw_output=Path(folder) / 'raw',
                      rehearsal=False, quiet=True, startup_timeout=60, capture_timeout=10, width=180, port=None)
        result.update(changes)
        return SimpleNamespace(**result)

    def test_prepared_mapping_reuses_kvcr_completion_and_exact_preflight_guards(self):
        self.assertEqual(capture.DEMOS['07-kvcr-prepared'].module, 'demos.kvcr.prepared')
        with tempfile.TemporaryDirectory() as folder:
            _, child, _ = completed_fixture(folder)
            self.assertTrue(capture.completed('07-kvcr-prepared', child, False)[0])
            proof = ui.read_json(child / 'peer-proof.json'); proof['external_cache_tokens'] = 0; ui.write_json(child / 'peer-proof.json', proof)
            self.assertFalse(capture.completed('07-kvcr-prepared', child, False)[0])
        with tempfile.TemporaryDirectory() as folder:
            _, child, _ = completed_fixture(folder)
            response = ui.read_json(child / 'target/response.json'); response['usage']['prompt_tokens'] -= 1
            ui.write_json(child / 'target/response.json', response)
            self.assertFalse(capture.completed('07-kvcr-prepared', child, False)[0])

    def test_admission_must_cover_both_http_requests_and_bound_worker_ids(self):
        for change in ('one_worker', 'stale_uid', 'late_gate', 'wrong_worker', 'no_target_gate'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                f, child, _ = completed_fixture(folder)
                path = child / 'admission-target/snapshot.json'
                value = ui.read_json(path)
                if change == 'one_worker':
                    value['frontend_readiness']['body']['namespaces'][f.dyn_ns]['worker_types']['aggregated']['workers'] = 1
                elif change == 'stale_uid': value['pods']['b']['metadata']['uid'] = 'unbound-b'
                elif change == 'late_gate': value['completed_at'] = '2026-11-05T21:04:01+00:00'
                elif change == 'wrong_worker':
                    response = ui.read_json(child / 'target/response.json'); response['workers'] = ['909']
                    ui.write_json(child / 'target/response.json', response)
                elif change == 'no_target_gate': path.unlink()
                if path.exists(): ui.write_json(path, value)
                ok, reason = capture.completed('07-kvcr-prepared', child, False)
                self.assertFalse(ok, reason)

    def test_recording_labels_parent_startup_and_archives_portable_repair_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            f, child, state = completed_fixture(folder)
            args = self.args(folder, child)
            self.assertNotIn('apply_started_at', state)
            actual_record = capture.record
            def record(command, raw_directory, **kwargs):
                self.assertEqual(command[2:5], ['-m', 'demos', 'kvcr-prepared'])
                self.assertNotIn('--rehearsal', command)
                return actual_record([sys.executable, '-c', 'print("Synthetic main panel for a local capture test")'], raw_directory, **kwargs)
            with mock.patch.object(capture, 'record', side_effect=record): self.assertEqual(capture.capture(args), 0)
            metadata = ui.read_json(args.output / 'capture.json')
            self.assertEqual(metadata['status'], 'live_passed')  # Fixture exercises this classification; no live work ran.
            self.assertTrue(metadata['preexisting_startup'])
            self.assertIn('prepared offstage', metadata['startup_scope'])
            self.assertFalse(metadata['startup_provenance']['startup_measured_in_capture'])
            self.assertEqual(metadata['startup_provenance']['parent_run'], str(f.parent.resolve()))
            self.assertEqual(metadata['startup_provenance']['retained_source_uid'], 'a-old')
            for name in ('prepared-binding.json', 'prepared-parent/repair.json', 'prepared-parent/plan.json',
                         'prepared-parent/snapshot.json', 'admission-source/snapshot.json', 'admission-target/a-main.log'):
                path = args.raw_output / 'evidence' / name
                self.assertTrue(path.exists(), name)
                self.assertEqual(metadata['evidence_sha256'][name], capture.sha256(path))
                self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            frozen = (args.raw_output / 'evidence/prepared-parent/repair.json').read_bytes()
            shutil.rmtree(f.parent); shutil.rmtree(f.reset); shutil.rmtree(f.lease)
            self.assertEqual((args.raw_output / 'evidence/prepared-parent/repair.json').read_bytes(), frozen)
            self.assertTrue(capture.completed('07-kvcr-prepared', args.raw_output / 'evidence', False)[0])

    def test_missing_binding_rehearsal_or_tampered_repair_stops_before_execution(self):
        for change in ('missing_binding', 'rehearsal', 'repair'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                f, child, _ = completed_fixture(folder)
                if change == 'missing_binding': (child / 'prepared-binding.json').unlink()
                elif change == 'repair': (f.reset / 'repair.json').write_text('{}')
                args = self.args(folder, child, rehearsal=change == 'rehearsal')
                with mock.patch.object(capture, 'record') as record, self.assertRaises((ValueError, OSError)):
                    capture.capture(args)
                record.assert_not_called()
                self.assertFalse(args.output.exists())


if __name__ == '__main__':
    unittest.main()
