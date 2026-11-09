#!/usr/bin/env python3
"""Freeze, build and privately publish a common-runtime candidate on gemini."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from types import SimpleNamespace
import urllib.request
import urllib.parse
from testlib import ROOT, Run

HOST = 'gemini'
REPOSITORY = 'nvcr.io/nvidian/dynamo-dev/nealv'


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def prepare(run):
    context = run.path / 'build-context'
    if context.exists():
        raise ValueError('Build context already frozen; use a new run for changed inputs')
    inputs = context / 'inputs'
    inputs.mkdir(parents=True)
    kvcr = json.loads((ROOT / 'configs/kvcr-lock.json').read_text())
    rust = json.loads((ROOT / 'configs/kvcr-build-image.json').read_text())[0]['image']
    for source, target in (('container/common-runtime.Dockerfile', 'Dockerfile'),
                           ('scripts/install_efa_image.sh', 'install-efa.sh'),
                           ('scripts/common_runtime_probe.py', 'common-runtime-probe.py')):
        shutil.copyfile(ROOT / source, context / target)
    archive_bytes = fetch(f'https://github.com/ai-dynamo/kvcr/archive/{kvcr["kvcr_revision"]}.tar.gz')
    archive = run.path / 'kvcr-source.tar.gz'
    archive.write_bytes(archive_bytes)
    unpack = run.path / 'kvcr-unpacked'
    unpack.mkdir()
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if not (member.isfile() or member.isdir()) or not (unpack / member.name).resolve().is_relative_to(unpack.resolve()):
                raise ValueError('Unsafe archive member')
        source.extractall(unpack)
    source_root = next(unpack.iterdir())
    shutil.copytree(source_root, inputs / 'kvcr')
    for record in kvcr['sources']:
        if hashlib.sha256((source_root / record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Pinned KVCR source differs: ' + record['path'])
    adapter_paths = ['vllm/distributed/kv_events.py', 'vllm/distributed/kv_transfer/kv_connector/v1/offloading/events.py',
                     'vllm/v1/kv_offload/base.py', 'vllm/v1/kv_offload/tiering/factory.py',
                     'vllm/v1/kv_offload/tiering/kvcr/__init__.py', 'vllm/v1/kv_offload/tiering/kvcr/manager.py']
    for path in adapter_paths:
        data = fetch(f'https://raw.githubusercontent.com/vllm-project/vllm/{kvcr["vllm_adapter_revision"]}/{path}')
        destination = inputs / 'vllm-overlay' / path.removeprefix('vllm/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    mx = json.loads(fetch('https://pypi.org/pypi/modelexpress/0.6.0/json'))
    wheel = next(w for w in mx['urls'] if '-cp312-cp312-' in w['filename'] and 'x86_64' in w['filename'])
    data = fetch(wheel['url'])
    if hashlib.sha256(data).hexdigest() != wheel['digests']['sha256']:
        raise ValueError('ModelExpress wheel checksum mismatch')
    (inputs / wheel['filename']).write_bytes(data)
    manifest = {str(p.relative_to(context)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(context.rglob('*')) if p.is_file()}
    build = {'host': HOST, 'repository': REPOSITORY, 'context': str(context),
             'remote_directory': '/tmp/nealv-dynamo-common-' + run.state['run_id'],
             'build_args': {'VLLM_IMAGE': kvcr['vllm_image'], 'RUST_IMAGE': rust,
                            'DYNAMO_REF': kvcr['dynamo_revision']},
             'context_hashes': manifest, 'kvcr_source_sha256': hashlib.sha256(archive_bytes).hexdigest(),
             'modelexpress': {'filename': wheel['filename'], 'sha256': wheel['digests']['sha256']}}
    fingerprint = hashlib.sha256(json.dumps(build, sort_keys=True).encode()).hexdigest()[:12]
    build['image_tag'] = REPOSITORY + ':workshop-common-' + run.state['run_id'] + '-' + fingerprint
    (run.path / 'build-lock.json').write_text(json.dumps(build, indent=2) + '\n')
    run.state['common_build'] = build
    run.save()
    run.result('common-build-inputs', 'prepared', image_tag=build['image_tag'], context_files=len(manifest),
               scope='Pinned source/base/wheel inputs; no image built or published')


def checked(run):
    build = json.loads((run.path / 'build-lock.json').read_text())
    if build['host'] != HOST or build['repository'] != REPOSITORY:
        raise ValueError('Unexpected build target')
    for path, digest in build['context_hashes'].items():
        if hashlib.sha256((Path(build['context']) / path).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen context changed: ' + path)
    return build


def _nvcr_entry(entries):
    if not isinstance(entries, dict):
        raise RuntimeError('Docker credential configuration is malformed')
    return next((entries[key] for key in ('nvcr.io', 'https://nvcr.io', 'https://nvcr.io/v1/',
                                         'https://nvcr.io/v2/') if key in entries), None)


def _credential_helper(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise RuntimeError('Docker credential helper configuration is malformed')
    executable = 'docker-credential-' + name
    helper = shutil.which(executable)
    if helper is None and sys.platform == 'darwin':
        desktop = Path('/Applications/Docker.app/Contents/Resources/bin') / executable
        if desktop.is_file() and os.access(desktop, os.X_OK):
            helper = str(desktop)
    if helper is None:
        raise RuntimeError('Configured Docker credential helper is unavailable on this host. '
                           'For demo preparation, configure WORKSHOP_PULL_SECRET_SOURCE=namespace/name '
                           'or save that reference in .local/pull-secret-source.')
    try:
        result = subprocess.run([helper, 'get'], input='nvcr.io\n', text=True, capture_output=True, timeout=20)
        credential = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RuntimeError('NGC credential helper could not return the existing credential') from None
    if (not isinstance(credential, dict) or
            not all(isinstance(credential.get(key), str) and credential[key] for key in ('Username', 'Secret'))):
        raise RuntimeError('NGC credential helper could not return the existing credential')
    return credential


def ngc_credential():
    """Read existing NGC authentication using the current host's Docker config."""
    config_path = Path(os.environ.get('DOCKER_CONFIG') or Path.home() / '.docker') / 'config.json'
    try:
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except (OSError, ValueError):
        raise RuntimeError('Cannot read Docker credential configuration') from None
    if not isinstance(config, dict):
        raise RuntimeError('Docker credential configuration is malformed')
    helper = _nvcr_entry(config.get('credHelpers', {})) or config.get('credsStore')
    if helper:
        return _credential_helper(helper)
    entry = _nvcr_entry(config.get('auths', {}))
    if entry is not None:
        try:
            username, secret = base64.b64decode(entry['auth'], validate=True).decode().split(':', 1)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            raise RuntimeError('NGC credential in Docker configuration is malformed') from None
        if username and secret:
            return {'Username': username, 'Secret': secret}
    if sys.platform == 'darwin':
        return _credential_helper('desktop')
    raise RuntimeError('No NGC credential is configured on this host. For demo preparation, configure '
                       'WORKSHOP_PULL_SECRET_SOURCE=namespace/name or .local/pull-secret-source; '
                       'for image operations, use docker login nvcr.io.')


def registry_check(run):
    credential = ngc_credential()
    auth = base64.b64encode((credential['Username'] + ':' + credential['Secret']).encode()).decode()
    scope = 'repository:' + REPOSITORY.split('/', 1)[1] + ':pull,push'
    url = 'https://nvcr.io/proxy_auth?' + urllib.parse.urlencode({'scope': scope})
    request = urllib.request.Request(url, headers={'Authorization': 'Basic ' + auth})
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)['token']
    encoded = token.split('.')[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    access = [{key: a[key] for key in ('type', 'name', 'actions')} for a in claims.get('access', [])]
    push = any(a.get('name') == REPOSITORY.split('/', 1)[1] and 'push' in a.get('actions', []) for a in access)
    run.result('common-registry-access', 'passed' if push else 'blocked', repository=REPOSITORY,
               access=access, scope='Token permissions only; credential and token not saved or printed')
    if not push:
        raise RuntimeError('Existing NGC credential has no push permission for the target repository')


def build_image(run):
    build = checked(run)
    remote = build['remote_directory']
    run.command(['ssh', HOST, shlex.join(['mkdir', '-p', remote + '/context'])])
    run.command(['scp', '-r', build['context'] + '/.', HOST + ':' + remote + '/context/'], timeout=300)
    args = ['docker', 'build', '--network=host', '--progress=plain', '--platform=linux/amd64',
            '-t', build['image_tag']]
    for key, value in build['build_args'].items():
        args += ['--build-arg', key + '=' + value]
    args += [remote + '/context']
    print('Native AMD64 build started. Progress: ' + str(run.path / 'build.log'), flush=True)
    with (run.path / 'build.log').open('w') as logs:
        done = subprocess.run(['ssh', HOST, shlex.join(args)], stdout=logs, stderr=subprocess.STDOUT, timeout=10800)
    if done.returncode:
        run.result('common-image-build', 'failed', exit_code=done.returncode, evidence='build.log')
        raise RuntimeError('Common image build failed; inspect saved build.log')
    report = run.command(['ssh', HOST, shlex.join(['docker', 'image', 'inspect', '--format',
                       '{{json .}}', build['image_tag']])]).stdout
    (run.path / 'built-image.json').write_text(report)
    obj = json.loads(report)
    if obj['Architecture'] != 'amd64':
        raise ValueError('Unexpected image architecture')
    run.result('common-image-build', 'built', image_tag=build['image_tag'], image_id=obj['Id'],
               scope='Build-stage contract/entrypoint checks passed; GPU feature tests remain')


def diagnose(run):
    build = checked(run)
    code = '''set +e
id
df -h / /tmp
df -i / /tmp
ls -ld /tmp /var/lib/apt/lists
printf 'LD_PRELOAD=%s\\nLD_LIBRARY_PATH=%s\\n' "${LD_PRELOAD:-}" "${LD_LIBRARY_PATH:-}"
ldconfig -p | grep libatomic
apt-get update -o Debug::Acquire::gpgv=true
'''
    result = run.command(['ssh', HOST, shlex.join(['docker', 'run', '--rm', '--network=host', '--user=0',
                         '--entrypoint', 'bash', build['build_args']['VLLM_IMAGE'], '-lc', code])],
                         timeout=180, check=False)
    (run.path / 'base-package-diagnostics.log').write_text(result.stdout + result.stderr)
    print((result.stdout + result.stderr)[-12000:])


def base_dependencies(run):
    build = checked(run)
    program = '''import importlib.metadata as m,json
packages={}
for name in ('torch','vllm','nixl','modelexpress','instanttensor','runai-model-streamer',
             'grpcio','protobuf','numpy','pydantic','google-crc32c','msgspec','uvloop'):
 try: packages[name]=m.version(name)
 except m.PackageNotFoundError: packages[name]=None
print(json.dumps(packages))
'''
    done = run.command(['ssh', HOST, shlex.join(['docker', 'run', '--rm', '--runtime=runc',
          '--read-only', '--env', 'NVIDIA_VISIBLE_DEVICES=void', '--tmpfs', '/tmp:size=64m',
          '--entrypoint', 'python3', build['build_args']['VLLM_IMAGE'], '-c', program])])
    report = json.loads(done.stdout)
    (run.path / 'base-dependencies.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def builder_status(run):
    build = checked(run)
    name = 'nealv-common-build-' + run.state['run_id']
    for args in (['df', '-h', '/tmp'], ['docker', 'stats', '--no-stream', name],
                 ['docker', 'top', name, '-eo', 'pid,pcpu,pmem,etime,comm'],
                 ['docker', 'logs', '--tail', '15', name]):
        done = run.command(['ssh', HOST, shlex.join(args)], timeout=45, check=False)
        print(done.stdout + done.stderr, end='')


def publish(run):
    build = checked(run)
    if run.state['checks'].get('common-image-build', {}).get('status') != 'built':
        raise ValueError('Complete image build first')
    credential = ngc_credential()
    private = ROOT / '.local/common-registry-auth' / run.state['run_id']
    private.mkdir(parents=True, mode=0o700)
    config = private / 'config.json'
    config.write_text(json.dumps({'auths': {'nvcr.io': {'auth': base64.b64encode(
        (credential['Username'] + ':' + credential['Secret']).encode()).decode()}}}))
    config.chmod(0o600)
    remote = build['remote_directory'] + '/auth'
    try:
        run.command(['ssh', HOST, shlex.join(['mkdir', '-m', '700', '-p', remote])])
        run.command(['scp', str(config), HOST + ':' + remote + '/config.json'])
        run.command(['ssh', HOST, shlex.join(['chmod', '600', remote + '/config.json'])])
        with (run.path / 'publish.log').open('w') as logs:
            done = subprocess.run(['ssh', HOST, shlex.join(['docker', '--config', remote, 'push', build['image_tag']])],
                                  stdout=logs, stderr=subprocess.STDOUT, timeout=3600)
        if done.returncode:
            raise RuntimeError('Private NGC publish failed; inspect publish.log')
        result = run.command(['ssh', HOST, shlex.join(['skopeo', 'inspect', '--authfile', remote + '/config.json',
                                 'docker://' + build['image_tag']])], timeout=120).stdout
        record = json.loads(result)
        candidate = {'image': REPOSITORY + '@' + record['Digest'], 'tag': build['image_tag'],
                     'architecture': record['Architecture'], 'dynamo_source': build['build_args']['DYNAMO_REF'],
                     'status': 'candidate', 'qualification': 'GPU feature matrix pending'}
        (run.path / 'common-runtime-candidate.json').write_text(json.dumps(candidate, indent=2) + '\n')
        run.result('common-image-publish', 'published', candidate_status=candidate['status'],
                   **{key: value for key, value in candidate.items() if key != 'status'})
    finally:
        config.unlink(missing_ok=True)
        run.command(['ssh', HOST, shlex.join(['rm', '-f', remote + '/config.json'])], check=False)
        private.rmdir()


def isolated_build(run, cache_run=None):
    """Build and push with task-owned BuildKit storage on the larger /tmp disk."""
    build = checked(run)
    kit = json.loads((ROOT / 'configs/common-buildkit.json').read_text())
    remote = build['remote_directory']
    state_directory = remote + '/state'
    if cache_run is not None:
        prior = checked(SimpleNamespace(path=cache_run.resolve()))
        if prior['remote_directory'] != '/tmp/nealv-dynamo-common-' + cache_run.name:
            raise ValueError('Unexpected prior cache location')
        prior_name = 'nealv-common-build-' + cache_run.name
        active = run.command(['ssh', HOST, shlex.join(['docker', 'container', 'inspect', prior_name])], check=False)
        if active.returncode == 0:
            raise ValueError('Prior builder must be stopped before reusing its cache')
        if active.returncode != 1 or 'no such' not in active.stderr.lower():
            raise RuntimeError('Could not confirm the prior builder is absent')
        state_directory = prior['remote_directory'] + '/state'
        run.result('common-build-cache', 'reused', source_run=str(cache_run.resolve()),
                   state_directory=state_directory, scope='Task-owned stopped BuildKit cache only')
    name = 'nealv-common-build-' + run.state['run_id']
    if not all(c.isalnum() or c in '-_' for c in name):
        raise ValueError('Invalid builder name')
    # Launch only a fresh named builder; never remove or reuse another container.
    exists = run.command(['ssh', HOST, shlex.join(['docker', 'container', 'inspect', name])], check=False)
    if exists.returncode == 0:
        raise ValueError('Builder container already exists; inspect it before retrying')
    if exists.returncode != 1 or 'no such' not in exists.stderr.lower():
        raise RuntimeError('Could not confirm the new builder name is available')
    setup = f'''set -eu
mkdir -p {shlex.quote(remote)}/{{context,tools,state,auth}}
chmod 700 {shlex.quote(remote)}/auth
test "$(df --output=avail -B1 /tmp | tail -1)" -gt 161061273600
curl --fail --location --retry 3 {shlex.quote(kit['url'])} -o {shlex.quote(remote)}/buildkit.tar.gz
echo '{kit['sha256']}  {remote}/buildkit.tar.gz' | sha256sum -c -
tar -xzf {shlex.quote(remote)}/buildkit.tar.gz -C {shlex.quote(remote)}/tools
'''
    run.command(['ssh', HOST, 'bash -s'], input_text=setup, timeout=300)
    run.command(['scp', '-r', build['context'] + '/.', HOST + ':' + remote + '/context/'], timeout=300)
    credential = ngc_credential()
    private = ROOT / '.local/common-registry-auth' / run.state['run_id']
    private.mkdir(parents=True, mode=0o700)
    config = private / 'config.json'
    config.write_text(json.dumps({'auths': {'nvcr.io': {'auth': base64.b64encode(
        (credential['Username'] + ':' + credential['Secret']).encode()).decode()}}}))
    config.chmod(0o600)
    launched = False
    try:
        run.command(['scp', str(config), HOST + ':' + remote + '/auth/config.json'])
        run.command(['ssh', HOST, shlex.join(['chmod', '600', remote + '/auth/config.json'])])
        launch = ['docker', 'run', '-d', '--name', name, '--label', 'workshop-common-builder=' + run.state['run_id'],
                  '--privileged', '--runtime=runc', '--network=host', '--read-only',
                  '--memory=64g', '--cpus=12', '--env', 'NVIDIA_VISIBLE_DEVICES=void',
                  '--tmpfs', '/tmp:exec,size=4g', '--tmpfs', '/run:exec,size=256m',
                  '--mount', 'type=bind,src=' + remote + '/tools/bin,dst=/tools,readonly',
                  '--mount', 'type=bind,src=' + state_directory + ',dst=/var/lib/buildkit',
                  '--mount', 'type=bind,src=' + remote + '/context,dst=/context,readonly',
                  '--mount', 'type=bind,src=' + remote + '/auth,dst=/auth,readonly',
                  '--entrypoint', '/tools/buildkitd', build['build_args']['VLLM_IMAGE'],
                  '--root=/var/lib/buildkit', '--addr=unix:///run/buildkit/buildkitd.sock',
                  '--oci-worker=true', '--containerd-worker=false', '--oci-worker-binary=/tools/buildkit-runc',
                  '--oci-worker-net=host', '--allow-insecure-entitlement=network.host']
        run.command(['ssh', HOST, shlex.join(launch)])
        launched = True
        client = ['docker', 'exec', '--env', 'DOCKER_CONFIG=/auth', name,
                  '/tools/buildctl', '--addr=unix:///run/buildkit/buildkitd.sock']
        for attempt in range(15):
            ready = run.command(['ssh', HOST, shlex.join(client + ['debug', 'workers'])], check=False)
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Isolated BuildKit did not become ready')
        args = client + ['build', '--frontend=dockerfile.v0', '--local', 'context=/context',
                         '--local', 'dockerfile=/context', '--opt', 'platform=linux/amd64',
                         '--allow', 'network.host', '--opt', 'force-network-mode=host',
                         '--output', 'type=image,name=' + build['image_tag'] + ',push=true',
                         '--metadata-file=/var/lib/buildkit/result-' + run.state['run_id'] + '.json', '--progress=plain']
        for key, value in build['build_args'].items():
            args += ['--opt', 'build-arg:' + key + '=' + value]
        run.result('common-image-build', 'running', image_tag=build['image_tag'],
                   builder='isolated BuildKit on /tmp', buildkit=kit, evidence='build.log')
        print('Isolated AMD64 build/publish started. Progress: ' + str(run.path / 'build.log'), flush=True)
        with (run.path / 'build.log').open('w') as logs:
            done = subprocess.run(['ssh', HOST, shlex.join(args)], stdout=logs, stderr=subprocess.STDOUT,
                                  timeout=14400)
        if done.returncode:
            run.result('common-image-build', 'failed', exit_code=done.returncode, evidence='build.log',
                       builder='isolated BuildKit on /tmp', buildkit=kit)
            raise RuntimeError('Isolated image build failed; inspect saved build.log')
        metadata = run.command(['ssh', HOST, shlex.join(['docker', 'exec', name,
                               'cat', '/var/lib/buildkit/result-' + run.state['run_id'] + '.json'])]).stdout
        (run.path / 'buildkit-result.json').write_text(metadata)
        digest = json.loads(metadata)['containerimage.digest']
        if not digest.startswith('sha256:') or len(digest) != 71:
            raise ValueError('Invalid exported image digest')
        candidate = {'image': REPOSITORY + '@' + digest, 'tag': build['image_tag'],
                     'architecture': 'amd64', 'dynamo_source': build['build_args']['DYNAMO_REF'],
                     'status': 'candidate', 'qualification': 'GPU feature matrix pending'}
        (run.path / 'common-runtime-candidate.json').write_text(json.dumps(candidate, indent=2) + '\n')
        run.result('common-image-build', 'built', image_tag=build['image_tag'], digest=digest,
                   builder='isolated BuildKit on /tmp', buildkit=kit,
                   scope='Build contract checks passed; GPU feature tests remain')
        run.result('common-image-publish', 'published', candidate_status=candidate['status'],
                   **{key: value for key, value in candidate.items() if key != 'status'})
    except Exception as error:
        run.result('common-image-build', 'failed', error=str(error), evidence='build.log',
                   builder='isolated BuildKit on /tmp', buildkit=kit)
        raise
    finally:
        if launched:
            logs = run.command(['ssh', HOST, shlex.join(['docker', 'logs', '--tail', '200', name])], check=False)
            (run.path / 'buildkit-daemon.log').write_text(logs.stdout + logs.stderr)
            run.command(['ssh', HOST, shlex.join(['docker', 'rm', '-f', name])], check=False)
        config.unlink(missing_ok=True)
        run.command(['ssh', HOST, shlex.join(['rm', '-f', remote + '/auth/config.json'])], check=False)
        private.rmdir()


def confirm_publish(run):
    """Reconcile a completed registry export after a local receipt-write error."""
    build = checked(run)
    exported = json.loads((run.path / 'buildkit-result.json').read_text())
    candidate = json.loads((run.path / 'common-runtime-candidate.json').read_text())
    digest = exported['containerimage.digest']
    if candidate['image'] != REPOSITORY + '@' + digest or candidate['tag'] != build['image_tag']:
        raise ValueError('Published candidate/export identity mismatch')
    credential = ngc_credential()
    auth = base64.b64encode((credential['Username'] + ':' + credential['Secret']).encode()).decode()
    repository = REPOSITORY.split('/', 1)[1]
    request = urllib.request.Request('https://nvcr.io/proxy_auth?' + urllib.parse.urlencode(
        {'scope': 'repository:' + repository + ':pull'}), headers={'Authorization': 'Basic ' + auth})
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)['token']
    headers = {'Authorization': 'Bearer ' + token,
               'Accept': 'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'}
    request = urllib.request.Request('https://nvcr.io/v2/' + repository + '/manifests/' + digest, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Registry manifest digest mismatch')
    manifest = json.loads(data)
    request = urllib.request.Request('https://nvcr.io/v2/' + repository + '/blobs/' + manifest['config']['digest'],
                                    headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=30) as response:
        config = json.load(response)
    if config['architecture'] != 'amd64' or config['os'] != 'linux':
        raise ValueError('Registry image platform mismatch')
    run.result('common-image-build', 'built', image_tag=build['image_tag'], digest=digest,
               scope='Completed BuildKit export, CPU contract checks and registry digest verified')
    run.result('common-image-publish', 'published', candidate_status=candidate['status'],
               **{key: value for key, value in candidate.items() if key != 'status'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'build', 'isolated-build', 'registry-check', 'publish', 'confirm-publish', 'diagnose', 'base-dependencies', 'builder-status'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--cache-run', type=Path, help='Stopped task-owned BuildKit cache to reuse for isolated-build')
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'isolated-build':
        isolated_build(run, args.cache_run)
        return
    {'prepare': prepare, 'build': build_image, 'registry-check': registry_check, 'publish': publish,
     'confirm-publish': confirm_publish, 'diagnose': diagnose, 'base-dependencies': base_dependencies, 'builder-status': builder_status,
     'isolated-build': isolated_build}[args.action](run)


if __name__ == '__main__':
    main()
