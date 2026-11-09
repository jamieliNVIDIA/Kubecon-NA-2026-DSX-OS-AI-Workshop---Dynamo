#!/usr/bin/env python3
"""Qualify full AgentX CPU reconstruction without holding GPUs or sending requests."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import execute_pair as e


def fetch_receipt(run, dest, label):
    """Transfer the full graph-bearing receipt compressed, with two hashes."""
    program='''import gzip,hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);raw=p.read_bytes();json.loads(raw)
data=gzip.compress(raw,compresslevel=6,mtime=0);out=p.with_suffix('.json.gz')
if out.exists():assert out.read_bytes()==data
else:out.write_bytes(data)
print('RESULT_JSON='+json.dumps({'path':str(out),'sha256':hashlib.sha256(data).hexdigest(),'original_sha256':hashlib.sha256(raw).hexdigest(),'original_bytes':len(raw)}),flush=True)
'''
    result=e.client(run,program,argv=(e.REMOTE+'/preparation/receipt-'+label+'.json',),timeout=180)
    transfer=json.loads(result.stdout.rsplit('RESULT_JSON=',1)[1].strip())
    target=dest/('receipt-'+label+'.json.gz')
    run.command(run.kbase+['cp',run.ns+'/rr-loadgen:'+transfer['path'],str(target)],timeout=600)
    data=target.read_bytes();assert hashlib.sha256(data).hexdigest()==transfer['sha256']
    raw=gzip.decompress(data)
    assert len(raw)==transfer['original_bytes']
    assert hashlib.sha256(raw).hexdigest()==transfer['original_sha256']
    (dest/('receipt-'+label+'.json')).write_bytes(raw)
    (dest/('receipt-'+label+'-transport.json')).write_text(json.dumps(transfer,indent=2)+'\n')
    return json.loads(raw)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--attempt',required=True)
    args=p.parse_args();run=e.Run(args.run)
    if not e.re.fullmatch(r'[a-z0-9-]+',args.attempt):raise ValueError('Invalid attempt label')
    dest=run.path/('cpu-qualification-'+args.attempt);dest.mkdir(exist_ok=False)
    while e.LEASE.exists():
        e.status(run,'CPU bootstrap paused for MX timing',lease=str(e.LEASE));time.sleep(30)
    location=json.loads((e.ROOT/'reports/workshop-measurements-20261030/agentx-workload/source-location.json').read_text())
    archive=Path(location['pinned_source_archive']);data=archive.read_bytes()
    assert hashlib.sha256(data).hexdigest()==location['pinned_source_sha256']
    program='''import base64,hashlib,json,sys,tarfile
from pathlib import Path
root=Path('/tmp/workshop-rr');root.mkdir(exist_ok=True)
data=base64.b64decode(sys.stdin.read());assert hashlib.sha256(data).hexdigest()==sys.argv[1]
archive=root/'pinned-source.tar.gz'
if archive.exists():assert hashlib.sha256(archive.read_bytes()).hexdigest()==sys.argv[1]
else:archive.write_bytes(data)
source=root/'aiperf-source'
if not source.exists():
 source.mkdir()
 with tarfile.open(archive) as tf:tf.extractall(source,filter='data')
loader=source/'src/aiperf/dataset/loader/semianalysis_cc_traces_weka.py'
assert hashlib.sha256(loader.read_bytes()).hexdigest()=='a6b39a93c47b9de8de779d3397600b62b4864e888749bdc1f744b979c0d3a189'
print(json.dumps({'source_archive_sha256':sys.argv[1],'source':str(source)}))
'''
    staged=run.k('exec','-i','rr-loadgen','-n',run.ns,'--','python3','-c',program,
        location['pinned_source_sha256'],input_text=base64.b64encode(data).decode(),timeout=240)
    (dest/'staging.json').write_text(staged.stdout)
    e.status(run,'bootstrapping isolated CPU AIPerf environment')
    bootstrap=run.k('exec','rr-loadgen','-n',run.ns,'--','uv','sync','--project',
        e.REMOTE+'/aiperf-source','--frozen','--no-dev','--no-default-groups',timeout=900)
    (dest/'bootstrap.log').write_text(bootstrap.stdout+bootstrap.stderr)
    e.precache(run)
    helper=e.ROOT/'reports/workshop-measurements-20261030/agentx-workload/prepare_agentx_cache.py'
    remote_helper=e.REMOTE+'/preparation/prepare_agentx_cache.py'
    e.upload(run,helper,remote_helper)
    for c in (1,4):
        template=e.ROOT/f'reports/workshop-measurements-20261030/agentx-workload/profile-c{c}.yaml'
        shutil.copy2(template,dest/template.name)
        e.upload(run,template,e.REMOTE+f'/preparation/profile-c{c}.yaml')
    for name in ('qualify_client.py','execute_pair.py','cluster.py','PLAN.md'):
        shutil.copy2(HERE/name,dest/name)
    (dest/'integrity.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in dest.iterdir() if p.is_file()},indent=2)+'\n')
    launch='''import json,os,subprocess,sys
from pathlib import Path
root=Path('/tmp/workshop-rr/preparation')
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
with (root/'console.log').open('w') as out:
 p=subprocess.Popen([sys.executable,str(root/'prepare_agentx_cache.py'),'--config',str(root/'profile-c1.yaml'),'--receipt',str(root/'receipt-c1.json')],env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
(root/'launch.json').write_text(json.dumps({'pid':p.pid,'environment':{k:v for k,v in env.items() if k.startswith(('HF_','AIPERF_DATASET_'))}}))
print(json.dumps({'pid':p.pid}))
'''
    (dest/'launch.json').write_text(e.client(run,launch).stdout)
    started=time.monotonic();history=[]
    inspect='''import json,sys
from pathlib import Path
root=Path('/tmp/workshop-rr/preparation');receipt=root/'receipt-c1.json'
value=None
if receipt.exists():
 try:value=json.loads(receipt.read_text())
 except json.JSONDecodeError:pass
# Keep the ~56 MB graph metadata out of progress stdout; copy it compressed.
small={k:value.get(k) for k in ('status','elapsed_seconds','cache_key','cache_files','cgroup_after','rss_after','error')} if value else None
v={'receipt':small,'console_tail':(root/'console.log').read_text(errors='replace')[-5000:]}
v['cgroup']={k:(Path('/sys/fs/cgroup')/k).read_text() for k in ['memory.current','memory.peak','memory.events']}
print(json.dumps(v))
'''
    while True:
        state=json.loads(e.client(run,inspect).stdout)
        history.append({'at':e.now(),'cgroup':state['cgroup']})
        (dest/'latest.json').write_text(json.dumps(state,indent=2)+'\n')
        (dest/'memory-history.json').write_text(json.dumps(history,indent=2)+'\n')
        receipt=state['receipt']
        if receipt and receipt['status'] in ('prepared','failed'):break
        if time.monotonic()-started>7200:raise TimeoutError('CPU preparation exceeded7200s; inspect owned process before cleanup')
        e.status(run,'full AgentX CPU reconstruction; no GPU lease held',memory=state['cgroup'],console_tail=state['console_tail'][-1500:])
        time.sleep(30)
    receipt=fetch_receipt(run,dest,'c1')
    if receipt['status']!='prepared':raise RuntimeError('Full AgentX CPU reconstruction failed; see immutable receipt')
    check='''import os,subprocess,sys
root='/tmp/workshop-rr/preparation'
env=os.environ.copy();env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
subprocess.run([sys.executable,root+'/prepare_agentx_cache.py','--config',root+'/profile-c4.yaml','--receipt',root+'/receipt-c4.json','--check-cache-only'],env=env,check=True)
'''
    (dest/'check-c4.log').write_text(e.client(run,check,timeout=900).stdout)
    second=fetch_receipt(run,dest,'c4')
    assert second['status']=='cache_verified' and second['initial_cache_hit'] is True
    assert receipt['cache_files']==second['cache_files']
    for name in ('console.log','launch.json'):
        remote=e.client(run,'from pathlib import Path;import sys;print(Path(sys.argv[1]).read_text())',argv=(e.REMOTE+'/preparation/'+name,))
        (dest/name).write_text(remote.stdout)
    run.result('rr-cpu-client-qualified','passed',evidence=str(dest),cache_key=receipt['cache_key'],
        scope='CPU preparation only; zero inference requests')
    e.status(run,'full AgentX CPU client qualified; ready for native-context GPU startup',
        elapsed_seconds=receipt['elapsed_seconds'],memory=receipt['cgroup_after'],cache_files=receipt['cache_files'])


if __name__=='__main__':main()
