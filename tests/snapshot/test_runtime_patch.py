"""Pinned runtime mutation and CuInterpose pause/restore failure semantics."""
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
import unittest
from unittest.mock import AsyncMock, patch

import snapshot_dgd_runtime_patch as subject

# Exact inspected runtime module, retained so these checks work without private
# live-cluster evidence or installed Dynamo/vLLM packages.
PINNED_SOURCE = "# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.\n# SPDX-License-Identifier: Apache-2.0\n\nimport gc\nimport logging\nimport os\nfrom collections.abc import Callable\n\nfrom dynamo.common.snapshot.lifecycle import (\n    EngineSnapshotController,\n    SnapshotConfig,\n    configure_snapshot_capture_env,\n)\n\nfrom .args import Config\nfrom .handlers import VllmEnginePauseController\nfrom .publisher import StatLoggerFactory\nfrom .worker_factory import EngineSetupResult, SnapshotEngineSetupResult\n\nlogger = logging.getLogger(__name__)\n\n\nasync def prepare_snapshot_engine(\n    config: Config,\n    setup_vllm_engine: Callable[..., EngineSetupResult],\n) -> EngineSnapshotController[SnapshotEngineSetupResult] | None:\n    snapshot_config = SnapshotConfig.from_env()\n    if snapshot_config is None:\n        return None\n\n    if config.headless:\n        raise ValueError(\n            \"--headless is incompatible with snapshot mode \"\n            \"(DYN_SNAPSHOT_CONTROL_DIR is set). \"\n            \"Remove --headless or unset DYN_SNAPSHOT_CONTROL_DIR.\"\n        )\n\n    configure_snapshot_capture_env()\n    logger.info(\"Snapshot mode enabled (watcher-driven signals)\")\n    config.engine_args.enable_sleep_mode = True\n\n    stat_logger_factory = StatLoggerFactory(\n        endpoint=None,\n        embedding_worker=config.embedding_worker,\n    )\n    engine = setup_vllm_engine(config, stat_logger_factory)\n    # Decide before the first pause: reaching this at pause time would raise\n    # after sleep() had already released the engine's memory.\n    checkpoint_hooks = all(\n        hasattr(engine[0], hook)\n        for hook in (\"checkpoint_prepare\", \"checkpoint_restore\")\n    )\n    if not checkpoint_hooks:\n        logger.warning(\n            \"This vLLM build has no AsyncLLM.checkpoint_prepare/checkpoint_restore; \"\n            \"snapshotting without communicator checkpointing. \"\n            \"Requires vLLM 0.27.0 or newer.\"\n        )\n\n    gc.collect()\n    snapshot_controller = EngineSnapshotController(\n        engine=(engine, stat_logger_factory),\n        pause_controller=VllmEnginePauseController(\n            engine[0],\n            prepare_for_process_checkpoint=checkpoint_hooks,\n        ),\n        snapshot_config=snapshot_config,\n        pause_args=(None,),\n    )\n    if not await snapshot_controller.wait_for_restore():\n        logger.info(\"vLLM snapshot captured successfully\")\n        os._exit(0)\n\n    return snapshot_controller\n"


class PatchTests(unittest.TestCase):
    def test_patch_changes_only_controller_and_keeps_entrypoint_lifecycle(self):
        self.assertEqual(subject.sha256(PINNED_SOURCE), subject.PINNED_SOURCE_SHA256)
        patched = subject.patch_source(PINNED_SOURCE)
        expected = PINNED_SOURCE.replace(subject.ORIGINAL_CONSTRUCTOR, subject.REPLACEMENT_CONSTRUCTOR)
        expected = expected.replace(subject.ORIGINAL_RETURN, subject.REPLACEMENT_RETURN)
        actual = patched.replace(subject.CONTROLLER_SOURCE, '', 1).replace(subject.PROXY_RESTORE_CONTEXT_SOURCE, '', 1)
        self.assertEqual(actual, expected)
        compile(patched, '<patched-snapshot>', 'exec')
        self.assertIn('snapshot_controller.wait_for_restore()', patched)
        self.assertIn('engine=(engine, stat_logger_factory)', patched)
        self.assertNotIn('prepare_for_process_checkpoint=checkpoint_hooks', patched)
        function = next(node for node in ast.parse(patched).body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'prepare_snapshot_engine')
        self.assertEqual(function.body[-2].value.func.id, 'write_cuinterpose_restore_context_from_proxy')
        self.assertIsInstance(function.body[-1], ast.Return)

    def test_unknown_or_already_patched_runtime_is_rejected(self):
        for source in [PINNED_SOURCE + '\n', PINNED_SOURCE.replace('checkpoint_hooks', 'different'),
                       subject.patch_source(PINNED_SOURCE)]:
            with self.subTest(source=source[-40:]), self.assertRaisesRegex(ValueError, 'pinned SHA256'):
                subject.patch_source(source)

    def test_cli_records_hashes_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source, output, receipt = [path / name for name in ('source.py', 'patched.py', 'receipt.json')]
            source.write_text(PINNED_SOURCE)
            command = [sys.executable, str(ROOT / 'scripts/snapshot_dgd_runtime_patch.py'),
                       '--source', str(source), '--output', str(output), '--receipt', str(receipt)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            expected = subject.receipt(PINNED_SOURCE, output.read_text())
            self.assertEqual(json.loads(receipt.read_text()), expected)
            self.assertEqual(json.loads(first.stdout), expected)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(subject.sha256(output.read_text()), expected['patched_sha256'])


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        namespace = {'logger': logging.getLogger('snapshot-patch-test')}
        exec(compile(subject.CONTROLLER_SOURCE, '<snapshot-controller>', 'exec'), namespace)
        self.engine = type('Engine', (), {})()
        self.events = []
        for name in ('pause_generation', 'release_kv_cache_memory', 'wake_up',
                     'resume_generation', 'check_health', 'checkpoint_prepare', 'checkpoint_restore'):
            async def call(name=name):
                self.events.append(name)
            setattr(self.engine, name, AsyncMock(side_effect=call))
        self.controller = namespace['CuInterposeSnapshotPauseController'](self.engine)

    async def test_pause_and_resume_use_direct_kv_contract_and_check_health(self):
        controller = self.controller
        self.assertFalse(await controller.resume())
        self.assertTrue(await controller.pause(None))
        self.assertTrue(controller.is_paused)
        self.assertFalse(await controller.pause(None))
        self.assertTrue(await controller.resume())
        self.assertTrue(controller.is_paused)
        controller.mark_resumed()
        self.assertFalse(controller.is_paused)
        self.assertFalse(controller.needs_resume_recovery)
        self.assertEqual(self.events, ['pause_generation', 'release_kv_cache_memory', 'wake_up',
                                       'resume_generation', 'check_health'])
        self.engine.checkpoint_prepare.assert_not_awaited()
        self.engine.checkpoint_restore.assert_not_awaited()

    async def test_release_failure_wakes_before_resuming_generation(self):
        self.engine.release_kv_cache_memory.side_effect = RuntimeError('release failed')
        with self.assertRaisesRegex(RuntimeError, 'release failed'):
            await self.controller.pause(None)
        self.assertEqual(self.events, ['pause_generation', 'wake_up', 'resume_generation'])
        self.assertFalse(self.controller.needs_resume_recovery)
        with self.assertRaisesRegex(RuntimeError, 'before health verification'):
            self.controller.mark_resumed()

    async def test_failed_rollback_remains_recoverable(self):
        self.engine.release_kv_cache_memory.side_effect = RuntimeError('release failed')
        self.engine.wake_up.side_effect = RuntimeError('wake failed')
        with self.assertLogs('snapshot-patch-test', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'release failed'):
                await self.controller.pause(None)
        self.assertTrue(self.controller.needs_resume_recovery)
        self.engine.resume_generation.assert_not_awaited()
        self.engine.wake_up.side_effect = None
        self.assertTrue(await self.controller.resume())
        self.controller.mark_resumed()
        self.assertFalse(self.controller.needs_resume_recovery)

    async def test_restore_wake_failure_keeps_generation_paused(self):
        await self.controller.pause(None)
        self.engine.wake_up.side_effect = RuntimeError('wake failed')
        with self.assertRaisesRegex(RuntimeError, 'wake failed'):
            await self.controller.resume()
        self.assertTrue(self.controller.is_paused)
        self.engine.resume_generation.assert_not_awaited()
        with self.assertRaises(RuntimeError):
            self.controller.mark_resumed()

    async def test_resume_generation_failure_does_not_repeat_successful_wake(self):
        await self.controller.pause(None)
        self.engine.resume_generation.side_effect = RuntimeError('resume failed')
        with self.assertRaisesRegex(RuntimeError, 'resume failed'):
            await self.controller.resume()
        self.engine.resume_generation.side_effect = None
        await self.controller.resume()
        self.engine.wake_up.assert_awaited_once()
        self.controller.mark_resumed()

    async def test_health_failure_cannot_be_marked_resumed_and_can_be_retried(self):
        await self.controller.pause(None)
        self.engine.check_health.side_effect = RuntimeError('unhealthy')
        with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
            await self.controller.resume()
        with self.assertRaises(RuntimeError):
            self.controller.mark_resumed()
        self.engine.check_health.side_effect = None
        await self.controller.resume()
        self.engine.wake_up.assert_awaited_once()
        self.engine.resume_generation.assert_awaited_once()
        self.controller.mark_resumed()

    async def test_cancellation_during_release_rolls_back_and_propagates(self):
        self.engine.release_kv_cache_memory.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.pause(None)
        self.engine.wake_up.assert_awaited_once()
        self.engine.resume_generation.assert_awaited_once()
        self.assertFalse(self.controller.needs_resume_recovery)

    async def test_other_pause_levels_and_partial_wakes_are_rejected(self):
        with self.assertRaises(ValueError):
            await self.controller.pause(1)
        with self.assertRaises(ValueError):
            await self.controller.resume(['kv_cache'])
        self.assertEqual(self.events, [])


class ProxyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / 'proc'
        self.pid1 = self.proc / '1'
        self.pid1.mkdir(parents=True)
        self.control = self.root / 'control'
        self.control.mkdir()
        self.required = {'DYN_NAMESPACE', 'DYN_COMPONENT', 'DYN_PARENT_DGD_K8S_NAME',
                         'DYN_PARENT_DGD_K8S_NAMESPACE', 'POD_NAME', 'POD_NAMESPACE', 'POD_UID'}
        self.namespace = {'os': os, 'logger': logging.getLogger('snapshot-proxy-test'),
                          'KUBERNETES_REQUIRED_ENV_NAMES': self.required,
                          'KUBERNETES_OPTIONAL_ENV_NAMES': {'DYN_NAMESPACE_WORKER_SUFFIX'},
                          'RESTORE_RUNTIME_ENV_NAMES': {'DYN_DISCOVERY_BACKEND', 'DYN_REQUEST_PLANE'},
                          'SNAPSHOT_RESTORE_CONTEXT_FILE': 'restore-context.json'}
        function = next(node for node in ast.parse(subject.PROXY_RESTORE_CONTEXT_SOURCE).body
                        if isinstance(node, ast.FunctionDef))
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<proxy-helper>', 'exec'), self.namespace)
        self.write_context = self.namespace['write_cuinterpose_restore_context_from_proxy']
        self.env = {name: 'destination-' + name.lower() for name in self.required}
        self.env.update(DYN_DISCOVERY_BACKEND='kubernetes', HF_TOKEN='secret-hf-token',
                        AWS_SECRET_ACCESS_KEY='secret-aws-key')
        self.pid1.joinpath('cmdline').write_bytes(b'/snapshot-control/snapshot-restore-proxy\0')
        self.write_environment()
        self.capture_env = patch.dict(os.environ, {'POD_UID': 'source-uid',
                                                  'DYN_REQUEST_PLANE': 'stale-capture-setting'})
        self.capture_env.start()
        self.addCleanup(self.capture_env.stop)

    def write_environment(self):
        self.pid1.joinpath('environ').write_bytes(b'\0'.join(
            name.encode() + b'=' + value.encode() for name, value in self.env.items()) + b'\0')

    def call(self):
        return self.write_context(proc_root=self.proc, control_dir=self.control)

    def test_proxy_identity_is_filtered_and_absent_settings_clear_capture_values(self):
        with self.assertLogs('snapshot-proxy-test', level='INFO') as logs:
            context = self.call()
        self.assertEqual(json.loads(self.control.joinpath('restore-context.json').read_text()), context)
        self.assertEqual(context['env']['POD_UID'], self.env['POD_UID'])
        self.assertIsNone(context['env']['DYN_REQUEST_PLANE'])
        self.assertIsNone(context['env']['DYN_NAMESPACE_WORKER_SUFFIX'])
        self.assertNotIn('HF_TOKEN', context['env'])
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', context['env'])
        self.assertNotIn('secret-', '\n'.join(logs.output))
        self.assertNotIn('secret-', self.control.joinpath('restore-context.json').read_text())
        self.assertEqual(list(self.control.glob('.restore-context-*')), [])
        self.assertEqual(os.environ['POD_UID'], 'source-uid')

    def test_wrong_proxy_or_additional_arguments_fail_before_context_creation(self):
        for command in [b'python3\0worker.py\0', b'/snapshot-control/snapshot-restore-proxy\0--extra\0', b'']:
            with self.subTest(command=command):
                self.pid1.joinpath('cmdline').write_bytes(command)
                with self.assertRaisesRegex(RuntimeError, 'expected Snapshot restore proxy'):
                    self.call()
                self.assertFalse(self.control.joinpath('restore-context.json').exists())

    def test_missing_or_empty_required_identity_is_rejected(self):
        for name in self.required:
            original = self.env.pop(name)
            self.write_environment()
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'required Kubernetes identity'):
                self.call()
            self.env[name] = ''
            self.write_environment()
            with self.assertRaisesRegex(RuntimeError, 'required Kubernetes identity'):
                self.call()
            self.env[name] = original

    def test_captured_or_unknown_source_uid_is_rejected(self):
        self.env['POD_UID'] = 'source-uid'
        self.write_environment()
        with self.assertRaisesRegex(RuntimeError, 'captured source identity'):
            self.call()
        self.env['POD_UID'] = 'new-uid'
        self.write_environment()
        with patch.dict(os.environ, {'POD_UID': ''}):
            with self.assertRaisesRegex(RuntimeError, 'captured source identity'):
                self.call()

    def test_existing_context_is_preserved_and_refused_even_if_matching(self):
        context = self.call()
        with self.assertRaisesRegex(RuntimeError, 'existing Snapshot restore context'):
            self.call()
        self.assertEqual(json.loads(self.control.joinpath('restore-context.json').read_text()), context)

    def test_duplicate_supported_environment_variable_is_rejected(self):
        with self.pid1.joinpath('environ').open('ab') as stream:
            stream.write(b'POD_UID=another-uid\0')
        with self.assertRaisesRegex(RuntimeError, 'duplicate supported'):
            self.call()

    def test_invalid_unrelated_environment_bytes_are_ignored(self):
        with self.pid1.joinpath('environ').open('ab') as stream:
            stream.write(b'UNRELATED_SECRET=\xff\xfe\0')
        self.assertNotIn('UNRELATED_SECRET', self.call()['env'])

    def test_atomic_link_refuses_concurrent_writer_and_removes_temporary(self):
        context = self.control / 'restore-context.json'
        def create_competing_writer(source, destination):
            context.write_text('existing')
            raise FileExistsError('concurrent context writer')
        with patch.object(os, 'link', side_effect=create_competing_writer):
            with self.assertRaises(FileExistsError):
                self.call()
        self.assertEqual(context.read_text(), 'existing')
        self.assertEqual(list(self.control.glob('.restore-context-*')), [])

    def test_destination_huggingface_offline_policy_is_applied_outside_context_schema(self):
        for policy in ['0', '1', None]:
            with self.subTest(policy=policy):
                if policy is None:
                    self.env.pop('HF_HUB_OFFLINE', None)
                else:
                    self.env['HF_HUB_OFFLINE'] = policy
                self.write_environment()
                with patch.dict(os.environ, {'HF_HUB_OFFLINE': 'stale-source-policy'}):
                    context = self.call()
                    self.assertEqual(os.environ.get('HF_HUB_OFFLINE'), policy)
                    self.assertNotIn('HF_HUB_OFFLINE', context['env'])
                self.control.joinpath('restore-context.json').unlink()

    def test_invalid_huggingface_offline_policy_fails_without_context_or_environment_change(self):
        for policy in ['', 'true', 'yes', '2']:
            with self.subTest(policy=policy):
                self.env['HF_HUB_OFFLINE'] = policy
                self.write_environment()
                with patch.dict(os.environ, {'HF_HUB_OFFLINE': 'stale-source-policy'}):
                    with self.assertRaisesRegex(RuntimeError, 'policy must be 0, 1, or absent'):
                        self.call()
                    self.assertEqual(os.environ['HF_HUB_OFFLINE'], 'stale-source-policy')
                self.assertFalse(self.control.joinpath('restore-context.json').exists())

    def test_failed_context_publication_does_not_apply_offline_policy(self):
        self.env['HF_HUB_OFFLINE'] = '1'
        self.write_environment()
        self.control.joinpath('restore-context.json').write_text('existing')
        with patch.dict(os.environ, {'HF_HUB_OFFLINE': 'stale-source-policy'}):
            with self.assertRaisesRegex(RuntimeError, 'existing Snapshot restore context'):
                self.call()
            self.assertEqual(os.environ['HF_HUB_OFFLINE'], 'stale-source-policy')


if __name__ == '__main__':
    unittest.main()
