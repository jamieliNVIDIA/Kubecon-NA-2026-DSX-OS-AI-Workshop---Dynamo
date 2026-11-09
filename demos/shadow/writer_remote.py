#!/usr/bin/env python3
"""Frozen writer-only transport using the existing owned CPU controller image."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

from scripts.source_paths import source_path, source_files
import demos.snapshot.remote as common

ROOT = Path(__file__).resolve().parents[2]
OWNER = 'workshop-shadow-writer-remote'
PROFILE = 'super-vl-writer-humming-runtime-descriptors-v4-routing-bias'
NODE = 'kubecon-nke-site-cp-0124'
UUIDS = ['GPU-b896cc31-be76-0f28-2e2d-d82564b624b7', 'GPU-a63322d6-c08e-79cb-c42a-031aeb4c1488']
CONTROLLER = 'demos/shadow/writer_remote_controller.py'
GUARD = Path('results/overnight-shadow-super-vl-20261104-a1/demo.json')
IMAGE_FROM = ROOT / 'results/demo-04-dgd-live-20261105-a3'
IMAGE_ID = 'sha256:f12b417250bc7d8e150e929114e60762e86f25146ea1f9289990a0fc7b5e9872'
INPUTS = {'runtime-overlay.json', 'source-contract-manifest.json', 'deployment.yaml', 'deployment.json',
    'workshop_descriptors.py', 'patches.py', 'model_loader.py', 'routing-bias-basis.json',
    'workshop_parameter_inventory.py', 'workshop_humming.py', 'device-class.json'}
GATES = ('model-staging', 'shadow-writer-preparation', 'shadow-writer-descriptor-cpu',
         'shadow-writer-wrapper-inspection', 'shadow-writer-cuda')
sha, now, write_new = common.sha, common.now, common.write_new


def relative(value, prefix=None):
    path = Path(common.safe_path(value))
    if prefix is not None:
        path.relative_to(prefix)
    return path


def run_path(value):
    path = Path(value).resolve()
    path.relative_to(ROOT / 'results')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', path.name):
        raise ValueError('Use the exact named fresh writer run under results/.')
    return path


def read(path):
    return json.loads(Path(path).read_text())


def regular(path):
    path = Path(path)
    path.relative_to(ROOT)
    current = ROOT
    for part in path.relative_to(ROOT).parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Writer payload symlink/ancestor forbidden.')
    if not path.is_file():
        raise ValueError('Required regular writer input missing: ' + str(path))
    return path


def frozen(run):
    state, spec = read(run / 'state.json'), read(run / 'descriptor-writer-spec.json')
    namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(run).encode()).hexdigest()[:8] + '-demo'
    if (state.get('owner') != 'kubecon-dynamo-feature-tests' or state.get('namespace') != namespace
            or spec.get('namespace') != namespace or spec.get('profile') != PROFILE
            or state.get('shadow_writer_profile') != PROFILE or spec.get('reader_enabled') is not False
            or spec.get('intentional_fault') is not False or spec.get('node') != NODE
            or sorted(spec.get('gpu_uuids', [])) != sorted(UUIDS)
            or state.get('shadow_descriptor_spec_sha256') != sha(run / 'descriptor-writer-spec.json')
            or state.get('writer_apply_started_at') or state.get('writer_dgd_uid')
            or any(state['checks'].get(key, {}).get('status') != 'passed' for key in GATES)):
        raise ValueError('Require the exact never-deployed v4 writer and all CPU/CUDA gates.')
    if set(spec['inputs']) != INPUTS:
        raise ValueError('Unexpected writer input whitelist.')
    cuda = state['checks']['shadow-writer-cuda']
    if (cuda.get('node') != NODE or cuda.get('arithmetic') != 'passed'
            or sorted(cuda.get('gpu_uuids', [])) != sorted(UUIDS)):
        raise ValueError('Exact assigned-pair CUDA arithmetic proof differs.')
    for name, expected in spec['inputs'].items():
        if sha(regular(run / relative(name))) != expected:
            raise ValueError('Frozen writer input changed: ' + name)
    for name, expected in spec['source_snapshot'].items():
        if Path(name).name != name or sha(regular(source_path(name, root=ROOT))) != expected:
            raise ValueError('Frozen writer source changed: ' + name)
        if sha(regular(run / 'source-snapshot' / name)) != expected:
            raise ValueError('Frozen source snapshot changed: ' + name)
    for name, expected in spec['runtime_contract_hashes'].items():
        if sha(regular(run / 'runtime-contract-sources' / relative(name))) != expected:
            raise ValueError('Frozen runtime source contract changed: ' + name)
    manifest = regular(Path(spec['config_manifest']))
    manifest.relative_to(ROOT / 'configs/dgd/workshop-shadow-descriptor-writer' / run.name)
    if (sha(manifest) != spec['config_manifest_sha256']
            or sha(regular(ROOT / 'configs/super-vl-tp2-lock.json')) != spec['model_lock_sha256']
            or not read(regular(ROOT / GUARD)).get('cleaned_at')):
        raise ValueError('Writer model/config/original-source cleanup guard changed.')
    return state, spec


def health_inputs(path, state):
    path = regular(Path(path).resolve())
    path.relative_to(ROOT / 'results')
    value = read(path)
    if (value.get('node') != NODE or value.get('changed_conditions')
            or set(value['outputs']) != {'kernel', 'kernel-xids', 'nvidia-smi'}
            or value['observed_at'] < state['checks']['shadow-writer-cuda']['updated_at']
            or any(v['exit_code'] for v in value['outputs'].values())):
        raise ValueError('Require complete fresh health after the exact-pair probe.')
    files = [path]
    for record in value['outputs'].values():
        name = record['file']
        if Path(name).name != name:
            raise ValueError('Health log must be a sibling regular file.')
        files.append(regular(path.parent / name))
    return files


def validate_plan(plan, root):
    if (plan.get('schema') != 1 or plan.get('kind') != 'shadow-writer-only'
            or plan.get('logical_root') != str(root) or plan.get('reader_enabled') is not False
            or plan.get('intentional_fault') is not False or plan.get('node') != NODE
            or sorted(plan.get('gpu_uuids', [])) != sorted(UUIDS)):
        raise ValueError('Writer plan scope/root/placement differs.')
    run = root / relative(plan['run'], 'results')
    state, _ = frozen(run)
    owner = plan['reservation']
    if (owner.get('agent') != OWNER or owner.get('run') != str(run)
            or owner.get('namespace') != state['namespace'] or owner.get('node') != NODE
            or sorted(owner.get('gpu_uuids', [])) != sorted(UUIDS)
            or plan['reservation_directory'] != state['namespace'] + '-writer-remote.gpu-lease'):
        raise ValueError('Writer reservation does not bind this exact candidate and pair.')
    for name, expected in plan['initial_run_sha256'].items():
        if sha(regular(run / relative(name))) != expected:
            raise ValueError('Initial writer state/input changed before launch: ' + name)
    for name, expected in plan['source_sha256'].items():
        if sha(regular(root / relative(name))) != expected:
            raise ValueError('Frozen bundle source changed: ' + name)
    health_inputs(root / relative(plan['health_before'], 'results'), state)
    regular(root / relative(plan['health_baseline'], 'results') / 'nodes.json')
    return run


def build(run, health_before, health_baseline, image_from=IMAGE_FROM):
    run = run_path(run)
    state, spec = frozen(run)
    prep = run / 'writer-remote-package'
    if prep.exists():
        raise ValueError('Writer package exists; never overwrite or repackage an attempted launch.')
    health = health_inputs(health_before, state)
    baseline = Path(health_baseline).resolve()
    regular(baseline / 'nodes.json').relative_to(ROOT / 'results')
    provenance = common.runtime_provenance(image_from)
    if provenance['image'] != IMAGE_ID:
        raise ValueError('Reuse only the exact existing owned curl-enabled image.')
    for name in common.IMAGE_INPUTS:
        source, target = regular(Path(image_from) / name), run / name
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                raise ValueError('Existing controller image provenance differs.')
        else:
            with target.open('xb') as output:
                output.write(source.read_bytes())
            target.chmod(0o400)
    runtime = common.runtime_provenance(run)
    files = [regular(path) for path in source_files(ROOT) if 'transcripts' not in path.relative_to(ROOT).parts]
    files += [regular(ROOT / 'configs/super-vl-tp2-lock.json'), regular(Path(spec['config_manifest'])),
              regular(ROOT / GUARD), regular(baseline / 'nodes.json')] + health
    run_names = {'state.json', 'descriptor-writer-spec.json', 'model-lock.json'} | INPUTS | set(common.IMAGE_INPUTS)
    files += [regular(run / name) for name in run_names]
    files += [regular(run / 'source-snapshot' / name) for name in spec['source_snapshot']]
    files += [regular(run / 'runtime-contract-sources' / relative(name)) for name in spec['runtime_contract_hashes']]
    payload = {str(path.relative_to(ROOT)): path for path in files}
    for name in payload:
        common.safe_path(name, payload=True)
    lease_name = state['namespace'] + '-writer-remote.gpu-lease'
    lease = ROOT / '.local' / lease_name
    lease.mkdir(exist_ok=False)
    reservation = {'agent': OWNER, 'run': str(run), 'namespace': state['namespace'],
                   'node': NODE, 'gpu_uuids': UUIDS, 'acquired_at': now()}
    write_new(lease / 'owner.json', reservation)
    prep.mkdir(exist_ok=False)
    tag = hashlib.sha256(str(run).encode()).hexdigest()[:8]
    name = 'kubecon-shadow-writer-' + tag
    plan = {'schema': 1, 'kind': 'shadow-writer-only', 'logical_root': str(ROOT),
        'run': str(run.relative_to(ROOT)), 'controller_name': name, 'namespace': state['namespace'],
        'node': NODE, 'gpu_uuids': UUIDS, 'reader_enabled': False, 'intentional_fault': False,
        'runtime': runtime, 'reservation': reservation, 'reservation_directory': lease_name,
        'health_before': str(health[0].relative_to(ROOT)), 'health_baseline': str(baseline.relative_to(ROOT)),
        'source_sha256': {key: sha(path) for key, path in payload.items() if not path.is_relative_to(run)},
        'initial_run_sha256': {str(path.relative_to(run)): sha(path) for path in files if path.is_relative_to(run)},
        'immutable_run_sha256': {str(path.relative_to(run)): sha(path) for path in files
                                 if path.is_relative_to(run) and path != run / 'state.json'}}
    write_new(prep / 'plan.json', plan)
    payload[str((prep / 'plan.json').relative_to(ROOT))] = prep / 'plan.json'
    records = {key: {'bytes': path.stat().st_size, 'sha256': sha(path), 'mode': 0o600} for key, path in payload.items()}
    manifest = {'schema': 1, 'name': name, 'logical_root': str(ROOT),
        'workspace': '/home/ubuntu/workshop-measurements/' + run.name + '-' + tag + '-controller/workspace',
        'image': IMAGE_ID, 'base_image': common.IMAGE, 'runtime': runtime, 'dependencies': common.DEPS,
        'controller': CONTROLLER, 'plan': str((prep / 'plan.json').relative_to(ROOT)),
        'plan_sha256': sha(prep / 'plan.json'), 'files': records}
    write_new(prep / 'payload-manifest.json', manifest)
    with tarfile.open(prep / 'payload.tar.gz', 'w:gz') as archive:
        for key, path in sorted(payload.items()):
            archive.add(path, arcname=key, recursive=False)
        raw = (prep / 'payload-manifest.json').read_bytes()
        member = tarfile.TarInfo('payload-manifest.json');member.size = len(raw);member.mode = 0o600
        archive.addfile(member, io.BytesIO(raw))
    digest = sha(prep / 'payload.tar.gz')
    common.verify_payload(prep / 'payload.tar.gz', digest)
    (prep / 'payload.sha256').write_text(digest + '\n')
    return {'controller_name': name, 'files': len(records), 'payload_sha256': digest,
            'plan_sha256': manifest['plan_sha256'], 'reservation': str(lease / 'owner.json')}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Snapshot bootstrap changed; review writer adaptation: ' + old)
    return text.replace(old, new)


def bootstrap():
    value = replace_once(common.BOOTSTRAP, "plan['reservation']['agent']!='workshop-snapshot-dgd'",
                         "plan['reservation']['agent']!='" + OWNER + "'")
    value = replace_once(value, "local/'workshop-measurements-20261030.gpu-lease'", "local/plan['reservation_directory']")
    value = replace_once(value, 'import demos.snapshot.dgd_demo as workshop_snapshot_dgd_demo,demos.snapshot.remote_controller as workshop_snapshot_remote_controller;',
        'import demos.shadow.descriptor_writer as workshop_shadow_descriptor_writer,demos.shadow.writer_remote_controller as workshop_shadow_writer_remote_controller,snapshot_gpu_health;')
    return replace_once(value, 'Snapshot controller imports passed', 'Writer-only controller imports passed')


def package(run):
    run = run_path(run);prep = run / 'writer-remote-package'
    manifest = read(prep / 'payload-manifest.json')
    digest = (prep / 'payload.sha256').read_text().strip()
    if (common.verify_payload(prep / 'payload.tar.gz', digest) != manifest
            or sha(prep / 'plan.json') != manifest['plan_sha256']):
        raise ValueError('Frozen writer package/plan changed.')
    return run, prep, manifest, digest


def launch(run):
    run, prep, manifest, digest = package(run)
    plan = read(prep / 'plan.json')
    validate_plan(plan, ROOT)
    if read(ROOT / '.local' / plan['reservation_directory'] / 'owner.json') != plan['reservation']:
        raise ValueError('Root reservation changed before launch.')
    if common.runtime_provenance(run) != manifest['runtime']:
        raise ValueError('Owned image provenance changed.')
    for name, record in manifest['files'].items():
        if sha(regular(ROOT / name)) != record['sha256']:
            raise ValueError('Package source changed before launch: ' + name)
    write_new(prep / 'launch-intent.json', {'at': now(), 'payload_sha256': digest, 'plan_sha256': manifest['plan_sha256']})
    program = bootstrap().replace('EXPECTED_SHA', repr(digest)).replace('EXPECTED_BASE_IMAGE', repr(common.IMAGE))
    program = program.replace('EXPECTED_IMAGE', repr(IMAGE_ID)).replace('EXPECTED_DEPS', repr(common.DEPS))
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(program)],
        input=(prep / 'payload.tar.gz').read_bytes(), capture_output=True, timeout=240)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr.decode(errors='replace'),
               'transport_source_sha256': sha(__file__), 'payload_sha256': digest}
    if result.returncode == 0:
        receipt['remote'] = json.loads(result.stdout)
    write_new(prep / 'launch-result.json', receipt)
    if result.returncode:
        raise RuntimeError('Writer launch failed/uncertain; never replay: ' + receipt['stderr'][-2000:])
    return receipt


STATUS = common.STATUS.replace("('remote-controller.json','remote-controller-plan.json','demo.json','state.json')",
    "('writer-remote-controller.json','writer-remote-exit.json','state.json')")
COLLECT = (common.COLLECT.split("roots={'run':", 1)[0] +
           "roots={'run':w/plan['run']}\nfiles={};paths={};total=0" +
           common.COLLECT.split('files={};paths={};total=0', 1)[1])


def status(run):
    _, prep, manifest, _ = package(run)
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(common.remote_program(manifest, STATUS))],
                            capture_output=True, text=True, timeout=90)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr}
    if not result.returncode:
        receipt['remote'] = json.loads(result.stdout)
    write_new(prep / ('status-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode:
        raise RuntimeError('Writer status unavailable; remote controller preserved: ' + result.stderr[-1000:])
    return receipt['remote']


def collect(run, output):
    run, prep, manifest, _ = package(run)
    output = Path(output).resolve();output.relative_to(ROOT / 'results')
    if output.exists() or output == run or output in run.parents or run in output.parents:
        raise ValueError('Use a fresh separate collection directory.')
    archive = output.with_name(output.name + '.tar.gz');errors = output.with_name(output.name + '.stderr.txt')
    with archive.open('xb') as stream, errors.open('x') as stderr:
        result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(common.remote_program(manifest, COLLECT))],
                                stdout=stream, stderr=stderr, timeout=600)
    write_new(output.with_name(output.name + '.transport.json'), {'at': now(), 'exit_code': result.returncode,
        'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size})
    if result.returncode:
        raise RuntimeError('Collection failed; preserve attempt, no silent retransmission.')
    archive.chmod(0o400)
    return common.extract_collection(archive, output, {'run': str(run.relative_to(ROOT)),
        'controller_name': manifest['name'], 'plan_sha256': manifest['plan_sha256']})


def preflight(run):
    _, prep, manifest, _ = package(run)
    program = common.PREFLIGHT.replace('EXPECTED_DEPS', repr(common.DEPS)).replace('EXPECTED_IMAGE', repr(IMAGE_ID))
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(program)], capture_output=True, text=True, timeout=90)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr, 'cluster_mutation': False}
    if not result.returncode:
        receipt['remote'] = json.loads(result.stdout)
    write_new(prep / ('preflight-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode:
        raise RuntimeError('Writer CPU/client preflight failed: ' + result.stderr[-1500:])
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'preflight', 'launch', 'status', 'collect'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--health-before', type=Path)
    parser.add_argument('--health-baseline', type=Path)
    parser.add_argument('--image-from', type=Path, default=IMAGE_FROM)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args();os.umask(0o077)
    if args.action == 'build':
        if not args.health_before or not args.health_baseline:
            parser.error('build requires fresh --health-before and --health-baseline containing nodes.json')
        value = build(args.run, args.health_before, args.health_baseline, args.image_from)
    elif args.action == 'collect':
        if args.output is None: parser.error('collect needs --output')
        result = collect(args.run, args.output)
        value = {k: result[k] for k in ('run', 'controller_name', 'plan_sha256', 'docker_state')}
    else:
        value = globals()[args.action](args.run)
    print(json.dumps(value, indent=2))
