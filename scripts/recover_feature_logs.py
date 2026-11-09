#!/usr/bin/env python3
"""Recover successful log captures from immutable command receipts after Pod cleanup."""
import argparse
import hashlib
import json
from pathlib import Path


def recover(root, prefix):
    output = root / 'recovered-logs'
    output.mkdir(exist_ok=True)
    index = []
    for path in sorted(root.glob('command-*.json')):
        receipt = json.loads(path.read_text())
        args = receipt['args']
        if 'logs' not in args or receipt['exit_code'] != 0:
            continue
        pod = args[args.index('logs') + 1]
        text = receipt.get('stdout', '')
        if not pod.startswith(prefix) or not text or text.startswith('unable to retrieve'):
            continue
        container = args[args.index('-c') + 1] if '-c' in args else 'default'
        filename = f'{pod}-{container}-{path.stem}.log'
        (output / filename).write_text(text)
        index.append({'file': filename, 'command_receipt': path.name,
                      'started_at': receipt['started_at'], 'bytes': len(text.encode()),
                      'sha256': hashlib.sha256(text.encode()).hexdigest()})
    (output / (prefix + '-index.json')).write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'captures': len(index)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    recover(args.run, args.prefix)
