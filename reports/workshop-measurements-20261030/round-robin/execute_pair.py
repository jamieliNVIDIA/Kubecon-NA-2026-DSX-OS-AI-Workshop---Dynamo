#!/usr/bin/env python3
"""Execute one immutable AgentX one-to-two replica pair under the GPU lease."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import yaml

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from testlib import Run
from cluster import LEASE, OWNER, render, lease_owned

MODEL='nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'
REV='8a115b9d966adce8c059a7bcf47f49a1e57957d8'
DATASET_REV='23f152f6f0f9399a85901b89a6458def0ef16729'
DATASET_SHA='29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276'
REMOTE='/tmp/workshop-rr'
PY=f'{REMOTE}/aiperf-source/.venv/bin/python'


def now():return dt.datetime.now(dt.timezone.utc).isoformat()


def status(run,stage,**details):
    value={'updated_at':now(),'stage':stage,'run':str(run.path),'namespace':run.ns,**details}
    (HERE/'LIVE.json').write_text(json.dumps(value,indent=2)+'\n')
    (HERE/'STATUS.md').write_text('# Round-robin comparison status\n\n'+
        f'Updated: {value["updated_at"]}.\n\nState: **{stage}**.\n\n'+
        f'Owned namespace: `{run.ns}`. Evidence: `{run.path.relative_to(ROOT)}`.\n\n'+
        'Design and immutable identities: [PLAN.md](PLAN.md).\n\n'+
        '```json\n'+json.dumps(details,indent=2)+'\n```\n')
    print(json.dumps(value),flush=True)


def client(run,program,*,timeout=90,input_text=None,argv=(),check=True):
    return run.k('exec','-i','rr-loadgen','-n',run.ns,'--',PY,'-c',program,*argv,
                 timeout=timeout,input_text=input_text,check=check)


def acquire(run,wait):
    end=time.monotonic()+wait
    while True:
        try:
            LEASE.mkdir()
            (LEASE/'owner.json').write_text(json.dumps({'agent':OWNER,'run':str(run.path),
                'namespace':run.ns,'acquired_at':now()},indent=2)+'\n')
            run.state['gpu_lease_owner']=OWNER;run.save();return
        except FileExistsError:
            if time.monotonic()>=end:raise TimeoutError('GPU execution lease is still held')
            status(run,'waiting for MX GPU lease',lease=str(LEASE))
            time.sleep(30)


def cleanup_gpu(run):
    lease_owned()
    from common_runtime_tests import stop
    stop(run,['ft-agg'])
    end=time.monotonic()+180
    while time.monotonic()<end:
        claims=run.get('get','resourceclaims','-n',run.ns)['items']
        active=[p for p in run.get('get','pods','-n',run.ns)['items']
                if p['metadata']['name'].startswith('ft-agg-')]
        if not claims and not active:
            run.result('rr-gpu-cleanup','passed',remaining_claims=0,remaining_worker_pods=0)
            lease_owned();(LEASE/'owner.json').unlink();LEASE.rmdir();return
        time.sleep(5)
    raise RuntimeError('Owned GPU claims/Pods remain; lease retained for safe diagnosis')


def precache(run):
    marker=run.path/'client-precache.json'
    if marker.exists():return
    program='''import hashlib,json,os
from pathlib import Path
root=Path('/tmp/workshop-rr');hf=root/'hf';(hf/'hub').mkdir(parents=True,exist_ok=True)
model=hf/'hub/models--nvidia--NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'
if not model.exists():model.symlink_to('/model-cache/feature-tests/20261015-super-vl-tp2/hf/hub/models--nvidia--NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4',target_is_directory=True)
os.environ.update(HF_HOME=str(hf),HF_HUB_CACHE=str(hf/'hub'),HF_DATASETS_CACHE=str(hf/'datasets'))
from huggingface_hub import hf_hub_download
path=Path(hf_hub_download('semianalysisai/cc-traces-weka-062126','traces.jsonl',repo_type='dataset',revision='23f152f6f0f9399a85901b89a6458def0ef16729'))
h=hashlib.sha256()
with path.open('rb') as f:
 while chunk:=f.read(4194304):h.update(chunk)
assert h.hexdigest()=='29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276'
from datasets import load_dataset
ds=load_dataset('semianalysisai/cc-traces-weka-062126',revision='23f152f6f0f9399a85901b89a6458def0ef16729',split='train')
assert len(ds)==393
from transformers import AutoTokenizer
t=AutoTokenizer.from_pretrained('nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4',revision='8a115b9d966adce8c059a7bcf47f49a1e57957d8',local_files_only=True)
print('RESULT_JSON='+json.dumps({'traces':len(ds),'dataset_sha256':h.hexdigest(),'dataset_path':str(path),'tokenizer':type(t).__name__}),flush=True)
'''
    result=client(run,program,timeout=1800)
    (run.path/'client-precache.log').write_text(result.stdout+result.stderr)
    value=json.loads(result.stdout.rsplit('RESULT_JSON=',1)[1].strip());marker.write_text(json.dumps(value,indent=2)+'\n')
    freeze=client(run,"import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()},sort_keys=True))")
    (run.path/'client-environment.json').write_text(freeze.stdout)


def workers(run):
    return [p for p in run.get('get','pods','-n',run.ns)['items']
        if p['metadata']['name'].startswith('ft-agg-') and
        any(c.get('resources',{}).get('claims') for c in p['spec'].get('containers',[]))
        and not p['metadata'].get('deletionTimestamp')]


def wait_serving(run,replicas,arm):
    end=time.monotonic()+2700;last=None
    while time.monotonic()<end:
        pods=workers(run)
        ready=[p for p in pods if any(c['type']=='Ready' and c['status']=='True'
                                    for c in p.get('status',{}).get('conditions',[]))]
        current=[(p['metadata']['name'],p.get('status',{}).get('phase'),
                  [(c['name'],c.get('restartCount'),c.get('ready')) for c in p.get('status',{}).get('containerStatuses',[])]) for p in pods]
        if current!=last:status(run,'waiting for native-context workers',arm=arm,workers=current);last=current
        failed=[p for p in pods if p.get('status',{}).get('phase')=='Failed' or
                any(c.get('restartCount',0)>0 and c.get('lastState',{}).get('terminated',{}).get('exitCode',0)
                    for c in p.get('status',{}).get('containerStatuses',[]))]
        if failed:
            collect_workers(run,arm)
            raise RuntimeError('Native-context serving startup failed; see owned worker logs')
        if len(pods)==replicas and len(ready)==replicas:
            return ready
        time.sleep(10)
    collect_workers(run,arm);raise TimeoutError('Native-context serving did not become ready in 2700s')


def collect_workers(run,arm):
    dest=run.path/arm;dest.mkdir(exist_ok=True)
    pods=run.get('get','pods','-n',run.ns)
    (dest/'pods.json').write_text(json.dumps(pods,indent=2)+'\n')
    (dest/'claims.json').write_text(json.dumps(run.get('get','resourceclaims','-n',run.ns),indent=2)+'\n')
    for p in pods['items']:
        name=p['metadata']['name']
        if not name.startswith('ft-agg-'):continue
        for previous in (False,True):
            log=run.k('logs',name,'-n',run.ns,'-c','main',*(['--previous'] if previous else []),check=False)
            (dest/(name+('-previous' if previous else '')+'.log')).write_text(log.stdout+log.stderr)
    return dest


def endpoint(run):
    services=run.get('get','services','-n',run.ns)['items']
    service=next(s for s in services if 'ft-agg' in s['metadata']['name'] and
                 any(p['port']==8000 for p in s['spec'].get('ports',[])))
    return f'http://{service["metadata"]["name"]}.{run.ns}.svc.cluster.local:8000'


def collect_frontend_metrics(run,base,arm,label):
    program='''import datetime,json,sys,urllib.request,urllib.error
url=sys.argv[1]+'/metrics'
try:
 with urllib.request.urlopen(url,timeout=30) as r:status=r.status;body=r.read().decode()
except urllib.error.HTTPError as error:status=error.code;body=error.read().decode()
except Exception as error:status=None;body=repr(error)
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'url':url,'status':status,'body':body}))
'''
    result=client(run,program,argv=(base,),check=False)
    (run.path/arm/f'frontend-metrics-{label}.json').write_text(result.stdout or
        json.dumps({'capture_error':result.stderr,'exit_code':result.returncode})+'\n')


def smoke(run,base,replicas,arm,require_distribution=True):
    program='''import json,sys,urllib.request
base=sys.argv[1];model=sys.argv[2]
def call(path,payload=None):
 data=json.dumps(payload).encode() if payload is not None else None
 req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
models=call('/v1/models');assert model in [m['id'] for m in models['data']]
payload={'model':model,'messages':[{'role':'user','content':'Count from one to one hundred in words.'}],
 'max_completion_tokens':2,'temperature':0,
 'chat_template_kwargs':{'enable_thinking':False},'nvext':{'extra_fields':['worker_id']}}
results=[]
for i in range(4):
 payload['messages'][0]['content']=f'Routing qualification {i}: count from one to one hundred in words.'
 r=call('/v1/chat/completions',payload);assert r['usage']['completion_tokens']==2,r
 results.append({'usage':r.get('usage'),'nvext':r.get('nvext'),'choices':r.get('choices')})
print(json.dumps({'models':models,'responses':results}),flush=True)
'''
    result=client(run,program,timeout=900,argv=(base,MODEL))
    value=json.loads(result.stdout.strip().splitlines()[-1])
    (run.path/arm/'endpoint-smoke.json').write_text(json.dumps(value,indent=2)+'\n')
    identities=[]
    for r in value['responses']:
        worker=(r.get('nvext') or {}).get('worker_id')
        if isinstance(worker,dict):worker=worker.get('decode_worker_id',worker.get('worker_id'))
        identities.append(str(worker))
    if (require_distribution and len(set(identities))!=replicas) or 'None' in identities:
        raise RuntimeError(f'Expected {replicas} serving worker identities, observed {identities}')
    return identities


def upload(run,path,destination):
    data=path.read_bytes();digest=hashlib.sha256(data).hexdigest()
    program='''import base64,hashlib,sys
from pathlib import Path
p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True)
data=base64.b64decode(sys.stdin.read());assert hashlib.sha256(data).hexdigest()==sys.argv[2]
if p.exists():assert p.read_bytes()==data
else:p.write_bytes(data)
print(sys.argv[2])
'''
    client(run,program,input_text=base64.b64encode(data).decode(),argv=(destination,digest))
    return digest


def seal_profile(run,base,pods,concurrency,replicas,arm,router_mode='round-robin',
                 initial_gpu_cache='retained first worker during manual scale-out'):
    template=ROOT/f'reports/workshop-measurements-20261030/agentx-workload/profile-c{concurrency}.yaml'
    config=yaml.safe_load(template.read_text())
    cfg=config['benchmark'];cfg['endpoint']['urls']=[base]
    cfg['artifacts']['dir']=f'{REMOTE}/runs/{arm}/artifacts'
    cfg['server_metrics']['discovery']={'mode':'disabled'}
    cfg['server_metrics']['urls']=[f'http://{p["status"]["podIP"]}:9090' for p in pods]
    profile=run.path/arm/'profile.yaml';profile.write_text(yaml.safe_dump(config,sort_keys=False))
    metadata={'sealed_at':now(),'arm':arm,'replicas':replicas,'h100_gpus':replicas*2,
        'concurrency_session_trees':concurrency,'model':MODEL,'model_revision':REV,
        'runtime_image':run.state['model_lock']['runtime_image'],'dataset_revision':DATASET_REV,
        'dataset_sha256':DATASET_SHA,'aiperf_commit':'e2c149ee29d3b64798d8ba2176e9f42e0aa89280',
        'dataset_pin_patch_sha256':hashlib.sha256((ROOT/'reports/workshop-measurements-20261030/agentx-workload/aiperf-dataset-revision.patch').read_bytes()).hexdigest(),
        'profile_sha256':hashlib.sha256(profile.read_bytes()).hexdigest(),
        'client_preprocessor_workers':1,
        'client_mmap_environment':{'AIPERF_DATASET_MMAP_BASE_PATH':REMOTE+'/mmap',
            'AIPERF_DATASET_MMAP_CACHE_DIR':REMOTE+'/mmap-cache'},
        'client_resources':{'requests':{'cpu':'4','memory':'64Gi','ephemeral-storage':'40Gi'},
            'limits':{'cpu':'8','memory':'96Gi','ephemeral-storage':'80Gi'}},
        'router_mode':router_mode,'initial_gpu_cache':initial_gpu_cache,
        'native_max_model_len':1048576,'max_num_seqs_per_worker':4,
        'execution_helpers_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest()
            for name in ('execute_pair.py','execute_router_pair.py','cluster.py','PLAN.md','KV_EXTENSION_PLAN.md')},
        'worker_pods':[{'name':p['metadata']['name'],'uid':p['metadata']['uid'],'node':p['spec']['nodeName'],
            'image_ids':[c.get('imageID') for c in p['status']['containerStatuses']]} for p in pods]}
    spec=run.path/arm/'spec.json'
    with spec.open('x') as f:f.write(json.dumps(metadata,indent=2)+'\n')
    upload(run,profile,f'{REMOTE}/runs/{arm}/profile.yaml')
    return metadata


def telemetry_start(run,pods,arm):
    receipts=[]
    program='''import json,subprocess,sys,time
from pathlib import Path
root=Path('/tmp')/('rr-telemetry-'+sys.argv[1]);root.mkdir(exist_ok=False)
with (root/'gpu.csv').open('w') as f:
 p=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu','--format=csv,nounits','--loop=5'],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
time.sleep(0.3)
assert p.poll() is None,(root/'gpu.csv').read_text()
(root/'pid').write_text(str(p.pid))
print(json.dumps({'pid':p.pid,'directory':str(root),'interval_seconds':5}))
'''
    for pod in pods:
        name=pod['metadata']['name']
        result=run.k('exec',name,'-n',run.ns,'-c','main','--','python3','-c',program,arm)
        receipts.append({'pod':name,**json.loads(result.stdout)})
    (run.path/arm/'gpu-telemetry-processes.json').write_text(json.dumps(receipts,indent=2)+'\n')


def telemetry_stop(run,arm):
    path=run.path/arm/'gpu-telemetry-processes.json'
    if not path.exists():return
    program='''import os,signal,sys,time
from pathlib import Path
root=Path(sys.argv[1]);pid=int((root/'pid').read_text())
cmd=Path(f'/proc/{pid}/cmdline')
if cmd.exists() and b'nvidia-smi' in cmd.read_bytes():os.kill(pid,signal.SIGTERM);time.sleep(0.2)
print((root/'gpu.csv').read_text())
'''
    for receipt in json.loads(path.read_text()):
        result=run.k('exec',receipt['pod'],'-n',run.ns,'-c','main','--','python3','-c',program,receipt['directory'],check=False)
        (run.path/arm/('gpu-'+receipt['pod']+'.csv')).write_text(result.stdout)
        if result.returncode:(run.path/arm/('gpu-'+receipt['pod']+'-error.txt')).write_text(result.stderr)


def launch_profile(run,arm):
    program='''import json,os,signal,subprocess,sys,time
from pathlib import Path
arm=sys.argv[1];root=Path('/tmp/workshop-rr/runs')/arm
runner=root/'runner.py'
code="""import datetime,json,os,signal,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
env=os.environ.copy()
for key in ['AIPERF_HTTP_X_DYNAMO_SESSION_ID_FROM_CORRELATION_ID','AIPERF_HTTP_X_SMG_ROUTING_KEY_FROM_CORRELATION_ID','AIPERF_HTTP_X_SESSION_ID_FROM_CORRELATION_ID']:env.pop(key,None)
env.update(HF_HOME='/tmp/workshop-rr/hf',HF_HUB_CACHE='/tmp/workshop-rr/hf/hub',HF_DATASETS_CACHE='/tmp/workshop-rr/hf/datasets',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',AIPERF_DATASET_WEKA_PARALLEL_WORKERS='1',AIPERF_DATASET_MMAP_BASE_PATH='/tmp/workshop-rr/mmap',AIPERF_DATASET_MMAP_CACHE_DIR='/tmp/workshop-rr/mmap-cache')
started=datetime.datetime.now(datetime.timezone.utc).isoformat()
with (root/'console.log').open('w') as f:
 p=subprocess.Popen(['/tmp/workshop-rr/aiperf-source/.venv/bin/python','-m','aiperf','profile','--config',str(root/'profile.yaml')],env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 (root/'process.json').write_text(json.dumps({'pid':p.pid,'started_at':started}))
 try:code=p.wait(timeout=5400)
 except subprocess.TimeoutExpired:
  os.killpg(p.pid,signal.SIGINT)
  try:p.wait(timeout=60)
  except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
  code=124
(root/'exit.json').write_text(json.dumps({'exit_code':code,'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
"""
if (root/'exit.json').exists() or (root/'process.json').exists():raise RuntimeError('Refusing to reuse an attempted profile arm')
runner.write_text(code)
with (root/'runner.log').open('w') as f:
 p=subprocess.Popen([sys.executable,str(runner)],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
print(json.dumps({'runner_pid':p.pid,'arm':arm}))
'''
    result=client(run,program,argv=(arm,));(run.path/arm/'launch.json').write_text(result.stdout)


def poll_profile(run,arm):
    program='''import json,sys
from pathlib import Path
p=Path('/tmp/workshop-rr/runs')/sys.argv[1]
exit=json.loads((p/'exit.json').read_text()) if (p/'exit.json').exists() else None
log=(p/'console.log').read_text(errors='replace') if (p/'console.log').exists() else ''
print(json.dumps({'exit':exit,'tail':log[-3500:]}))
'''
    while True:
        info=json.loads(client(run,program,argv=(arm,)).stdout)
        (run.path/arm/'latest-profile.json').write_text(json.dumps(info,indent=2)+'\n')
        if info['exit'] is not None:return info['exit']
        status(run,'AgentX profile running',arm=arm,console_tail=info['tail'][-1500:])
        time.sleep(30)


def collect_profile(run,arm):
    remote=f'{REMOTE}/runs/{arm}.tar.gz'
    client(run,"import subprocess,sys;subprocess.run(['tar','-czf',sys.argv[1],'-C','/tmp/workshop-rr/runs',sys.argv[2]],check=True)",argv=(remote,arm),timeout=300)
    dest=run.path/arm/'raw-artifacts.tar.gz'
    run.command(run.kbase+['cp',f'{run.ns}/rr-loadgen:{remote}',str(dest)],timeout=600)
    import tarfile
    target=run.path/arm/'raw';target.mkdir(exist_ok=False)
    with tarfile.open(dest) as tf:
        for member in tf.getmembers():
            if not (member.isfile() or member.isdir()):raise ValueError('Unexpected artifact archive member type')
            candidate=(target/member.name).resolve()
            if candidate!=target.resolve() and target.resolve() not in candidate.parents:
                raise ValueError('Unsafe artifact archive path')
        tf.extractall(target)
    files={str(p.relative_to(run.path/arm)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in (run.path/arm).rglob('*') if p.is_file() and p.name!='integrity.json'}
    (run.path/arm/'integrity.json').write_text(json.dumps(files,indent=2)+'\n')


def validate_profile(run,arm):
    candidates=[p for p in (run.path/arm/'raw').rglob('profile_export_aiperf.json')
        if 'phases' not in p.parts]
    if len(candidates)!=1:raise RuntimeError(f'Expected one main AIPerf JSON export, found {len(candidates)}')
    data=json.loads(candidates[0].read_text())
    metric=lambda name: data.get(name,{}).get('avg')
    selected={key:value for key,value in data.items() if isinstance(value,dict) and 'unit' in value and
        (key in {'request_count','error_request_count','output_token_throughput','output_token_throughput_per_user',
                 'request_latency','time_to_first_token','inter_token_latency','input_sequence_length',
                 'output_sequence_length','request_throughput','context_overflow_count'} or
         'interactivity' in key or 'session' in key or 'concurrency' in key)}
    phase_lines=[]
    for console in (run.path/arm/'raw').rglob('console.log'):
        text=re.sub(r'\x1b\[[0-9;]*m','',console.read_text(errors='replace'))
        phase_lines.extend(line for line in text.splitlines()
            if 'Phase ' in line and (' complete' in line or 'sending complete' in line))
    summary={'export':str(candidates[0]),'benchmark_id':data.get('benchmark_id'),
        'is_complete':data.get('is_complete'),'was_cancelled':data.get('was_cancelled'),
        'runtime_submission_invalid_reasons':data.get('runtime_submission_invalid_reasons'),
        'submission_metadata':data.get('metadata'),
        'export_schema_version':data.get('schema_version'),
        'start_time':data.get('start_time'),'end_time':data.get('end_time'),
        'branch_stats':data.get('branch_stats'),
        'phase_completion_log_lines':phase_lines,
        'session_metric_fields':[key for key in selected if 'session' in key],
        'session_count_scope':'Branch and session counters are retained as exported; successful requests do not imply complete agent trees.',
        'error_summary':data.get('error_summary'),'metrics':selected}
    (run.path/arm/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if data.get('is_complete') is not True or data.get('was_cancelled') is not False:
        raise RuntimeError('AIPerf export is incomplete/cancelled; preserve results without a comparison claim')
    if data.get('runtime_submission_invalid_reasons'):
        raise RuntimeError('AgentX runtime submission is invalid; see summary.json')
    if (data.get('metadata') or {}).get('submission_valid') is not True:
        raise RuntimeError('AgentX scenario submission is invalid; see summary.json')
    if not data.get('start_time') or not data.get('end_time'):
        raise RuntimeError('AIPerf export lacks the measured time window; see summary.json')
    if not metric('request_count') or metric('request_count')<=0:
        raise RuntimeError('AIPerf export has no successful measured requests')
    if data.get('error_summary'):
        raise RuntimeError('AIPerf export contains request errors; see summary.json')
    if (metric('error_request_count') or 0)>0 or (metric('context_overflow_count') or 0)>0:
        raise RuntimeError('AIPerf reports request errors/context overflows; see summary.json')
    run.result('rr-'+arm+'-metrics','passed',benchmark_id=data.get('benchmark_id'),
               successful_requests=metric('request_count'),export=str(candidates[0]))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--concurrency',type=int,choices=[1,4],required=True)
    p.add_argument('--lease-wait',type=int,default=10800)
    p.add_argument('--attempt',default='a2',help='Fresh recorded execution attempt label')
    args=p.parse_args();run=Run(args.run)
    if not re.fullmatch(r'[a-z0-9-]+',args.attempt):raise ValueError('Invalid attempt label')
    attempted=run.path/f'pair-c{args.concurrency}-{args.attempt}-intent.json'
    if attempted.exists():raise ValueError('Pair already attempted; use a fresh immutable execution attempt')
    attempted.write_text(json.dumps({'created_at':now(),'concurrency':args.concurrency,
        'attempt':args.attempt,'weka_parallel_workers':1})+'\n')
    acquire(run,args.lease_wait)
    success=False
    first_worker_uids=None
    try:
        status(run,'preparing pinned corpus in CPU client',concurrency=args.concurrency)
        precache(run)
        for replicas in [1,2]:
            arm=f'c{args.concurrency}-r{replicas}-{args.attempt}'
            (run.path/arm).mkdir(exist_ok=False)
            status(run,'deploying native-context RR workers',arm=arm,replicas=replicas)
            graph,claims,manifest=render(run,replicas)
            run.k('apply','--dry-run=client','-f',str(manifest));run.k('apply','--dry-run=server','-f',str(manifest))
            run.apply(claims+[graph]);pods=wait_serving(run,replicas,arm)
            current_uids={pod['metadata']['uid'] for pod in pods}
            if replicas==1:first_worker_uids=current_uids
            elif not first_worker_uids.issubset(current_uids):
                collect_workers(run,arm)
                raise RuntimeError('Scale-out replaced the first worker; planned retained-cache conditions do not hold')
            from gpu_claims import verify_allocation
            for pod in pods:verify_allocation(run,pod,pod['spec']['containers'][0],2)
            collect_workers(run,arm)
            for pod in pods:
                log=(run.path/arm/(pod['metadata']['name']+'.log')).read_text()
                if not re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)',log):
                    raise RuntimeError('Could not verify native1M context from worker startup log')
            base=endpoint(run);ids=smoke(run,base,replicas,arm)
            spec=seal_profile(run,base,pods,args.concurrency,replicas,arm,
                initial_gpu_cache=('fresh first worker before bounded smoke and canonical AgentX primer'
                    if replicas==1 else 'retained first worker and fresh second worker before canonical AgentX primer'))
            run.result('rr-'+arm+'-qualified','passed',worker_ids=ids,spec_sha256=hashlib.sha256((run.path/arm/'spec.json').read_bytes()).hexdigest())
            status(run,'starting AgentX profile',arm=arm,spec=spec)
            collect_frontend_metrics(run,base,arm,'before')
            telemetry_start(run,pods,arm)
            try:
                launch_profile(run,arm);outcome=poll_profile(run,arm)
            finally:
                telemetry_stop(run,arm)
            collect_workers(run,arm);collect_frontend_metrics(run,base,arm,'after');collect_profile(run,arm)
            run.result('rr-'+arm,'completed' if outcome['exit_code']==0 else 'failed',**outcome,
                       note='AIPerf exit success still requires semantic/metric validation')
            if outcome['exit_code']:raise RuntimeError(f'AgentX {arm} exited {outcome["exit_code"]}; parameters preserved')
            validate_profile(run,arm)
        success=True
    except Exception as exc:
        run.result('rr-pair-c'+str(args.concurrency),'blocked',error=str(exc))
        status(run,'blocked',error=str(exc),concurrency=args.concurrency)
        raise
    finally:
        try:cleanup_gpu(run)
        except Exception as error:
            status(run,'cleanup needs attention; GPU lease retained',error=str(error));raise
    if success:
        run.result('rr-pair-c'+str(args.concurrency),'completed')
        status(run,'paired profiles complete; analysis pending',concurrency=args.concurrency)


if __name__=='__main__':main()
