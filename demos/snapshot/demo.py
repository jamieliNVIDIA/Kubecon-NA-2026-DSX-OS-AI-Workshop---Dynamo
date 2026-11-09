#!/usr/bin/env python3
"""Same-node Snapshot Pod replacement from a prepared Super VL TP2 artifact."""
from __future__ import annotations

import copy
import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time

import yaml
import demos.common.runtime as ui
import demos.common.support as support
from demos.common.presentation import prose
import snapshot_cuinterpose_tests as model
import snapshot_tp2_nvme_compare as nvme
import snapshot_tp2_storage_compare as control
from snapshot_storage_compare import agent, artifact_path, execute, go_seconds, labels, owned

OWNER = 'workshop-demo-snapshot'
PROFILE = 'super-vl-native-snapshot-v1'
INPUTS = ui.ROOT / 'demos/snapshot'
SOURCE = INPUTS / 'prepared-source.json'
STEPS = [
    ('An initialized engine, saved once', 'Inspect the prepared artifact and restore contract; capture happened offstage.'),
    ('Replace the Pod', 'Delete this demo\'s serving Pod, restore a new one, and follow recovery through readiness.'),
    ('Check what recovered', 'A new Pod UID, the same artifact and compatible GPUs, and a restored engine.'),
    ('Use the recovered engine', 'Make a fresh inference request. In-flight requests and prefix caches are separate concerns.'),
]


def validate_source(snapshot, content, source):
    if (snapshot['metadata']['uid'] != source['snapshot_uid'] or not control.ready(snapshot) or
            content['metadata']['uid'] != source['content_uid'] or not control.ready(content) or
            content['spec']['snapshotRef']['uid'] != source['snapshot_uid'] or
            content['spec']['source']['nodeName'] != source['node'] or
            content['spec']['source']['podRef']['uid'] != source['source_pod_uid'] or
            content['spec'].get('storage') is not None):
        raise ValueError('Prepared Snapshot identity, binding, placement, or readiness changed.')


def restore_timing(log, namespace, name, content_uid):
    summaries = []
    for line in log.splitlines():
        if 'Restore timing summary' in line:
            value = json.loads(line[line.index('{'):])
            if value.get('pod') == namespace + '/' + name:
                summaries.append(value)
    if len(summaries) != 1 or summaries[0].get('content_uid') != content_uid:
        raise ValueError('Need one restore timing summary matching the exact Pod and artifact.')
    summary = summaries[0]
    return {'agent_seconds': go_seconds(summary['restore']['duration']),
            'phases': {k: go_seconds(v) for k, v in summary['restore']['phases'].items()},
            'agent_summary': summary}


def validate_pod(pod, claim, source, lock, previous_uid=None):
    if (pod['metadata']['uid'] in (source['source_pod_uid'], previous_uid) or
            not control.ready(pod) or not any(c['type'] == 'nvidia.com/Restored' and c['status'] == 'True'
                                            for c in pod['status'].get('conditions', []))):
        raise ValueError('Need a distinct Ready Pod with nvidia.com/Restored=True.')
    main = next(c for c in pod['status']['containerStatuses'] if c['name'] == 'main')
    if (main.get('restartCount', 0) or main['imageID'].split('@')[-1] != lock['runtime_image'].split('@')[-1] or
            pod['spec']['nodeName'] != source['node'] or
            pod['metadata'].get('annotations', {}).get('nvidia.com/restore-from') != source['snapshot_name']):
        raise ValueError('Restore image, restart history, node, or annotation changed.')
    pair = sorted([[a['pool'], a['device']] for a in claim['status']['allocation']['devices']['results']])
    if pair != source['physical_gpu_pair']:
        raise ValueError('Physical GPU pair differs from the qualified captured pair.')
    return {'pod': pod['metadata']['name'], 'pod_uid': pod['metadata']['uid'],
            'physical_gpu_pair': pair, 'node': pod['spec']['nodeName'], 'restored': True}


class SnapshotDemo(ui.Demo):
    """Recover a native vLLM Pod using the retained fallback artifact."""
    entrypoint = Path(__file__).resolve()
    compact_output = True

    def __init__(self, args):
        from testlib import Run
        self.args = args
        path = args.run or ui.ROOT / 'results' / ('demo-04-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        self.run = Run(path)
        self.path, self.file = self.run.path, self.run.path / 'demo.json'
        self.source = ui.read_json(SOURCE)
        self.forward = None
        if self.file.exists():
            self.data = ui.read_json(self.file)
            if self.data.get('snapshot_profile') != PROFILE or self.data['rehearsal'] != args.rehearsal:
                raise ValueError('Incompatible demo run/profile; use a fresh directory.')
            if args.storage is not None and args.storage != self.data['storage']:
                raise ValueError('Storage is frozen for this run; use a fresh directory.')
            if args.action != 'cleanup':
                self.check_inputs()
        else:
            self.run.ns = self.source['namespace']
            self.run.state.update(namespace=self.run.ns, source_namespace=self.run.ns,
                                  run_id='snapshot-demo-' + hashlib.sha256(str(self.path).encode()).hexdigest()[:10],
                                  artifact_uid=self.source['content_uid'], workers=[],
                                  model_lock=ui.read_json(ui.MODEL_LOCK))
            self.run.save()
            self.data = {'schema': 1, 'snapshot_profile': PROFILE, 'demo_kind': 'snapshot',
                         'rehearsal': args.rehearsal, 'storage': args.storage or 'nvme', 'namespace': self.run.ns,
                         'created_at': ui.now(), 'prepared': False, 'step': 0, 'restores': [],
                         'model': self.run.state['model_lock']['model'],
                         'pod_selector': 'snapshot-storage-experiment=' + self.run.state['run_id'],
                         'resource_kinds': 'podsnapshots', 'log_files': ['restore-agent.log', 'restored-worker.log'],
                         'resource_note': 'Native vLLM fallback / same node / TP2. Operator variant: snapshot-dgd.'}
            job = yaml.safe_load((ui.ROOT / self.source['capture_template']).read_text())
            job['metadata']['namespace'] = self.run.ns
            ui.write_json(self.path / 'snapshotjob.json', job)
            (self.path / 'artifact-files.sha256').write_bytes((INPUTS / 'artifact-files.sha256').read_bytes())
            support.write_yaml(self.path / 'snapshot-settings.yaml', {
                'scope': 'Native vLLM Snapshot restore. Operator-managed variant: snapshot-dgd.',
                'initialize_once': {'resource': 'SnapshotJob', 'name': self.source['snapshot_name'],
                                    'tensor_parallel_size': 2, 'capture': 'prepared offstage'},
                'artifact': {'content_uid': self.source['content_uid'], 'bytes': self.source['logical_bytes'],
                             'restore_storage': self.data['storage'], 'node': self.source['node']},
                'replacement_pod': {'annotations': {'nvidia.com/restore-from': self.source['snapshot_name']}},
                'what_survives': 'Initialized engine. KV cache was released before capture; no live stream is saved.'})
            self.data['source_hashes'] = {str(p.relative_to(ui.ROOT)): ui.digest(p) for p in
                (SOURCE, ui.MODEL_LOCK, ui.ROOT / self.source['capture_template'],
                 ui.ROOT / 'configs/snapshot-upgrade-20261022/images.json',
                 ui.ROOT / 'scripts/snapshot_cuinterpose_app.py')}
            self.data['inputs'] = {n: ui.digest(self.path / n) for n in
                                   ('snapshotjob.json', 'artifact-files.sha256', 'snapshot-settings.yaml')}
            self.save()
        self.ns = self.data['namespace']
        if self.data.get('cleaned_at') and args.action not in ('cleanup', 'preview') and not args.preview:
            raise ValueError('This demo was cleaned up. Use a fresh run.')

    def check_inputs(self):
        for name, sha in self.data['source_hashes'].items():
            if ui.digest(ui.ROOT / name) != sha:
                raise ValueError('Source changed: ' + name)
        for name, sha in self.data['inputs'].items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen input changed: ' + name)
        if ui.digest(self.path / 'artifact-files.sha256') != self.source['hash_manifest_sha256']:
            raise ValueError('Artifact hash manifest is not the qualified one.')

    def preview(self):
        print((self.path / 'snapshot-settings.yaml').read_text())
        print('Offstage prime verifies retained artifact/storage and starts a disposable restored serving Pod.')
        print('Onstage replacement uses a second distinct Pod. No cold-start speedup is assumed.')

    def check_source(self):
        snapshot = self.run.get('get', 'podsnapshot', self.source['snapshot_name'], '-n', self.ns)
        content = self.run.get('get', 'podsnapshotcontent', snapshot['status']['boundSnapshotContentName'])
        validate_source(snapshot, content, self.source)
        ui.write_json(self.path / 'source-snapshot.json', snapshot)
        ui.write_json(self.path / 'source-content.json', content)

    def check_agent(self):
        pod = agent(self.run)  # Also checks the saved UID after preparation.
        pins = ui.read_json(ui.ROOT / 'configs/snapshot-upgrade-20261022/images.json')
        for name in ('agent', 'pagebroker'):
            image = next(p['image'] for p in pins if '/' + name + '@' in p['image'])
            status = next(c for c in pod['status']['containerStatuses'] if c['name'] == name)
            if status['imageID'] != image or not status['ready'] or status.get('restartCount', 0):
                raise ValueError('Snapshot build, readiness or restart history changed.')
        return pod

    def prepare(self):
        self.check_inputs()
        if self.args.rehearsal:
            print('[REHEARSAL] Artifact, GPU compatibility and prepared storage checks simulated.')
        else:
            ui.acquire(self.path, OWNER)
            if self.data['prepared']:
                self.check_source()
                self.check_agent()
                return
            control.idle(self.run)
            active = [j for j in self.run.get('get', 'snapshotjobs', '-A')['items'] if not any(
                c['type'] in ('Completed', 'Failed') and c['status'] == 'True'
                for c in j.get('status', {}).get('conditions', []))]
            if active:
                raise ValueError('Another Snapshot capture is active; defer preparation.')
            namespace = self.run.get('get', 'namespace', self.ns)
            if namespace['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != 'kubecon-dynamo-feature-tests':
                raise ValueError('Retained capture namespace is not an owned feature-test namespace.')
            self.check_source()
            pod = self.check_agent()
            self.run.state['agent_uid'] = pod['metadata']['uid']
            self.run.save()
            ui.write_json(self.path / 'agent-before.json', pod)
            # The retained namespace supplies the captured app/config/PVC. Verify its source code.
            config = self.run.get('get', 'configmap', 'snapshot-cuinterpose-app', '-n', self.ns)
            app = config.get('data', {}).get('app.py', '')
            if hashlib.sha256(app.encode()).hexdigest() != ui.digest(ui.ROOT / 'scripts/snapshot_cuinterpose_app.py'):
                raise ValueError('Captured app ConfigMap differs from the qualified adapter.')
            if self.data['storage'] == 'nvme':
                nvme.verify_disk(self.run)
                # Reuse only: never overwrite, copy, mount a host disk, or format one.
                p = agent(self.run)
                result = self.run.k('exec', '-i', '-n', control.SYSTEM, p['metadata']['name'], '-c', 'agent', '--',
                    'sh', '-c', 'set -eu; cd "$1"; sha256sum --strict --status -c -; '
                    'find . -type f -printf \'%s\\n\' | awk \'{n++;b+=$1} END {printf "files %d bytes %.0f\\n",n,b}\'',
                    'verify-existing-artifact', nvme.local_path(self.run),
                    input_text=(self.path / 'artifact-files.sha256').read_text(), timeout=600)
                expected = f'files {self.source["files"]} bytes {self.source["logical_bytes"]}'
                if expected not in result.stdout:
                    raise ValueError('Prepared NVMe artifact file count/size differs.')
                (self.path / 'nvme-verification.log').write_text(result.stdout)
                nvme.build_helper(self.run)
                if not self.run.state.get('nvme_overlay'):
                    nvme.nvme_view(self.run)
                else:
                    self.storage_ready()
            else:
                actual = execute(self.run, 'findmnt -n -o FSTYPE -T "$1"', artifact_path(self.run)).stdout.strip()
                if actual != 'nfs4':
                    raise ValueError('Expected the unmodified EFS artifact view.')
        self.data['prepared'] = True
        self.save()

    def prime(self):
        self.prepare()
        if not self.data['restores']:
            print('\nOffstage: start and verify a disposable serving Pod from the prepared engine.')
            self.start_restore()
            # The application itself generates READY before marking serving-ready.
        else:
            self.check_identity()
        print('Primed. Keep this run for the onstage Pod replacement; capture is not repeated.')

    def make_manifest(self, name):
        pod = model.restore_manifest(self.run, name)
        pod['metadata'].update(namespace=self.ns, labels={**labels(self.run), 'workshop-demo': 'snapshot'})
        # Allow the primed service to survive offstage preparation + the session.
        pod['spec']['activeDeadlineSeconds'] = 21600
        from gpu_claims import prepare
        objects, claims = prepare([pod], self.run.state['model_lock'])
        # Count alone follows allocator ordering. Select the qualified hardware
        # explicitly instead of discovering a different pair after restoration.
        expression = ('device.driver == "gpu.nvidia.com" && '
                      'has(device.attributes["gpu.nvidia.com"].uuid) && '
                      'device.attributes["gpu.nvidia.com"].uuid in ' +
                      json.dumps(self.source['physical_gpu_uuids']))
        for claim in claims:
            claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'] = [
                {'cel': {'expression': expression}}]
        for obj in objects + claims:
            obj['metadata'].update(namespace=self.ns, labels={**labels(self.run), 'workshop-demo': 'snapshot'})
        return {'apiVersion': 'v1', 'kind': 'List', 'items': claims + objects}

    def storage_ready(self):
        self.check_source()
        self.check_agent()
        actual = execute(self.run, 'findmnt -n -o FSTYPE -T "$1"', artifact_path(self.run)).stdout.strip()
        if actual != ('ext4' if self.data['storage'] == 'nvme' else 'nfs4'):
            raise ValueError('Artifact storage view changed.')

    def start_restore(self):
        intent = self.data.get('pending_restore')
        if not self.args.rehearsal:
            if not ui.lease_owned(self.path, OWNER):
                raise RuntimeError('This run does not own the GPU lease.')
            self.storage_ready()
        index = len(self.data['restores']) + 1
        name = intent['name'] if intent else self.run.state['run_id'] + '-' + str(index)
        manifest = self.make_manifest(name)
        ui.write_json(self.path / (name + '.json'), manifest)
        existing = None
        if not self.args.rehearsal:
            result = self.run.k('get', 'pod', name, '-n', self.ns, '-o', 'json', check=False)
            if result.returncode == 0:
                existing = json.loads(result.stdout)
                owned(self.run, existing)
                if not intent or (intent.get('pod_uid') and intent['pod_uid'] != existing['metadata']['uid']):
                    raise ValueError('Restore Pod already exists without a matching pending intent.')
            elif 'NotFound' not in result.stderr:
                raise RuntimeError(result.stderr)
            if existing is None:
                control.idle(self.run)
        if not existing:
            self.show_command(self.run.kbase + ['apply', '-f', str(self.path / (name + '.json'))])
        self.data['active_pod'] = name
        self.data['apply_started_at'] = intent['applied_at'] if intent else ui.now()
        self.data['pending_restore'] = {'name': name, 'applied_at': self.data['apply_started_at'],
                                        'pod_uid': existing['metadata']['uid'] if existing else None}
        self.data.pop('ready_observed_at', None)
        self.save()
        if name not in self.run.state['workers']:
            self.run.state['workers'].append(name)
            self.run.save()
        if not self.args.rehearsal and existing is None:
            self.run.apply(manifest['items'])
            created = self.run.get('get', 'pod', name, '-n', self.ns)
            self.data['pending_restore']['pod_uid'] = created['metadata']['uid']
            self.save()
        elif existing:
            print('Continuing this restore; preserving the original startup timestamp.')
        else:
            print('[REHEARSAL] Replacement Pod created (simulated).')
        self.wait()
        record = self.validate_live()
        self.data['restores'].append(record)
        self.data.pop('pending_restore', None)
        self.data.pop('replacement_pending', None)
        self.save()

    def wait(self):
        if self.args.rehearsal:
            for stage in range(4):
                self.data['startup'] = {'ready': stage == 3, 'total_seconds': None, 'phases': [
                    {'name': n, 'seconds': None, 'status': 'done' if i < stage or stage == 3 else
                     'running' if i == stage else 'pending'}
                    for i, n in enumerate(('Pod startup', 'Process restore', 'GPU restore', 'Readiness'))]}
                self.save()
                if not self.args.auto:
                    time.sleep(1)
            (self.path / 'restore-agent.log').write_text('REHEARSAL: example process restore -> GPU restore -> complete\n')
            (self.path / 'restored-worker.log').write_text('REHEARSAL: wake engine -> resume -> fresh inference -> serving\n')
        else:
            end = time.monotonic() + self.args.timeout
            while time.monotonic() < end:
                pod = self.run.get('get', 'pod', self.data['active_pod'], '-n', self.ns)
                support.healthy([pod])
                logs = self.run.k('logs', agent(self.run)['metadata']['name'], '-n', control.SYSTEM, '-c', 'agent',
                                  '--timestamps=true', '--tail=2000').stdout
                (self.path / 'restore-agent-full.log').write_text(logs)
                # Keep the pane focused on this Pod, rather than historical restore events.
                scoped = [line for line in logs.splitlines() if self.data['active_pod'] in line]
                (self.path / 'restore-agent.log').write_text('\n'.join(scoped) + '\n')
                app = self.run.k('logs', self.data['active_pod'], '-n', self.ns, '-c', 'main',
                                 '--timestamps=true', check=False)
                if app.returncode == 0:
                    (self.path / 'restored-worker.log').write_text(app.stdout)
                elapsed = (dt.datetime.now(dt.timezone.utc) - ui.timestamp(self.data['apply_started_at'])).total_seconds()
                self.data['startup'] = {'ready': control.ready(pod), 'total_seconds': elapsed, 'phases': [
                    {'name': 'Restore / ready', 'status': 'done' if control.ready(pod) else 'running',
                     'seconds': elapsed, 'source': 'elapsed since apply; exact phases follow the agent summary'}]}
                self.save()
                if control.ready(pod):
                    break
                time.sleep(2)
            else:
                raise TimeoutError('Restored Pod did not become Ready.')
        self.data['ready_observed_at'] = ui.now()
        self.save()

    def validate_live(self):
        if self.args.rehearsal:
            return {'simulated': True, 'pod': self.data['active_pod'], 'pod_uid': 'simulated-' + self.data['active_pod'],
                    'content_uid': self.source['content_uid'], 'agent_seconds': None, 'phases': {},
                    'pod_to_ready_seconds': None}
        from gpu_claims import verify_allocation
        pod = self.run.get('get', 'pod', self.data['active_pod'], '-n', self.ns)
        owned(self.run, pod)
        support.healthy([pod])
        claim = verify_allocation(self.run, pod, next(c for c in pod['spec']['containers'] if c['name'] == 'main'), 2)
        previous_uid = self.data['restores'][-1]['pod_uid'] if self.data['restores'] and self.data['restores'][-1]['pod'] != pod['metadata']['name'] else None
        record = validate_pod(pod, claim, self.source, self.run.state['model_lock'], previous_uid)
        logs = self.run.k('logs', agent(self.run)['metadata']['name'], '-n', control.SYSTEM, '-c', 'agent',
                          '--timestamps=true', '--tail=2000').stdout
        (self.path / (pod['metadata']['name'] + '-agent.log')).write_text(logs)
        record.update(restore_timing(logs, self.ns, pod['metadata']['name'], self.source['content_uid']))
        ready_at = next(c['lastTransitionTime'] for c in pod['status']['conditions'] if c['type'] == 'Ready')
        record.update(simulated=False, content_uid=self.source['content_uid'],
                      pod_to_ready_seconds=(ui.timestamp(ready_at) - ui.timestamp(pod['metadata']['creationTimestamp'])).total_seconds())
        for suffix, obj in [('pod', pod), ('claim', claim), ('record', record)]:
            ui.write_json(self.path / (pod['metadata']['name'] + '-' + suffix + '.json'), obj)
        return record

    def check_identity(self):
        if self.args.rehearsal:
            return
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('Snapshot demo no longer owns the GPU lease.')
        self.storage_ready()
        pod = self.run.get('get', 'pod', self.data['active_pod'], '-n', self.ns)
        owned(self.run, pod)
        support.healthy([pod])
        if not control.ready(pod) or pod['metadata']['uid'] != self.data['restores'][-1]['pod_uid']:
            raise ValueError('Restored serving Pod changed; do not use its previous evidence.')

    def replace(self):
        if not self.data.get('replacement_pending'):
            self.check_identity()
            name = self.data['active_pod']
            self.show_command(self.run.kbase + ['delete', 'pod', name, '-n', self.ns, '--wait=true'])
            # Durable intent makes interruption after deletion recoverable without reusing a Pod UID.
            self.data['replacement_pending'] = True
            self.save()
        else:
            name = self.data['restores'][-1]['pod']
            print('Continuing the recorded Pod replacement.')
        if not self.args.rehearsal and not self.data.get('pending_restore'):
            if not ui.lease_owned(self.path, OWNER):
                raise RuntimeError('Snapshot demo no longer owns the lease.')
            control.delete_worker(self.run, name)
            for _ in range(60):
                if not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Old GPU claims remain; restore deferred.')
        self.start_restore()
        self.summary()

    def summary(self):
        record = self.data['restores'][-1]
        result = {**record, 'storage': self.data['storage'],
                  'apply_to_ready_seconds': self.data['startup']['total_seconds'],
                  'note': 'Capture, NVMe staging and artifact verification happened offstage. '
                          'Agent restore and Pod-to-Ready have different boundaries; do not add them. '
                          'No matched cold-start baseline is included.'}
        ui.write_json(self.path / 'timing.json', result)
        print('\nRestore timing' + (' · REHEARSAL / not measured' if self.args.rehearsal else ''))
        for label, value in [('Pod to Ready', record['pod_to_ready_seconds']), ('Agent restore', record['agent_seconds'])]:
            print(label + ': ' + (f'{value:.2f}s' if value is not None else 'not measured'))
        for name, seconds in record['phases'].items():
            print(f'  {name:24s} {seconds:8.3f}s')
        print(prose(result['note']))

    def show_artifact(self):
        self.check_identity()
        self.command(['cat', self.path / 'snapshot-settings.yaml'])
        if self.args.rehearsal:
            print('[REHEARSAL] Prepared Snapshot/content Ready; primed serving Pod available (simulated).')
        else:
            self.kubectl('get', 'podsnapshot', self.source['snapshot_name'], '-n', self.ns)
        print(prose('This fallback uses native Snapshot resources. The snapshot-dgd variant demonstrates operator-managed recovery.'))

    def show_proof(self):
        self.check_identity()
        records = self.data['restores']
        proof = {'simulated': self.args.rehearsal, 'before_uid': records[-2]['pod_uid'],
                 'after_uid': records[-1]['pod_uid'], 'content_uid': self.source['content_uid'],
                 'node': self.source['node'], 'physical_gpu_pair': self.source['physical_gpu_pair'],
                 'scope': 'Same-node initialized-engine recovery. KV released before capture; no active request saved.'}
        ui.write_json(self.path / 'recovery-proof.json', proof)
        summary = ('Recovery proof' + (' · REHEARSAL / simulated identities' if self.args.rehearsal else '') + '\n' +
                   f'{"Resource":30s} Result\n' +
                   f'{"Serving Pod":30s} replaced\n' +
                   f'{"Prepared Snapshot/content":30s} unchanged\n' +
                   f'{"Node and physical GPU pair":30s} unchanged\n' +
                   f'{"Restored engine":30s} Ready\n')
        (self.path / 'recovery-summary.txt').write_text(summary)
        self.command(['cat', self.path / 'recovery-summary.txt'])
        print('Exact Pod, artifact and GPU identities: recovery-proof.json. No active request was saved.')

    def request(self):
        self.check_identity()
        port = self.args.port
        args = self.run.kbase + ['port-forward', '-n', self.ns, 'pod/' + self.data['active_pod'],
                                 f'{port}:8000', '--address=127.0.0.1']
        self.show_command(args)
        if not self.args.rehearsal:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
            with (self.path / 'port-forward.log').open('a') as out:
                self.forward = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT)
            for _ in range(40):
                if self.forward.poll() is not None:
                    raise RuntimeError('Port-forward stopped; inspect port-forward.log.')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                raise TimeoutError('Port-forward did not open.')
        args = ['curl', '--fail', '--silent', '--show-error', '--max-time', '180', f'http://127.0.0.1:{port}/test']
        self.show_command(args)
        if self.args.rehearsal:
            response = {'text': 'READY', 'model': self.data['model'],
                        'revision': self.run.state['model_lock']['revision'], 'tp': 2, 'simulated': True}
        else:
            response = json.loads(self.run.command(args, timeout=200).stdout)
            lock = self.run.state['model_lock']
            if (response.get('text', '').strip('.') != 'READY' or response.get('model') != lock['model'] or
                    response.get('revision') != lock['revision'] or response.get('tp') != 2):
                raise ValueError('Fresh restored inference failed identity/output checks.')
            self.check_identity()
        ui.write_json(self.path / 'response.json', response)
        print(json.dumps(response, indent=2))
        print(prose('This qualified artifact exposes /test and generates READY. Coding-agent chat and Dynamo registration remain integration work.'))

    def require_primed(self):
        self.check_inputs()
        if self.args.rehearsal and not self.data['restores']:
            previous_auto = self.args.auto
            try:
                self.args.auto = True
                with contextlib.redirect_stdout(io.StringIO()):
                    self.prime()
            finally:
                self.args.auto = previous_auto
        if not self.data['prepared'] or not self.data['restores']:
            command = ui.presenter_command(self.entrypoint, 'prime', '--run', ui.repo_path(self.path), '--auto')
            raise ValueError('Run prime offstage first; artifact checks and the initial restore are not presentation steps:\n' +
                             shlex.join(command))

    def guided(self):
        self.require_primed()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal; use --rehearsal --plain --auto offline.')
        print('\nDynamo workshop · Snapshot Pod recovery\n' +
              ('REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER') +
              '\nRun: ' + ui.repo_path(self.path) + '\nNamespace: ' + self.ns, flush=True)
        if self.data.get('replacement_pending'):
            print('An interrupted replacement is pending; resume at the replacement step.')
            self.run_steps(STEPS[1:], [self.replace, self.show_proof, self.request], start=2, total=len(STEPS))
        else:
            self.run_steps(STEPS, [self.show_artifact, self.replace, self.show_proof, self.request])

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        if self.data.get('cleaned_at'):
            print('Already cleaned up.')
            return
        if not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('Snapshot run does not own the lease; cleanup deferred.')
        for name in self.run.state.get('workers', []):
            control.delete_worker(self.run, name)  # Requires the exact per-run ownership label.
        for _ in range(60):
            if not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
                break
            time.sleep(2)
        else:
            raise RuntimeError('GPU claims still remain; cleanup/lease retained.')
        control.idle(self.run)
        if self.run.state.get('nvme_overlay'):
            nvme.efs_view(self.run)
        helper = self.run.state.get('nvme_mount_helper')
        if helper:
            expected = '/tmp/snapshot-nvme-tools-' + self.run.state['run_id'] + '/nvme-bind'
            if helper != expected:
                raise ValueError('Unexpected mount-helper path; inspect manually.')
            execute(self.run, 'set -eu; rm -f "$1/nvme-bind"; rmdir "$1"', str(Path(helper).parent))
            self.run.state.pop('nvme_mount_helper')
            self.run.save()
        self.check_source()
        if (self.path / 'agent-before.json').exists():
            if self.check_agent()['spec'] != ui.read_json(self.path / 'agent-before.json')['spec']:
                raise ValueError('Shared agent specification changed; lease retained.')
        support.release(self.path, OWNER)
        self.data['cleaned_at'] = ui.now()
        self.save()
        print('Owned restore Pods removed; EFS view restored; lease released. Artifacts and capture namespace retained.')


if __name__ == '__main__':
    support.launch(SnapshotDemo, STEPS, 18003, snapshot=True)
