"""Offline evidence must distinguish complete inventories from partial logs."""
from tests.support import ROOT
import copy
import json
import unittest

import demos.shadow.inventory_analysis as analysis


class InventoryAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.contract = analysis.frozen_contract((ROOT / 'demos/shadow/compat/descriptor_attention.py').read_text())

    def fixtures(self):
        records = []
        for rank in (0, 1):
            common = {'candidate': 'fresh', 'tp_rank': rank}
            def event(kind, **values):
                return dict(common, event=kind, **values)
            selected = event('parameter', name='decoder.weight', owner='decoder', parameter='weight',
                is_none=False, alias_of=None, dtype='torch.float32', requires_grad=True,
                is_cuda=True, is_meta=False, shape=[16, 32], stride=[32, 1],
                quant_method_class=self.contract['MODEL_OPT'] + ':ModelOptLinearMethod',
                kernel_class=self.contract['HUMMING_LINEAR'],
                layout_attributes={'packed_factor': {'type': 'fractions:Fraction', 'numerator': 1, 'denominator': 2}})
            unselected = dict(selected, name='embedding.weight', owner='embedding',
                quant_method_class='builtins:NoneType', kernel_class='builtins:NoneType',
                layout_attributes={})
            none = event('parameter', name='decoder.bias', owner='decoder', parameter='bias',
                is_none=True, quant_method_class=selected['quant_method_class'], kernel_class=selected['kernel_class'])
            rows = [event('begin', pid=100 + rank), selected, unselected, none,
                event('summary', slots=3, parameters=2, cuda_parameters=2, meta_parameters=0,
                    none_slots=1, aliases=0, dtypes={'torch.float32': 2}, requires_grad={'True': 2}, inspection_errors=[]),
                event('published', path='/shared/rank.json', sha256='a' * 64),
                event('all-ranks-ready', generations={'0': 'b' * 32, '1': 'c' * 32})]
            records.extend({'value': value, 'source': 'actual-main.log', 'line': index + 1} for index, value in enumerate(rows))
        return records

    def test_prefixed_actual_jsonl_and_fatal_are_parsed_with_source_lines(self):
        row = self.fixtures()[0]['value']
        log = 'timestamp (Worker_TP0 pid=100) ' + analysis.PREFIX + json.dumps(row) + '\x1b[0m\n'
        log += 'timestamp ValueError: Unexpected inference parameter dtype/gradient contract: parameter=decoder.weight\n'
        events, fatal, errors = analysis.scan_log(log.encode(), 'main.log', 'fresh')
        self.assertEqual(events[0]['value'], row)
        self.assertEqual(events[0]['line'], 1)
        self.assertEqual(fatal[0]['line'], 2)
        self.assertEqual(errors, [])

    def test_complete_duplicate_sources_keep_origins_and_limit_selected_exporter_issues(self):
        records = self.fixtures()
        duplicate = [dict(row, source='previous-main.log') for row in copy.deepcopy(records)]
        ranks = analysis.reconstruct(records + duplicate, self.contract)
        for rank in ranks.values():
            self.assertTrue(rank['complete'])
            self.assertEqual(rank['reconstructed_summary']['slots'], 3)
            self.assertEqual(len(rank['all_parameter_issues']), 2)
            self.assertEqual(len(rank['candidate_exporter_parameter_issues']), 1)
            issue = rank['candidate_exporter_parameter_issues'][0]
            self.assertEqual(issue['name'], 'decoder.weight')
            self.assertEqual(issue['issues'], ['requires-grad-not-false',
                'layout-attribute-not-finite-int-or-float:packed_factor'])
            self.assertEqual(len(rank['origins']['parameter:decoder.weight']), 2)

    def test_partial_stream_is_not_complete_and_missing_rows_are_explained(self):
        records = [record for record in self.fixtures() if record['value'].get('name') != 'decoder.weight']
        ranks = analysis.reconstruct(records, self.contract)
        self.assertFalse(ranks['0']['complete'])
        self.assertEqual(ranks['0']['summary_mismatches']['slots'], {'recorded': 3, 'reconstructed': 2})

    def test_conflicting_parameter_or_process_generation_is_refused(self):
        records = self.fixtures()
        for original in (records[0], records[1]):
            changed = copy.deepcopy(original)
            if changed['value']['event'] == 'begin': changed['value']['pid'] = 999
            else: changed['value']['dtype'] = 'torch.float16'
            with self.assertRaisesRegex(ValueError, 'Conflicting inventory'):
                analysis.reconstruct(records + [changed], self.contract)

    def test_foreign_or_truncated_jsonl_never_becomes_current_evidence(self):
        value = self.fixtures()[0]['value']
        value['candidate'] = 'old'
        log = analysis.PREFIX + json.dumps(value) + '\n' + analysis.PREFIX + '{"event":'
        events, fatal, errors = analysis.scan_log(log.encode(), 'main.log', 'fresh')
        self.assertEqual(events, [])
        self.assertEqual(len(errors), 2)

    def test_malformed_metadata_is_reported_without_crashing_analysis(self):
        row = self.fixtures()[1]['value']
        row.update(dtype={'inspection_error': {}}, shape=[{'type': 'opaque'}], requires_grad={'type': 'opaque'})
        issues = analysis.parameter_issues(row, self.contract)
        self.assertIn('dtype-not-allowlisted', issues)
        self.assertIn('unsupported-shape', issues)
        self.assertIn('requires-grad-not-false', issues)


if __name__ == '__main__': unittest.main()
