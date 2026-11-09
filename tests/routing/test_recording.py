"""C16 evidence qualification, presenter default and historical replay compatibility."""
from tests.support import ROOT
import contextlib
import copy
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.metrics.demo as metrics
import demos.routing.demo as routing
import demos.routing.recording as c16


def args(path, profile=None):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
                           auto=True, plain=True, port=18006, timeout=60, recording_profile=profile)


class C16Tests(unittest.TestCase):
    def test_all_three_actual_cells_and_same_load_pairings_are_valid(self):
        metadata, studies, _, _, discovery = routing.load_recording(c16.BUNDLE)
        self.assertEqual(metadata['profile'], c16.PROFILE)
        self.assertEqual(metadata['import_verification']['transport_files_rechecked'], 1040)
        self.assertEqual(metadata['import_verification']['frozen_payload_members_rechecked'], 47)
        self.assertEqual([row['requests'] for row in studies['scaleout']['arms']], [303, 316])
        self.assertEqual([row['requests'] for row in studies['policy']['arms']], [316, 311])
        self.assertEqual(studies['scaleout']['concurrency_session_trees'], 16)
        self.assertEqual(studies['policy']['concurrency_session_trees'], 16)
        self.assertEqual(discovery['kv_event_source_hosts'], ['192.168.100.28', '192.168.98.146'])
        historical = routing.load_recording(routing.BUNDLE)[-1]
        self.assertNotEqual(discovery['frontend_uid'], historical['frontend_uid'])
        self.assertNotEqual(discovery['kv_event_source_hosts'], historical['kv_event_source_hosts'])

    def test_analysis_export_mismatch_cannot_be_accepted(self):
        _, studies, _, _, _ = routing.load_recording(c16.BUNDLE)
        row = copy.deepcopy(studies['policy']['arms'][1])
        raw = ui.read_json(c16.BUNDLE / 'cells/two-kv-c16-a1/aiperf.json')
        row['ttft_p99_ms'] /= 10
        with self.assertRaisesRegex(ValueError, 'analysis/export mismatch'):
            c16.validate_export(row, raw)

    def test_missing_or_rehashed_changed_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recording'
            shutil.copytree(c16.BUNDLE, path)
            metadata = ui.read_json(path / 'recording.json')
            original = copy.deepcopy(metadata)
            metadata['files_sha256'].pop('cells/two-rr-c16-a1/aiperf.json')
            ui.write_json(path / 'recording.json', metadata)
            with self.assertRaisesRegex(ValueError, 'inventory'):
                routing.load_recording(path)
            manifest = ui.read_json(path / 'policy-kv-deployment.json')
            worker = routing.component(manifest, 'worker')['podTemplate']['spec']['containers'][0]
            worker['args'][worker['args'].index('--max-num-seqs') + 1] = '4'
            ui.write_json(path / 'policy-kv-deployment.json', manifest)
            original['files_sha256']['policy-kv-deployment.json'] = ui.digest(path / 'policy-kv-deployment.json')
            ui.write_json(path / 'recording.json', original)
            with self.assertRaisesRegex(ValueError, 'effective worker arguments differ'):
                routing.load_recording(path)

    def test_current_pod_ips_are_checked_against_actual_event_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'recording'
            shutil.copytree(c16.BUNDLE, path)
            analysis = ui.read_json(path / 'analysis.json')
            row = next(cell['metrics'] for cell in analysis['cells'] if cell['arm'] == c16.ARMS[2])
            pods_path = path / 'cells/two-kv-c16-a1/pod-identities.json'
            pods = ui.read_json(pods_path)
            name = row['spec']['worker_pods'][0]['name']
            next(p for p in pods['items'] if p['metadata']['name'] == name)['status']['podIP'] = '192.0.2.99'
            ui.write_json(pods_path, pods)
            manifest = ui.read_json(path / 'policy-kv-deployment.json')
            with self.assertRaisesRegex(ValueError, 'discovery does not match current Pods'):
                c16.validate_identity(path, c16.ARMS[2], row, row['spec'], manifest, analysis['campaign'])

    def test_default_presenter_uses_c16_without_cluster_calls(self):
        with tempfile.TemporaryDirectory() as d:
            demo = routing.RoutingDemo(args(Path(d) / 'run'))
            self.assertEqual(demo.data['routing_profile'], c16.PROFILE)
            with mock.patch.object(demo.run, 'k', side_effect=AssertionError('Cluster calls forbidden')):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    demo.guided()
            self.assertIn('18.6%', out.getvalue())
            self.assertIn('No saturation curve', out.getvalue())
            self.assertNotIn('DIFFERENT drain-inclusive denominators', out.getvalue())
            self.assertEqual(ui.read_json(demo.path / 'comparison.json')['measurement_class'], 'fixed-order-c16-observation')
            self.assertTrue((demo.path / 'realized-mix.json').exists())
            self.assertTrue((demo.path / 'pressure-proof.json').exists())
            self.assertEqual(ui.read_json(demo.path / 'realized-mix.json')['two-kv-c16-a1']['requests'], 311)
            for name in ('scaleout-summary.txt', 'policy-summary.txt'):
                lines = (demo.path / name).read_text().splitlines()
                self.assertLessEqual(len(lines), 27)
                self.assertLessEqual(max(map(len, lines)), 80)

    def test_old_run_and_metrics09_stay_on_original_frozen_sources(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / 'historical'
            demo = routing.RoutingDemo(args(run, 'historical'))
            self.assertEqual(demo.data['routing_profile'], routing.PROFILE)
            resumed = routing.RoutingDemo(args(run))
            self.assertEqual(resumed.data['routing_profile'], routing.PROFILE)
            with self.assertRaisesRegex(ValueError, 'choice differs'):
                routing.RoutingDemo(args(run, 'c16'))
            primer = metrics.MetricsDemo(args(Path(d) / 'metrics09'))
            self.assertEqual(ui.read_json(primer.path / 'metrics-proof.json')['requests'], 122)
            self.assertEqual(ui.read_json(primer.path / 'recording/recording.json')['profile'], routing.PROFILE)

    def test_actual_c16_cli(self):
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'routing', '--rehearsal',
                '--plain', '--auto', '--run', str(Path(d) / 'path with spaces')], cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('AgentX C16', result.stdout)
            self.assertIn('Recorded investigation complete.', result.stdout)
            self.assertEqual(result.stdout.count('$ cat'), 5)


if __name__ == '__main__':
    unittest.main()
