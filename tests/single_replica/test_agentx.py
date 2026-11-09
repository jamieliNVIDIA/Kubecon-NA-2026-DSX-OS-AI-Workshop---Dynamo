"""Guard the intro's AIPerf AgentX steps: one shared slice, offline runs, skips and staging checks."""
from tests.support import ROOT
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import demos.common.runtime as demo
from demos.single_replica import agentx
from demos.single_replica import demo as intro

LOCK = json.loads(demo.MODEL_LOCK.read_text())
URL = 'http://127.0.0.1:18000'


class Process:
    def __init__(self, calls, waits):
        self.calls, self.waits, self.signals = calls, list(waits), []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    def wait(self, timeout=None):
        value = self.waits.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def send_signal(self, value):
        self.signals.append(value)

    def kill(self):
        self.signals.append(signal.SIGKILL)


@contextlib.contextmanager
def staging_home(directory):
    home = Path(directory) / 'aiperf'
    source = home / 'source'
    with mock.patch.multiple(agentx, HOME=home, SOURCE=source, AIPERF=source / '.venv/bin/aiperf',
                             PYTHON=source / '.venv/bin/python', RECEIPT=home / 'staged.json',
                             CACHE=home / 'dataset-cache'):
        yield home


def stage_receipt(key='0d8a7466f33d5f5205da3621f94b0779'):
    agentx.AIPERF.parent.mkdir(parents=True)
    agentx.AIPERF.write_text('#!/bin/sh\n')
    (agentx.CACHE / key).mkdir(parents=True)
    (agentx.CACHE / key / 'manifest.json').write_text('{}')
    agentx.RECEIPT.write_text(json.dumps({'fingerprint': agentx.fingerprint(LOCK), 'cache_key': key}))


class AgentxTests(unittest.TestCase):
    def live_demo(self, directory):
        instance = intro.IntroDemo(SimpleNamespace(run=Path(directory) / 'run', rehearsal=False, action='run',
                                                   preview=False, auto=True))
        instance.data['base_url'] = URL
        return instance

    def test_both_runs_share_one_slice_and_differ_only_in_concurrency(self):
        one, eight = (agentx.groups(LOCK, URL, c, f'aiperf-c{c}') for c in agentx.CONCURRENCY)
        self.assertEqual(agentx.CONCURRENCY, (1, 8))
        first, second = agentx.arguments(one), agentx.arguments(eight)
        self.assertEqual(first[:2], [str(agentx.AIPERF), 'profile'])
        different = [(a, b) for a, b in zip(first, second) if a != b]
        self.assertEqual(len(first), len(second))
        self.assertEqual(different, [('aiperf-c1', 'aiperf-c8'), ('1', '8')])
        text = agentx.projected(one)
        lines = text.splitlines()
        self.assertEqual(lines[0], 'aiperf profile \\')
        self.assertEqual(len(lines), len(one))
        self.assertTrue(all(len(line) <= 80 for line in lines))
        self.assertTrue(lines[-1].endswith('--artifact-dir aiperf-c1 --concurrency 1'))
        for expected in ('--scenario inferencex-agentx-mvp --unsafe-override',
                         '--public-dataset semianalysis_cc_traces_weka_062126',
                         '--trajectory-start-min-ratio 0 --trajectory-start-max-ratio 0',
                         '--model ' + LOCK['model'], '--tokenizer-revision ' + LOCK['revision'],
                         '--url ' + URL, '--benchmark-duration 20 --benchmark-grace-period 10'):
            self.assertIn(expected, text)
        self.assertNotIn(str(agentx.SOURCE), text)

    def test_rehearsal_shows_the_command_without_running_aiperf(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = intro.IntroDemo(SimpleNamespace(run=Path(directory) / 'run', rehearsal=True, action='run',
                                                       preview=False, auto=True))
            instance.data['base_url'] = URL
            output = io.StringIO()
            with mock.patch.object(agentx.subprocess, 'Popen') as popen, contextlib.redirect_stdout(output):
                instance.aiperf(8)
            popen.assert_not_called()
            self.assertIn('$ aiperf profile', output.getvalue())
            self.assertIn('--concurrency 8', output.getvalue())
            self.assertIn('[REHEARSAL] AIPerf is not run', output.getvalue())
            self.assertFalse(list(instance.path.glob('aiperf-c*')))

    def test_live_step_is_skipped_until_aiperf_is_staged(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory):
            instance = self.live_demo(directory)
            output = io.StringIO()
            with mock.patch.object(agentx.subprocess, 'Popen') as popen, contextlib.redirect_stdout(output):
                instance.aiperf(1)
            popen.assert_not_called()
            self.assertIn('$ aiperf profile', output.getvalue())
            self.assertIn('prepare-aiperf', output.getvalue())
            self.assertFalse(list(instance.path.glob('aiperf-c*')))
            self.assertNotIn('agentx', instance.data)

    def test_live_step_runs_the_projected_command_offline_and_keeps_a_receipt(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory) as home:
            stage_receipt()
            instance = self.live_demo(directory)
            calls = []
            process = Process(calls, [0])
            with mock.patch.object(agentx.subprocess, 'Popen', process), contextlib.redirect_stdout(io.StringIO()):
                instance.aiperf(1)
            (args, kwargs), = calls
            self.assertEqual(args, agentx.arguments(agentx.groups(LOCK, URL, 1, 'aiperf-c1')))
            self.assertEqual(kwargs['cwd'], str(instance.path))
            env = kwargs['env']
            self.assertEqual((env['HF_HUB_OFFLINE'], env['HF_DATASETS_OFFLINE']), ('1', '1'))
            self.assertEqual(env['AIPERF_DATASET_MMAP_CACHE_DIR'], str(home / 'dataset-cache'))
            self.assertNotIn('VIRTUAL_ENV', env)
            receipt = json.loads((instance.path / 'aiperf-c1.json').read_text())
            self.assertEqual((receipt['exit_code'], receipt['timed_out'], receipt['artifact_dir']), (0, False, 'aiperf-c1'))
            self.assertEqual(receipt['args'], args)
            saved = json.loads(instance.file.read_text())['agentx']['1']
            self.assertEqual((saved['exit_code'], saved['artifact_dir']), (0, 'aiperf-c1'))
            # A resumed walkthrough keeps the first attempt's evidence.
            self.assertEqual(agentx.artifact_name(instance.path, 1), 'aiperf-c1-2')

    def test_failed_or_overlong_run_is_reported_and_the_walkthrough_continues(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory):
            stage_receipt()
            instance = self.live_demo(directory)
            output = io.StringIO()
            overlong = Process([], [subprocess.TimeoutExpired('aiperf', agentx.TIMEOUT), -2])
            with mock.patch.object(agentx.subprocess, 'Popen', overlong), contextlib.redirect_stdout(output):
                instance.aiperf(8)
            self.assertEqual(overlong.signals, [signal.SIGINT])
            self.assertTrue(json.loads((instance.path / 'aiperf-c8.json').read_text())['timed_out'])
            self.assertIn('was stopped', output.getvalue())
            with mock.patch.object(agentx.subprocess, 'Popen', Process([], [3])), \
                    contextlib.redirect_stdout(output):
                instance.aiperf(8)
            self.assertEqual(json.loads((instance.path / 'aiperf-c8-2.json').read_text())['exit_code'], 3)
            self.assertIn('exited with code 3; see aiperf-c8-2/logs/aiperf.log', output.getvalue())

    def test_interrupt_stops_aiperf_before_leaving_the_step(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory):
            stage_receipt()
            instance = self.live_demo(directory)
            interrupted = Process([], [KeyboardInterrupt(), -2])
            with mock.patch.object(agentx.subprocess, 'Popen', interrupted), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    instance.aiperf(1)
            self.assertEqual(interrupted.signals, [signal.SIGINT])

    def test_staged_requires_the_same_slice_the_pinned_aiperf_and_a_warm_cache(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory):
            self.assertIsNone(agentx.staged(LOCK))
            stage_receipt()
            self.assertEqual(agentx.staged(LOCK)['cache_key'], '0d8a7466f33d5f5205da3621f94b0779')
            changed = dict(LOCK, revision='another-revision')
            self.assertIsNone(agentx.staged(changed))
            with mock.patch.object(agentx, 'SLICE', agentx.SLICE[:-1]):
                self.assertIsNone(agentx.staged(LOCK))
            (agentx.CACHE / '0d8a7466f33d5f5205da3621f94b0779' / 'manifest.json').unlink()
            self.assertIsNone(agentx.staged(LOCK))

    def test_staging_refuses_a_missing_or_changed_archive_before_running_anything(self):
        with tempfile.TemporaryDirectory() as directory, staging_home(directory):
            archive = Path(directory) / 'aiperf.tar.gz'
            archive.write_bytes(b'not the pinned source')
            with mock.patch.object(agentx, 'ARCHIVE', archive), \
                    mock.patch.object(agentx.subprocess, 'run') as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
                    agentx.stage(LOCK)
            run.assert_not_called()

    def test_unpack_keeps_in_tree_links_and_rejects_escaping_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'LICENSE').write_text('license\n')

            def archive(name, entries):
                path = root / name
                with tarfile.open(path, 'w:gz') as bundle:
                    for entry in entries:
                        bundle.addfile(*entry)
                return path

            licence = tarfile.TarInfo('LICENSE')
            licence.size = len(b'license\n')
            link = tarfile.TarInfo('deploy/LICENSE')
            link.type, link.linkname = tarfile.SYMTYPE, '../LICENSE'
            good = archive('good.tar.gz', [(licence, io.BytesIO(b'license\n')), (link,)])
            agentx.unpack(good, root / 'source')
            self.assertEqual((root / 'source/deploy/LICENSE').read_text(), 'license\n')
            escape = tarfile.TarInfo('deploy/escape')
            escape.type, escape.linkname = tarfile.SYMTYPE, '../../outside'
            for entries in ([(escape,)], [(tarfile.TarInfo('../outside'), io.BytesIO(b''))]):
                with self.assertRaisesRegex(RuntimeError, 'Unexpected entry'):
                    agentx.unpack(archive('bad.tar.gz', entries), root / 'other')
                self.assertFalse((root / 'other').exists())

    def test_prepare_aiperf_stages_the_host_without_creating_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(demo, 'ROOT', root), mock.patch.object(demo, 'CURRENT_RUN', root / 'current.json'), \
                    mock.patch.object(agentx, 'stage') as stage, \
                    mock.patch.object(sys, 'argv', ['demo', 'prepare-aiperf']):
                intro.main()
            stage.assert_called_once_with(LOCK)
            self.assertEqual(list(root.iterdir()), [])

    def test_steps_and_actions_stay_paired(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = intro.IntroDemo(SimpleNamespace(run=Path(directory) / 'run', rehearsal=True, action='run',
                                                       preview=False, auto=True))
            actions = instance.actions()
            self.assertEqual(len(actions), len(intro.STEPS))
            self.assertEqual(actions[:4], [instance.deployment, instance.startup, instance.endpoint, instance.request])
            self.assertEqual([a.args for a in actions[-2:]], [(1,), (8,)])


if __name__ == '__main__':
    unittest.main()
