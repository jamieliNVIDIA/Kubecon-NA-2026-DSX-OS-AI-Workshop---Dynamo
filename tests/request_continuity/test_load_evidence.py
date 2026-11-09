"""Independent raw protocol and comparison-control verification."""
import json
import unittest

import demos.request_continuity.verify_load as verify


class RawEvidenceTests(unittest.TestCase):
    def test_multiline_sse_and_done_parse(self):
        raw = b'data: {"id":"one",\ndata: "choices":[]}\n\ndata: [DONE]\n\n'
        self.assertEqual(verify.sse_frames(raw), [{'id': 'one', 'choices': []}, '[DONE]'])

    def test_truncated_data_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            verify.sse_frames(b'data: {"id":"one"}\n')

    def test_mode_normalization_does_not_hide_runtime_or_load_changes(self):
        a = {'name': 'demo-continuity-disabled', 'namespace': 'old',
             'env': [{'name': 'DYN_MIGRATION_LIMIT', 'value': '0'}], 'args': ['--max-num-seqs', '4']}
        b = {'name': 'demo-continuity-enabled', 'namespace': 'new',
             'env': [{'name': 'DYN_MIGRATION_LIMIT', 'value': '3'}], 'args': ['--max-num-seqs', '4']}
        self.assertEqual(verify.normalize(a), verify.normalize(b))
        b['args'][-1] = '8'
        self.assertNotEqual(verify.normalize(a), verify.normalize(b))


if __name__ == '__main__':
    unittest.main()
