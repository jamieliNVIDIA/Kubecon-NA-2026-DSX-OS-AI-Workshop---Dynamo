"""KVCR presenter safety, evidence matching and offline flow regressions."""
import contextlib
from collections import UserDict
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

import demos.common.runtime as ui
import demos.kvcr.demo as demo
import demos.kvcr.guard as guard
import demos.kvcr.prepare_sources as sources
import kvcr_guard_runtime as runtime


def args(path):
    return SimpleNamespace(run=Path(path), action='run', rehearsal=True, preview=False,
        auto=True, plain=True, port=18007, timeout=60, placement=None, source_bundle=None)


def metrics(blocks=0, size=0, tokens=0, failed=0):
    return '\n'.join([
        'vllm:kvcr_transfer_blocks_total{operation="remote_deliver"} ' + str(blocks),
        'vllm:kv_offload_tiering_read_bytes_total{tier="1:kvcr"} ' + str(size),
        'vllm:prompt_tokens_by_source_total{source="external_kv_transfer"} ' + str(tokens),
        'vllm:kvcr_duration_seconds_count{scope="remote_deliver",result="failed"} ' + str(failed),
    ])


def proof_inputs():
    return ({'a': '', 'b': metrics()}, {'a': '', 'b': metrics(3, 4096, 192)},
            'KVCR_EVENT source_transfer_completed op=wire source_op=local blocks=3 bytes=4096 result=success',
            'KVCR_EVENT target_transfer_completed scope=remote_deliver op=wire source=tcp://1.2.3.4:23280 blocks=3 bytes=4096 result=success',
            '1.2.3.4', {'workers': ['A']}, {'workers': ['B'], 'usage': {
                'prompt_tokens': 512, 'prompt_tokens_details': {'cached_tokens': 192}}})


def legacy_payload():
    """The two-request READY payload that legacy runs and prepared children freeze."""
    model = ui.read_json(ui.MODEL_LOCK)
    context = demo.coding_prefix('fixture')
    return {'model': model['model'], 'revision': model['revision'], 'requests': {
        'source': demo.request_body(model['model'], context + demo.SOURCE_SUFFIX),
        'target': demo.request_body(model['model'], context + demo.TARGET_SUFFIX)}}


def tokenized(payload, source=6467, target=6468, common=6453):
    return {'model': payload['model'], 'revision': payload['revision'],
            'input_sha256': demo.object_sha256(payload),
            'request_sha256': {r: demo.object_sha256(b) for r, b in payload['requests'].items()},
            'source_prompt_tokens': source, 'target_prompt_tokens': target, 'common_prefix_tokens': common}


def speedup_tokenized(payload, shared=52000, warmup=9300, cold=12, control=52010):
    return {'model': payload['model'], 'revision': payload['revision'],
            'input_sha256': demo.object_sha256(payload),
            'request_sha256': {r: demo.object_sha256(b) for r, b in payload['requests'].items()},
            'prompt_tokens': {'warmup_main': warmup + 30, 'warmup_sub': warmup + 40, 'main': shared + 30,
                              'control': control + 40, 'sub': shared + 40},
            'common_prefix_tokens': {'main/sub': shared, 'warmup_main/warmup_sub': warmup,
                                     'control/sub': cold, 'control/main': cold}}


GEOMETRY = {'effective_page_tokens': 4224, 'context_limit_tokens': 8192}
SPEEDUP_GEOMETRY = {'effective_page_tokens': 4224, 'context_limit_tokens': 65536}
LOG_GEOMETRY = ('2026-11-05T16:17:12Z Using max model len 8192\n'
                'Setting attention block size to 4224 tokens to ensure that attention page size is >= mamba page size.\n')
SPEEDUP_LOG_GEOMETRY = LOG_GEOMETRY.replace('8192', '65536')


def batch_tokenizer(ids_for):
    class BatchEncoding(UserDict):
        """Mock Hugging Face's real UserDict/Mapping result protocol."""
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            if kwargs != {'tokenize': True, 'add_generation_prompt': True, 'return_dict': True, 'enable_thinking': False}:
                raise AssertionError('Unexpected chat-template arguments')
            # Current Hugging Face can return a BatchEncoding/Mapping,
            # rather than a bare list when tokenizing a chat template.
            return BatchEncoding({'input_ids': ids_for(messages), 'attention_mask': [1]})
    transformer = ModuleType('transformers')
    transformer.__version__ = 'fixture'
    transformer.AutoTokenizer = SimpleNamespace(from_pretrained=lambda *a, **k: Tokenizer())
    return transformer


def run_program(program, payload, transformer):
    with mock.patch.dict(sys.modules, {'transformers': transformer}), \
            mock.patch.dict(os.environ, {'KVCR_MODEL': payload['model'], 'KVCR_MODEL_REVISION': payload['revision']}), \
            mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), \
            contextlib.redirect_stdout(io.StringIO()) as output:
        exec(compile(program, 'tokenizer-probe', 'exec'), {})
    return json.loads(output.getvalue())


def chunk(worker, content='', finish=None, timing=None, usage=None):
    value = {'id': 'one', 'model': ui.read_json(ui.MODEL_LOCK)['model'],
             'choices': [{'delta': {'content': content}, 'finish_reason': finish}],
             'nvext': {'worker_id': {'decode_worker_id': worker}}}
    if timing:
        value['nvext']['timing'] = timing
    if usage:
        value['usage'] = usage
    return 'data: ' + json.dumps(value) + '\n\n'


class Stream(io.BytesIO):
    status = 200


class KVCRDemoTests(unittest.TestCase):
    def test_legacy_tokenizer_program_accepts_mapping_output_and_preserves_token_sequence(self):
        payload = legacy_payload()
        source = payload['requests']['source']['messages']
        transformer = batch_tokenizer(lambda m: [101, 201, 301, 401, 501] if m == source else [101, 201, 301, 999])
        record = run_program(demo.TOKENIZER_PROGRAM, payload, transformer)
        self.assertEqual((record['source_prompt_tokens'], record['target_prompt_tokens'], record['common_prefix_tokens']), (5, 4, 3))
        self.assertEqual(record['request_sha256'], {r: demo.object_sha256(b) for r, b in payload['requests'].items()})
        self.assertTrue(record['tokenizer_output_types']['source'].endswith('.BatchEncoding'))
        self.assertEqual(record['input_ids_types']['source'], 'builtins.list')

    def test_speedup_tokenizer_program_measures_every_request_and_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            payload = ui.read_json(d.path / 'prompt-preflight-input.json')
            record = run_program(demo.SPEEDUP_TOKENIZER_PROGRAM, payload,
                                 batch_tokenizer(lambda m: [ord(c) for c in m[0]['content']]))
            shared = len((d.path / 'shared-context.txt').read_text())
            self.assertEqual(set(record['prompt_tokens']), set(demo.ROLES))
            # Both agents append '\n\n' before their different tasks.
            self.assertEqual(record['common_prefix_tokens']['main/sub'], shared + 2)
            self.assertLess(record['common_prefix_tokens']['control/sub'], 64)
            self.assertEqual(record['request_sha256'], {r: demo.object_sha256(b) for r, b in payload['requests'].items()})

    def test_repository_fixture_is_deterministic_and_plants_each_function_once(self):
        text, paths = demo.repository('tag-one', 64, demo.PLANTED)
        self.assertEqual(demo.repository('tag-one', 64, demo.PLANTED), (text, paths))
        self.assertNotEqual(demo.repository('tag-two', 64, demo.PLANTED)[0], text)
        self.assertEqual(sorted(p.rsplit('/', 1)[1] for p in paths.values()),
                         sorted(f + '.py' for f in demo.PLANTED_FILES))
        for name, path in paths.items():
            self.assertEqual(text.count('def ' + name + '('), 1)
            self.assertEqual(text.count('# ' + path + '\n'), 1)
            section = text[text.index('# ' + path):]
            self.assertLess(section.index('def ' + name + '('), section.index('\n# repository/'))
        self.assertIn(demo.PLANTED[1], demo.task('sub', demo.PLANTED[1]))

    def test_effective_geometry_requires_live_logs_not_requested_block_flag(self):
        self.assertEqual(demo.runtime_geometry(LOG_GEOMETRY), GEOMETRY)
        for text in ('--block-size 64 --max-model-len 8192', '',
                     LOG_GEOMETRY + 'Setting attention block size to 64 tokens'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                demo.runtime_geometry(text)

    def test_legacy_prompt_preflight_rejects_a3_sizing_and_mismatched_or_overflowing_inputs(self):
        payload = legacy_payload()
        geometry = {'a': GEOMETRY, 'b': GEOMETRY}
        self.assertEqual(demo.prompt_preflight_proof(payload, tokenized(payload), geometry)['status'], 'passed')
        for values, shapes in [
            (tokenized(payload, 3247, 3248, 3230), geometry),
            (tokenized(payload, 8200, 8201, 6500), geometry),
            (tokenized(payload, common=7000), geometry),
            ({**tokenized(payload), 'revision': 'wrong'}, geometry),
            ({**tokenized(payload), 'input_sha256': 'wrong'}, geometry),
            ({**tokenized(payload), 'common_prefix_tokens': True}, geometry),
            (tokenized(payload), {'a': GEOMETRY, 'b': {**GEOMETRY, 'effective_page_tokens': 64}}),
            (tokenized(payload), {'a': {**GEOMETRY, 'effective_page_tokens': 0}, 'b': GEOMETRY}),
        ]:
            with self.subTest(values=values, shapes=shapes), self.assertRaises(ValueError):
                demo.prompt_preflight_proof(payload, values, shapes)

    def test_speedup_preflight_needs_long_shared_prefix_cold_like_for_like_control_and_room(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            payload = ui.read_json(d.path / 'prompt-preflight-input.json')
            geometry = {'a': SPEEDUP_GEOMETRY, 'b': SPEEDUP_GEOMETRY}
            proof = demo.speedup_preflight_proof(payload, speedup_tokenized(payload), geometry)
            self.assertEqual((proof['status'], proof['reusable_pages']), ('passed', 12))
            for values, shapes, message in [
                (speedup_tokenized(payload, shared=30000), geometry, 'below 10 effective'),
                (speedup_tokenized(payload, warmup=4000), geometry, 'Warm-up context'),
                (speedup_tokenized(payload, cold=4224), geometry, 'shares a reusable page'),
                (speedup_tokenized(payload, control=54500), geometry, 'like for like'),
                (speedup_tokenized(payload, shared=65500, control=65510), geometry, 'exceeds the live engine'),
                (speedup_tokenized(payload), {'a': GEOMETRY, 'b': GEOMETRY}, 'exceeds the live engine'),
                (speedup_tokenized(payload), {'a': SPEEDUP_GEOMETRY, 'b': GEOMETRY}, 'do not match'),
                ({**speedup_tokenized(payload), 'input_sha256': 'wrong'}, geometry, 'do not match'),
                ({**speedup_tokenized(payload), 'prompt_tokens': {'main': 1}}, geometry, 'every request'),
            ]:
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    demo.speedup_preflight_proof(payload, values, shapes)

    def test_short_preflight_prevents_any_request_entirely(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = d.data['rehearsal'] = False
            payload = ui.read_json(d.path / 'prompt-preflight-input.json')
            pods = {p: {'metadata': {'name': 'pod-' + p, 'uid': p}} for p in 'ab'}
            def command(*values, **kwargs):
                text = SPEEDUP_LOG_GEOMETRY if values[0] == 'logs' else json.dumps(speedup_tokenized(payload, shared=30000))
                return SimpleNamespace(stdout=text, stderr='')
            with mock.patch.object(d, 'check_identity'), mock.patch.object(d, 'peers', return_value=pods), \
                    mock.patch.object(d.run, 'k', side_effect=command), mock.patch.object(d, 'endpoint') as endpoint, \
                    mock.patch.object(demo, 'stream_request') as http:
                with self.assertRaisesRegex(ValueError, 'no request sent'):
                    d.main_agent()
                endpoint.assert_not_called()
                http.assert_not_called()
            self.assertFalse((d.path / 'main').exists())
            self.assertFalse(ui.read_json(d.path / 'prompt-preflight-failure.json')['source_request_sent'])

    def test_live_preflight_is_bound_to_inputs_and_worker_identity_without_reexecution(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = d.data['rehearsal'] = False
            payload = ui.read_json(d.path / 'prompt-preflight-input.json')
            pods = {p: {'metadata': {'name': 'pod-' + p, 'uid': p}} for p in 'ab'}
            def command(*values, **kwargs):
                if values[0] == 'exec':
                    self.assertEqual(json.loads(kwargs['input_text']), payload)
                    text = json.dumps(speedup_tokenized(payload))
                else:
                    text = SPEEDUP_LOG_GEOMETRY
                return SimpleNamespace(stdout=text, stderr='')
            with mock.patch.object(d, 'check_identity'), mock.patch.object(d, 'peers', return_value=pods), \
                    mock.patch.object(d.run, 'k', side_effect=command) as calls, contextlib.redirect_stdout(io.StringIO()):
                first = d.ensure_prompt_preflight()
                count = calls.call_count
                self.assertEqual(d.ensure_prompt_preflight(), first)
                self.assertEqual(calls.call_count, count)
                pods['b']['metadata']['uid'] = 'replacement'
                with self.assertRaisesRegex(ValueError, 'current worker Pods'):
                    d.ensure_prompt_preflight()
            self.assertEqual(first['common_prefix_tokens']['main/sub'], 52000)
            self.assertEqual(first['context_limit_tokens'], 65536)
            self.assertTrue(first['checked_before_source_request'])

    def test_frozen_preflight_body_matches_actual_guard_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SimpleNamespace(path=Path(directory), state={'model_lock': {'model': 'model'}})
            chunk = {'id': 'one', 'model': 'model', 'choices': [{'delta': {'content': 'READY'}, 'finish_reason': 'stop'}],
                     'nvext': {'worker_id': {'decode_worker_id': 'A'}}, 'usage': {'prompt_tokens': 6000, 'completion_tokens': 3}}
            def urlopen(request, timeout):
                self.assertEqual(json.loads(request.data), demo.request_body('model', 'context'))
                return Stream(('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n').encode())
            with mock.patch('urllib.request.urlopen', side_effect=urlopen):
                guard.response(run, 'http://example.test', 'source', 'context', 'A')

    def test_stream_request_keeps_frontend_timing_and_rejects_another_worker(self):
        timing = {'ttft_ms': 412.5, 'prefill_time_ms': 400.0}
        usage = {'prompt_tokens': 52040, 'prompt_tokens_details': {'cached_tokens': 50688}}
        body = demo.speedup_body(ui.read_json(ui.MODEL_LOCK)['model'], 'repository\n\ntask')
        stream = (chunk('B', 'repository/api/') + chunk('B', 'x.py', 'stop', timing, usage) + 'data: [DONE]\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            def urlopen(request, timeout):
                self.assertEqual(json.loads(request.data), body)
                self.assertEqual(request.headers['X-dynamo-worker-instance-id'], 'B')
                return Stream(stream)
            with mock.patch('urllib.request.urlopen', side_effect=urlopen):
                proof = demo.stream_request('http://example.test', body, 'B', Path(directory) / 'sub')
            self.assertEqual((proof['content'], proof['timing'], proof['usage']), ('repository/api/x.py', timing, usage))
            self.assertEqual(demo.first_token_ms(proof), 412.5)
            self.assertEqual(ui.read_json(Path(directory) / 'sub/request.json'), body)
            with mock.patch('urllib.request.urlopen', return_value=Stream(stream)), \
                    self.assertRaisesRegex(ValueError, 'expected worker'):
                demo.stream_request('http://example.test', body, 'A', Path(directory) / 'other')
        self.assertEqual(demo.first_token_ms({'timing': None, 'client_first_token_seconds': 0.25}), 250)

    def test_runtime_keeps_guard_defaults_and_accepts_demo_context_overrides(self):
        env = {'KVCR_PEER': 'a', 'POD_IP': '10.0.0.1', 'KVCR_COMPATIBILITY_DIGEST': 'digest',
               'KVCR_MODEL': 'model', 'KVCR_MODEL_REVISION': 'revision'}
        flag = lambda argv, name: argv[argv.index(name) + 1]
        default = runtime.engine_args(env)
        self.assertEqual((flag(default, '--max-model-len'), flag(default, '--max-num-batched-tokens')), ('8192', '8192'))
        longer = runtime.engine_args({**env, 'KVCR_MAX_MODEL_LEN': '65536', 'KVCR_MAX_NUM_BATCHED_TOKENS': '8448'})
        self.assertEqual((flag(longer, '--max-model-len'), flag(longer, '--max-num-batched-tokens')), ('65536', '8448'))
        with self.assertRaises(ValueError):
            runtime.engine_args({**env, 'KVCR_MAX_MODEL_LEN': '64k'})

    def test_settle_waits_for_a_counter_to_move_and_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = False
            pods = {p: {'metadata': {'name': 'pod-' + p}} for p in 'ab'}
            readings = iter([metrics(), metrics(1, 10), metrics(2, 20), metrics(2, 20)])
            text = lambda pod: next(readings) if pod['metadata']['name'] == 'pod-b' else ''
            with mock.patch.object(d, 'peers', return_value=pods), mock.patch.object(d, 'metric_text', side_effect=text), \
                    mock.patch.object(demo.time, 'sleep'):
                after = d.settle('after-sub', 'b', 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'}, {'a': '', 'b': metrics()})
            self.assertEqual(after['b'], metrics(2, 20))
            self.assertEqual(d.snapshot('after-sub'), after)
            with mock.patch.object(d, 'peers', return_value=pods), mock.patch.object(d, 'metric_text', return_value=metrics()), \
                    mock.patch.object(demo.time, 'sleep'), mock.patch.object(demo.time, 'monotonic', side_effect=[0, 0, 100] * 2):
                with self.assertRaises(TimeoutError):
                    d.settle('never', 'b', 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'}, {'a': '', 'b': metrics()})
                d.settle('optional', 'b', 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'},
                         {'a': '', 'b': metrics()}, required=False)
            self.assertTrue((d.path / 'optional/snapshot.json').is_file())

    def test_control_request_must_be_a_cold_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = False
            d.forward = object()
            d.data['base_url'] = 'http://example.test'
            warm = {'usage': {'prompt_tokens': 52040, 'prompt_tokens_details': {'cached_tokens': 50688}}, 'content': '',
                    'expected_answer': 'x', 'answer_matches': False, 'timing': None}
            with mock.patch.object(d, 'check_identity'), mock.patch.object(d, 'snapshot', return_value={'a': '', 'b': metrics()}), \
                    mock.patch.object(d, 'show_request'), mock.patch.object(d, 'send', return_value=warm) as send, \
                    mock.patch.object(d, 'settle', return_value={'a': '', 'b': metrics()}), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'not a cold comparison'):
                d.subagents()
            self.assertEqual([c.args[0] for c in send.call_args_list], ['control'])

    def test_live_comparison_matches_receipts_and_reports_the_speedup(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = False
            for role, cached, ms, worker in (('main', 0, 3100.0, 'A'), ('control', 0, 3000.0, 'B'), ('sub', 192, 400.0, 'B')):
                (d.path / role).mkdir()
                ui.write_json(d.path / role / 'response.json', {
                    'workers': [worker], 'content': 'x', 'expected_answer': 'x', 'answer_matches': True,
                    'timing': {'ttft_ms': ms}, 'usage': {'prompt_tokens': 512, 'prompt_tokens_details': {'cached_tokens': cached}}})
            for label, text in (('after-control', metrics()), ('after-sub', metrics(3, 4096, 192))):
                d.snapshot(label, {'a': '', 'b': text})
            ui.write_json(d.path / 'warmup.json', {'efa_provider': True})
            pods = {'a': {'metadata': {'name': 'pod-a'}, 'status': {'podIP': '1.2.3.4'}}, 'b': {'metadata': {'name': 'pod-b'}}}
            logs = {'pod-a': proof_inputs()[2], 'pod-b': proof_inputs()[3]}
            def command(*values, **kwargs):
                self.assertTrue(any(v.startswith('--since-time=') for v in values))
                return SimpleNamespace(stdout=logs[values[1]])
            output = io.StringIO()
            with mock.patch.object(d, 'check_identity'), mock.patch.object(d, 'peers', return_value=pods), \
                    mock.patch.object(d.run, 'k', side_effect=command), contextlib.redirect_stdout(output):
                d.compare()
            summary = ui.read_json(d.path / 'speedup.json')
            self.assertEqual(summary['first_token_speedup'], 7.5)
            self.assertEqual(ui.read_json(d.path / 'peer-proof.json')['blocks'], 3)
            self.assertIn('7.5x sooner', output.getvalue())
            self.assertEqual(ui.read_json(d.path / 'response.json')['workers'], ['B'])

    def test_speedup_summary_compares_first_tokens_on_the_same_worker(self):
        rows = {role: {'usage': {'prompt_tokens': 52000, 'prompt_tokens_details': {'cached_tokens': cached}},
                       'timing': {'ttft_ms': ms}, 'answer_matches': True}
                for role, cached, ms in (('main', 0, 3100.0), ('control', 0, 3000.0), ('sub', 50688, 400.0))}
        summary = demo.speedup_summary(rows, {'blocks': 72, 'bytes': 1245708288, 'external_cache_tokens': 50688})
        self.assertEqual(summary['first_token_speedup'], 7.5)
        self.assertEqual(summary['rows']['sub']['cached_tokens'], 50688)
        self.assertEqual(demo.bar(400, 3000, 30), '████')

    def test_cpu_sizing_fails_short_fixture_before_gpu_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            payload = ui.read_json(d.path / 'prompt-preflight-input.json')
            with mock.patch('snapshot_tp2_workflow.cpu_probe', return_value=speedup_tokenized(payload, shared=30000)):
                with self.assertRaisesRegex(ValueError, 'below 10 effective'):
                    d.early_prompt_size_gate()
            self.assertFalse((d.path / 'prompt-size-cpu.json').exists())
            with mock.patch('snapshot_tp2_workflow.cpu_probe', return_value=speedup_tokenized(payload)) as probe, \
                    contextlib.redirect_stdout(io.StringIO()):
                d.early_prompt_size_gate()
            # The payload travels in one environment string, which Linux caps at 128 KiB.
            program, env = probe.call_args.args[2], {e['name']: e['value'] for e in probe.call_args.args[3]}
            self.assertLess(len(env['KVCR_PREFLIGHT_PAYLOAD']), 128 * 1024)
            with mock.patch.dict(os.environ, {'KVCR_PREFLIGHT_PAYLOAD': env['KVCR_PREFLIGHT_PAYLOAD']}), \
                    mock.patch.object(sys, 'stdin'):
                prefix = program[:program.index('import hashlib')]
                exec(compile(prefix, 'prefix', 'exec'), {})
                self.assertEqual(json.load(sys.stdin), payload)
            receipt = ui.read_json(d.path / 'prompt-size-cpu.json')
            self.assertFalse(receipt['live_geometry_qualified'])
            self.assertEqual(receipt['reference_geometry'], SPEEDUP_GEOMETRY)
            self.assertFalse((d.path / 'prompt-preflight.json').exists())

    def test_old_profile_can_still_be_cleaned_without_replaying_it(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.data['kvcr_profile'] = 'super-vl-kvcr-host-peer-nightly-v1'
            d.save()
            cleanup = args(directory)
            cleanup.action = 'cleanup'
            demo.KVCRDemo(cleanup)
            with self.assertRaisesRegex(ValueError, 'same mode/profile'):
                demo.KVCRDemo(args(directory))

    def test_legacy_runs_keep_the_two_request_walkthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            with contextlib.redirect_stdout(io.StringIO()):
                d.prime()
            d.data['kvcr_profile'] = demo.LEGACY_PROFILE
            d.save()
            d = demo.KVCRDemo(args(directory))
            self.assertTrue(d.legacy)
            with mock.patch.object(d, 'run_steps') as steps, contextlib.redirect_stdout(io.StringIO()):
                d.guided()
            self.assertEqual(steps.call_args.args[0], demo.STEPS)

    def test_public_sources_refuse_bad_hash_and_unapproved_host(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'artifact'
            record = {'url': 'https://raw.githubusercontent.com/project/rev/file', 'bytes': 4, 'sha256': 'bad'}
            with mock.patch.object(sources.urllib.request, 'urlopen', return_value=io.BytesIO(b'data')):
                with self.assertRaises(ValueError):
                    sources.fetch(record, path)
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                sources.fetch({**record, 'url': 'https://example.com/file'}, path)

    def test_render_binds_exact_pairs_budget_and_long_context(self):
        placement = ui.read_json(demo.PLACEMENT)
        lock = ui.read_json(ui.MODEL_LOCK)
        graph, claims = demo.render('dynamo-ft-test', lock, {'configmap': 'candidate', 'bundle_sha256': 'x'}, 'runtime', placement)
        self.assertEqual(len(claims), 2)
        self.assertEqual(graph['metadata']['name'], demo.GRAPH)
        for c in graph['spec']['components']:
            peer = c['podTemplate']['metadata']['labels'].get('kvcr-peer', 'a')
            spec = c['podTemplate']['spec']
            self.assertEqual(spec['nodeSelector']['kubernetes.io/hostname'], placement[peer]['node'])
            if c['type'] == 'worker':
                self.assertEqual(sum(int(x['resources']['requests'].get('vpc.amazonaws.com/efa', '0'))
                                     for x in spec['containers']), 5)
                self.assertEqual(spec['containers'][0]['image'], lock['runtime_image'])
                env = {e['name']: e.get('value') for e in spec['containers'][0]['env']}
                self.assertEqual((env['KVCR_MAX_MODEL_LEN'], env['KVCR_MAX_NUM_BATCHED_TOKENS']), ('65536', '8448'))
        for claim, peer in zip(claims, ('a', 'b')):
            exact = claim['spec']['spec']['devices']['requests'][0]['exactly']
            self.assertEqual(exact['count'], 2)
            self.assertTrue(all(u in exact['selectors'][0]['cel']['expression'] for u in placement[peer]['gpu_uuids']))

    def test_harness_globals_restore_after_error(self):
        original = guard.NODE, guard.GRAPH, guard.OWNER, ui.LEASE
        with self.assertRaises(RuntimeError), demo.harness_scope(ui.read_json(demo.PLACEMENT), Path('/tmp/new')):
            self.assertEqual(guard.OWNER, demo.OWNER)
            raise RuntimeError('stop')
        self.assertEqual((guard.NODE, guard.GRAPH, guard.OWNER, ui.LEASE), original)

    def test_placement_rejects_overlap(self):
        placement = ui.read_json(demo.PLACEMENT)
        placement['b']['gpu_uuids'][0] = placement['a']['gpu_uuids'][0]
        with self.assertRaises(ValueError):
            demo.validate_placement(placement)

    def test_transfer_needs_matching_wire_id_and_saved_computation(self):
        values = proof_inputs()
        self.assertEqual(demo.peer_proof(*values)['external_cache_tokens'], 192)
        for changed in [
            {1: {'a': '', 'b': metrics(3, 4096, 0)}},
            {1: {'a': '', 'b': metrics(3, 4096, 192, 1)}},
            {2: values[2].replace('op=wire ', 'op=other ')},
            {3: values[3].replace('source=tcp://1.2.3.4', 'source=tcp://9.9.9.9')},
            {6: {'workers': ['A'], 'usage': values[6]['usage']}},
            {6: {'workers': ['B'], 'usage': {'prompt_tokens': 512, 'prompt_tokens_details': {'cached_tokens': 0}}}},
        ]:
            bad = list(copy.deepcopy(values))
            for i, value in changed.items():
                bad[i] = value
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                demo.peer_proof(*bad)

    def test_log_interval_refuses_rotation(self):
        self.assertEqual(demo.interval_log('before', 'before after'), ' after')
        with self.assertRaises(ValueError):
            demo.interval_log('before', 'different')

    def test_completed_native_probe_uses_cuda_uuid_receipt_after_claim_gc(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            expected = sorted(d.placement['a']['gpu_uuids'])
            finished = {'metadata': {'uid': 'probe'}, 'status': {'containerStatuses': [
                {'imageID': d.data['candidate']['base_image']} ]}}
            logs = {'main': json.dumps({'status': 'passed', 'gpu_uuids': expected}),
                    'guard': 'using provider=efa\n' + json.dumps({'status': 'passed', 'GPU_devices': []})}
            def command(*values, **kwargs):
                text = logs[values[values.index('-c') + 1]] if values[0] == 'logs' else ''
                return SimpleNamespace(stdout=text)
            with mock.patch.object(d.run, 'apply'), mock.patch.object(d.run, 'wait_pod', return_value=finished), \
                    mock.patch.object(d.run, 'k', side_effect=command), \
                    mock.patch.object(d, 'allocated_uuids', side_effect=AssertionError('DRA claim already GCd')):
                d.native_gate('a')
            self.assertEqual(ui.read_json(Path(directory) / 'native-a.json')['gpu_uuids'], expected)

    def test_offline_flow_creates_no_false_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-B', '-m', 'demos', 'kvcr', '--rehearsal', '--plain',
                '--auto', '--run', directory], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NO CLUSTER CALLS', result.stdout)
            self.assertNotIn('Enter or Space', result.stdout)
            self.assertNotIn('Startup timing:', result.stdout)
            self.assertNotIn('Commands shown relative', result.stdout)
            self.assertNotIn('Tokenizer/page preflight', result.stdout)
            self.assertNotIn('Answer: ', result.stdout)
            self.assertEqual(result.stdout.count('Port forward and /v1/models response are simulated'), 1)
            self.assertLess(result.stdout.index('Workers ready:'), result.stdout.index('$ curl'))
            proof = ui.read_json(Path(directory) / 'peer-proof.json')
            self.assertTrue(proof['simulated'])
            self.assertIsNone(proof['bytes'])
            summary = ui.read_json(Path(directory) / 'speedup.json')
            self.assertTrue(summary['simulated'])
            self.assertIsNone(summary['first_token_speedup'])
            self.assertTrue(ui.read_json(Path(directory) / 'warmup.json')['simulated'])
            self.assertTrue(all(ui.read_json(p)['args'][0] == 'cat' for p in Path(directory).glob('command-*.json')))
            for role in demo.ROLES:
                body = ui.read_json(Path(directory) / (role + '-request.json'))
                self.assertEqual(body['model'], ui.read_json(ui.MODEL_LOCK)['model'])
                self.assertEqual(body['max_completion_tokens'], demo.ANSWER_TOKENS)

    def test_live_walkthrough_requires_completed_offstage_prime_before_any_action(self):
        for missing in ('prepared', 'ready_observed_at', 'prompt-preflight.json', 'prompt_preflight_sha256',
                        'warmup.json', 'warmup_sha256'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                d = demo.KVCRDemo(args(directory))
                d.args.rehearsal = d.data['rehearsal'] = False
                d.data.update(prepared=True, ready_observed_at='2026-11-07T01:00:00+00:00')
                for name, key in (('prompt-preflight.json', 'prompt_preflight_sha256'), ('warmup.json', 'warmup_sha256')):
                    receipt = d.path / name
                    ui.write_json(receipt, {'status': 'passed'})
                    d.data[key] = ui.digest(receipt)
                if missing.endswith('.json'):
                    (d.path / missing).unlink()
                else:
                    d.data.pop(missing)
                output = io.StringIO()
                with (mock.patch.object(d, 'prepare') as prepare,
                      mock.patch.object(d, 'deploy') as deploy,
                      mock.patch.object(d, 'wait') as wait,
                      mock.patch.object(d, 'run_steps') as steps,
                      mock.patch.object(d.run, 'k') as cluster,
                      contextlib.redirect_stdout(output),
                      self.assertRaisesRegex(RuntimeError, '-m demos kvcr prime --run')):
                    d.guided()
                for operation in (prepare, deploy, wait, steps, cluster):
                    operation.assert_not_called()
                self.assertNotIn('Dynamo workshop', output.getvalue())

    def test_ready_worker_step_never_deploys_or_prints_raw_startup_json(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            with contextlib.redirect_stdout(io.StringIO()):
                d.prime()
            output = io.StringIO()
            with (mock.patch.object(d, 'prepare') as prepare,
                  mock.patch.object(d, 'deploy') as deploy,
                  mock.patch.object(d, 'wait') as wait,
                  contextlib.redirect_stdout(output)):
                d.warm_workers()
            for operation in (prepare, deploy, wait):
                operation.assert_not_called()
            self.assertIn('Workers ready:', output.getvalue())
            self.assertNotIn('apply_to_observed_ready_seconds', output.getvalue())
            self.assertNotIn('Startup timing:', output.getvalue())

    def test_unprimed_live_run_fails_before_creating_tmux_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.rehearsal = d.data['rehearsal'] = False
            with (mock.patch.object(sys, 'argv', ['kvcr']),
                  mock.patch.object(demo, 'KVCRDemo', return_value=d),
                  mock.patch.object(ui, 'tmux_layout') as layout,
                  contextlib.redirect_stdout(io.StringIO()),
                  self.assertRaisesRegex(RuntimeError, '-m demos kvcr prime --run')):
                demo.main()
            layout.assert_not_called()

    def test_interactive_rehearsal_prepares_simulated_workers_without_an_invisible_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            d.args.auto = False
            modes = []
            original_prime = d.prime
            def prime():
                modes.append(d.args.auto)
                original_prime()
            with (mock.patch.object(demo.sys.stdin, 'isatty', return_value=True),
                  mock.patch.object(d, 'prime', side_effect=prime),
                  mock.patch.object(d, 'pause', side_effect=lambda: modes.append(d.args.auto)),
                  mock.patch.object(d, 'run_steps') as steps,
                  contextlib.redirect_stdout(io.StringIO())):
                d.guided()
            self.assertEqual(modes, [True, True])
            self.assertFalse(d.args.auto)
            steps.assert_called_once()
            self.assertTrue(d.data['ready_observed_at'])

    def test_preview_does_not_prepare_sources_or_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            with mock.patch.object(d.run, 'k', side_effect=AssertionError('cluster')), contextlib.redirect_stdout(io.StringIO()):
                d.preview()

    def test_interrupted_preparation_requires_fresh_run_before_cluster_access(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            ui.write_json(Path(directory) / 'model-lock.json', {})
            d.args.rehearsal = False
            with mock.patch.object(d.run, 'k', side_effect=AssertionError('cluster')):
                with self.assertRaisesRegex(RuntimeError, 'prime a fresh'):
                    d.prepare()

    def test_resume_retains_completed_requests_and_refuses_partial_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            d = demo.KVCRDemo(args(directory))
            with contextlib.redirect_stdout(io.StringIO()):
                d.guided()
                previous = {r: d.data[r + '_completed_at'] for r in ('main', 'control', 'sub')}
                with mock.patch.object(d, 'endpoint', side_effect=AssertionError('no new HTTP')), \
                        mock.patch.object(demo, 'stream_request', side_effect=AssertionError('no new HTTP')):
                    d.main_agent()
                    d.subagents()
                self.assertEqual(previous, {r: d.data[r + '_completed_at'] for r in ('main', 'control', 'sub')})
                # A partial request without terminal proof cannot be replayed.
                d.data.pop('sub_completed_at')
                with self.assertRaisesRegex(ValueError, 'already started'):
                    d.send('sub', 'http://example.test')


if __name__ == '__main__':
    unittest.main()
