"""Presenter panes stay read-only, bounded and clear about saved observations."""
from tests.support import ROOT
import contextlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from demos.common import runtime as ui, support
from demos.common.presentation import request_text, response_text, shell_command


class SharedPresentationTests(unittest.TestCase):
    def test_phase_table_matches_workers_by_name_with_optional_loader_rows(self):
        def phase(name, seconds, status='done'):
            return {'name': name, 'seconds': seconds, 'status': status}
        workers = {
            'prefill': {'phases': [phase('Model setup', 4), phase('Weight loading', 30), phase('Engine init', None, 'unknown')]},
            'decode': {'phases': [phase('Model loading', 20), phase('Model setup', 5),
                                  phase('Weight loading', 10), phase('  Peer copy', 3), phase('Engine init', 7)]},
        }
        table = support.worker_phase_table(workers)
        self.assertIn('not timed', table)
        self.assertLess(table.index('Model loading'), table.index('Model setup'))
        self.assertLess(table.index('  Peer copy'), table.index('Engine init'))
        loading = next(line for line in table.splitlines() if line.startswith('Weight loading'))
        self.assertLess(loading.index('30.0s'), loading.index('10.0s'))
        engine = next(line for line in table.splitlines() if line.startswith('Engine init'))
        self.assertIn('not timed', engine)
        self.assertIn('7.0s', engine)

    def test_observer_marks_api_failure_before_saved_timings_without_writing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            state = {'namespace': 'dynamo-ft-observer', 'rehearsal': False, 'prepared': True,
                     'pod_selector': 'workshop-role', 'resource_kinds': 'dgd',
                     'startup': {'total_seconds': 120, 'phases': []}}
            ui.write_json(path / 'demo.json', state)
            before = (path / 'demo.json').read_bytes()
            output = io.StringIO()
            failed = subprocess.CompletedProcess([], 124, '', 'Resource read timed out.')
            with mock.patch.object(ui, 'panel_read', return_value=failed) as read, contextlib.redirect_stdout(output):
                support.observe(path, 'resources', once=True)
            self.assertEqual(read.call_count, 2)
            self.assertIn('current readiness is unknown', output.getvalue())
            self.assertLess(output.getvalue().index('Observer disconnected'), output.getvalue().index('Apply to Ready'))
            self.assertEqual((path / 'demo.json').read_bytes(), before)

    def test_resource_observer_rejects_invalid_api_payload(self):
        data = {'namespace': 'dynamo-ft-observer', 'pod_selector': 'workshop-role'}
        for payload in ('{invalid', '{"items":null}', '{"items":[{"kind":"Pod","metadata":null}]}',
                        '{"items":[{"kind":"Pod","metadata":{"name":"worker"},"status":null}]}'):
            with self.subTest(payload=payload), mock.patch.object(
                    ui, 'panel_read', return_value=subprocess.CompletedProcess([], 0, payload, '')):
                items, errors = support.resource_observations(data)
            self.assertFalse(items)
            self.assertIn('invalid snapshot', errors[0])

    def test_wrapping_preserves_exact_shell_arguments_including_quoted_payloads(self):
        arguments = ['curl', '--data', '{"message":"literal $HOME and `date`"}',
                     '--output', '/some path/with spaces/result.json', '--header', 'X-Literal: a b']
        rendered = shell_command(arguments, width=55)
        self.assertIn('\\\n', rendered)
        self.assertEqual(shlex.split(rendered.replace('\\\n', '')), arguments)
        self.assertEqual(shell_command(['cat', 'settings.yaml']), 'cat settings.yaml')

    def test_request_and_answer_projection_preserve_original_payloads(self):
        body = {'model': 'actual-model', 'stream': True, 'max_completion_tokens': 64,
                'messages': [{'role': 'user', 'content': 'Write a Python function. ' * 12}]}
        response = {'choices': [{'message': {'content': 'def add(a, b):\n    return a + b'}}],
                    'usage': {'completion_tokens': 12}}
        before = json.dumps({'body': body, 'response': response})
        prompt, answer = request_text(body), response_text(response)
        self.assertIn('full JSON: request.json', prompt)
        self.assertIn('max_completion_tokens: 64', prompt)
        self.assertLessEqual(max(map(len, prompt.splitlines())), 100)
        self.assertIn('def add(a, b):\n    return a + b', answer)
        self.assertIn('Output tokens: 12', answer)
        self.assertEqual(json.dumps({'body': body, 'response': response}), before)
        code_prompt = {'messages': [{'role': 'user', 'content': 'Read this code:\ndef add(a, b):\n    return a + b'}]}
        self.assertIn('    def add(a, b):\n        return a + b', request_text(code_prompt))

    def test_resumed_steps_keep_absolute_numbers_and_have_no_click_wait_timing(self):
        instance = object.__new__(ui.Demo)
        instance.path, instance.args = Path('/some/run'), SimpleNamespace(rehearsal=True)
        instance.data, instance.forward, instance.compact_output = {}, None, True
        instance.pause, instance.save = mock.Mock(), mock.Mock()
        events = []
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            instance.run_steps([('Replace', 'Recover'), ('Verify', 'Check identity')],
                               [lambda: events.append('replace'), lambda: events.append('verify')], start=2, total=4)
        self.assertEqual(events, ['replace', 'verify'])
        self.assertEqual(instance.data['step'], 3)
        self.assertIn('2/4  Replace', output.getvalue())
        self.assertIn('3/4  Verify', output.getvalue())
        self.assertNotIn('Step finished', output.getvalue())


if __name__ == '__main__':
    unittest.main()
