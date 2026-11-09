#!/usr/bin/env python3
"""Render each synthetic cell's AIPerf profile with the pinned AIPerf, then reload and plan it offline.

Run with the AgentX dependency interpreter (source-location.json `dependency_python`). The pinned
source archive is extracted to a temporary directory and imported from there, so the rendered YAML is
exactly what the CPU client's AIPerf parses. Nothing contacts an endpoint.

Usage: profiles.py --archive ARCHIVE --sha256 DIGEST --cells CELLS.json --output DIR
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile

import yaml

MODEL = 'nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'
REVISION = '8a115b9d966adce8c059a7bcf47f49a1e57957d8'
PLACEHOLDER_URL = 'http://frontend.invalid:8000'


def flags(cell):
    users = cell['agents']
    return ['--model', MODEL, '--tokenizer', MODEL, '--tokenizer-revision', REVISION,
            '--url', PLACEHOLDER_URL, '--endpoint-type', 'chat', '--streaming', '--use-server-token-count',
            '--user-centric-rate', repr(users / cell['gap_seconds']), '--num-users', str(users),
            '--concurrency', str(users),
            '--shared-system-prompt-length', '32000', '--user-context-prompt-length', '24000',
            '--synthetic-input-tokens-mean', '4000', '--synthetic-input-tokens-stddev', '1500',
            '--osl', '650', '--prompt-corpus', 'coding',
            '--extra-inputs', json.dumps({'ignore_eos': True, 'chat_template_kwargs': {'enable_thinking': False}}),
            # Fixed-length sessions: with variable lengths the pinned user-centric scheduler gives virtually aged
            # users the dataset's average remaining turns, so short conversations raise ValueError every turn.
            '--session-turns-mean', '12', '--session-turns-stddev', '0',
            '--num-dataset-entries', '1000', '--random-seed', str(cell['seed']),
            '--benchmark-duration', str(cell['duration_seconds']),
            '--benchmark-grace-period', str(cell['grace_seconds']),
            '--slice-duration', str(cell['slice_seconds']),
            '--export-level', 'records', '--output-artifact-dir', 'artifacts/' + cell['cell']]


def render(cell, output):
    from aiperf.cli_commands.profile import app
    from aiperf.config.flags.resolver import resolve_config
    from aiperf.config.loader import build_benchmark_plan, load_config

    _, bound, _ = app.parse_args(flags(cell))
    config = resolve_config(bound.arguments['cli_config'], None)
    value = config.model_dump(mode='json', by_alias=True, exclude_unset=True, exclude_none=True)
    benchmark = value['benchmark']
    # The campaign samples nvidia-smi in the workers itself, as the AgentX cells did.
    benchmark['gpuTelemetry'] = {'enabled': False}
    # Worker /metrics URLs are filled in when the cell is sealed; Kubernetes discovery stays off.
    benchmark['serverMetrics']['discovery'] = {'mode': 'disabled'}
    path = output / f'profile-{cell["cell"]}.yaml'
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    reloaded = load_config(path)
    build_benchmark_plan(reloaded)
    phase = reloaded.benchmark.phases[0]
    dataset = value['benchmark']['datasets'][0]
    assert str(phase.type).endswith('user_centric') and phase.users == cell['agents']
    assert abs(phase.rate - cell['agents'] / cell['gap_seconds']) < 1e-9
    assert dataset['prefixPrompts'] == {'sharedSystemLength': 32000, 'userContextLength': 24000}
    return {'cell': cell['cell'], 'profile': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'phase_type': str(phase.type), 'users': phase.users, 'rate': phase.rate,
            'duration': phase.duration, 'grace_period': phase.grace_period, 'seed': cell['seed']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--cells', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert hashlib.sha256(args.archive.read_bytes()).hexdigest() == args.sha256, 'Pinned AIPerf archive changed'
    cells = json.loads(args.cells.read_text())
    with tempfile.TemporaryDirectory(prefix='pinned-aiperf-') as temporary:
        with tarfile.open(args.archive) as archive:
            archive.extractall(temporary, filter='data')
        source = Path(temporary) / 'src'
        assert (source / 'aiperf/__init__.py').exists(), 'Unexpected pinned archive layout'
        sys.path.insert(0, str(source))
        import aiperf
        assert Path(aiperf.__file__).resolve().is_relative_to(source.resolve())
        receipts = [render(cell, args.output) for cell in cells]
    print(json.dumps({'aiperf_source': 'pinned archive ' + args.sha256, 'profiles': receipts}))


if __name__ == '__main__':
    main()
