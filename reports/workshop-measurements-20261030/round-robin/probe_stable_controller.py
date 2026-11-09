#!/usr/bin/env python3
"""Bounded read-only status pullback for root's reviewed stable controller.

No remote deployment, process signalling, file writes, cleanup, or lease changes.
The local snapshot is immutable and does not replace authoritative run evidence.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/workshop-stable-controller-20261103'

PROGRAM = r'''import datetime,json,subprocess
from pathlib import Path
workspace=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=workspace/'results/workshop-rr-20261103-resume02'
mx=workspace/'results/workshop-mx-startup-20261103-artifact04'
container='kubecon-workshop-controller-20261103'
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':'ip-172-31-10-102',
        'physical_workspace':str(workspace),'container':container}
query=subprocess.run(['docker','inspect','--format','{{json .State}}',container],capture_output=True,text=True,timeout=30)
result['inspect_exit_code']=query.returncode
result['container_state']=json.loads(query.stdout) if query.returncode==0 else {'error':query.stderr[-2000:]}
logs=subprocess.run(['docker','logs','--tail','35',container],capture_output=True,text=True,timeout=30)
result['controller_log_tail']=(logs.stdout+logs.stderr)[-6000:]
paths=[run/'resume-c4-r2-stable-a1'/name for name in ('STATUS.json','exit.json','cleanup-proof.json')]
paths += [run/'continuation-stable-a2'/name for name in ('STATUS.json','exit.json','mx-outcome.json','final-owned-client-proof.json')]
paths += list((run/'continuation-stable-a2').glob('*cleanup-proof/cleanup-proof.json'))
paths += [mx/'comparison.json',mx/'artifact-cache-check-failure.json',mx/'startup-analysis.json']
paths += [workspace/'.local/workshop-measurements-20261030.gpu-lease/owner.json']
result['receipts']={str(path.relative_to(workspace)):json.loads(path.read_text()) for path in paths if path.exists()}
result['analysis_summaries']={}
for path in (run/'scaleout-c4-a1-analysis.json',run/'routing-c1-a1-analysis.json',run/'routing-c4-a1-analysis.json'):
 if path.exists():
  value=json.loads(path.read_text())
  result['analysis_summaries'][path.name]={key:value.get(key) for key in ('type','concurrency_session_trees','paired_repetitions','second_over_first','canonical_throughput_denominators_differ')}
  result['analysis_summaries'][path.name]['arms']=[{key:arm.get(key) for key in ('arm','benchmark_id','requests','request_error_count','cancelled_profile_records','output_tokens','output_tokens_per_second','record_span_output_tokens_per_second','decode_tokens_per_second_per_user_mean','ttft_p50_ms','ttft_p99_ms','server_reported_cache_read_pct','predicted_kv_hit_histogram_count','predicted_kv_hit_histogram_sum')} for arm in value['arms']]
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]+', args.label):
        raise ValueError('Invalid immutable status label')
    dest = OUT / ('status-' + args.label)
    dest.mkdir(exist_ok=False)
    argv = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2', 'ubuntu@3.238.63.5',
            'python3', '-c', shlex.quote(PROGRAM)]
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        completed = subprocess.CompletedProcess(argv, 124,
            (error.stdout or b'').decode() if isinstance(error.stdout, bytes) else error.stdout or '',
            (error.stderr or b'').decode() if isinstance(error.stderr, bytes) else error.stderr or '')
    (dest / 'stdout.txt').write_text(completed.stdout)
    (dest / 'stderr.txt').write_text(completed.stderr)
    (dest / 'receipt.json').write_text(json.dumps({'argv': argv, 'started_at': started,
        'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'exit_code': completed.returncode,
        'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Read-only Docker state/log and owned-workspace receipt snapshot; no remote mutation'}, indent=2) + '\n')
    if completed.returncode:
        raise RuntimeError('Read-only stable status SSH probe failed: ' + completed.stderr[-2000:])
    value = json.loads(completed.stdout)
    (dest / 'status.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'snapshot': str(dest), 'at': value['at'], 'container_state': value['container_state'],
        'stage_receipts': {key: item for key, item in value['receipts'].items()
                          if key.endswith(('STATUS.json', 'exit.json'))}}, indent=2))


if __name__ == '__main__':
    main()
