#!/usr/bin/env python3
"""One frozen writer-only qualification; no reader, fault, retry or preparation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

import demos.shadow.writer_remote as transport

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value, *, exclusive=False):
    path = Path(path)
    if exclusive:
        transport.common.write_new(path, value)
    else:
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.replace(path)


def serving_proof(run):
    from demos.snapshot.dgd import validate_coding_output
    state, spec = read(run / 'state.json'), read(run / 'descriptor-writer-spec.json')
    checks = state['checks']
    if any(checks.get(key, {}).get('status') != 'passed' for key in
           ('shadow-writer-serving', 'shadow-writer-descriptors')):
        raise ValueError('Writer serving and actual descriptor capture must both pass.')
    responses = read(run / 'coding-responses.json')
    if len(responses) != 3:
        raise ValueError('Require three complete real coding responses.')
    for response in responses:
        validate_coding_output(response['content'])
        chunks = response['chunks']
        if (response['request']['model'] != state['model_lock']['model']
                or 'data: [DONE]' not in response['sse'] or not chunks
                or any(c.get('error') or c.get('model') != state['model_lock']['model'] for c in chunks)
                or not response.get('worker', {}).get('decode_worker_id')
                or not any(choice.get('finish_reason') == 'stop' for c in chunks for choice in c.get('choices', []))):
            raise ValueError('Incomplete writer coding stream/model/worker proof.')
    summary = read(run / 'descriptor-capture.json')
    for rank in (0, 1):
        path = run / 'rank-manifests' / ('rank-' + str(rank) + '.json')
        value = read(path)
        if (transport.sha(path) != summary[str(rank)]['manifest_sha256']
                or value['identity'] != dict(spec['descriptor_identity'], tp_rank=rank)
                or value['version'] != spec['descriptor_version']
                or value.get('reader_ready') is not True or value.get('unhandled_modules')
                or not value.get('gms_memory_layout_hash')):
            raise ValueError('Actual rank descriptor is not ready with exact frozen provenance.')
    return {'responses': 3, 'worker_uid': checks['shadow-writer-serving']['worker_uid'],
            'rank_manifest_sha256': {rank: value['manifest_sha256'] for rank, value in summary.items()},
            'scope': 'Writer-only coding and manifest readiness. No GPU reader, promotion or recovery proof.'}


class Controller:
    def __init__(self, root, plan):
        self.root, self.plan = root, plan
        self.run = root / transport.relative(plan['run'], 'results')
        self.folder = self.run / 'writer-remote-controller'
        self.child = None
        self.result = {'schema': 1, 'status': 'running', 'started_at': transport.now(),
                       'run': str(self.run), 'phases': [], 'reader_enabled': False,
                       'intentional_fault': False, 'automatic_retry': False,
                       'local_reservation_released': False, 'remote_mirror_retained': True}

    def unchanged(self):
        for name, expected in self.plan['source_sha256'].items():
            if transport.sha(self.root / transport.relative(name)) != expected:
                raise ValueError('Frozen controller source changed: ' + name)
        for name, expected in self.plan['immutable_run_sha256'].items():
            if transport.sha(self.run / transport.relative(name)) != expected:
                raise ValueError('Frozen writer input changed: ' + name)
        owner = self.root / '.local' / self.plan['reservation_directory'] / 'owner.json'
        if read(owner) != self.plan['reservation']:
            raise ValueError('Exact mirrored writer reservation changed.')

    def heartbeat(self, phase):
        write(self.run / 'writer-remote-controller.json',
              {'at': transport.now(), 'phase': phase, 'phases': self.result['phases']})

    def stop_child(self):
        if self.child is not None and self.child.poll() is None:
            os.killpg(self.child.pid, signal.SIGINT)
            try:
                self.child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait(timeout=15)
        self.child = None

    def command(self, phase, command, timeout):
        self.unchanged()
        folder = self.folder / phase
        folder.mkdir(exist_ok=False)
        entry = {'phase': phase, 'started_at': transport.now(), 'command': command, 'timeout_seconds': timeout}
        self.result['phases'].append(entry)
        write(folder / 'command.json', entry, exclusive=True)
        try:
            with (folder / 'console.log').open('x') as output:
                self.child = subprocess.Popen(command, cwd=self.root, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                deadline = time.monotonic() + timeout
                while self.child.poll() is None:
                    self.heartbeat(phase)
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Bounded writer phase expired: ' + phase)
                    time.sleep(2)
                entry['exit_code'] = self.child.returncode
                self.child = None
                if entry['exit_code']:
                    raise RuntimeError('Writer phase failed; no replay: ' + phase)
        except BaseException as error:
            self.stop_child()
            entry['error'] = repr(error)
            raise
        finally:
            entry['finished_at'] = transport.now()
            write(folder / 'exit.json', entry, exclusive=True)

    def health(self):
        self.health_attempted = True
        destination = self.run / 'writer-remote-post-health'
        self.command('post-health', [sys.executable, '-B', str(self.root / 'scripts/snapshot_gpu_health.py'),
            '--run', str(destination), '--baseline', str(self.root / self.plan['health_baseline']),
            '--node', self.plan['node']], 300)
        files = list(destination.glob('snapshot-gpu-health-*.json'))
        if len(files) != 1:
            raise ValueError('Require exactly one fresh post-writer health report.')
        return files[0]

    def execute(self):
        self.folder.mkdir(exist_ok=False)
        write(self.run / 'writer-remote-start.json', {'at': transport.now(), 'pid': os.getpid(),
              'controller_sha256': transport.sha(__file__), 'reservation': self.plan['reservation']}, exclusive=True)
        writer = [sys.executable, '-B', '-m', 'demos.shadow.descriptor_writer']
        self.health_attempted = False
        qualified = False
        try:
            self.command('deploy', writer + ['deploy', '--run', str(self.run),
                '--health-before', str(self.root / self.plan['health_before'])], 300)
            self.command('verify', writer + ['verify', '--run', str(self.run), '--timeout', '1500'], 2400)
            self.result['serving'] = serving_proof(self.run)
            after = self.health()
            self.command('finalize', writer + ['finalize', '--run', str(self.run), '--health-after', str(after)], 180)
            if read(self.run / 'state.json')['checks'].get('shadow-writer-qualification', {}).get('status') != 'passed':
                raise ValueError('Final writer health qualification did not pass.')
            qualified = True
        except BaseException as error:
            self.stop_child()
            self.result.update(error=repr(error), traceback=traceback.format_exc())
        finally:
            if not self.health_attempted:
                try:
                    self.health()
                except BaseException as error:
                    self.result['post_health_error'] = repr(error)
            try:
                self.command('cleanup', writer + ['cleanup', '--run', str(self.run)], 600)
                if read(self.run / 'state.json')['checks'].get('shadow-writer-cleanup', {}).get('status') != 'passed':
                    raise ValueError('Scoped writer cleanup did not pass.')
                self.result['cleanup'] = 'passed'
            except BaseException as error:
                self.stop_child()
                self.result['cleanup_error'] = repr(error)
            self.result['status'] = ('qualified_and_cleaned_pending_root_audit' if qualified and
                self.result.get('cleanup') == 'passed' else 'failed_preserved_for_root_audit')
            self.result['finished_at'] = transport.now()
            write(self.run / 'writer-remote-exit.json', self.result, exclusive=True)
            self.heartbeat(self.result['status'])
            print(json.dumps(self.result), flush=True)
        return 0 if self.result['status'] == 'qualified_and_cleaned_pending_root_audit' else 1


def execute(plan_path, expected):
    if transport.sha(plan_path) != expected:
        raise ValueError('Writer plan hash changed.')
    plan = read(plan_path)
    transport.validate_plan(plan, ROOT)
    controller = Controller(ROOT, plan)
    controller.unchanged()
    def interrupted(signum, frame):
        raise InterruptedError('Writer controller signal ' + str(signum))
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    return controller.execute()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    raise SystemExit(execute(args.plan, args.plan_sha256))
