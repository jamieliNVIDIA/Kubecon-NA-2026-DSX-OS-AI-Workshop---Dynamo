#!/usr/bin/env python3
"""Present operator-managed Snapshot Pod recovery through the Dynamo frontend.

The fresh checkpoint is captured and staged offstage. The creating DGD remains
alive through replacement. The older native presenter remains a separate demo.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import yaml

import demos.common.runtime as ui
import demos.common.support as support
import demos.snapshot.dgd as lifecycle
import demos.snapshot.nvme as storage
from snapshot_storage_compare import agent
from demos.snapshot.demo import restore_timing

PROFILE_FILE = ui.ROOT / 'demos/snapshot/dgd-profile.json'
PROFILE = 'super-vl-dgd-snapshot-upstream-nvme-presenter-v1'
OWNER = lifecycle.LEASE_OWNER
STEPS = [
    ('An initialized Dynamo worker, saved once', 'Inspect the DGD checkpoint settings; capture and storage staging happened offstage.'),
    ('Replace the worker Pod', 'Delete only the worker. The operator restores its replacement while the frontend stays put.'),
    ('Check what recovered', 'A new Pod and worker, the same DGD, frontend, checkpoint, node and GPU pair.'),
    ('Use the recovered service', 'Submit a fresh coding request through the unchanged HTTP frontend.'),
]


def excerpt(objects):
    """Project real DGD fields; the complete executable manifest remains saved."""
    graph = next(item for item in objects if item['kind'] == 'DynamoGraphDeployment')
    components = []
    for component in graph['spec']['components']:
        item = {key: component[key] for key in ('name', 'type', 'replicas')}
        main = component['podTemplate']['spec']['containers'][0]
        if component['type'] == 'frontend':
            item['podTemplate'] = {'spec': {'containers': [{'name': main['name'],
                'command': ui._InlineList(main['command']), 'args': ui._InlineList(main['args'])}]}}
        else:
            item['experimental'] = {'checkpoint': ui._InlineMap({key: component['experimental']['checkpoint'][key]
                                                   for key in ('enabled', 'startupPolicy', 'deletionPolicy')})}
            args = main['args']
            selected = []
            for flag in ('--model', '--tensor-parallel-size', '--max-model-len'):
                selected.extend([flag, args[args.index(flag) + 1]])
            item['podTemplate'] = {'spec': {'containers': [{'name': main['name'],
                'command': ui._InlineList(main['command']), 'args': ui._InlineList(selected)}]}}
        components.append(item)
    return yaml.dump({'kind': graph['kind'], 'metadata': {'name': graph['metadata']['name']},
        'spec': {'backendFramework': graph['spec']['backendFramework'], 'components': components}},
        Dumper=ui._ExcerptDumper, sort_keys=False, width=96)


def parse_coding_stream(raw, model):
    chunks, done = [], False
    for line in raw.splitlines():
        if line == 'data: [DONE]':
            done = True
        elif line.startswith('data: '):
            chunks.append(json.loads(line[6:]))
    if not done or not chunks or any(c.get('error') for c in chunks):
        raise ValueError('Coding stream did not finish cleanly.')
    if any(c.get('model') not in (None, model) for c in chunks):
        raise ValueError('Coding stream model changed.')
    if not any(choice.get('finish_reason') == 'stop' for c in chunks for choice in c.get('choices', [])):
        raise ValueError('Coding stream has no successful stop.')
    text = ''.join(choice.get('delta', {}).get('content') or '' for c in chunks for choice in c.get('choices', []))
    worker = next((c['nvext']['worker_id'] for c in reversed(chunks) if c.get('nvext', {}).get('worker_id')), None)
    if not worker or not worker.get('decode_worker_id'):
        raise ValueError('Coding stream has no decode-worker identity.')
    return {'content': lifecycle.validate_coding_output(text), 'worker': worker, 'chunks': chunks, 'sse': raw}


class SnapshotDgdDemo(ui.Demo):
    """Recover a same-node Dynamo-managed Super VL worker from a fresh checkpoint."""
    entrypoint = Path(__file__).resolve()
    compact_output = True

    def __init__(self, args):
        from testlib import Run
        self.args, self.forward = args, None
        path = args.run or ui.ROOT / 'results' / ('demo-04-dgd-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        if (Path(path) / 'state.json').exists() and not (Path(path) / 'demo.json').exists():
            raise ValueError('Use a fresh presenter run; do not adopt another run or incomplete initialization.')
        requested = ui.requested_lease()
        self.run = Run(path)
        self.path, self.file = self.run.path, self.run.path / 'demo.json'
        self.profile = ui.read_json(PROFILE_FILE)
        if self.file.exists():
            self.data = ui.read_json(self.file)
            ui.record_lease(self.data, requested, existing=True)
            if self.data.get('snapshot_profile') != PROFILE or self.data['rehearsal'] != args.rehearsal:
                raise ValueError('Incompatible Snapshot presenter/profile; use a fresh run.')
            if args.storage is not None and args.storage != self.data['storage']:
                raise ValueError('Storage choice is frozen; use a fresh run.')
            self.spec = lifecycle.load_spec(self.run)
            if args.action != 'cleanup':
                self.check_inputs()
        else:
            if self.run.state.get('snapshot_dgd_uid') or self.run.state.get('snapshot_dgd_submitted_at'):
                raise ValueError('Use a fresh presenter run; do not adopt an existing qualification DGD.')
            suffix = hashlib.sha256(str(self.path).encode()).hexdigest()[:10]
            self.run.ns = 'dynamo-ft-snapshot-demo-' + suffix
            lock = ui.read_json(ui.MODEL_LOCK)
            lock.update(manifest_directory='workshop-snapshot-dgd', snapshot_cuinterpose=True, snapshot_launch_job=False)
            selected_storage = args.storage or 'nvme'
            self.run.state.update(namespace=self.run.ns, run_id='snapshot-demo-' + suffix,
                model_lock=lock, model_cache_run_id=self.profile['cache_source'], snapshot_dgd_node=self.profile['node'])
            if selected_storage == 'nvme':
                self.run.state['snapshot_dgd_storage_gate'] = 'nvme'
            self.run.save()
            ui.write_json(self.path / 'model-lock.json', lock)
            settings = {key: self.profile[key] for key in ('node', 'gpu_uuids', 'patch_configmap', 'patch_sha256', 'module_path')}
            settings['cache_home'] = '/model-cache/feature-tests/' + self.profile['cache_source'] + '/hf'
            self.spec = lifecycle.freeze(self.run, settings)
            patch = yaml.safe_load((ui.ROOT / self.profile['runtime_patch']).read_text())
            if lifecycle.sha256(patch['data']['snapshot.py'].encode()) != settings['patch_sha256']:
                raise ValueError('Runtime overlay differs from the qualified candidate.')
            candidate = ui.read_json(ui.ROOT / self.profile['candidate'])
            if candidate['patched_sha256'] != settings['patch_sha256'] or candidate['runtime_image'] != lock['runtime_image']:
                raise ValueError('Candidate image or runtime overlay pin changed.')
            patch['metadata'].update(namespace=self.run.ns, labels=self.run.labels())
            support.write_yaml(self.path / 'runtime-patch.yaml', patch)
            objects = ui.read_json(self.path / 'deployment.json')['items']
            (self.path / 'deployment-excerpt.yaml').write_text(excerpt(objects))
            ui.write_json(self.path / 'request.json', {'model': lock['model'], 'messages': [{'role': 'user', 'content':
                'Write a short Python function add(a, b) that returns their sum. Reply with code only.'}],
                'temperature': 0, 'max_completion_tokens': 64, 'chat_template_kwargs': {'enable_thinking': False},
                'stream': True, 'stream_options': {'include_usage': True},
                'nvext': {'extra_fields': ['worker_id', 'timing']}})
            sources = (PROFILE_FILE, ui.MODEL_LOCK, lifecycle.TEMPLATE,
                       ui.ROOT / self.profile['candidate'], ui.ROOT / self.profile['runtime_patch'],
                       Path(lifecycle.__file__), Path(storage.__file__), Path(__file__))
            self.data = {'schema': 1, 'snapshot_profile': PROFILE, 'demo_kind': 'snapshot-dgd',
                'rehearsal': args.rehearsal, 'namespace': self.run.ns, 'model': lock['model'],
                'storage': selected_storage, 'created_at': ui.now(), 'step': 0, 'prepared': False,
                'pod_selector': 'feature-test-run=' + self.run.ns, 'resource_kinds': 'dgd,podsnapshots',
                'resource_note': 'Dynamo-managed / same node / TP2 / prepared ' + selected_storage + ' checkpoint',
                'log_files': ['restore-agent.log', 'restored-worker.log'],
                'source_hashes': {str(p.relative_to(ui.ROOT)): ui.digest(p) for p in sources},
                'inputs': {name: ui.digest(self.path / name) for name in
                    ('deployment.json', 'deployment.yaml', 'deployment-excerpt.yaml', 'runtime-patch.yaml', 'model-lock.json', 'request.json')}}
            ui.record_lease(self.data, requested, existing=False)
            self.save()
        self.ns = self.run.ns
        if self.data.get('cleaned_at') and args.action not in ('cleanup', 'preview') and not args.preview:
            raise ValueError('This presenter was cleaned up; use a fresh run/capture.')

    def check_inputs(self):
        for name, sha in self.data['source_hashes'].items():
            if ui.digest(ui.ROOT / name) != sha:
                raise ValueError('Source changed: ' + name)
        for name, sha in self.data['inputs'].items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen demo input changed: ' + name)

    def preview(self):
        print((self.path / 'deployment-excerpt.yaml').read_text())
        print('Focused excerpt; full executable deployment.yaml + runtime-patch.yaml are in the run directory.')
        print('Prime creates, captures and verifies a new checkpoint offstage. Keep that creating DGD alive.')
        print('Pinned experimental identity/offline bridge; node-local storage is workshop-specific plumbing.')

    def callback(self):
        return self.ensure_storage if self.data['storage'] == 'nvme' else None

    def ensure_storage(self, run, snapshot, content):
        """Run every storage guard, retaining verbose output outside projection."""
        path = self.path / 'storage-validation.log'
        if not run.state.get(storage.KEY, {}).get('staged'):
            print('Preparing the node-local checkpoint; detailed checks: storage-validation.log', flush=True)
        try:
            with path.open('a') as output, contextlib.redirect_stdout(output):
                print('\nStorage validation at ' + ui.now(), flush=True)
                return storage.ensure(run, snapshot, content)
        except Exception:
            print('Storage validation failed; details: storage-validation.log', file=sys.stderr, flush=True)
            raise

    def prepare(self):
        self.check_inputs()
        if self.args.rehearsal:
            print('[REHEARSAL] CPU model-cache, admission, runtime overlay and prepared storage checks simulated.')
        else:
            ui.acquire(self.path, OWNER)
            lifecycle.require_lease(self.run)
            if self.data['prepared']:
                lifecycle.check_patch(self.run, self.spec)
                return
            lifecycle.prepare(self.run, self.spec, ui.ROOT / self.profile['baseline'])
            self.run.apply([yaml.safe_load((self.path / 'runtime-patch.yaml').read_text())])
            lifecycle.dry_run(self.run, self.spec)
            if self.data['storage'] == 'nvme':
                storage.inspect(self.run)
        self.data['prepared'] = True
        self.save()

    def prime(self):
        self.prepare()
        if self.run.state.get('replacement_intent') or self.data.get('replacement_identity'):
            raise ValueError('This run has already begun replacement; resume the walkthrough instead of priming again.')
        if not self.data.get('initial_identity'):
            if not self.args.rehearsal and not self.run.state.get('snapshot_dgd_submitted_at'):
                print('Offstage: create the DGD, capture, publish, stage and restore its initial worker.', flush=True)
                lifecycle.deploy(self.run, self.spec)
            identity = self.wait_restored()
            # An offstage smoke proves initial registration/output. Onstage requests
            # remain separately gated, after replacement timing is displayed.
            if self.args.rehearsal:
                response = {'simulated': True, 'worker': {'decode_worker_id': 'simulated-initial-worker'}}
            else:
                with lifecycle.frontend(self.run, 'snapshot') as base:
                    response = lifecycle.coding_request(base, self.data['model'])
                ui.write_json(self.path / 'initial-request.json', response)
            identity['response_worker'] = response['worker']
            ui.write_json(self.path / 'initial-identity.json', identity)
            self.data['initial_identity'] = identity
            self.save()
        self.check_identity()
        print('Primed. Creating DGD, frontend and artifact stay alive through onstage replacement.')

    def current_identity(self, baseline=None):
        lifecycle.require_lease(self.run)
        lifecycle.check_patch(self.run, self.spec)
        data = lifecycle.inventory(self.run)
        graph, snapshot, content = lifecycle.checkpoint_state(self.run, data, self.callback())
        serving = lifecycle.serving_pods(data)
        if not snapshot or not serving or not lifecycle.condition(graph, 'Ready'):
            return None, data
        if not all(lifecycle.condition(p, 'Ready') for p in serving[:2]):
            return None, data
        if baseline and serving[0]['metadata']['uid'] == baseline['worker_uid']:
            return None, data
        return lifecycle.validate_worker(self.run, self.spec, serving[0], snapshot, content,
            serving[1], serving[2], baseline), data

    def collect_visible_logs(self, data):
        workers = [p for p in data['pods']['items'] if p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component') == lifecycle.COMPONENT
                   and not p['metadata'].get('deletionTimestamp')]
        if workers:
            result = self.run.k('logs', workers[0]['metadata']['name'], '-n', self.ns, '-c', 'main',
                                '--timestamps=true', '--tail=200', check=False)
            (self.path / 'restored-worker.log').write_text(result.stdout)
        pod = agent(self.run)
        result = self.run.k('logs', pod['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent',
                            '--timestamps=true', '--tail=3000', check=False)
        (self.path / 'restore-agent-full.log').write_text(result.stdout)
        (self.path / 'restore-agent.log').write_text('\n'.join(line for line in result.stdout.splitlines() if self.ns in line) + '\n')

    def wait_restored(self, baseline=None):
        if self.args.rehearsal:
            phase = 'replacement' if baseline else 'initial'
            identity = {'simulated': True, 'dgd_uid': 'simulated-dgd', 'frontend_uid': 'simulated-frontend',
                'service_uid': 'simulated-service', 'service_name': 'ft-snapshot-frontend',
                'worker_name': 'simulated-' + phase, 'worker_uid': 'simulated-' + phase + '-uid',
                'checkpoint_name': 'simulated-checkpoint', 'checkpoint_uid': 'simulated-checkpoint-uid',
                'content_uid': 'simulated-content-uid', 'node': self.profile['node'], 'gpu_uuids': self.profile['gpu_uuids']}
            (self.path / 'restore-agent.log').write_text('REHEARSAL: process restore -> CUDA restore -> complete\n')
            (self.path / 'restored-worker.log').write_text('REHEARSAL: restored engine -> new worker registration -> Ready\n')
            self.data['ready_observed_at'] = ui.now()
            self.save()
            return identity
        deadline = time.monotonic() + self.args.timeout
        last = None
        while time.monotonic() < deadline:
            identity, data = self.current_identity(baseline)
            self.collect_visible_logs(data)
            status = [(p['metadata']['name'], p.get('status', {}).get('phase', 'Pending'), bool(lifecycle.condition(p, 'Ready')))
                      for p in data['pods']['items']]
            if status != last:
                print(ui.compact_resource_table(data['dgd']['items'] + data['pods']['items']), flush=True)
                last = status
            if baseline:
                elapsed = lifecycle.elapsed(self.run.state['replacement_intent']['requested_at'], ui.now())
                self.data['startup'] = {'ready': bool(identity), 'total_seconds': elapsed, 'phases': [
                    {'name': 'Replacement / ready', 'seconds': elapsed, 'status': 'done' if identity else 'running'}]}
                self.save()
            if identity:
                # Qualification timing stays ahead of any presenter inference.
                timing = restore_timing((self.path / 'restore-agent-full.log').read_text(), self.ns,
                                        identity['worker_name'], identity['content_uid'])
                identity['restore_timing'] = timing
                self.data['ready_observed_at'] = ui.now()
                self.save()
                lifecycle.collect_logs(self.run, data, phase='replacement' if baseline else 'initial')
                return identity
            time.sleep(3)
        raise TimeoutError('Restored Dynamo service did not become Ready; preserve the run for inspection.')

    def check_identity(self):
        if self.args.rehearsal:
            return
        saved = self.data.get('replacement_identity') or self.data.get('initial_identity')
        if not saved:
            raise ValueError('Prime this presenter before the walkthrough.')
        identity, _ = self.current_identity()
        if identity is None or any(identity[key] != saved[key] for key in
                ('dgd_uid', 'worker_uid', 'frontend_uid', 'service_uid', 'checkpoint_uid', 'content_uid', 'node', 'gpu_uuids')):
            raise ValueError('Primed service identity changed; do not use earlier evidence.')

    def show_artifact(self):
        self.check_identity()
        self.command(['cat', self.path / 'deployment-excerpt.yaml'])
        print('Full executable manifest: deployment.yaml. Runtime bridge: runtime-patch.yaml.')
        if self.args.rehearsal:
            print('Storage: ' + self.data['storage'] + ' checkpoint (simulated).')
        elif self.data['storage'] == 'nvme':
            record = self.run.state[storage.KEY]
            print(f"Storage: node-local NVMe; {record['expected_bytes'] / 1e9:.1f} GB / "
                  f"{record['expected_files']:,} files verified.")
        else:
            print('Storage: shared EFS checkpoint.')
        print('Capture and staging happened offstage; the checkpoint belongs to this living DGD.')
        print('Same-node fresh-request recovery. KV was released before capture; active streams are separate.')

    def submit_replacement(self):
        """Record one fault, UID-conditional delete, resume uncertain intent safely."""
        lifecycle.require_lease(self.run)
        baseline = self.data['initial_identity']
        pending = self.run.state.get('replacement_intent')
        if not pending:
            self.check_identity()
            self.run.state['replacement_intent'] = {'requested_at': ui.now(), 'pod_name': baseline['worker_name'],
                'pod_uid': baseline['worker_uid'], 'delete_submitted': False}
            self.run.save()
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': baseline['worker_uid']}}
            self.run.k('delete', '--raw', '/api/v1/namespaces/' + self.ns + '/pods/' + baseline['worker_name'],
                       '-f', '-', input_text=json.dumps(options), timeout=90)
            self.run.state['replacement_intent']['delete_submitted'] = True
            self.run.save()
        elif not pending['delete_submitted']:
            found = self.run.k('get', 'pod', pending['pod_name'], '-n', self.ns, '-o', 'json', check=False)
            if found.returncode == 0 and json.loads(found.stdout)['metadata']['uid'] == pending['pod_uid']:
                raise RuntimeError('Delete outcome is uncertain and original Pod remains; inspect before resuming.')
            if found.returncode != 0 and 'NotFound' not in found.stderr:
                raise RuntimeError('Cannot verify uncertain deletion; preserve the lease.')

    def replace(self):
        if self.data.get('replacement_identity'):
            self.check_identity()
            self.summary()
            return
        name = self.data['initial_identity']['worker_name']
        self.show_command(self.run.kbase + ['delete', 'pod', name, '-n', self.ns])
        if self.args.rehearsal:
            self.data['replacement_requested_at'] = ui.now()
        else:
            self.submit_replacement()
        identity = self.wait_restored(self.data['initial_identity'])
        self.data['replacement_identity'] = identity
        ui.write_json(self.path / 'replacement-identity.json', identity)
        self.save()
        self.summary()

    def summary(self):
        identity = self.data['replacement_identity']
        record = {'simulated': self.args.rehearsal, 'storage': self.data['storage'],
            'pod_to_ready_seconds': None, 'deletion_to_observed_ready_seconds': None,
            'agent_seconds': None, 'phases': {}, 'inference_sent': False,
            'notes': ['Capture, publication, staging and hashes happened offstage.',
                'Agent restore, Pod-to-Ready and deletion-to-observed-Ready are different boundaries; do not add them.',
                'No matched cold-start baseline. The next request has not been sent yet.']}
        if not self.args.rehearsal:
            record.update(identity['restore_timing'])
            record['pod_to_ready_seconds'] = lifecycle.elapsed(identity['pod_created_at'], identity['ready_at'])
            record['deletion_to_observed_ready_seconds'] = lifecycle.elapsed(
                self.run.state['replacement_intent']['requested_at'], self.data['ready_observed_at'])
        ui.write_json(self.path / 'timing.json', record)
        print('\nRestore timing' + (' · REHEARSAL / not measured' if self.args.rehearsal else ''))
        for label, field in [('Pod to Ready', 'pod_to_ready_seconds'), ('Agent restore', 'agent_seconds'),
                             ('Deletion to observed Ready', 'deletion_to_observed_ready_seconds')]:
            value = record[field]
            print(label + ': ' + (f'{value:.2f}s' if value is not None else 'not measured'))
        for name, seconds in record['phases'].items():
            print(f'  {name:24s} {seconds:8.3f}s')
        for note in record['notes']:
            print(note)

    def show_proof(self):
        self.check_identity()
        initial, replacement = self.data['initial_identity'], self.data['replacement_identity']
        fields = ('dgd_uid', 'frontend_uid', 'service_uid', 'checkpoint_uid', 'content_uid', 'node', 'gpu_uuids')
        if initial['worker_uid'] == replacement['worker_uid'] or any(initial[key] != replacement[key] for key in fields):
            raise ValueError('Need a distinct worker and unchanged service/artifact identities.')
        proof = {'simulated': self.args.rehearsal, 'before_uid': initial['worker_uid'], 'after_uid': replacement['worker_uid'],
            **{key: replacement[key] for key in fields}, 'scope': 'Same-node initialized-engine replacement; no KV/stream preservation.'}
        ui.write_json(self.path / 'recovery-proof.json', proof)
        summary = self.path / 'recovery-summary.txt'
        summary.write_text(('REHEARSAL / SIMULATED IDENTITIES\n' if self.args.rehearsal else '') +
            'RESOURCE                    RECOVERY\n'
            'Worker Pod                  replaced\n'
            'DGD / frontend / Service    unchanged\n'
            'Checkpoint                  unchanged\n'
            'Node / GPU pair             unchanged\n'
            '\nFull identity proof: recovery-proof.json\n')
        self.command(['cat', summary])

    def endpoint(self):
        name = self.data['replacement_identity']['service_name']
        command = self.run.kbase + ['port-forward', '-n', self.ns, 'service/' + name,
                                    f'{self.args.port}:8000', '--address=127.0.0.1']
        self.show_command(command)
        if self.args.rehearsal:
            return
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', self.args.port))
        with (self.path / 'port-forward.log').open('a') as output:
            self.forward = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        for _ in range(40):
            if self.forward.poll() is not None:
                raise RuntimeError('Port-forward stopped; inspect port-forward.log.')
            try:
                with socket.create_connection(('127.0.0.1', self.args.port), timeout=1):
                    return
            except OSError:
                time.sleep(0.5)
        raise TimeoutError('Port-forward did not open.')

    def request(self):
        self.check_identity()
        self.endpoint()
        command = ['curl', '--fail', '--silent', '--show-error', '--no-buffer', '--max-time', '180',
            '-H', 'Content-Type: application/json', '--data-binary', '@' + str(self.path / 'request.json'),
            f'http://127.0.0.1:{self.args.port}/v1/chat/completions']
        self.show_command(command)
        started = ui.now()
        if self.args.rehearsal:
            response = {'simulated': True, 'content': 'def add(a, b):\n    return a + b',
                        'worker': {'decode_worker_id': 'simulated-replacement-worker'}}
        else:
            raw = self.run.command(command, timeout=200).stdout
            (self.path / 'response.sse').write_text(raw)
            response = parse_coding_stream(raw, self.data['model'])
            if response['worker']['decode_worker_id'] == self.data['initial_identity']['response_worker']['decode_worker_id']:
                raise ValueError('Fresh inference retained the initial decode-worker identity.')
            self.check_identity()
        response.update(started_at=started, completed_at=ui.now())
        ui.write_json(self.path / 'response.json', response)
        print(response['content'])
        print('\nDynamo decode worker: ' + str(response['worker']['decode_worker_id']))
        print('Fresh coding inference through the unchanged frontend. No in-flight request was restored.')

    def require_primed(self):
        self.check_inputs()
        if not self.data.get('prepared') or not self.data.get('initial_identity'):
            if not self.args.rehearsal:
                raise ValueError('Run prime offstage first; capture/staging must not consume onstage time.')
            previous_auto = self.args.auto
            try:
                self.args.auto = True
                with contextlib.redirect_stdout(io.StringIO()):
                    self.prime()
            finally:
                self.args.auto = previous_auto

    def guided(self):
        self.require_primed()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal; use --rehearsal --plain --auto offline.')
        print('\nDynamo workshop · Operator-managed Snapshot recovery\n' +
              ('REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER') +
              '\nRun: ' + ui.repo_path(self.path) + '\nNamespace: ' + self.ns)
        if self.run.state.get('replacement_intent') and not self.data.get('replacement_identity'):
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
        lifecycle.require_lease(self.run)
        if self.run.state.get('snapshot_dgd_submitted_at'):
            lifecycle.cleanup(self.run, self.spec)
        else:
            # Preparation can fail before deployment; verify no GPU workloads
            # exist before releasing a reservation or a private storage helper.
            pods = self.run.get('get', 'pods', '-n', self.ns)['items']
            claims = self.run.get('get', 'resourceclaims', '-n', self.ns)['items']
            graphs = self.run.get('get', 'dgd', '-n', self.ns)['items']
            if pods or claims or graphs:
                raise ValueError('Unexpected resources before deployment; cleanup/lease retained.')
        if self.data['storage'] == 'nvme' and self.run.state.get(storage.KEY):
            storage.cleanup(self.run)
        self.data['cleaned_at'] = ui.now()
        self.save()
        support.release(self.path, OWNER)
        print('Owned workloads/claims removed; private EFS view restored; snapshots and artifact copies retained.')


if __name__ == '__main__':
    support.launch(SnapshotDgdDemo, STEPS, 18004, snapshot=True)
