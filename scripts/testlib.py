"""Bounded Kubernetes test operations and durable per-run evidence."""
import datetime as dt
import copy
import fcntl
import json
import os
import hashlib
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'kubecon-dynamo-feature-tests'


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()


class Run:
    def __init__(self, path=None):
        os.umask(0o077)
        self.path = Path(path).resolve() if path else ROOT / 'results' / f'{stamp()}-features'
        self.path.mkdir(parents=True, exist_ok=bool(path))
        state_file = self.path / 'state.json'
        if state_file.exists():
            self.state = json.loads(state_file.read_text())
        else:
            self.state = {'run_id': self.path.name, 'namespace': 'dynamo-ft-' + stamp(),
                          'owner': OWNER, 'checks': {}}
        if self.state['owner'] != OWNER or not self.state['namespace'].startswith('dynamo-ft-'):
            raise ValueError('Not an owned feature-test run')
        self.ns = self.state['namespace']
        self.kbase = [str(ROOT / '.local/bin/kubectl'),
                      f'--kubeconfig={ROOT / ".local/kubeconfig"}', '--request-timeout=30s']
        self.counter = len(list(self.path.glob('command-*.json')))
        self._saved = copy.deepcopy(self.state) if state_file.exists() else {}
        self.state.setdefault('attempts', []).append({
            'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'scripts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (ROOT / 'scripts').glob('*.py')}})
        self.save()

    def save(self):
        # Independent observers/tests may share a run; merge only this process's
        # changes so a readiness waiter cannot erase another feature's receipt.
        def merge(latest, previous, current):
            if isinstance(previous, dict) and isinstance(current, dict):
                result = copy.deepcopy(latest) if isinstance(latest, dict) else {}
                for key in previous.keys() - current.keys():
                    result.pop(key, None)
                for key, value in current.items():
                    if key not in previous:
                        result[key] = copy.deepcopy(value)
                    elif value != previous[key]:
                        result[key] = merge(result.get(key), previous[key], value)
                return result
            if isinstance(previous, list) and isinstance(current, list) and current[:len(previous)] == previous:
                return (latest or []) + [x for x in current[len(previous):] if x not in (latest or [])]
            return copy.deepcopy(current)
        target = self.path / 'state.json'
        with (self.path / '.state.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            latest = json.loads(target.read_text()) if target.exists() else {}
            self.state = merge(latest, self._saved, self.state)
            temporary = self.path / f'state.json.{os.getpid()}.tmp'
            temporary.write_text(json.dumps(self.state, indent=2) + '\n')
            temporary.replace(target)
            self._saved = copy.deepcopy(self.state)

    def command(self, args, input_text=None, timeout=90, check=True):
        self.counter += 1
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            result = subprocess.run(args, input=input_text, text=True,
                                    capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(args, 124,
                (exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else exc.stdout or '',
                (exc.stderr or b'').decode() if isinstance(exc.stderr, bytes) else exc.stderr or '')
        receipt = {'args': args, 'started_at': started, 'exit_code': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr}
        (self.path / f'command-{self.counter:04d}-{time.time_ns()}.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if check and result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}): {result.stderr[-3000:]}')
        return result

    def k(self, *args, **kwargs):
        return self.command(self.kbase + list(args), **kwargs)

    def get(self, *args):
        return json.loads(self.k(*args, '-o', 'json').stdout)

    def labels(self):
        return {'app.kubernetes.io/managed-by': OWNER, 'feature-test-run': self.ns}

    def write_manifest(self, path, objects):
        """Save the effective allocation manifests, including any DRA templates."""
        import yaml
        from gpu_claims import prepare
        converted, templates = prepare(objects, self.state.get('model_lock', {}))
        items = templates + converted
        for obj in items:
            obj.setdefault('metadata', {}).setdefault('labels', {}).update(self.labels())
            obj['metadata']['namespace'] = self.ns
        content = items[0] if len(items) == 1 else {'apiVersion': 'v1', 'kind': 'List', 'items': items}
        path.write_text(yaml.safe_dump(content, sort_keys=False))

    def ensure_namespace(self):
        result = self.k('get', 'namespace', self.ns, '-o', 'json', check=False)
        if result.returncode == 0:
            obj = json.loads(result.stdout)
            if obj['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER:
                raise ValueError('Refusing to reuse an unowned namespace')
        else:
            self.k('create', '-f', '-', input_text=json.dumps({'apiVersion': 'v1',
                   'kind': 'Namespace', 'metadata': {'name': self.ns, 'labels': self.labels()}}))

    def apply(self, objects, *, cluster_scope=False):
        lock = self.state.get('model_lock', {})
        if lock.get('gpu_allocation') == 'dra':
            from gpu_claims import prepare
            objects, templates = prepare(objects, lock)
            if templates:
                self.apply(templates)
        for obj in objects:
            metadata = obj.setdefault('metadata', {})
            metadata.setdefault('labels', {}).update(self.labels())
            if obj['kind'] != 'PersistentVolume':
                metadata['namespace'] = self.ns
            elif not cluster_scope or not metadata['name'].startswith(self.ns):
                raise ValueError('Only owned test PVs may be created at cluster scope')
            existing = self.k('get', obj['kind'], metadata['name'],
                              *([] if obj['kind'] == 'PersistentVolume' else ['-n', self.ns]),
                              '-o', 'json', check=False)
            if existing.returncode == 0:
                labels = json.loads(existing.stdout)['metadata'].get('labels', {})
                if labels.get('feature-test-run') != self.ns:
                    raise ValueError('Refusing to modify an unowned resource')
        manifest = {'apiVersion': 'v1', 'kind': 'List', 'items': objects}
        content = json.dumps(manifest, indent=2)
        digest_name = f'manifest-{self.counter + 1:04d}-{time.time_ns()}.json'
        (self.path / digest_name).write_text(content + '\n')
        self.k('apply', '--dry-run=server', '-f', '-', input_text=content)
        self.k('apply', '-f', '-', input_text=content)

    def wait_pod(self, name, timeout=600, completed=False):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            pod = self.get('get', 'pod', name, '-n', self.ns)
            status = pod.get('status', {})
            phase = status.get('phase', 'Unknown')
            waiting = [(c['name'], c.get('state', {}).get('waiting', {}).get('reason'))
                       for c in status.get('containerStatuses', [])]
            current = (phase, repr(waiting))
            if current != last:
                print(f'{name}: {phase} {waiting}', flush=True)
                last = current
            if phase == 'Failed':
                self.diagnostics(name)
                raise RuntimeError(f'{name} failed')
            if completed and phase == 'Succeeded':
                return pod
            if not completed and any(c.get('type') == 'Ready' and c.get('status') == 'True'
                                     for c in status.get('conditions', [])):
                return pod
            if any(reason in {'ErrImagePull', 'ImagePullBackOff', 'InvalidImageName', 'CreateContainerConfigError'}
                   for _, reason in waiting):
                self.diagnostics(name)
                raise RuntimeError(f'{name}: {waiting}')
            time.sleep(5)
        self.diagnostics(name)
        raise TimeoutError(f'{name} did not become ready in {timeout}s')

    def diagnostics(self, name):
        self.k('describe', 'pod', name, '-n', self.ns, check=False)
        self.k('logs', name, '-n', self.ns, '--all-containers', '--tail=300', check=False)

    def result(self, feature, status, **details):
        receipt = {'status': status, 'updated_at': dt.datetime.now(dt.timezone.utc).isoformat(), **details}
        (self.path / f'check-{feature}-{time.time_ns()}.json').write_text(json.dumps(receipt, indent=2) + '\n')
        self.state['checks'][feature] = receipt
        self.save()
        print(json.dumps({feature: self.state['checks'][feature]}, indent=2), flush=True)
