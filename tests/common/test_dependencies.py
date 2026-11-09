"""Source cleanup and MX target startup must serialize without sharing ownership."""
from tests.support import ROOT
from pathlib import Path
import shlex
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from demos.common import dependencies, runtime as ui


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.parent, self.child = self.root / 'intro', self.root / 'MX target'
        self.parent.mkdir()
        self.child.mkdir()
        self.data = {'schema': 2, 'profile': ui.PROFILE, 'rehearsal': False,
                     'prepared': True, 'namespace': 'dynamo-ft-test'}
        ui.write_json(self.parent / 'demo.json', self.data)
        self.lease = self.root / 'lease'
        self.lease.mkdir()
        ui.write_json(self.lease / 'owner.json', {'agent': ui.OWNER, 'run': str(self.parent)})
        self.original_lease = (self.lease / 'owner.json').read_bytes()

    def assert_lease_unchanged(self):
        self.assertEqual((self.lease / 'owner.json').read_bytes(), self.original_lease)

    def cleanup_instance(self):
        instance = object.__new__(ui.Demo)
        instance.args = SimpleNamespace(rehearsal=False)
        instance.path, instance.ns = self.parent, self.data['namespace']
        instance.data = self.data
        instance.run = mock.Mock()
        instance.kubectl = mock.Mock()
        instance.save = lambda: ui.write_json(self.parent / 'demo.json', instance.data)
        return instance

    def test_exact_registration_is_idempotent_and_preserves_parent_lease(self):
        with dependencies.parent_lock(self.parent):
            dependencies.register(self.parent, self.child)
            original = (self.parent / dependencies.RECORD).read_bytes()
            dependencies.register(self.parent, self.child)
            self.assertEqual((self.parent / dependencies.RECORD).read_bytes(), original)
            with self.assertRaises(RuntimeError) as error:
                dependencies.assert_clear(self.parent)
            self.assertEqual(shlex.split(str(error.exception).splitlines()[-1])[1:], [
                '-m', 'demos', 'modelexpress', 'cleanup', '--run', str(self.child)])
            self.assertTrue((self.parent / dependencies.RECORD).exists())
            dependencies.unregister(self.parent, self.child)
            dependencies.unregister(self.parent, self.child)
            dependencies.assert_clear(self.parent)
        self.assert_lease_unchanged()

    def test_foreign_registration_and_unregistration_leave_original_record(self):
        with dependencies.parent_lock(self.parent):
            dependencies.register(self.parent, self.child)
            original = (self.parent / dependencies.RECORD).read_bytes()
            for operation in (dependencies.register, dependencies.unregister):
                with self.subTest(operation=operation.__name__), self.assertRaises(RuntimeError):
                    operation(self.parent, self.root / 'foreign')
                self.assertEqual((self.parent / dependencies.RECORD).read_bytes(), original)
        self.assert_lease_unchanged()

    def test_missing_cleaned_unknown_and_non_intro_parent_are_rejected(self):
        variants = [None, {**self.data, 'cleaned_at': 'earlier'},
                    {**self.data, 'profile': 'unknown'}, {**self.data, 'demo_kind': 'modelexpress'},
                    {**self.data, 'prepared': False}, {**self.data, 'rehearsal': True}]
        for data in variants:
            with self.subTest(data=data):
                path = self.parent / 'demo.json'
                if data is None:
                    path.unlink()
                else:
                    ui.write_json(path, data)
                with dependencies.parent_lock(self.parent), self.assertRaises(RuntimeError):
                    dependencies.register(self.parent, self.child)
                self.assertFalse((self.parent / dependencies.RECORD).exists())
        self.assert_lease_unchanged()

    def test_invalid_record_blocks_cleanup_without_discarding_it(self):
        path = self.parent / dependencies.RECORD
        path.write_text('{"schema": "unknown"}\n')
        with dependencies.parent_lock(self.parent), self.assertRaisesRegex(RuntimeError, 'Cannot verify'):
            dependencies.assert_clear(self.parent)
        self.assertTrue(path.exists())
        self.assert_lease_unchanged()

    def test_cleanup_waits_for_registration_and_refuses_before_cluster_delete(self):
        instance = self.cleanup_instance()
        started, finished = threading.Event(), threading.Event()
        errors = []

        def cleanup():
            started.set()
            try:
                instance.cleanup()
            except BaseException as error:
                errors.append(error)
            finally:
                finished.set()

        with dependencies.parent_lock(self.parent):
            thread = threading.Thread(target=cleanup)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.wait(0.05))
            dependencies.register(self.parent, self.child)
        self.assertTrue(finished.wait(2))
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIn('Clean up its target first', str(errors[0]))
        instance.run.k.assert_not_called()
        instance.run.get.assert_not_called()
        instance.kubectl.assert_not_called()
        self.assert_lease_unchanged()

    def test_registration_waits_for_full_cleanup_then_rejects_cleaned_source(self):
        instance = self.cleanup_instance()
        instance.run.k.return_value = SimpleNamespace(returncode=1, stderr='NotFound')
        entered, release, registration_started = threading.Event(), threading.Event(), threading.Event()
        cleanup_errors, registration_errors = [], []

        def inventory(*args):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Test cleanup was not released')
            return {'items': []}

        instance.run.get.side_effect = inventory

        def cleanup():
            try:
                instance.cleanup()
            except BaseException as error:
                cleanup_errors.append(error)

        def register():
            registration_started.set()
            try:
                with dependencies.parent_lock(self.parent):
                    dependencies.register(self.parent, self.child)
            except BaseException as error:
                registration_errors.append(error)

        with mock.patch.object(ui, 'LEASE', self.lease):
            cleanup_thread = threading.Thread(target=cleanup)
            cleanup_thread.start()
            self.assertTrue(entered.wait(2))
            register_thread = threading.Thread(target=register)
            register_thread.start()
            self.assertTrue(registration_started.wait(2))
            try:
                register_thread.join(0.05)
                self.assertTrue(register_thread.is_alive())
                self.assertFalse((self.parent / dependencies.RECORD).exists())
                self.assert_lease_unchanged()
            finally:
                release.set()
                cleanup_thread.join(3)
                register_thread.join(3)
        self.assertFalse(cleanup_thread.is_alive())
        self.assertFalse(register_thread.is_alive())
        self.assertEqual(cleanup_errors, [])
        self.assertEqual(len(registration_errors), 1)
        self.assertIn('uncleaned', str(registration_errors[0]))
        self.assertFalse((self.parent / dependencies.RECORD).exists())
        self.assertFalse(self.lease.exists())
        self.assertTrue(ui.read_json(self.parent / 'demo.json')['cleaned_at'])


if __name__ == '__main__':
    unittest.main()
