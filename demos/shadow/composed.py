#!/usr/bin/env python3
"""Source-frozen active/standby composition of the qualified descriptor writer.

Freeze is offline and refuses incomplete writer evidence. Live commands are
explicit root-executor actions. The original stock GMS materializer is kept.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
from types import SimpleNamespace

from scripts.source_paths import source_path
import yaml
from testlib import ROOT, Run, OWNER as RUN_OWNER
import demos.common.runtime as ui
import demos.common.support as support
import demos.shadow.demo as presenter
import demos.shadow.writer as writer
import demos.shadow.descriptor_writer as instrumented
import demos.shadow.writer_descriptors as descriptors
from demos.shadow.writer_descriptors import VERSION
from demos.shadow.reader_descriptors import READER_ADAPTER_REVISION
from demos.shadow.reader_delta import validate_reader_delta
from demos.shadow.reader_cpu import build_packet as build_reader_packet, PROGRAM as READER_CPU_PROGRAM
from demos.shadow.follow_policy import continuous_logs
from demos.shadow.diagnostics import collect_previous

PROFILE = 'super-vl-shadow-humming-runtime-descriptors-v4-routing-bias'
GRAPH, NODE, UUIDS = presenter.GRAPH, presenter.NODE, presenter.UUIDS
BASIS_FILES = ('state.json', 'descriptor-writer-spec.json', 'descriptor-capture.json',
    'descriptor-capture-provenance.json', 'health-before.json', 'health-after.json',
    'model-lock.json', 'coding-responses.json', 'private-lock-proof.json', 'gms-after.json',
    'rank-manifests/rank-0.json', 'rank-manifests/rank-1.json')
DEV_CACHE_INPUTS = ('dev-cache-qualification.json', 'dev-cache-bootstrap.json', 'dev-cache-receipt.json')
DEV_CACHE_SOURCES = ('workshop_mx_dev_cache.py', 'mx_dev_cache_stage.py')


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def validate_basis(spec, state, manifests, capture, provenance, health):
    checks = state['checks']
    for name in ('shadow-writer-serving', 'shadow-writer-descriptors', 'shadow-writer-qualification', 'shadow-writer-cleanup'):
        if checks.get(name, {}).get('status') != 'passed':
            raise ValueError('Writer composition gate is incomplete: ' + name)
    if checks['shadow-writer-qualification'].get('new_xids') != []:
        raise ValueError('Writer composition has unresolved GPU-health evidence.')
    if health['receipt']['observed_at'] < checks['shadow-writer-descriptors']['updated_at']:
        raise ValueError('Writer final GPU health predates descriptor capture.')
    serving = checks['shadow-writer-serving']
    if (provenance['before'] != provenance['after'] or
            provenance['before']['pod_uid'] != serving['worker_uid'] or
            provenance['before']['allocation']['container_ids'] != serving['container_ids']):
        raise ValueError('Writer descriptor capture has no stable serving-generation provenance.')
    hashes = {v['state']['memory_layout_hash'] for v in provenance['before']['gms'].values()}
    if set(manifests) != {'0', '1'}:
        raise ValueError('Both actual TP-rank manifests are required.')
    counts = None
    for rank in (0, 1):
        value = manifests[str(rank)]
        if (value['version'] != VERSION or
                value['identity'] != dict(spec['descriptor_identity'], tp_rank=rank) or
                value.get('reader_ready') is not True or value.get('unhandled_modules')):
            raise ValueError('Actual writer manifest is not a complete, matching reader basis.')
        if value['gms_memory_layout_hash'] not in hashes or capture[str(rank)]['reader_ready'] is not True:
            raise ValueError('Writer manifest is not bound to its verified committed GMS state.')
        descriptors._validate_routing_bias_inventory(value)
        for owner in descriptors.ROUTING_BIAS_OWNERS:
            row = value['modules'][owner]
            if (row.get('kind') != 'humming-moe' or row.get('layer_class') != descriptors.ROUTED_EXPERTS or
                    row.get('quant_method_class') != descriptors.MODEL_OPT + ':ModelOptNvFp4FusedMoE' or
                    row.get('experts_class') not in descriptors.MOE_EXPERTS):
                raise ValueError('Writer routing-correction descriptor has an unreviewed owner/backend.')
        if counts is not None and counts != value['counts']:
            raise ValueError('TP ranks disagree about the supported runtime inventory.')
        counts = value['counts']
    if counts.get('modelopt-attention', 0) < 1:
        raise ValueError('The real manifest did not establish the model attention runtime.')
    return counts


def _regular(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(part in ('.', '..') for part in relative.parts):
        raise ValueError('Writer evidence must use safe relative paths.')
    current = Path(root)
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Writer evidence symlinks are not allowed.')
    if not current.is_file():
        raise ValueError('Required writer evidence is absent: ' + name)
    return current


def _collection(path):
    """Recheck a completed extracted collection without constructing/mutating Run."""
    root = path.parent
    verification_path = _regular(root, 'collection-verification.json')
    manifest_path = _regular(root, 'collection-manifest.json')
    verification = json.loads(verification_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if (path.name != 'run' or verification.get('status') != 'verified' or
            verification.get('state_adopted') is not False or
            manifest.get('docker_state', {}).get('Running') is not False or
            manifest.get('docker_state', {}).get('ExitCode') != 0 or
            verification.get('files') != len(manifest.get('files', {})) or
            any(verification.get(key) != manifest.get(key) for key in ('run', 'controller_name', 'plan_sha256'))):
        raise ValueError('Writer collection is incomplete, live, unverified or from another controller.')
    for name, record in manifest['files'].items():
        if PurePosixPath(name).parts[0] != 'run':
            raise ValueError('Unexpected writer-only collection root.')
        source = _regular(root, name)
        if source.stat().st_size != record['bytes'] or ui.digest(source) != record['sha256']:
            raise ValueError('Extracted writer collection changed: ' + name)
    original_relative = PurePosixPath(manifest['run'])
    if (original_relative.is_absolute() or len(original_relative.parts) != 2 or
            original_relative.parts[0] != 'results' or '..' in original_relative.parts):
        raise ValueError('Collection has no exact original named writer run.')
    original = ROOT.joinpath(*original_relative.parts)
    plan_path = _regular(original, 'writer-remote-package/plan.json')
    local_manifest = json.loads(_regular(original, 'writer-remote-package/payload-manifest.json').read_text())
    if (ui.digest(plan_path) != manifest['plan_sha256'] or
            local_manifest.get('plan_sha256') != manifest['plan_sha256'] or
            local_manifest.get('name') != manifest['controller_name']):
        raise ValueError('Collected writer does not match the original frozen local launch plan.')
    plan = json.loads(plan_path.read_text())
    if (plan.get('run') != manifest['run'] or plan.get('logical_root') != str(ROOT) or
            plan.get('namespace') != json.loads((path / 'state.json').read_text()).get('namespace') or
            plan.get('reader_enabled') is not False or plan.get('intentional_fault') is not False):
        raise ValueError('Collected writer plan scope or original path differs.')
    for name, expected in plan['immutable_run_sha256'].items():
        if ui.digest(_regular(path, name)) != expected:
            raise ValueError('Collected immutable writer input differs from the launch: ' + name)
    return original, manifest, verification


def writer_basis_binding(path):
    """Exact hash binding for root's separate acceptance receipt; no success claim.

    Root may add schema=1, kind=shadow-writer-basis-root-audit and status=passed
    only after its independent audit accepts serving/manifests/health/cleanup.
    The collected state remains a read-only evidence source, never adopted.
    """
    path = Path(path).resolve()
    original, manifest, verification = _collection(path)
    state = json.loads(_regular(path, 'state.json').read_text())
    return {'source_run': str(path), 'original_run': str(original), 'namespace': state['namespace'],
        'files': {name: ui.digest(_regular(path, name)) for name in BASIS_FILES + ('writer-remote-exit.json',)},
        'collection_manifest_sha256': ui.digest(path.parent / 'collection-manifest.json'),
        'collection_verification_sha256': ui.digest(path.parent / 'collection-verification.json'),
        'plan_sha256': manifest['plan_sha256'], 'controller_name': manifest['controller_name'],
        'archive_sha256': verification['archive_sha256']}


def qualified_basis(path, source_audit=None):
    """Read-only local/collected basis validation; never calls Run/instrumented.load."""
    path = Path(path).resolve()
    state = json.loads(_regular(path, 'state.json').read_text())
    spec = json.loads(_regular(path, 'descriptor-writer-spec.json').read_text())
    collected = (path.parent / 'collection-manifest.json').exists() or path.name == 'run'
    original, collection, verification = _collection(path) if collected else (path, None, None)
    if (state.get('owner') != 'kubecon-dynamo-feature-tests' or
            spec.get('profile') != instrumented.PROFILE or state.get('shadow_writer_profile') != instrumented.PROFILE or
            spec.get('descriptor_version') != VERSION or spec.get('namespace') != state.get('namespace') or
            not state['namespace'].startswith('dynamo-ft-') or
            state.get('shadow_descriptor_spec_sha256') != ui.digest(path / 'descriptor-writer-spec.json') or
            spec.get('reader_enabled') is not False or spec.get('intentional_fault') is not False):
        raise ValueError('Writer basis identity/profile/scope changed.')
    for name in ('shadow-writer-serving', 'shadow-writer-descriptors', 'shadow-writer-qualification', 'shadow-writer-cleanup'):
        if state['checks'].get(name, {}).get('status') != 'passed':
            raise ValueError('Writer composition gate is incomplete: ' + name)
    if original.parent != ROOT / 'results':
        raise ValueError('Writer basis needs its exact original named workspace run.')
    expected_namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(original).encode()).hexdigest()[:8] + '-demo'
    if (state['namespace'] != expected_namespace or
            spec['descriptor_identity'].get('candidate') != original.name or
            spec['descriptor_identity'].get('tensor_parallel_size') != 2 or spec.get('node') != NODE or
            set(spec.get('gpu_uuids', [])) != set(UUIDS)):
        raise ValueError('Writer basis candidate/path/placement identity differs from its frozen origin.')
    if collected and (path / 'descriptor-writer-spec.json').read_bytes() != (original / 'descriptor-writer-spec.json').read_bytes():
        raise ValueError('Collected writer specification differs from the original frozen candidate.')
    for name, expected in spec['inputs'].items():
        if ui.digest(_regular(path, name)) != expected:
            raise ValueError('Frozen writer input changed: ' + name)
    for name, expected in spec['source_snapshot'].items():
        if (ui.digest(_regular(path / 'source-snapshot', name)) != expected or
                ui.digest(_regular(ROOT, str(source_path(name, root=ROOT).relative_to(ROOT)))) != expected):
            raise ValueError('Frozen writer implementation/source snapshot changed: ' + name)
    for name, expected in spec['runtime_contract_hashes'].items():
        if ui.digest(_regular(path / 'runtime-contract-sources', name)) != expected:
            raise ValueError('Frozen writer installed-source contract changed: ' + name)
    if ui.digest(path / 'source-contract-manifest.json') != spec['descriptor_identity']['source_manifest_sha256']:
        raise ValueError('Writer runtime identity is not bound to its exact installed-source contract manifest.')
    overlay = json.loads((path / 'runtime-overlay.json').read_text())['data']
    if hashlib.sha256(json.dumps(overlay, sort_keys=True).encode()).hexdigest() != spec['overlay_sha256']:
        raise ValueError('Writer overlay contents differ from their frozen identity.')
    for installed, implementation in (('workshop_descriptors.py', 'workshop_shadow_descriptors_v4.py'),
            ('workshop_parameter_inventory.py', 'workshop_shadow_parameter_inventory.py')):
        if (hashlib.sha256(overlay[installed].encode()).hexdigest() != spec['source_snapshot'].get(implementation) or
                overlay[installed] != (path / installed).read_text()):
            raise ValueError('Writer overlay does not contain its reviewed v4/inventory implementation.')
    config = ROOT / 'configs/dgd/workshop-shadow-descriptor-writer' / original.name / 'deployment.yaml'
    if (spec['config_manifest'] != str(config) or ui.digest(config) != spec['config_manifest_sha256'] or
            ui.digest(path / 'deployment.yaml') != spec['config_manifest_sha256'] or
            ui.digest(ui.MODEL_LOCK) != spec['model_lock_sha256'] or
            json.loads((path / 'model-lock.json').read_text()) != state.get('model_lock') or
            (collected and (path / 'model-lock.json').read_bytes() != (original / 'model-lock.json').read_bytes())):
        raise ValueError('Writer original config path/model lock/effective manifest changed.')
    files = {name: _regular(path, name) for name in BASIS_FILES}
    if collected:
        reservation = ROOT / '.local' / (state['namespace'] + '-writer-remote.gpu-lease')
        if reservation.exists():
            raise ValueError('Root must close the original writer GPU reservation before full composition freeze.')
        exit_path = _regular(path, 'writer-remote-exit.json')
        terminal = json.loads(exit_path.read_text())
        if (terminal.get('status') != 'qualified_and_cleaned_pending_root_audit' or
                terminal.get('cleanup') != 'passed' or terminal.get('reader_enabled') is not False or
                terminal.get('intentional_fault') is not False):
            raise ValueError('Remote writer has no terminal qualified-and-cleaned result.')
        if source_audit is None:
            raise ValueError('Collected writer requires a separate accepted root audit; remote state is never adopted.')
        audit_path = Path(source_audit).resolve()
        audit = json.loads(audit_path.read_text())
        binding = writer_basis_binding(path)
        if (audit.get('schema') != 1 or audit.get('kind') != 'shadow-writer-basis-root-audit' or
                audit.get('status') != 'passed' or any(audit.get(key) != value for key, value in binding.items())):
            raise ValueError('Root writer acceptance is absent or not bound to these exact collected bytes.')
        files.update({'writer-remote-exit.json': exit_path, 'root-acceptance.json': audit_path,
            'collection-manifest.json': path.parent / 'collection-manifest.json',
            'collection-verification.json': path.parent / 'collection-verification.json'})
    values = {name: json.loads(source.read_text()) for name, source in files.items()}
    capture = values['descriptor-capture.json']
    manifests = {str(rank): values['rank-manifests/rank-' + str(rank) + '.json'] for rank in (0, 1)}
    for rank in (0, 1):
        if ui.digest(path / ('rank-manifests/rank-' + str(rank) + '.json')) != capture[str(rank)]['manifest_sha256']:
            raise ValueError('Actual captured writer manifest changed.')
    counts = validate_basis(spec, state, manifests, capture,
        values['descriptor-capture-provenance.json'], values['health-after.json'])
    basis = SimpleNamespace(path=path, ns=state['namespace'], state=state, original_path=original,
                            collected=collected)
    return basis, spec, files, counts


def render_graph(template, namespace, overlay, identity):
    template = copy.deepcopy(template)
    for component in template['spec']['components']:
        if component['type'] != 'worker': continue
        spec = component['podTemplate']['spec']
        main = spec['containers'][0]
        spec['volumes'] = [v for v in spec['volumes'] if v['name'] != 'runtime-descriptors']
        main['volumeMounts'] = [v for v in main['volumeMounts'] if v['name'] != 'runtime-descriptors']
        main['env'] = [e for e in main['env'] if e['name'] not in
            ('DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR', 'DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY')]
    graph = instrumented.render_graph(template, namespace, overlay, identity)
    graph['metadata']['name'] = GRAPH
    graph['metadata']['annotations'] = {'nvidia.com/dynamo-kube-discovery-mode': 'container'}
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        pod['metadata']['labels']['workshop-demo'] = 'shadow'
        if component['type'] == 'worker':
            component['experimental']['failover'] = {}
        else:
            env = pod['spec']['containers'][0]['env']
            migration = next((e for e in env if e['name'] == 'DYN_MIGRATION_LIMIT'), None)
            if migration is None or migration.get('value') != '0':
                raise ValueError('Full Shadow composition requires fresh requests with migration disabled.')
    return graph


def reader_delta_inputs(basis, source_spec, reader_cpu, reader_packet):
    """Accept the exact reader-only change and its independent actual-image CPU gate."""
    if reader_cpu is None or reader_packet is None:
        raise ValueError('Supply the passed actual-image reader CPU result and its exact fixture packet before full freeze.')
    reader_cpu, reader_packet = Path(reader_cpu).resolve(), Path(reader_packet).resolve()
    implementation = (ROOT / 'demos/shadow/reader_descriptors.py').read_text()
    delta = validate_reader_delta((basis.path / 'workshop_descriptors.py').read_text(), implementation)
    packet = json.loads(reader_packet.read_text())
    if json.dumps(packet, sort_keys=True) != json.dumps(build_reader_packet(basis.path), sort_keys=True):
        raise ValueError('Reader CPU packet differs from the accepted actual writer schema/config/parameter evidence.')
    program = reader_packet.parent / 'cpu-program.py'
    if program.read_text() != READER_CPU_PROGRAM:
        raise ValueError('Reader CPU program differs from the frozen reviewed payload.')
    intent_path = reader_cpu.parent / 'intent.json'
    intent = json.loads(intent_path.read_text())
    if (intent.get('program_sha256') != hashlib.sha256(READER_CPU_PROGRAM.encode()).hexdigest() or
            intent.get('sources') != {'DESCRIPTOR': delta['reader_helper_sha256'], 'MOE_PACKET': ui.digest(reader_packet)}):
        raise ValueError('Reader CPU intent is not bound to this exact helper/program/packet.')
    report = json.loads(reader_cpu.read_text())
    checks = list(reader_cpu.parent.glob('check-reader-v6-source-cpu-*.json'))
    if len(checks) != 1:
        raise ValueError('Reader CPU requires exactly one actual passed check receipt; preserve all attempts.')
    check = json.loads(checks[0].read_text())
    check_payload = {key: value for key, value in check.items() if key not in ('status', 'updated_at')}
    if (check.get('status') != 'passed' or type(check.get('updated_at')) is not str or not check['updated_at'] or
            json.dumps(check_payload, sort_keys=True) != json.dumps(report, sort_keys=True)):
        raise ValueError('Reader CPU result does not match its passed execution receipt.')
    expected_image = basis.state['model_lock']['runtime_image']
    if (report.get('cuda_initialized') is not False or report.get('descriptor_source_sha256') != delta['reader_helper_sha256'] or
            report.get('reader_adapter_revision') != READER_ADAPTER_REVISION or report.get('descriptor_version') != VERSION or
            report.get('fixture_packet_sha256') != ui.digest(reader_packet) or
            report.get('source_hashes') != packet['source_contracts'] or
            type(report.get('runtime_groups')) is not int or report['runtime_groups'] != len(packet['runtime_groups']) or
            type(report.get('covered_roles')) is not int or report['covered_roles'] != 80 or
            report.get('image_id') != expected_image):
        raise ValueError('Reader CPU no-CUDA/image/source/schema/coverage contract is incomplete.')
    expected_functions = ['vllm.model_executor.utils.replace_parameter',
        'ModelOptNvFp4FusedMoE.get_fused_moe_quant_config', 'make_nvfp4_moe_quant_config',
        'get_humming_moe_quant_config', '_deep_gemm_linear_data',
        '_fused_moe_grouped_gemm_may_use_deep_gemm', '_count_warmup_iterations']
    expected_doubles = ['DeepGEMM env flags forced true', 'ineligible linear-provider/expert classes',
        'unreachable hardware helpers raise AssertionError', 'empty DeepGEMM warmup caches']
    if (report.get('native_functions_executed') != expected_functions or
            report.get('metadata_test_doubles') != expected_doubles):
        raise ValueError('Reader CPU native metadata execution/doubles contract is incomplete.')
    expected_cases = {(group['runtime_signature_sha256'], json.dumps(values)): len(group['covered_roles'])
        for group in packet['runtime_groups'] for values in (None, (0.0, 0.0, 0.0), (0.25, 1.5, 7.0))}
    observed_cases = {}
    for case in report.get('builder_cases', []):
        key = (case['runtime_signature_sha256'], json.dumps(case['swiglu']))
        if key in observed_cases or type(case.get('covered_roles')) is not int or any(case.get(name) is not True for name in
                ('native_ordinary_none_matches', 'real_HummingMoEQuantConfig', 'generic_ModelOpt_callback',
                 'exact_parameter_and_gate_aliases', 'parameters_unchanged')):
            raise ValueError('Reader CPU native state/config/alias/no-transform cases are incomplete or duplicated.')
        flags = case.get('deep_gemm_flags')
        if (type(flags) is not list or len(flags) != 2 or any(value is not True for value in flags) or
                case.get('native_warmup_predicate') is not False or type(case.get('native_warmup_count')) is not int or
                case['native_warmup_count'] != 0 or
                case.get('counterfactual_error') != "'RoutedExperts' object has no attribute 'w13_input_scale'"):
            raise ValueError('Reader CPU must reproduce the missing attribute and pass enabled native warmup selection/count.')
        observed_cases[key] = case['covered_roles']
    if observed_cases != expected_cases:
        raise ValueError('Reader CPU did not cover every actual schema group with all three SwiGLU cases.')
    files = {'reader-cpu-result.json': reader_cpu, 'reader-cpu-packet.json': reader_packet,
        'reader-cpu-program.py': program, 'reader-cpu-intent.json': intent_path, 'reader-cpu-check.json': checks[0]}
    delta.update(actual_image_cpu={name: ui.digest(path) for name, path in files.items()},
        actual_source_hashes=packet['source_contracts'], covered_roles=80,
        writer_overlay_sha256=source_spec['overlay_sha256'])
    return implementation, delta, files


def validate_candidate_cache(path, spec):
    """Read-only validation of optional, entirely in-run cache provenance."""
    path = Path(path)
    cache = spec.get('dev_cache')
    present = set(spec.get('inputs', {})) & set(DEV_CACHE_INPUTS)
    if cache is None:
        if present:
            raise ValueError('Cache inputs require an explicit full development-cache binding.')
        return None
    if (type(cache) is not dict or type(cache.get('schema')) is not int or cache['schema'] != 1 or
            cache.get('candidate_id') != path.name or present != set(DEV_CACHE_INPUTS) or
            set(cache) != {'schema', 'candidate_id', 'qualification_sha256', 'bootstrap_sha256',
                          'receipt_sha256', 'source_sha256'}):
        raise ValueError('Full development-cache metadata or exact optional input set differs.')
    for filename, key in zip(DEV_CACHE_INPUTS, ('qualification_sha256', 'bootstrap_sha256', 'receipt_sha256')):
        if cache[key] != spec['inputs'][filename] or ui.digest(path / filename) != cache[key]:
            raise ValueError('Frozen full development-cache file binding differs: ' + filename)
    sources = {name: ui.digest(source_path(name, root=ROOT)) for name in DEV_CACHE_SOURCES}
    if (cache['source_sha256'] != sources or
            any(spec['source_snapshot'].get(name) != digest for name, digest in sources.items())):
        raise ValueError('Frozen full development-cache implementation source differs.')
    import scripts.development.mx_cache.workflow as dev_cache
    return dev_cache.validate_candidate_cache(
        json.loads((path / 'deployment.json').read_text()), path / DEV_CACHE_INPUTS[0],
        json.loads((path / DEV_CACHE_INPUTS[1]).read_text()),
        json.loads((path / DEV_CACHE_INPUTS[2]).read_text()), candidate_id=path.name)


def freeze(path, source, source_audit=None, reader_cpu=None, reader_packet=None, dev_cache_qualification=None):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError('Use a fresh full Shadow candidate.')
    basis, source_spec, receipts, counts = qualified_basis(source, source_audit)  # No output before real gates pass.
    implementation, delta, cpu_files = reader_delta_inputs(basis, source_spec, reader_cpu, reader_packet)
    namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(path).encode()).hexdigest()[:8] + '-demo'
    labels = {'app.kubernetes.io/managed-by': RUN_OWNER, 'feature-test-run': namespace}
    identity = dict(source_spec['descriptor_identity'], candidate=path.name)
    cm = json.loads((basis.path / 'runtime-overlay.json').read_text())
    cm['data']['workshop_descriptors.py'] = implementation
    overlay_sha256 = hashlib.sha256(json.dumps(cm['data'], sort_keys=True).encode()).hexdigest()
    overlay = 'shadow-descriptors-' + overlay_sha256[:12]
    cm['metadata'] = {'name': overlay, 'namespace': namespace, 'labels': labels}
    graph = render_graph(json.loads((basis.path / 'deployment.json').read_text()), namespace, overlay, identity)
    cache_files = None
    if dev_cache_qualification is not None:
        import scripts.development.mx_cache.workflow as dev_cache
        qualification_path = Path(dev_cache_qualification).resolve()
        qualification_bytes = qualification_path.read_bytes()
        graph, bootstrap, cache_receipt = dev_cache.apply_candidate_cache(
            graph, qualification_path, candidate_id=path.name)
        dev_cache.validate_candidate_cache(graph, qualification_path, bootstrap, cache_receipt, candidate_id=path.name)
        if qualification_path.read_bytes() != qualification_bytes:
            raise ValueError('Development-cache qualification changed during offline rendering.')
        if (bootstrap.get('kind') != 'ConfigMap' or bootstrap['metadata'].get('namespace') != namespace or
                any(bootstrap['metadata'].get('labels', {}).get(key) != value for key, value in labels.items())):
            raise ValueError('Development-cache bootstrap is not scoped to this exact candidate namespace.')
        cache_files = (qualification_bytes, bootstrap, cache_receipt)
    # All writer/reader/cache gates above are read-only; rejected inputs never
    # create a new Run or candidate/config directory.
    run = Run(path)
    run.ns = namespace
    run.state['namespace'] = run.ns
    run.save()
    dc = presenter.device_class(run.ns, UUIDS)
    dc['metadata']['labels'].update(run.labels())
    write(path / 'runtime-overlay.json', cm)
    write(path / 'deployment.json', graph)
    write(path / 'device-class.json', dc)
    if cache_files is not None:
        (path / DEV_CACHE_INPUTS[0]).write_bytes(cache_files[0])
        write(path / DEV_CACHE_INPUTS[1], cache_files[1])
        write(path / DEV_CACHE_INPUTS[2], cache_files[2])
    support.write_yaml(path / 'deployment.yaml', graph)
    config = ROOT / 'configs/dgd/workshop-shadow-composed' / path.name / 'deployment.yaml'
    config.parent.mkdir(parents=True, exist_ok=False)
    config.write_bytes((path / 'deployment.yaml').read_bytes())
    for name, content in cm['data'].items():
        (path / name).write_text(content)
    write(path / 'reader-delta.json', delta)
    for name, source_file in cpu_files.items():
        (path / name).write_bytes(source_file.read_bytes())
    (path / 'source-contract-manifest.json').write_bytes((basis.path / 'source-contract-manifest.json').read_bytes())
    for name in source_spec['runtime_contract_hashes']:
        target = path / 'runtime-contract-sources' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((basis.path / 'runtime-contract-sources' / name).read_bytes())
    receipt_hashes = {}
    for name, source_file in receipts.items():
        target = path / 'writer-basis' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_file.read_bytes())
        receipt_hashes[name] = ui.digest(target)
    support.write_yaml(path / 'shadow-settings.yaml', {
        'experimental': {'gpuMemoryService': {}, 'failover': {}},
        'model': json.loads((basis.path / 'model-lock.json').read_text())['model'],
        'tensor_parallel_size': 2, 'weights': 'one shared committed allocation per rank',
        'engines': 'one active; one initialized and parked standby',
        'runtime': 'experimental Super VL integration; not production-qualified',
        'fault': 'one verified active EngineCore SIGKILL',
        'scope': 'healthy same Pod/GMS/GPUs; fresh coding requests; no in-flight/KV/SLO claim'})
    critical = tuple(source_spec['source_snapshot']) + ('workshop_shadow_composed.py',
        'shadow_failover_tests.py', 'shadow_live_tests.py', 'workshop_demo_support.py',
        'workshop_shadow_follow_policy.py', 'workshop_shadow_descriptors_v5.py',
        'workshop_shadow_reader_delta.py', 'workshop_shadow_reader_cpu_v5.py',
        'workshop_shadow_descriptors_v6.py', 'workshop_shadow_reader_delta_v6.py', 'workshop_shadow_reader_cpu_v6.py')
    if cache_files is not None:
        critical += DEV_CACHE_SOURCES
    snapshot = path / 'source-snapshot'
    snapshot.mkdir()
    for name in critical:
        (snapshot / name).write_bytes((source_path(name, root=ROOT)).read_bytes())
    spec = dict(source_spec, profile=PROFILE, graph=GRAPH, namespace=run.ns,
        descriptor_identity=identity, source_writer_run=str(basis.path),
        source_writer_original_run=str(basis.original_path), source_writer_collected=basis.collected,
        overlay_sha256=overlay_sha256, writer_overlay_sha256=source_spec['overlay_sha256'],
        reader_adapter_revision=READER_ADAPTER_REVISION, reader_delta=delta,
        source_writer_namespace=basis.ns, writer_basis_receipts=receipt_hashes,
        expected_runtime_counts=counts, config_manifest=str(config), config_manifest_sha256=ui.digest(config),
        inputs={p.name: ui.digest(p) for p in path.iterdir() if p.is_file() and p.name not in ('state.json', '.state.lock')},
        source_snapshot={name: ui.digest(snapshot / name) for name in critical}, reader_enabled=True,
        intentional_fault=False, fault_policy='one separately guarded active EngineCore fault after ready + fresh health',
        scope='Experimental full Shadow composition; writer proof is a prerequisite, not reader or recovery proof')
    if cache_files is not None:
        spec['dev_cache'] = {'schema': 1, 'candidate_id': path.name,
            'qualification_sha256': ui.digest(path / DEV_CACHE_INPUTS[0]),
            'bootstrap_sha256': ui.digest(path / DEV_CACHE_INPUTS[1]),
            'receipt_sha256': ui.digest(path / DEV_CACHE_INPUTS[2]),
            'source_sha256': {name: spec['source_snapshot'][name] for name in DEV_CACHE_SOURCES}}
        validate_candidate_cache(path, spec)
    write(path / 'full-spec.json', spec)
    run.state.update(shadow_full_profile=PROFILE, shadow_full_spec_sha256=ui.digest(path / 'full-spec.json'))
    run.save()
    write(path / 'demo.json', {'schema': 2, 'profile': PROFILE, 'shadow_profile': PROFILE,
        'demo_kind': 'shadow', 'rehearsal': False, 'namespace': run.ns, 'graph': GRAPH,
        'model': json.loads((basis.path / 'model-lock.json').read_text())['model'],
        'created_at': ui.now(), 'step': 0, 'prepared': False, 'pod_selector': 'workshop-demo=shadow',
        'resource_kinds': 'dgd', 'resource_note': 'Experimental shared weights / active + parked reader / TP2',
        'log_files': ['engine-0.log', 'engine-1.log', 'gms-server.log']})
    print(json.dumps({'run': str(path), 'namespace': run.ns, 'writer_basis': str(basis.path),
        'expected_runtime_counts': counts, 'scope': spec['scope'], 'live_actions': False}, indent=2))


def load(path):
    run = Run(Path(path).resolve())
    spec = json.loads((run.path / 'full-spec.json').read_text())
    if (spec['profile'] != PROFILE or run.state.get('shadow_full_profile') != PROFILE or
            spec['namespace'] != run.ns or ui.digest(run.path / 'full-spec.json') != run.state['shadow_full_spec_sha256']):
        raise ValueError('Full Shadow candidate identity changed.')
    for name, digest in spec['inputs'].items():
        if ui.digest(run.path / name) != digest:
            raise ValueError('Frozen full Shadow input changed: ' + name)
    for name, digest in spec['source_snapshot'].items():
        if ui.digest(source_path(name, root=ROOT)) != digest:
            raise ValueError('Frozen full Shadow implementation changed: ' + name)
    for name, digest in spec['runtime_contract_hashes'].items():
        if ui.digest(run.path / 'runtime-contract-sources' / name) != digest:
            raise ValueError('Frozen full runtime contract changed: ' + name)
    for name, digest in spec['writer_basis_receipts'].items():
        if ui.digest(run.path / 'writer-basis' / name) != digest:
            raise ValueError('Frozen writer qualification evidence changed: ' + name)
    if ui.digest(ui.MODEL_LOCK) != spec['model_lock_sha256'] or ui.digest(Path(spec['config_manifest'])) != spec['config_manifest_sha256']:
        raise ValueError('Pinned model or full executable manifest changed.')
    validate_candidate_cache(run.path, spec)
    return run, spec


def validate_ready_observation(expected, actual):
    if expected['pod_uid'] != actual['pod_uid'] or expected['states'] != actual['states']:
        raise ValueError('Ready active/standby Pod or roles changed before the fault.')
    for name in ('engine-0', 'engine-1', 'gms-server'):
        for key in ('containerID', 'restartCount'):
            if expected['container_statuses'][name][key] != actual['container_statuses'][name][key]:
                raise ValueError('Ready engine/GMS generation changed before the fault.')
    for name, value in expected['gms'].items():
        if name.endswith('_weights.sock'):
            current = actual['gms'].get(name, {})
            if (value['state']['memory_layout_hash'] != current.get('state', {}).get('memory_layout_hash') or
                    value['events'] != current.get('events')):
                raise ValueError('Ready committed weight generation changed before the fault.')


def startup_probes_ready(observation):
    """Kubelet startup/readiness progress is health, not container identity."""
    statuses = observation.get('container_statuses', {})
    for name in ('engine-0', 'engine-1', 'gms-server'):
        status = statuses.get(name, {})
        if (status.get('ready') is not True or status.get('started') is not True or
                type(status.get('containerID')) is not str or not status['containerID'] or
                type(status.get('restartCount')) is not int or status['restartCount'] != 0 or
                type(status.get('state')) is not dict or
                type(status['state'].get('running')) is not dict):
            return False
    return True


def validate_startup_observation(expected, actual):
    """Require healthy probes and stable generations plus every GMS field."""
    if not startup_probes_ready(expected) or not startup_probes_ready(actual):
        raise ValueError('Initial coding requires healthy Ready/Started engine and GMS startup probes.')
    if sorted(expected['states'].values()) != ['active', 'standby']:
        raise ValueError('Initial coding requires one active engine and one parked reader.')
    validate_ready_observation(expected, actual)  # Stable Pod/roles/container IDs/restarts; weight contracts.
    if json.dumps(expected['gms'], sort_keys=True) != json.dumps(actual['gms'], sort_keys=True):
        raise ValueError('Full GMS state, layout or events changed during initial coding.')


def validate_boundary_pod(expected, pod):
    if pod['metadata']['uid'] != expected['pod_uid']:
        raise ValueError('Ready Pod changed at the mutation boundary.')
    statuses = {c['name']: c for c in pod['status'].get('containerStatuses', []) +
                pod['status'].get('initContainerStatuses', [])}
    for name in ('engine-0', 'engine-1', 'gms-server'):
        for key in ('containerID', 'restartCount'):
            if statuses.get(name, {}).get(key) != expected['container_statuses'][name][key]:
                raise ValueError('Ready engine/GMS generation changed at the mutation boundary.')


class ComposedShadowDemo(presenter.ShadowDemo):
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        self.args = args
        self.run, self.spec = load(args.run)
        self.path, self.ns = self.run.path, self.run.ns
        self.file = self.path / 'demo.json'
        self.data = json.loads(self.file.read_text())
        if self.data['profile'] != PROFILE or args.rehearsal:
            raise ValueError('This source-frozen composition requires actual live evidence; use the original demo for rehearsal.')
        self.lease = ROOT / '.local' / (self.ns + '-shadow.gpu-lease')
        self.forward, self.compact_output = None, True
        if self.data.get('cleaned_at') and args.action not in ('preview', 'cleanup'):
            raise ValueError('This full Shadow candidate was cleaned; use a fresh candidate.')

    def check_inputs(self):
        load(self.path)

    def cache_binding(self):
        if validate_candidate_cache(self.path, self.spec) is None:
            return None
        return tuple(json.loads((self.path / name).read_text()) for name in DEV_CACHE_INPUTS)

    def cache_producer(self, phase):
        binding = self.cache_binding()
        if binding is None:
            return None
        import scripts.development.mx_cache.workflow as dev_cache
        qualification = binding[0]
        producer = qualification['producer']
        output = self.path / ('dev-cache-producer-' + phase + '.json')
        if output.exists():
            raise ValueError('Development-cache producer gate already attempted; preserve it and use a fresh candidate.')
        pod = self.run.get('get', 'pod', producer['name'], '-n', producer['namespace'])
        write(output, pod)  # Preserve the actual source generation even when validation fails.
        return dev_cache.validate_producer_snapshot(qualification, pod)

    def cache_bootstrap(self, delete=False, require_existing=False):
        binding = self.cache_binding()
        if binding is None:
            return
        expected = binding[1]
        name = expected['metadata']['name']
        found = self.run.k('get', 'configmap', name, '-n', self.ns, '-o', 'json', check=False)
        if found.returncode:
            if 'NotFound' not in found.stderr:
                raise RuntimeError(found.stderr)
            if delete:
                return
            if require_existing:
                raise ValueError('Prepared development-cache bootstrap ConfigMap disappeared.')
        else:
            current = json.loads(found.stdout)
            if (current['metadata'].get('namespace') != self.ns or
                    any(current['metadata'].get('labels', {}).get(key) != value
                        for key, value in expected['metadata']['labels'].items()) or
                    current.get('data') != expected['data'] or
                    (expected.get('immutable') is True and current.get('immutable') is not True) or
                    (self.run.state.get('shadow_dev_cache_bootstrap_uid') is not None and
                     current['metadata']['uid'] != self.run.state['shadow_dev_cache_bootstrap_uid'])):
                raise ValueError('Refusing changed or foreign development-cache bootstrap ConfigMap.')
            if delete:
                self.run.k('delete', 'configmap', name, '-n', self.ns, '--wait=true', '--timeout=60s')
                return
            if require_existing:
                return
        if not delete:
            self.run.apply([copy.deepcopy(expected)])
            current = self.run.get('get', 'configmap', name, '-n', self.ns)
            if (current.get('data') != expected['data'] or
                    current['metadata'].get('labels', {}).get('feature-test-run') != self.ns or
                    (expected.get('immutable') is True and current.get('immutable') is not True)):
                raise ValueError('Applied development-cache bootstrap differs from frozen data.')
            self.run.state['shadow_dev_cache_bootstrap_uid'] = current['metadata']['uid']
            self.run.save()

    def collect_cache_stage(self, pod):
        binding = self.cache_binding()
        if binding is None:
            return True
        import scripts.development.mx_cache.workflow as dev_cache
        existing = self.run.state['checks'].get('shadow-full-dev-cache-stage', {})
        if existing.get('status') == 'passed':
            if existing.get('pod_uid') != pod['metadata']['uid']:
                raise ValueError('Completed development cache belongs to a different worker Pod.')
            return True
        status = next((s for s in pod['status'].get('initContainerStatuses', [])
                       if s['name'] == 'mx-dev-cache-stage'), None)
        if status is None or 'terminated' not in status.get('state', {}):
            return False
        raw = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'mx-dev-cache-stage',
                         timeout=120, check=False)
        log = self.path / 'dev-cache-init.log'
        if log.exists():
            raise ValueError('Development-cache init collection was already attempted; preserve its evidence.')
        log.write_text(raw.stdout + (('\n' + raw.stderr) if raw.stderr else ''))
        write(self.path / 'dev-cache-init-container.json', {'pod': pod, 'status': status})
        expected_image = self.run.state['model_lock']['runtime_image']
        image = next(c['image'] for c in pod['spec']['initContainers'] if c['name'] == 'mx-dev-cache-stage')
        exit_code = status['state']['terminated'].get('exitCode')
        restart_count = status.get('restartCount')
        if (raw.returncode or type(exit_code) is not int or exit_code != 0 or
                type(restart_count) is not int or restart_count != 0 or
                not status.get('containerID') or image != expected_image or
                not dev_cache.exact_image_id(status.get('imageID'), expected_image)):
            raise ValueError('Development-cache init did not complete once in the exact runtime image.')
        lines = [line.removeprefix('MX_DEV_CACHE_STAGE=') for line in raw.stdout.splitlines()
                 if line.startswith('MX_DEV_CACHE_STAGE=')]
        if len(lines) != 1:
            raise ValueError('Development-cache init requires exactly one complete all-file staging receipt.')
        receipt = json.loads(lines[0])
        write(self.path / 'dev-cache-stage-result.json', receipt)
        dev_cache.validate_stage_receipt(receipt, binding[2])
        if receipt.get('hf_home') != binding[2]['hf_home']:
            raise ValueError('Development cache was staged outside the exact worker HF_HOME mount.')
        producer = self.cache_producer('after-stage')
        self.run.result('shadow-full-dev-cache-stage', 'passed', pod_uid=pod['metadata']['uid'],
            container_id=status['containerID'], image_id=status['imageID'],
            receipt_sha256=ui.digest(self.path / 'dev-cache-stage-result.json'),
            log_sha256=ui.digest(log), source_producer=producer,
            scope='All model files hash-verified in worker-local RAM before engine startup; CPU file cache only')
        return True

    def cache_failure_logs(self):
        if self.cache_binding() is None:
            return
        pods = self.run.get('get', 'pods', '-n', self.ns)['items']
        workers = [p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'worker']
        if len(workers) != 1:
            return
        raw = self.run.k('logs', workers[0]['metadata']['name'], '-n', self.ns, '-c', 'mx-dev-cache-stage',
                         timeout=120, check=False)
        (self.path / 'startup-dev-cache-init.log').write_text(raw.stdout + '\n' + raw.stderr)

    def prepare(self):
        self.check_inputs()
        self.acquire()
        writer.prepare(self.run, self.spec)
        self.cache_bootstrap()
        self.data['prepared'] = True
        self.save()

    def deploy(self):
        self.check_inputs()
        self.source_released()

        if self.run.state['checks'].get('shadow-writer-cuda', {}).get('status') != 'passed':
            raise ValueError('Fresh exact-pair CUDA probe is required before full startup.')
        health = writer.health_copy(self.run, self.args.health_before, 'health-before.json')
        if health['observed_at'] < self.run.state['checks']['shadow-writer-cuda']['updated_at']:
            raise ValueError('Full-startup health predates the exact-pair CUDA probe.')
        if (self.path / 'full-gpu-intent.json').exists():
            raise ValueError('Full GPU startup was already attempted; use wait or a fresh candidate.')
        if self.run.get('get', 'pods', '-n', self.ns)['items'] or self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
            raise ValueError('Unexpected existing workload or GPU claims in full candidate namespace.')
        self.acquire()
        self.cache_bootstrap(require_existing=True)
        self.cache_producer('before-deploy')
        write(self.path / 'full-gpu-intent.json', {'at': ui.now(), 'node': NODE, 'gpu_uuids': UUIDS})
        self.data['apply_started_at'] = ui.now()
        self.save()
        self.run.state.setdefault('graphs', {})['shadow'] = {'name': GRAPH}
        self.run.save()
        self.run.apply([json.loads((self.path / 'deployment.json').read_text())])
        graph = self.run.get('get', 'dgd', GRAPH, '-n', self.ns)
        self.run.state['shadow_full_dgd_uid'] = graph['metadata']['uid']
        self.run.state['shadow_full_dgd_generation'] = graph['metadata']['generation']
        self.run.state['shadow_full_dgd_spec_sha256'] = hashlib.sha256(json.dumps(graph['spec'], sort_keys=True).encode()).hexdigest()
        write(self.path / 'full-applied-dgd.json', graph)
        self.run.save()

    def assert_graph(self):
        graph = self.run.get('get', 'dgd', GRAPH, '-n', self.ns)
        if (graph['metadata']['uid'] != self.run.state.get('shadow_full_dgd_uid') or
                graph['metadata'].get('labels', {}).get('feature-test-run') != self.ns or
                graph['metadata']['generation'] != self.run.state.get('shadow_full_dgd_generation') or
                hashlib.sha256(json.dumps(graph['spec'], sort_keys=True).encode()).hexdigest() !=
                self.run.state.get('shadow_full_dgd_spec_sha256')):
            raise ValueError('Frozen full DGD identity, generation or serving spec changed.')
        return graph

    def source_released(self):
        source_path = self.path / 'writer-basis' / 'state.json'
        if ui.digest(source_path) != self.spec['writer_basis_receipts']['state.json']:
            raise ValueError('Frozen writer cleanup proof changed.')
        source = json.loads(source_path.read_text())
        if (source['namespace'] != self.spec['source_writer_namespace'] or
                source['checks'].get('shadow-writer-cleanup', {}).get('status') != 'passed'):
            raise ValueError('The qualified source writer must be cleaned before full GPU startup.')
        for kind in ('pods', 'resourceclaims'):
            if self.run.get('get', kind, '-n', source['namespace'])['items']:
                raise ValueError('Source writer still owns live Pods or GPU claims.')

    def probe(self):
        self.source_released()
        writer.probe(self.run, self.spec)

    def stop(self):
        found = self.run.k('get', 'dgd', GRAPH, '-n', self.ns, '-o', 'json', check=False)
        if found.returncode:
            if 'NotFound' not in found.stderr: raise RuntimeError(found.stderr)
            return
        graph = json.loads(found.stdout)
        if (graph['metadata'].get('labels', {}).get('feature-test-run') != self.ns or
                graph['metadata']['uid'] != self.run.state.get('shadow_full_dgd_uid')):
            raise ValueError('Refusing to stop a foreign/replaced full Shadow graph.')
        self.run.k('delete', 'dgd', GRAPH, '-n', self.ns, '--wait=true', '--timeout=120s', timeout=135)

    def wait(self):
        with continuous_logs(self.run):
            return self.wait_verified()

    def wait_verified(self):
        from demos.snapshot.dgd import coding_request
        from serving_tests import frontend
        if not self.run.state.get('shadow_full_dgd_uid'):
            raise ValueError('Deploy the frozen full graph before waiting for startup.')
        if (self.path / 'shadow-fault-intent.json').exists():
            raise ValueError('A fault was already attempted; startup qualification cannot be reused.')
        deadline, pod_uid = time.monotonic() + self.args.timeout, None
        try:
            while time.monotonic() < deadline:
                self.assert_graph()
                pods = self.run.get('get', 'pods', '-n', self.ns)['items']
                workers = [p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'worker']
                if workers:
                    if len(workers) != 1: raise RuntimeError('Unexpected full Shadow worker count.')
                    pod = workers[0]
                    if pod_uid is not None and pod['metadata']['uid'] != pod_uid:
                        raise RuntimeError('Full Shadow Pod was replaced during startup.')
                    pod_uid = pod['metadata']['uid']
                    statuses = pod['status'].get('containerStatuses', []) + pod['status'].get('initContainerStatuses', [])
                    if any(s.get('restartCount', 0) for s in statuses):
                        raise RuntimeError('Full Shadow container restarted before qualification.')
                    if any(s.get('imageID') and not s['imageID'].endswith(self.run.state['model_lock']['runtime_image'].split('@')[-1])
                           for s in statuses if s['name'] in ('engine-0', 'engine-1', 'gms-server')):
                        raise RuntimeError('Full Shadow runtime image changed.')
                    cache_staged = self.collect_cache_stage(pod)
                    if not cache_staged:
                        print('Waiting for hash-verified worker-local model cache.', flush=True)
                        time.sleep(5)
                        continue
                    self.logs()
                    text = '\n'.join((self.path / name).read_text() for name in ('engine-0.log', 'engine-1.log') if (self.path / name).exists())
                    if any(s in text for s in ('CUDA_ERROR_ILLEGAL_ADDRESS', 'an illegal memory access was encountered',
                            'Shape/dtype mismatch for', 'Engine core initialization failed', 'WorkerProc initialization failed')):
                        raise RuntimeError('Fatal full Shadow initialization; stopping the owned graph.')
                    try:
                        snapshot = presenter.control.snapshot(self.run)
                    except (RuntimeError, KeyError, StopIteration, ValueError):
                        snapshot = None
                    if snapshot and sorted(snapshot['states'].values()) == ['active', 'standby']:
                        if not cache_staged:
                            raise ValueError('Active/parked engines appeared without a verified local cache stage.')
                        presenter.validate_pair(snapshot, UUIDS)
                        if not startup_probes_ready(snapshot):
                            print('Waiting for engine and GMS startup probes to settle.', flush=True)
                            time.sleep(5)
                            continue
                        break
                print('Waiting for one active engine and one parked reader.', flush=True)
                time.sleep(5)
            else:
                raise TimeoutError('No active and parked reader within the bounded startup wait.')
            write(self.path / 'full-ready-before.json', snapshot)
            responses = []
            with frontend(self.run, 'shadow') as base:
                for index in range(3):
                    response = coding_request(base, self.data['model'])
                    write(self.path / ('full-ready-coding-' + str(index + 1) + '.json'), response)
                    responses.append(response)
                    write(self.path / 'full-ready-coding.json', responses)
            after = presenter.control.snapshot(self.run)
            write(self.path / 'full-ready-after.json', after)
            self.assert_graph()
            presenter.validate_pair(after, UUIDS)
            validate_startup_observation(snapshot, after)
            self.run.result('shadow-full-ready', 'passed', dgd_uid=self.run.state['shadow_full_dgd_uid'],
                pod_uid=after['pod_uid'], states=after['states'],
                responses=3, scope='Actual active + parked reader and correct fresh coding; no fault/recovery qualification yet')
            self.data['ready_observed_at'] = ui.now()
            self.save()
        except Exception as error:
            self.run.result('shadow-full-ready', 'failed', error=str(error), fault_injected=False)
            for action, name in ((lambda: collect_previous(self.run), 'previous-logs'),
                                 (self.logs, 'logs'), (self.cache_failure_logs, 'cache-logs'), (self.stop, 'stop')):
                try:
                    action()
                except Exception as diagnostic:
                    write(self.path / ('startup-' + name + '-error.json'), {'primary': str(error), 'diagnostic': str(diagnostic)})
            raise

    def health_after(self, path, filename, after_time):
        from r610_retest_audit import new_xids
        if path is None:
            raise ValueError('Supply a fresh node-health receipt with --health-after.')
        receipt = writer.health_copy(self.run, path, filename)
        before = json.loads((self.path / 'health-before.json').read_text())
        after = json.loads((self.path / filename).read_text())
        if (receipt['observed_at'] < after_time or new_xids(before['xids'], after['xids']) or
                receipt['driver_pod_uid'] != before['receipt']['driver_pod_uid'] or
                receipt['node_status']['nodeInfo']['bootID'] != before['receipt']['node_status']['nodeInfo']['bootID']):
            raise ValueError('New GPU errors or full-candidate health identity/timing mismatch.')

    def failover(self):
        ready = self.run.state['checks'].get('shadow-full-ready', {})
        if ready.get('status') != 'passed':
            raise ValueError('Actual active/parked reader and coding must pass before any fault.')
        source = self.args.health_after or self.data.get('pre_fault_health_source')
        self.health_after(source, 'health-before-fault.json', ready['updated_at'])
        expected = json.loads((self.path / 'full-ready-after.json').read_text())
        original = presenter.control.snapshot
        original_write, original_exec = presenter.control.write, presenter.control.exec_probe
        def checked(run):
            self.assert_graph()
            observed = original(run)
            if not (self.path / 'shadow-fault-intent.json').exists():
                validate_ready_observation(expected, observed)
            return observed
        def checked_write(run, name, value):
            if name == 'shadow-fault-intent.json':
                # Full CUDA/GMS observations stay outside the measured interval.
                self.assert_graph()
                validate_ready_observation(expected, original(run))
            return original_write(run, name, value)
        def checked_exec(run, pod, container, mode, *args, **kwargs):
            if mode == 'kill':
                # Only lightweight API reads at the final mutation boundary.
                self.assert_graph()
                validate_boundary_pod(expected, presenter.control.owned_pod(run))
            return original_exec(run, pod, container, mode, *args, **kwargs)
        presenter.control.snapshot = checked
        presenter.control.write, presenter.control.exec_probe = checked_write, checked_exec
        try:
            super().failover()  # Existing PID/container/lock/one-fault and replenishment guards.
        finally:
            presenter.control.snapshot = original
            presenter.control.write, presenter.control.exec_probe = original_write, original_exec
        proof = json.loads((self.path / 'recovery-proof.json').read_text())
        proof['timing_scope'] = 'Includes final lightweight DGD/container identity reads, kubectl kill command and request polling; no extra CUDA-context probes in the timed kill boundary.'
        write(self.path / 'recovery-proof.json', proof)

    def finalize(self):
        proof = self.run.state['checks'].get('shadow-failover', {})
        if proof.get('status') != 'passed':
            raise ValueError('Full promotion/replenishment proof is required before final qualification.')
        self.health_after(self.args.health_after, 'health-after.json', proof['updated_at'])
        self.run.result('shadow-full-qualification', 'passed', scope='Experimental same-Pod Shadow promotion, fresh coding, replenishment and no new Xids; no KV/stream/SLO/node-failure claim')

    def cleanup(self):
        self.stop()
        if self.spec.get('dev_cache') is not None:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if (not self.run.get('get', 'pods', '-n', self.ns)['items'] and
                        not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']):
                    break
                time.sleep(3)
            else:
                raise RuntimeError('Owned cache workloads/claims remain; bootstrap and reservation retained.')
            self.cache_bootstrap(delete=True)
        super().cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run', choices=('freeze', 'prepare', 'probe', 'deploy', 'wait', 'prime',
        'verify', 'finalize', 'cleanup', 'run', 'preview', 'observe', 'hold'))
    parser.add_argument('--run', type=Path)
    parser.add_argument('--source-writer', type=Path)
    parser.add_argument('--source-audit', type=Path, help='Separate root acceptance bound to verified collected writer bytes')
    parser.add_argument('--reader-cpu', type=Path, help='Passed actual-image reader-only CPU result.json')
    parser.add_argument('--reader-packet', type=Path, help='Exact actual writer-derived reader CPU fixtures.json')
    parser.add_argument('--dev-cache-qualification', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--health-before', type=Path)
    parser.add_argument('--health-after', type=Path)
    parser.add_argument('--timeout', type=int, default=1500)
    parser.add_argument('--port', type=int, default=18008)
    parser.add_argument('--view', choices=('resources', 'logs'), default='resources')
    for flag in ('plain', 'auto', 'detach', 'rehearsal', 'once', 'preview'):
        parser.add_argument('--' + flag, action='store_true',
                            help=argparse.SUPPRESS if flag == 'rehearsal' else None)
    args = parser.parse_args()
    if args.rehearsal:
        parser.error('Composed Shadow requires qualified live inputs; use python -m demos shadow --rehearsal offline.')
    if args.action == 'hold':
        while True: time.sleep(60)
    if not args.run: parser.error('--run is required')
    if args.action == 'freeze':
        if not args.source_writer: parser.error('freeze requires --source-writer')
        freeze(args.run, args.source_writer, args.source_audit, args.reader_cpu, args.reader_packet,
               args.dev_cache_qualification)
        return
    if args.action == 'observe':
        support.observe(args.run.resolve(), args.view, args.once)
        return
    demo = ComposedShadowDemo(args)
    if args.action == 'run':
        demo.require_primed()
    if args.action == 'run' and args.health_after:
        demo.data['pre_fault_health_source'] = str(args.health_after.resolve())
        demo.save()  # The tmux child inherits this checked source path through demo.json.
    if args.preview or args.action == 'preview':
        demo.preview()
    elif args.action == 'run' and not args.plain:
        ui.tmux_layout(demo)
    else:
        with ui.presenter_lock(demo.path):
            if args.action == 'probe': demo.probe()
            elif args.action == 'prime':
                demo.deploy()
                demo.wait()
            elif args.action == 'verify': demo.failover()
            elif args.action == 'run': demo.guided()
            else: getattr(demo, args.action)()


if __name__ == '__main__': main()
