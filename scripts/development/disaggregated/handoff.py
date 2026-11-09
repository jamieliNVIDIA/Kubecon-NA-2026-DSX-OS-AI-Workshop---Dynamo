#!/usr/bin/env python3
"""Fresh matched P/D campaign with an explicitly handed-off qualified CPU client.

The expired disagg a1 is never resumed or relabeled. This separate campaign
reuses verified routing CPU data and its live client by recorded handoff; GPU
workers/graphs, CLI benchmark namespaces, profiles and results are fresh.
Cleanup retains the borrowed CPU, PVC, namespace and all earlier artifacts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import scripts.development.disaggregated.benchmark as b

ROOT = b.ROOT
ORIGINAL = ROOT / 'results/workshop-disagg-agentx-20261105-a1'
PROBE = ROOT / 'results/workshop-disagg-client-handoff-probe-20261105-a1'
HANDOFF = ROOT / 'reports/receipts/2026-11-05-routing-cpu-handoff-disagg.json'
SOURCE_NAMESPACE = 'dynamo-ft-routing-overnight-20261105-a1'
SOURCE_UID = '4385c581-2c2c-446a-8f7d-123617386cf8'
ARM_NAMES = {role: 'disagg-a2-' + role + '-c16-a1' for role in b.ARMS}


def setup(path):
    b.NAMESPACE = SOURCE_NAMESPACE
    return b.setup(path)


def validate_handoff(probe, qualification, handoff):
    if (qualification.get('passed') is not True or qualification.get('active_benchmark_processes') or
            qualification.get('source_pod_uid') != SOURCE_UID or probe.get('uid') != SOURCE_UID or
            probe.get('namespace') != SOURCE_NAMESPACE or qualification.get('source_namespace') != SOURCE_NAMESPACE):
        raise ValueError('Qualified source CPU probe is missing, changed or busy.')
    # The source workstream must explicitly acknowledge this exact client.
    client = handoff.get('client', {})
    if (client.get('uid') != SOURCE_UID or client.get('namespace') != SOURCE_NAMESPACE or
            client.get('node') != probe.get('node')):
        raise ValueError('Source-workstream handoff does not identify the exact CPU client.')
    if (handoff.get('status') != 'exclusive_cpu_client_use_handed_off' or
            handoff.get('live_executor') != '/root' or
            handoff.get('to_agent') != '/root/disagg_comparison' or
            handoff.get('old_routing_controller', {}).get('retired_for_future_execution') is not True):
        raise ValueError('Source-workstream CPU handoff is not acknowledged.')
    if not qualification.get('files') or qualification.get('pinned_source_members_verified', 0) < 1:
        raise ValueError('Full source/data/cache verification is missing.')


def handoff_manifest(run, topology):
    value = b.manifest(run, topology)
    names = {}
    for obj in value['items']:
        if obj['kind'] == 'ResourceClaimTemplate':
            name = obj['metadata']['name']
            names[name] = 'disagg-a2-' + name
            obj['metadata']['name'] = names[name]
    for obj in value['items']:
        if obj['kind'] == 'DynamoGraphDeployment':
            for component in obj['spec']['components']:
                for claim in component['podTemplate']['spec'].get('resourceClaims', []):
                    claim['resourceClaimTemplateName'] = names[claim['resourceClaimTemplateName']]
    return value


def freeze(run):
    if (run.path / 'campaign.json').exists():
        raise ValueError('Fresh campaign only; never refreeze.')
    old = SimpleNamespace(path=ORIGINAL, state=json.loads((ORIGINAL / 'state.json').read_text()))
    b.verify(old)
    probe = json.loads((PROBE / 'probe-spec.json').read_text())
    qualification = json.loads((PROBE / 'qualification.json').read_text())
    handoff = json.loads(HANDOFF.read_text())
    validate_handoff(probe, qualification, handoff)
    if (handoff['root_probe']['qualification_sha256'] != b.sha(PROBE / 'qualification.json') or
            handoff['source_campaign_sha256'] != probe['source_campaign_sha256'] or
            handoff['root_probe']['source_preparation_receipt_sha256'] != probe['source_receipt_sha256']):
        raise ValueError('Source handoff and root probe do not share exact provenance.')
    prior = json.loads((ORIGINAL / 'campaign.json').read_text())
    if prior['model_lock'] != run.state['model_lock']:
        raise ValueError('Model/runtime controls changed.')
    for name in ('expected-probes.json', 'profile.yaml'):
        (run.path / name).write_bytes((ORIGINAL / name).read_bytes())
    binding = {'namespace': SOURCE_NAMESPACE, 'pod': 'rr-loadgen', 'pod_uid': SOURCE_UID,
        'node': probe['node'], 'image': probe['runtime_image'],
        'source_campaign_sha256': probe['source_campaign_sha256'],
        'source_receipt_sha256': probe['source_receipt_sha256'], 'cache_key': probe['cache_key'],
        'verified_files': qualification['files'], 'probe_sha256': b.sha(PROBE / 'qualification.json'),
        'handoff_sha256': b.sha(HANDOFF), 'retained_on_cleanup': True}
    value = {**prior, 'namespace': run.ns, 'client_binding': binding, 'arm_names': ARM_NAMES,
        'original_failed_attempt': str(ORIGINAL.relative_to(ROOT)),
        'parameter_authorization': 'Root explicitly approved fresh campaign with handed-off qualified routing CPU client after user resumed original work; all locked model/runtime/GPU/load/trace/phase controls retained.',
        'cpu_data_reconstructed': False, 'client_identity_reused_by_explicit_handoff': True,
        'cache_history': 'Fresh GPU engines/private compiler caches for each topology; fresh CLI/cache-bust namespace and unchanged canonical AgentX primers. CPU mmap data reused from hash-qualified handed-off client.',
        'execution_entrypoint': str(Path(__file__).relative_to(ROOT)), 'execution_entrypoint_sha256': b.sha(__file__),
        'gpu_cleanup_scope': 'Only fresh ft-agg graph and its children/claims; retain borrowed CPU/PVC/namespace/previous archives'}
    b.write(run.path / 'campaign.json', value)
    b.write(run.path / 'client-binding.json', binding)
    for topology in b.ARMS:
        b.write(run.path / ('deployment-' + topology + '.json'), handoff_manifest(run, topology))
    paths = [ROOT / name for name in json.loads((ORIGINAL / 'inputs-sha256.json').read_text())]
    paths += [Path(__file__), ROOT / 'scripts/development/disaggregated/controller.py',
              ROOT / 'scripts/development/disaggregated/probe_client.py', HANDOFF]
    paths += [PROBE / name for name in ('probe-spec.json', 'qualification.json', 'source-pod.json')]
    paths += [p for p in run.path.iterdir() if p.is_file() and p.name not in ('state.json', '.state.lock')]
    b.write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): b.sha(p) for p in paths})
    (run.path / 'campaign.sha256').write_text(b.sha(run.path / 'campaign.json') + '\n')
    b.verify(run)
    b.status(run, 'Fresh campaign frozen with explicit qualified CPU handoff; no new GPU resources')


def check_client(run):
    binding = b.spec(run)['client_binding']
    pod = run.get('get', 'pod', binding['pod'], '-n', binding['namespace'])
    if (pod['metadata']['uid'] != binding['pod_uid'] or pod['spec']['nodeName'] != binding['node'] or
            pod['metadata']['labels'].get('feature-test-run') != binding['namespace'] or
            pod['status'].get('phase') != 'Running' or
            any(v.get('restartCount', 0) or not v.get('ready') or
                not v['imageID'].endswith(binding['image'].split('@')[1])
                for v in pod['status']['containerStatuses'])):
        raise ValueError('Explicitly handed-off CPU client changed or expired.')
    return pod


def prepare(run):
    b.verify(run)
    if run.state['checks'].get('disagg-cpu-qualified'):
        raise ValueError('Do not repeat this CPU binding qualification.')
    check_client(run)
    namespace = run.get('get', 'namespace', run.ns)
    if namespace['metadata']['labels'].get('app.kubernetes.io/managed-by') != run.state['owner']:
        raise ValueError('Borrowed namespace is not owned.')
    if run.get('get', 'dgd', '-n', run.ns)['items'] or run.get('get', 'resourceclaims', '-n', run.ns)['items']:
        raise ValueError('Borrowed namespace GPU resources are not empty.')
    program = '''from pathlib import Path
import json,sys
for arm in json.loads(sys.argv[1]):
 assert not (Path('/tmp/workshop-rr/runs')/arm).exists(),'Fresh handed-off-client arm already exists: '+arm
print('Fresh remote arm paths are absent.')
'''
    b.e.client(run, program, argv=(json.dumps(list(ARM_NAMES.values())),))
    for topology in b.ARMS:
        for mode in ('client', 'server'):
            run.k('apply', '--dry-run=' + mode, '-f', str(run.path / ('deployment-' + topology + '.json')))
    from common_runtime_tests import efa
    efa(run)
    remote_profile = '/tmp/workshop-rr/preparation/disagg-handoff-a2-profile.yaml'
    b.e.upload(run, run.path / 'profile.yaml', remote_profile)
    remote_receipt = '/tmp/workshop-rr/preparation/receipt-disagg-handoff-a2.json'
    program = '''import os,subprocess,sys
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
subprocess.run([sys.executable,'/tmp/workshop-rr/preparation/prepare_agentx_cache.py','--config',sys.argv[1],'--receipt',sys.argv[2],'--check-cache-only'],env=env,check=True)
'''
    result = b.e.client(run, program, argv=(remote_profile, remote_receipt), timeout=900)
    (run.path / 'cpu-cache-only.log').write_text(result.stdout + result.stderr)
    folder = run.path / 'cpu-cache-qualification'
    folder.mkdir(exist_ok=False)
    receipt = b.c.qualify_client.fetch_receipt(run, folder, 'disagg-handoff-a2')
    from scripts.development.disaggregated.recover_client import validate
    validate(receipt, b.sha(run.path / 'profile.yaml'),
             b.sha(ROOT / 'reports/workshop-measurements-20261030/agentx-workload/prepare_agentx_cache.py'), 'cache_verified')
    original_receipt = json.loads((b.ROOT / 'results/workshop-routing-overnight-collection-recovered-20261105-0739/verified/results/workshop-routing-overnight-20261105-a1/cpu-qualification-a1/receipt-c1.json').read_text())
    if (receipt.get('initial_cache_hit') is not True or receipt['cache_key'] != b.spec(run)['client_binding']['cache_key'] or
            receipt['cache_files'] != original_receipt['cache_files']):
        raise ValueError('Fresh profile does not reuse the exact handed-off qualified full cache.')
    run.result('disagg-cpu-qualified', 'passed', source_pod_uid=SOURCE_UID, data_reconstructed=False,
               scope='New campaign/profile cache-only verification through explicit CPU-client handoff; no inference yet')


def execute(run, topology):
    b.verify(run)
    check_client(run)
    if run.state['checks'].get('disagg-cpu-qualified', {}).get('status') != 'passed':
        raise ValueError('Fresh CPU binding/profile qualification is required.')
    arm = b.spec(run)['arm_names'][topology]
    folder = run.path / arm
    folder.mkdir(exist_ok=False)
    b.write(folder / 'intent.json', {'at': b.e.now(), 'topology': topology, 'client_uid': SOURCE_UID})
    b.e.acquire(run, 0)
    try:
        b.c.allocation_available(run, arm)
        b.write(b.LEASE / 'allocation.json', {'gpu_uuids_by_node': b.GPUS, 'namespace': run.ns,
                                            'run': str(run.path), 'owner': b.OWNER})
        run.apply(json.loads((run.path / ('deployment-' + topology + '.json')).read_text())['items'])
        b.status(run, 'Starting fresh handed-off-client ' + topology, arm=arm)
        pods = b.e.wait_serving(run, 2, arm)
        b.e.collect_workers(run, arm)
        b.qualify_workers(run, topology, pods, arm)
        base = b.e.endpoint(run)
        b.e.smoke(run, base, 2, arm, require_distribution=topology == 'aggregate')
        b.seal_profile(run, topology, arm, pods, base)
        b.e.collect_frontend_metrics(run, base, arm, 'before')
        b.e.telemetry_start(run, pods, arm)
        try:
            b.e.launch_profile(run, arm)
            outcome = b.e.poll_profile(run, arm)
        finally:
            b.e.telemetry_stop(run, arm)
        b.e.collect_workers(run, arm)
        b.qualify_workers(run, topology, b.e.workers(run), arm)
        b.e.collect_frontend_metrics(run, base, arm, 'after')
        b.e.collect_profile(run, arm)
        b.write(folder / 'outcome.json', outcome)
        if outcome['exit_code']:
            raise RuntimeError('Immutable profile failed; no retuning or replay.')
        b.e.validate_profile(run, arm)
        b.write(folder / 'integrity-final.json', {str(p.relative_to(folder)): b.sha(p)
            for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'})
        run.result('disagg-' + topology, 'passed', arm=arm, fresh_campaign=True, source_cpu_uid=SOURCE_UID)
    except BaseException as error:
        b.e.collect_workers(run, arm)
        b.write(folder / 'failure.json', {'at': b.e.now(), 'error': repr(error)})
        run.result('disagg-' + topology, 'blocked', error=repr(error))
        raise
    finally:
        if b.LEASE.exists():
            b.c.lease_owned(run)
            (b.LEASE / 'allocation.json').unlink(missing_ok=True)
        b.c.cleanup_gpu(run, 'cleanup-' + topology + '.json')


def cleanup(run):
    if b.LEASE.exists():
        b.c.lease_owned(run)
        (b.LEASE / 'allocation.json').unlink(missing_ok=True)
    b.c.cleanup_gpu(run)
    client = check_client(run)
    b.write(run.path / 'cleanup-final.json', {'at': b.e.now(), 'gpu_cleanup_passed': True,
        'gpu_lease_absent': not b.LEASE.exists(), 'borrowed_cpu_retained': True,
        'source_pod_uid': client['metadata']['uid'], 'source_namespace': run.ns,
        'retained': ['CPU Pod', 'PVC', 'namespace', 'prior routing archives', 'prepared cache']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'prepare', 'aggregate', 'disaggregated', 'cleanup', 'verify'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = setup(args.run)
    if args.action in ('freeze', 'prepare', 'cleanup'):
        globals()[args.action](run)
    elif args.action == 'verify':
        b.verify(run)
    else:
        execute(run, args.action)


if __name__ == '__main__':
    main()
