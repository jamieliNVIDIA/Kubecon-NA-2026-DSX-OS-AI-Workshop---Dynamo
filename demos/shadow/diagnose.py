#!/usr/bin/env python3
"""Preserve read-only Shadow diagnostics in a fresh directory, without Run writes."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def collect(run_path, output):
    run_path, output = Path(run_path).resolve(), Path(output).resolve()
    state = json.loads((run_path / 'state.json').read_text())
    demo = json.loads((run_path / 'demo.json').read_text())
    namespace = state['namespace']
    if (state.get('owner') != 'kubecon-dynamo-feature-tests' or
            not namespace.startswith('dynamo-ft-') or demo['namespace'] != namespace or
            demo.get('demo_kind') != 'shadow'):
        raise ValueError('Need an existing owned Shadow run; no namespace supplied separately.')
    device_class = json.loads((run_path / 'device-class.json').read_text())['metadata']['name']
    if device_class != namespace + '-shadow':
        raise ValueError('Unexpected scoped Shadow DeviceClass.')
    output.mkdir(parents=True, exist_ok=False)
    base = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'),
            '--request-timeout=25s']
    files = {}

    def record(name, args):
        if args[0] not in ('get', 'logs', 'describe'):
            raise ValueError('Diagnostics are read-only.')
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            result = subprocess.run(base + args, capture_output=True, text=True, timeout=60)
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            decode = lambda v: v.decode(errors='replace') if isinstance(v, bytes) else v or ''
            stdout, stderr, code = decode(error.stdout), decode(error.stderr), 124
        path = output / name
        path.write_text(stdout)
        (output / (name + '.stderr')).write_text(stderr)
        files[name] = {'args': args, 'started_at': started, 'exit_code': code,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        return code, stdout

    pods = []
    try:
        for resource in ('pods', 'events', 'dgd', 'podcliques', 'podcliquesets', 'podgangs',
                         'deployments', 'replicasets', 'resourceclaims', 'resourceclaimtemplates',
                         'dynamoworkermetadatas', 'configmaps'):
            code, text = record(resource + '.json', ['get', resource, '-n', namespace, '-o', 'json'])
            if resource == 'pods':
                if code:
                    raise RuntimeError('Pod inventory failed; preserve attempt before retrying.')
                pods = json.loads(text)['items']
                if any(p['metadata'].get('labels', {}).get('feature-test-run') != namespace for p in pods):
                    raise ValueError('An unowned Pod is present; do not inspect its containers.')
        record('deviceclass.json', ['get', 'deviceclass', device_class, '-o', 'json'])
        for pod in pods:
            name = pod['metadata']['name']
            record(name + '-describe.txt', ['describe', 'pod', name, '-n', namespace])
            containers = pod['spec'].get('containers', []) + pod['spec'].get('initContainers', [])
            for container in containers:
                for previous in (False, True):
                    record(name + '-' + container['name'] + ('-previous' if previous else '-current') + '.log',
                        ['logs', name, '-n', namespace, '-c', container['name'], '--timestamps=true',
                         '--tail=4000'] + (['--previous'] if previous else []))
    finally:
        (output / 'manifest.json').write_text(json.dumps({
            'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'read_only': True,
            'run': str(run_path), 'namespace': namespace,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'files': files}, indent=2) + '\n')
    summary = [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'],
                'containers': [{'name': c['name'], 'restarts': c['restartCount'], 'ready': c['ready']}
                               for c in p['status'].get('containerStatuses', [])]} for p in pods]
    print(json.dumps({'output': str(output), 'pods': summary}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    arguments = parser.parse_args()
    collect(arguments.run, arguments.output)
