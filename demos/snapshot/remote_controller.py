#!/usr/bin/env python3
"""Run one fresh Snapshot qualification inside a detached jump-host container.

The Docker bind preserves the local logical repo path. Existing jump-host
kubectl/kubeconfig are mounted read-only; no credentials enter the source bundle.
Capture/stage/release, the actual presenter PTY and cleanup continue without the
external VPN or chat. This controller never extends immutable SnapshotJob specs.
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
import traceback

ROOT = Path(__file__).resolve().parents[2]
OWNER = 'workshop-snapshot-dgd'
RECORDING_PARENT = Path('demos/transcripts/live/04-snapshot-dgd')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value, *, exclusive=False):
    path = Path(path)
    if exclusive:
        with path.open('x') as stream:
            stream.write(json.dumps(value, indent=2) + '\n')
        return
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def relative(value, prefix=None):
    path = Path(value)
    if path.is_absolute() or str(path) != value or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe relative controller path.')
    if prefix is not None:
        path.relative_to(prefix)
    return path


def read(path):
    return json.loads(Path(path).read_text())


def validate_plan(plan, root):
    if plan.get('schema') != 1 or plan.get('logical_root') != str(root):
        raise ValueError('Snapshot controller plan/root differs.')
    run_relative = relative(plan['run'], Path('results'))
    run = root / run_relative
    if plan.get('mode') not in ('full', 'prime'):
        raise ValueError('Choose an explicit full/prime controller mode.')
    recording = relative(plan.get('recording', str(RECORDING_PARENT / run.name)), RECORDING_PARENT)
    if recording != RECORDING_PARENT / run.name:
        raise ValueError('Recording must belong to this exact fresh run.')
    if plan.get('prime_timeout_seconds') != 5400:
        raise ValueError('Keep the approved bounded prime window.')
    reservation = plan['reservation']
    if reservation.get('agent') != OWNER or reservation.get('run') != str(run):
        raise ValueError('Controller reservation belongs to another run.')
    for name, expected in plan['source_sha256'].items():
        path = root / relative(name)
        if path.is_symlink() or digest(path) != expected:
            raise ValueError('Frozen controller source changed: ' + name)
    for name, expected in plan['run_input_sha256'].items():
        path = run / relative(name)
        if path.is_symlink() or digest(path) != expected:
            raise ValueError('Frozen initial run input changed: ' + name)
    state, demo = read(run / 'state.json'), read(run / 'demo.json')
    if (not demo.get('prepared') or demo.get('rehearsal') is not False or demo.get('storage') != 'nvme'
            or state.get('checks', {}).get('model-staging', {}).get('status') != 'passed'
            or state.get('snapshot_dgd_uid') or state.get('snapshot_dgd_submitted_at')
            or demo.get('initial_identity') or demo.get('cleaned_at') or state.get('replacement_intent')):
        raise ValueError('Controller requires a CPU-prepared, never-deployed fresh NVMe run.')
    if state['namespace'] != demo['namespace'] or not state['namespace'].startswith('dynamo-ft-'):
        raise ValueError('Frozen namespace differs.')
    lease = read(root / '.local/workshop-measurements-20261030.gpu-lease/owner.json')
    if lease != reservation:
        raise ValueError('Mirrored reservation differs from the exact root-owned reservation.')
    return run, root / recording


def prime_proof(run):
    """Check real prepared storage and frontend inference before injecting a fault."""
    import demos.snapshot.dgd as lifecycle
    import demos.snapshot.nvme as storage
    from demos.snapshot.dgd_demo import parse_coding_stream
    state, demo = read(run / 'state.json'), read(run / 'demo.json')
    identity, response = read(run / 'initial-identity.json'), read(run / 'initial-request.json')
    record = state.get(storage.KEY, {})
    source = record.get('source', {})
    if (demo.get('rehearsal') is not False or not demo.get('ready_observed_at')
            or identity != demo.get('initial_identity') or identity.get('dgd_uid') != state.get('snapshot_dgd_uid')
            or identity.get('worker_uid') == identity.get('source_uid')
            or not identity.get('frontend_uid') or not identity.get('service_uid')
            or identity.get('content_uid') != source.get('artifact_uid')
            or not record.get('staged') or not record.get('overlay_verified') or state.get('nvme_overlay') is not True
            or record.get('expected_files', 0) <= 0 or record.get('expected_bytes', 0) <= 0
            or digest(run / storage.MANIFEST) != record.get('hash_manifest_sha256')
            or response.get('request') != read(run / 'request.json')
            or response.get('worker') != identity.get('response_worker')
            or not response.get('worker', {}).get('decode_worker_id')):
        raise ValueError('Remote prime did not establish exact real storage/identity/inference proof.')
    lifecycle.validate_coding_output(response['content'])
    parsed = parse_coding_stream(response['sse'], demo['model'])
    if parsed['content'] != response['content'] or parsed['worker'] != response['worker']:
        raise ValueError('Initial coding result differs from its completed stream evidence.')
    expected = read(run / 'snapshot-dgd-spec.json')
    if (identity.get('node') != expected['settings']['node'] or
            sorted(identity.get('gpu_uuids', [])) != sorted(expected['settings']['gpu_uuids'])):
        raise ValueError('Remote prime placement differs from the qualified pair.')
    return {'simulated': False, 'dgd_uid': identity['dgd_uid'], 'worker_uid': identity['worker_uid'],
        'content_uid': identity['content_uid'], 'node': identity['node'], 'gpu_uuids': identity['gpu_uuids'],
        'hash_manifest_sha256': record['hash_manifest_sha256'], 'files': record['expected_files'],
        'bytes': record['expected_bytes'], 'decode_worker_id': response['worker']['decode_worker_id'],
        'scope': 'Fresh creating DGD, fully verified local staging, initial restore and real frontend coding response.'}


def capture_proof(run, recording):
    import demos.common.capture as capture
    import demos.snapshot.dgd as lifecycle
    valid, reason = capture.completed('04-snapshot-dgd', run, False)
    if not valid:
        raise ValueError('Remote presenter completion failed: ' + reason)
    receipt = read(recording / 'capture.json')
    if (receipt.get('status') != 'live_passed' or receipt.get('demo') != '04-snapshot-dgd'
            or receipt.get('run') != str(run) or receipt.get('mode') != 'live'
            or receipt.get('interrupted') or receipt.get('timed_out')
            or digest(recording / 'main.txt') != receipt.get('transcript_sha256')):
        raise ValueError('Remote capture is not a complete actual main-panel recording.')
    timing, response = read(run / 'timing.json'), read(run / 'response.json')
    if (timing.get('simulated') or any(timing.get(key, 0) <= 0 for key in
            ('pod_to_ready_seconds', 'agent_seconds', 'deletion_to_observed_ready_seconds'))):
        raise ValueError('Require real, separately bounded recovery clocks.')
    lifecycle.validate_coding_output(response['content'])
    for name, expected in receipt['evidence_sha256'].items():
        path = Path(receipt['evidence_snapshot_directory']) / relative(name)
        if digest(path) != expected:
            raise ValueError('Frozen presenter evidence changed: ' + name)
    return {'simulated': False, 'recording': str(recording), 'transcript_sha256': receipt['transcript_sha256'],
        'initial_uid': read(run / 'initial-identity.json')['worker_uid'],
        'replacement_uid': read(run / 'replacement-identity.json')['worker_uid'],
        'timing': timing, 'response_worker': response['worker'], 'scope': 'Actual main panel; separate readiness clocks and fresh final coding inference.'}


def cleanup_proof(run, root):
    state, demo = read(run / 'state.json'), read(run / 'demo.json')
    if (not demo.get('cleaned_at') or state.get('nvme_overlay') or state.get('nvme_mount_helper')
            or any(state.get('checks', {}).get(key, {}).get('status') != 'passed'
                   for key in ('snapshot-dgd-cleanup', 'snapshot-dgd-nvme-cleanup'))
            or (root / '.local/workshop-measurements-20261030.gpu-lease/owner.json').exists()):
        raise ValueError('Owned cleanup or mirrored reservation release is incomplete.')
    return {'cleaned_at': demo['cleaned_at'], 'owned_cleanup': 'passed', 'mirror_reservation_released': True,
        'scope': 'Controller scoped cleanup; root independently audits cluster and releases its local reservation after collection.'}


class Controller:
    def __init__(self, root, plan, run, recording):
        self.root, self.plan, self.run, self.recording = root, plan, run, recording
        self.folder = run / 'remote-controller'
        self.active = None
        self.initial_inputs = dict(read(run / 'demo.json')['inputs'])
        self.initial_inputs['snapshot-dgd-spec.json'] = digest(run / 'snapshot-dgd-spec.json')
        self.outcome = {'schema': 1, 'status': 'running', 'started_at': now(), 'run': str(run),
                        'mode': plan['mode'], 'phases': [], 'default_capture_deadline_seconds': 3600,
                        'deadline_extension_attempted': False, 'external_observer_required': False}

    def unchanged(self):
        for name, expected in self.plan['source_sha256'].items():
            if digest(self.root / relative(name)) != expected:
                raise ValueError('Frozen source changed: ' + name)
        for name, expected in self.initial_inputs.items():
            if digest(self.run / relative(name)) != expected:
                raise ValueError('Frozen executable input changed: ' + name)

    def save(self, phase, **details):
        write(self.run / 'remote-controller.json', {'at': now(), 'phase': phase, **details})

    def stop_child(self):
        if self.active is not None and self.active.poll() is None:
            os.killpg(self.active.pid, signal.SIGINT)
            try:
                self.active.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(self.active.pid, signal.SIGKILL)
                self.active.wait(timeout=15)
        self.active = None

    def command(self, phase, command, timeout):
        self.unchanged()
        folder = self.folder / phase
        folder.mkdir(exist_ok=False)
        entry = {'phase': phase, 'started_at': now(), 'command': command, 'timeout_seconds': timeout}
        self.outcome['phases'].append(entry)
        write(folder / 'command.json', entry)
        with (folder / 'console.log').open('x') as output:
            self.active = subprocess.Popen(command, cwd=self.root, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + timeout
            while self.active.poll() is None:
                self.save(phase, child_pid=self.active.pid, phases=self.outcome['phases'])
                if time.monotonic() >= deadline:
                    self.stop_child()
                    raise TimeoutError('Bounded remote phase expired: ' + phase)
                time.sleep(3)
            code = self.active.returncode
            self.active = None
        entry.update(finished_at=now(), exit_code=code)
        write(folder / 'exit.json', entry)
        if code:
            raise RuntimeError('Remote ' + phase + ' failed; no automatic replay or retuning.')

    def diagnostics(self):
        try:
            from testlib import Run
            import demos.snapshot.dgd as lifecycle
            self.unchanged()
            lifecycle.collect_logs(Run(self.run), phase='remote-failure')
        except BaseException as error:
            self.outcome['diagnostic_error'] = repr(error)

    def execute(self):
        self.folder.mkdir(exist_ok=False)
        write(self.run / 'remote-controller-plan.json', self.plan, exclusive=True)
        write(self.run / 'remote-controller-start.json', {'at': now(), 'pid': os.getpid(),
            'controller_sha256': digest(__file__), 'mode': self.plan['mode'],
            'reservation': self.plan['reservation'], 'default_capture_deadline_seconds': 3600}, exclusive=True)
        presenter = [sys.executable, '-B', '-m', 'demos.snapshot.dgd_demo']
        successful = False
        try:
            self.command('prime', presenter + ['prime', '--auto', '--run', str(self.run), '--timeout', '5400'], 5400)
            self.outcome['prime'] = prime_proof(self.run)
            write(self.folder / 'prime' / 'proof.json', self.outcome['prime'])
            if self.plan['mode'] == 'prime':
                self.outcome.update(status='primed_awaiting_explicit_handoff', lease_retained=True)
                successful = True
                return 0
            self.command('capture', [sys.executable, '-B', '-m', 'demos.common.capture',
                '--demo', '04-snapshot-dgd', '--run', str(self.run), '--output', str(self.recording),
                '--startup-timeout', '1800', '--capture-timeout', '2400', '--quiet'], 2460)
            self.outcome['presenter'] = capture_proof(self.run, self.recording)
            write(self.folder / 'capture' / 'proof.json', self.outcome['presenter'])
            successful = True
            self.outcome['status'] = 'presenter_passed_pending_cleanup'
        except BaseException as error:
            self.stop_child()
            self.outcome.update(status='failed', error=repr(error), traceback=traceback.format_exc())
            self.diagnostics()
        finally:
            if self.plan['mode'] == 'full' or not successful:
                try:
                    self.command('cleanup', presenter + ['cleanup', '--auto', '--run', str(self.run)], 600)
                    self.outcome['cleanup'] = cleanup_proof(self.run, self.root)
                    if successful:
                        self.outcome['status'] = 'qualified_and_cleaned_pending_root_audit'
                except BaseException as error:
                    self.stop_child()
                    self.outcome['cleanup_error'] = repr(error)
                    self.outcome['status'] = 'failed_cleanup_incomplete'
            self.outcome['finished_at'] = now()
            write(self.run / 'remote-controller-exit.json', self.outcome, exclusive=True)
            self.save(self.outcome['status'], result=self.outcome)
            print(json.dumps(self.outcome), flush=True)
        return 0 if self.outcome['status'] == 'qualified_and_cleaned_pending_root_audit' else 1


def execute(plan_path, expected):
    if digest(plan_path) != expected:
        raise ValueError('Remote plan SHA256 differs; no work started.')
    plan = read(plan_path)
    run, recording = validate_plan(plan, ROOT)
    controller = Controller(ROOT, plan, run, recording)
    def interrupted(signum, frame):
        raise InterruptedError('Controller signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    return controller.execute()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    return execute(args.plan, args.plan_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
