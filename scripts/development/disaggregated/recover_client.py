#!/usr/bin/env python3
"""Recover the original detached CPU qualification after an observer outage.

This does not reconstruct the corpus, recreate the client, restart a benchmark,
or change its sealed configuration. New verification receipts use new paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import scripts.development.disaggregated.benchmark as benchmark


def validate(receipt, profile_hash, helper_hash, expected_status):
    if receipt.get('status') != expected_status:
        raise ValueError('CPU qualification is not terminal/successful: ' + str(receipt.get('status')))
    if receipt['profile_sha256'] != profile_hash or receipt['helper_sha256'] != helper_hash:
        raise ValueError('The CPU receipt is for a different profile or helper.')
    if receipt.get('seed') != 20261030 or not receipt.get('cache_files'):
        raise ValueError('CPU qualification lacks the frozen seed/cache files.')
    for name, text in receipt.get('cgroup_after', {}).items():
        if name != 'memory.events':
            continue
        counters = dict(line.split() for line in text.splitlines())
        if any(int(counters.get(name, 0)) for name in ('oom', 'oom_kill', 'oom_group_kill')):
            raise ValueError('CPU preparation had an OOM event.')


def validate_original_pod(pod, expected, namespace, image):
    if (pod['metadata']['uid'] != expected['uid'] or pod['spec']['nodeName'] != expected['node'] or
            pod['metadata']['labels'].get('feature-test-run') != namespace or
            any(v.get('restartCount', 0) or not v['imageID'].endswith(image.split('@')[1])
                for v in pod['status']['containerStatuses'])):
        raise ValueError('The original detached CPU preparation Pod changed.')
    if (pod['status'].get('phase') != 'Running' or
            any(v.get('state', {}).get('terminated') for v in pod['status']['containerStatuses'])):
        raise ValueError('Original CPU Pod is no longer running; inspect its exact retained container snapshot before considering new preparation.')


def recover(run, attempt):
    benchmark.verify(run)
    if not attempt.isalnum():
        raise ValueError('Use an alphanumeric fresh recovery attempt name.')
    if any((run.path / (topology + '-c16-a1/intent.json')).exists() for topology in benchmark.ARMS):
        raise ValueError('This recovery is only for CPU preparation before any GPU benchmark attempt.')
    expected = json.loads((run.path / 'client-identity.json').read_text())
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    validate_original_pod(pod, expected, run.ns, run.state['model_lock']['runtime_image'])
    folder = run.path / ('cpu-recovery-' + attempt)
    folder.mkdir(exist_ok=False)
    benchmark.write(folder / 'client-identity.json', pod)
    original = run.path / 'cpu-qualification-a1'
    staged = json.loads((original / 'staging.json').read_text())
    location = json.loads((benchmark.SOURCE / 'agentx-workload/source-location.json').read_text())
    if staged['source_archive_sha256'] != location['pinned_source_sha256']:
        raise ValueError('Original client staged a different pinned source.')
    inspect = '''import json
from pathlib import Path
p=Path('/tmp/workshop-rr/preparation/receipt-c1.json')
v=json.loads(p.read_text())
print(json.dumps({'status':v.get('status'),'error':v.get('error'),'elapsed_seconds':v.get('elapsed_seconds')}))
'''
    started = time.monotonic()
    while True:
        value = json.loads(benchmark.e.client(run, inspect).stdout)
        benchmark.write(folder / 'latest.json', value)
        if value['status'] != 'running':
            break
        if time.monotonic() - started > 1800:
            raise TimeoutError('Original detached CPU preparation has not finished; preserve it.')
        time.sleep(30)
    receipt = benchmark.c.qualify_client.fetch_receipt(run, folder, 'c1')
    helper = benchmark.SOURCE / 'agentx-workload/prepare_agentx_cache.py'
    profile_c1 = benchmark.SOURCE / 'agentx-workload/profile-c1.yaml'
    validate(receipt, benchmark.sha(profile_c1), benchmark.sha(helper), 'prepared')
    program = '''import os,subprocess,sys
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
subprocess.run([sys.executable,'/tmp/workshop-rr/preparation/prepare_agentx_cache.py','--config',sys.argv[1],'--receipt',sys.argv[2],'--check-cache-only'],env=env,check=True)
'''
    for label, local, remote in [
        ('c4-recovery-' + attempt, benchmark.SOURCE / 'agentx-workload/profile-c4.yaml', '/tmp/workshop-rr/preparation/profile-c4.yaml'),
        ('disagg-c16-recovery-' + attempt, run.path / 'profile.yaml', '/tmp/workshop-rr/preparation/disagg-profile-c16.yaml')]:
        benchmark.e.upload(run, local, remote)
        result = benchmark.e.client(run, program, argv=(remote, '/tmp/workshop-rr/preparation/receipt-' + label + '.json'), timeout=900)
        (folder / (label + '.log')).write_text(result.stdout + result.stderr)
        check = benchmark.c.qualify_client.fetch_receipt(run, folder, label)
        validate(check, benchmark.sha(local), benchmark.sha(helper), 'cache_verified')
        if check.get('initial_cache_hit') is not True or check['cache_files'] != receipt['cache_files']:
            raise ValueError('Actual profile does not reuse the original exact verified full-corpus cache.')
    benchmark.write(folder / 'qualification.json', {'at': benchmark.e.now(), 'passed': True,
        'original_pod_uid': pod['metadata']['uid'], 'original_cache_key': receipt['cache_key'],
        'original_observer_failure': 'prepare-console-network.log', 'source_replayed': False,
        'scope': 'Original full-corpus CPU preparation recovered after transport-only observer outage; no benchmark attempted'})
    run.result('rr-cpu-client-qualified', 'passed', evidence=str(folder), cache_key=receipt['cache_key'],
               scope='Original CPU preparation recovered; zero inference requests')
    run.result('disagg-cpu-qualified', 'passed', concurrency_session_trees=16, recovery_attempt=attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    recover(benchmark.setup(args.run), args.attempt)


if __name__ == '__main__':
    main()
