"""A finite Run request timeout must not terminate a long-lived log stream."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from demos.shadow.follow_policy import unlimited_stream_base, UnlimitedLogFollowers


class FollowTimeoutTests(unittest.TestCase):
    def test_equal_form_inherited_timeout_is_replaced(self):
        result = unlimited_stream_base(['kubectl', '--kubeconfig=local', '--request-timeout=30s'])
        self.assertEqual(result, ['kubectl', '--kubeconfig=local', '--request-timeout=0'])

    def test_split_form_and_repeated_defaults_cannot_override_stream_policy(self):
        result = unlimited_stream_base(['kubectl', '--request-timeout', '30s', '--context=workshop', '--request-timeout=15s'])
        self.assertEqual(result, ['kubectl', '--context=workshop', '--request-timeout=0'])

    def test_future_follower_uses_unlimited_base_and_keeps_bounded_get_override(self):
        run = SimpleNamespace(ns='test', path=Path('/offline'), kbase=['kubectl', '--request-timeout=30s'])
        follower = UnlimitedLogFollowers(run)
        self.assertEqual(follower.kbase[-1], '--request-timeout=0')
        bounded_get = follower.kbase + ['get', 'pods', '--request-timeout=8s']
        self.assertEqual(bounded_get[-1], '--request-timeout=8s')

    def test_malformed_split_flag_is_refused(self):
        with self.assertRaises(ValueError): unlimited_stream_base(['kubectl', '--request-timeout'])


if __name__ == '__main__': unittest.main()
