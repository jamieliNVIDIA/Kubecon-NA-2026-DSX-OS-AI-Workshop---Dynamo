"""Preserve writer failure logs before cleanup; observer never mutates Run state."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time


def unlimited_stream_base(kbase):
    """Remove inherited finite request deadlines from a streaming client."""
    result, index = [], 0
    while index < len(kbase):
        arg = str(kbase[index])
        if arg == '--request-timeout':
            if index + 1 >= len(kbase):
                raise ValueError('Inherited request-timeout flag is missing its value.')
            index += 2
            continue
        if arg.startswith('--request-timeout='):
            index += 1
            continue
        result.append(arg)
        index += 1
    return result + ['--request-timeout=0']


def collect_previous(run):
    """Canonical collector replacement: retain previous generation before stop."""
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    (run.path / 'current-pods.json').write_text(json.dumps({'items': pods}, indent=2) + '\n')
    history = run.path / 'writer-log-history'
    history.mkdir(exist_ok=True)
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Foreign writer Pod.')
        statuses = {c['name']: c for c in pod['status'].get('containerStatuses', []) +
                    pod['status'].get('initContainerStatuses', [])}
        for container in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
            name = container['name']
            status = statuses.get(name, {})
            prefix = pod['metadata']['uid'] + '-' + name + '-r' + str(status.get('restartCount', 0))
            current = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', name,
                '--timestamps=true', check=False, timeout=35)
            latest = run.path / (pod['metadata']['name'] + '-' + name + '.log')
            text = current.stdout + current.stderr
            if latest.exists() and latest.stat().st_size > len(text.encode()):
                prior = latest.read_bytes()
                retained = history / (prefix + '-prior-observation-' + hashlib.sha256(prior).hexdigest()[:12] + '.log')
                if not retained.exists(): retained.write_bytes(prior)
            latest.write_text(text)
            if status.get('restartCount', 0):
                previous = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', name,
                    '--previous', '--timestamps=true', check=False, timeout=35)
                retained = history / (prefix + '-previous-' + str(time.time_ns()) + '.log')
                retained.write_text(previous.stdout + previous.stderr)
                (retained.with_suffix('.json')).write_text(json.dumps({
                    'pod': pod['metadata']['name'], 'pod_uid': pod['metadata']['uid'],
                    'container': name, 'status': status, 'exit_code': previous.returncode,
                    'scope': 'Previous generation read before verifier-owned stop; cause may remain unknown'}, indent=2) + '\n')
    return pods


class LogFollowers:
    """Independent kubectl logs streams; no concurrent Run journal/state writes."""
    def __init__(self, run):
        self.namespace, self.kbase = run.ns, unlimited_stream_base(run.kbase)
        self.path = run.path / ('writer-log-follow-' + str(time.time_ns()))
        self.stop_event, self.lock = threading.Event(), threading.Lock()
        self.children, self.seen = [], set()
        self.thread = threading.Thread(target=self.watch, daemon=True)

    def start(self):
        self.path.mkdir()
        self.thread.start()

    def watch(self):
        while not self.stop_event.is_set():
            try:
                command = self.kbase + ['get', 'pods', '-n', self.namespace, '-o', 'json', '--request-timeout=8s']
                result = subprocess.run(command, capture_output=True, text=True, timeout=12)
                if result.returncode:
                    raise RuntimeError(result.stderr[-2000:])
                for pod in json.loads(result.stdout)['items']:
                    if pod['metadata'].get('labels', {}).get('feature-test-run') != self.namespace: continue
                    statuses = pod['status'].get('containerStatuses', []) + pod['status'].get('initContainerStatuses', [])
                    for status in statuses:
                        cid = status.get('containerID')
                        if not cid: continue
                        key = (pod['metadata']['uid'], status['name'], cid)
                        if key in self.seen: continue
                        self.seen.add(key)
                        label = key[0] + '-' + key[1] + '-' + hashlib.sha256(cid.encode()).hexdigest()[:10]
                        command = self.kbase + ['logs', pod['metadata']['name'], '-n', self.namespace,
                            '-c', status['name'], '--follow', '--timestamps=true', '--pod-running-timeout=10s']
                        output = (self.path / (label + '.log')).open('ab', buffering=0)
                        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
                        (self.path / (label + '.json')).write_text(json.dumps({
                            'pod': pod['metadata']['name'], 'pod_uid': key[0], 'container': key[1],
                            'container_id': cid, 'restart_count': status.get('restartCount', 0),
                            'command': command, 'scope': 'Independent continuous read-only log stream'}, indent=2) + '\n')
                        with self.lock: self.children.append((process, output))
            except Exception as error:
                with (self.path / 'observer-errors.jsonl').open('a') as output:
                    output.write(json.dumps({'at_ns': time.time_ns(), 'error': str(error)}) + '\n')
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=14)
        with self.lock: children = list(self.children)
        for process, output in children:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            output.close()


@contextmanager
def preserve_writer_logs(run, writer):
    original = writer.collect
    follower = LogFollowers(run)
    follower.start()
    writer.collect = collect_previous
    try:
        yield follower.path
    finally:
        writer.collect = original
        follower.stop()


WRAPPER_PROGRAM = r'''import ast,hashlib,importlib.metadata as metadata,json
from pathlib import Path
import torch,vllm
assert not torch.cuda.is_initialized()
root=Path(metadata.distribution('vllm').locate_file(''))
files={str(p.relative_to(root)):p.read_text() for p in sorted((root/'vllm/model_executor/layers/fused_moe').glob('*.py'))}
assert files and sum(len(v.encode()) for v in files.values())<6000000
properties=[]
for name,source in files.items():
    for cls in ast.parse(source).body:
        if not isinstance(cls,ast.ClassDef): continue
        for method in cls.body:
            if isinstance(method,ast.FunctionDef) and method.name=='quant_method':
                properties.append({'file':name,'class':cls.name,'line':method.lineno,
                    'decorators':[ast.unparse(x) for x in method.decorator_list],
                    'body':ast.unparse(method)})
print(json.dumps({'files':files,'vllm_file':vllm.__file__,'vllm_version':vllm.__version__,
    'cuda_initialized':torch.cuda.is_initialized(),'quant_method_properties':properties}))
'''


def inspect_wrappers(run):
    from snapshot_tp2_workflow import cpu_probe
    path = run.path / 'runtime-wrapper-sources'
    if path.exists(): raise ValueError('Preserve the existing CPU source inspection; use its recorded result.')
    result = cpu_probe(run, 'descriptor-wrapper-source-read', WRAPPER_PROGRAM)
    path.mkdir()
    hashes = {}
    for name, source in result.pop('files').items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.py':
            raise ValueError('Unexpected wrapper source path.')
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
    result['files'] = hashes
    (path / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    run.result('shadow-writer-wrapper-inspection', 'passed', **result,
        scope='Actual pinned-image CPU source reads; wrapper alias review remains separate from GPU qualification')
