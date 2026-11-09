#!/usr/bin/env python3
"""Fixed, bounded continuation of the already authorized workshop measurements.

Root reviews and launches this script. It accepts no shell text or arbitrary
command data, never changes scientific settings, and stops on unsafe ownership,
transport, identity, cleanup or unknown failures.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import execute_pair as e
import analyze as analysis
import campaign_prerequisites as prerequisites

RR_RUN = ROOT / 'results/workshop-rr-20261103-resume02'
MX_RUN = ROOT / 'results/workshop-mx-startup-20261103-artifact04'
MX = HERE.parent / 'mx-startup'
PYTHON = ROOT / '.local/venv/bin/python'
STAGES = ('c4', 'mx', 'routing-c1', 'routing-c4')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def validate_mx_frozen():
    spec = json.loads((MX_RUN / 'spec.json').read_text())
    expected = [
        (ROOT / 'configs/super-vl-tp2-lock.json', spec['model_lock_source_sha256']),
        (MX / 'artifact_comparison.py', spec['script_sha256']),
        (MX / 'measure_startup.py', spec['shared_helper_sha256']),
        (Path(spec['source_template']), spec['source_template_sha256']),
        (Path(spec['target_template']), spec['target_template_sha256']),
        (ROOT / 'results/workshop-mx-startup-20261030-pair04/spec.json', spec['reference_spec_sha256']),
        (Path(spec['serving_profile_reference']), spec['serving_profile_reference_sha256']),
    ]
    for path, sha256 in expected:
        assert ROOT in path.resolve().parents
        assert prerequisites.digest(path) == sha256, 'Frozen MX input changed: ' + str(path)
    assert json.loads((MX / 'artifact-coordinator-images.json').read_text()) == spec['coordinator_images']
    prepared = json.loads((MX_RUN / 'evidence-sha256.json').read_text())
    for name in ('source.json', 'target-native.json', 'target-p2p.json', 'target-artifacts.json', 'coordinator.json'):
        assert prerequisites.digest(MX_RUN / name) == prepared[name], name
    return spec


def fingerprints():
    spec = validate_mx_frozen()
    paths = list(HERE.glob('*.py')) + list(MX.glob('*.py')) + list((ROOT / 'scripts').glob('*.py')) + [
        ROOT / 'configs/super-vl-tp2-lock.json',
        ROOT / 'configs/dgd/super-vl-tp2/nemotron-agg-functionality.yaml',
        HERE / 'PLAN.md', HERE / 'KV_EXTENSION_PLAN.md',
        HERE / 'router-extension-candidates/two-worker-round-robin-template.yaml',
        HERE / 'router-extension-candidates/two-worker-kv-template.yaml',
        HERE.parent / 'agentx-workload/profile-c1.yaml',
        HERE.parent / 'agentx-workload/profile-c4.yaml',
        HERE.parent / 'agentx-workload/aiperf-dataset-revision.patch',
        RR_RUN / 'model-lock.json', RR_RUN / 'upstream-c1-prerequisite.json',
        MX_RUN / 'model-lock.json', MX_RUN / 'spec.json',
        Path(spec['source_template']), Path(spec['target_template']),
        ROOT / 'results/workshop-mx-startup-20261030-pair04/spec.json',
        Path(spec['serving_profile_reference']), MX / 'artifact-coordinator-images.json',
    ]
    paths += [MX_RUN / name for name in ('source.json', 'target-native.json', 'target-p2p.json',
                                       'target-artifacts.json', 'coordinator.json')]
    return {str(path.relative_to(ROOT)): prerequisites.digest(path) for path in paths}


class Driver:
    def __init__(self, label, start_at):
        self.run = e.Run(RR_RUN)
        self.path = RR_RUN / ('continuation-' + label)
        self.path.mkdir(exist_ok=False)
        self.lock = RR_RUN / '.remaining-controller.lock'
        self.token = uuid.uuid4().hex
        descriptor = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'token': self.token, 'started_at': now(),
                                     'controller': str(self.path)}) + '\n')
        self.frozen = fingerprints()
        self.child = None
        atomic(self.path / 'plan.json', {'started_at': now(), 'start_at': start_at,
            'rr_run': str(RR_RUN), 'mx_run': str(MX_RUN), 'stages': list(STAGES),
            'source_sha256': self.frozen,
            'scope': 'Execute fixed approved runs; no automatic tuning or parameter substitution'})

    def state(self, stage, **details):
        atomic(self.path / 'STATUS.json', {'at': now(), 'stage': stage, **details})

    def unchanged(self):
        for relative, expected in self.frozen.items():
            if prerequisites.digest(ROOT / relative) != expected:
                raise RuntimeError('Frozen controller input changed: ' + relative)

    def command(self, name, argv, timeout=21600, allow_failure=False):
        self.unchanged()
        path = self.path / name
        path.mkdir(exist_ok=False)
        started = now()
        atomic(path / 'command.json', {'argv': [str(arg) for arg in argv], 'cwd': str(ROOT),
                                      'started_at': started, 'timeout_seconds': timeout})
        code = None
        with (path / 'console.log').open('w') as stream:
            self.child = subprocess.Popen([str(arg) for arg in argv], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            atomic(path / 'process.json', {'pid': self.child.pid, 'started_at': started})
            end = time.monotonic() + timeout
            while self.child.poll() is None:
                self.state(name, pid=self.child.pid, started_at=started)
                if time.monotonic() >= end:
                    os.killpg(self.child.pid, signal.SIGINT)
                    try:
                        self.child.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.child.pid, signal.SIGKILL)
                        self.child.wait()
                    code = 124
                    break
                time.sleep(15)
            if code is None:
                code = self.child.returncode
            self.child = None
        atomic(path / 'exit.json', {'exit_code': code, 'started_at': started, 'finished_at': now()})
        if code and not allow_failure:
            raise RuntimeError(f'{name} exited {code}; inspect {path / "console.log"}')
        return code

    def owned_scope(self, namespace):
        state = json.loads((MX_RUN / 'state.json').read_text()) if namespace != self.run.ns else self.run.state
        assert state['owner'] == 'kubecon-dynamo-feature-tests' and state['namespace'] == namespace
        assert namespace.startswith('dynamo-ft-')
        obj = self.run.get('get', 'namespace', namespace)
        assert obj['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') == state['owner']

    def cleanup_proof(self, name, namespace, mx=False):
        self.owned_scope(namespace)
        path = self.path / name
        path.mkdir(exist_ok=False)
        deadline = time.monotonic() + 180
        attempt = 0
        while True:
            objects = {}
            for kind in ('pods', 'resourceclaims', 'dgd'):
                value = self.run.get('get', kind, '-n', namespace)
                atomic(path / (kind + f'-{attempt:03d}.json'), value)
                objects[kind] = value['items']
            gpu_pods = [pod['metadata']['name'] for pod in objects['pods']
                        if any(container.get('resources', {}).get('claims') or
                               any(key.startswith('nvidia.com/') and 'gpu' in key
                                   for key in container.get('resources', {}).get('limits', {}))
                               for container in pod['spec'].get('containers', []))]
            proof = {'at': now(), 'namespace': namespace, 'snapshot_index': attempt,
                     'gpu_pods': gpu_pods,
                     'resourceclaims': [item['metadata']['name'] for item in objects['resourceclaims']],
                     'graphs': [item['metadata']['name'] for item in objects['dgd']],
                     'gpu_lease_present': e.LEASE.exists()}
            if mx:
                proof['coordinator_pods'] = [pod['metadata']['name'] for pod in objects['pods']
                                            if pod['metadata']['name'] in ('mx-coordinator', 'mx-redis')]
            clean = not (gpu_pods or proof['resourceclaims'] or proof['graphs'] or
                         proof['gpu_lease_present'] or proof.get('coordinator_pods'))
            atomic(path / 'latest.json', proof)
            if clean or time.monotonic() >= deadline:
                proof['verified'] = clean
                atomic(path / 'cleanup-proof.json', proof)
                if not clean:
                    raise RuntimeError('Cleanup/lease handoff unverified after 180 s: ' + json.dumps(proof))
                return proof
            self.state(name, namespace=namespace, snapshot_index=attempt,
                       scope='Read-only wait for owned resource garbage collection; no deletes')
            attempt += 1
            time.sleep(5)

    def client_ready(self):
        state = json.loads((RR_RUN / 'state.json').read_text())
        check = state.get('checks', {}).get('rr-cpu-client-qualified', {})
        assert check.get('status') == 'passed', 'Current CPU qualification not complete'
        receipt = json.loads((Path(check['evidence']) / 'receipt-c4.json').read_text())
        assert receipt['status'] == 'cache_verified' and receipt['initial_cache_hit'] is True
        expected = json.loads((RR_RUN / 'upstream-c1-prerequisite.json').read_text())['expected_cache_files']
        assert receipt['cache_files'] == expected, 'Current corpus cache differs from accepted source'
        pod = self.run.get('get', 'pod', 'rr-loadgen', '-n', self.run.ns)
        assert pod['status']['phase'] == 'Running'
        assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status']['conditions'])
        assert all(c.get('restartCount', 0) == 0 for c in pod['status']['containerStatuses'])
        lock = json.loads((RR_RUN / 'model-lock.json').read_text())
        assert pod['spec']['containers'][0]['image'] == lock['runtime_image']
        assert pod['status']['containerStatuses'][0]['imageID'].split('@')[-1] == lock['runtime_image'].split('@')[-1]
        # Qualification predates this controller. Bind it to the actual Ready
        # Pod observed when this fresh client was created, never just a marker.
        prior_uids = set()
        for receipt_path in RR_RUN.glob('command-*.json'):
            command = json.loads(receipt_path.read_text())
            if command.get('args', [])[-7:] != ['get', 'pod', 'rr-loadgen', '-n', self.run.ns, '-o', 'json']:
                continue
            if command.get('exit_code') != 0 or command['started_at'] > check['updated_at']:
                continue
            observed = json.loads(command['stdout'])
            if any(c['type'] == 'Ready' and c['status'] == 'True' for c in observed.get('status', {}).get('conditions', [])):
                prior_uids.add(observed['metadata']['uid'])
        assert prior_uids == {pod['metadata']['uid']}, 'CPU Pod identity changed since qualification'
        identity = self.path / 'client-identity.json'
        if identity.exists():
            assert json.loads(identity.read_text())['metadata']['uid'] == pod['metadata']['uid']
        else:
            atomic(identity, pod)

    def analyze_rr(self, concurrency, routing=False):
        prefix = 'routing' if routing else 'scaleout'
        destination = RR_RUN / f'{prefix}-c{concurrency}-a1-analysis.json'
        if destination.exists():
            value = json.loads(destination.read_text())
            for arm in value['arms']:
                actual = analysis.load_arm(RR_RUN / arm['arm'])
                assert actual['spec_sha256'] == arm['spec_sha256']
            self.state(prefix + '-analysis-already-verified', path=str(destination))
        else:
            argv = [PYTHON, HERE / 'analyze.py', '--run', RR_RUN, '--concurrency', str(concurrency), '--attempt', 'a1']
            if routing:
                argv.append('--routing')
            self.command(prefix + f'-c{concurrency}-analysis', argv, timeout=300)
        # Final acceptance inventory is append-only; keep the earlier manifest.
        names = ([f'routing-c{concurrency}-{mode}-a1' for mode in ('round-robin', 'kv')]
                 if routing else [f'c{concurrency}-r{count}-a1' for count in (1, 2)])
        for name in names:
            path = RR_RUN / name
            target = path / 'integrity-final.json'
            values = {str(p.relative_to(path)): prerequisites.digest(p) for p in path.rglob('*')
                      if p.is_file() and p != target}
            if target.exists():
                assert json.loads(target.read_text())['sha256'] == values
            else:
                atomic(target, {'scope': 'All completed arm files, including positive acceptance summary', 'sha256': values})

    def validate_mx_results(self, feature_failure):
        state = json.loads((MX_RUN / 'state.json').read_text())
        lock = json.loads((MX_RUN / 'model-lock.json').read_text())
        assert lock['model'] == e.MODEL and lock['revision'] == e.REV
        assert lock['runtime_image'] == self.run.state['model_lock']['runtime_image']
        for name in ('central-source-bootstrap', 'central-native-storage', 'central-mx-weights', 'central-mx-artifacts'):
            folder = MX_RUN / name
            result = json.loads((folder / 'result.json').read_text())
            assert state['checks']['mx-startup-' + name]['status'] == 'passed'
            assert any(model['id'] == e.MODEL and model.get('context_window') == 1048576 for model in result['models']['data'])
            assert result['response']['model'] == e.MODEL
            assert 'READY' in result['response']['choices'][0]['message'].get('content', '')
            pods = json.loads((folder / 'pods.json').read_text())['items']
            pod = next(pod for pod in pods if pod['metadata']['name'] == result['target_pod'])
            container = pod['spec']['containers'][0]
            assert container['image'] == lock['runtime_image']
            argv = container['args']
            for flag, expected in (('--tensor-parallel-size', '2'), ('--revision', e.REV),
                                   ('--max-num-seqs', '4'), ('--max-num-batched-tokens', '8192'),
                                   ('--gpu-memory-utilization', '0.85')):
                assert argv[argv.index(flag) + 1] == expected, flag
            assert '--max-model-len' not in argv
            if name == 'central-native-storage':
                assert '--load-format' not in argv
            else:
                assert argv[argv.index('--load-format') + 1] == 'modelexpress'
            env = {item['name']: item.get('value') for item in container.get('env', [])}
            expected_transfer = '1' if name in ('central-source-bootstrap', 'central-mx-artifacts') else '0'
            assert env.get('MX_ARTIFACT_TRANSFER') == expected_transfer
            assert 'MODEL_EXPRESS_URL' not in env
            assert env.get('MX_ARTIFACT_COMPILE_CONFIG_DIGEST') == json.loads((MX_RUN / 'spec.json').read_text())['compile_config_digest']
            assert all(c.get('restartCount', 0) == 0 for c in pod['status']['containerStatuses'])
            assert pod['status']['containerStatuses'][0]['imageID'].split('@')[-1] == lock['runtime_image'].split('@')[-1]
            allocation = json.loads((folder / 'gpu-allocation.json').read_text())
            assert len(allocation['status']['allocation']['devices']['results']) == 2
            visible = (folder / 'gpu-visible.csv').read_text()
            assert visible.count('H100') == 2
            if name in ('central-mx-weights', 'central-mx-artifacts'):
                assert len(result.get('per_rank_transfers', [])) == 2
                logs = '\n'.join(p.read_text() for p in folder.glob(result['target_pod'] + '-*.log'))
                assert 'Trying strategy: default' not in logs
        if feature_failure:
            error = state.get('checks', {}).get('mx-artifact-batch', {}).get('error', '')
            assert (MX_RUN / 'artifact-cache-check-failure.json').exists()
            assert error.startswith('Artifact transfer/reuse not established:'), error
            return {'status': 'feature-effectiveness-failed', 'error': error,
                    'scope': 'All identity/correctness/P2P gates passed; no compiler-cache speedup established'}
        assert state['checks']['mx-artifact-startup-comparison']['status'] == 'passed'
        json.loads((MX_RUN / 'comparison.json').read_text())
        proof = json.loads((MX_RUN / 'artifact-reuse-evidence.json').read_text())
        assert proof['actual_engine_cache_hit_ranks'] == ['0', '1']
        assert proof['artifact_install_lines'] and len(proof['selected_installed_cache_lines']) >= 2
        assert not proof['unused_cache_warning_lines']
        artifact_result = json.loads((MX_RUN / 'central-mx-artifacts/result.json').read_text())
        artifact_logs = '\n'.join(path.read_text() for path in (MX_RUN / 'central-mx-artifacts').glob(artifact_result['target_pod'] + '-*.log'))
        assert 'Compiling model again due to a load failure' not in artifact_logs
        return {'status': 'passed', 'scope': 'Identity, correctness, P2P and both engine cache-hit ranks verified'}

    def mx(self):
        validate_mx_frozen()
        assert not list(MX_RUN.glob('central-*/result.json')), 'MX GPU attempt already exists; do not reuse it'
        batch_code = self.command('mx-artifact04-batch', [PYTHON, '-B', MX / 'artifact_comparison.py',
                                  'batch', '--run', MX_RUN], timeout=14400, allow_failure=True)
        classification = None
        validation_error = None
        try:
            classification = self.validate_mx_results(feature_failure=batch_code != 0)
        except Exception as error:
            validation_error = repr(error)
        # Even a feature-only failure must be cleaned and proved before RR.
        self.command('mx-artifact04-cleanup', [PYTHON, '-B', MX / 'artifact_comparison.py',
                     'cleanup', '--run', MX_RUN], timeout=600)
        namespace = json.loads((MX_RUN / 'state.json').read_text())['namespace']
        proof = self.cleanup_proof('mx-artifact04-cleanup-proof', namespace, mx=True)
        atomic(self.path / 'mx-outcome.json', {'at': now(), 'batch_exit_code': batch_code,
              'classification': classification, 'validation_error': validation_error, 'cleanup': proof})
        if validation_error:
            raise RuntimeError('MX identity/transport/unknown failure; stop independent work: ' + validation_error)
        self.command('mx-artifact04-analysis', [PYTHON, '-B', MX / 'analyze_startup.py', MX_RUN], timeout=300)
        if batch_code:
            e.status(self.run, 'MX feature effectiveness failed; clean handoff verified; independent routing comparisons continue',
                     mx_outcome=str(self.path / 'mx-outcome.json'))

    def execute(self, start_at):
        self.client_ready()
        self.cleanup_proof('initial-rr-cleanup-proof', self.run.ns)
        state = json.loads((MX_RUN / 'state.json').read_text())
        assert state['checks']['mx-artifact-coordinator']['status'] == 'passed'
        if start_at != 'c4':
            current = json.loads((RR_RUN / 'state.json').read_text())
            assert current['checks']['rr-pair-c4']['status'] == 'completed'
            self.analyze_rr(4)
        for name in STAGES[STAGES.index(start_at):]:
            self.client_ready()
            if e.LEASE.exists():
                raise RuntimeError('GPU lease held before new stage; no automatic removal')
            if name == 'c4':
                self.command('scaleout-c4', [PYTHON, HERE / 'execute_pair.py', '--run', RR_RUN,
                             '--concurrency', '4', '--attempt', 'a1'])
                self.cleanup_proof('scaleout-c4-cleanup-proof', self.run.ns)
                self.analyze_rr(4)
            elif name == 'mx':
                self.mx()
            else:
                concurrency = 1 if name == 'routing-c1' else 4
                self.command(name, [PYTHON, HERE / 'execute_router_pair.py', '--run', RR_RUN,
                             '--concurrency', str(concurrency), '--attempt', 'a1'])
                self.cleanup_proof(name + '-cleanup-proof', self.run.ns)
                self.analyze_rr(concurrency, routing=True)
        self.cleanup_proof('final-rr-cleanup-proof', self.run.ns)
        self.command('owned-client-cleanup', self.run.kbase + ['delete', 'pod', 'rr-loadgen', '-n', self.run.ns,
                     '--ignore-not-found', '--wait=true', '--timeout=60s'], timeout=120)
        pods = self.run.get('get', 'pods', '-n', self.run.ns)['items']
        assert not any(p['metadata']['name'] == 'rr-loadgen' for p in pods)
        atomic(self.path / 'final-owned-client-proof.json', {'at': now(), 'namespace': self.run.ns,
                                                          'client_absent': True, 'gpu_lease_present': e.LEASE.exists()})

    def close(self):
        if self.child is not None and self.child.poll() is None:
            os.killpg(self.child.pid, signal.SIGINT)
            try:
                self.child.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait()
        owner = json.loads(self.lock.read_text())
        if owner.get('token') != self.token:
            raise RuntimeError('Continuation lock ownership changed')
        self.lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--start-at', choices=STAGES, default='c4')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.label):
        raise ValueError('Invalid immutable continuation label')
    def terminate(signum, frame):
        raise KeyboardInterrupt('Continuation received signal ' + str(signum))
    signal.signal(signal.SIGTERM, terminate)
    driver = Driver(args.label, args.start_at)
    started = now()
    try:
        driver.execute(args.start_at)
        driver.state('all remaining approved stages completed; final integrity sealing pending')
        atomic(driver.path / 'exit.json', {'exit_code': 0, 'started_at': started, 'finished_at': now()})
        e.status(driver.run, 'remaining approved benchmark stages completed; final report review pending',
                 continuation=str(driver.path))
    except BaseException as error:
        driver.state('stopped; inspect exact failure before continuation', error=repr(error), traceback=traceback.format_exc())
        atomic(driver.path / 'exit.json', {'exit_code': 1, 'started_at': started, 'finished_at': now(),
                                        'error': repr(error), 'gpu_lease_present': e.LEASE.exists()})
        e.status(driver.run, 'continuation stopped; parameters preserved', error=repr(error), continuation=str(driver.path))
        raise
    finally:
        driver.close()


if __name__ == '__main__':
    main()
