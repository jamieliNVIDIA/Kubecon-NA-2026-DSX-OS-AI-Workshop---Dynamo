"""Evidence boundaries and offline presenter behavior for recorded AgentX routing."""
from tests.support import ROOT
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.routing.demo as routing


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18006, timeout=60, recording_profile='historical')


class RecordingTests(unittest.TestCase):
    def test_committed_recording_validates_actual_exports_and_keeps_studies_separate(self):
        metadata, studies, _, _, discovery = routing.load_recording(routing.BUNDLE)
        self.assertEqual(metadata['measurement_class'], 'historical-low-load-pilots')
        self.assertEqual(studies['scaleout']['concurrency_session_trees'], 4)
        self.assertEqual(studies['policy']['concurrency_session_trees'], 1)
        self.assertEqual([r['requests'] for r in studies['scaleout']['arms']], [122, 114])
        self.assertEqual([r['requests'] for r in studies['policy']['arms']], [81, 84])
        self.assertEqual(len(discovery['kv_event_source_hosts']), 2)

    def test_tampered_file_missing_hash_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recording'
            shutil.copytree(routing.BUNDLE, path)
            metadata = ui.read_json(path / 'recording.json')
            (path / 'policy-analysis.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                routing.load_recording(path)
            metadata['files_sha256'].pop('policy-analysis.json')
            ui.write_json(path / 'recording.json', metadata)
            with self.assertRaisesRegex(ValueError, 'inventory'):
                routing.load_recording(path)
            for name in ('../outside', '/tmp/outside'):
                with self.assertRaisesRegex(ValueError, 'escapes'):
                    routing.relative_file(path, name)

    def test_rehashed_wrong_numbers_still_fail_export_check(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recording'
            shutil.copytree(routing.BUNDLE, path)
            value = ui.read_json(path / 'policy-analysis.json')
            value['arms'][1]['ttft_p50_ms'] = 1
            ui.write_json(path / 'policy-analysis.json', value)
            metadata = ui.read_json(path / 'recording.json')
            metadata['files_sha256']['policy-analysis.json'] = ui.digest(path / 'policy-analysis.json')
            ui.write_json(path / 'recording.json', metadata)
            with self.assertRaisesRegex(ValueError, 'differs from AIPerf'):
                routing.load_recording(path)

    def test_policy_cannot_change_worker_controls_or_omit_overlap(self):
        _, studies, _, _, _ = routing.load_recording(routing.BUNDLE)
        value = copy.deepcopy(studies['policy'])
        value['arms'][1]['spec']['max_num_seqs_per_worker'] = 128
        with self.assertRaisesRegex(ValueError, 'controls differ'):
            routing.validate_study(value, 'routing', 1)
        value = copy.deepcopy(studies['policy'])
        value['arms'][1]['predicted_kv_hit_histogram_sum'] = 0
        with self.assertRaisesRegex(ValueError, 'prefix-overlap'):
            routing.validate_study(value, 'routing', 1)

    def test_manifest_excerpt_comes_from_real_measured_paths(self):
        _, _, _, kv, _ = routing.load_recording(routing.BUNDLE)
        text = routing.settings_excerpt(kv)
        self.assertIn('- --router-mode\n', text)
        self.assertIn('- kv\n', text)
        self.assertIn('--kv-events-config', text)
        self.assertIn('enable_kv_cache_events', text)
        self.assertLessEqual(len(text.splitlines()), 38)
        self.assertLessEqual(max(map(len, text.splitlines())), 80)


class PresenterTests(unittest.TestCase):
    def test_unprepared_live_run_refuses_before_walkthrough_or_layout(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'unprepared'
            live = args(path)
            live.rehearsal = False
            demo = routing.RoutingDemo(live)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaisesRegex(RuntimeError, '-m demos routing prepare --run'):
                    demo.guided()
            self.assertNotIn('Scaling and routing', out.getvalue())
            self.assertFalse(ui.read_json(demo.file)['prepared'])
            with mock.patch.object(sys, 'argv', ['routing', '--run', str(path)]), \
                    mock.patch.object(ui, 'tmux_layout') as layout, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'Prepare this run offstage'):
                    routing.main()
            layout.assert_not_called()

    def test_prepared_playback_rechecks_evidence_without_onstage_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            live = args(Path(d) / 'prepared')
            live.rehearsal = False
            demo = routing.RoutingDemo(live)
            with contextlib.redirect_stdout(io.StringIO()):
                demo.prepare()
            with mock.patch.object(demo, 'prepare', side_effect=AssertionError('Preparation belongs offstage')), \
                    mock.patch.object(demo.run, 'k', side_effect=AssertionError('Cluster calls forbidden')), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                demo.guided()
            text = out.getvalue()
            self.assertIn('RECORDED EVIDENCE / NO CLUSTER CALLS', text)
            self.assertIn('$ cat scaleout-summary.txt', text)
            self.assertNotIn('Recording hashes and paired controls verified', text)
            self.assertNotIn('Commands shown relative', text)
            self.assertNotIn('Step finished in', text)
            self.assertEqual(ui.read_json(demo.file)['step'], len(demo.steps))

    def test_full_walkthrough_only_runs_cats_and_does_not_touch_lease(self):
        with tempfile.TemporaryDirectory() as d:
            lease = Path(d) / 'foreign-lease'
            lease.mkdir()
            owner = b'{"agent":"other-chat","run":"/preserve"}'
            (lease / 'owner.json').write_bytes(owner)
            with mock.patch.object(ui, 'LEASE', lease):
                demo = routing.RoutingDemo(args(Path(d) / 'demo'))
                with mock.patch.object(demo.run, 'k', side_effect=AssertionError('Cluster calls forbidden')):
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        demo.guided()
                        demo.cleanup()
            self.assertEqual((lease / 'owner.json').read_bytes(), owner)
            self.assertIn('RECORDED EVIDENCE / NO CLUSTER CALLS', output.getvalue())
            self.assertIn('DIFFERENT drain-inclusive denominators', output.getvalue())
            self.assertNotIn('Enter or Space', output.getvalue())
            self.assertEqual(ui.read_json(demo.file)['step'], 4)
            self.assertIn('completed_at', ui.read_json(demo.file))
            self.assertTrue(all(ui.read_json(p)['args'][0] == 'cat' for p in demo.path.glob('command-*.json')))

    def test_prepared_recording_is_frozen_and_observer_is_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            demo = routing.RoutingDemo(args(Path(d) / 'demo'))
            original = demo.file.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                routing.observe(demo.path, 'resources', once=True)
                routing.observe(demo.path, 'logs', once=True)
            self.assertEqual(demo.file.read_bytes(), original)
            (demo.path / 'policy-summary.txt').write_text('fake results')
            with self.assertRaisesRegex(ValueError, 'Prepared recording changed'):
                demo.prepare()

    def test_launcher_and_real_cli_rehearsal(self):
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'routing', '--rehearsal',
                '--plain', '--auto', '--run', str(Path(d) / 'path with spaces')], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('No cluster resources were created', result.stdout)
            self.assertIn('$ cat scaleout-summary.txt', result.stdout)
            self.assertIn('$ cat routing-settings.yaml', result.stdout)
            self.assertEqual(result.stdout.count('$ cat'), 5)


if __name__ == '__main__':
    unittest.main()
