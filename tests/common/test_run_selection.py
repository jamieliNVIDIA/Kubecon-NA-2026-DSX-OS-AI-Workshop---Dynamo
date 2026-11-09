"""Exercise default run selection at every presenter CLI without cluster actions."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.common.presenter as presenter
import demos.common.support as support
import demos.disaggregated.demo as disagg
import demos.snapshot.demo as snapshot
import demos.snapshot.dgd_demo as snapshot_dgd
import demos.request_continuity.demo as migration
import demos.modelexpress.demo as mx
import demos.routing.demo as routing
import demos.kvcr.demo as kvcr
import demos.kvcr.prepared as prepared
import demos.shadow.demo as shadow
import demos.shadow.composed as composed
import demos.metrics.demo as metrics


def fake_demo(original, root, events):
    class Fake:
        entrypoint = original.entrypoint

        def __init__(self, args):
            self.args = args
            self.path = Path(args.run or root / 'results' / str(time.time_ns())).resolve()
            self.path.mkdir(parents=True, exist_ok=True)
            self.file = self.path / 'demo.json'
            self.data = ui.read_json(self.file) if self.file.exists() else {
                'prepared': False, 'rehearsal': args.rehearsal, 'profile': 'test-profile'}
            self.save()
            events.append(('init', self.path))

        def save(self):
            ui.write_json(self.file, self.data)

        def prepare(self):
            self.data.update(prepared=True, mx_prepared=True)
            self.save()
            events.append(('prepare', self.path))

        prime = prepare

        def require_prepared(self):
            if not self.data.get('prepared'):
                raise RuntimeError('Prepare the selected run first.')

        require_primed = require_prepared

        def source_identity(self):
            return {'uid': 'fake-source'}

        def guided(self):
            events.append(('run', self.path))

        def cleanup(self):
            self.data['cleaned_at'] = ui.now()
            self.save()
            events.append(('cleanup', self.path))

    return Fake


class SelectionTests(unittest.TestCase):
    def test_failed_explicit_run_keeps_previous_selection_and_success_can_switch_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first, second = root / 'first', root / 'second'
            for path in (first, second):
                path.mkdir()
                ui.write_json(path / 'demo.json', {'prepared': True, 'rehearsal': False, 'routing_profile': 'profile'})
            with mock.patch.object(ui, 'ROOT', root), mock.patch.object(presenter, 'ROOT', root):
                selection = ui.run_selection(routing.RoutingDemo)
                selection.remember_path(first)
                with self.assertRaisesRegex(ValueError, 'native validation rejected'):
                    presenter.launch(routing.RoutingDemo.entrypoint, ['--run', str(second)],
                                     execute=mock.Mock(side_effect=ValueError('native validation rejected')))
                self.assertEqual(selection.resolve(), first)
                presenter.launch(routing.RoutingDemo.entrypoint, ['--run', str(second)], execute=mock.Mock())
                self.assertEqual(selection.resolve(), second)

    def test_prepared_kvcr_prepare_help_reaches_native_bind_help_without_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(presenter, 'ROOT', Path(directory)):
                def help(*unused, **kwargs):
                    self.assertEqual(sys.argv[1:], ['bind', '--help'])
                    raise SystemExit(0)
                presenter.launch(prepared.PreparedKVCRDemo.entrypoint, ['prepare', '--help'], execute=help)
                self.assertFalse((Path(directory) / '.local').exists())

    def test_each_standard_launcher_prepares_runs_and_cleans_its_own_selection(self):
        cases = [(mx, 'ModelExpressDemo'), (routing, 'RoutingDemo'), (metrics, 'MetricsDemo'),
                 (kvcr, 'KVCRDemo'), (disagg, 'DisaggDemo'), (snapshot, 'SnapshotDemo'),
                 (snapshot_dgd, 'SnapshotDgdDemo'), (migration, 'MigrationDemo'), (shadow, 'ShadowDemo')]
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            with mock.patch.object(ui, 'ROOT', root), mock.patch.object(presenter, 'ROOT', root):
                for module, name in cases:
                    with self.subTest(demo=name):
                        original = getattr(module, name)
                        events = []
                        fake = fake_demo(original, root, events)
                        selection = ui.run_selection(fake)
                        def invoke():
                            if module in (disagg, snapshot, snapshot_dgd, migration, shadow):
                                support.main(fake, [], 18000, snapshot=module in (snapshot, snapshot_dgd))
                            else:
                                module.main()
                        with mock.patch.object(module, name, fake):
                            presenter.launch(original.entrypoint, ['prepare'], execute=lambda *a, **k: invoke())
                            selected = selection.resolve()
                            presenter.launch(original.entrypoint, ['--plain', '--auto'], execute=lambda *a, **k: invoke())
                            presenter.launch(original.entrypoint, ['cleanup'], execute=lambda *a, **k: invoke())
                        self.assertEqual([path for _, path in events], [selected] * len(events))
                        self.assertEqual([action for action, _ in events], ['init', 'prepare', 'init', 'run', 'init', 'cleanup'])
                        self.assertFalse(selection.path.exists())

    def test_selections_are_separate_and_preview_rehearsal_and_missing_cleanup_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with mock.patch.object(ui, 'ROOT', root), mock.patch.object(presenter, 'ROOT', root):
                a, b = ui.run_selection(disagg.DisaggDemo), ui.run_selection(snapshot.SnapshotDemo)
                run_a, run_b = root / 'a', root / 'b'
                for path in (run_a, run_b):
                    path.mkdir()
                    ui.write_json(path / 'demo.json', {'prepared': True, 'profile': 'profile', 'rehearsal': False})
                a.remember_path(run_a)
                b.remember_path(run_b)
                self.assertEqual(a.resolve(), run_a)
                self.assertEqual(b.resolve(), run_b)
                for options in ({'preview': True}, {'rehearsal': True}, {'full_manifest': True}):
                    args = SimpleNamespace(action='run', run=None, **options)
                    a.select(args)
                    self.assertIsNone(args.run)
                missing = root / 'typo'
                with self.assertRaisesRegex(ValueError, 'Cleanup requires an existing'):
                    a.select(SimpleNamespace(action='cleanup', run=missing))
                self.assertFalse(missing.exists())
                ui.write_json(run_a / 'demo.json', {'prepared': True, 'profile': 'changed', 'rehearsal': False})
                with self.assertRaisesRegex(RuntimeError, 'no longer prepared'):
                    a.resolve()
                a.forget(run_a)
                self.assertEqual(b.resolve(), run_b)

    def test_composed_freeze_prepare_run_reuses_output_and_preserves_source_arguments(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            events = []
            fake = fake_demo(composed.ComposedShadowDemo, root, events)
            def freeze(path, source, *unused):
                self.assertEqual(source, Path('writer-source'))
                path.mkdir(parents=True)
                ui.write_json(path / 'demo.json', {'prepared': False, 'profile': 'test-profile', 'rehearsal': False})
            with mock.patch.object(ui, 'ROOT', root), mock.patch.object(presenter, 'ROOT', root), mock.patch.object(composed, 'ROOT', root), \
                    mock.patch.object(composed, 'ComposedShadowDemo', fake), \
                    mock.patch.object(composed, 'freeze', side_effect=freeze):
                selection = ui.run_selection(fake)
                presenter.launch(fake.entrypoint, ['freeze', '--source-writer', 'writer-source'], execute=lambda *a, **k: composed.main())
                frozen = selection.resolve(frozen=True)
                self.assertFalse(selection.path.exists())
                presenter.launch(fake.entrypoint, ['prepare'], execute=lambda *a, **k: composed.main())
                self.assertEqual(selection.resolve(), frozen)
                presenter.launch(fake.entrypoint, ['--plain', '--auto'], execute=lambda *a, **k: composed.main())
                self.assertEqual(events[-1], ('run', frozen))

    def test_prepared_kvcr_prepare_binds_explicit_repair_then_bare_run_selects_child(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory).resolve()
            events = []
            fake = fake_demo(prepared.PreparedKVCRDemo, root, events)
            def bind(repair, output):
                self.assertEqual(repair, Path('explicit-repair.json'))
                output.mkdir(parents=True)
                ui.write_json(output / 'demo.json', {'prepared': True, 'profile': 'test-profile', 'rehearsal': False})
            with mock.patch.object(ui, 'ROOT', root), mock.patch.object(presenter, 'ROOT', root), mock.patch.object(prepared, 'PreparedKVCRDemo', fake), \
                    mock.patch.object(prepared, 'bind', side_effect=bind), mock.patch.object(ui, 'tmux_layout') as layout:
                presenter.launch(fake.entrypoint, ['prepare', '--repair', 'explicit-repair.json'], execute=lambda *a, **k: prepared.main())
                selected = ui.run_selection(fake).resolve()
                presenter.launch(fake.entrypoint, [], execute=lambda *a, **k: prepared.main())
                self.assertEqual(layout.call_args.args[0].path, selected)


if __name__ == '__main__':
    unittest.main()
