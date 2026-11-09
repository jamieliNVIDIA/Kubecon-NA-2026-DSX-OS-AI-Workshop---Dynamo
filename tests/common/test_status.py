"""Status reports recorded lifecycle metadata without changing or qualifying runs."""
from tests.support import ROOT
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from demos import __main__ as cli
from demos.common import status
from demos.registry import get_demo


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class StatusTests(unittest.TestCase):
    def select(self, root, name, data, *, frozen=False):
        spec = get_demo(name)
        run = root / 'results' / name
        write(run / 'demo.json', {'namespace': 'dynamo-ft-status', 'rehearsal': False, **data})
        pointer = (root / '.local/demo-01-current.json' if name == 'single-replica' else
                   root / '.local/current-runs' / (spec.selection_key + '.json'))
        if frozen:
            pointer = pointer.with_suffix('.frozen.json')
        write(pointer, {'run': str(run)})
        return run, pointer

    def rows(self, root):
        return {row['demo']: row for row in status.snapshot(root)['demos']}

    def test_empty_status_creates_no_workspace_or_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'missing-workspace'
            result = status.snapshot(root)
            self.assertTrue(all(row['state'] == 'not selected' for row in result['demos']))
            self.assertEqual(result['reservations'], [])
            self.assertFalse(root.exists())
            self.assertIn('Recorded state; no live readiness check', status.render(result))

    def test_selected_intro_and_peer_show_source_dependency_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, _ = self.select(root, 'single-replica', {'prepared': True, 'ready_observed_at': 'recorded'})
            peer, _ = self.select(root, 'modelexpress', {
                'mx_prepared': True, 'apply_started_at': 'recorded', 'source_binding': {'run': str(first)}})
            write(first / '.mx-dependent.json', {'schema': 1, 'parent_run': str(first), 'child_run': str(peer)})
            write(root / '.local/test.gpu-lease/owner.json', {
                'agent': 'workshop-demo-single-replica', 'run': str(first), 'private_token': 'SECRET-CREDENTIAL'})
            before = hashes(root)
            result = status.snapshot(root)
            rows = {row['demo']: row for row in result['demos']}
            self.assertEqual(rows['single-replica']['state'], 'ready')
            self.assertEqual(rows['single-replica']['dependent_run'], 'results/modelexpress')
            self.assertEqual(rows['modelexpress']['state'], 'started')
            self.assertEqual(rows['modelexpress']['parent_run'], 'results/single-replica')
            self.assertEqual(result['reservations'], [{
                'lease': '.local/test.gpu-lease', 'owner': 'single-replica', 'run': 'results/single-replica'}])
            self.assertNotIn('SECRET-CREDENTIAL', json.dumps(result))
            self.assertEqual(hashes(root), before)

    def test_one_bad_selection_does_not_hide_other_prepared_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, pointer = self.select(root, 'single-replica', {})
            pointer.write_text('{not valid JSON')
            self.select(root, 'routing', {'prepared': True, 'presentation_mode': 'recorded-evidence'})
            self.select(root, 'metrics', {'prepared': True, 'presentation_mode': 'recorded-evidence'})
            rows = self.rows(root)
            self.assertEqual(rows['single-replica']['state'], 'invalid')
            self.assertEqual(rows['routing']['state'], 'prepared')
            self.assertEqual(rows['routing']['mode'], 'recorded evidence')
            self.assertEqual(rows['metrics']['mode'], 'recorded evidence')

    def test_missing_run_and_changed_selection_identity_are_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, pointer = self.select(root, 'disaggregated', {'profile': 'new', 'prepared': True})
            write(pointer, {'run': str(run), 'identity': {'profile': 'old', 'namespace': 'dynamo-ft-status'}})
            other, _ = self.select(root, 'snapshot', {'prepared': True})
            (other / 'demo.json').unlink()
            rows = self.rows(root)
            self.assertEqual(rows['disaggregated']['state'], 'invalid')
            self.assertIn('Selected run identity changed.', rows['disaggregated']['notes'])
            self.assertEqual(rows['snapshot']['state'], 'invalid')

    def test_cleaned_rehearsal_and_frozen_states_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.select(root, 'snapshot', {'prepared': True, 'ready_observed_at': 'recorded', 'cleaned_at': 'recorded'})
            self.select(root, 'kvcr', {'prepared': True, 'rehearsal': True})
            self.select(root, 'shadow-composed', {'prepared': False}, frozen=True)
            rows = self.rows(root)
            self.assertEqual(rows['snapshot']['state'], 'cleaned')
            self.assertEqual(rows['kvcr']['mode'], 'rehearsal')
            self.assertEqual(rows['shadow-composed']['state'], 'frozen')

    def test_dgd_replacement_intent_overrides_the_previous_ready_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = self.select(root, 'snapshot-dgd', {
                'prepared': True, 'initial_identity': {'uid': 'original-worker'},
                'ready_observed_at': 'original-ready'})
            write(run / 'state.json', {'replacement_intent': {
                'original_pod_uid': 'original-worker', 'private_value': 'SECRET-STATE'}})
            before = hashes(root)
            result = status.snapshot(root)
            row = next(row for row in result['demos'] if row['demo'] == 'snapshot-dgd')
            self.assertEqual(row['state'], 'started')
            self.assertNotIn('SECRET-STATE', json.dumps(result))
            self.assertEqual(hashes(root), before)
            data = json.loads((run / 'demo.json').read_text())
            data['replacement_identity'] = {'uid': 'replacement-worker'}
            write(run / 'demo.json', data)
            self.assertEqual(self.rows(root)['snapshot-dgd']['state'], 'ready')

    def test_corrupt_dgd_controller_state_is_isolated_to_that_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, _ = self.select(root, 'snapshot-dgd', {
                'prepared': True, 'initial_identity': {'uid': 'original-worker'},
                'ready_observed_at': 'original-ready'})
            self.select(root, 'routing', {'prepared': True, 'presentation_mode': 'recorded-evidence'})
            for raw in ('{invalid state', '[]'):
                with self.subTest(raw=raw):
                    (run / 'state.json').write_text(raw)
                    before = hashes(root)
                    rows = self.rows(root)
                    self.assertEqual(rows['snapshot-dgd']['state'], 'invalid')
                    self.assertEqual(rows['routing']['state'], 'prepared')
                    self.assertEqual(hashes(root), before)

    def test_unknown_or_invalid_lease_owner_never_exposes_raw_metadata_or_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / '.local/a.gpu-lease/owner.json', {
                'agent': 'SECRET-UNKNOWN-OWNER', 'run': 'results/external', 'authorization': 'SECRET-TOKEN'})
            path = root / '.local/b.gpu-lease/owner.json'
            path.parent.mkdir(parents=True)
            path.write_text('SECRET-BROKEN-JSON')
            value = status.snapshot(root)
            text = status.render(value)
            self.assertEqual([row['owner'] for row in value['reservations']], ['unrecognized owner', 'invalid'])
            self.assertNotIn('SECRET', text)
            self.assertNotIn('cleanup', text)

    def test_prepared_parent_and_corrupt_dependency_are_reported_without_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child, _ = self.select(root, 'kvcr-prepared', {
                'prepared': True, 'ready_observed_at': 'recorded', 'prepared_parent': 'results/retained-parent'})
            first, _ = self.select(root, 'single-replica', {'prepared': True})
            write(first / '.mx-dependent.json', {'schema': 1, 'parent_run': str(child), 'child_run': str(child)})
            before = hashes(root)
            rows = self.rows(root)
            self.assertEqual(rows['kvcr-prepared']['parent_run'], 'results/retained-parent')
            self.assertEqual(rows['single-replica']['state'], 'invalid')
            self.assertEqual(hashes(root), before)

    def test_global_cli_dispatches_status_and_json_without_presenter_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for options in ([], ['--json']):
                output = io.StringIO()
                with (mock.patch.object(status, 'ROOT', root),
                      mock.patch.object(cli, 'dispatch') as dispatch,
                      contextlib.redirect_stdout(output)):
                    self.assertEqual(cli.main(['status'] + options), 0)
                dispatch.assert_not_called()
                if options:
                    self.assertEqual(json.loads(output.getvalue())['scope'], status.SCOPE)
                else:
                    self.assertIn('Recorded state; no live readiness check', output.getvalue())
            self.assertEqual(list(root.iterdir()), [])

    def test_status_runs_without_site_packages_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-S', '-B', '-m', 'demos', 'status', '--json'],
                                    cwd=directory, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['scope'], status.SCOPE)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
