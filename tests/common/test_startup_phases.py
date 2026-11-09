"""Phase boundaries and refreshing timers use observed timestamps, including tqdm logs."""
import contextlib
import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.support import ROOT
import demos.common.runtime as ui


class PhaseTests(unittest.TestCase):
    applied = '2026-11-06T00:00:00Z'
    logs = '\n'.join([
        '2026-11-06T00:00:20Z Initializing a V1 LLM engine',
        '2026-11-06T00:00:40Z Loading model from scratch...',
        '2026-11-06T00:00:45Z \rLoading safetensors checkpoint shards: 0% Completed | 0/88',
        '2026-11-06T00:01:45Z Loading weights took 60.0 seconds',
        '2026-11-06T00:01:47Z Model loading took 38 GiB and 67 seconds',
        '2026-11-06T00:01:50Z Model loading took 38 GiB and 70 seconds',
        '2026-11-06T00:01:51Z Warming up Mamba2 SSD Triton kernels...',
        '2026-11-06T00:02:10Z Running FlashInfer autotune with 8192 tokens',
        '2026-11-06T00:02:20Z init engine (profile, create kv cache, warmup model) took 30 s',
    ])

    def pods(self, ready=False):
        return [{'metadata': {'labels': {'workshop-role': role}}, 'status': {
            'containerStatuses': [{'name': 'main', 'state': {'running': {'startedAt': '2026-11-06T00:00:10Z'}}}],
            'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False',
                            'lastTransitionTime': '2026-11-06T00:02:25Z'}]}}
                for role in ('frontend', 'worker')]

    def progress(self, logs=None, observed='2026-11-06T00:03:00Z', ready=True):
        return ui.startup_progress(self.pods(ready), self.logs if logs is None else logs, self.applied, observed)

    def test_startup_module_imports_without_site_packages_or_presenter_runtime(self):
        program = '''import sys
class NoPresenterDependencies:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ('yaml', 'demos.common.runtime', 'testlib'):
            raise AssertionError('Pure startup module imported ' + fullname)
sys.meta_path.insert(0, NoPresenterDependencies())
from demos.common import startup
assert 'yaml' not in sys.modules
assert 'demos.common.runtime' not in sys.modules
assert 'testlib' not in sys.modules
assert startup.phase_timings('Model loading took 38 GiB and 12.5 seconds')['model_loading'] == 12.5
assert startup.timestamp('2026-11-06T00:00:00.123456789Z').microsecond == 123456
'''
        result = subprocess.run([sys.executable, '-B', '-S', '-c', program], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        from demos.common import startup
        for name in ('PATTERNS', 'StartupDisplay', 'phase_timings', 'timestamp', 'startup_progress',
                     'progress_lines', 'ready_pods'):
            self.assertIs(getattr(ui, name), getattr(startup, name), name)

    def test_preweight_phases_and_warmup_window_have_distinct_boundaries(self):
        progress = self.progress()
        phases = {p['name']: p for p in progress['phases']}
        expected = {'Pod startup': 10, 'Runtime setup': 10, 'Worker / TP setup': 20,
                    'Model setup': 5, 'Weight loading': 60, 'Weight finalizing': 5,
                    'Engine init': 30, '  Warmup window': 29, 'Readiness': 5}
        self.assertEqual({name: p['seconds'] for name, p in phases.items()}, expected)
        self.assertTrue(all(p['status'] == 'done' for p in phases.values()))
        self.assertEqual(progress['total_seconds'], 145)
        self.assertEqual(progress['logged_seconds_slowest_rank']['model_loading'], 70)
        self.assertIsNone(progress['logged_seconds_slowest_rank']['warmup'])
        self.assertIn('overlaps', phases['  Warmup window']['source'])

    def test_running_timer_advances_without_new_logs_and_display_repaints(self):
        logs = self.logs.split('2026-11-06T00:01:45Z')[0]
        first = self.progress(logs, '2026-11-06T00:00:50Z', False)
        second = self.progress(logs, '2026-11-06T00:00:55Z', False)
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        output = Terminal()
        with contextlib.redirect_stdout(output):
            display = ui.StartupDisplay()
            display.update(first)
            display.update(second)
        self.assertIn('running     5.0s', output.getvalue())
        self.assertIn('running    10.0s', output.getvalue())
        self.assertIn('Elapsed: 55.0s', output.getvalue())
        self.assertIn('\033[10F', output.getvalue())
        self.assertNotIn('\033[2J', output.getvalue())
        self.assertEqual([p['status'] for p in first['phases']], [p['status'] for p in second['phases']])

    def test_missing_markers_do_not_invent_phase_or_warmup_durations(self):
        progress = self.progress('2026-11-06T00:02:20Z init engine (profile, create kv cache, warmup model) took 30 s')
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(phases['Engine init']['seconds'], 30)
        for name in ('Runtime setup', 'Worker / TP setup', 'Model setup', 'Weight loading', '  Warmup window'):
            self.assertEqual(phases[name]['status'], 'unknown')
            self.assertIsNone(phases[name]['seconds'])

    def test_summary_keeps_eager_note_and_reports_warmup_window_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = object.__new__(ui.Demo)
            demo.path = Path(directory)
            demo.args = SimpleNamespace(rehearsal=False)
            demo.data = {'worker_pod': 'worker', 'apply_started_at': self.applied,
                         'ready_observed_at': '2026-11-06T00:02:26Z',
                         'worker_ready_transition_at': '2026-11-06T00:02:25Z', 'startup': self.progress()}
            (demo.path / 'worker.log').write_text(self.logs)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                demo.summary()
            text = output.getvalue()
            self.assertIn('Kernel warmup window', text)
            self.assertIn('29.00s (log markers)', text)
            self.assertIn('eager execution', text)
            self.assertNotIn('not logged', text)
            for removed in ('Startup proceeds without', 'Logged subphases can overlap', 'Checkpoint already staged'):
                self.assertNotIn(removed, text)
            saved = ui.read_json(demo.path / 'timing.json')
            self.assertEqual(saved['observed_kernel_warmup_window_seconds'], 29)
            self.assertIsNone(saved['logged_seconds_slowest_rank']['warmup'])

    def mx_pods(self, ready=False, *, arguments=True):
        pods = self.pods(ready)
        for pod in pods:
            role = pod['metadata']['labels']['workshop-role']
            pod['metadata'].update(uid=role + '-uid', name=role + '-pod')
            if role == 'worker' and arguments:
                pod['spec'] = {'containers': [{'name': 'main', 'args': [
                    '--load-format', 'modelexpress', '--tensor-parallel-size', '2']}]}
        return pods

    def mx_logs(self, strategy='source'):
        lines = [
            '2026-11-06T00:00:20Z Initializing a V1 LLM engine',
            '2026-11-06T00:00:40Z (Worker_TP0) MxModelLoader starting',
            '2026-11-06T00:00:40.200000Z (Worker_TP1) MxModelLoader starting',
        ]
        if strategy == 'source':
            lines += [
                '2026-11-06T00:00:45Z (Worker_TP0) [Worker 0] Attempting InstantTensor loading',
                '2026-11-06T00:00:46Z (Worker_TP1) [Worker 1] Attempting InstantTensor loading',
                '2026-11-06T00:00:47Z \rLoading safetensors using InstantTensor loader: 0%',
                '2026-11-06T00:01:45Z (Worker_TP0) [Worker 0] InstantTensor weight loading complete',
                '2026-11-06T00:01:50Z (Worker_TP1) [Worker 1] InstantTensor weight loading complete',
                '2026-11-06T00:01:51Z (Worker_TP0) Model loading took 38 GiB and 71 seconds',
                '2026-11-06T00:01:55Z (Worker_TP1) Model loading took 38 GiB and 75 seconds',
            ]
        else:
            lines += [
                '2026-11-06T00:00:45Z (Worker_TP0) Receiving 100 tensors from source (P2P)',
                '2026-11-06T00:00:49Z (Worker_TP0) [Worker 0] [TIMING] RDMA transfer complete: 100 tensors, 40 GB, 4.000s',
                '2026-11-06T00:00:50Z (Worker_TP0) Model loading took 38 GiB and 10 seconds',
                '2026-11-06T00:01:00Z (Worker_TP1) Receiving 100 tensors from source (P2P)',
                '2026-11-06T00:01:03Z (Worker_TP1) Transfer complete: 100 tensors, 40 GB in 3.00s',
                '2026-11-06T00:01:03.001Z (Worker_TP1) [Worker 1] [TIMING] RDMA transfer complete: 100 tensors, 40 GB, 3.000s',
                '2026-11-06T00:01:05Z (Worker_TP1) Model loading took 38 GiB and 25 seconds',
            ]
        lines += ['2026-11-06T00:02:25Z init engine (profile, create kv cache, warmup model) took 30 s']
        return '\n'.join(lines)

    def mx_progress(self, logs=None, *, ready=True, observed='2026-11-06T00:03:00Z', arguments=True):
        return ui.startup_progress(self.mx_pods(ready, arguments=arguments),
                                   self.mx_logs() if logs is None else logs, self.applied, observed)

    def test_mx_storage_loading_has_total_and_measured_subphases(self):
        progress = self.mx_progress()
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(progress['loader'], 'modelexpress')
        self.assertEqual(phases['Model loading']['seconds'], 75)
        self.assertEqual(phases['Model setup']['seconds'], 5)
        self.assertEqual(phases['Weight loading']['seconds'], 65)
        self.assertEqual(phases['Weight finalizing']['seconds'], 5)
        for name in ('Model loading', 'Model setup', 'Weight loading', 'Weight finalizing'):
            self.assertEqual(phases[name]['status'], 'done')
        self.assertNotIn('  Peer copy', phases)
        text = ui.progress_lines(progress)
        self.assertIn('    Model setup', text)
        self.assertNotIn('unknown', text)
        self.assertNotIn('skipped', text)
        status_columns = {line.index('not timed' if phase['status'] == 'unknown' else phase['status'])
                          for phase, line in zip(progress['phases'], text.splitlines())}
        self.assertEqual(len(status_columns), 1)

    def test_mx_instant_tensor_tqdm_start_handles_a_separate_timestamp(self):
        logs = '\n'.join(line for line in self.mx_logs().splitlines() if 'Attempting InstantTensor' not in line)
        progress = self.mx_progress(logs)
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(phases['Model setup']['seconds'], 7)
        self.assertEqual(phases['Weight loading']['seconds'], 63)

    def test_peer_loading_window_and_slowest_rank_copy_are_distinct(self):
        progress = self.mx_progress(self.mx_logs('peer'))
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(phases['Model loading']['seconds'], 25)
        self.assertAlmostEqual(phases['Weight loading']['seconds'], 18.001)
        self.assertAlmostEqual(phases['Weight finalizing']['seconds'], 1.999)
        self.assertEqual(phases['  Peer copy']['seconds'], 4)
        self.assertIn('staggered', phases['Weight loading']['source'])
        self.assertIn('inside', phases['  Peer copy']['source'])

    def test_first_completed_rank_does_not_finish_model_or_peer_loading(self):
        partial = self.mx_logs('peer').split('2026-11-06T00:01:00Z')[0]
        for arguments in (True, False):
            with self.subTest(arguments=arguments):
                progress = self.mx_progress(partial, ready=False, observed='2026-11-06T00:01:10Z',
                                            arguments=arguments)
                phases = {p['name']: p for p in progress['phases']}
                self.assertEqual(phases['Model loading']['status'], 'running')
                self.assertEqual(phases['Model loading']['seconds'], 30)
                self.assertEqual(phases['Weight loading']['status'], 'running')
                self.assertEqual(phases['Weight loading']['seconds'], 25)
                self.assertNotIn('  Peer copy', phases)

    def test_tp_argument_keeps_incomplete_rank_receipts_unmeasured_when_ready(self):
        partial = self.mx_logs('peer').split('2026-11-06T00:01:00Z')[0]
        partial = '\n'.join(line for line in partial.splitlines() if 'Worker_TP1' not in line)
        phases = {p['name']: p for p in self.mx_progress(partial)['phases']}
        for name in ('Model loading', 'Weight loading', 'Weight finalizing'):
            self.assertEqual(phases[name]['status'], 'unknown')
            self.assertIsNone(phases[name]['seconds'])
        self.assertNotIn('  Peer copy', phases)

    def test_malformed_mx_markers_do_not_invent_weight_or_copy_durations(self):
        logs = '\n'.join([
            '2026-11-06T00:00:40Z (Worker_TP0) MxModelLoader starting',
            '2026-11-06T00:00:45Z (Worker_TP0) Receiving unknown tensors from source (P2P)',
            '2026-11-06T00:00:50Z (Worker_TP0) [TIMING] RDMA transfer complete: 100 tensors, 40 GB, nans',
            '2026-11-06T00:01:00Z (Worker_TP0) Model loading took 38 GiB and 20 seconds',
            '2026-11-06T00:01:05Z (Worker_TP1) Model loading took 38 GiB and 25 seconds',
        ])
        progress = self.mx_progress(logs)
        phases = {p['name']: p for p in progress['phases']}
        self.assertEqual(phases['Model loading']['seconds'], 25)
        for name in ('Model setup', 'Weight loading', 'Weight finalizing'):
            self.assertEqual(phases[name]['status'], 'unknown')
            self.assertIsNone(phases[name]['seconds'])
        self.assertNotIn('  Peer copy', phases)
        display = ui.progress_lines(progress)
        self.assertIn('not timed', display)
        self.assertNotIn('unknown', display)
        self.assertNotIn('skipped', display)

    def test_terminal_clears_removed_optional_copy_row(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        first = self.mx_progress(self.mx_logs('peer'))
        second = self.mx_progress()
        output = Terminal()
        with contextlib.redirect_stdout(output):
            display = ui.StartupDisplay()
            display.update(first)
            display.update(second)
        self.assertEqual(len(first['phases']) - len(second['phases']), 1)
        self.assertTrue(output.getvalue().endswith('\033[2K\n\033[1F'))
        self.assertEqual(display.height, len(second['phases']) + 1)

    def saved_mx_run(self, path):
        logs = self.mx_logs()
        pods = self.mx_pods(True)
        cache = path / 'startup-observations/worker-uid.log'
        cache.parent.mkdir()
        cache.write_text(logs)
        (path / 'worker.log').write_text(logs)
        ui.write_json(path / 'ready-pods.json', {'items': pods})
        data = {'rehearsal': False, 'apply_started_at': self.applied,
                'ready_observed_at': '2026-11-06T00:03:00Z',
                'startup': {'phases': [{'name': 'Model setup', 'status': 'unknown', 'seconds': None}]}}
        data['startup_observation'] = {'status': 'fresh', 'worker_uid': 'worker-uid',
                                       'context': ui.startup_context(data),
                                       'log_file': 'startup-observations/worker-uid.log',
                                       'log_sha256': ui.digest(cache)}
        ui.write_json(path / 'demo.json', data)
        ui.write_json(path / 'timing.json', {'preserved': 'recorded before parser update'})
        return data

    def test_completed_saved_progress_can_upgrade_for_display_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data = self.saved_mx_run(path)
            before = {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}
            original = copy.deepcopy(data)
            with mock.patch.object(ui, 'write_json', side_effect=AssertionError('Display must not write')):
                progress = ui.startup_display_progress(path, data)
            phases = {p['name']: p for p in progress['phases']}
            self.assertEqual(phases['Model loading']['seconds'], 75)
            self.assertEqual(phases['Weight loading']['seconds'], 65)
            self.assertEqual(data, original)
            self.assertEqual({p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}, before)

    def test_saved_progress_upgrade_refuses_stale_or_different_identity_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            data = self.saved_mx_run(path)
            variants = []
            for status in ('stale', 'disconnected', 'failed'):
                changed = copy.deepcopy(data)
                changed['startup_observation']['status'] = status
                variants.append(changed)
            changed = copy.deepcopy(data)
            changed['startup_observation']['worker_uid'] = 'replacement'
            variants.append(changed)
            changed = copy.deepcopy(data)
            changed['startup_observation']['context']['apply_started_at'] = 'different-start'
            variants.append(changed)
            changed = copy.deepcopy(data)
            changed['startup_observation']['log_sha256'] = 'wrong-hash'
            variants.append(changed)
            for changed in variants:
                with self.subTest(observation=changed['startup_observation']):
                    self.assertIs(ui.startup_display_progress(path, changed), changed['startup'])
            (path / 'worker.log').write_text('changed recorded log')
            self.assertIs(ui.startup_display_progress(path, data), data['startup'])


if __name__ == '__main__':
    unittest.main()
