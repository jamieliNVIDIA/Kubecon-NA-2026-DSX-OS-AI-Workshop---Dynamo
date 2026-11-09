#!/usr/bin/env python3
"""Fresh writer-only v4 role-bound runtime-descriptor composition experiment.

All live phases are explicit commands for the root executor. This module does
not alter a5, enable a reader, inject a fault, or qualify recovery.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

from scripts.source_paths import source_path
import yaml
from testlib import ROOT, Run
import demos.common.runtime as ui
import demos.shadow.writer as writer
from demos.shadow.demo import NODE, UUIDS, device_class
from demos.shadow.writer_descriptors import VERSION, ROUTING_BIAS_OWNERS, patch_descriptor_loader
from demos.shadow.parameter_inventory import VERSION as INVENTORY_VERSION
from demos.shadow.writer_cpu import PROGRAM as CPU_PROGRAM
from demos.shadow.diagnostics import preserve_writer_logs, inspect_wrappers

PROFILE = 'super-vl-writer-humming-runtime-descriptors-v4-routing-bias'
BASE = ROOT / 'results/overnight-shadow-super-vl-20261105-writer-a5'
DIAGNOSTIC = ROOT / 'results/overnight-shadow-super-vl-20261105-descriptor-writer-a5'
INVENTORY = ROOT / 'results/overnight-shadow-super-vl-20261105-descriptor-inventory-a1'
INFERENCE_SOURCES = ROOT / 'results/workshop-shadow-inference-sources-20261105-a1'
MOUNT = '/var/run/workshop-shadow-descriptors'
SOURCE_GROUPS = ('runtime-contract-sources', 'reader-runtime-sources',
    'reader-runtime-extra-sources', 'reader-runtime-attention-sources-a2', 'reader-runtime-model-sources')


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def routing_bias_basis(runtime_image):
    """Bind the narrow allowance to complete actual inventories and image sources."""
    diagnostic_state = json.loads((DIAGNOSTIC / 'state.json').read_text())
    diagnostic_spec = DIAGNOSTIC / 'descriptor-writer-spec.json'
    if (ui.digest(diagnostic_spec) != diagnostic_state['shadow_descriptor_spec_sha256'] or
            diagnostic_state['checks'].get('shadow-writer-cleanup', {}).get('status') != 'passed'):
        raise ValueError('Actual strict diagnostic must remain frozen and be canonically cleaned first.')
    health_path = DIAGNOSTIC / 'post-failure-health-audit-20261105-a1.json'
    health = json.loads(health_path.read_text())
    if (health.get('new_xids') != [] or health.get('changed_conditions') != [] or
            not all(health.get(key) is True for key in ('same_driver', 'same_boot', 'outputs_exit0'))):
        raise ValueError('Actual strict diagnostic has unresolved GPU-health evidence.')
    analysis_path = INVENTORY / 'analysis.json'
    analysis = json.loads(analysis_path.read_text())
    if (analysis.get('complete') is not True or analysis.get('pair_generation_verified') is not True or
            analysis.get('spec_sha256') != ui.digest(diagnostic_spec) or analysis.get('parse_errors')):
        raise ValueError('Routing-bias role requires complete actual two-rank diagnostic evidence.')
    for source in analysis['source_logs']:
        if ui.digest(INVENTORY / source['snapshot']) != source['sha256']:
            raise ValueError('Preserved actual diagnostic log changed.')
    expected_names = {owner + '.e_score_correction_bias' for owner in ROUTING_BIAS_OWNERS}
    for rank in ('0', '1'):
        rows = analysis['ranks'][rank]
        issues = rows['candidate_exporter_parameter_issues']
        if (not rows['complete'] or {row['name'] for row in issues} != expected_names or
                any(row['issues'] != ['requires-grad-not-false'] or row['dtype'] != 'torch.float32' or
                    row['requires_grad'] is not True or row['shape'] != [512] or row['stride'] != [1] or
                    row['layout_attributes'] != {} for row in issues)):
            raise ValueError('Observed routing-bias role differs from the proposed exact 40-parameter contract.')
    wrapper_root = DIAGNOSTIC / 'runtime-wrapper-sources'
    wrapper_manifest = wrapper_root / 'manifest.json'
    inference_manifest = INFERENCE_SOURCES / 'manifest.json'
    sources = {}
    for manifest_path, source_root, names in (
            (wrapper_manifest, wrapper_root, ('vllm/model_executor/layers/fused_moe/routed_experts.py',)),
            (inference_manifest, INFERENCE_SOURCES / 'sources',
                ('vllm/v1/worker/gpu_model_runner.py', 'vllm/v1/worker/gpu_worker.py'))):
        manifest = json.loads(manifest_path.read_text())
        if manifest['image_id'] != runtime_image or manifest.get('cuda_initialized') is not False:
            raise ValueError('Routing-bias source evidence used a different image or initialized CUDA.')
        for name in names:
            source = source_root / name
            if ui.digest(source) != manifest['files'][name]:
                raise ValueError('Routing-bias source evidence changed: ' + name)
            sources[name] = (ui.digest(source), source)
    basis = {'diagnostic_run': str(DIAGNOSTIC), 'diagnostic_spec_sha256': ui.digest(diagnostic_spec),
        'diagnostic_cleanup': diagnostic_state['checks']['shadow-writer-cleanup'],
        'diagnostic_health_sha256': ui.digest(health_path), 'inventory_analysis': str(analysis_path),
        'inventory_analysis_sha256': ui.digest(analysis_path),
        'source_manifest_sha256': {str(path): ui.digest(path) for path in (wrapper_manifest, inference_manifest)},
        'scope': 'Actual exact-role metadata plus matching-image inference source basis; no reader or recovery qualification'}
    return sources, basis


def render_graph(template, namespace, overlay, identity):
    graph = copy.deepcopy(template)
    graph['metadata'] = {'name': writer.GRAPH, 'namespace': namespace,
                         'labels': {'feature-test-run': namespace}}
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        pod['metadata']['labels'].update({'feature-test-run': namespace,
                                        'workshop-demo': 'shadow-writer'})
        if component['type'] != 'worker':
            continue
        component['experimental'] = {'gpuMemoryService': {'deviceClassName': namespace + '-shadow'}}
        spec, main = pod['spec'], pod['spec']['containers'][0]
        if spec['nodeSelector'] != {'kubernetes.io/hostname': NODE}:
            raise ValueError('Descriptor candidate changed the assigned node.')
        if any(e['name'] in ('DYN_VLLM_GMS_SHADOW_MODE', 'DYN_GMS_SCRATCH_KV_ENABLED') for e in main['env']):
            raise ValueError('Writer-only descriptor candidate must not enable Shadow or scratch KV.')
        old = {'writer-runtime', 'shadow-runtime'}
        spec['volumes'] = [v for v in spec['volumes'] if v['name'] not in old]
        main['volumeMounts'] = [v for v in main['volumeMounts'] if v['name'] not in old]
        spec['volumes'] += [
            {'name': 'writer-runtime', 'configMap': {'name': overlay}},
            {'name': 'runtime-descriptors', 'emptyDir': {'sizeLimit': '64Mi'}},
        ]
        for name in ('model_loader.py', 'workshop_humming.py', 'patches.py', 'workshop_descriptors.py',
                     'workshop_parameter_inventory.py'):
            main['volumeMounts'].append({'name': 'writer-runtime', 'subPath': name, 'readOnly': True,
                'mountPath': '/usr/local/lib/python3.12/dist-packages/gpu_memory_service/integrations/vllm/' + name})
        main['volumeMounts'].append({'name': 'runtime-descriptors', 'mountPath': MOUNT})
        main['env'] += [
            {'name': 'DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR', 'value': MOUNT},
            {'name': 'DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY', 'value': json.dumps(identity, sort_keys=True)},
        ]
    return graph


def freeze(path):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError('Use a fresh descriptor candidate; never overwrite a prior attempt.')
    base_spec = json.loads((BASE / 'writer-spec.json').read_text())
    base_state = json.loads((BASE / 'state.json').read_text())
    if (base_state['checks']['shadow-writer-qualification']['status'] != 'passed' or
            base_state['checks']['shadow-writer-cleanup']['status'] != 'passed'):
        raise ValueError('Passing a5 writer must be canonically cleaned before composing a new candidate.')
    if ui.digest(BASE / 'writer-spec.json') != base_state['shadow_writer_spec_sha256']:
        raise ValueError('The qualified a5 specification changed.')
    for name, digest in base_spec['inputs'].items():
        if ui.digest(BASE / name) != digest:
            raise ValueError('Frozen a5 input changed: ' + name)
    for name, digest in base_spec['source_snapshot'].items():
        if ui.digest(source_path(name, root=ROOT)) != digest:
            raise ValueError('Qualified a5 implementation changed: ' + name)
    run = Run(path)
    suffix = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    run.ns = 'dynamo-ft-r610-' + suffix + '-demo'
    run.state['namespace'] = run.ns
    sources = {}
    for group in SOURCE_GROUPS:
        root = BASE / group
        if group == 'runtime-contract-sources':
            entries = {name: digest for name, digest in base_spec['runtime_contract_hashes'].items()}
        else:
            manifest = json.loads((root / 'manifest.json').read_text())
            if manifest['image_id'] != base_state['model_lock']['runtime_image']:
                raise ValueError('Source inspection used a different runtime image.')
            entries = manifest['files']
        for name, digest in entries.items():
            source = root / name
            if ui.digest(source) != digest:
                raise ValueError('Installed source inspection changed: ' + name)
            if name in sources and sources[name][0] != digest:
                raise ValueError('Conflicting installed source inspections: ' + name)
            sources[name] = (digest, source)
    module_source = writer.SOURCE / 'runtime-sources/module.py'
    sources['gpu_memory_service/client/torch/module.py'] = (ui.digest(module_source), module_source)
    recovered = writer.SOURCE / 'recovered-runtime-20261105-a1'
    recovered_manifest = json.loads((recovered / 'manifest.json').read_text())
    for name in ('pods.json', 'runtime-sources.json'):
        if ui.digest(recovered / name) != recovered_manifest['receipts'][name]['sha256']:
            raise ValueError('Original ModelOpt inspection receipt changed: ' + name)
    pod_name = recovered_manifest['receipts']['runtime-sources.json']['args'][1]
    pod = next(p for p in json.loads((recovered / 'pods.json').read_text())['items']
               if p['metadata']['name'] == pod_name)
    image = next(c['imageID'] for c in pod['status']['containerStatuses'] if c['name'] == 'main')
    if not image.endswith(base_state['model_lock']['runtime_image'].split('@')[-1]):
        raise ValueError('ModelOpt source inspection used a different image.')
    modelopt_name = 'vllm/model_executor/layers/quantization/modelopt.py'
    modelopt = recovered / 'sources' / modelopt_name
    if modelopt.read_text() != json.loads((recovered / 'runtime-sources.json').read_text())['files'][modelopt_name]:
        raise ValueError('ModelOpt extracted source differs from its recorded image inspection.')
    sources[modelopt_name] = (ui.digest(modelopt), modelopt)
    additional, role_basis = routing_bias_basis(base_state['model_lock']['runtime_image'])
    for name, value in additional.items():
        if name in sources and sources[name][0] != value[0]:
            raise ValueError('Conflicting routing-bias source contract: ' + name)
        sources[name] = value
    contracts = {name: value[0] for name, value in sorted(sources.items())}
    role_source_names = tuple(additional) + ('vllm/model_executor/models/nemotron_h.py',
                                           'gpu_memory_service/client/torch/module.py')
    role_source_hashes = {name: contracts[name] for name in role_source_names}
    write(path / 'routing-bias-basis.json', role_basis)
    for name, (_, source) in sources.items():
        target = path / 'runtime-contract-sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    source_manifest = {'image_id': base_state['model_lock']['runtime_image'], 'files': contracts}
    write(path / 'source-contract-manifest.json', source_manifest)
    identity = {'candidate': path.name,
        'image_sha256': base_state['model_lock']['runtime_image'].split('@sha256:')[1],
        'model_revision': base_state['model_lock']['revision'],
        'model_config_sha256': base_state['model_lock']['model_metadata_sha256']['config.json'],
        'source_manifest_sha256': ui.digest(path / 'source-contract-manifest.json'),
        'tensor_parallel_size': 2}
    data = {'model_loader.py': patch_descriptor_loader((BASE / 'model_loader.py').read_text()),
            'workshop_humming.py': (BASE / 'workshop_humming.py').read_text(),
            'patches.py': (BASE / 'patches.py').read_text(),
            'workshop_descriptors.py': (ROOT / 'demos/shadow/writer_descriptors.py').read_text(),
            'workshop_parameter_inventory.py': (ROOT / 'demos/shadow/parameter_inventory.py').read_text()}
    checksum = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    overlay = 'writer-descriptors-' + checksum[:12]
    graph = render_graph(json.loads((BASE / 'deployment.json').read_text()), run.ns, overlay, identity)
    cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': overlay,
        'namespace': run.ns, 'labels': run.labels()}, 'immutable': True, 'data': data}
    dc = device_class(run.ns, UUIDS)
    dc['metadata']['labels'].update(run.labels())
    write(path / 'runtime-overlay.json', cm)
    write(path / 'deployment.json', graph)
    write(path / 'device-class.json', dc)
    for name, source in data.items():
        (path / name).write_text(source)
    deployment = yaml.safe_dump(graph, sort_keys=False)
    (path / 'deployment.yaml').write_text(deployment)
    config_dir = ROOT / 'configs/dgd/workshop-shadow-descriptor-writer' / path.name
    config_dir.mkdir(parents=True, exist_ok=False)
    (config_dir / 'deployment.yaml').write_text(deployment)
    critical = tuple(base_spec['source_snapshot']) + (
        'workshop_shadow_descriptor_writer.py', 'workshop_shadow_descriptors_v4.py',
        'workshop_shadow_parameter_inventory.py', 'workshop_shadow_descriptor_cpu_v4.py',
        'workshop_shadow_diagnostics.py')
    snapshots = path / 'source-snapshot'
    snapshots.mkdir()
    for name in critical:
        (snapshots / name).write_bytes((source_path(name, root=ROOT)).read_bytes())
    inputs = {p.name: ui.digest(p) for p in path.iterdir()
              if p.is_file() and p.name not in ('state.json', '.state.lock')}
    spec = dict(base_spec, profile=PROFILE, namespace=run.ns, source_run=str(BASE),
        overlay_sha256=checksum, runtime_contract_hashes=contracts, inputs=inputs,
        source_snapshot={name: ui.digest(snapshots / name) for name in critical},
        descriptor_version=VERSION, descriptor_identity=identity, descriptor_mount=MOUNT,
        parameter_inventory_version=INVENTORY_VERSION,
        routing_bias_source_hashes=role_source_hashes,
        descriptor_cpu_program_sha256=hashlib.sha256(CPU_PROGRAM.encode()).hexdigest(),
        config_manifest=str(config_dir / 'deployment.yaml'), config_manifest_sha256=ui.digest(config_dir / 'deployment.yaml'),
        intentional_fault=False, reader_enabled=False,
        diagnostic_wrappers_required=True,
        failure_log_policy='previous logs before stop; independent unlimited continuous streams',
        scope='Fresh writer-only role-bound routing-bias descriptor composition; no Shadow/reader/recovery qualification')
    write(path / 'descriptor-writer-spec.json', spec)
    run.state.update(shadow_writer_profile=PROFILE,
        shadow_descriptor_spec_sha256=ui.digest(path / 'descriptor-writer-spec.json'))
    run.save()
    print(json.dumps({'run': str(path), 'namespace': run.ns, 'overlay': checksum,
        'contract_sources': len(contracts), 'scope': spec['scope'], 'live_actions': False}, indent=2))


def load(path):
    run = Run(Path(path).resolve())
    file = run.path / 'descriptor-writer-spec.json'
    spec = json.loads(file.read_text())
    if (spec['profile'] != PROFILE or run.state.get('shadow_writer_profile') != PROFILE or
            spec['namespace'] != run.ns or ui.digest(file) != run.state['shadow_descriptor_spec_sha256']):
        raise ValueError('Descriptor writer candidate identity changed.')
    for name, digest in spec['inputs'].items():
        if ui.digest(run.path / name) != digest:
            raise ValueError('Frozen descriptor input changed: ' + name)
    for name, digest in spec['source_snapshot'].items():
        if ui.digest(source_path(name, root=ROOT)) != digest:
            raise ValueError('Frozen descriptor implementation changed: ' + name)
    for name, digest in spec['runtime_contract_hashes'].items():
        if ui.digest(run.path / 'runtime-contract-sources' / name) != digest:
            raise ValueError('Frozen installed-source contract changed: ' + name)
    if (ui.digest(ui.MODEL_LOCK) != spec['model_lock_sha256'] or
            ui.digest(Path(spec['config_manifest'])) != spec['config_manifest_sha256']):
        raise ValueError('Pinned model/runtime or executable config manifest changed.')
    return run, spec


def inspect_descriptors(run, spec):
    """One explicit bounded actual-image CPU probe using this candidate's bytes."""
    if run.state['checks'].get('shadow-writer-preparation', {}).get('status') != 'passed':
        raise ValueError('Prepare the fresh candidate before its actual-image descriptor CPU probe.')
    intent = run.path / 'descriptor-cpu-intent.json'
    sources = {'DESCRIPTOR': run.path / 'workshop_descriptors.py',
               'PARAMETER_INVENTORY': run.path / 'workshop_parameter_inventory.py'}
    program_digest = hashlib.sha256(CPU_PROGRAM.encode()).hexdigest()
    if program_digest != spec['descriptor_cpu_program_sha256']:
        raise ValueError('Actual-image CPU program changed after freeze.')
    # O_EXCL through mode x prevents repeated CPU attempts from overwriting logs.
    with intent.open('x') as stream:
        json.dump({'at': ui.now(), 'program_sha256': program_digest,
            'source_sha256': {key: ui.digest(path) for key, path in sources.items()}}, stream, indent=2)
        stream.write('\n')
    environment = []
    for key, path in sources.items():
        environment += [
            {'name': key + '_SOURCE_B64', 'value': base64.b64encode(path.read_bytes()).decode()},
            {'name': key + '_SOURCE_SHA256', 'value': ui.digest(path)},
        ]
    environment.append({'name': 'EXPECTED_ROUTING_BIAS_SOURCE_HASHES',
                        'value': json.dumps(spec['routing_bias_source_hashes'], sort_keys=True)})
    try:
        from snapshot_tp2_workflow import cpu_probe
        report = cpu_probe(run, 'descriptor-v4-cpu-check', CPU_PROGRAM, environment)
        if (report.get('cuda_initialized') is not False or
                report.get('descriptor_source_sha256') != ui.digest(sources['DESCRIPTOR']) or
                report.get('parameter_inventory_source_sha256') != ui.digest(sources['PARAMETER_INVENTORY']) or
                report.get('parameter_inventory_real_torch_meta_cpu') != 'passed' or
                report.get('routing_bias_roles_real_meta_stock_cpu') != 40 or
                report.get('routing_bias_source_hashes') != spec['routing_bias_source_hashes'] or
                report.get('stock_shape_dtype_guard') != 'unchanged strict rejection'):
            raise ValueError('Actual-image descriptor CPU probe returned incomplete source/metadata/no-CUDA evidence.')
        write(run.path / 'descriptor-cpu-result.json', report)
        run.result('shadow-writer-descriptor-cpu', 'passed', program_sha256=program_digest, **report)
    except Exception as error:
        run.result('shadow-writer-descriptor-cpu', 'failed', error=str(error),
            scope='Actual-image CPU preflight only; preserve intent and create a fresh candidate before retrying')
        raise


def require_descriptor_cpu(run, spec):
    proof = run.state['checks'].get('shadow-writer-descriptor-cpu', {})
    if (proof.get('status') != 'passed' or proof.get('cuda_initialized') is not False or
            proof.get('program_sha256') != spec['descriptor_cpu_program_sha256'] or
            proof.get('descriptor_source_sha256') != ui.digest(run.path / 'workshop_descriptors.py') or
            proof.get('parameter_inventory_source_sha256') != ui.digest(run.path / 'workshop_parameter_inventory.py') or
            proof.get('routing_bias_roles_real_meta_stock_cpu') != 40 or
            proof.get('routing_bias_source_hashes') != spec['routing_bias_source_hashes'] or
            proof.get('stock_shape_dtype_guard') != 'unchanged strict rejection'):
        raise ValueError('Run the frozen actual-image descriptor CPU probe before any diagnostic GPU startup.')


def capture(run, spec):
    try:
        return capture_validated(run, spec)
    except Exception as error:
        run.result('shadow-writer-descriptors', 'failed', error=str(error),
            intentional_fault=False, scope='Descriptor capture failed provenance checks; no accepted reader manifest')
        raise


def capture_validated(run, spec):
    proof = run.state['checks'].get('shadow-writer-serving', {})
    if proof.get('status') != 'passed':
        raise ValueError('Writer coding must pass before descriptor capture.')
    baseline_claim = json.loads((run.path / 'worker-gpu-claim.json').read_text())
    baseline_gms = {key: value for key, value in json.loads((run.path / 'gms-after.json').read_text()).items()
                    if key.endswith('_weights.sock')}
    observation = run.path / ('descriptor-capture-observation-' + str(time.time_ns()))
    observation.mkdir()
    before = capture_state(run, proof, baseline_claim, baseline_gms, observation / 'before')
    program = '''import json,os
from pathlib import Path
root=Path(os.environ['DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR'])
print(json.dumps({str(rank):json.loads((root/('rank-'+str(rank)+'.json')).read_text()) for rank in (0,1)}))
'''
    result = run.k('exec', proof['worker_pod'], '-n', run.ns, '-c', 'main', '--',
        'python3', '-c', program, timeout=60)
    manifests = json.loads(result.stdout)
    write(observation / 'raw-rank-manifests.json', manifests)
    after = capture_state(run, proof, baseline_claim, baseline_gms, observation / 'after')
    if before != after:
        raise ValueError('Writer/container/claim/GMS state changed while reading rank manifests.')
    hashes = {value['state']['memory_layout_hash'] for value in before['gms'].values()}
    for value in manifests.values():
        layout_hash = value.get('gms_memory_layout_hash', '')
        if (len(layout_hash) != 64 or any(c not in '0123456789abcdef' for c in layout_hash) or
                layout_hash not in hashes):
            raise ValueError('Captured descriptor does not match the current committed GMS layout.')
    directory = run.path / 'rank-manifests'
    directory.mkdir(exist_ok=True)
    summary = {}
    for rank in (0, 1):
        value = manifests[str(rank)]
        identity = dict(spec['descriptor_identity'], tp_rank=rank)
        if value['version'] != VERSION or value['identity'] != identity:
            raise ValueError('Captured descriptor version/rank/source identity mismatch.')
        if len(value.get('gms_memory_layout_hash', '')) != 64:
            raise ValueError('Captured descriptor has no committed GMS hash.')
        path = directory / ('rank-' + str(rank) + '.json')
        if path.exists() and json.loads(path.read_text()) != value:
            raise ValueError('Attempted to overwrite a different captured descriptor.')
        if not path.exists():
            write(path, value)
        summary[str(rank)] = {'manifest_sha256': ui.digest(path), 'counts': value['counts'],
            'reader_ready': value['reader_ready'], 'unhandled_modules': value['unhandled_modules'],
            'gms_memory_layout_hash': value['gms_memory_layout_hash']}
    write(run.path / 'descriptor-capture.json', summary)
    write(run.path / 'descriptor-capture-provenance.json', {'serving_proof': proof,
        'observation': str(observation), 'before': before, 'after': after})
    run.result('shadow-writer-descriptors', 'passed', ranks=summary,
        scope='Actual writer descriptor capture only; reader readiness is a manifest gate, not GPU reader proof')


def capture_state(run, proof, baseline_claim, baseline_gms, directory):
    """Bind a manifest read to the actual qualified writer and GMS generation."""
    directory.mkdir()
    pod = run.get('get', 'pod', proof['worker_pod'], '-n', run.ns)
    write(directory / 'pod.json', pod)
    if (pod['metadata']['uid'] != proof['worker_uid'] or
            pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns or
            pod['spec']['nodeName'] != NODE):
        raise ValueError('Writer Pod identity or placement changed before descriptor capture.')
    # Keep the original serving claim proof intact: these helpers write fresh
    # evidence under this observation, while their Kubernetes calls use run.
    checked = SimpleNamespace(path=directory, ns=run.ns, state=run.state, get=run.get, k=run.k)
    allocation = writer.verify_worker(checked, pod)
    if (set(allocation['gpu_uuids']) != set(proof['gpu_uuids']) or
            allocation['container_ids'] != proof['container_ids']):
        raise ValueError('Writer/GMS container generation or physical GPU claim changed since serving.')
    claim = json.loads((directory / 'worker-gpu-claim.json').read_text())
    claim_identity = lambda value: {'name': value['metadata']['name'], 'uid': value['metadata']['uid'],
                                   'allocation': value['status']['allocation']}
    if claim_identity(claim) != claim_identity(baseline_claim):
        raise ValueError('Writer ResourceClaim identity/allocation changed since serving.')
    gms = writer.gms_state(checked, pod, 'gms-current.json')
    if gms != baseline_gms:
        raise ValueError('Committed GMS layout or generation changed since serving.')
    return {'pod_uid': pod['metadata']['uid'], 'allocation': allocation,
            'claim': claim_identity(claim), 'gms': gms}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'prepare', 'inspect-descriptors', 'inspect-wrappers', 'probe', 'deploy', 'verify', 'capture', 'finalize', 'cleanup'))
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=1500)
    parser.add_argument('--health-before', type=Path)
    parser.add_argument('--health-after', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        freeze(args.run)
        return
    run, spec = load(args.run)
    if args.action == 'prepare': writer.prepare(run, spec)
    elif args.action == 'inspect-descriptors': inspect_descriptors(run, spec)
    elif args.action == 'inspect-wrappers': inspect_wrappers(run)
    elif args.action == 'probe':
        require_descriptor_cpu(run, spec)
        writer.probe(run, spec)
    elif args.action == 'deploy':
        require_descriptor_cpu(run, spec)
        if (spec.get('diagnostic_wrappers_required') and
                run.state['checks'].get('shadow-writer-wrapper-inspection', {}).get('status') != 'passed'):
            raise ValueError('Run the actual-image CPU wrapper source inspection before diagnostic model startup.')
        writer.deploy(run, spec, args.health_before)
    elif args.action == 'verify':
        with preserve_writer_logs(run, writer):
            writer.verify(run, spec, args.timeout)
            capture(run, spec)
    elif args.action == 'capture': capture(run, spec)
    elif args.action == 'finalize': writer.finalize(run, args.health_after)
    elif args.action == 'cleanup':
        if (run.state['checks'].get('shadow-writer-serving', {}).get('status') == 'passed' and
                run.state['checks'].get('shadow-writer-descriptors', {}).get('status') not in ('passed', 'failed')):
            raise ValueError('Capture actual rank manifests before deleting the writer Pod.')
        writer.cleanup(run)


if __name__ == '__main__': main()
