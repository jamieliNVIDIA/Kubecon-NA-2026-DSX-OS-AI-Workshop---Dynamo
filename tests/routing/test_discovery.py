"""Regression coverage for the actual socket-topic qualification failure."""
from tests.support import ROOT
import importlib.util
import unittest

PATH = ROOT / 'reports/workshop-measurements-20261030/rr-kv/discovery.py'
SPEC = importlib.util.spec_from_file_location('rrkv_discovery', PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DiscoveryTest(unittest.TestCase):
    ips = ['192.168.1.2', '192.168.1.3']

    def lines(self):
        return '\n'.join([
            'Adding worker WorkerWithDpRank { worker_id: 123, dp_rank: 0 }',
            'Adding worker WorkerWithDpRank { worker_id: 456, dp_rank: 0 }',
        ] + [f'ZMQ single-consumer stream connected endpoint="tcp://{ip}:33445" topic="{topic}"'
             for topic in ['kv_metrics', 'kv-events', 'active_sequences_events'] for ip in self.ips])

    def check(self, text, smoke=('123',), mode='kv'):
        return MODULE.inspect(text, self.ips, smoke, mode)

    def test_six_topic_connections_are_two_kv_sources(self):
        proof = self.check(self.lines())
        self.assertTrue(proof['passed'], proof)
        self.assertEqual(len(proof['zmq_endpoints_by_topic']), 3)
        self.assertEqual(proof['kv_event_source_hosts'], self.ips)

    def test_repeated_connections_do_not_inflate_worker_count(self):
        self.assertTrue(self.check(self.lines() + '\n' + self.lines())['passed'])

    def test_missing_kv_source_is_rejected_despite_other_topics(self):
        text = '\n'.join(line for line in self.lines().splitlines()
                         if not ('192.168.1.3' in line and 'topic="kv-events"' in line))
        self.assertFalse(self.check(text)['passed'])

    def test_foreign_host_is_rejected(self):
        self.assertFalse(self.check(self.lines().replace('192.168.1.3', '192.168.1.4'))['passed'])

    def test_missing_registered_worker_is_rejected(self):
        self.assertFalse(self.check(self.lines().replace('worker_id: 456', 'worker_id: 123'))['passed'])

    def test_unknown_smoke_worker_is_rejected(self):
        self.assertFalse(self.check(self.lines(), smoke=('789',))['passed'])

    def test_kv_smoke_may_select_one_worker(self):
        self.assertTrue(self.check(self.lines(), smoke=('123',) * 4)['passed'])

    def test_rr_requires_both_smoke_workers(self):
        self.assertFalse(self.check('', mode='round-robin')['passed'])
        self.assertTrue(self.check('', smoke=('123', '456'), mode='round-robin')['passed'])


if __name__ == '__main__':
    unittest.main()
