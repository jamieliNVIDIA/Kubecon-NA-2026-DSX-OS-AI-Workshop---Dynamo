#!/usr/bin/env python3
"""Fresh AgentX C32 comparison with exact frontend model readiness gating."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'reports/workshop-measurements-20261030/rr-kv'
AGENTX = ROOT / 'reports/workshop-measurements-20261030/agentx-workload'
module_spec = importlib.util.spec_from_file_location('previous_rrkv_campaign', BASE / 'campaign.py')
c = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(c)
e = c.e
LEASE = ROOT / '.local/workshop-routing-c32-20261105.gpu-lease'
NAMESPACE = 'dynamo-ft-routing-c32-20261105-a1'
OWNER = '/root/routing_load_sweep_c32'
LOADS = [32]
MAX_SEQS = 128
CONFIGS = {'two-rr': (2, 'round-robin'), 'two-kv': (2, 'kv'), 'one-rr': (1, 'round-robin')}
REFERENCE = ROOT / 'results/workshop-rrkv-20261104-a1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def setup(path):
    c.NAMESPACE = NAMESPACE
    c.LEASE = LEASE
    c.OWNER = OWNER
    return c.setup(path)


def spec(run):
    return json.loads((run.path / 'campaign.json').read_text())


def manifest(run, config):
    replicas, mode = CONFIGS[config]
    value = c.generated(run, mode)
    for obj in value['items']:
        if obj['kind'] == 'DynamoGraphDeployment':
            for component in obj['spec']['components']:
                pod = component['podTemplate']['spec']
                pod['activeDeadlineSeconds'] = 21600
                if component['type'] != 'worker':
                    continue
                component['replicas'] = replicas
                container = pod['containers'][0]
                args = container['args']
                args[args.index('--max-num-seqs') + 1] = str(MAX_SEQS)
                if replicas == 1:
                    terms = pod['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
                    for term in terms:
                        for expression in term['matchExpressions']:
                            if expression['key'] == 'kubernetes.io/hostname':
                                expression['values'] = ['kubecon-nke-site-cp-0198']
    return value


def verify(run):
    for name, digest in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert sha(ROOT / name) == digest, 'Frozen source changed: ' + name
    assert sha(run.path / 'campaign.json') == (run.path / 'campaign.sha256').read_text().strip()
    assert spec(run)['loads'] == LOADS and spec(run)['max_num_seqs'] == MAX_SEQS
    assert spec(run)['model_lock'] == run.state['model_lock']
    assert spec(run)['gpu_uuids_by_node'] == c.GPUS
    rr = json.loads((run.path / 'deployment-two-rr.json').read_text())
    kv = json.loads((run.path / 'deployment-two-kv.json').read_text())
    frontend = next(component for obj in rr['items'] if obj['kind'] == 'DynamoGraphDeployment'
                    for component in obj['spec']['components'] if component['type'] == 'frontend')
    args = frontend['podTemplate']['spec']['containers'][0]['args']
    args[args.index('--router-mode') + 1] = 'kv'
    assert rr == kv, 'Two-worker policies differ beyond router mode'


def freeze(run):
    assert not (run.path / 'campaign.json').exists(), 'Do not refreeze an attempted campaign'
    prior = json.loads((REFERENCE / 'campaign.json').read_text())
    write(run.path / 'expected-probes.json', json.loads((REFERENCE / 'expected-probes.json').read_text()))
    value = {**prior, 'namespace': run.ns, 'loads': LOADS, 'max_num_seqs': MAX_SEQS,
        'sequence': [{'configuration': config, 'concurrency': n, 'arm': f'{config}-c{n}-a1'}
                     for n in LOADS for config in CONFIGS], 'lease': str(LEASE.relative_to(ROOT)),
        'lease_owner': OWNER, 'concurrent_work': 'Disjoint exact GPU0+2 pairs on cp-0198/cp-0942; concurrent node CPU, EFS and network load from other demo tests',
        'cache_history': 'Fresh workers/private compiler caches per cell; bounded smoke and new canonical AgentX primer before each profile',
        'parameter_authorization': 'User resumed unfinished workshop work; root explicitly authorized fresh C32 comparison after prior frontend model readiness race',
        'endpoint_readiness': {'expected_model_id': prior['model_lock']['model'], 'timeout_seconds': 120.0, 'poll_interval_seconds': 1.0, 'scope': 'GET /v1/models only; no inference until exact ID observed'},
        'cpu_client': 'New owned rr-loadgen in fresh namespace; old routing CPU remains exclusively handed to P/D',
        'client_deadline_seconds': 86400, 'worker_deadline_seconds': 21600,
        'measurement_class': 'C32 fixed order two-RR, two-KV, one-RR; fresh workers per cell, N=1. No direct capacity curve claim against separate C16 campaign.'}
    value.pop('replicas', None)
    value.pop('initial_cache', None)
    write(run.path / 'campaign.json', value)
    for config in CONFIGS:
        write(run.path / ('deployment-' + config + '.json'), manifest(run, config))
    # The preceding CPU/admission helpers expect these names; both are exact frozen copies.
    for mode, config in [('round-robin', 'two-rr'), ('kv', 'two-kv')]:
        (run.path / ('deployment-' + mode + '.json')).write_bytes((run.path / ('deployment-' + config + '.json')).read_bytes())
    for n in LOADS:
        profile = yaml.safe_load((AGENTX / 'profile-c4.yaml').read_text())
        profile['benchmark']['phases'][0]['concurrency'] = n
        profile['benchmark']['artifacts']['dir'] = f'artifacts/agentx-c{n}'
        (run.path / f'profile-c{n}.yaml').write_text(yaml.safe_dump(profile, sort_keys=False))
    previous_inputs = json.loads((REFERENCE / 'inputs-sha256.json').read_text())
    paths = [ROOT / name for name in previous_inputs if not name.startswith('results/workshop-rrkv-20261104-a1/')]
    paths += [HERE / 'campaign.py', HERE / 'controller.py', HERE / 'PLAN.md', HERE / 'ready.py',
              ROOT / 'tests/routing/test_model_readiness.py', REFERENCE / 'campaign.json',
              ROOT / 'results/workshop-rrkv-stopped-pullback-20261104-a1/verification.json']
    paths += [p for p in run.path.iterdir() if p.is_file() and p.name not in ['state.json', '.state.lock']]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in paths})
    (run.path / 'campaign.sha256').write_text(sha(run.path / 'campaign.json') + '\n')
    verify(run)
    e.status(run, 'Frozen higher-load sweep; no cluster resources created')


def loadgen(run):
    lock = run.state['model_lock']
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'rr-loadgen'}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 86400, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': c.CPU_NODE}, 'imagePullSecrets': [{'name': 'common-runtime-pull'}],
        'containers': [{'name': 'loadgen', 'image': lock['runtime_image'], 'command': ['sleep', '86400'],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                    {'name': 'AIPERF_DATASET_WEKA_PARALLEL_WORKERS', 'value': '1'}],
            'resources': {'requests': {'cpu': '4', 'memory': '64Gi', 'ephemeral-storage': '40Gi'},
                          'limits': {'cpu': '8', 'memory': '96Gi', 'ephemeral-storage': '80Gi'}},
            'volumeMounts': [{'name': 'cache', 'mountPath': '/model-cache'}]}],
        'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    run.wait_pod('rr-loadgen', timeout=300)


def prepare(run):
    # Reuse proven admission/model checks with the new namespace, CPU deadline and cap.
    original = c.cluster.loadgen
    c.cluster.loadgen = loadgen
    try:
        c.prepare(run)
    finally:
        c.cluster.loadgen = original


def validate_cpu(run):
    c.qualify_cpu(run)
    proof = {}
    program = '''import json,sys
from pathlib import Path
from aiperf.cli_runner import _make_benchmark_run
from aiperf.config import load_config
from aiperf.config.dataset.resolver import DatasetResolver
from aiperf.config.resolution.resolvers import ScenarioResolver,TimingResolver
from aiperf.dataset.dataset_manager import DatasetManager
cfg=load_config(Path(sys.argv[1]));run=_make_benchmark_run(cfg.benchmark,random_seed=cfg.random_seed)
for resolver in [DatasetResolver(),ScenarioResolver(),TimingResolver()]:resolver.resolve(run)
manager=DatasetManager(run=run,service_id='sweep-config-qualification')
assert manager._try_cache_lookup() is not None,'Higher-concurrency profile needs a new CPU cache'
print(json.dumps({'concurrency':cfg.benchmark.phases[0].concurrency,'cache_key':manager._cache_key_for_run,'scenario_outcome':run.resolved.scenario_outcome.model_dump(mode='json')}))
'''
    # DatasetManager requires the same environment as the full qualification helper.
    wrapped = '''import os
os.environ.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
''' + program
    for n in LOADS:
        path = run.path / f'profile-c{n}.yaml'
        remote = e.REMOTE + f'/preparation/sweep-profile-c{n}.yaml'
        e.upload(run, path, remote)
        value = json.loads(e.client(run, wrapped, argv=(remote,), timeout=180).stdout.strip().splitlines()[-1])
        assert value['concurrency'] == n
        proof[str(n)] = value
    write(run.path / 'higher-load-cpu-qualification.json', {'passed': True, 'profiles': proof})
    run.result('sweep-cpu-qualified', 'passed', loads=LOADS)


def verify_workers(run, config, pods, folder):
    replicas, mode = CONFIGS[config]
    items = json.loads((run.path / ('deployment-' + config + '.json')).read_text())['items']
    expected = next(component for obj in items if obj['kind'] == 'DynamoGraphDeployment'
                    for component in obj['spec']['components'] if component['type'] == 'worker')['podTemplate']['spec']['containers'][0]
    probes = json.loads((run.path / 'expected-probes.json').read_text())
    nodes = set(c.GPUS) if replicas == 2 else {'kubecon-nke-site-cp-0198'}
    actual = {}
    for pod in pods:
        name = pod['metadata']['name'];container = pod['spec']['containers'][0]
        c.verify_allocation(run, pod, container, 2)
        assert container['args'] == expected['args'] and container['image'] == expected['image']
        assert all(container.get(key) == value for key, value in probes.items())
        assert all(v['restartCount'] == 0 and v['imageID'].endswith(spec(run)['model_lock']['runtime_image'].split('@')[1])
                   for v in pod['status']['containerStatuses'])
        text = (folder / (name + '.log')).read_text()
        assert 'running in text-only mode' in text
        assert sorted(set(re.findall(r'canary_wait_time_secs=(\d+)', text))) == ['1']
        assert re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)', text)
        cache_lines = [line for line in text.splitlines() if 'GPU KV cache size:' in line or 'Available KV cache memory:' in line]
        assert cache_lines, 'Missing actual KV capacity during engine qualification'
        node = pod['spec']['nodeName'];assert node in nodes
        result = run.k('exec', name, '-n', run.ns, '-c', 'main', '--', 'nvidia-smi',
            '--query-gpu=index,uuid,name,memory.total,driver_version', '--format=csv,noheader')
        (folder / ('gpu-visible-' + name + '.csv')).write_text(result.stdout)
        uuids = sorted(line.split(',')[1].strip() for line in result.stdout.strip().splitlines())
        assert uuids == sorted(c.GPUS[node]) and all('H100' in line for line in result.stdout.splitlines())
        actual[node] = {'gpu_uuids': uuids, 'cache_capacity_logs': cache_lines, 'uid': pod['metadata']['uid']}
    assert set(actual) == nodes
    value = {'passed': True, 'configuration': config, 'max_num_seqs': MAX_SEQS,
             'workers': actual, 'campaign_sha256': sha(run.path / 'campaign.json')}
    write(folder / 'worker-qualification.json', value)
    return value


def discovery(run, arm, mode, pods, ids):
    if len(pods) == 2:
        c.qualify_discovery(run, arm, mode, pods, ids)
    else:
        assert mode == 'round-robin' and len(set(ids)) == 1 and 'None' not in ids
        write(run.path / arm / 'discovery-qualification.json', {'passed': True, 'mode': mode,
              'worker_pod_ips': [p['status']['podIP'] for p in pods], 'smoke_worker_ids': sorted(set(ids)),
              'scope': 'One RR worker exercised by four bounded smoke requests'})


def seal_profile(run, config, n, pods, arm, base):
    replicas, mode = CONFIGS[config]
    profile = yaml.safe_load((run.path / f'profile-c{n}.yaml').read_text())
    cfg = profile['benchmark'];cfg['endpoint']['urls'] = [base]
    cfg['artifacts']['dir'] = f'{e.REMOTE}/runs/{arm}/artifacts'
    cfg['server_metrics']['discovery'] = {'mode': 'disabled'}
    cfg['server_metrics']['urls'] = [f'http://{p["status"]["podIP"]}:9090' for p in pods]
    path = run.path / arm / 'profile.yaml'
    path.write_text(yaml.safe_dump(profile, sort_keys=False))
    metadata = {'sealed_at': e.now(), 'arm': arm, 'configuration': config, 'replicas': replicas, 'h100_gpus': replicas * 2,
        'concurrency_session_trees': n, 'model': e.MODEL, 'model_revision': e.REV,
        'runtime_image': run.state['model_lock']['runtime_image'], 'dataset_revision': e.DATASET_REV,
        'dataset_sha256': e.DATASET_SHA, 'aiperf_commit': spec(run)['aiperf_commit'],
        'dataset_pin_patch_sha256': sha(AGENTX / 'aiperf-dataset-revision.patch'), 'profile_sha256': sha(path),
        'campaign_sha256': sha(run.path / 'campaign.json'), 'client_preprocessor_workers': 1,
        'client_resources': {'requests': {'cpu': '4', 'memory': '64Gi', 'ephemeral-storage': '40Gi'},
            'limits': {'cpu': '8', 'memory': '96Gi', 'ephemeral-storage': '80Gi'}},
        'router_mode': mode, 'native_max_model_len': 1048576, 'max_num_seqs_per_worker': MAX_SEQS,
        'cache_history': spec(run)['cache_history'], 'initial_gpu_cache': 'Fresh worker processes for this topology/load cell; bounded smoke plus mandatory canonical primer',
        'worker_pods': [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'], 'node': p['spec']['nodeName'],
                        'image_ids': [v['imageID'] for v in p['status']['containerStatuses']]} for p in pods]}
    with (run.path / arm / 'spec.json').open('x') as stream:
        json.dump(metadata, stream, indent=2)
    e.upload(run, path, f'{e.REMOTE}/runs/{arm}/profile.yaml')


def client_sample(run, arm, label):
    program = '''import json
from pathlib import Path
r=Path('/sys/fs/cgroup');names=['cpu.stat','cpu.max','memory.current','memory.peak','memory.events','io.stat']
print(json.dumps({name:(r/name).read_text() for name in names if (r/name).exists()}))
'''
    write(run.path / arm / ('client-' + label + '.json'), json.loads(e.client(run, program).stdout))


def accept_cell(run, arm, outcome):
    assert outcome['exit_code'] == 0, 'AIPerf process failed: ' + repr(outcome)
    folder = run.path / arm
    exports = [p for p in (folder / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
    assert len(exports) == 1, 'Missing or ambiguous export'
    data = json.loads(exports[0].read_text())
    assert data.get('is_complete') is True and data.get('was_cancelled') is False
    metric = lambda name: (data.get(name) or {}).get('avg', 0)
    assert metric('request_count') > 0
    records = []
    for path in (folder / 'raw').rglob('profile_export.jsonl'):
        for line in path.read_text().splitlines():
            meta = json.loads(line).get('metadata', {})
            if meta.get('phase_kind', meta.get('benchmark_phase')) == 'profiling':
                records.append(meta)
    cancelled = sum(bool(v.get('was_cancelled')) for v in records)
    errors = metric('error_request_count') or 0
    overflow = metric('context_overflow_count') or 0
    valid = (data.get('metadata') or {}).get('submission_valid') is True and not data.get('runtime_submission_invalid_reasons')
    clean = valid and not errors and not overflow and not cancelled and not data.get('error_summary')
    lines = []
    for console in (folder / 'raw').rglob('console.log'):
        lines += [line for line in console.read_text(errors='replace').splitlines()
                  if 'Phase ' in line and (' complete' in line or 'sending complete' in line)]
    value = {'outcome': 'clean' if clean else 'stress_observation', 'clean_comparison_eligible': clean,
        'successful_requests': metric('request_count'), 'request_errors': errors, 'context_overflow': overflow,
        'cancelled_profile_records': cancelled, 'submission_valid': valid,
        'runtime_submission_invalid_reasons': data.get('runtime_submission_invalid_reasons'),
        'error_summary': data.get('error_summary'), 'phase_completion_log_lines': lines,
        'scope': 'Stress outcomes retained; censored/invalid cells do not establish latency SLOs or speedup'}
    write(folder / 'summary.json', value)
    run.result('cell-' + arm, 'completed', **value)
    return value


def wait_frontend_model(run, base, folder):
    """Observe the exact frontend model before inference; preserve failed polls."""
    program = (HERE / 'ready.py').read_text()
    result = e.client(run, program, argv=(base, e.MODEL, '--timeout', '120', '--interval', '1'),
                      timeout=150, check=False)
    (folder / 'frontend-model-readiness-output.txt').write_text(result.stdout + result.stderr)
    receipt = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {
        'passed': False, 'error': 'Readiness client returned no JSON receipt', 'exit_code': result.returncode}
    write(folder / 'frontend-model-readiness.json', receipt)
    if result.returncode or receipt.get('passed') is not True or receipt.get('expected_model') != e.MODEL:
        raise RuntimeError('Expected frontend model was not advertised before the bounded startup gate.')
    return receipt


def configuration(run, config, concurrency):
    verify(run)
    assert run.state['checks']['sweep-cpu-qualified']['status'] == 'passed'
    with (run.path / (f'configuration-{config}-c{concurrency}-started.json')).open('x') as stream:
        json.dump({'at': e.now(), 'configuration': config, 'concurrency': concurrency}, stream)
    start = f'startup-{config}-c{concurrency}'
    (run.path / start).mkdir(exist_ok=False)
    e.acquire(run, 10800)
    try:
        assert not e.workers(run) and not run.get('get', 'resourceclaims', '-n', run.ns)['items']
        c.allocation_available(run, start)
        write(run.path / start / 'events-before.json', run.get('get', 'events', '-n', run.ns))
        run.apply(json.loads((run.path / ('deployment-' + config + '.json')).read_text())['items'])
        e.status(run, 'Qualifying higher-concurrency workers', configuration=config, max_num_seqs=MAX_SEQS)
        replicas, mode = CONFIGS[config]
        pods = e.wait_serving(run, replicas, start)
        e.collect_workers(run, start)
        verify_workers(run, config, pods, run.path / start)
        base = e.endpoint(run)
        for n in [concurrency]:
            verify(run)
            arm = f'{config}-c{n}-a1';folder = run.path / arm;folder.mkdir(exist_ok=False)
            # Worker identity stays fixed within the curve; verify health and restarts at every point.
            current = e.workers(run)
            assert {p['metadata']['uid'] for p in current} == {p['metadata']['uid'] for p in pods}
            e.collect_workers(run, arm)
            verify_workers(run, config, current, folder)
            wait_frontend_model(run, base, folder)
            ids = e.smoke(run, base, replicas, arm, require_distribution=mode == 'round-robin')
            e.collect_workers(run, arm)
            discovery(run, arm, mode, current, ids)
            seal_profile(run, config, n, current, arm, base)
            e.collect_frontend_metrics(run, base, arm, 'before')
            client_sample(run, arm, 'before')
            e.telemetry_start(run, current, arm)
            try:
                e.launch_profile(run, arm)
                outcome = e.poll_profile(run, arm)
            finally:
                e.telemetry_stop(run, arm)
            client_sample(run, arm, 'after')
            e.collect_workers(run, arm)
            # Preserve client artifacts before runtime qualification can fail.
            # The previous campaign lost the failing primer's raw exports here.
            e.collect_frontend_metrics(run, base, arm, 'after')
            e.collect_profile(run, arm)
            write(folder / 'events-after.json', run.get('get', 'events', '-n', run.ns))
            verify_workers(run, config, e.workers(run), folder)
            accept_cell(run, arm, outcome)
            write(folder / 'integrity-final.json', {'sha256': {str(p.relative_to(folder)): sha(p)
                for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'}})
            e.status(run, 'Load point recorded', configuration=config, concurrency=n, arm=arm)
        run.result(f'configuration-{config}-c{concurrency}', 'completed', concurrency=concurrency)
    except BaseException as error:
        e.collect_workers(run, start)
        run.result(f'configuration-{config}-c{concurrency}', 'stopped', error=repr(error))
        raise
    finally:
        c.cleanup_gpu(run, f'after-{config}-c{concurrency}-cleanup.json')


def finalize(run):
    assert all(run.state['checks'][f'configuration-{config}-c{n}']['status'] == 'completed' for n in LOADS for config in CONFIGS)
    verify(run)
    c.cleanup_gpu(run)
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    assert pod['metadata']['uid'] == json.loads((run.path / 'client-identity.json').read_text())['uid']
    assert pod['metadata']['labels']['feature-test-run'] == run.ns
    run.k('delete', 'pod', 'rr-loadgen', '-n', run.ns, '--wait=true', '--timeout=120s', timeout=150)
    for kind in ['pods', 'resourceclaims', 'dgd']:
        assert not run.get('get', kind, '-n', run.ns)['items']
    write(run.path / 'qualification.json', {'passed': True, 'cells_recorded': len(LOADS) * len(CONFIGS), 'cleanup_verified': True,
        'scoped_lease_absent': not LEASE.exists(), 'scope': 'Execution and collection; comparison eligibility is per cell'})
    e.status(run, 'All topology-first cells recorded and resources cleaned; analysis pending')
    write(run.path / 'evidence-sha256.json', {str(p.relative_to(run.path)): sha(p)
        for p in run.path.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cells = {f'{config}-c{n}': (config, n) for n in LOADS for config in CONFIGS}
    parser.add_argument('action', choices=['freeze', 'prepare', 'qualify-cpu', 'finalize', 'verify', *cells])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args();run = setup(args.run)
    if args.action == 'freeze':
        freeze(run)
        return
    verify(run)
    if args.action == 'prepare':prepare(run)
    elif args.action == 'qualify-cpu':validate_cpu(run)
    elif args.action in cells:configuration(run, *cells[args.action])
    elif args.action == 'finalize':finalize(run)
    else:e.status(run, 'Frozen higher-load inputs verified')


if __name__ == '__main__':
    main()
