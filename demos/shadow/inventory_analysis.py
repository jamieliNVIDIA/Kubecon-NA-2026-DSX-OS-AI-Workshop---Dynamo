#!/usr/bin/env python3
"""Offline reconstruction of a frozen diagnostic's actual parameter JSONL.

No cluster calls, Torch imports or candidate state writes. The output preserves
exact source log bytes and separates all parameter metadata from candidate
quantization owners. MoE/attention selection needs additional runtime evidence.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

PREFIX = 'WORKSHOP_PARAMETER_INVENTORY_V1 '
EVENTS = {'begin', 'parameter', 'summary', 'published', 'all-ranks-ready'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frozen_contract(source):
    tree = ast.parse(source)
    values = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id in ('MODEL_OPT', 'HUMMING_LINEAR', 'CUTLASS_FP8', 'PARAM_ATTRS'):
            values[target.id] = ast.literal_eval(statement.value)
        elif target.id == 'TORCH_DTYPES':
            node = statement.value
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                    node.func.id == 'frozenset' and len(node.args) == 1 and not node.keywords):
                raise ValueError('Unexpected frozen dtype allowlist syntax.')
            values[target.id] = frozenset(ast.literal_eval(node.args[0]))
    if set(values) != {'MODEL_OPT', 'HUMMING_LINEAR', 'CUTLASS_FP8', 'PARAM_ATTRS', 'TORCH_DTYPES'}:
        raise ValueError('Frozen diagnostic contract declarations are incomplete.')
    return values


def scan_log(data, label, expected_candidate):
    events, failures, parse_errors = [], [], []
    decoder = json.JSONDecoder()
    lines = data.decode('utf-8', errors='replace').splitlines()
    for number, line in enumerate(lines, 1):
        if 'ValueError:' in line and any(marker in line for marker in (
                'inference parameter dtype/gradient contract', 'parameter layout attribute',
                'parameter shape/stride', 'final-parameter inventory',
                'Writer manifest requires actual final CUDA parameters')):
            failures.append({'source': label, 'line': number, 'text': line})
        index = line.find(PREFIX)
        if index < 0:
            continue
        try:
            value, end = decoder.raw_decode(line[index + len(PREFIX):])
            if (type(value) is not dict or value.get('event') not in EVENTS or
                    type(value.get('tp_rank')) is not int or value['tp_rank'] not in (0, 1)):
                raise ValueError('Unknown inventory event or TP rank.')
            if value.get('candidate') != expected_candidate:
                raise ValueError('Foreign candidate JSONL must never be merged into this evidence.')
            events.append({'value': value, 'source': label, 'line': number})
        except (ValueError, json.JSONDecodeError) as error:
            parse_errors.append({'source': label, 'line': number, 'error': str(error)})
    return events, failures, parse_errors


def exporter_scope(row, contract):
    quant = row.get('quant_method_class')
    if quant == contract['MODEL_OPT'] + ':ModelOptLinearMethod':
        if row.get('kernel_class') == contract['HUMMING_LINEAR']:
            return 'humming-linear'
        if row.get('kernel_class') == contract['CUTLASS_FP8']:
            return 'cutlass-fp8'
        return 'unreviewed-modelopt-linear-backend'
    if quant == contract['MODEL_OPT'] + ':ModelOptNvFp4FusedMoE':
        return 'humming-moe-candidate-owner'
    if quant == contract['MODEL_OPT'] + ':ModelOptKVCacheMethod':
        return 'modelopt-attention-candidate-owner'
    return 'not-selected-by-v3-exporter'


def parameter_issues(row, contract):
    if row['is_none']:
        return []
    issues = []
    if type(row.get('dtype')) is not str or row['dtype'] not in contract['TORCH_DTYPES']:
        issues.append('dtype-not-allowlisted')
    if row.get('requires_grad') is not False:
        issues.append('requires-grad-not-false')
    if row.get('is_cuda') is not True or row.get('is_meta') is not False:
        issues.append('not-final-cuda-parameter')
    for field in ('shape', 'stride'):
        value = row.get(field)
        if (type(value) is not list or any(type(item) is not int or item < 0 for item in value)):
            issues.append('unsupported-' + field)
    if any(item == 0 for item in row.get('shape', ())):
        issues.append('empty-extent-not-supported-by-allocation-guard')
    for name in contract['PARAM_ATTRS']:
        value = row.get('layout_attributes', {}).get(name)
        if value is None:
            continue
        number = value.get('value')
        if (value.get('type') not in ('builtins:int', 'builtins:float') or
                type(number) not in (int, float) or not math.isfinite(number)):
            issues.append('layout-attribute-not-finite-int-or-float:' + name)
    return issues


def reconstruct(events, contract):
    ranks = {str(rank): {'parameters': {}, 'origins': {}, 'events': {}} for rank in (0, 1)}
    for observation in events:
        value = observation['value']
        rank = ranks[str(value['tp_rank'])]
        key = value['name'] if value['event'] == 'parameter' else value['event']
        target = rank['parameters'] if value['event'] == 'parameter' else rank['events']
        if key in target and target[key] != value:
            raise ValueError('Conflicting inventory row/generation for TP' + str(value['tp_rank']) + ':' + key)
        target[key] = value
        rank['origins'].setdefault(value['event'] + ':' + key, []).append(
            {'source': observation['source'], 'line': observation['line']})
    for rank in ranks.values():
        rows = list(rank['parameters'].values())
        actual = [row for row in rows if not row['is_none']]
        observed = {'slots': len(rows), 'parameters': len(actual),
            'cuda_parameters': sum(row.get('is_cuda') is True for row in actual),
            'meta_parameters': sum(row.get('is_meta') is True for row in actual),
            'none_slots': len(rows) - len(actual),
            'aliases': sum(row.get('alias_of') is not None for row in actual),
            'dtypes': dict(Counter(str(row.get('dtype')) for row in actual)),
            'requires_grad': dict(Counter(str(row.get('requires_grad')) for row in actual))}
        summary = rank['events'].get('summary', {})
        mismatches = {name: {'recorded': summary.get(name), 'reconstructed': value}
            for name, value in observed.items() if summary.get(name) != value}
        complete_events = set(rank['events']) == {'begin', 'summary', 'published', 'all-ranks-ready'}
        rank['complete'] = complete_events and not mismatches and not summary.get('inspection_errors')
        rank['summary_mismatches'] = mismatches
        rank['reconstructed_summary'] = observed
        issues = []
        scopes = Counter()
        for row in rows:
            scope = exporter_scope(row, contract)
            scopes[scope] += 1
            problems = parameter_issues(row, contract)
            if problems:
                issues.append({'name': row['name'], 'exporter_scope': scope, 'issues': problems,
                    'dtype': row.get('dtype'), 'requires_grad': row.get('requires_grad'),
                    'parameter_class': row.get('parameter_class'), 'shape': row.get('shape'),
                    'stride': row.get('stride'), 'layout_attributes': row.get('layout_attributes', {}),
                    'module_class': row.get('module_class'), 'quant_method_class': row.get('quant_method_class'),
                    'kernel_class': row.get('kernel_class')})
        rank['scope_slot_counts'] = dict(scopes)
        rank['all_parameter_issues'] = issues
        rank['candidate_exporter_parameter_issues'] = [issue for issue in issues if
            issue['exporter_scope'] in ('humming-linear', 'cutlass-fp8',
                'humming-moe-candidate-owner', 'modelopt-attention-candidate-owner')]
    return ranks


def analyze(run_path, output, logs=None):
    run_path, output = Path(run_path).resolve(), Path(output).resolve()
    spec_path = run_path / 'descriptor-writer-spec.json'
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    state = json.loads((run_path / 'state.json').read_text())
    if state['shadow_descriptor_spec_sha256'] != digest(spec_bytes):
        raise ValueError('Frozen candidate specification changed.')
    for name, expected in spec['inputs'].items():
        if digest((run_path / name).read_bytes()) != expected:
            raise ValueError('Frozen diagnostic input changed: ' + name)
    contract = frozen_contract((run_path / 'workshop_descriptors.py').read_text())
    logs = sorted(Path(path).resolve() for path in logs) if logs else sorted(run_path.rglob('*.log'))
    snapshots, events, failures, errors = [], [], [], []
    for path in logs:
        data = path.read_bytes()  # One consistent local snapshot, even if the stream is still growing.
        if PREFIX.encode() not in data and b'Unexpected inference parameter' not in data:
            continue
        label = str(path)
        parsed, fatal, invalid = scan_log(data, label, spec['descriptor_identity']['candidate'])
        events.extend(parsed); failures.extend(fatal); errors.extend(invalid)
        snapshots.append((path, data))
    ranks = reconstruct(events, contract)
    generations = [rank['events'].get('all-ranks-ready', {}).get('generations') for rank in ranks.values()]
    pair_verified = (generations[0] == generations[1] and type(generations[0]) is dict and
        set(generations[0]) == {'0', '1'} and all(type(value) is str and len(value) == 32 and
            all(char in '0123456789abcdef' for char in value) for value in generations[0].values()))
    report = {'scope': 'Actual diagnostic metadata from preserved engine JSONL; no reader/GPU-recovery qualification',
        'analysis_source_sha256': digest(Path(__file__).read_bytes()),
        'run': str(run_path), 'namespace': spec['namespace'], 'spec_sha256': digest(spec_bytes),
        'descriptor_identity': spec['descriptor_identity'], 'parse_errors': errors,
        'classification_scope': 'Linear class/kernel matches are exact; MoE/attention owners are candidates pending additional backend/expert/runtime evidence.',
        'pair_generation_verified': pair_verified,
        'complete': bool(events) and all(rank['complete'] for rank in ranks.values()) and pair_verified and not errors,
        'strict_failures': failures, 'ranks': ranks,
        'source_logs': [{'path': str(path), 'bytes': len(data), 'sha256': digest(data)} for path, data in snapshots]}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'source-logs').mkdir()
    for index, (path, data) in enumerate(snapshots):
        name = str(index).zfill(3) + '-' + path.name
        (output / 'source-logs' / name).write_bytes(data)
        report['source_logs'][index]['snapshot'] = 'source-logs/' + name
    (output / 'analysis.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'output': str(output), 'complete': report['complete'], 'parse_errors': len(errors),
        'ranks': {rank: {'complete': value['complete'], 'slots': value['reconstructed_summary']['slots'],
            'all_issues': len(value['all_parameter_issues']),
            'candidate_exporter_issues': len(value['candidate_exporter_parameter_issues'])}
            for rank, value in ranks.items()}, 'strict_failures': len(failures)}, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--logs', nargs='+', type=Path)
    arguments = parser.parse_args()
    analyze(arguments.run, arguments.output, arguments.logs)
