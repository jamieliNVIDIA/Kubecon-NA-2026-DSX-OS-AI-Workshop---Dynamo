#!/usr/bin/env python3
"""Recover completed CPU preparation receipts without printing their large graph."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import execute_pair as e


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    if not e.re.fullmatch(r'[a-z0-9-]+', args.attempt):
        raise ValueError('Invalid immutable evidence label')
    run = e.Run(args.run)
    if e.LEASE.exists():
        raise RuntimeError('CPU recovery must finish before GPU timing begins')
    dest = run.path / ('cpu-transport-recovery-' + args.attempt)
    dest.mkdir(exist_ok=False)
    pod = run.get('get', 'pod', 'rr-loadgen', '-n', run.ns)
    (dest / 'client-pod.json').write_text(json.dumps(pod, indent=2) + '\n')
    assert pod['status']['phase'] == 'Running'
    assert all(c.get('restartCount', 0) == 0 for c in pod['status']['containerStatuses'])
    assert pod['spec']['containers'][0]['image'] == run.state['model_lock']['runtime_image']
    for name in ('resume_client.py', 'qualify_client.py', 'execute_pair.py', 'cluster.py', 'PLAN.md'):
        shutil.copy2(HERE / name, dest / name)
    e.status(run, 'recovering completed CPU preparation via compressed verified copy')

    # Never emit cache_manifest.dataset_metadata_json through exec stdout: it is
    # a ~53 MB string nested in an already large receipt. Copy compressed bytes
    # instead and verify both compressed and original hashes.
    pack = '''import gzip,hashlib,json,sys
from pathlib import Path
source=Path(sys.argv[1]);raw=source.read_bytes();value=json.loads(raw)
assert value['status'] in ('prepared','cache_verified'),value['status']
data=gzip.compress(raw,compresslevel=6,mtime=0);target=source.with_suffix('.json.gz')
if target.exists():assert target.read_bytes()==data
else:target.write_bytes(data)
print('RESULT_JSON='+json.dumps({'path':str(target),'sha256':hashlib.sha256(data).hexdigest(),'original_sha256':hashlib.sha256(raw).hexdigest(),'original_bytes':len(raw),'compressed_bytes':len(data)}),flush=True)
'''

    def fetch(label):
        result = e.client(run, pack, argv=(e.REMOTE + '/preparation/receipt-' + label + '.json',), timeout=180)
        receipt = json.loads(result.stdout.rsplit('RESULT_JSON=', 1)[1].strip())
        target = dest / ('receipt-' + label + '.json.gz')
        run.command(run.kbase + ['cp', run.ns + '/rr-loadgen:' + receipt['path'], str(target)], timeout=600)
        data = target.read_bytes()
        assert hashlib.sha256(data).hexdigest() == receipt['sha256']
        raw = gzip.decompress(data)
        assert len(raw) == receipt['original_bytes']
        assert hashlib.sha256(raw).hexdigest() == receipt['original_sha256']
        (dest / ('receipt-' + label + '.json')).write_bytes(raw)
        value = json.loads(raw)
        graph = json.loads(value['cache_manifest']['dataset_metadata_json'])['conversations']
        counts = {'conversations': len(graph), 'roots': sum(c.get('is_root', True) for c in graph),
                  'request_turns': sum(not t.get('no_request', False) for c in graph for t in c['turns'])}
        assert counts == {'conversations': 9843, 'roots': 393, 'request_turns': 98827}, counts
        summary = {k: value[k] for k in ('status', 'elapsed_seconds', 'cache_key', 'initial_cache_hit',
                   'seed', 'profile_sha256', 'helper_sha256', 'source_file_sha256', 'environment',
                   'cache_files', 'rss_after', 'cgroup_after')}
        summary.update(counts=counts, transport=receipt)
        (dest / ('summary-' + label + '.json')).write_text(json.dumps(summary, indent=2) + '\n')
        return summary

    first = fetch('c1')
    assert first['status'] == 'prepared'
    check = '''import os,subprocess,sys
root='/tmp/workshop-rr/preparation'
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
subprocess.run([sys.executable,root+'/prepare_agentx_cache.py','--config',root+'/profile-c4.yaml','--receipt',root+'/receipt-c4.json','--check-cache-only'],env=env,check=True)
'''
    (dest / 'check-c4.log').write_text(e.client(run, check, timeout=900).stdout)
    second = fetch('c4')
    assert second['status'] == 'cache_verified'
    assert second['initial_cache_hit'] is True
    assert first['cache_files'] == second['cache_files']
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir() if p.is_file()}
    (dest / 'integrity.json').write_text(json.dumps(files, indent=2) + '\n')
    run.result('rr-cpu-client-qualified', 'passed', evidence=str(dest), counts=first['counts'],
               client_uid=pod['metadata']['uid'], cache_key=first['cache_key'], scope='CPU preparation, zero inference requests')
    e.status(run, 'full AgentX CPU client qualified; ready for native-context GPU startup',
             elapsed_seconds=first['elapsed_seconds'], memory=first['cgroup_after'], cache_files=first['cache_files'],
             transport_recovery=str(dest))


if __name__ == '__main__':
    main()
