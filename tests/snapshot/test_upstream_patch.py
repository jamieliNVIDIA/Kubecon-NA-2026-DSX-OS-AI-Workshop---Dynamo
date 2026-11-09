"""Verify the trial preserves upstream controller selection and hook delegation."""
from tests.support import ROOT
import ast
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

import snapshot_dgd_runtime_patch as bridge
import snapshot_dgd_upstream_patch as subject
from tests.snapshot.test_runtime_patch import PINNED_SOURCE


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.upstream = subject.UPSTREAM_SOURCE.read_text()

    def test_exact_upstream_body_is_preserved_with_only_the_identity_bridge(self):
        result = subject.patch_source(PINNED_SOURCE, self.upstream)
        without_bridge = result.replace(bridge.PROXY_RESTORE_CONTEXT_SOURCE, '', 1)
        without_bridge = without_bridge.replace(bridge.REPLACEMENT_RETURN, bridge.ORIGINAL_RETURN, 1)
        self.assertEqual(without_bridge, self.upstream)
        self.assertNotIn('class CuInterposeSnapshotPauseController', result)
        self.assertIn('prepare_for_process_checkpoint=checkpoint_hooks', result)
        compile(result, '<upstream-trial>', 'exec')

    def test_changed_image_or_upstream_input_is_rejected(self):
        for source, upstream in [(PINNED_SOURCE + '\n', self.upstream),
                                 (PINNED_SOURCE, self.upstream + '\n')]:
            with self.subTest(source=len(source), upstream=len(upstream)), self.assertRaises(ValueError):
                subject.patch_source(source, upstream)

    def test_cli_records_provenance_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source, output, receipt = [path / name for name in ('source.py', 'patch.py', 'receipt.json')]
            source.write_text(PINNED_SOURCE)
            args = [sys.executable, '-B', str(ROOT/'scripts/snapshot_dgd_upstream_patch.py'),
                    '--source', str(source), '--output', str(output), '--receipt', str(receipt)]
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(receipt.read_text())
            self.assertEqual(info['upstream_commit'], subject.UPSTREAM_COMMIT)
            self.assertFalse(info['custom_pause_controller'])
            self.assertEqual(info['patched_sha256'], bridge.sha256(output.read_text()))
            self.assertNotEqual(subprocess.run(args, text=True, capture_output=True).returncode, 0)


class UpstreamIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        source = subject.patch_source(PINNED_SOURCE, subject.UPSTREAM_SOURCE.read_text())
        tree = ast.parse(source)
        selected = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.AsyncFunctionDef))
                    and n.name in ('_ReleaseOnlyKvCache', 'prepare_snapshot_engine')]
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[
            ast.alias(name='annotations')], level=0)] + selected, type_ignores=[])
        ast.fix_missing_locations(module)
        self.controllers = []
        class Controller:
            def __init__(inner, **kwargs):
                inner.__dict__.update(kwargs)
                self.controllers.append(inner)
            async def wait_for_restore(inner):
                return True
        self.native = lambda client, **kwargs: types.SimpleNamespace(client=client, **kwargs)
        self.contexts = []
        self.ns = {'os': os, 'logger': logging.getLogger('snapshot-upstream-test'),
            'SnapshotConfig': types.SimpleNamespace(from_env=lambda: types.SimpleNamespace(control_dir='/control')),
            'configure_snapshot_capture_env': lambda: None,
            'StatLoggerFactory': lambda **kwargs: object(), 'EngineSnapshotController': Controller,
            'VllmEnginePauseController': self.native, 'gc': types.SimpleNamespace(collect=lambda: None),
            'write_cuinterpose_restore_context_from_proxy': lambda **kwargs: self.contexts.append(kwargs)}
        exec(compile(module, '<exact-upstream-selection>', 'exec'), self.ns)

    def engine(self, *, hooks=True, release=True):
        engine = types.SimpleNamespace(wake_up=AsyncMock())
        if hooks:
            engine.checkpoint_prepare = AsyncMock()
            engine.checkpoint_restore = AsyncMock()
        if release:
            engine.release_kv_cache_memory = AsyncMock()
        return engine

    async def prepare(self, engine, load_format=None, gms_v1=None):
        config = types.SimpleNamespace(headless=False, embedding_worker=False,
            engine_args=types.SimpleNamespace(load_format=load_format))
        with patch.dict(os.environ, {}, clear=True):
            if gms_v1 is not None:
                os.environ['DYN_GMS_USE_V1'] = gms_v1
            return await self.ns['prepare_snapshot_engine'](config, lambda *_: (engine, object()))

    async def test_native_controller_and_communicator_hooks_are_retained(self):
        engine = self.engine()
        result = await self.prepare(engine)
        self.assertTrue(result.pause_controller.prepare_for_process_checkpoint)
        wrapped = result.pause_controller.client
        await wrapped.sleep(None)
        await wrapped.checkpoint_prepare()
        await wrapped.checkpoint_restore()
        await wrapped.wake_up()
        for method in ('release_kv_cache_memory', 'checkpoint_prepare', 'checkpoint_restore', 'wake_up'):
            getattr(engine, method).assert_awaited_once()
        self.assertEqual(self.contexts, [{'control_dir': '/control'}])

    async def test_gms_workers_keep_their_original_engine_client(self):
        for load_format, gms in [('gms', None), (None, 'true')]:
            engine = self.engine()
            result = await self.prepare(engine, load_format, gms)
            self.assertIs(result.pause_controller.client, engine)

    async def test_old_engine_without_release_method_keeps_upstream_fallback(self):
        engine = self.engine(release=False)
        result = await self.prepare(engine)
        self.assertIs(result.pause_controller.client, engine)

    async def test_missing_communicator_hooks_preserves_upstream_detection(self):
        engine = self.engine(hooks=False)
        with self.assertLogs('snapshot-upstream-test', level='WARNING'):
            result = await self.prepare(engine)
        self.assertFalse(result.pause_controller.prepare_for_process_checkpoint)


if __name__ == '__main__':
    unittest.main()
