#!/usr/bin/env python3
"""Complete only original C4 r2, retaining the recovered original r1 worker.

Fixed serving/workload sequence is identical to execute_pair.py's second arm.
Root reviews and launches on the stable controller. Never reruns the first arm.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import execute_pair as e
import analyze as analysis
import recover_c4_r1 as recovered
from gpu_claims import verify_allocation

RUN = recovered.RUN
FIRST = recovered.ARM
SECOND = 'c4-r2-a1'


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def state(path, stage, **details):
    target = path / 'STATUS.json'
    temporary = path / 'STATUS.json.tmp'
    temporary.write_text(json.dumps({'at': e.now(), 'stage': stage, **details}, indent=2) + '\n')
    temporary.replace(target)


def lease():
    value = json.loads((e.LEASE / 'owner.json').read_text())
    assert value['agent'] == e.OWNER and Path(value['run']).resolve() == RUN
    assert value['namespace'] == 'dynamo-ft-r610-1ec4908b-rr'
    return value


def cleanup_proof(run, dest):
    end = time.monotonic() + 180
    index = 0
    while True:
        objects = {}
        for kind in ('pods', 'resourceclaims', 'dgd'):
            value = run.get('get', kind, '-n', run.ns)
            save(dest / (kind + f'-cleanup-{index:03d}.json'), value)
            objects[kind] = value['items']
        gpu = [p['metadata']['name'] for p in objects['pods']
               if any(c.get('resources', {}).get('claims') or
                      any(k.startswith('nvidia.com/') and 'gpu' in k for k in c.get('resources', {}).get('limits', {}))
                      for c in p['spec'].get('containers', []))]
        proof = {'at': e.now(), 'gpu_pods': gpu,
                 'resourceclaims': [p['metadata']['name'] for p in objects['resourceclaims']],
                 'graphs': [p['metadata']['name'] for p in objects['dgd']],
                 'gpu_lease_present': e.LEASE.exists()}
        clean = not any(proof[k] for k in ('gpu_pods', 'resourceclaims', 'graphs', 'gpu_lease_present'))
        if clean or time.monotonic() >= end:
            proof['verified'] = clean
            save(dest / 'cleanup-proof.json', proof)
            assert clean, 'Cleanup/lease handoff unverified'
            return
        index += 1
        time.sleep(5)


def execute(label):
    dest = RUN / ('resume-c4-r2-' + label)
    dest.mkdir(exist_ok=False)
    lock = RUN / '.c4-r2-continuation.lock'
    acquired = False
    run = None
    may_cleanup = False
    started = e.now()
    try:
        assert not (RUN / '.remaining-controller.lock').exists()
        assert not (RUN / '.c4-r1-recovery.lock').exists()
        assert not (RUN / SECOND).exists(), 'Original second arm already attempted; never reuse it'
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'label': label, 'at': started}) + '\n')
        acquired = True
        save(dest / 'lease-before.json', lease())
        frozen = json.loads((RUN / 'continuation-a1/plan.json').read_text())['source_sha256']
        for relative, expected in frozen.items():
            assert analysis.sha(e.ROOT / relative) == expected, 'Original frozen input changed: ' + relative
        save(dest / 'helper-provenance.json', {'at': started, 'helper_sha256': analysis.sha(Path(__file__)),
             'recovery_helper_sha256': analysis.sha(Path(recovered.__file__)), 'original_frozen_inputs': frozen})
        assert analysis.sha(RUN / FIRST / 'spec.json') == recovered.SPEC_SHA
        first = analysis.load_arm(RUN / FIRST)
        assert first['spec']['worker_pods'][0]['uid'] == recovered.WORKER_UID
        assert first['spec']['concurrency_session_trees'] == 4
        accepted = json.loads((RUN / 'recovery-c4-r1-a1/accepted-original-arm.json').read_text())
        assert accepted['benchmark_id'] == first['benchmark_id'] and accepted['requests'] == first['requests']
        assert accepted['client_uid'] == recovered.CLIENT_UID and accepted['worker_uid'] == recovered.WORKER_UID
        run = e.Run(RUN)
        assert run.state['checks']['rr-c4-r1-recovered']['status'] == 'passed'
        namespace = run.get('get', 'namespace', run.ns)
        save(dest / 'namespace.json', namespace)
        assert namespace['metadata']['labels']['app.kubernetes.io/managed-by'] == run.state['owner']
        for kind in ('pods', 'resourceclaims', 'dgd'):
            save(dest / (kind + '-before.json'), run.get('get', kind, '-n', run.ns))
        client = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
        recovered.ready(client, recovered.CLIENT_UID, first['spec']['runtime_image'])
        pods = e.workers(run)
        assert len(pods) == 1 and pods[0]['metadata']['uid'] == recovered.WORKER_UID
        recovered.ready(pods[0], recovered.WORKER_UID, first['spec']['runtime_image'])
        verify_allocation(run, pods[0], pods[0]['spec']['containers'][0], 2)
        save(dest / 'retained-worker-before.json', pods[0])
        # The completed first benchmark must stay finished; do not signal or replay it.
        probe = e.client(run, "import json;from pathlib import Path;p=Path('/tmp/workshop-rr/runs/c4-r1-a1');print((p/'exit.json').read_text())")
        assert json.loads(probe.stdout)['exit_code'] == 0
        save(dest / 'intent.json', {'at': e.now(), 'first_arm': FIRST, 'first_spec_sha256': recovered.SPEC_SHA,
             'second_arm': SECOND, 'first_worker_uid': recovered.WORKER_UID, 'client_uid': recovered.CLIENT_UID,
             'scope': 'Continue only original second arm with retained first worker; original scientific settings'})
        (RUN / SECOND).mkdir(exist_ok=False)
        may_cleanup = True
        try:
            state(dest, 'deploying original second replica')
            e.status(run, 'resuming original C4 second arm; first worker retained', arm=SECOND, recovery=str(dest))
            graph, claims, manifest = e.render(run, 2)
            run.k('apply', '--dry-run=client', '-f', str(manifest))
            run.k('apply', '--dry-run=server', '-f', str(manifest))
            lease()
            run.apply(claims + [graph])
            pods = e.wait_serving(run, 2, SECOND)
            assert recovered.WORKER_UID in {p['metadata']['uid'] for p in pods}, 'Scale-out replaced original worker'
            for pod in pods:
                verify_allocation(run, pod, pod['spec']['containers'][0], 2)
            e.collect_workers(run, SECOND)
            for pod in pods:
                text = (RUN / SECOND / (pod['metadata']['name'] + '.log')).read_text()
                assert e.re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)', text)
            base = e.endpoint(run)
            ids = e.smoke(run, base, 2, SECOND)
            spec = e.seal_profile(run, base, pods, 4, 2, SECOND,
                                 initial_gpu_cache='retained first worker and fresh second worker before canonical AgentX primer')
            assert analysis.normalized_profile(RUN / FIRST) == analysis.normalized_profile(RUN / SECOND)
            run.result('rr-' + SECOND + '-qualified', 'passed', worker_ids=ids,
                       spec_sha256=analysis.sha(RUN / SECOND / 'spec.json'))
            e.collect_frontend_metrics(run, base, SECOND, 'before')
            e.telemetry_start(run, pods, SECOND)
            state(dest, 'original second-arm profile running', spec_sha256=analysis.sha(RUN / SECOND / 'spec.json'))
            try:
                e.launch_profile(run, SECOND)
                outcome = e.poll_profile(run, SECOND)
            finally:
                e.telemetry_stop(run, SECOND)
            e.collect_workers(run, SECOND)
            e.collect_frontend_metrics(run, base, SECOND, 'after')
            e.collect_profile(run, SECOND)
            run.result('rr-' + SECOND, 'completed' if outcome['exit_code'] == 0 else 'failed', **outcome,
                       note='Original second arm after read-only first-arm transport recovery')
            assert outcome['exit_code'] == 0, 'Original second arm failed; no automatic parameter changes'
            e.validate_profile(run, SECOND)
        finally:
            # Identical owned cleanup to the original paired controller. If the
            # API is unreachable, cleanup fails and the exact lease is retained.
            lease()
            e.cleanup_gpu(run)
        may_cleanup = False
        cleanup_proof(run, dest)
        run.result('rr-pair-c4', 'completed', recovery=str(dest),
                   note='Original r1 recovered unchanged; original r2 completed with retained first worker')
        argv = [str(e.ROOT / '.local/venv/bin/python'), '-B', str(HERE / 'analyze.py'), '--run', str(RUN),
                '--concurrency', '4', '--attempt', 'a1']
        save(dest / 'analysis-command.json', {'argv': argv, 'at': e.now()})
        result = run.command(argv, timeout=300)
        (dest / 'analysis.log').write_text(result.stdout + result.stderr)
        for name in (FIRST, SECOND):
            folder = RUN / name
            target = folder / 'integrity-final.json'
            save(target, {'scope': 'All completed arm files, including positive acceptance summary',
                          'sha256': {str(p.relative_to(folder)): analysis.sha(p) for p in folder.rglob('*')
                                     if p.is_file() and p != target}})
        state(dest, 'original C4 pair accepted, analyzed and cleaned')
        save(dest / 'exit.json', {'exit_code': 0, 'started_at': started, 'finished_at': e.now(),
                                 'gpu_lease_present': e.LEASE.exists()})
        e.status(run, 'original C4 pair accepted, analyzed and cleaned; MX handoff ready', recovery=str(dest))
    except BaseException as error:
        state(dest, 'stopped; preserve exact failure', error=repr(error))
        save(dest / 'exit.json', {'exit_code': 1, 'started_at': started, 'finished_at': e.now(), 'error': repr(error),
             'traceback': traceback.format_exc(), 'gpu_lease_present': e.LEASE.exists(), 'owned_cleanup_reached': may_cleanup})
        if run is not None:
            run.result('rr-c4-r2-recovery', 'blocked', error=repr(error), evidence=str(dest))
            e.status(run, 'C4 second-arm recovery stopped; parameters preserved', error=repr(error), recovery=str(dest))
        raise
    finally:
        save(dest / 'integrity.json', {str(p.relative_to(dest)): analysis.sha(p) for p in dest.rglob('*') if p.is_file()})
        if acquired:
            assert json.loads(lock.read_text())['pid'] == os.getpid()
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not e.re.fullmatch(r'[a-z0-9-]+', args.label):
        raise ValueError('Invalid immutable recovery label')
    def terminate(signum, frame):
        raise KeyboardInterrupt('Second-arm controller received signal ' + str(signum))
    signal.signal(signal.SIGTERM, terminate)
    execute(args.label)


if __name__ == '__main__':
    main()
