#!/usr/bin/env python3
"""Fresh matched storage / MX weights / MX artifacts startup trial.

Derive a versioned compiled baseline from the qualified text-only health pair.
Prior frozen helpers, manifests and result trees are never changed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import text_only_health_startup as health

core = health.core
base = core.base
mx = core.previous
REFERENCE = ROOT / 'results/workshop-health-pullback-20261103-a1/verified/results/workshop-mx-startup-20261103-textonly-health01'
PROFILE = ROOT / 'configs/dgd/super-vl-textonly-fast-startup'
COMPILE_DIGEST = 'supervl-tp2-native1048576-seqs4-batch8192-textonly-e98d074e-baseline01'
ARMS = [('storage', 'target-native'), ('weights', 'target-p2p'), ('artifacts', 'target-artifacts')]


def write(path, value):
    core.write(path, value)


def worker(items):
    graph = next(x for x in items if x['kind'] == 'DynamoGraphDeployment')
    return next(x for x in graph['spec']['components'] if x['type'] == 'worker')['podTemplate']['spec']['containers'][0]


def derive(run, filename, native=False, artifacts=True):
    items = json.loads((REFERENCE / filename).read_text())['items']
    items = copy.deepcopy(items)
    base.relabel(items, run.ns)
    for item in items:
        item['metadata']['namespace'] = run.ns
    c = worker(items)
    c['startupProbe']['periodSeconds'] = 2
    c['startupProbe']['failureThreshold'] = 1800
    # Match the qualified receiver health settings on the seed as well.
    c['readinessProbe'] = copy.deepcopy(worker(json.loads((REFERENCE / 'target-fast-health.json').read_text())['items'])['readinessProbe'])
    c['env'] = [e for e in c['env'] if e['name'] != 'DYN_CANARY_WAIT_TIME']
    c['env'].append({'name': 'DYN_CANARY_WAIT_TIME', 'value': '1'})
    for e in c['env']:
        if e['name'] == 'MX_ARTIFACT_COMPILE_CONFIG_DIGEST':
            e['value'] = COMPILE_DIGEST
        elif e['name'] == 'MX_ARTIFACT_TRANSFER':
            e['value'] = '1' if artifacts else '0'
    if native:
        idx = c['args'].index('--load-format')
        assert c['args'][idx + 1] == 'modelexpress'
        del c['args'][idx:idx + 2]
        c['env'] = [e for e in c['env'] if not e['name'].startswith('MX_') and e['name'] != 'MODEL_EXPRESS_URL']
    return items


def manifests(run, role, native=False):
    name = 'source' if role == 'source' else 'target-native' if native else 'target-artifacts' if mx.MODE == 'artifacts' else 'target-p2p'
    return copy.deepcopy(json.loads((run.path / (name + '.json')).read_text())['items'])


def freeze(run):
    if (run.path / 'inputs-sha256.json').exists():
        verify(run)
        return
    assert not (run.path / 'spec.json').exists(), 'Preserve partial freeze; choose a new run'
    assert json.loads((REFERENCE / 'qualification.json').read_text())['passed']
    old = json.loads((REFERENCE / 'spec.json').read_text())
    assert run.state['model_lock'] == old['model_lock']
    old.update(schema=5, script_sha256=base.digest(__file__),
        compile_config_digest=COMPILE_DIGEST,
        sequence=['text-only-fast-source-bootstrap', 'storage', 'weights', 'artifacts'],
        comparison_group='One fixed-order matched storage / peer weights / peer weights-plus-artifacts trial',
        capability='text-only; all workers --language-model-only',
        receiver_arms=[{'name': name, 'manifest': filename + '.json'} for name, filename in ARMS],
        changed_worker_args=['--language-model-only'],
        health_scope='All seed/receiver workers use the qualified fast startup health policy; frontend unchanged',
        control_changes='Loading path and MX artifact transfer only differ between receiver arms',
        reference_qualification_sha256=base.digest(REFERENCE / 'qualification.json'),
        source_template=str(PROFILE / 'source.yaml'), target_template=str(PROFILE / 'target-weights.yaml'),
        source_load='idle except engine health/canary and one tiny correctness request',
        baseline_directory=str(PROFILE))
    PROFILE.mkdir(exist_ok=False)
    definitions = [('source', 'source.json', False, True),
                   ('target-native', 'target-fast-health.json', True, False),
                   ('target-p2p', 'target-fast-health.json', False, False),
                   ('target-artifacts', 'target-fast-health.json', False, True)]
    filenames = ['source.yaml', 'target-storage.yaml', 'target-weights.yaml', 'target-artifacts.yaml']
    for (name, template, native, artifacts), profile_name in zip(definitions, filenames):
        obj = {'apiVersion': 'v1', 'kind': 'List', 'items': derive(run, template, native, artifacts)}
        write(run.path / (name + '.json'), obj)
        # JSON is valid YAML, preserving string-valued environment settings.
        write(PROFILE / profile_name, obj)
    old['source_template_sha256'] = base.digest(PROFILE / 'source.yaml')
    old['target_template_sha256'] = base.digest(PROFILE / 'target-weights.yaml')
    write(run.path / 'spec.json', old)
    (run.path / 'spec.sha256').write_text(base.digest(run.path / 'spec.json') + '\n')
    write(run.path / 'coordinator.json', {'apiVersion': 'v1', 'kind': 'List', 'items': mx.coordinator_objects(run)})
    write(PROFILE / 'coordinator.yaml', json.loads((run.path / 'coordinator.json').read_text()))
    write(PROFILE / 'profile.json', {'schema': 1, 'run': str(run.path.relative_to(ROOT)),
        'namespace': run.ns, 'spec_sha256': base.digest(run.path / 'spec.json'),
        'scope': old['comparison_group'], 'status': 'frozen; not yet deployed'})
    paths = [Path(__file__), Path(health.__file__), Path(core.__file__), Path(mx.__file__), Path(base.__file__),
             core.MX / 'analyze_startup.py', ROOT / 'configs/super-vl-tp2-lock.json',
             ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh']
    paths += [ROOT / 'scripts' / name for name in ['testlib.py', 'storage_tests.py', 'common_runtime_tests.py',
        'common_runtime_build.py', 'serving_tests.py', 'gpu_claims.py', 'feature_tests.py']]
    paths += [run.path / name for name in ['spec.json', 'source.json', 'target-native.json',
                                         'target-p2p.json', 'target-artifacts.json', 'coordinator.json']]
    paths += list(PROFILE.glob('*.yaml'))
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)): base.digest(p) for p in paths})
    verify(run)
    core.status('Updated compiled baseline and three loading arms frozen locally')


def comparable(c):
    value = copy.deepcopy(c)
    if '--load-format' in value['args']:
        index = value['args'].index('--load-format')
        del value['args'][index:index + 2]
    value['env'] = [e for e in value['env'] if not e['name'].startswith('MX_')]
    return value


def verify(run):
    assert base.digest(run.path / 'spec.json') == (run.path / 'spec.sha256').read_text().strip()
    for name, expected in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert base.digest(ROOT / name) == expected, 'Frozen input changed: ' + name
    s = core.spec(run)
    assert s['model_lock'] == run.state['model_lock']
    assert s['context_length'] == 1048576 and s['max_model_len_override'] is None
    assert (s['tensor_parallel_size'], s['max_num_seqs'], s['max_num_batched_tokens'], s['gpu_memory_utilization']) == (2, 4, 8192, .85)
    assert s['compile_config_digest'] == COMPILE_DIGEST
    containers = {}
    for name in ['source', 'target-native', 'target-p2p', 'target-artifacts']:
        c = worker(json.loads((run.path / (name + '.json')).read_text())['items'])
        env = {e['name']: e.get('value') for e in c['env']}
        assert c['args'].count('--language-model-only') == 1
        assert '--max-model-len' not in c['args'] and '--enforce-eager' not in c['args']
        assert c['image'] == s['model_lock']['runtime_image']
        assert c['args'][c['args'].index('--revision') + 1] == s['model_lock']['revision']
        assert c['args'][c['args'].index('--tensor-parallel-size') + 1] == '2'
        assert env['DYN_CANARY_WAIT_TIME'] == '1' and 'MODEL_EXPRESS_URL' not in env
        assert c['startupProbe']['periodSeconds'] == 2 and c['startupProbe']['failureThreshold'] == 1800
        assert c['startupProbe']['timeoutSeconds'] == 20 and c['readinessProbe']['periodSeconds'] == 2
        if name == 'target-native':
            assert '--load-format' not in c['args'] and not any(k.startswith('MX_') for k in env)
        else:
            assert c['args'][c['args'].index('--load-format') + 1] == 'modelexpress'
            assert env['MX_ARTIFACT_TRANSFER'] == ('0' if name == 'target-p2p' else '1')
            assert env['MX_ARTIFACT_COMPILE_CONFIG_DIGEST'] == COMPILE_DIGEST
        containers[name] = c
    assert comparable(containers['target-native']) == comparable(containers['target-p2p']) == comparable(containers['target-artifacts']), 'Non-MX receiver settings differ'


def prepare(run):
    original_apply = run.apply
    def ordered(objects, **kwargs):
        server = [o for o in objects if o['kind'] == 'Pod' and o['metadata']['name'] == 'mx-coordinator']
        redis = [o for o in objects if o['kind'] == 'Pod' and o['metadata']['name'] == 'mx-redis']
        if server and redis:
            original_apply([o for o in objects if o not in server], **kwargs)
            run.wait_pod('mx-redis', timeout=300)
            return original_apply(server, **kwargs)
        return original_apply(objects, **kwargs)
    run.apply = ordered
    try:
        mx.prepare(run)
    finally:
        run.apply = original_apply
    verify(run)
    run.result('matched-baseline-preparation', 'passed', scope='CPU qualification and all manifest dry-runs')


def validate(run, tag, role, result):
    folder = run.path / tag
    pod = core.worker_from(folder, role)
    c = pod['spec']['containers'][0]
    expected = worker(manifests(run, role, native=tag == 'storage'))
    for key in ['args', 'image', 'startupProbe', 'readinessProbe', 'livenessProbe']:
        assert c[key] == expected[key], 'Effective worker setting differs: ' + key
    wanted_env = {e['name']: e for e in expected['env']}
    actual_env = {e['name']: e for e in c['env']}
    assert all(actual_env.get(k) == value for k, value in wanted_env.items())
    assert not any(k.startswith('MX_') and k not in wanted_env for k in actual_env)
    assert pod['spec']['nodeName'] == core.spec(run)['source_node' if role == 'source' else 'target_node']
    assert result['models']['data'][0]['context_window'] == 1048576
    assert all(x.get('restartCount', 0) == 0 for x in pod['status']['containerStatuses'])
    assert all(x['imageID'].endswith(core.spec(run)['model_lock']['runtime_image'].split('@')[1]) for x in pod['status']['containerStatuses'])
    gpus = (folder / 'gpu-visible.csv').read_text().strip().splitlines()
    assert len(gpus) == 2 and all('H100' in x for x in gpus)
    logs = mx.logs_for(run, folder, role)
    assert 'running in text-only mode' in logs
    assert not any(marker in logs for marker in ['Multi-modal warmup completed', 'Encoder cache will be initialized with a budget'])
    assert sorted(set(re.findall(r'canary_wait_time_secs=(\d+)', logs))) == ['1']
    if tag in ['storage', 'weights']:
        assert 'vLLM artifact install complete:' not in logs and 'which ModelExpress installed' not in logs
        assert 'Directly load AOT compilation from path' not in logs and 'Directly load the compiled graph(s)' not in logs, 'Fresh baseline unexpectedly reused a compiled graph'
    write(folder / 'identity-health-proof.json', {'passed': True, 'worker_uid': pod['metadata']['uid'],
        'canary_wait_seconds': 1, 'text_only': True, 'native_context': 1048576,
        'gpu_uuid_lines': gpus, 'effective_probes': {k: c[k] for k in ['startupProbe', 'readinessProbe', 'livenessProbe']}})
    return sorted(line.split(',')[1].strip() for line in gpus)


def batch(run):
    verify(run)
    assert run.state['checks']['matched-baseline-preparation']['status'] == 'passed'
    assert not (run.path / 'batch-started.json').exists(), 'No replay of a started trial'
    base.acquire(run)
    write(run.path / 'batch-started.json', {'at': base.now(), 'sequence': core.spec(run)['sequence']})
    try:
        mx.MODE = 'artifacts'
        source = mx.run_arm(run, 'text-only-fast-source-bootstrap', 'source')
        validate(run, 'text-only-fast-source-bootstrap', 'source', source)
        mx.await_artifact_publication(run)
        arms = {}
        identities = {}
        for name, _ in ARMS:
            mx.MODE = 'artifacts' if name == 'artifacts' else 'weights'
            core.status('Starting matched updated baseline arm: ' + name)
            result = mx.run_arm(run, name, 'target', native=name == 'storage')
            identities[name] = validate(run, name, 'target', result)
            health.retained_source(run, run.path / name, source['pod_uid'])
            if name == 'artifacts':
                proof = core.cache_proof(run, name)
                write(run.path / name / 'artifact-reuse-evidence.json', proof)
            arms[name] = result
            health.stop_target(run, result['pod_uid'])
            # Preserve every inter-arm cleanup receipt, not only the final one.
            write(run.path / ('after-' + name + '-cleanup.json'), json.loads((run.path / 'between-arm-cleanup.json').read_text()))
        assert len({value['pod_uid'] for value in arms.values()}) == 3
        assert identities['storage'] == identities['weights'] == identities['artifacts']
        times = {k: v['apply_to_ready_observed_seconds'] for k, v in arms.items()}
        write(run.path / 'comparison.json', {'source': source, **arms,
            'ready_seconds': times, 'same_receiver_gpu_uuids': identities['storage'],
            'weight_ready_speedup': times['storage'] / times['weights'],
            'artifact_ready_speedup_vs_storage': times['storage'] / times['artifacts'],
            'artifact_ready_speedup_vs_weights': times['weights'] / times['artifacts'],
            'scope': core.spec(run)['comparison_group'] + '; five-second Ready observation; no throughput or distribution claim'})
        run.result('matched-baseline-startup', 'passed', ready_seconds=times)
    except Exception as error:
        try:
            base.collect(run, 'failed-attempt')
        finally:
            run.result('matched-baseline-startup', 'failed', error=repr(error))
        raise
    finally:
        core.clean_resources(run)
        core.seal(run)


def finalize(run):
    verify(run)
    assert run.state['checks']['matched-baseline-startup']['status'] == 'passed'
    cleanup = json.loads((run.path / 'cleanup-proof.json').read_text())
    assert cleanup['verified'] and cleanup['gpu_lease_absent'] and not base.LEASE.exists()
    runpy.run_path(str(core.MX / 'analyze_startup.py'))['extract'](run.path)
    proof = json.loads((run.path / 'artifacts/artifact-reuse-evidence.json').read_text())
    assert proof['actual_engine_cache_hit_ranks'] == ['0', '1'] and not proof['failure_lines']
    write(run.path / 'qualification.json', {'passed': True, 'cleanup_verified': True,
        'scope': core.spec(run)['comparison_group'], 'helper_sha256': base.digest(__file__)})
    core.status('Updated baseline comparison completed, qualified and cleaned')
    core.seal(run)


def configure(run):
    core.COMPILE_DIGEST = COMPILE_DIGEST
    core.configure(run)
    mx.COMPILE_DIGEST = COMPILE_DIGEST
    base.OWNER = '/root/startup_matched_baseline'
    base.manifests = manifests
    mx.central_manifests = manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'verify', 'prepare', 'batch', 'cleanup', 'finalize'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = base.setup_run(args.run)
    configure(run)
    if args.action == 'freeze':
        freeze(run)
        return
    verify(run)
    if args.action == 'verify':
        core.status('Updated baseline inputs verified offline')
    elif args.action == 'prepare':
        prepare(run)
    elif args.action == 'batch':
        batch(run)
    elif args.action == 'finalize':
        finalize(run)
    else:
        core.clean_resources(run)
        core.seal(run)


if __name__ == '__main__':
    main()
