#!/usr/bin/env python3
"""Read-only direct/relay SSH reachability checks for interrupted Snapshot cleanup."""
import argparse
import json
from pathlib import Path
import shlex
from testlib import Run


def test(run):
    options = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
               '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1',
               '-o', 'ControlPath=none', '-o', 'ForwardAgent=no']
    program = "import socket; s=socket.create_connection(('3.238.63.5',22),timeout=5); print('JUMP_PORT_REACHABLE'); s.close()"
    commands = {
        'direct': options + ['ubuntu@3.238.63.5', 'printf JUMP_SSH_READY'],
        'gemini_relay': options + ['gemini', 'python3 -c ' + shlex.quote(program)],
    }
    report = {}
    for name, command in commands.items():
        result = run.command(command, timeout=20, check=False)
        report[name] = {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        print(json.dumps({name: report[name]}), flush=True)
    run.result('snapshot-access', 'present' if report['direct']['exit_code'] == 0 else 'blocked',
               **report, scope='SSH/TCP probes only; no credentials copied or cluster resources changed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    test(Run(parser.parse_args().run))
