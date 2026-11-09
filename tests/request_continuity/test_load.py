"""Concurrent HTTP-load integrity and pinned assignment gates."""
from tests.support import ROOT
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import demos.request_continuity.load as load
import demos.common.runtime as ui


class IntegrityTests(unittest.TestCase):
    def assignment(self):
        return ui.read_json(ROOT / 'configs/dgd/workshop-request-continuity/overnight-gpu-assignment.json')

    def test_only_assigned_nodes_and_gpu_uuids_render(self):
        value = self.assignment()
        graph, claim = load.assigned_render('dynamo-ft-check', ui.read_json(ui.MODEL_LOCK), 'enabled', value)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        spec = worker['podTemplate']['spec']
        expression = spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][
            'nodeSelectorTerms'][0]['matchExpressions'][0]
        self.assertEqual(set(expression['values']), set(value['nodes']))
        self.assertTrue(spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'])
        cel = claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'][0]['cel']['expression']
        for uuids in value['nodes'].values():
            for uuid in uuids:
                self.assertIn(uuid, cel)
        self.assertEqual(worker['replicas'], 2)

    def test_duplicate_or_partial_hardware_refused(self):
        value = self.assignment()
        names = list(value['nodes'])
        value['nodes'][names[1]] = value['nodes'][names[0]]
        with self.assertRaises(ValueError):
            load.validate_assignment(value)
        value = self.assignment()
        value['nodes'][names[0]][0] = 'GPU-fake'
        with self.assertRaises(ValueError):
            load.validate_assignment(value)

    def test_http_200_and_done_are_insufficient(self):
        value = {'events': [{'type': 'done', 'seconds': 1}], 'http_status': 200,
                 'request_count': 1, 'read_error': None}
        self.assertFalse(load.stream_summary(value, 'model')['successful_completion'])

    def test_gaps_are_client_gaps_and_sticky_worker_remains_explicit(self):
        chunk = lambda text, finish=None: {'type': 'chunk', 'chunk': {'model': 'model', 'id': 'r',
            'choices': [{'delta': {'content': text}, 'finish_reason': finish}]}, 'content': text, 'worker': 'old'}
        events = [dict(chunk('x'), seconds=1), dict(chunk('y'), seconds=4),
                  dict(chunk('', 'stop'), seconds=5), {'type': 'done', 'seconds': 6}]
        value = {'events': events, 'http_status': 200, 'request_count': 1, 'read_error': None}
        result = load.stream_summary(value, 'model')
        self.assertTrue(result['successful_completion'])
        self.assertEqual(result['ttft_seconds'], 1)
        self.assertEqual(result['max_client_inter_content_gap_seconds'], 3)
        self.assertIsNone(result['exact_handoff_gap_seconds'])
        self.assertEqual(result['sse_initial_worker'], 'old')

    def test_real_local_sse_captures_four_overlapping_clients_once(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append(request)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for i in range(24):
                    value = {'model': 'model', 'id': 'response', 'nvext': {'worker_id': {'decode_worker_id': 1}},
                             'choices': [{'delta': {'content': 'x'}, 'finish_reason': None}]}
                    self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                    self.wfile.flush()
                    time.sleep(.005)
                value['choices'] = [{'delta': {}, 'finish_reason': 'stop'}]
                self.wfile.write(('data: ' + json.dumps(value) + '\n\ndata: [DONE]\n\n').encode())
                self.wfile.flush()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'batch'
                faults = []
                def fault(worker, path):
                    faults.append((worker, path))
                    return {'signal_sent': True}
                results, summaries = load.capture_batch('http://127.0.0.1:' + str(server.server_port),
                    {'model': 'model', 'stream': True}, target, fault=fault)
                self.assertEqual(len(seen), 4)
                self.assertEqual(len(faults), 1)
                self.assertEqual(faults[0][0], '1')
                self.assertTrue(all(s['successful_completion'] for s in summaries.values()))
                self.assertEqual(len(ui.read_json(target / 'load-at-fault.json')['outstanding_client_indices']), 4)
                self.assertEqual(len(results), 4)
                with self.assertRaises(FileExistsError):
                    load.capture_batch('http://invalid', {'model': 'model'}, target)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
