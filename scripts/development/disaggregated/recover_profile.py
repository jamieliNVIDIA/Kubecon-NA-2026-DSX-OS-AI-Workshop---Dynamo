#!/usr/bin/env python3
"""Inspect/collect the original detached P/D profile after observer transport loss.

Never launches inference, restarts a profile, changes a frozen input, or deletes
resources. Root is the sole live executor. Cleanup is a separate explicit step
after the original runner has ended and its evidence is collected.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shutil

import scripts.development.disaggregated.handoff as handoff


REMOTE_INSPECT = r'''import hashlib,json,os,sys
from pathlib import Path
root=Path('/tmp/workshop-rr/runs')/sys.argv[1]
profile=root/'profile.yaml'
assert profile.is_file(),'Original profile is absent'
digest=hashlib.sha256(profile.read_bytes()).hexdigest()
assert digest==sys.argv[2],'Original remote profile changed'
read=lambda name:json.loads((root/name).read_text()) if (root/name).exists() else None
process=read('process.json');exit=read('exit.json')
active=None
if process and exit is None:
 p=Path('/proc')/str(process['pid'])/'cmdline'
 active=p.read_bytes().replace(b'\0',b' ').decode(errors='replace') if p.exists() else None
print(json.dumps({'original_profile_sha256':digest,'process':process,'exit':exit,
 'active_process_command':active,'console_tail':(root/'console.log').read_text(errors='replace')[-5000:]}))
'''


def validate_original_status(value, profile_sha256, *, completed=False):
    if value.get('original_profile_sha256') != profile_sha256 or not value.get('process'):
        raise ValueError('Original profile/process identity is missing or changed.')
    if value.get('exit') is None:
        command = value.get('active_process_command') or ''
        if '-m aiperf profile' not in command:
            raise ValueError('Original runner has no exit receipt and cannot be verified active.')
        if completed:
            raise ValueError('Original profile is still running; preserve it and inspect again, never replay.')


def snapshot_before(run, folder, recovery):
    destination = recovery / 'before-recovery'
    destination.mkdir(exist_ok=False)
    for path in folder.iterdir():
        if path.is_file():
            shutil.copy2(path, destination / path.name)
    for name in ('controller-a2-exit.json', 'controller-a2-start.json', 'disaggregated-console.log'):
        source = run.path / name
        if source.exists():
            shutil.copy2(source, destination / name)
    handoff.b.write(recovery / 'before-recovery-sha256.json', {
        p.name: handoff.b.sha(p) for p in destination.iterdir() if p.is_file()})


def recovery(run, attempt, collect):
    if not attempt.isalnum():
        raise ValueError('Use a fresh alphanumeric recovery attempt.')
    handoff.b.verify(run)
    handoff.check_client(run)
    campaign = handoff.b.spec(run)
    arm = campaign['arm_names']['disaggregated']
    folder = run.path / arm
    if not (folder / 'launch.json').exists() or not (folder / 'spec.json').exists():
        raise ValueError('No originally launched P/D profile is available to recover.')
    recovery = run.path / ('profile-recovery-' + attempt)
    recovery.mkdir(exist_ok=False)
    expected_hash = json.loads((folder / 'spec.json').read_text())['profile_sha256']
    result = handoff.b.e.client(run, REMOTE_INSPECT, argv=(arm, expected_hash))
    status = json.loads(result.stdout)
    validate_original_status(status, expected_hash, completed=collect)
    handoff.b.write(recovery / 'original-remote-status.json', status)
    handoff.b.write(recovery / 'context.json', {'at': handoff.b.e.now(), 'arm': arm,
        'action': 'collect' if collect else 'inspect', 'helper_sha256': handoff.b.sha(__file__),
        'campaign_sha256': handoff.b.sha(run.path / 'campaign.json'),
        'original_source_pod_uid': campaign['client_binding']['pod_uid'],
        'profile_replayed': False, 'inference_started_by_recovery': False,
        'original_controller_exit_preserved': True, 'cleanup_performed': False})
    if not collect:
        print(json.dumps({'remote_exit': status['exit'], 'active': status['exit'] is None,
                          'saved': str(recovery / 'original-remote-status.json')}, indent=2))
        return
    if (folder / 'raw').exists() or (folder / 'raw-artifacts.tar.gz').exists():
        raise ValueError('Prior collection artifacts exist; verify/preserve them before another export.')
    # The controller's failed cleanup must not have released/reassigned this slot.
    handoff.b.c.lease_owned(run)
    startup = json.loads((folder / 'worker-qualification.json').read_text())
    wanted = {v['pod_uid'] for v in startup['workers'].values()}
    pods = handoff.b.e.workers(run)
    if {p['metadata']['uid'] for p in pods} != wanted:
        raise ValueError('Original P/D serving Pods changed; preserve diagnostics before claiming a matched result.')
    snapshot_before(run, folder, recovery)
    handoff.b.e.telemetry_stop(run, arm)
    handoff.b.e.collect_workers(run, arm)
    handoff.b.qualify_workers(run, 'disaggregated', handoff.b.e.workers(run), arm)
    handoff.b.e.collect_frontend_metrics(run, handoff.b.e.endpoint(run), arm, 'after')
    handoff.b.write(folder / 'outcome.json', status['exit'])
    handoff.b.e.collect_profile(run, arm)
    if status['exit']['exit_code'] != 0:
        raise RuntimeError('Original profile failed; raw evidence collected, no comparison acceptance.')
    summary = handoff.b.e.validate_profile(run, arm)
    handoff.b.write(folder / 'integrity-final.json', {str(p.relative_to(folder)): handoff.b.sha(p)
        for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'})
    handoff.b.write(recovery / 'acceptance.json', {'at': handoff.b.e.now(), 'passed': True,
        'arm': arm, 'original_profile_replayed': False, 'original_controller_exit_preserved': True,
        'benchmark_id': summary['benchmark_id'], 'cleanup_performed': False,
        'scope': 'Original detached profile collected after observer-only outage; normal immutable acceptance gates retained'})
    run.result('disagg-disaggregated', 'passed', arm=arm, recovered_original_profile=True,
               source_cpu_uid=campaign['client_binding']['pod_uid'])
    print(json.dumps({'passed': True, 'arm': arm, 'recovery': str(recovery),
                      'benchmark_id': summary['benchmark_id'], 'cleanup_performed': False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'collect'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    recovery(handoff.setup(args.run), args.attempt, args.action == 'collect')


if __name__ == '__main__':
    main()
