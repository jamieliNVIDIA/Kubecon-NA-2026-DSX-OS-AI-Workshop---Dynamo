#!/usr/bin/env python3
"""Interrupt only this run's local Shadow startup waiter after a recorded CUDA failure."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
from testlib import Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    run = Run(args.run)
    if any((run.path / p).exists() for p in ('shadow-fault-intent.json', 'shadow-fault.json')):
        raise RuntimeError('Cannot interrupt a run with a fault attempt')
    evidence = list((run.path / 'diagnostics').glob('ft-shadow-*/engine-*-previous.log'))
    if not any('an illegal memory access was encountered' in p.read_text() for p in evidence):
        raise RuntimeError('Requires preserved CUDA startup-failure evidence')
    expected = ['scripts/super_vl_tests.py', 'feature', '--feature', 'shadow', '--run', str(args.run)]
    found = []
    # Do not store or print unrelated local process command lines.
    for line in subprocess.check_output(['ps', '-axo', 'pid=,uid=,command='], text=True).splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        pid, uid, command = fields
        if int(uid) != os.getuid() or 'scripts/super_vl_tests.py' not in command:
            continue
        try:
            argv = shlex.split(command)
        except ValueError:
            continue
        if len(argv) == len(expected) + 1 and Path(argv[0]).name.lower().startswith('python') and argv[1:] == expected:
            found.append(int(pid))
    if len(found) != 1:
        raise RuntimeError(f'Expected one exact local Shadow feature process, found {found}')
    report = {'pid': found[0], 'signal': 'SIGINT', 'target': expected,
              'reason': 'Writer CUDA illegal access after GMS remap; stop unchanged startup retries',
              'fault_injected': False, 'evidence': [str(p.relative_to(run.path)) for p in evidence]}
    (run.path / 'shadow-startup-interrupt.json').write_text(json.dumps(report, indent=2) + '\n')
    run.result('super-vl-shadow', 'blocked', **report)
    run.result('shadow-failover', 'blocked', **report)
    os.kill(found[0], signal.SIGINT)  # Python's finally block performs owned cluster cleanup.
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
