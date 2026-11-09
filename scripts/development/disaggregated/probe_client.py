#!/usr/bin/env python3
"""Read-only exact-source check before explicitly borrowing a qualified CPU client."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from testlib import ROOT, Run

ORIGINAL = ROOT / 'results/workshop-disagg-agentx-20261105-a1'
REFERENCE = ROOT / 'results/workshop-routing-overnight-collection-recovered-20261105-0739/verified/results/workshop-routing-overnight-20261105-a1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4194304), b''):
            h.update(chunk)
    return h.hexdigest()


def expected():
    original = json.loads((ORIGINAL / 'campaign.json').read_text())
    campaign = json.loads((REFERENCE / 'campaign.json').read_text())
    for name in ('model_lock', 'dataset_revision', 'dataset_sha256', 'aiperf_commit'):
        if original[name] != campaign[name]:
            raise ValueError('Qualified source differs from locked disagg controls: ' + name)
    receipt_path = REFERENCE / 'cpu-qualification-a1/receipt-c1.json'
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'prepared' or receipt.get('seed') != original['seed']:
        raise ValueError('Qualified original CPU receipt is not the expected completed preparation.')
    identity = json.loads((REFERENCE / 'client-identity.json').read_text())
    raw = json.loads((REFERENCE / 'client-precache.json').read_text())
    if raw['traces'] != 393 or raw['dataset_sha256'] != original['dataset_sha256']:
        raise ValueError('Qualified source is not the full frozen AgentX corpus.')
    higher = json.loads((REFERENCE / 'higher-load-cpu-qualification.json').read_text())
    if higher.get('passed') is not True or higher['profiles']['16']['scenario_outcome']['submission_valid'] is not True:
        raise ValueError('Source C16 profile was not CPU-qualified.')
    files = dict(receipt['cache_files'])
    files.update({str(Path('/tmp/workshop-rr/aiperf-source/src/aiperf') / name): {'sha256': digest}
                  for name, digest in receipt['source_file_sha256'].items()})
    files['/tmp/workshop-rr/preparation/prepare_agentx_cache.py'] = {'sha256': receipt['helper_sha256']}
    files[raw['dataset_path']] = {'sha256': original['dataset_sha256']}
    location = json.loads((ROOT / 'reports/workshop-measurements-20261030/agentx-workload/source-location.json').read_text())
    files['/tmp/workshop-rr/pinned-source.tar.gz'] = {'sha256': location['pinned_source_sha256']}
    lock = original['model_lock']
    model = '/tmp/workshop-rr/hf/hub/models--' + lock['model'].replace('/', '--')
    for name in ('config.json', 'tokenizer_config.json', 'model.safetensors.index.json'):
        files[model + '/snapshots/' + lock['revision'] + '/' + name] = {'sha256': lock['model_metadata_sha256'][name]}
    return {'namespace': campaign['namespace'], 'pod': 'rr-loadgen', 'uid': identity['uid'], 'node': identity['node'],
            'runtime_image': lock['runtime_image'], 'model_ref_path': model + '/refs/main', 'model_revision': lock['revision'],
            'cache_key': receipt['cache_key'], 'files': files, 'source_receipt_sha256': sha(receipt_path),
            'source_receipt': str(receipt_path.relative_to(ROOT)), 'source_campaign_sha256': sha(REFERENCE / 'campaign.json'),
            'aiperf_archive': '/tmp/workshop-rr/pinned-source.tar.gz', 'aiperf_source': '/tmp/workshop-rr/aiperf-source',
            'new_remote_arms': ['aggregate-c16-a1', 'disaggregated-c16-a1']}


PROGRAM = r'''import hashlib,json,os,sys,tarfile,time
from pathlib import Path
s=json.load(sys.stdin);started=time.monotonic();files={}
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for chunk in iter(lambda:stream.read(4194304),b''):h.update(chunk)
 return h.hexdigest()
for name,expected in s['files'].items():
 p=Path(name);value={'bytes':p.stat().st_size,'sha256':sha(p)}
 assert value['sha256']==expected['sha256'],'Source file changed: '+name
 if 'bytes' in expected:assert value['bytes']==expected['bytes'],'Source file size changed: '+name
 files[name]=value
assert Path(s['model_ref_path']).read_text().strip()==s['model_revision'],'Tokenizer/model ref changed'
root=Path(s['aiperf_source']).resolve();members=0
with tarfile.open(s['aiperf_archive']) as archive:
 for entry in archive:
  if not entry.isfile():continue
  target=(root/entry.name).resolve();assert root==target or root in target.parents,'Archive path escapes source'
  with archive.extractfile(entry) as stream:expected=hashlib.sha256(stream.read()).hexdigest()
  assert target.is_file() and sha(target)==expected,'Extracted source differs from pinned archive: '+entry.name
  members+=1
active=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid():continue
 try:cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ')
 except (FileNotFoundError,PermissionError,ProcessLookupError):continue
 if b'-m aiperf profile' in cmd or (b'/tmp/workshop-rr/runs/' in cmd and b'runner.py' in cmd):
  active.append({'pid':int(p.name),'command':cmd.decode(errors='replace')})
assert not active,'Another benchmark/runner is active in the source client'
for arm in s['new_remote_arms']:
 assert not (Path('/tmp/workshop-rr/runs')/arm).exists(),'New comparison arm already exists in source client: '+arm
print(json.dumps({'passed':True,'metadata_only_read_only':True,'files':files,'pinned_source_members_verified':members,'active_benchmark_processes':active,'cache_key':s['cache_key'],'elapsed_seconds':time.monotonic()-started}))
'''


def probe(output):
    output = Path(output)
    if output.exists():
        raise ValueError('Use a fresh probe output directory.')
    run = Run(output)
    specification = expected()
    (run.path / 'probe-spec.json').write_text(json.dumps(specification, indent=2) + '\n')
    pod = run.get('get', 'pod', specification['pod'], '-n', specification['namespace'])
    if (pod['metadata']['uid'] != specification['uid'] or pod['spec']['nodeName'] != specification['node'] or
            pod['metadata']['labels'].get('feature-test-run') != specification['namespace'] or
            pod['status'].get('phase') != 'Running' or
            any(v.get('restartCount', 0) or not v.get('ready') or
                not v['imageID'].endswith(specification['runtime_image'].split('@')[1])
                for v in pod['status']['containerStatuses'])):
        raise ValueError('The intended qualified CPU client changed or is not Ready.')
    (run.path / 'source-pod.json').write_text(json.dumps(pod, indent=2) + '\n')
    result = run.k('exec', '-i', specification['pod'], '-n', specification['namespace'], '--',
        '/tmp/workshop-rr/aiperf-source/.venv/bin/python', '-B', '-c', PROGRAM,
        input_text=json.dumps(specification), timeout=600)
    value = json.loads(result.stdout)
    value.update(source_namespace=specification['namespace'], source_pod_uid=specification['uid'],
                 source_node=specification['node'], source_campaign_sha256=specification['source_campaign_sha256'],
                 source_receipt_sha256=specification['source_receipt_sha256'])
    (run.path / 'qualification.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'passed': value['passed'], 'source_pod_uid': value['source_pod_uid'],
                      'files_checked': len(value['files']), 'source_members_checked': value['pinned_source_members_verified'],
                      'elapsed_seconds': value['elapsed_seconds']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe(args.output)


if __name__ == '__main__':
    main()
