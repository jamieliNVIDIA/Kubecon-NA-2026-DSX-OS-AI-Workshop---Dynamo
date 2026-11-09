"""Run a reviewed text-only pilot after an audited, terminal prior failure.

Runs in a detached CPU controller on the stable host. No predecessor signals,
cleanup or lease changes; no GPU preparation before live cleanup gates pass.
"""
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

ROOT = Path(__file__).resolve().parents[3]
PREDECESSOR = ROOT / 'results/workshop-rr-20261103-resume02/continuation-stable-a2'
RR = PREDECESSOR.parent
LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
PYTHON = ROOT / '.local/venv/bin/python'
KUBECTL = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'), '--request-timeout=30s']


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic(path, value):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    assert sha(args.plan) == args.plan_sha256, 'Approved follow-up plan bytes changed'
    plan = json.loads(args.plan.read_text())
    assert plan['run_directory'] == 'results/workshop-mx-startup-20261103-textonly02'
    path = ROOT / plan['controller_directory']
    path.mkdir(exist_ok=False)
    atomic(path / 'consumed-plan.json', {'plan': plan, 'plan_sha256': sha(args.plan), 'at': now()})
    child = None
    started = now()

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Follow-up controller received signal ' + str(signum))

    signal.signal(signal.SIGTERM, interrupted)

    def state(stage, **detail):
        atomic(path / 'STATUS.json', {'at': now(), 'stage': stage, **detail})

    def unchanged():
        for relative, digest in plan['source_sha256'].items():
            assert sha(ROOT / relative) == digest, 'Frozen follow-up input changed: ' + relative

    def command(tag, argv, timeout):
        nonlocal child
        unchanged()
        directory = path / tag
        directory.mkdir(exist_ok=False)
        began = now()
        atomic(directory / 'command.json', {'argv': [str(arg) for arg in argv], 'started_at': began, 'timeout_seconds': timeout})
        with (directory / 'console.log').open('w') as out:
            child = subprocess.Popen([str(arg) for arg in argv], cwd=ROOT, stdin=subprocess.DEVNULL,
                                     stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + timeout
            while child.poll() is None:
                state(tag, child_pid=child.pid, started_at=began)
                if time.monotonic() > deadline:
                    os.killpg(child.pid, signal.SIGINT)
                    try:
                        child.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                    atomic(directory / 'exit.json', {'exit_code': 124, 'started_at': began, 'finished_at': now()})
                    raise TimeoutError(tag)
                time.sleep(10)
            code = child.returncode
            child = None
        atomic(directory / 'exit.json', {'exit_code': code, 'started_at': began, 'finished_at': now()})
        if code:
            raise RuntimeError(tag + ' failed: exit ' + str(code))

    def get(*parts):
        result = subprocess.run(KUBECTL + list(parts) + ['-o', 'json'], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError('Read-only cleanup check failed: ' + result.stderr[-1500:])
        return json.loads(result.stdout)

    def verify_prior_cleanup():
        handoff = json.loads((ROOT / plan['predecessor_handoff_path']).read_text())
        exit_path = ROOT / handoff['predecessor_exit_path']
        assert sha(exit_path) == handoff['predecessor_exit_sha256']
        exit_value = json.loads(exit_path.read_text())
        assert exit_value['exit_code'] == handoff['accepted_terminal_exit_code'] == 1
        assert not (RR / '.remaining-controller.lock').exists()
        assert not LEASE.exists(), 'Predecessor still owns GPU lease'
        prior = []
        for ns in handoff['namespaces']:
            namespace = get('get', 'namespace', ns)
            assert namespace['metadata']['labels']['app.kubernetes.io/managed-by'] == 'kubecon-dynamo-feature-tests'
            pods = get('get', 'pods', '-n', ns)['items']
            claims = get('get', 'resourceclaims', '-n', ns)['items']
            graphs = get('get', 'dgd', '-n', ns)['items']
            gpu = [pod['metadata']['name'] for pod in pods if any(
                c.get('resources', {}).get('claims') or any(
                    key.startswith('nvidia.com/') and 'gpu' in key
                    for key in c.get('resources', {}).get('limits', {}))
                for c in pod['spec'].get('containers', []))]
            assert not gpu and not claims and not graphs, 'Predecessor namespace cleanup no longer holds: ' + ns
            prior.append({'namespace': ns, 'gpu_pods': gpu, 'claims': [], 'graphs': []})
        all_pods = get('get', 'pods', '-A')['items']
        unexpected = [pod['metadata']['namespace'] + '/' + pod['metadata']['name']
                      for pod in all_pods
                      if pod['spec'].get('nodeName') in ('kubecon-nke-site-cp-0124', 'kubecon-nke-site-cp-0198')
                      and any(c.get('resources', {}).get('claims') or any(
                          key.startswith('nvidia.com/') and 'gpu' in key
                          for key in c.get('resources', {}).get('limits', {}))
                          for c in pod['spec'].get('containers', []))]
        assert not unexpected, 'Other GPU workloads on benchmark nodes: ' + repr(unexpected)
        atomic(path / 'predecessor-cleanup-verified.json', {'at': now(), 'exit': exit_value, 'namespaces': prior, 'unexpected_gpu_pods': unexpected})

    try:
        unchanged()
        assert (PREDECESSOR / 'plan.json').is_file()
        verify_prior_cleanup()
        unchanged()
        for stage in plan['stages']:
            command(stage['name'], [PYTHON, '-B'] + stage['argv'], stage['timeout_seconds'])
        assert not LEASE.exists(), 'Text-only helper did not release GPU ownership'
        state('text-only pilot completed; evidence sealed by helper')
        atomic(path / 'exit.json', {'exit_code': 0, 'started_at': started, 'finished_at': now()})
    except BaseException as error:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        state('stopped; inspect failure before continuing', error=repr(error), traceback=traceback.format_exc())
        atomic(path / 'exit.json', {'exit_code': 1, 'started_at': started, 'finished_at': now(), 'error': repr(error), 'gpu_lease_present': LEASE.exists()})
        raise


if __name__ == '__main__':
    main()
