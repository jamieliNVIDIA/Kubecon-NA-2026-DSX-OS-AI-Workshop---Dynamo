#!/usr/bin/env python3
"""AgentX C32 one-worker round-robin cell with health canaries off: the missing arm of the C32 comparison.

Reuses the November 5 C32 campaign module and narrows it to its one-worker configuration. The worker's node
(cp-0942 instead of cp-0198) and its health-check environment are the only manifest changes; freeze() proves it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
C32 = ROOT / 'reports/overnight-2026-11-04/routing-c32'
module_spec = importlib.util.spec_from_file_location('routing_c32_campaign', C32 / 'campaign.py')
r = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(r)
c, e = r.c, r.e
REFERENCE = ROOT / 'results/workshop-routing-c32-20261105-a1'
LEASE = ROOT / '.local/workshop-agentx-c32-one-worker-20261108-a1.gpu-lease'
OWNER = '/root/agentx_c32_one_worker'
NAMESPACE = 'dynamo-ft-agentx-c32-one-worker-20261108-a1'
NODE = 'kubecon-nke-site-cp-0942'
# cp-0942 GPU0/2 was the second worker in both accepted C32 two-worker cells. The original one-worker pair,
# cp-0198 GPU0/2, is held by the presenter MX target.
GPUS = {NODE: ['GPU-c15ae016-71f1-03bc-0228-624adbb1b4e8', 'GPU-4aacb1e1-a109-70bb-6b72-8071d736ba75']}
CONFIG, CONCURRENCY = 'one-rr', 32
ARM = f'{CONFIG}-c{CONCURRENCY}-a1'
REMOVED_ENV = ('DYN_CANARY_WAIT_TIME', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT')
# Frozen C32 inputs that changed afterwards. None alters worker arguments, the profile, primer or acceptance.
HARNESS_CHANGES = {
    'reports/overnight-2026-11-04/routing-c32/campaign.py': 'freeze() lists the readiness test at its new tests/routing/ path',
    'reports/workshop-measurements-20261030/rr-kv/campaign.py': 'freeze() lists the discovery test at its new tests/routing/ path',
    'scripts/common_runtime_build.py': 'NGC credential lookup reads the host Docker configuration portably',
    'scripts/common_runtime_tests.py': 'The pull secret may come from a configured source secret',
}
MOVED_TESTS = {'tests/test_routing_model_readiness.py': 'tests/routing/test_model_readiness.py',
               'tests/test_rrkv_discovery.py': 'tests/routing/test_discovery.py'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def spec(run):
    return json.loads((run.path / 'campaign.json').read_text())


def setup(path):
    c.NAMESPACE = r.NAMESPACE = NAMESPACE
    c.LEASE = r.LEASE = LEASE
    c.OWNER = r.OWNER = OWNER
    c.GPUS = GPUS
    c.CPU_NODE = NODE
    # The C32 module reads these at call time, so its cell, finalize and CPU qualification run this campaign.
    r.CONFIGS = {CONFIG: (1, 'round-robin')}
    r.verify = c.verify = verify
    r.verify_workers = verify_workers
    return c.setup(path)


def manifest(run):
    value = c.generated(run, 'round-robin')
    for obj in value['items']:
        if obj['kind'] != 'DynamoGraphDeployment':
            continue
        for component in obj['spec']['components']:
            pod = component['podTemplate']['spec']
            pod['activeDeadlineSeconds'] = 21600
            if component['type'] != 'worker':
                continue
            component['replicas'] = 1
            container = pod['containers'][0]
            args = container['args']
            args[args.index('--max-num-seqs') + 1] = str(r.MAX_SEQS)
            # A load test, not a startup test (user decision, November 7, 2026). The C32 one-worker attempt was
            # restarted by liveness when queued canaries exceeded their 180 s deadline during the primer.
            container['env'] = [v for v in container['env'] if v['name'] not in REMOVED_ENV]
            container['env'].append({'name': 'DYN_HEALTH_CHECK_ENABLED', 'value': 'false'})
    return value


def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for key in sorted(set(a) | set(b)) for d in differences(a.get(key), b.get(key), f'{path}/{key}')]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f'{path}/{i}')]
    return [] if a == b else [{'path': path, 'c32': a, 'this': b}]


def reference_differences(run):
    """The C32 one-worker manifest, namespace normalized, against this one; only placement and health may differ."""
    old = json.loads((REFERENCE / 'campaign.json').read_text())['namespace']
    reference = json.loads((REFERENCE / 'deployment-one-rr.json').read_text().replace(old, run.ns))
    found = differences(reference, json.loads((run.path / 'deployment-one-rr.json').read_text()))
    allowed = (r'/items/\d+/spec/components/\d+/podTemplate/spec/affinity/nodeAffinity/.*/values/0',
               r'/items/\d+/spec/spec/devices/requests/0/exactly/selectors/0/cel/expression',
               r'/items/\d+/spec/components/\d+/podTemplate/spec/containers/0/env')
    unexpected = [d['path'] for d in found if not any(re.fullmatch(p, d['path']) for p in allowed)]
    assert not unexpected, 'Manifest differs from the C32 one-worker manifest beyond placement and health: ' + repr(unexpected)
    for d in found:
        if d['path'].endswith('/env'):
            kept = [v for v in d['c32'] if v['name'] not in REMOVED_ENV]
            assert d['this'] == kept + [{'name': 'DYN_HEALTH_CHECK_ENABLED', 'value': 'false'}], 'Unexpected worker env change'
        elif d['path'].endswith('/values/0'):
            assert d['c32'] == 'kubecon-nke-site-cp-0198' and d['this'] == NODE
        else:
            assert all(u in d['this'] for u in GPUS[NODE]) and len(re.findall(r'GPU-[0-9a-f-]+', d['this'])) == 2
    return found


def worker_container(run):
    items = json.loads((run.path / 'deployment-one-rr.json').read_text())['items']
    return next(x for obj in items if obj['kind'] == 'DynamoGraphDeployment'
                for x in obj['spec']['components'] if x['type'] == 'worker')['podTemplate']['spec']['containers'][0]


def verify(run):
    for name, digest in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert sha(ROOT / name) == digest, 'Frozen source changed: ' + name
    assert sha(run.path / 'campaign.json') == (run.path / 'campaign.sha256').read_text().strip()
    value = spec(run)
    assert value['loads'] == [CONCURRENCY] and value['max_num_seqs'] == r.MAX_SEQS
    assert value['model_lock'] == run.state['model_lock'] and value['gpu_uuids_by_node'] == GPUS
    assert reference_differences(run) == json.loads((run.path / 'reference-differences.json').read_text())
    assert sha(run.path / 'profile-c32.yaml') == sha(REFERENCE / 'profile-c32.yaml')


def freeze(run):
    assert not (run.path / 'campaign.json').exists(), 'Do not refreeze an attempted campaign'
    previous = json.loads((REFERENCE / 'inputs-sha256.json').read_text())
    changed = {name for name, digest in previous.items() if (ROOT / name).exists() and sha(ROOT / name) != digest}
    assert changed == set(HARNESS_CHANGES), 'Unreviewed change to a C32 input: ' + repr(sorted(changed ^ set(HARNESS_CHANGES)))
    assert {name for name in previous if not (ROOT / name).exists()} == set(MOVED_TESTS)
    prior = json.loads((REFERENCE / 'campaign.json').read_text())
    write(run.path / 'expected-probes.json', json.loads((REFERENCE / 'expected-probes.json').read_text()))
    value = {**prior, 'namespace': run.ns, 'loads': [CONCURRENCY], 'max_num_seqs': r.MAX_SEQS,
        'sequence': [{'configuration': CONFIG, 'concurrency': CONCURRENCY, 'arm': ARM}],
        'gpu_uuids_by_node': GPUS, 'cpu_node': NODE, 'lease': str(LEASE.relative_to(ROOT)), 'lease_owner': OWNER,
        'health': {'DYN_HEALTH_CHECK_ENABLED': 'false', 'removed': ['DYN_CANARY_WAIT_TIME=1', 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT=180'],
                   'authorization': 'User decision, November 7, 2026: the 1 s canary was a startup optimization, not a load-test setting',
                   'scope': 'This cell only; the accepted C32 two-worker cells ran with the canaries'},
        'reference_campaign': {'run': str(REFERENCE.relative_to(ROOT)), 'campaign_sha256': sha(REFERENCE / 'campaign.json'),
                               'profile_c32_sha256': sha(REFERENCE / 'profile-c32.yaml')},
        'harness_changes_since_c32': HARNESS_CHANGES,
        'concurrent_work': ('Presenter demos in dynamo-ft-r610-f2bd6ac3-demo hold cp-0124 GPU1/3 and cp-0198 GPU0/2; '
                            'this cell uses only cp-0942 GPU0/2 plus shared node CPU, EFS and network'),
        'cache_history': 'Fresh worker processes and private compiler caches; bounded smoke and the canonical AgentX primer precede the profile',
        'parameter_authorization': 'User requested the AgentX C32 one-worker cell on November 8, 2026',
        'cpu_client': 'New owned rr-loadgen in this namespace',
        'client_deadline_seconds': 86400, 'worker_deadline_seconds': 21600,
        'measurement_class': ('C32 one-worker RR cell, N=1, run November 8 for comparison with the accepted November 5 '
                              'two-worker pair; health canaries off in this cell only; worker on cp-0942 instead of cp-0198')}
    write(run.path / 'campaign.json', value)
    write(run.path / 'deployment-one-rr.json', manifest(run))
    write(run.path / 'reference-differences.json', reference_differences(run))
    (run.path / 'profile-c32.yaml').write_bytes((REFERENCE / 'profile-c32.yaml').read_bytes())
    paths = [ROOT / name for name in previous if not name.startswith(str(REFERENCE.relative_to(ROOT)) + '/')
             and name not in MOVED_TESTS]
    paths += [ROOT / name for name in MOVED_TESTS.values()]
    paths += [REFERENCE / name for name in ['campaign.json', 'deployment-one-rr.json', 'expected-probes.json',
                                            'profile-c32.yaml', 'model-lock.json', 'inputs-sha256.json']]
    paths += [Path(__file__), HERE / 'controller.py', HERE / 'PLAN.md',
              ROOT / 'reports/workshop-measurements-20261030/round-robin/analyze.py', C32 / 'analyze.py']
    paths += [p for p in run.path.iterdir() if p.is_file() and p.name not in ['state.json', '.state.lock']
              and not p.name.startswith(('command-', 'check-', 'manifest-'))]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))})
    (run.path / 'campaign.sha256').write_text(sha(run.path / 'campaign.json') + '\n')
    verify(run)
    e.status(run, 'Frozen AgentX C32 one-worker cell; no cluster resources created')


def verify_workers(run, config, pods, folder):
    assert config == CONFIG and len(pods) == 1
    expected = worker_container(run)
    probes = json.loads((run.path / 'expected-probes.json').read_text())
    actual = {}
    for pod in pods:
        name = pod['metadata']['name']
        container = pod['spec']['containers'][0]
        c.verify_allocation(run, pod, container, 2)
        assert container['args'] == expected['args'] and container['image'] == expected['image']
        assert all(container.get(key) == value for key, value in probes.items())
        env = {v['name']: v.get('value') for v in container.get('env', [])}
        assert env.get('DYN_HEALTH_CHECK_ENABLED') == 'false' and not set(REMOVED_ENV) & set(env)
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
        assert uuids == sorted(GPUS[NODE]) and all('H100' in line for line in result.stdout.splitlines())
        actual[NODE] = {'gpu_uuids': uuids, 'cache_capacity_logs': cache_lines, 'uid': pod['metadata']['uid']}
    value = {'passed': True, 'configuration': config, 'max_num_seqs': r.MAX_SEQS, 'health_check_enabled': False,
             'workers': actual, 'campaign_sha256': sha(run.path / 'campaign.json')}
    write(folder / 'worker-qualification.json', value)
    return value


def prepare(run):
    verify(run)
    assert not run.state['checks'].get('rrkv-cpu-prepared'), 'CPU preparation already attempted'
    c.prepare_storage(run)
    c.copy_pull_secret(run)
    path = run.path / 'deployment-one-rr.json'
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
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'agentx-model-check'}, 'spec': {
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
        result = run.wait_pod('agentx-model-check', completed=True, timeout=360)
        value = json.loads(run.k('logs', 'agentx-model-check', '-n', run.ns).stdout)
        value['image_id'] = result['status']['containerStatuses'][0]['imageID']
        assert value['image_id'].endswith(run.state['model_lock']['runtime_image'].split('@')[1])
        write(run.path / 'runtime-inspection.json', value)
    finally:
        run.k('delete', 'pod', 'agentx-model-check', '-n', run.ns, '--wait=true', '--timeout=90s')
    r.loadgen(run)
    client = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    write(run.path / 'client-identity.json', {'uid': client['metadata']['uid'], 'node': client['spec']['nodeName']})
    # The C32 CPU qualification requires this check name.
    run.result('rrkv-cpu-prepared', 'passed', scope='Storage, pull secret, server dry-run, model/image check, CPU client')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'verify', 'prepare', 'qualify-cpu', 'cell', 'finalize', 'cleanup'])
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
        r.validate_cpu(run)
    elif args.action == 'cell':
        r.configuration(run, CONFIG, CONCURRENCY)
    elif args.action == 'finalize':
        r.finalize(run)
    elif args.action == 'cleanup':
        c.cleanup_gpu(run, 'manual-cleanup.json')
    else:
        e.status(run, 'Frozen AgentX C32 one-worker inputs verified')


if __name__ == '__main__':
    main()
