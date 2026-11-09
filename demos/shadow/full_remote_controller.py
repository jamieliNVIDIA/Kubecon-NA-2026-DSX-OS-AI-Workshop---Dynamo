#!/usr/bin/env python3
"""One frozen full Shadow demo; controller artifacts always stay outside Run."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import traceback

import demos.shadow.full_remote as transport
from demos.shadow.writer_remote_controller import Controller as BoundedController, read, write

ROOT = Path(__file__).resolve().parents[2]
DEMO = '08-shadow-engine-composed'


def ready_proof(run):
    import demos.common.capture as capture
    return capture.shadow_composed_provenance(run, read(run / 'demo.json'))


def pending_proof(run, recording, private):
    import demos.common.capture as capture
    receipt = read(recording / 'capture.json')
    if (receipt.get('status') != 'pending_qualification' or receipt.get('demo') != DEMO
            or receipt.get('run') != str(run) or receipt.get('output') != str(recording)
            or receipt.get('raw_output') != str(private) or receipt.get('exit_code') != 0
            or receipt.get('interrupted') is not False or receipt.get('timed_out') is not False
            or receipt.get('defer_qualification') is not True
            or transport.sha(recording / 'pending-main.txt') != receipt.get('transcript_sha256')
            or transport.sha(private / 'main-panel.ansi') != receipt.get('raw_sha256')):
        raise ValueError('Require the complete first-fault pending capture; never retake it automatically.')
    sealed = read(private / 'pending-receipt.json')
    if (transport.sha(private / 'pending-receipt.json') != receipt.get('pending_receipt_sha256')
            or sealed != {key: value for key, value in receipt.items() if key != 'pending_receipt_sha256'}
            or receipt.get('raw_path') != str(private / 'main-panel.ansi')
            or receipt.get('source_snapshot_directory') != str(private / 'sources')
            or receipt.get('evidence_snapshot_directory') != str(private / 'evidence')
            or transport.sha(private / 'timeline.jsonl') != receipt.get('timeline_sha256')
            or transport.sha(private / 'demo-before.json') != receipt.get('state_before_sha256')
            or transport.sha(private / 'pre-fault-health-source.json') != receipt.get('pre_fault_health', {}).get('source_sha256')):
        raise ValueError('Pending first-fault receipt/timeline/before-state/health seal changed.')
    for name, expected in receipt['source_sha256'].items():
        if transport.sha(private / 'sources' / transport.relative(name)) != expected:
            raise ValueError('Pending source snapshot changed: ' + name)
    for name, expected in receipt['evidence_sha256'].items():
        if (transport.sha(private / 'evidence' / transport.relative(name)) != expected
                or transport.sha(run / transport.relative(name)) != expected):
            raise ValueError('Pending Full evidence changed: ' + name)
    proof = capture.validate_shadow_composed_capture(run, read(run / 'demo.json'), require_health=False)
    return {'capture_receipt_sha256': transport.sha(recording / 'capture.json'),
        'transcript_sha256': receipt['transcript_sha256'], 'raw_sha256': receipt['raw_sha256'],
        'provenance': proof, 'scope': 'One actual guarded fault, promotion, fresh coding and replenishment; final health still pending.'}


def final_proof(run, recording, private, pending):
    import demos.common.capture as capture
    receipt = read(recording / 'capture.json')
    if (receipt.get('status') != 'live_passed' or receipt.get('demo') != DEMO
            or receipt.get('run') != str(run) or receipt.get('raw_output') != str(private)
            or receipt.get('output') != str(recording) or receipt.get('startup_provenance') != pending['provenance']
            or receipt.get('transcript') != 'main.txt'
            or receipt.get('transcript_sha256') != pending['transcript_sha256']
            or receipt.get('raw_sha256') != pending['raw_sha256']
            or transport.sha(recording / 'main.txt') != pending['transcript_sha256']
            or transport.sha(private / 'main-panel.ansi') != pending['raw_sha256']):
        raise ValueError('Final qualification must preserve the exact first-fault PTY/transcript.')
    evidence = private / 'final-evidence'
    if receipt.get('final_evidence_snapshot_directory') != str(evidence):
        raise ValueError('Final evidence path differs.')
    for name, expected in receipt['final_evidence_sha256'].items():
        if transport.sha(evidence / transport.relative(name)) != expected:
            raise ValueError('Final frozen evidence changed: ' + name)
    valid, reason = capture.completed(DEMO, evidence, False)
    if not valid:
        raise ValueError(reason)
    proof = capture.validate_shadow_composed_capture(run, read(run / 'demo.json'))
    if proof != pending['provenance']:
        raise ValueError('Final Full provenance differs from the sealed first-fault capture.')
    return {'recording': str(recording), 'transcript_sha256': pending['transcript_sha256'],
        'raw_sha256': pending['raw_sha256'], 'final_evidence_files': len(receipt['final_evidence_sha256']),
        'provenance': proof, 'scope': 'Same-Pod initialized standby promotion and fresh coding; no KV/stream/SLO/node-loss claim.'}


class Controller(BoundedController):
    def __init__(self, root, plan):
        self.root, self.plan = root, plan
        self.run = root / transport.relative(plan['run'], 'results')
        self.control = root / transport.relative(plan['control'], 'results')
        self.recording = root / transport.relative(plan['recording'], 'demos/transcripts/live')
        self.private = root / transport.relative(plan['raw_recording'], 'results')
        if self.run == self.control or self.run in self.control.parents or self.control in self.run.parents:
            raise ValueError('Controller/health artifacts must be outside the Full run.')
        self.folder, self.child = self.control / 'phases', None
        self.health_attempts = set()
        self.result = {'schema': 1, 'status': 'running', 'started_at': transport.now(), 'run': str(self.run),
            'phases': [], 'fault_policy': 'exactly one guarded fault; no retry or redeployment',
            'local_reservation_released': False}

    def unchanged(self):
        for name, expected in self.plan['source_sha256'].items():
            if transport.sha(self.root / transport.relative(name)) != expected:
                raise ValueError('Frozen full controller source changed: ' + name)
        for name, expected in self.plan['immutable_run_sha256'].items():
            if transport.sha(self.run / transport.relative(name)) != expected:
                raise ValueError('Frozen full input changed: ' + name)
        owner = self.root / '.local' / self.plan['reservation_directory'] / 'owner.json'
        if read(transport.regular(owner)) != self.plan['reservation']:
            raise ValueError('Exact Full scoped reservation changed.')

    def heartbeat(self, phase):
        write(self.control / 'full-remote-controller.json',
              {'at': transport.now(), 'phase': phase, 'phases': self.result['phases']})

    def health(self, phase):
        if phase in self.health_attempts:
            raise ValueError('Never replay a health phase or overwrite its evidence.')
        self.health_attempts.add(phase)
        destination = self.control / 'health' / phase
        self.command(phase, [sys.executable, '-B', str(self.root / 'scripts/snapshot_gpu_health.py'),
            '--run', str(destination), '--baseline', str(self.root / self.plan['health_baseline']),
            '--node', self.plan['node']], 300)
        files = list(destination.glob('snapshot-gpu-health-*.json'))
        if len(files) != 1:
            raise ValueError('Require one fresh external health receipt.')
        return files[0]

    def execute(self):
        self.folder.mkdir(exist_ok=False)
        write(self.control / 'full-remote-start.json', {'at': transport.now(), 'pid': os.getpid(),
            'controller_sha256': transport.sha(__file__), 'reservation': self.plan['reservation']}, exclusive=True)
        full = [sys.executable, '-B', '-m', 'demos.shadow.composed']
        run_args = ['--run', str(self.run)]
        capture = [sys.executable, '-B', '-m', 'demos.common.capture',
            '--demo', DEMO, '--run', str(self.run), '--output', str(self.recording),
            '--raw-output', str(self.private), '--quiet']
        qualified = False
        try:
            self.command('deploy', full + ['deploy'] + run_args + ['--health-before', str(self.root / self.plan['health_before'])], 300)
            self.command('wait', full + ['wait'] + run_args + ['--timeout', '1500'], 2400)
            self.result['ready'] = ready_proof(self.run)
            before = self.health('pre-fault-health')
            self.command('capture-pending', capture + ['--defer-qualification', '--pre-fault-health', str(before),
                '--startup-timeout', '1500', '--capture-timeout', '2400'], 2460)
            self.result['pending'] = pending_proof(self.run, self.recording, self.private)
            # No controller journal, health Run or phase logs are written inside
            # self.run here: pending capture only permits canonical finalization.
            after = self.health('post-fault-health')
            self.command('finalize', full + ['finalize'] + run_args + ['--health-after', str(after)], 180)
            self.command('capture-finalize', capture + ['--finalize-pending'], 300)
            self.result['recording'] = final_proof(self.run, self.recording, self.private, self.result['pending'])
            qualified = True
        except BaseException as error:
            self.stop_child()
            self.result.update(error=repr(error), traceback=traceback.format_exc())
        finally:
            if not qualified and not ({'post-fault-health', 'post-failure-health'} & self.health_attempts):
                try:
                    self.health('post-failure-health')
                except BaseException as error:
                    self.result['post_failure_health_error'] = repr(error)
            try:
                self.command('cleanup', full + ['cleanup'] + run_args, 600)
                if (not read(self.run / 'demo.json').get('cleaned_at') or
                        (self.root / '.local' / self.plan['reservation_directory'] / 'owner.json').exists()):
                    raise ValueError('Scoped Full cleanup or remote mirror release is incomplete.')
                self.result.update(cleanup='passed', remote_mirror_released=True)
            except BaseException as error:
                self.stop_child()
                self.result['cleanup_error'] = repr(error)
            self.result['status'] = ('qualified_and_cleaned_pending_root_audit' if qualified and
                self.result.get('cleanup') == 'passed' else 'failed_preserved_for_root_audit')
            self.result['finished_at'] = transport.now()
            write(self.control / 'full-remote-exit.json', self.result, exclusive=True)
            self.heartbeat(self.result['status'])
            print(json.dumps(self.result), flush=True)
        return 0 if self.result['status'] == 'qualified_and_cleaned_pending_root_audit' else 1


def execute(plan_path, expected):
    if transport.sha(plan_path) != expected:
        raise ValueError('Full plan hash changed.')
    plan = read(plan_path)
    transport.validate_plan(plan, ROOT)
    controller = Controller(ROOT, plan)
    controller.unchanged()
    def interrupted(signum, frame): raise InterruptedError('Full controller signal ' + str(signum))
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    return controller.execute()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args();os.umask(0o077)
    raise SystemExit(execute(args.plan, args.plan_sha256))
