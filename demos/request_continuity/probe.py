"""In-container vLLM EngineCore inspection and PID-identity-checked fault injection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import time


def process_identity(proc):
    pid = int(proc.name)
    command = (proc / 'cmdline').read_bytes().split(b'\0')[0].decode(errors='replace')
    start_ticks = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    return {'pid': pid, 'command': command, 'start_ticks': start_ticks}


def inspect(root=Path('/proc')):
    candidates = []
    for proc in root.iterdir():
        if not proc.name.isdecimal() or int(proc.name) <= 1:
            continue
        try:
            identity = process_identity(proc)
        except (OSError, ValueError, IndexError):
            continue
        if identity['command'].startswith('VLLM::EngineCore'):
            candidates.append(identity)
    if len(candidates) != 1:
        raise ValueError('Expected one vLLM EngineCore in this container: ' + repr(candidates))
    return candidates[0]


def kill(expected, root=Path('/proc')):
    actual = inspect(root)
    if actual != expected or actual['pid'] <= 1:
        raise ValueError('Engine process identity changed; refusing fault injection.')
    os.kill(actual['pid'], signal.SIGKILL)
    return {**actual, 'signal': 'SIGKILL', 'signal_sent': True,
            'sent_at_unix_ns': time.time_ns()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'kill'])
    parser.add_argument('expected', nargs='?')
    args = parser.parse_args()
    if args.action == 'kill' and args.expected is None:
        parser.error('kill requires the previously inspected process identity')
    value = inspect() if args.action == 'inspect' else kill(json.loads(args.expected))
    print('RESULT_JSON=' + json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
