"""Pinned metric semantics and read-only AgentX metrics presenter checks."""
from tests.support import ROOT
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.metrics.demo as metrics
import demos.routing.demo as routing


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18009, timeout=60)


class MetricsTests(unittest.TestCase):
    def test_measured_values_and_exact_definitions(self):
        definitions = ui.read_json(metrics.DEFINITIONS)
        value, config, _ = metrics.validated_metrics(routing.BUNDLE, definitions)
        self.assertEqual(value['requests'], 122)
        self.assertEqual(value['request_errors'], 0)
        self.assertEqual(value['agent_tree_concurrency'], 4)
        self.assertEqual(value['h100_gpus'], 2)
        self.assertAlmostEqual(value['canonical_output_tokens_per_second_per_gpu'], 40.58078354734011)
        self.assertAlmostEqual(value['canonical_rate_denominator_seconds'], 1200.001472204)
        self.assertAlmostEqual(value['observed_request_span_seconds'], 902.686032896)
        self.assertFalse(config['endpoint'].get('per_chunk_usage', False))
        check = definitions['record_formula_check']
        self.assertEqual(check['records'], 122)
        self.assertEqual(check['formula_mismatches'], 0)
        self.assertEqual(len(definitions['source_files_sha256']), 8)
        self.assertAlmostEqual(value['mean_per_request_decode_tokens_per_second'], check['mean_per_request_rate'])
        self.assertNotAlmostEqual(check['mean_per_request_rate'], check['inverse_mean_itl_tokens_per_second'])

    def test_different_definition_version_refused(self):
        definitions = ui.read_json(metrics.DEFINITIONS)
        definitions['aiperf_commit'] = 'wrong-source'
        with self.assertRaisesRegex(ValueError, 'definitions do not match'):
            metrics.validated_metrics(routing.BUNDLE, definitions)

    def test_walkthrough_runs_only_local_reads_and_keeps_bounded_output(self):
        with tempfile.TemporaryDirectory() as d:
            lease = Path(d) / 'lease'
            lease.mkdir()
            (lease / 'owner.json').write_text('other-owner')
            with mock.patch.object(ui, 'LEASE', lease):
                demo = metrics.MetricsDemo(args(Path(d) / 'run'))
                with mock.patch.object(demo.run, 'k', side_effect=AssertionError('No cluster calls')):
                    with contextlib.redirect_stdout(io.StringIO()) as out:
                        demo.guided()
                        demo.cleanup()
            self.assertEqual((lease / 'owner.json').read_text(), 'other-owner')
            self.assertEqual(demo.data['step'], 3)
            self.assertIn('completed_at', demo.data)
            self.assertEqual(len(list(demo.path.glob('command-*.json'))), 3)
            self.assertTrue(all(ui.read_json(p)['args'][0] == 'cat' for p in demo.path.glob('command-*.json')))
            self.assertIn('NO CLUSTER CALLS', out.getvalue())
            self.assertNotIn('Enter or Space', out.getvalue())
            for offstage in ('Historical exports, metric definitions', 'Commands shown relative', 'Step finished in'):
                self.assertNotIn(offstage, out.getvalue())
            for name in ('workload.txt', 'user-metrics.txt', 'service-metrics.txt'):
                lines = (demo.path / name).read_text().splitlines()
                self.assertLessEqual(len(lines), 25)
                self.assertLessEqual(max(map(len, lines)), 80)

    def test_live_run_requires_offstage_preparation_before_opening_layout(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recording with spaces'
            with mock.patch.object(sys, 'argv', ['metrics', '--run', str(path)]), \
                    mock.patch.object(ui, 'tmux_layout') as layout, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaisesRegex(RuntimeError, '-m demos metrics prepare --run'):
                    metrics.main()
            layout.assert_not_called()
            self.assertNotIn('Dynamo workshop', out.getvalue())
            self.assertFalse(ui.read_json(path / 'demo.json')['prepared'])

    def test_prepared_live_playback_preserves_verified_inputs_without_preparing_again(self):
        with tempfile.TemporaryDirectory() as d:
            options = args(Path(d) / 'run')
            options.rehearsal = False
            demo = metrics.MetricsDemo(options)
            with contextlib.redirect_stdout(io.StringIO()):
                demo.prepare()
            original = {name: ui.digest(demo.path / name) for name in demo.data['inputs_sha256']}
            with mock.patch.object(demo, 'prepare', side_effect=AssertionError('Preparation is offstage')), \
                    mock.patch.object(demo.run, 'k', side_effect=AssertionError('No cluster calls')), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                demo.guided()
            self.assertEqual(original, {name: ui.digest(demo.path / name) for name in original})
            self.assertIn('RECORDED EVIDENCE / NO CLUSTER CALLS', out.getvalue())
            self.assertNotIn('Historical exports, metric definitions', out.getvalue())

    def test_observers_do_not_mutate_run_and_changed_proof_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            demo = metrics.MetricsDemo(args(Path(d) / 'run'))
            original = demo.file.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                metrics.observe(demo.path, 'resources', once=True)
                metrics.observe(demo.path, 'logs', once=True)
            self.assertEqual(demo.file.read_bytes(), original)
            proof = ui.read_json(demo.path / 'metrics-proof.json')
            proof['canonical_output_tokens_per_second_per_gpu'] *= 10
            ui.write_json(demo.path / 'metrics-proof.json', proof)
            with self.assertRaisesRegex(ValueError, 'Prepared metrics changed'):
                demo.prepare()

    def test_real_cli(self):
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'metrics', '--rehearsal',
                '--plain', '--auto', '--run', str(Path(d) / 'with spaces')], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Recorded metrics investigation complete', result.stdout)
            self.assertEqual(result.stdout.count('$ cat'), 3)


if __name__ == '__main__':
    unittest.main()
