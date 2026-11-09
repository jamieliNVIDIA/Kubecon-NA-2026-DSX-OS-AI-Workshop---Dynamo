"""Worker readiness must not be mistaken for frontend model discovery."""
from tests.support import ROOT
import importlib.util
import unittest
import urllib.error

SOURCE = ROOT / 'reports/overnight-2026-11-04/routing-c32/ready.py'
SPEC = importlib.util.spec_from_file_location('routing_model_readiness', SOURCE)
ready = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ready)


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class ModelReadinessTests(unittest.TestCase):
    def wait(self, fetch, **kwargs):
        clock = Clock()
        return ready.wait_for_model(fetch, 'expected-model', timeout=3, interval=1,
                                    monotonic=clock.monotonic, sleep=clock.sleep, **kwargs)

    def test_model_published_after_ready_worker_is_accepted(self):
        responses = iter([{'data': []}, {'data': [{'id': 'different-model'}]},
                          {'data': [{'id': 'expected-model'}]}])
        receipt = self.wait(lambda timeout: next(responses))
        self.assertTrue(receipt['passed'])
        self.assertEqual(receipt['attempts'], 3)
        self.assertEqual(receipt['elapsed_seconds'], 2)

    def test_wrong_model_or_http_200_alone_never_passes(self):
        with self.assertRaises(ready.ModelReadinessTimeout) as caught:
            self.wait(lambda timeout: {'data': [{'id': 'expected-model-other'}]})
        self.assertFalse(caught.exception.receipt['passed'])
        self.assertEqual(caught.exception.receipt['elapsed_seconds'], 3)

    def test_temporary_http_failure_is_recorded_then_recovers(self):
        calls = []
        def fetch(timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.HTTPError('http://frontend/v1/models', 503, 'starting', None, None)
            return {'data': [{'id': 'expected-model'}]}
        receipt = self.wait(fetch)
        self.assertTrue(receipt['passed'])
        self.assertIn('HTTPError', receipt['observations'][0]['error'])
        self.assertLessEqual(calls[-1], 2)

    def test_stalled_or_malformed_listing_stops_at_deadline(self):
        with self.assertRaises(ready.ModelReadinessTimeout) as caught:
            self.wait(lambda timeout: {'object': 'list'})
        self.assertEqual(caught.exception.receipt['attempts'], 3)
        self.assertEqual(caught.exception.receipt['elapsed_seconds'], 3)

    def test_fetch_consuming_the_remaining_budget_cannot_pass_late(self):
        clock = Clock()
        def fetch(timeout):
            clock.value += timeout + 0.1
            return {'data': [{'id': 'expected-model'}]}
        with self.assertRaises(ready.ModelReadinessTimeout):
            ready.wait_for_model(fetch, 'expected-model', timeout=1, interval=1,
                                 monotonic=clock.monotonic, sleep=clock.sleep)


if __name__ == '__main__':
    unittest.main()
