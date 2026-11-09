#!/usr/bin/env python3
"""Synthetic user-centric scale-out and routing campaign: one TP2 worker, then two, behind RR and KV frontends."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
module_spec = importlib.util.spec_from_file_location('rrkv_campaign', HERE.parent / 'rr-kv' / 'campaign.py')
c = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(c)
e = c.e
C32 = ROOT / 'reports/overnight-2026-11-04/routing-c32'
REFERENCE = ROOT / 'results/workshop-routing-c32-20261105-a1'
LOCATION = HERE.parent / 'agentx-workload' / 'source-location.json'

LEASE = ROOT / '.local/workshop-synthetic-scaleout-20261107-a3.gpu-lease'
OWNER = '/root/synthetic_scaleout'
NAMESPACE = 'dynamo-ft-synthetic-scaleout-20261107-a3'
NODE = 'kubecon-nke-site-cp-0942'
# cp-0942 gpu-0/2 (the AgentX C32 second worker's pair) and gpu-4/6; the live demos hold cp-0124 and cp-0198.
GPUS = {NODE: ['GPU-c15ae016-71f1-03bc-0228-624adbb1b4e8', 'GPU-4aacb1e1-a109-70bb-6b72-8071d736ba75',
               'GPU-09ecbc64-ad4f-708b-6ca3-ba1ba5fd052f', 'GPU-58272147-35f4-6125-0810-25497aee2a1a']}
MAX_SEQS = 128
GAP_SECONDS = 45
OUTPUT_TOKENS = 650
# A long grace lets overload cells drain in-flight turns instead of cancelling them; the window ends at 540 s.
WINDOW = {'duration_seconds': 540, 'grace_seconds': 300, 'slice_seconds': 30, 'analysis_start_seconds': 180}
FRONTENDS = {'rr': ('Frontend', 'round-robin'), 'kv': ('FrontendKV', 'kv')}
# Every profile is rendered and frozen up front; a cell's seed follows its position here, unchanged from a2,
# so a cell rerun in a3 replays a2's dataset exactly.
PROFILES = ['1w-32', '1w-64', '1w-128', '2kv-64', '2rr-64', '2rr-128', '2kv-128', '2kv-32']
# a2 completed one worker at 32/64/128 cleanly, then its scale-up could not schedule worker 2 (see deployment()).
# a3 repeats 1w-64 as a bridge to a2's phase A, then runs the two-worker cells.
PHASE_A = ['1w-64']
PHASE_B = ['2kv-64', '2rr-64', '2rr-128', '2kv-128', '2kv-32']
CLIENT_ENV = {'HF_HOME': '/tmp/workshop-rr/hf', 'HF_HUB_CACHE': '/tmp/workshop-rr/hf/hub',
              'HF_DATASETS_CACHE': '/tmp/workshop-rr/hf/datasets', 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def spec(run):
    return json.loads((run.path / 'campaign.json').read_text())


def parse(name):
    match = re.fullmatch(r'([12])(w|rr|kv)-(\d+)', name)
    assert match, name
    return int(match[1]), 'rr' if match[2] == 'w' else match[2], int(match[3])


def setup(path):
    c.NAMESPACE = NAMESPACE
    c.LEASE = LEASE
    c.OWNER = OWNER
    c.GPUS = GPUS
    c.CPU_NODE = NODE
    return c.setup(path)


def deployment(run, workers):
    value = c.generated(run, 'round-robin')
    for obj in value['items']:
        if obj['kind'] != 'DynamoGraphDeployment':
            continue
        components = obj['spec']['components']
        frontend = next(x for x in components if x['type'] == 'frontend')
        assert frontend['name'] == FRONTENDS['rr'][0]
        kv = copy.deepcopy(frontend)
        kv['name'] = FRONTENDS['kv'][0]
        args = kv['podTemplate']['spec']['containers'][0]['args']
        args[args.index('--router-mode') + 1] = FRONTENDS['kv'][1]
        components.insert(components.index(frontend) + 1, kv)
        for component in components:
            pod = component['podTemplate']['spec']
            pod['activeDeadlineSeconds'] = 21600
            if component['type'] != 'worker':
                continue
            component['replicas'] = workers
            # The two-worker template spreads replicas across hosts (podAntiAffinity on feature-test-role=agg); both
            # workers share cp-0942 here because the presenter demos hold the other nodes' routing pairs.
            assert pod['affinity'].pop('podAntiAffinity')['requiredDuringSchedulingIgnoredDuringExecution'][0][
                'topologyKey'] == 'kubernetes.io/hostname'
            container = pod['containers'][0]
            args = container['args']
            args[args.index('--max-num-seqs') + 1] = str(MAX_SEQS)
            # A load test, not a startup test: the 1 s canary wait and 180 s timeout came from MX startup tuning.
            container['env'] = [v for v in container['env']
                                if v['name'] not in ('DYN_CANARY_WAIT_TIME', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT')]
            container['env'].append({'name': 'DYN_HEALTH_CHECK_ENABLED', 'value': 'false'})
    return value


def worker_container(run, workers):
    items = json.loads((run.path / f'deployment-{workers}w.json').read_text())['items']
    return next(x for obj in items if obj['kind'] == 'DynamoGraphDeployment'
                for x in obj['spec']['components'] if x['type'] == 'worker')['podTemplate']['spec']['containers'][0]


def verify(run):
    for name, digest in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert sha(ROOT / name) == digest, 'Frozen source changed: ' + name
    assert sha(run.path / 'campaign.json') == (run.path / 'campaign.sha256').read_text().strip()
    assert spec(run)['model_lock'] == run.state['model_lock'] and spec(run)['gpu_uuids_by_node'] == GPUS
    one = json.loads((run.path / 'deployment-1w.json').read_text())
    two = json.loads((run.path / 'deployment-2w.json').read_text())
    for obj in two['items']:
        for component in obj.get('spec', {}).get('components', []):
            if component['type'] == 'worker':
                assert component['replicas'] == 2
                component['replicas'] = 1
    assert one == two, 'One- and two-worker deployments differ beyond the worker replica count'


def freeze(run):
    assert not (run.path / 'campaign.json').exists(), 'Do not refreeze an attempted campaign'
    prior = json.loads((REFERENCE / 'campaign.json').read_text())
    write(run.path / 'expected-probes.json', json.loads((REFERENCE / 'expected-probes.json').read_text()))
    cells = [{'cell': name, 'agents': parse(name)[2], 'gap_seconds': GAP_SECONDS, 'seed': 20261107 + index,
              **{k: v for k, v in WINDOW.items() if k != 'analysis_start_seconds'}}
             for index, name in enumerate(PROFILES)]
    value = {'schema': 1, 'model_lock': prior['model_lock'], 'namespace': run.ns,
        'model_cache_run_id': prior['model_cache_run_id'], 'checkpoint_weight_bytes': prior['checkpoint_weight_bytes'],
        'aiperf_commit': prior['aiperf_commit'], 'pull_secret_source_namespace': prior['pull_secret_source_namespace'],
        'gpu_uuids_by_node': GPUS, 'cpu_node': NODE, 'tp': 2, 'native_context': 1048576, 'max_num_seqs': MAX_SEQS,
        'max_num_batched_tokens': 8192, 'gpu_memory_utilization': .85, 'text_only': True, 'compile': True,
        'health': {'DYN_HEALTH_CHECK_ENABLED': 'false', 'removed': ['DYN_CANARY_WAIT_TIME=1', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT=180'],
                   'authorization': 'User decision, November 7, 2026: the 1 s canary was a startup optimization, not a load-test setting'},
        'workload': {'kind': 'AIPerf synthetic user-centric multi-turn; labeled synthetic, never AgentX',
                     'shared_system_prompt_tokens': 32000, 'user_context_tokens': 24000,
                     'new_input_tokens': {'mean': 4000, 'stddev': 1500}, 'output_tokens': OUTPUT_TOKENS,
                     'output_forced': 'ignore_eos', 'thinking': 'disabled via chat_template_kwargs',
                     'turns': {'mean': 12, 'stddev': 0}, 'gap_seconds': GAP_SECONDS, 'corpus': 'coding',
                     'dataset_entries': 1000, 'server_token_counts': True},
        'window': WINDOW, 'cells': cells, 'phase_a': PHASE_A, 'phase_b': PHASE_B,
        'matrix_rule': ('Fixed doubling matrix: one worker at 32/64/128 (from a2), two KV workers at 32/64/128, '
                        'round-robin at 64/128; a3 reruns 1w-64 with its a2 seed as the bridge'),
        'frontends': {k: list(v) for k, v in FRONTENDS.items()},
        'lease': str(LEASE.relative_to(ROOT)), 'lease_owner': OWNER,
        'cache_history': 'Workers persist across cells; a fresh seed per cell gives new user contexts. Phase A runs on worker 1 alone; worker 2 joins at the scale-up.',
        'concurrent_work': 'Live presenter demos in dynamo-ft-r610-f2bd6ac3-demo on cp-0124/cp-0198 are untouched; this campaign uses only cp-0942 GPU0/2/4/6 plus shared node CPU, EFS and network',
        'measurement_class': 'Synthetic coding-agent-shaped load; N=1 per cell, fixed order, workers persist across cells',
        'parameter_authorization': 'User approved the synthetic plan and GPU use on November 7, 2026',
        'supersedes': ('a1, stopped after 1w-64: with session-turns stddev 4 the pinned user-centric scheduler gave '
                       'virtually aged users the average remaining turns, so 4 of 32 users in 1w-32 raised ValueError '
                       'every turn for up to ~330 s; a2 fixed sessions at 12 turns. a2 completed 1w-32/1w-64/1w-128 '
                       'cleanly, then its second worker stayed Unschedulable for 2700 s: the template podAntiAffinity '
                       '(feature-test-role=agg, kubernetes.io/hostname) forbids two workers on cp-0942. a3 removes that '
                       'rule and is otherwise identical to a2, with the same profiles and seeds.')}
    write(run.path / 'campaign.json', value)
    for workers in (1, 2):
        write(run.path / f'deployment-{workers}w.json', deployment(run, workers))
    write(run.path / 'cells.json', cells)
    location = json.loads(LOCATION.read_text())
    result = subprocess.run([location['dependency_python'], '-I', str(HERE / 'profiles.py'),
                             '--archive', location['pinned_source_archive'], '--sha256', location['pinned_source_sha256'],
                             '--cells', str(run.path / 'cells.json'), '--output', str(run.path)],
                            capture_output=True, text=True, timeout=900, env={**os.environ, 'HF_HUB_OFFLINE': '1'})
    assert result.returncode == 0, result.stderr[-3000:]
    write(run.path / 'profile-rendering.json', json.loads(result.stdout.strip().splitlines()[-1]))
    rrkv = HERE.parent / 'rr-kv'
    old = HERE.parent / 'round-robin'
    paths = [Path(__file__), HERE / 'controller.py', HERE / 'profiles.py', HERE / 'dataset_check.py',
             rrkv / 'campaign.py', rrkv / 'discovery.py', C32 / 'ready.py',
             old / 'execute_pair.py', old / 'cluster.py', old / 'qualify_client.py',
             old / 'router-extension-candidates' / 'two-worker-round-robin-template.yaml',
             ROOT / 'configs/super-vl-tp2-lock.json', LOCATION, Path(location['pinned_source_archive']),
             REFERENCE / 'campaign.json', REFERENCE / 'expected-probes.json']
    paths += [ROOT / 'scripts' / name for name in ['testlib.py', 'storage_tests.py', 'serving_tests.py', 'feature_tests.py',
                                                   'common_runtime_tests.py', 'common_runtime_build.py', 'gpu_claims.py']]
    paths += [p for p in run.path.iterdir() if p.is_file() and p.name not in ['state.json', '.state.lock']
              and not p.name.startswith(('command-', 'check-', 'manifest-'))]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in paths})
    (run.path / 'campaign.sha256').write_text(sha(run.path / 'campaign.json') + '\n')
    verify(run)
    e.status(run, 'Frozen synthetic scale-out campaign; no cluster resources created')


def loadgen(run):
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'rr-loadgen'}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 86400, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': NODE}, 'imagePullSecrets': [{'name': 'common-runtime-pull'}],
        'containers': [{'name': 'loadgen', 'image': run.state['model_lock']['runtime_image'], 'command': ['sleep', '86400'],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
            'resources': {'requests': {'cpu': '4', 'memory': '64Gi', 'ephemeral-storage': '40Gi'},
                          'limits': {'cpu': '8', 'memory': '96Gi', 'ephemeral-storage': '80Gi'}},
            'volumeMounts': [{'name': 'cache', 'mountPath': '/model-cache'}]}],
        'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    run.wait_pod('rr-loadgen', timeout=300)


def prepare(run):
    verify(run)
    assert not run.state['checks'].get('synthetic-cpu-prepared'), 'CPU preparation already attempted'
    c.prepare_storage(run)
    c.copy_pull_secret(run)
    for workers in (1, 2):
        path = run.path / f'deployment-{workers}w.json'
        run.k('apply', '--dry-run=client', '-f', str(path))
        run.k('apply', '--dry-run=server', '-f', str(path))
    program = '''import hashlib,importlib.metadata as m,json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK']);home=Path(os.environ['HF_HOME'])
model=home/'hub'/('models--'+lock['model'].replace('/','--'));root=model/'snapshots'/lock['revision']
assert (model/'refs/main').read_text().strip()==lock['revision'],'Offline model ref differs from pinned revision'
checks={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['config.json','tokenizer_config.json','model.safetensors.index.json']}
assert all(checks[name]==lock['model_metadata_sha256'][name] for name in checks)
files=set(json.loads((root/'model.safetensors.index.json').read_text())['weight_map'].values())
assert len(files)==88 and sum((root/name).stat().st_size for name in files)==int(os.environ['WEIGHT_BYTES'])
print(json.dumps({'metadata_sha256':checks,'weight_files':len(files),'packages':{name:m.version(name) for name in ['ai-dynamo','vllm','torch','transformers']}}))
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'synthetic-model-check'}, 'spec': {
        'restartPolicy': 'Never', 'activeDeadlineSeconds': 300, 'automountServiceAccountToken': False,
        'nodeSelector': {'kubernetes.io/hostname': NODE}, 'imagePullSecrets': [{'name': 'common-runtime-pull'}],
        'containers': [{'name': 'check', 'image': run.state['model_lock']['runtime_image'], 'command': ['python3', '-c', program],
            'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                    {'name': 'HF_HOME', 'value': '/model-cache/feature-tests/20261015-super-vl-tp2/hf'},
                    {'name': 'MODEL_LOCK', 'value': json.dumps(run.state['model_lock'])},
                    {'name': 'WEIGHT_BYTES', 'value': str(spec(run)['checkpoint_weight_bytes'])}],
            'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'cpu': '2', 'memory': '4Gi'}},
            'volumeMounts': [{'name': 'cache', 'mountPath': '/model-cache', 'readOnly': True}]}],
        'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    try:
        result = run.wait_pod('synthetic-model-check', completed=True, timeout=360)
        value = json.loads(run.k('logs', 'synthetic-model-check', '-n', run.ns).stdout)
        value['image_id'] = result['status']['containerStatuses'][0]['imageID']
        assert value['image_id'].endswith(run.state['model_lock']['runtime_image'].split('@')[1])
        write(run.path / 'runtime-inspection.json', value)
    finally:
        run.k('delete', 'pod', 'synthetic-model-check', '-n', run.ns, '--wait=true', '--timeout=90s')
    loadgen(run)
    client = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    write(run.path / 'client-identity.json', {'uid': client['metadata']['uid'], 'node': client['spec']['nodeName']})
    run.result('synthetic-cpu-prepared', 'passed', scope='Storage, pull secret, server dry-runs, model/image check, CPU client')


def client_run(run, script, *argv, timeout=900):
    env = ['env', *[f'{k}={v}' for k, v in CLIENT_ENV.items()]]
    return run.k('exec', 'rr-loadgen', '-n', run.ns, '--', *env, e.PY, script, *argv, timeout=timeout)


def qualify_cpu(run):
    verify(run)
    assert run.state['checks']['synthetic-cpu-prepared']['status'] == 'passed'
    assert not run.state['checks'].get('synthetic-cpu-qualified'), 'Do not replay CPU qualification'
    dest = run.path / 'cpu-qualification'
    dest.mkdir(exist_ok=False)
    location = json.loads(LOCATION.read_text())
    data = Path(location['pinned_source_archive']).read_bytes()
    assert hashlib.sha256(data).hexdigest() == location['pinned_source_sha256']
    program = '''import base64,hashlib,json,sys,tarfile
from pathlib import Path
root=Path('/tmp/workshop-rr');root.mkdir(exist_ok=True)
data=base64.b64decode(sys.stdin.read());assert hashlib.sha256(data).hexdigest()==sys.argv[1]
archive=root/'pinned-source.tar.gz';archive.write_bytes(data)
source=root/'aiperf-source';source.mkdir(exist_ok=False)
with tarfile.open(archive) as tf:tf.extractall(source,filter='data')
print(json.dumps({'source_archive_sha256':sys.argv[1],'source':str(source)}))
'''
    staged = run.k('exec', '-i', 'rr-loadgen', '-n', run.ns, '--', 'python3', '-c', program, location['pinned_source_sha256'],
                   input_text=base64.b64encode(data).decode(), timeout=240)
    (dest / 'staging.json').write_text(staged.stdout)
    e.status(run, 'Bootstrapping the pinned AIPerf client environment; no GPU lease held')
    bootstrap = run.k('exec', 'rr-loadgen', '-n', run.ns, '--', 'uv', 'sync', '--project', e.REMOTE + '/aiperf-source',
                      '--frozen', '--no-dev', '--no-default-groups', timeout=900)
    (dest / 'bootstrap.log').write_text(bootstrap.stdout + bootstrap.stderr)
    tokenizer = '''import json,os
from pathlib import Path
hf=Path('/tmp/workshop-rr/hf');(hf/'hub').mkdir(parents=True,exist_ok=True)
model=hf/'hub/models--nvidia--NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'
if not model.exists():model.symlink_to('/model-cache/feature-tests/20261015-super-vl-tp2/hf/hub/models--nvidia--NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4',target_is_directory=True)
os.environ.update(HF_HOME=str(hf),HF_HUB_CACHE=str(hf/'hub'),HF_HUB_OFFLINE='1')
from transformers import AutoTokenizer
t=AutoTokenizer.from_pretrained('nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4',revision='8a115b9d966adce8c059a7bcf47f49a1e57957d8',local_files_only=True)
print(json.dumps({'tokenizer':type(t).__name__,'vocab_size':t.vocab_size}))
'''
    (dest / 'tokenizer.json').write_text(e.client(run, tokenizer, timeout=600).stdout)
    environment = e.client(run, "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()},sort_keys=True))")
    (dest / 'client-environment.json').write_text(environment.stdout)
    remote = e.REMOTE + '/preparation'
    e.upload(run, HERE / 'dataset_check.py', remote + '/dataset_check.py')
    validate = '''import json,sys
from pathlib import Path
from aiperf.config import load_config
from aiperf.config.loader import build_benchmark_plan
out={}
for path in sys.argv[1:]:
 cfg=load_config(Path(path));build_benchmark_plan(cfg);p=cfg.benchmark.phases[0]
 out[Path(path).name]={'type':str(p.type),'users':p.users,'rate':p.rate,'duration':p.duration}
print(json.dumps(out))
'''
    for name in PROFILES:
        e.upload(run, run.path / f'profile-{name}.yaml', f'{remote}/profile-{name}.yaml')
    plans = e.client(run, validate, argv=tuple(f'{remote}/profile-{name}.yaml' for name in PROFILES), timeout=300)
    write(dest / 'profile-plans.json', json.loads(plans.stdout.strip().splitlines()[-1]))
    largest = max(PROFILES, key=lambda name: parse(name)[2])
    timing = client_run(run, remote + '/dataset_check.py', f'{remote}/profile-{largest}.yaml')
    value = json.loads(timing.stdout.strip().splitlines()[-1])
    assert value['conversations'] == 1000 and not value['tokenizer_override']
    write(dest / 'dataset-generation.json', value)
    run.result('synthetic-cpu-qualified', 'passed', dataset_seconds=value['dataset_seconds'],
               scope='Pinned AIPerf environment, offline tokenizer, every profile planned, largest dataset generated; zero requests')


def wait_frontend_model(run, base, folder):
    """Observe the exact frontend model before inference; preserve failed polls."""
    program = (C32 / 'ready.py').read_text()
    result = e.client(run, program, argv=(base, e.MODEL, '--timeout', '120', '--interval', '1'), timeout=150, check=False)
    (folder / 'frontend-model-readiness-output.txt').write_text(result.stdout + result.stderr)
    receipt = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {
        'passed': False, 'error': 'Readiness client returned no JSON receipt', 'exit_code': result.returncode}
    write(folder / 'frontend-model-readiness.json', receipt)
    if result.returncode or receipt.get('passed') is not True or receipt.get('expected_model') != e.MODEL:
        raise RuntimeError('Expected frontend model was not advertised before the bounded startup gate.')


def forced_length(run, base, folder):
    program = '''import json,sys,urllib.request
payload={'model':sys.argv[2],'messages':[{'role':'user','content':'Write a long Python module for a task queue.'}],
 'max_tokens':64,'ignore_eos':True,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
req=urllib.request.Request(sys.argv[1]+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=300) as r:value=json.load(r)
print(json.dumps({'usage':value.get('usage'),'finish_reason':value['choices'][0].get('finish_reason')}))
'''
    value = json.loads(e.client(run, program, argv=(base, e.MODEL), timeout=360).stdout.strip().splitlines()[-1])
    write(folder / 'forced-length.json', value)
    assert value['usage']['completion_tokens'] == 64, 'Frontend does not honor ignore_eos; output length would not be forced'


def frontends(run, folder):
    pods = json.loads((folder / 'pods.json').read_text())['items']
    found = {}
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('nvidia.com/dynamo-component-type') != 'frontend':
            continue
        args = pod['spec']['containers'][0].get('args', [])
        mode = args[args.index('--router-mode') + 1]
        kind = next(k for k, (_, m) in FRONTENDS.items() if m == mode)
        assert kind not in found, 'Two frontend Pods with one router mode'
        found[kind] = pod
    assert set(found) == set(FRONTENDS), 'Expected one RR and one KV frontend Pod'
    return found


def endpoints(run, folder):
    pods = frontends(run, folder)
    services = run.get('get', 'services', '-n', run.ns)['items']

    def selects(service, pod):
        labels = pod['metadata'].get('labels', {})
        selector = service['spec'].get('selector') or {}
        return bool(selector) and all(labels.get(k) == v for k, v in selector.items())

    value = {}
    for kind, pod in pods.items():
        other = next(p for k, p in pods.items() if k != kind)
        # A Service that also selects the other frontend cannot identify a router mode.
        matches = [s for s in services if selects(s, pod) and not selects(s, other) and
                   any(p['port'] == 8000 for p in s['spec'].get('ports', []))]
        assert len(matches) == 1, f'Expected one port-8000 Service for the {kind} frontend, found {len(matches)}'
        value[kind] = f'http://{matches[0]["metadata"]["name"]}.{run.ns}.svc.cluster.local:8000'
    return value, pods


def qualify_topology(run, pods, label):
    folder = run.path / label
    found, frontend_pods = endpoints(run, folder)
    smoke = {}
    for kind, base in found.items():
        sub = folder / ('frontend-' + kind)
        sub.mkdir(exist_ok=False)
        wait_frontend_model(run, base, sub)
        smoke[kind] = e.smoke(run, base, len(pods), f'{label}/frontend-{kind}', require_distribution=kind == 'rr')
    forced_length(run, found['rr'], folder)
    if len(pods) == 2:
        e.collect_workers(run, label)
        name = frontend_pods['kv']['metadata']['name']
        path = folder / (name + '.log')
        proof = c.discovery.inspect(path.read_text(), [p['status']['podIP'] for p in pods], smoke['kv'], 'kv')
        proof.update(frontend_uid=frontend_pods['kv']['metadata']['uid'], log_sha256=sha(path))
        write(folder / 'discovery-qualification.json', proof)
        assert proof['passed'], proof['errors']
    write(folder / 'endpoints.json', {'endpoints': found, 'smoke_worker_ids': smoke})
    return found


def verify_workers(run, pods, folder, workers):
    expected = worker_container(run, workers)
    probes = json.loads((run.path / 'expected-probes.json').read_text())
    seen = {}
    for pod in pods:
        name = pod['metadata']['name']
        container = pod['spec']['containers'][0]
        c.verify_allocation(run, pod, container, 2)
        assert container['args'] == expected['args'] and container['image'] == expected['image']
        assert all(container.get(key) == value for key, value in probes.items())
        env = {v['name']: v.get('value') for v in container.get('env', [])}
        assert env.get('DYN_HEALTH_CHECK_ENABLED') == 'false' and 'DYN_CANARY_WAIT_TIME' not in env
        assert all(v['restartCount'] == 0 and v['imageID'].endswith(spec(run)['model_lock']['runtime_image'].split('@')[1])
                   for v in pod['status']['containerStatuses'])
        text = (folder / (name + '.log')).read_text()
        assert 'running in text-only mode' in text
        assert set(re.findall(r'health_check_enabled=(\w+)', text)) == {'false'}, 'Canary health checks are not disabled'
        assert re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)', text)
        cache_lines = [line for line in text.splitlines() if 'GPU KV cache size:' in line or 'Available KV cache memory:' in line]
        assert cache_lines, 'Missing actual KV capacity during engine qualification'
        assert pod['spec']['nodeName'] == NODE
        result = run.k('exec', name, '-n', run.ns, '-c', 'main', '--', 'nvidia-smi',
                       '--query-gpu=index,uuid,name,memory.total,driver_version', '--format=csv,noheader')
        (folder / ('gpu-visible-' + name + '.csv')).write_text(result.stdout)
        uuids = sorted(line.split(',')[1].strip() for line in result.stdout.strip().splitlines())
        assert len(uuids) == 2 and set(uuids) <= set(GPUS[NODE]) and all('H100' in line for line in result.stdout.splitlines())
        seen[name] = {'uid': pod['metadata']['uid'], 'gpu_uuids': uuids, 'cache_capacity_logs': cache_lines}
    assert len(seen) == workers and len({u for v in seen.values() for u in v['gpu_uuids']}) == 2 * workers
    write(folder / 'worker-qualification.json', {'passed': True, 'workers': seen, 'max_num_seqs': MAX_SEQS,
          'health_check_enabled': False, 'campaign_sha256': sha(run.path / 'campaign.json')})


def free_for_second_worker(run, folder):
    """Our four UUIDs may only be held by this namespace's own claims before the scale-up."""
    wanted = set(GPUS[NODE])
    identities = {}
    for item in run.get('get', 'resourceslices')['items']:
        if item['spec'].get('driver') != 'gpu.nvidia.com':
            continue
        for device in item['spec'].get('devices', []):
            attrs = device.get('attributes', device.get('basic', {}).get('attributes', {}))
            uuid = attrs.get('uuid', {}).get('string')
            if uuid in wanted:
                identities[(item['spec']['pool']['name'], device['name'])] = uuid
    conflicts = []
    for claim in run.get('get', 'resourceclaims', '-A')['items']:
        for device in claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', []):
            uuid = identities.get((device.get('pool'), device.get('device')))
            if uuid and claim['metadata']['namespace'] != run.ns:
                conflicts.append({'gpu_uuid': uuid, 'namespace': claim['metadata']['namespace'], 'claim': claim['metadata']['name']})
    write(folder / 'allocation-preflight.json', {'at': e.now(), 'conflicts': conflicts, 'scope': 'Claims outside this namespace'})
    assert not conflicts, 'A reserved GPU is held outside this campaign: ' + repr(conflicts)


def startup_timing(folder, applied, pods):
    value = {'applied_at': applied, 'workers': []}
    for pod in pods:
        ready = next(x['lastTransitionTime'] for x in pod['status']['conditions'] if x['type'] == 'Ready')
        value['workers'].append({'name': pod['metadata']['name'], 'uid': pod['metadata']['uid'],
                                 'created_at': pod['metadata']['creationTimestamp'], 'ready_at': ready})
    write(folder / 'startup-timing.json', value)


def healthy(run, pods):
    current = e.workers(run)
    assert {p['metadata']['uid'] for p in current} == {p['metadata']['uid'] for p in pods}, 'Worker identity changed'
    for pod in current:
        assert all(s['restartCount'] == 0 and s.get('ready') for s in pod['status']['containerStatuses']), 'Worker restarted or not ready'
    return current


def seal(run, name, pods, base):
    workers, kind, agents = parse(name)
    profile = yaml.safe_load((run.path / f'profile-{name}.yaml').read_text())
    bench = profile['benchmark']
    bench['endpoint']['urls'] = [base]
    bench['artifacts']['dir'] = f'{e.REMOTE}/runs/{name}/artifacts'
    assert bench['serverMetrics']['discovery'] == {'mode': 'disabled'}
    bench['serverMetrics']['urls'] = [f'http://{p["status"]["podIP"]}:9090' for p in pods]
    path = run.path / name / 'profile.yaml'
    path.write_text(yaml.safe_dump(profile, sort_keys=False))
    metadata = {'sealed_at': e.now(), 'cell': name, 'workers': workers, 'h100_gpus': 2 * workers, 'frontend': kind,
        'router_mode': FRONTENDS[kind][1], 'agents': agents, 'offered_request_rate': agents / GAP_SECONDS,
        'offered_output_tokens_per_second': agents / GAP_SECONDS * OUTPUT_TOKENS, 'model': e.MODEL, 'model_revision': e.REV,
        'runtime_image': run.state['model_lock']['runtime_image'], 'aiperf_commit': spec(run)['aiperf_commit'],
        'frozen_profile_sha256': sha(run.path / f'profile-{name}.yaml'), 'profile_sha256': sha(path),
        'campaign_sha256': sha(run.path / 'campaign.json'), 'max_num_seqs_per_worker': MAX_SEQS,
        'worker_pods': [{'name': p['metadata']['name'], 'uid': p['metadata']['uid'], 'node': p['spec']['nodeName'],
                         'ip': p['status']['podIP']} for p in pods]}
    with (run.path / name / 'spec.json').open('x') as stream:
        json.dump(metadata, stream, indent=2)
    e.upload(run, path, f'{e.REMOTE}/runs/{name}/profile.yaml')


def client_sample(run, name, label):
    program = '''import json
from pathlib import Path
r=Path('/sys/fs/cgroup');names=['cpu.stat','cpu.max','memory.current','memory.peak','memory.events']
print(json.dumps({name:(r/name).read_text() for name in names if (r/name).exists()}))
'''
    write(run.path / name / ('client-' + label + '.json'), json.loads(e.client(run, program).stdout))


def export(run, name):
    found = [p for p in (run.path / name / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
    assert len(found) == 1, 'Missing or ambiguous AIPerf export'
    return json.loads(found[0].read_text())


def accept(run, name, outcome):
    _, _, agents = parse(name)
    data = export(run, name)
    metric = lambda key, stat='avg': (data.get(key) or {}).get(stat)
    requests = metric('request_count') or 0
    errors = metric('error_request_count') or 0
    value = {'cell': name, 'agents': agents, 'exit_code': outcome.get('exit_code'),
        'offered_request_rate': agents / GAP_SECONDS, 'request_rate': metric('request_throughput'),
        'requests': requests, 'request_errors': errors, 'error_summary': data.get('error_summary'),
        'output_tokens_per_second': metric('output_token_throughput'),
        'output_tokens_per_second_per_user': metric('output_token_throughput_per_user'),
        'ttft_p50_ms': metric('time_to_first_token', 'p50'), 'ttft_p90_ms': metric('time_to_first_token', 'p90'),
        'itl_p50_ms': metric('inter_token_latency', 'p50'), 'itl_p90_ms': metric('inter_token_latency', 'p90'),
        'output_sequence_length_mean': metric('output_sequence_length'),
        'is_complete': data.get('is_complete'), 'was_cancelled': data.get('was_cancelled'),
        'scope': 'Whole-run AIPerf summary including cold first turns; the 180-540 s window analysis is separate'}
    records = [json.loads(line).get('metadata', {}) for p in (run.path / name / 'raw').rglob('profile_export.jsonl')
               for line in p.read_text().splitlines()]
    cancelled = sum(bool(r.get('was_cancelled')) for r in records
                    if r.get('phase_kind', r.get('benchmark_phase')) == 'profiling')
    length = value['output_sequence_length_mean']
    forced = bool(length) and abs(length - OUTPUT_TOKENS) <= 0.05 * OUTPUT_TOKENS
    complete = outcome.get('exit_code') == 0 and data.get('is_complete') is True and data.get('was_cancelled') is False
    clean = complete and requests > 0 and not errors and not cancelled and not data.get('error_summary') and forced
    # As in C32, request errors, cancellations or an unforced length mark a stress observation, not a stop.
    value.update(cancelled_profile_records=cancelled, output_length_forced=forced,
                 outcome='clean' if clean else 'stress_observation')
    try:
        value['window_180_540s'] = window_stats(run, name)
    except (ValueError, KeyError, StopIteration) as error:
        value['window_180_540s'] = {'error': repr(error)}
    write(run.path / name / 'summary.json', value)
    run.result('cell-' + name, 'completed' if complete else 'failed', **value)
    assert complete, 'AIPerf process failed or its export is incomplete; preserve and stop'
    return value


def run_cell(run, name, pods, found):
    verify(run)
    workers, kind, agents = parse(name)
    assert len(pods) == workers
    folder = run.path / name
    folder.mkdir(exist_ok=False)
    current = healthy(run, pods)
    e.collect_workers(run, name)
    base = found[kind]
    seal(run, name, current, base)
    e.collect_frontend_metrics(run, base, name, 'before')
    client_sample(run, name, 'before')
    e.status(run, 'Synthetic cell running', cell=name, agents=agents, frontend=kind, workers=workers)
    e.telemetry_start(run, current, name)
    try:
        e.launch_profile(run, name)
        outcome = e.poll_profile(run, name)
    finally:
        e.telemetry_stop(run, name)
    client_sample(run, name, 'after')
    e.collect_frontend_metrics(run, base, name, 'after')
    e.collect_workers(run, name)
    e.collect_profile(run, name)
    healthy(run, pods)
    value = accept(run, name, outcome)
    write(folder / 'integrity-final.json', {'sha256': {str(p.relative_to(folder)): sha(p)
          for p in folder.rglob('*') if p.is_file() and p.name != 'integrity-final.json'}})
    return value


def window_stats(run, name):
    """Completed-request rate and TTFT p90 over the analysis window, as analyze.py computes them."""
    raw = run.path / name / 'raw'
    records = [json.loads(line) for p in raw.rglob('profile_export.jsonl') for line in p.read_text().splitlines()]
    records = [r for r in records if r.get('metadata', {}).get('phase_kind', r.get('metadata', {}).get('benchmark_phase'))
               == 'profiling' and not r['metadata'].get('was_cancelled')]
    exports = list(raw.rglob('server_metrics_export.json'))
    start = (json.loads(exports[0].read_text())['summary']['phase_time_ranges']['profiling']['start_ns'] if exports
             else min(r['metadata']['request_start_ns'] for r in records))
    begin, end = start + WINDOW['analysis_start_seconds'] * 1e9, start + WINDOW['duration_seconds'] * 1e9
    completed = [r for r in records if begin <= r['metadata']['request_end_ns'] < end]
    ttft = sorted(r['metrics']['time_to_first_token']['value'] for r in records
                  if begin <= r['metadata']['request_start_ns'] < end and r['metrics'].get('time_to_first_token'))
    return {'request_rate': len(completed) / ((end - begin) / 1e9), 'requests_completed': len(completed),
            'ttft_p90_ms': ttft[int(0.9 * (len(ttft) - 1))] if ttft else None}


def cells(run):
    verify(run)
    assert run.state['checks']['synthetic-cpu-qualified']['status'] == 'passed'
    with (run.path / 'cells-started.json').open('x') as stream:
        json.dump({'at': e.now(), 'campaign_sha256': sha(run.path / 'campaign.json')}, stream)
    e.acquire(run, 600)
    try:
        start = run.path / 'startup-1w'
        start.mkdir(exist_ok=False)
        assert not e.workers(run) and not run.get('get', 'resourceclaims', '-n', run.ns)['items']
        c.allocation_available(run, 'startup-1w')
        applied = e.now()
        e.status(run, 'Starting worker 1 and both frontends')
        run.apply(json.loads((run.path / 'deployment-1w.json').read_text())['items'])
        pods = e.wait_serving(run, 1, 'startup-1w')
        e.collect_workers(run, 'startup-1w')
        startup_timing(start, applied, pods)
        verify_workers(run, pods, start, 1)
        found = qualify_topology(run, pods, 'startup-1w')
        for name in PHASE_A:
            run_cell(run, name, pods, found)
        scale = run.path / 'scale-up'
        scale.mkdir(exist_ok=False)
        free_for_second_worker(run, scale)
        first = {p['metadata']['uid'] for p in pods}
        applied = e.now()
        e.status(run, 'Scaling workers 1 -> 2')
        run.apply(json.loads((run.path / 'deployment-2w.json').read_text())['items'])
        pods = e.wait_serving(run, 2, 'scale-up')
        assert first <= {p['metadata']['uid'] for p in pods}, 'Scale-up replaced worker 1'
        e.collect_workers(run, 'scale-up')
        startup_timing(scale, applied, [p for p in pods if p['metadata']['uid'] not in first])
        verify_workers(run, pods, scale, 2)
        found = qualify_topology(run, pods, 'scale-up')
        for name in PHASE_B:
            run_cell(run, name, pods, found)
        run.result('synthetic-cells', 'completed', phase_a=PHASE_A, phase_b=PHASE_B)
    except BaseException as error:
        run.result('synthetic-cells', 'failed', error=repr(error))
        raise
    finally:
        final = run.path / 'final-workers'
        final.mkdir(exist_ok=True)
        try:
            e.collect_workers(run, 'final-workers')
        finally:
            c.cleanup_gpu(run, 'cells-cleanup.json')


def finalize(run):
    verify(run)
    assert run.state['checks']['synthetic-cells']['status'] == 'completed'
    c.cleanup_gpu(run)
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    assert pod['metadata']['uid'] == json.loads((run.path / 'client-identity.json').read_text())['uid']
    assert pod['metadata']['labels']['feature-test-run'] == run.ns
    run.k('delete', 'pod', 'rr-loadgen', '-n', run.ns, '--wait=true', '--timeout=120s', timeout=150)
    for kind in ['pods', 'resourceclaims', 'dgd']:
        assert not run.get('get', kind, '-n', run.ns)['items'], kind
    write(run.path / 'qualification.json', {'passed': True, 'cleanup_verified': True, 'scoped_lease_absent': not LEASE.exists(),
          'scope': 'Execution and collection; per-cell acceptance is in each cell summary'})
    e.status(run, 'All synthetic cells recorded and resources cleaned; analysis pending')
    write(run.path / 'evidence-sha256.json', {str(p.relative_to(run.path)): sha(p)
          for p in run.path.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'verify', 'prepare', 'qualify-cpu', 'cells', 'finalize', 'cleanup'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = setup(args.run)
    if args.action == 'freeze':
        freeze(run)
        return
    verify(run)
    if args.action == 'prepare':
        prepare(run)
    elif args.action == 'qualify-cpu':
        qualify_cpu(run)
    elif args.action == 'cells':
        cells(run)
    elif args.action == 'finalize':
        finalize(run)
    elif args.action == 'cleanup':
        c.cleanup_gpu(run, 'manual-cleanup.json')
    else:
        e.status(run, 'Frozen synthetic campaign inputs verified')


if __name__ == '__main__':
    main()
