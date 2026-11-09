#!/usr/bin/env python3
"""Freeze the already-qualified C4 scale-out and C1 policy pilots for presentation.

This is an evidence-copy operation, not an inference or benchmark invocation.
It needs the existing private pullbacks. It never overwrites a recording.
Newer load-sweep evidence requires a separate reviewed importer/profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import demos.routing.demo as demo


def load(path):
    return json.loads(path.read_text())


def verify_arm(path):
    inventory = load(path / 'integrity-final.json')['sha256']
    for name, expected in inventory.items():
        actual = hashlib.sha256(demo.relative_file(path, name).read_bytes()).hexdigest()
        demo.require(actual == expected, 'Source arm inventory mismatch: ' + name)


def freeze(destination, scaleout, policy):
    demo.require(not destination.exists(), 'Destination already exists; recording attempts are immutable.')
    scaleout_verification = load(scaleout / 'verification.json')
    policy_verification = load(policy / 'verification.json')
    demo.require(scaleout_verification['mismatches'] == 0 and scaleout_verification['files_verified'] == 142 and
                 scaleout_verification['c4_stage_exit']['exit_code'] == 0, 'C4 closeout was not verified.')
    demo.require(policy_verification['passed'] and policy_verification['files_verified'] == 680 and
                 policy_verification['user_stopped'], 'Policy pullback was not verified.')
    source = {
        'scaleout-analysis.json': scaleout / 'analysis/recomputed-analysis.json',
        'policy-analysis.json': policy / 'verified/results/workshop-rrkv-20261104-a1/routing-c1-a1-analysis.json',
        'scaleout-verification.json': scaleout / 'verification.json',
        'policy-verification.json': policy / 'verification.json',
    }
    source_roots = {
        'scaleout': scaleout / 'verified/results/workshop-rr-20261103-resume02',
        'policy': policy / 'verified/results/workshop-rrkv-20261104-a1',
    }
    for name in ['scaleout', 'policy']:
        analysis = load(source[name + '-analysis.json'])
        for index, row in enumerate(analysis['arms'], 1):
            arm = source_roots[name] / row['arm']
            verify_arm(arm)
            exports = list((arm / 'raw').rglob('profile_export_aiperf.json'))
            demo.require(len(exports) == 1, 'Need one main AIPerf export per arm.')
            source[f'{name}-arm{index}-aiperf.json'] = exports[0]
    for mode in ('round-robin', 'kv'):
        arm = source_roots['policy'] / f'routing-c1-{mode}-a1'
        source['policy-' + mode + '-deployment.json'] = arm / 'deployment.json'
    source['policy-kv-discovery.json'] = source_roots['policy'] / 'routing-c1-kv-a1/discovery-qualification.json'
    destination.mkdir(parents=True)
    for name, path in source.items():
        (destination / name).write_bytes(path.read_bytes())
    metadata = {'schema': 1, 'profile': demo.PROFILE, 'measurement_class': 'historical-low-load-pilots',
        'frozen_at': demo.ui.now(), 'sources': {name: str(path.relative_to(ROOT)) for name, path in source.items()},
        'files_sha256': {name: demo.ui.digest(destination / name) for name in source},
        'scope': 'C4 operational scale-out and separate C1 fresh-worker policy pair. N=1, low load. '
                 'Not a capacity result, combined study, new benchmark, or latest load-sweep result.',
        'higher_load_import': 'Deliberately gated: a separate recording profile/importer must validate '
                             'fresh 128-sequence experiments, overload/censoring and matched same-load pairs.'}
    demo.ui.write_json(destination / 'recording.json', metadata)
    demo.load_recording(destination)
    print(json.dumps({'recording': str(destination), 'files_verified': len(source),
                      'recording_sha256': demo.ui.digest(destination / 'recording.json')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scaleout', type=Path, default=ROOT / 'results/workshop-c4-closeout-20261104-a1')
    parser.add_argument('--policy', type=Path, default=ROOT / 'results/workshop-rrkv-stopped-pullback-20261104-a1')
    args = parser.parse_args()
    freeze(args.output.resolve(), args.scaleout.resolve(), args.policy.resolve())
