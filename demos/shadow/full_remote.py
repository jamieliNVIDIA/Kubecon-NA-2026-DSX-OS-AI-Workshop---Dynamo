#!/usr/bin/env python3
"""Frozen full Shadow transport; supervisor/health artifacts stay outside Run."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile

from scripts.source_paths import source_path, source_files
import demos.snapshot.remote as common
import demos.shadow.writer_remote as writer_transport

ROOT = Path(__file__).resolve().parents[2]
PROFILE = 'super-vl-shadow-humming-runtime-descriptors-v4-routing-bias'
REVISION = 'workshop-humming-reader-v6-optional-input-state'
OWNER = 'workshop-demo-shadow'
NODE, UUIDS, IMAGE_ID = writer_transport.NODE, writer_transport.UUIDS, writer_transport.IMAGE_ID
CONTROLLER = 'demos/shadow/full_remote_controller.py'
HELM = {'schema': 1, 'host_path': '/usr/local/bin/helm', 'container_path': '/opt/homebrew/bin/helm',
        'sha256': '7a319dee5ea7a1f7d7a0d92d5c223586f3b65abc33163c9de2a85f083aa3df2b',
        'version': 'v3.22.0+g144ca65'}
INPUTS = (writer_transport.INPUTS - {'routing-bias-basis.json'}) | {'shadow-settings.yaml',
    'reader-delta.json', 'reader-cpu-result.json', 'reader-cpu-packet.json', 'reader-cpu-program.py',
    'reader-cpu-intent.json', 'reader-cpu-check.json'}
CACHE_INPUTS = {'dev-cache-qualification.json', 'dev-cache-bootstrap.json', 'dev-cache-receipt.json'}
CACHE_SOURCES = {'workshop_mx_dev_cache.py', 'mx_dev_cache_stage.py'}
sha, now, write_new = common.sha, common.now, common.write_new
relative, regular, read = writer_transport.relative, writer_transport.regular, writer_transport.read


def validate_helm_binding(binding):
    if type(binding) is not dict or json.dumps(binding, sort_keys=True) != json.dumps(HELM, sort_keys=True):
        raise ValueError('Full Helm dependency path/hash/version differs from the reviewed binding.')
    return binding


def verify_host_helm(binding):
    validate_helm_binding(binding)
    path = Path(binding['host_path'])
    if (path.is_symlink() or not path.is_file() or str(path.resolve()) != binding['host_path'] or
            not os.access(path, os.R_OK | os.X_OK) or
            hashlib.sha256(path.read_bytes()).hexdigest() != binding['sha256']):
        raise ValueError('Pinned host Helm is unavailable, nonexecutable or changed; no controller launch.')


def helm_probe_program(binding, kubeconfig):
    validate_helm_binding(binding)
    if not Path(kubeconfig).is_absolute():
        raise ValueError('Helm probe requires the exact absolute controller kubeconfig destination.')
    return '''import hashlib,json,os,subprocess
from pathlib import Path
binding=BINDING
path=Path(binding['container_path'])
if not path.is_file() or not os.access(path,os.R_OK|os.X_OK) or hashlib.sha256(path.read_bytes()).hexdigest()!=binding['sha256']:
 raise ValueError('Mounted Helm bytes/permissions differ')
version=subprocess.run([str(path),'version','--short'],capture_output=True,text=True,timeout=10)
if version.returncode or version.stdout.strip()!=binding['version']:
 raise RuntimeError('Mounted Helm version failed/differed: '+version.stderr[-1000:])
command=[str(path),'--kubeconfig',KUBECONFIG,'get','values','nvidia-dra-driver-gpu','-n','nvidia-dra-driver','-a','-o','json']
result=subprocess.run(command,capture_output=True,text=True,timeout=35)
if result.returncode:raise RuntimeError('Read-only DRA Helm values failed: '+result.stderr[-1000:])
values=json.loads(result.stdout)
if type(values) is not dict or values.get('resources',{}).get('gpus',{}).get('enabled') is not True or values.get('gpuResourcesEnabledOverride') is not True:
 raise ValueError('DRA GPU Helm values are disabled or malformed')
print(json.dumps({'status':'passed','helm':binding,'helm_version':version.stdout.strip(),'command':command,
 'driver_values':values,'driver_values_sha256':hashlib.sha256(result.stdout.encode()).hexdigest()}))
'''.replace('BINDING', repr(binding)).replace('KUBECONFIG', repr(kubeconfig))


def helm_probe_command(binding, image, kubeconfig):
    validate_helm_binding(binding)
    if image != IMAGE_ID:
        raise ValueError('Full Helm probe requires the exact pinned controller image.')
    return ['docker', 'run', '--rm', '--pull=never', '--network=host', '--user', '1000:1000',
            '--cpus=0.25', '--memory=256m', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--env', 'NVIDIA_VISIBLE_DEVICES=void', '--env', 'PYTHONDONTWRITEBYTECODE=1',
            '--mount', 'type=bind,src=' + binding['host_path'] + ',dst=' + binding['container_path'] + ',readonly',
            '--mount', 'type=bind,src=/home/ubuntu/.kube/config,dst=' + kubeconfig + ',readonly',
            '--entrypoint', '/usr/local/bin/python', image, '-B', '-c', helm_probe_program(binding, kubeconfig)]


def run_helm_probe(binding, image, kubeconfig):
    verify_host_helm(binding)
    command = helm_probe_command(binding, image, kubeconfig)
    receipt = {'status': 'failed', 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'exit_code': None, 'helm': binding,
               'image_id': image, 'docker_command': command, 'stderr': '', 'stdout': '',
               'gpu_requests': 0, 'cluster_mutation': False}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        receipt.update(exit_code=124 if isinstance(error, subprocess.TimeoutExpired) else 127, error=repr(error))
        return receipt
    receipt.update(exit_code=result.returncode, stderr=result.stderr, stdout=result.stdout)
    if result.returncode == 0:
        try:
            value = json.loads(result.stdout)
            validate_helm_binding(value['helm'])
            expected_command = [binding['container_path'], '--kubeconfig', kubeconfig, 'get', 'values',
                                'nvidia-dra-driver-gpu', '-n', 'nvidia-dra-driver', '-a', '-o', 'json']
            values = value['driver_values']
            if (value['status'] != 'passed' or value['helm'] != binding or value['helm_version'] != binding['version'] or
                    value['command'] != expected_command or
                    values.get('resources', {}).get('gpus', {}).get('enabled') is not True or
                    values.get('gpuResourcesEnabledOverride') is not True):
                raise ValueError('CPU Helm probe result differs from its exact command/binding.')
            receipt.update(status='passed', result=value)
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            receipt['error'] = str(error)
    return receipt


def helm_support():
    """Use the same bounded probe implementation in preflight and bootstrap."""
    functions = (validate_helm_binding, verify_host_helm, helm_probe_program, helm_probe_command, run_helm_probe)
    return ('import hashlib,json,os,subprocess\nimport datetime as dt\nfrom pathlib import Path\nHELM=' + repr(HELM) +
            '\nIMAGE_ID=' + repr(IMAGE_ID) + '\n' + '\n'.join(inspect.getsource(function) for function in functions))


def paths(value):
    run = writer_transport.run_path(value)
    control = run.with_name(run.name + '-remote-control')
    return run, control, control / 'package'


def input_names(spec):
    """Keep the default exact; optional cache data needs a separate bound set."""
    cache = spec.get('dev_cache')
    if cache is None:
        expected = INPUTS
    elif type(cache) is dict and cache:
        expected = INPUTS | CACHE_INPUTS
    else:
        raise ValueError('Optional cache metadata must be an explicit qualified binding.')
    if set(spec['inputs']) != expected:
        raise ValueError('Unexpected full reader input whitelist.')
    return expected


def validate_cache_binding(run, spec):
    cache = spec.get('dev_cache')
    if cache is None:
        return None
    if type(cache.get('schema')) is not int or cache['schema'] != 1 or cache.get('candidate_id') != run.name:
        raise ValueError('Optional cache schema/candidate binding differs from this Full run.')
    for field, name in (('qualification_sha256', 'dev-cache-qualification.json'),
                        ('bootstrap_sha256', 'dev-cache-bootstrap.json'), ('receipt_sha256', 'dev-cache-receipt.json')):
        if cache.get(field) != spec['inputs'][name]:
            raise ValueError('Optional cache metadata is not bound to its exact input: ' + name)
    if not CACHE_SOURCES <= set(spec['source_snapshot']):
        raise ValueError('Optional cache requires both frozen cache implementation sources.')
    if cache.get('source_sha256') != {name: spec['source_snapshot'][name] for name in CACHE_SOURCES}:
        raise ValueError('Optional cache source fences differ from its frozen implementation closure.')
    from demos.shadow.composed import validate_candidate_cache
    result = validate_candidate_cache(run, spec)  # Read-only; includes producer/model/staging/owned-CM fences.
    if result is None:
        raise ValueError('Declared cache has no accepted frozen qualification.')
    return result


def frozen(run):
    state, demo, spec = read(run / 'state.json'), read(run / 'demo.json'), read(run / 'full-spec.json')
    namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(run).encode()).hexdigest()[:8] + '-demo'
    if (state.get('owner') != 'kubecon-dynamo-feature-tests' or state.get('namespace') != namespace
            or spec.get('namespace') != namespace or demo.get('namespace') != namespace
            or spec.get('profile') != PROFILE or state.get('shadow_full_profile') != PROFILE
            or demo.get('profile') != PROFILE or demo.get('rehearsal') is not False
            or demo.get('prepared') is not True or demo.get('cleaned_at') or demo.get('apply_started_at')
            or spec.get('reader_adapter_revision') != REVISION or spec.get('reader_enabled') is not True
            or spec.get('intentional_fault') is not False or spec.get('node') != NODE
            or sorted(spec.get('gpu_uuids', [])) != sorted(UUIDS)
            or state.get('shadow_full_spec_sha256') != sha(run / 'full-spec.json')
            or state.get('shadow_full_dgd_uid')
            or any((run / name).exists() for name in ('full-gpu-intent.json', 'shadow-fault-intent.json', 'shadow-fault.json', 'recovery-proof.json'))
            or any(key in state.get('checks', {}) for key in ('shadow-full-ready', 'shadow-failover', 'shadow-full-qualification'))
            or any(state['checks'].get(key, {}).get('status') != 'passed' for key in
                   ('model-staging', 'shadow-writer-preparation', 'shadow-writer-cuda'))):
        raise ValueError('Require the fresh prepared v6 full candidate before any deployment or fault.')
    input_names(spec)
    cuda = state['checks']['shadow-writer-cuda']
    if (cuda.get('node') != NODE or cuda.get('arithmetic') != 'passed'
            or sorted(cuda.get('gpu_uuids', [])) != sorted(UUIDS)):
        raise ValueError('Exact assigned-pair CUDA arithmetic proof differs.')
    for key, directory in (('inputs', ''), ('source_snapshot', 'source-snapshot'),
                           ('runtime_contract_hashes', 'runtime-contract-sources'), ('writer_basis_receipts', 'writer-basis')):
        if not spec.get(key): raise ValueError('Missing frozen full provenance: ' + key)
        for name, expected in spec[key].items():
            if sha(regular(run / directory / relative(name))) != expected:
                raise ValueError('Frozen full input/source/basis changed: ' + name)
            if key == 'source_snapshot' and sha(regular(source_path(name, root=ROOT))) != expected:
                raise ValueError('Frozen full implementation changed: ' + name)
    config = regular(Path(spec['config_manifest']))
    config.relative_to(ROOT / 'configs/dgd/workshop-shadow-composed' / run.name)
    if sha(config) != spec['config_manifest_sha256'] or sha(regular(ROOT / 'configs/super-vl-tp2-lock.json')) != spec['model_lock_sha256']:
        raise ValueError('Pinned full config/model changed.')
    basis = read(run / 'writer-basis/state.json')
    if basis['namespace'] != spec['source_writer_namespace'] or basis['checks'].get('shadow-writer-cleanup', {}).get('status') != 'passed':
        raise ValueError('Frozen accepted writer cleanup basis differs.')
    validate_cache_binding(run, spec)
    return state, demo, spec


def owner_path(run, namespace):
    return ROOT / '.local' / (namespace + '-shadow.gpu-lease') / 'owner.json'


def validate_owner(owner, run):
    if (owner.get('owner') != OWNER or owner.get('run') != str(run) or owner.get('node') != NODE
            or owner.get('gpu_uuids') != UUIDS or not owner.get('acquired_at')):
        raise ValueError('Existing scoped Full lease does not bind this run and physical pair.')


def validate_plan(plan, root):
    if (plan.get('schema') != 1 or plan.get('kind') != 'shadow-full-single-fault'
            or plan.get('logical_root') != str(root) or type(plan.get('fault_count')) is not int
            or plan.get('fault_count') != 1 or plan.get('node') != NODE or plan.get('gpu_uuids') != UUIDS
            or plan.get('reader_adapter_revision') != REVISION):
        raise ValueError('Full controller plan scope/root differs.')
    validate_helm_binding(plan.get('helm'))
    run, control, _ = paths(root / relative(plan['run'], 'results'))
    if (root / relative(plan['control'], 'results') != control
            or plan['recording'] != 'demos/transcripts/live/08-shadow-engine-composed/' + run.name
            or plan['raw_recording'] != str(control.relative_to(root) / 'private-recording')):
        raise ValueError('Full control/recording paths must belong to this exact run, outside it.')
    state, _, spec = frozen(run)
    if (plan.get('dev_cache') != spec.get('dev_cache') or ('dev_cache' in plan) != ('dev_cache' in spec)):
        raise ValueError('Full plan cache qualification differs from its frozen specification.')
    validate_owner(plan['reservation'], run)
    if plan['namespace'] != state['namespace'] or plan['reservation_directory'] != state['namespace'] + '-shadow.gpu-lease':
        raise ValueError('Full namespace or scoped lease differs.')
    if read(regular(owner_path(run, state['namespace']))) != plan['reservation']:
        raise ValueError('Exact regular Full lease owner differs from the frozen plan.')
    for name, expected in plan['initial_run_sha256'].items():
        if sha(regular(run / relative(name))) != expected: raise ValueError('Initial Full state changed before launch: ' + name)
    for name, expected in plan['source_sha256'].items():
        if sha(regular(root / relative(name))) != expected: raise ValueError('Frozen Full source changed: ' + name)
    writer_transport.health_inputs(root / relative(plan['health_before'], 'results'), state)
    regular(root / relative(plan['health_baseline'], 'results') / 'nodes.json')
    return run


def build(value, health_before, health_baseline, image_from=writer_transport.IMAGE_FROM):
    run, control, prep = paths(value)
    state, _, spec = frozen(run)
    reservation = read(regular(owner_path(run, state['namespace'])))
    validate_owner(reservation, run)  # Mirror the existing owner; never acquire/change its lease.
    health = writer_transport.health_inputs(health_before, state)
    baseline = Path(health_baseline).resolve();regular(baseline / 'nodes.json').relative_to(ROOT / 'results')
    if control.exists(): raise ValueError('Full control attempt exists; never repackage or overwrite.')
    if common.runtime_provenance(image_from)['image'] != IMAGE_ID:
        raise ValueError('Reuse only the exact existing owned CPU image.')
    control.mkdir(exist_ok=False)
    for name in common.IMAGE_INPUTS:
        target = control / name;target.parent.mkdir(exist_ok=True)
        with target.open('xb') as output: output.write(regular(Path(image_from) / name).read_bytes())
        target.chmod(0o400)
    runtime = common.runtime_provenance(control)
    files = [regular(path) for path in source_files(ROOT) if 'transcripts' not in path.relative_to(ROOT).parts]
    files += [regular(ROOT / 'configs/super-vl-tp2-lock.json'), regular(Path(spec['config_manifest'])), regular(baseline / 'nodes.json')] + health
    files += [regular(control / name) for name in common.IMAGE_INPUTS]
    names = input_names(spec) | {'state.json', 'demo.json', 'full-spec.json', 'model-lock.json'}
    files += [regular(run / name) for name in names]
    for key, folder in (('source_snapshot', 'source-snapshot'), ('runtime_contract_hashes', 'runtime-contract-sources'), ('writer_basis_receipts', 'writer-basis')):
        files += [regular(run / folder / relative(name)) for name in spec[key]]
    payload = {str(path.relative_to(ROOT)): path for path in files}
    for name in payload: common.safe_path(name, payload=True)
    if CONTROLLER not in payload:
        raise ValueError('Full remote controller source is missing.')
    tag = hashlib.sha256(str(run).encode()).hexdigest()[:8]
    controller_name = 'kubecon-shadow-full-' + tag
    plan = {'schema': 1, 'kind': 'shadow-full-single-fault', 'logical_root': str(ROOT),
        'run': str(run.relative_to(ROOT)), 'control': str(control.relative_to(ROOT)),
        'controller_name': controller_name, 'namespace': state['namespace'], 'node': NODE, 'gpu_uuids': UUIDS,
        'fault_count': 1, 'reader_adapter_revision': REVISION, 'runtime': runtime,
        'helm': dict(HELM),
        'reservation': reservation, 'reservation_directory': state['namespace'] + '-shadow.gpu-lease',
        'health_before': str(health[0].relative_to(ROOT)), 'health_baseline': str(baseline.relative_to(ROOT)),
        'recording': 'demos/transcripts/live/08-shadow-engine-composed/' + run.name,
        'raw_recording': str(control.relative_to(ROOT) / 'private-recording'),
        'source_sha256': {name: sha(path) for name, path in payload.items() if not path.is_relative_to(run)},
        'initial_run_sha256': {str(path.relative_to(run)): sha(path) for path in files if path.is_relative_to(run)},
        'immutable_run_sha256': {str(path.relative_to(run)): sha(path) for path in files if path.is_relative_to(run)
                                 and path not in (run / 'state.json', run / 'demo.json')}}
    if 'dev_cache' in spec:
        plan['dev_cache'] = spec['dev_cache']
    prep.mkdir(exist_ok=False);write_new(prep / 'plan.json', plan)
    payload[str((prep / 'plan.json').relative_to(ROOT))] = prep / 'plan.json'
    records = {name: {'bytes': path.stat().st_size, 'sha256': sha(path), 'mode': 0o600} for name, path in payload.items()}
    manifest = {'schema': 1, 'name': controller_name, 'logical_root': str(ROOT),
        'workspace': '/home/ubuntu/workshop-measurements/' + run.name + '-' + tag + '-full-controller/workspace',
        'image': IMAGE_ID, 'base_image': common.IMAGE, 'runtime': runtime, 'dependencies': common.DEPS,
        'helm': dict(HELM),
        'controller': CONTROLLER, 'plan': str((prep / 'plan.json').relative_to(ROOT)), 'plan_sha256': sha(prep / 'plan.json'), 'files': records}
    write_new(prep / 'payload-manifest.json', manifest)
    with tarfile.open(prep / 'payload.tar.gz', 'w:gz') as archive:
        for name, path in sorted(payload.items()): archive.add(path, arcname=name, recursive=False)
        raw = (prep / 'payload-manifest.json').read_bytes()
        member = tarfile.TarInfo('payload-manifest.json');member.size = len(raw);member.mode = 0o600
        archive.addfile(member, io.BytesIO(raw))
    digest = sha(prep / 'payload.tar.gz');common.verify_payload(prep / 'payload.tar.gz', digest)
    (prep / 'payload.sha256').write_text(digest + '\n')
    return {'controller_name': controller_name, 'files': len(records), 'payload_sha256': digest,
            'plan_sha256': manifest['plan_sha256'], 'reservation': str(owner_path(run, state['namespace'])),
            'control': str(control), 'lease_acquired_or_changed': False}


def bootstrap():
    replace = writer_transport.replace_once
    value = replace(common.BOOTSTRAP, "plan['reservation']['agent']!='workshop-snapshot-dgd'", "plan['reservation']['owner']!='" + OWNER + "'")
    value = replace(value, "local/'workshop-measurements-20261030.gpu-lease'", "local/plan['reservation_directory']")
    value = replace(value, "receipt=json.loads(receipt_raw);run_path=plan['run']", "receipt=json.loads(receipt_raw);run_path=plan['control']")
    value = replace(value, 'import demos.snapshot.dgd_demo as workshop_snapshot_dgd_demo,demos.snapshot.remote_controller as workshop_snapshot_remote_controller;',
                    'import demos.shadow.composed as workshop_shadow_composed,demos.shadow.full_remote_controller as workshop_shadow_full_remote_controller,demos.common.capture as capture_workshop_demo;')
    value = replace(value, 'Snapshot controller imports passed', 'Full single-fault controller imports passed')
    value = replace(value, "plan=json.loads(verified[manifest['plan']])", "plan=json.loads(verified[manifest['plan']])\n validate_helm_binding(plan.get('helm'))\n validate_helm_binding(manifest.get('helm'))\n verify_host_helm(plan['helm'])")
    value = replace(value, " '--mount','type=bind,src=/usr/bin/kubectl,dst='+logical+'/.local/bin/kubectl,readonly',",
                    " '--mount','type=bind,src='+plan['helm']['host_path']+',dst='+plan['helm']['container_path']+',readonly',\n '--mount','type=bind,src=/usr/bin/kubectl,dst='+logical+'/.local/bin/kubectl,readonly',")
    value = replace(value, ' result=subprocess.run(command,capture_output=True,text=True,timeout=45)',
                    " helm_receipt=run_helm_probe(plan['helm'],manifest['image'],logical+'/.local/kubeconfig')\n with (w/plan['control']/'helm-preflight.json').open('x') as stream:stream.write(json.dumps(helm_receipt,indent=2)+'\\n')\n if helm_receipt['status']!='passed':raise RuntimeError('Full CPU Helm preflight failed before GPU actions: '+str(helm_receipt.get('error',helm_receipt['stderr']))[-2000:])\n verify_host_helm(plan['helm'])\n result=subprocess.run(command,capture_output=True,text=True,timeout=45)")
    value = replace(value, "'source_import_probe':tested.stdout.strip()", "'source_import_probe':tested.stdout.strip(),'helm_preflight':helm_receipt")
    return helm_support() + '\n' + value


def package(value):
    run, control, prep = paths(value)
    manifest = read(prep / 'payload-manifest.json');digest = (prep / 'payload.sha256').read_text().strip()
    if common.verify_payload(prep / 'payload.tar.gz', digest) != manifest or sha(prep / 'plan.json') != manifest['plan_sha256']:
        raise ValueError('Frozen full package/plan changed.')
    return run, control, prep, manifest, digest


def launch(value):
    run, control, prep, manifest, digest = package(value)
    plan = read(prep / 'plan.json');validate_plan(plan, ROOT)
    validate_helm_binding(manifest.get('helm'))
    if read(regular(owner_path(run, plan['namespace']))) != plan['reservation'] or common.runtime_provenance(control) != manifest['runtime']:
        raise ValueError('Existing Full lease or owned image provenance changed.')
    for name, record in manifest['files'].items():
        if sha(regular(ROOT / name)) != record['sha256']: raise ValueError('Full source changed before launch: ' + name)
    write_new(prep / 'launch-intent.json', {'at': now(), 'payload_sha256': digest, 'plan_sha256': manifest['plan_sha256']})
    program = bootstrap().replace('EXPECTED_SHA', repr(digest)).replace('EXPECTED_BASE_IMAGE', repr(common.IMAGE))
    program = program.replace('EXPECTED_IMAGE', repr(IMAGE_ID)).replace('EXPECTED_DEPS', repr(common.DEPS))
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(program)], input=(prep / 'payload.tar.gz').read_bytes(), capture_output=True, timeout=240)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr.decode(errors='replace'),
               'transport_source_sha256': sha(__file__), 'payload_sha256': digest}
    if result.returncode == 0: receipt['remote'] = json.loads(result.stdout)
    write_new(prep / 'launch-result.json', receipt)
    if result.returncode: raise RuntimeError('Full launch failed/uncertain; never replay: ' + receipt['stderr'][-1500:])
    return receipt


STATUS = r'''
import datetime,hashlib,json,subprocess
from pathlib import Path
w=Path(manifest['workspace']);raw=(w/manifest['plan']).read_bytes()
if hashlib.sha256(raw).hexdigest()!=manifest['plan_sha256']:raise ValueError('Remote full plan hash differs')
plan=json.loads(raw)
state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',manifest['name']],timeout=20))
files={}
for root,names in ((w/plan['run'],('state.json','demo.json')),(w/plan['control'],('full-remote-controller.json','full-remote-exit.json'))):
 for name in names:
  p=root/name
  if p.is_file():files[name]=json.loads(p.read_text())
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller_state':state,'files':files}))
'''
COLLECT = (common.COLLECT.split("roots={'run':", 1)[0] + r'''
roots={'run':w/plan['run'],'recording':w/plan['recording'],'recording-private':w/plan['control']}
capture=roots['recording']/'capture.json'
if capture.is_file():
 proof=json.loads(capture.read_text())
 if proof.get('run')!=plan['logical_root']+'/'+plan['run'] or proof.get('demo')!='08-shadow-engine-composed' or proof.get('raw_output')!=plan['logical_root']+'/'+plan['raw_recording']:raise ValueError('Full capture provenance differs')
files={};paths={};total=0''' + common.COLLECT.split('files={};paths={};total=0', 1)[1])


def status(value):
    _, _, prep, manifest, _ = package(value)
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(common.remote_program(manifest, STATUS))], capture_output=True, text=True, timeout=90)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr}
    if not result.returncode: receipt['remote'] = json.loads(result.stdout)
    write_new(prep / ('status-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode: raise RuntimeError('Full observation unavailable; remote execution preserved: ' + result.stderr[-1000:])
    return receipt['remote']


def collect(value, output):
    run, control, prep, manifest, _ = package(value)
    output = Path(output).resolve();output.relative_to(ROOT / 'results')
    if output.exists() or any(output == p or output in p.parents or p in output.parents for p in (run, control)):
        raise ValueError('Use a fresh separate full collection directory.')
    archive = output.with_name(output.name + '.tar.gz');errors = output.with_name(output.name + '.stderr.txt')
    with archive.open('xb') as stream, errors.open('x') as stderr:
        result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(common.remote_program(manifest, COLLECT))], stdout=stream, stderr=stderr, timeout=600)
    write_new(output.with_name(output.name + '.transport.json'), {'at': now(), 'exit_code': result.returncode, 'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size})
    if result.returncode: raise RuntimeError('Full collection failed; preserve this attempt, no silent retransmission.')
    archive.chmod(0o400)
    return common.extract_collection(archive, output, {'run': str(run.relative_to(ROOT)), 'controller_name': manifest['name'], 'plan_sha256': manifest['plan_sha256']})


def preflight(value):
    _, _, prep, manifest, _ = package(value)
    plan = read(prep / 'plan.json')
    validate_helm_binding(plan.get('helm'))
    validate_helm_binding(manifest.get('helm'))
    program = common.PREFLIGHT.replace('EXPECTED_DEPS', repr(common.DEPS)).replace('EXPECTED_IMAGE', repr(IMAGE_ID))
    before_print = "helm_receipt=run_helm_probe(HELM,IMAGE_ID," + repr(manifest['logical_root'] + '/.local/kubeconfig') + ")\nif helm_receipt['status']!='passed':raise RuntimeError('Full CPU Helm preflight failed before GPU actions: '+str(helm_receipt.get('error',helm_receipt['stderr']))[-2000:])\n"
    program = writer_transport.replace_once(program, "print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'image_id':image['Id']",
                    before_print + "print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helm_preflight':helm_receipt,'image_id':image['Id']")
    program = helm_support() + '\n' + program
    result = subprocess.run(common.SSH + ['python3', '-c', shlex.quote(program)], capture_output=True, text=True, timeout=150)
    receipt = {'at': now(), 'exit_code': result.returncode, 'stderr': result.stderr, 'cluster_mutation': False}
    if not result.returncode: receipt['remote'] = json.loads(result.stdout)
    write_new(prep / ('preflight-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json'), receipt)
    if result.returncode: raise RuntimeError('Full CPU/client preflight failed: ' + result.stderr[-1500:])
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'preflight', 'launch', 'status', 'collect'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--health-before', type=Path)
    parser.add_argument('--health-baseline', type=Path)
    parser.add_argument('--image-from', type=Path, default=writer_transport.IMAGE_FROM)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args();os.umask(0o077)
    if args.action == 'build':
        if not args.health_before or not args.health_baseline: parser.error('build requires --health-before and --health-baseline containing nodes.json')
        result = build(args.run, args.health_before, args.health_baseline, args.image_from)
    elif args.action == 'collect':
        if args.output is None: parser.error('collect needs --output')
        value = collect(args.run, args.output);result = {k: value[k] for k in ('run', 'controller_name', 'plan_sha256', 'docker_state')}
    else: result = globals()[args.action](args.run)
    print(json.dumps(result, indent=2))
