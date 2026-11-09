#!/usr/bin/env python3
"""Finish one already-frozen P/D comparison after its CPU preparation passes.

No retries, refreezes, workload changes or other namespaces are allowed. The
controller exists so the bounded pair can finish while the parent chat is idle.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import scripts.development.disaggregated.benchmark as benchmark


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_deadline(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Controller deadline must include an explicit timezone.')
    return parsed.timestamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', default='a1', help='Fresh controller receipt label; never reuses benchmark arms.')
    parser.add_argument('--deadline', help='Explicit ISO8601 execution deadline with timezone for an actively resumed task.')
    parser.add_argument('--entrypoint', type=Path, help='Frozen campaign-specific execution wrapper, including scoped cleanup.')
    args = parser.parse_args()
    path = args.run.resolve()
    if not args.attempt.isalnum():
        raise ValueError('Use an alphanumeric controller attempt label.')
    prefix = 'controller' if args.attempt == 'a1' else 'controller-' + args.attempt
    deadline = (parse_deadline(args.deadline) if args.deadline else
                dt.datetime(2026, 11, 5, 15, 15, tzinfo=dt.timezone.utc).timestamp())
    if deadline <= time.time():
        raise ValueError('The old overnight window has ended; supply a fresh explicit --deadline for an authorized resumption.')
    campaign = json.loads((path / 'campaign.json').read_text())
    entrypoint = args.entrypoint.resolve() if args.entrypoint else Path(benchmark.__file__).resolve()
    if args.entrypoint and (str(entrypoint.relative_to(benchmark.ROOT)) != campaign.get('execution_entrypoint') or
                            benchmark.sha(entrypoint) != campaign.get('execution_entrypoint_sha256')):
        raise ValueError('Explicit execution wrapper must match the immutable campaign.')
    minimum_profile_budget = campaign['profile_seconds'] + campaign['grace_seconds']
    with (path / (prefix + '-start.json')).open('x') as stream:
        json.dump({'at': now(), 'pid': os.getpid(), 'controller_sha256': benchmark.sha(__file__),
                   'campaign_sha256': benchmark.sha(path / 'campaign.json'),
                   'deadline_utc': dt.datetime.fromtimestamp(deadline, dt.timezone.utc).isoformat(),
                   'arm_timeout_cap_seconds': 8100, 'minimum_admission_drain_budget_seconds': minimum_profile_budget,
                   'execution_entrypoint': str(entrypoint), 'execution_entrypoint_sha256': benchmark.sha(entrypoint),
                   'scope': 'Execution-window change only; locked engine/load/corpus/phase settings unchanged. Deadline truncation is ineligible for a comparison.'}, stream, indent=2)
    outcome = {'started_at': now(), 'status': 'running', 'arms': []}
    active = None

    def stop(signum, frame):
        raise InterruptedError('Controller signal ' + str(signum))

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            state = json.loads((path / 'state.json').read_text())
            if state.get('checks', {}).get('disagg-cpu-qualified', {}).get('status') == 'passed':
                break
            console = (path / 'prepare-console-network.log').read_text(errors='replace')
            if 'Traceback (most recent call last)' in console:
                raise RuntimeError('CPU preparation failed; no GPU actions started.')
            if time.time() > deadline - 2 * minimum_profile_budget:
                raise TimeoutError('Insufficient execution-window budget remains even for the two locked admission/drain phases.')
            write(path / (prefix + '-status.json'), {'at': now(), 'stage': 'Waiting for CPU qualification'})
            time.sleep(30)
        for topology in benchmark.ARMS:
            if time.time() > deadline - minimum_profile_budget:
                raise TimeoutError('Do not start an arm without its locked admission/drain budget. Startup/primers also consume the execution window.')
            executable = ([sys.executable, str(entrypoint)] if args.entrypoint else
                          [sys.executable, '-m', 'scripts.development.disaggregated.benchmark'])
            command = executable + [topology, '--run', str(path)]
            write(path / (prefix + '-status.json'), {'at': now(), 'stage': topology, 'command': command})
            started = now()
            with (path / (topology + '-console.log')).open('x') as output:
                active = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                          cwd=benchmark.ROOT, start_new_session=True)
                code = active.wait(timeout=min(8100, max(1, deadline - time.time())))
            outcome['arms'].append({'topology': topology, 'started_at': started, 'finished_at': now(), 'exit_code': code})
            active = None
            if code:
                raise RuntimeError('Immutable ' + topology + ' arm failed; no automatic retuning/retry.')
        outcome['status'] = 'profiles_collected'
    except BaseException as error:
        outcome.update(status='blocked', error=repr(error))
        if active is not None and active.poll() is None:
            os.killpg(active.pid, signal.SIGINT)
            try:
                active.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(active.pid, signal.SIGKILL)
                active.wait()
    finally:
        try:
            if args.entrypoint:
                result = subprocess.run([sys.executable, str(entrypoint), 'cleanup', '--run', str(path)], timeout=420)
                if result.returncode:
                    raise RuntimeError('Campaign-specific scoped cleanup failed: ' + str(result.returncode))
            else:
                run = benchmark.setup(path)
                benchmark.cleanup(run)
            outcome['cleanup'] = 'passed'
        except BaseException as error:
            outcome['cleanup'] = 'blocked'
            outcome['cleanup_error'] = repr(error)
        outcome['finished_at'] = now()
        write(path / (prefix + '-exit.json'), outcome)
        print(json.dumps(outcome), flush=True)
    return 0 if outcome['status'] == 'profiles_collected' and outcome['cleanup'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
