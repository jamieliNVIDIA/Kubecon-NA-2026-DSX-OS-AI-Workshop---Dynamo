#!/usr/bin/env python3
"""Immutable, matched four-H100 AgentX aggregate-versus-P/D investigation.

Reuse the qualified AgentX preparation/execution plumbing, but freeze a separate
campaign, namespace and exact GPU reservation. A failed arm is retained, never
silently retuned or replayed. This is an exploratory N=1 pair, not a capacity or
universal disaggregation-speedup claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'reports/workshop-measurements-20261030'
sys.path.insert(0, str(ROOT / 'scripts'))
module_spec = importlib.util.spec_from_file_location('disagg_prior_campaign', SOURCE / 'rr-kv/campaign.py')
c = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(c)
e = c.e
import demos.disaggregated.demo as pd

OWNER = '/root/disagg_comparison'
LEASE = ROOT / '.local/overnight-disagg.gpu-lease'
NAMESPACE = 'dynamo-ft-overnight-disagg-20261105-a1'
GPUS = {
    'kubecon-nke-site-cp-0198': ['GPU-c22769a2-282c-de40-459e-261999971cd9', 'GPU-7338f39e-745f-e46a-7ef6-cc8cc155d7af'],
    'kubecon-nke-site-cp-0942': ['GPU-7b0cff01-e024-1e7f-5c2e-53c85b3835e4', 'GPU-bd8b4452-af4b-12ab-237d-63d32996835c'],
}
CONCURRENCY = 16
MAX_SEQS = 128
ARMS = ('aggregate', 'disaggregated')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def spec(run):
    return json.loads((run.path / 'campaign.json').read_text())


def status(run, stage, **details):
    value = {'updated_at': e.now(), 'stage': stage, 'namespace': run.ns, **details}
    write(run.path / 'LIVE_STATUS.json', value)
    print(json.dumps(value), flush=True)


def setup(path):
    c.NAMESPACE, c.LEASE, c.OWNER, c.GPUS = NAMESPACE, LEASE, OWNER, GPUS
    c.CPU_NODE = 'kubecon-nke-site-cp-0942'
    c.spec, c.verify = spec, verify
    run = c.setup(path)
    e.status = status
    return run


def select_claim(claim, uuids):
    exact = claim['spec']['spec']['devices']['requests'][0]['exactly']
    if exact['count'] != 2:
        raise ValueError('Each engine must use exactly two GPUs.')
    exact['selectors'] = [{'cel': {'expression':
        'device.driver == "gpu.nvidia.com" && has(device.attributes["gpu.nvidia.com"].uuid) && '
        'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids)}}]


def manifest(run, topology):
    if topology == 'aggregate':
        result = c.generated(run, 'kv')
    elif topology == 'disaggregated':
        graph, claims = pd.render(run.ns, run.state['model_lock'])
        graph['metadata']['name'] = 'ft-agg'
        result = {'apiVersion': 'v1', 'kind': 'List', 'items': claims + [graph]}
        for claim, node in zip(claims, GPUS):
            select_claim(claim, GPUS[node])
        for component in graph['spec']['components']:
            if component['type'] in ('prefill', 'decode'):
                node = list(GPUS)[0 if component['type'] == 'prefill' else 1]
                component['podTemplate']['spec']['nodeSelector'] = {'kubernetes.io/hostname': node}
    else:
        raise ValueError('Unknown topology.')
    probes = json.loads((run.path / 'expected-probes.json').read_text())
    for obj in result['items']:
        obj['metadata']['namespace'] = run.ns
        obj['metadata']['labels'] = run.labels()
        if obj['kind'] != 'DynamoGraphDeployment':
            continue
        for component in obj['spec']['components']:
            role = component['type']
            pod = component['podTemplate']
            pod.setdefault('metadata', {}).setdefault('labels', {}).update({
                **run.labels(), 'workshop-benchmark-role': role})
            pod['spec']['activeDeadlineSeconds'] = 10800
            main = pod['spec']['containers'][0]
            if role == 'frontend':
                pod['spec']['nodeSelector'] = {'kubernetes.io/hostname': c.CPU_NODE}
                continue
            args = main['args']
            if '--max-model-len' in args:
                at = args.index('--max-model-len')
                del args[at:at + 2]
            args[args.index('--max-num-seqs') + 1] = str(MAX_SEQS)
            if '--language-model-only' not in args:
                args.append('--language-model-only')
            main.update(copy.deepcopy(probes))
            settings = {'DYN_CANARY_WAIT_TIME': '1', 'VLLM_CACHE_ROOT': '/tmp/workshop-vllm-cache',
                'TRITON_CACHE_DIR': '/tmp/workshop-triton-cache', 'DG_JIT_CACHE_DIR': '/tmp/workshop-deepgemm-cache',
                'FLASHINFER_WORKSPACE_BASE': '/tmp/workshop-flashinfer-cache'}
            main['env'] = [v for v in main.get('env', []) if v['name'] not in settings]
            main['env'] += [{'name': k, 'value': v} for k, v in settings.items()]
    return result


def freeze(run):
    if (run.path / 'campaign.json').exists():
        raise ValueError('Never refreeze an attempted campaign; verify or choose a new run.')
    reference = ROOT / 'results/workshop-rrkv-20261104-a1'
    prior = json.loads((reference / 'campaign.json').read_text())
    write(run.path / 'expected-probes.json', json.loads((reference / 'expected-probes.json').read_text()))
    value = {**prior, 'namespace': run.ns, 'gpu_uuids_by_node': GPUS,
        'lease': str(LEASE.relative_to(ROOT)), 'lease_owner': OWNER,
        'sequence': list(ARMS), 'concurrency_session_trees': CONCURRENCY,
        'max_num_seqs': MAX_SEQS, 'gpus_per_topology': 4, 'repetitions': 1,
        'parameter_authorization': 'User requested overnight remaining demos, AgentX benchmarks, whole-cluster testing; topology/load chosen as bounded exploratory investigation before lock.',
        'comparison': '2 aggregated TP2 KV-routed workers versus TP2 prefill + TP2 decode on identical physical node/GPU pairs',
        'cache_history': 'Fresh engines/private compilation caches per topology; bounded smoke plus unchanged canonical AgentX snapshot primer',
        'concurrent_work': 'Other disjoint-GPU workshop tests on all nodes; CPU, EFS, PCIe and network interference possible',
        'measurement_class': 'Sequential fixed-order N=1 exploration; report neutral/negative results and realized request-mix/drain limitations'}
    for key in ('replicas', 'initial_cache'):
        value.pop(key, None)
    write(run.path / 'campaign.json', value)
    for topology in ARMS:
        write(run.path / ('deployment-' + topology + '.json'), manifest(run, topology))
    # Original CPU preparation uses these paths only for admission dry-runs.
    for topology, alias in zip(ARMS, ('round-robin', 'kv')):
        (run.path / ('deployment-' + alias + '.json')).write_bytes(
            (run.path / ('deployment-' + topology + '.json')).read_bytes())
    profile = yaml.safe_load((SOURCE / 'agentx-workload/profile-c4.yaml').read_text())
    profile['benchmark']['phases'][0]['concurrency'] = CONCURRENCY
    (run.path / 'profile.yaml').write_text(yaml.safe_dump(profile, sort_keys=False))
    paths = [Path(__file__), ROOT / 'demos/disaggregated/demo.py', pd.TEMPLATE,
             ROOT / 'configs/super-vl-tp2-lock.json']
    prior_inputs = json.loads((reference / 'inputs-sha256.json').read_text())
    paths += [ROOT / name for name in prior_inputs if not name.startswith('results/workshop-rrkv-20261104-a1/')]
    paths += [p for p in run.path.iterdir() if p.is_file() and p.name not in ('state.json', '.state.lock')]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in paths})
    (run.path / 'campaign.sha256').write_text(sha(run.path / 'campaign.json') + '\n')
    verify(run)
    status(run, 'Frozen matched four-GPU AgentX comparison; no deployment')


def verify(run):
    for name, digest in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        if sha(ROOT / name) != digest:
            raise ValueError('Frozen input changed: ' + name)
    if spec(run)['gpu_uuids_by_node'] != GPUS or spec(run)['model_lock'] != run.state['model_lock']:
        raise ValueError('Campaign allocation/model identity changed.')


def prepare(run):
    c.prepare(run)
    from common_runtime_tests import efa
    efa(run)
    c.qualify_cpu(run)
    remote = e.REMOTE + '/preparation/disagg-profile-c16.yaml'
    e.upload(run, run.path / 'profile.yaml', remote)
    # Cache keys exclude concurrency but must be checked with the actual profile.
    program = '''import os,subprocess,sys
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
subprocess.run([sys.executable,'/tmp/workshop-rr/preparation/prepare_agentx_cache.py','--config',sys.argv[1],'--receipt','/tmp/workshop-rr/preparation/receipt-disagg-c16.json','--check-cache-only'],env=env,check=True)
'''
    result = e.client(run, program, argv=(remote,), timeout=900)
    (run.path / 'cpu-c16-check.log').write_text(result.stdout + result.stderr)
    run.result('disagg-cpu-qualified', 'passed', concurrency_session_trees=CONCURRENCY)


def qualify_workers(run, topology, pods, arm):
    expected = json.loads((run.path / ('deployment-' + topology + '.json')).read_text())
    graph = next(v for v in expected['items'] if v['kind'] == 'DynamoGraphDeployment')
    by_role = {v['type']: v['podTemplate']['spec']['containers'][0] for v in graph['spec']['components']}
    identities = {}
    for pod in pods:
        role = pod['metadata']['labels']['workshop-benchmark-role']
        main = pod['spec']['containers'][0]
        if main['args'] != by_role[role]['args'] or main['image'] != run.state['model_lock']['runtime_image']:
            raise ValueError('Worker executable configuration changed.')
        if any(v.get('restartCount', 0) or not v['imageID'].endswith(run.state['model_lock']['runtime_image'].split('@')[1])
               for v in pod['status']['containerStatuses']):
            raise ValueError('Worker restarted or image digest changed.')
        c.verify_allocation(run, pod, main, 2)
        result = run.k('exec', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--',
            'nvidia-smi', '--query-gpu=uuid,name', '--format=csv,noheader')
        node = pod['spec']['nodeName']
        uuids = sorted(line.split(',')[0].strip() for line in result.stdout.strip().splitlines())
        if node not in GPUS or uuids != sorted(GPUS[node]):
            raise ValueError('Worker did not receive its frozen node/GPU pair.')
        identities[node] = {'role': role, 'gpu_uuids': uuids, 'pod_uid': pod['metadata']['uid']}
    if set(identities) != set(GPUS):
        raise ValueError('Expected one TP2 worker on each frozen node.')
    write(run.path / arm / 'worker-qualification.json', {'passed': True, 'workers': identities,
        'native_context': 1048576, 'max_num_seqs': MAX_SEQS, 'topology': topology})


def seal_profile(run, topology, arm, pods, base):
    config = yaml.safe_load((run.path / 'profile.yaml').read_text())
    cfg = config['benchmark']
    cfg['endpoint']['urls'] = [base]
    cfg['artifacts']['dir'] = e.REMOTE + '/runs/' + arm + '/artifacts'
    cfg['server_metrics']['discovery'] = {'mode': 'disabled'}
    cfg['server_metrics']['urls'] = ['http://' + p['status']['podIP'] + ':9090' for p in pods]
    path = run.path / arm / 'profile.yaml'
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    value = {**spec(run), 'topology': topology, 'sealed_at': e.now(), 'arm': arm,
             'profile_sha256': sha(path), 'campaign_sha256': sha(run.path / 'campaign.json'),
             'worker_pods': [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'],
                              'node': p['spec']['nodeName']} for p in pods]}
    with (run.path / arm / 'spec.json').open('x') as stream:
        json.dump(value, stream, indent=2)
    e.upload(run, path, e.REMOTE + '/runs/' + arm + '/profile.yaml')


def execute_arm(run, topology):
    verify(run)
    if run.state['checks'].get('disagg-cpu-qualified', {}).get('status') != 'passed':
        raise ValueError('CPU/corpus qualification must precede GPU reservation.')
    arm = topology + '-c16-a1'
    folder = run.path / arm
    folder.mkdir(exist_ok=False)
    write(folder / 'intent.json', {'at': e.now(), 'topology': topology})
    e.acquire(run, 0)
    try:
        c.allocation_available(run, arm)
        write(LEASE / 'allocation.json', {'gpu_uuids_by_node': GPUS, 'namespace': run.ns,
                                         'run': str(run.path), 'owner': OWNER})
        run.apply(json.loads((run.path / ('deployment-' + topology + '.json')).read_text())['items'])
        status(run, 'Starting ' + topology, arm=arm)
        pods = e.wait_serving(run, 2, arm)
        e.collect_workers(run, arm)
        qualify_workers(run, topology, pods, arm)
        base = e.endpoint(run)
        e.smoke(run, base, 2, arm, require_distribution=topology == 'aggregate')
        seal_profile(run, topology, arm, pods, base)
        e.collect_frontend_metrics(run, base, arm, 'before')
        e.telemetry_start(run, pods, arm)
        try:
            e.launch_profile(run, arm)
            outcome = e.poll_profile(run, arm)
        finally:
            e.telemetry_stop(run, arm)
        e.collect_workers(run, arm)
        qualify_workers(run, topology, e.workers(run), arm)
        e.collect_frontend_metrics(run, base, arm, 'after')
        e.collect_profile(run, arm)
        write(folder / 'outcome.json', outcome)
        if outcome['exit_code']:
            raise RuntimeError('AIPerf arm failed; preserve immutable attempt.')
        summary = e.validate_profile(run, arm)
        write(folder / 'integrity-final.json', {str(p.relative_to(folder)): sha(p)
            for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'})
        run.result('disagg-' + topology, 'passed', arm=arm,
                   scope='Fixed-order exploratory AgentX profile; comparison limits in campaign.json')
        return summary
    except BaseException as error:
        e.collect_workers(run, arm)
        write(folder / 'failure.json', {'at': e.now(), 'error': repr(error)})
        run.result('disagg-' + topology, 'blocked', error=repr(error))
        raise
    finally:
        # The original helper removes owner.json itself after scoped workload
        # cleanup; remove our additional metadata only while ownership matches.
        if LEASE.exists():
            c.lease_owned(run)
            (LEASE / 'allocation.json').unlink(missing_ok=True)
        c.cleanup_gpu(run, 'cleanup-' + topology + '.json')


def cleanup(run):
    if LEASE.exists():
        c.lease_owned(run)
        (LEASE / 'allocation.json').unlink(missing_ok=True)
    c.cleanup_gpu(run)
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    expected = json.loads((run.path / 'client-identity.json').read_text())
    if pod['metadata']['uid'] != expected['uid'] or pod['metadata']['labels']['feature-test-run'] != run.ns:
        raise ValueError('CPU client identity changed; refuse deletion.')
    run.k('delete', 'pod', 'rr-loadgen', '-n', run.ns, '--wait=true', '--timeout=120s', timeout=150)
    write(run.path / 'cleanup-final.json', {'at': e.now(), 'gpu_lease_absent': not LEASE.exists(),
        'namespace': run.ns, 'remaining': {kind: len(run.get('get', kind, '-n', run.ns)['items'])
            for kind in ('pods', 'resourceclaims', 'dgd')}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'verify', 'prepare', 'aggregate', 'disaggregated', 'all', 'cleanup'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = setup(args.run)
    if args.action == 'freeze':
        freeze(run)
    elif args.action == 'verify':
        verify(run)
    elif args.action == 'prepare':
        prepare(run)
    elif args.action == 'cleanup':
        cleanup(run)
    elif args.action == 'all':
        freeze(run)
        prepare(run)
        try:
            for topology in ARMS:
                execute_arm(run, topology)
        finally:
            cleanup(run)
        status(run, 'Matched pair collected and cleaned; analysis pending')
    else:
        execute_arm(run, args.action)


if __name__ == '__main__':
    main()
