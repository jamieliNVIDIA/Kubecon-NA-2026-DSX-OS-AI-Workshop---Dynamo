#!/usr/bin/env python3
"""Reference accepted upstream scale-out proof without relabeling it as a rerun."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import execute_pair as e


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4194304):
            h.update(chunk)
    return h.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def normalized_profile(value):
    value = json.loads(json.dumps(value))
    config = value['benchmark']
    config['endpoint']['urls'] = ['NORMALIZED']
    config['artifacts']['dir'] = 'NORMALIZED'
    config['server_metrics']['urls'] = ['NORMALIZED']
    config['server_metrics']['discovery'] = {'mode': 'disabled'}
    return value


def inspect_pair(run, source, concurrency, attempt):
    source = source.resolve()
    assert e.ROOT / 'results' in source.parents, 'Upstream proof must be owned local results'
    state = json.loads((source / 'state.json').read_text())
    assert state['owner'] == 'kubecon-dynamo-feature-tests'
    check = state['checks'].get(f'rr-pair-c{concurrency}', {})
    assert check.get('status') == 'completed', 'Upstream pair did not complete'
    old_lock = json.loads((source / 'model-lock.json').read_text())
    lock = json.loads((run.path / 'model-lock.json').read_text())
    for key in ('model', 'revision', 'runtime_image', 'tensor_parallel_size', 'gpu_allocation'):
        assert old_lock.get(key) == lock.get(key), key
    template = yaml.safe_load((e.ROOT / f'reports/workshop-measurements-20261030/agentx-workload/profile-c{concurrency}.yaml').read_text())
    arms = []
    for replicas in (1, 2):
        arm = source / f'c{concurrency}-r{replicas}-{attempt}'
        manifest_path = arm / 'integrity-final.json'
        inventory = json.loads(manifest_path.read_text())['sha256']
        for rel, expected in inventory.items():
            assert digest(arm / rel) == expected, rel
        spec = json.loads((arm / 'spec.json').read_text())
        assert spec['model'] == lock['model'] and spec['model_revision'] == lock['revision']
        assert spec['runtime_image'] == lock['runtime_image']
        assert spec['native_max_model_len'] == 1048576 and spec['max_num_seqs_per_worker'] == 4
        assert spec['concurrency_session_trees'] == concurrency and spec['replicas'] == replicas
        assert spec['dataset_revision'] == e.DATASET_REV and spec['dataset_sha256'] == e.DATASET_SHA
        assert spec['aiperf_commit'] == 'e2c149ee29d3b64798d8ba2176e9f42e0aa89280'
        assert spec['router_mode'] == 'round-robin' and spec['h100_gpus'] == replicas * 2
        assert digest(arm / 'profile.yaml') == spec['profile_sha256']
        profile = yaml.safe_load((arm / 'profile.yaml').read_text())
        assert normalized_profile(profile) == normalized_profile(template), 'Workload changed'
        exports = [p for p in (arm / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
        assert len(exports) == 1
        data = json.loads(exports[0].read_text())
        assert data.get('is_complete') is True and data.get('was_cancelled') is False
        assert (data.get('metadata') or {}).get('submission_valid') is True
        assert not data.get('runtime_submission_invalid_reasons') and not data.get('error_summary')
        assert data.get('request_count', {}).get('avg', 0) > 0
        assert not data.get('error_request_count', {}).get('avg', 0)
        assert not data.get('context_overflow_count', {}).get('avg', 0)
        arms.append({'name': arm.name, 'spec_sha256': digest(arm / 'spec.json'),
                     'profile_sha256': spec['profile_sha256'], 'integrity_final_sha256': digest(manifest_path),
                     'accepted_export': str(exports[0].relative_to(source)),
                     'accepted_export_sha256': digest(exports[0]), 'sealed_files_verified': len(inventory)})
    # Compare the deployment template after rebinding only run ownership. The
    # per-arm Pod snapshots above remain the immutable actual runtime evidence.
    _, _, current_path = e.render(run, 1)
    old_template_path = source / 'rr-1-replica.yaml'
    old = yaml.safe_load(old_template_path.read_text())
    old = json.loads(json.dumps(old).replace(state['namespace'], run.ns))
    current = yaml.safe_load(current_path.read_text())
    assert old == current, 'Serving template changed beyond namespace ownership'
    cache_receipts = list(source.glob('cpu-transport-recovery-*/summary-c4.json'))
    assert len(cache_receipts) == 1, 'Need the exact upstream cache qualification receipt'
    cache = json.loads(cache_receipts[0].read_text())
    return {'source_run': str(source), 'source_namespace': state['namespace'], 'concurrency': concurrency,
            'attempt': attempt, 'source_pair_check_sha256': json_hash(check), 'arms': arms,
            'normalized_deployment_sha256': json_hash(current),
            'source_cache_receipt': str(cache_receipts[0]), 'source_cache_receipt_sha256': digest(cache_receipts[0]),
            'expected_cache_files': cache['cache_files'],
            'scope': 'Reference to previously accepted measurements; no new C1 execution or pass status'}


def resolve(run):
    evidence = {}
    for concurrency in (1, 4):
        if run.state.get('checks', {}).get(f'rr-pair-c{concurrency}', {}).get('status') == 'completed':
            evidence[str(concurrency)] = {'kind': 'current-run-measurement', 'source_run': str(run.path)}
            continue
        path = run.path / f'upstream-c{concurrency}-prerequisite.json'
        if not path.exists():
            raise RuntimeError('Complete and validate both scale-out pairs before the routing extension')
        recorded = json.loads(path.read_text())
        actual = inspect_pair(run, Path(recorded['source_run']), concurrency, recorded['attempt'])
        assert actual == recorded, 'Upstream proof changed after reference was recorded'
        qualified = run.state.get('checks', {}).get('rr-cpu-client-qualified', {})
        assert qualified.get('status') == 'passed', 'Current client not qualified'
        cache_path = Path(qualified['evidence']) / 'receipt-c4.json'
        cache = json.loads(cache_path.read_text())
        assert cache['status'] == 'cache_verified' and cache['initial_cache_hit'] is True
        assert cache['cache_files'] == recorded['expected_cache_files'], 'Current corpus/cache differs'
        evidence[str(concurrency)] = {'kind': 'verified-upstream-reference', 'source_run': recorded['source_run'],
                                     'reference': str(path), 'reference_sha256': digest(path),
                                     'source_specs_sha256': [a['spec_sha256'] for a in recorded['arms']]}
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--concurrency', type=int, choices=[1], required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    if not e.re.fullmatch(r'[a-z0-9-]+', args.attempt):
        raise ValueError('Invalid source attempt')
    run = e.Run(args.run)
    proof = inspect_pair(run, args.source_run, args.concurrency, args.attempt)
    path = run.path / f'upstream-c{args.concurrency}-prerequisite.json'
    with path.open('x') as stream:
        stream.write(json.dumps(proof, indent=2) + '\n')
    run.result('rr-upstream-c1-reference', 'verified', source_run=proof['source_run'], reference=str(path),
               reference_sha256=digest(path), scope='Historical proof reference, not a newly measured C1 pass')
    print(json.dumps({'reference': str(path), 'source_run': proof['source_run'],
                      'sealed_files_verified': sum(a['sealed_files_verified'] for a in proof['arms'])}))


if __name__ == '__main__':
    main()
