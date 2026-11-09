#!/usr/bin/env python3
"""Build the fixed workshop continuation bundle; never include credentials."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import yaml

ROOT = Path(__file__).resolve().parents[3]
RR = ROOT / 'results/workshop-rr-20261103-resume02'
MX = ROOT / 'results/workshop-mx-startup-20261103-artifact04'
OUT = ROOT / 'results/workshop-stable-controller-20261103'
LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease/owner.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def credential_check(value, path):
    if isinstance(value, dict):
        if value.get('kind') == 'Secret':
            raise ValueError('Secret object in allowlist: ' + path)
        args = value.get('args', [])
        if isinstance(args, list) and 'get' in args and 'secret' in args:
            raise ValueError('Raw get-secret receipt in allowlist: ' + path)
        forbidden = {'.dockerconfigjson', 'client-key-data', 'client-certificate-data',
                     'password', 'access_token', 'refresh_token', 'aws_secret_access_key',
                     'aws_access_key_id', 'authorization', 'api_key'}
        for key, child in value.items():
            if key.lower() in forbidden and child not in (None, '', False):
                raise ValueError('Credential field in allowlist: ' + path + ':' + key)
            credential_check(child, path)
        if isinstance(value.get('stdout'), str):
            try:
                nested = json.loads(value['stdout'])
            except (ValueError, TypeError):
                pass
            else:
                credential_check(nested, path + ':stdout')
    elif isinstance(value, list):
        for child in value:
            credential_check(child, path)


def main():
    os.umask(0o077)
    OUT.mkdir(exist_ok=False)
    files = {}

    def add(path, archive=None):
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/nonregular allowlisted file: ' + str(path))
        name = archive or str(path.relative_to(ROOT))
        parts = Path(name).parts
        if Path(name).is_absolute() or '..' in parts or any(p in parts for p in ('.git', '.aws', '__pycache__')):
            raise ValueError('Unsafe archive path: ' + name)
        if parts[0] == '.local' and path != LEASE:
            raise ValueError('Only lease metadata may be copied from .local')
        if path.suffix in ('.json', '.yaml', '.yml'):
            value = json.loads(path.read_text()) if path.suffix == '.json' else yaml.safe_load(path.read_text())
            credential_check(value, name)
        files[name] = path

    frozen = json.loads((RR / 'continuation-a1/plan.json').read_text())['source_sha256']
    for name, expected in frozen.items():
        path = ROOT / name
        if digest(path) != expected:
            raise ValueError('Original frozen input changed: ' + name)
        add(path)
    for directory in (ROOT / 'scripts', ROOT / 'reports/workshop-measurements-20261030/round-robin',
                      ROOT / 'reports/workshop-measurements-20261030/mx-startup'):
        for path in directory.glob('*.py'):
            add(path)
    for name in ('state.json', 'model-lock.json', 'upstream-c1-prerequisite.json', 'rr-1-replica.yaml',
                 'client-precache.json', 'client-environment.json', 'runtime-inspection.json', 'pair-c4-a1-intent.json'):
        add(RR / name)
    state = json.loads((RR / 'state.json').read_text())
    add(Path(state['checks']['rr-cpu-client-qualified']['evidence']) / 'receipt-c4.json')
    for path in RR.glob('command-*.json'):
        value = json.loads(path.read_text())
        if value.get('args', [])[-7:] == ['get', 'pod', 'rr-loadgen', '-n', state['namespace'], '-o', 'json'] and value.get('exit_code') == 0:
            add(path)
    for path in RR.glob('check-rr-c4-r1*.json'):
        add(path)
    for directory in RR.iterdir():
        if directory.is_dir() and (directory.name == 'c4-r1-a1' or directory.name.startswith(('recovery-c4', 'c4-r1-recovery', 'continuation-a1'))):
            for path in directory.rglob('*'):
                if path.is_file():
                    add(path)
    reference = json.loads((RR / 'upstream-c1-prerequisite.json').read_text())
    source = Path(reference['source_run'])
    for name in ('state.json', 'model-lock.json', 'rr-1-replica.yaml'):
        add(source / name)
    add(Path(reference['source_cache_receipt']))
    for arm in reference['arms']:
        directory = source / arm['name']
        inventory = directory / 'integrity-final.json'
        add(inventory)
        for name, expected in json.loads(inventory.read_text())['sha256'].items():
            path = directory / name
            if digest(path) != expected:
                raise ValueError('Accepted C1 evidence changed: ' + str(path))
            add(path)
    for name in ('state.json', 'model-lock.json', 'spec.json', 'spec.sha256', 'source.json',
                 'target-native.json', 'target-p2p.json', 'target-artifacts.json', 'coordinator.json',
                 'evidence-sha256.json', 'cpu-preflight-proof.json', 'offline-retry-equivalence.json'):
        add(MX / name)
    add(LEASE)
    for path in Path(yaml.__file__).parent.glob('*.py'):
        add(path, '.controller-deps/yaml/' + path.name)
    launcher = ROOT / 'reports/workshop-measurements-20261030/mx-startup/launch_stable_controller.sh'
    add(launcher)
    manifest = {'logical_root': str(ROOT), 'yaml_version': yaml.__version__,
                'lease_metadata_sha256': digest(LEASE), 'files': {
                    name: {'sha256': digest(path), 'bytes': path.stat().st_size}
                    for name, path in sorted(files.items())},
                'scope': 'Consumed source/reference/evidence only; no credentials, model weights, dataset or client venv. Existing host kubeconfig is mounted read-only, never copied.'}
    data = (json.dumps(manifest, indent=2) + '\n').encode()
    (OUT / 'bundle-manifest.json').write_bytes(data)
    (OUT / 'controller-delegation.template.json').write_text(json.dumps({
        'remote_host': 'ip-172-31-10-102', 'logical_root': str(ROOT),
        'lease_metadata_sha256': manifest['lease_metadata_sha256'],
        'local_controllers_stopped': False, 'local_gpu_execution_frozen': False,
        'scope': 'Root must verify/set both gates before launch; keep local lease as delegation sentinel until remote final cleanup is verified.'
    }, indent=2) + '\n')
    with tarfile.open(OUT / 'controller-bundle.tar.gz', 'w:gz') as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
        info = tarfile.TarInfo('controller-bundle-manifest.json')
        info.size = len(data)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(data))
    print(json.dumps({'bundle': str(OUT / 'controller-bundle.tar.gz'), 'files': len(files),
                      'raw_bytes': sum(v['bytes'] for v in manifest['files'].values()),
                      'compressed_bytes': (OUT / 'controller-bundle.tar.gz').stat().st_size,
                      'sha256': digest(OUT / 'controller-bundle.tar.gz')}))


if __name__ == '__main__':
    main()
