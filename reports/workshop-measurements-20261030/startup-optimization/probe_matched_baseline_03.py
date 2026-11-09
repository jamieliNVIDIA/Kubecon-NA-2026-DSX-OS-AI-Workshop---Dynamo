"""Read-only immutable status snapshots for the matched-baseline controller."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-baseline-controller-observations-20261104-a3'
PROGRAM=r'''
import datetime,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-mx-startup-20261104-baseline03'
controller=w/'results/workshop-baseline-controller-20261104-a3'
v={'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
v['docker_state']=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}','kubecon-workshop-baseline-20261104-a3'],timeout=20))
v['receipts']={}
for p in [controller/'STATUS.json',controller/'exit.json',controller/'predecessor-cleanup-verified.json',run/'LIVE_STATUS.json',run/'comparison.json',run/'cleanup-proof.json',run/'startup-analysis.json',run/'qualification.json']:
 if p.exists():v['receipts'][str(p.relative_to(w))]=json.loads(p.read_text())
v['console_tails']={str(p.relative_to(w)):p.read_text()[-7000:] for p in controller.glob('*/console.log')}
state=json.loads((run/'state.json').read_text());ns=state['namespace']
r=subprocess.run(['kubectl','--request-timeout=15s','get','pods','-n',ns,'-o','json'],capture_output=True,text=True,timeout=25)
if r.returncode:v['pod_query_error']=r.stderr[-1200:]
else:v['pods']=[{'name':p['metadata']['name'],'uid':p['metadata']['uid'],'phase':p.get('status',{}).get('phase'),'conditions':p.get('status',{}).get('conditions',[]),'containers':p.get('status',{}).get('containerStatuses',[])} for p in json.loads(r.stdout)['items']]
v['worker_progress']={}
for p in v.get('pods',[]):
 if all(c.get('ready') for c in p['containers']):continue
 if not any(part in p['name'] for part in ['-source-','-target-']) or 'frontend' in p['name']:continue
 logs=subprocess.run(['kubectl','--request-timeout=15s','logs',p['name'],'-n',ns,'-c','main','--tail=400','--timestamps=true'],capture_output=True,text=True,timeout=25)
 markers=['loading','Loading','compile','compil','warmup','text-only','engine','Engine','Transfer','TIMING','ERROR']
 v['worker_progress'][p['name']]=[line for line in logs.stdout.splitlines() if '503 Service Unavailable' not in line and any(word in line for word in markers)][-4:]
print(json.dumps(v))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    parser.add_argument('--generation',choices=['1'],default='1')
    args=parser.parse_args();assert re.fullmatch('[a-z0-9-]+',args.label)
    OUT.mkdir(exist_ok=True);dest=OUT/args.label;dest.mkdir(exist_ok=False)
    program=PROGRAM
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(program)]
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    result=subprocess.run(argv,capture_output=True,text=True,timeout=90)
    (dest/'receipt.json').write_text(json.dumps({'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':result.returncode,'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
    (dest/'stderr.txt').write_text(result.stderr)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    value=json.loads(result.stdout);(dest/'status.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'at':value['at'],'controller':value['docker_state']['Status'],'stage':{k:v.get('stage',v.get('message',v.get('exit_code'))) for k,v in value['receipts'].items() if k.endswith(('STATUS.json','LIVE_STATUS.json','exit.json'))},'worker_progress':value.get('worker_progress',{}),'pod_states':[(p['name'],p['phase'],all(c.get('ready') for c in p['containers']),sum(c.get('restartCount',0) for c in p['containers'])) for p in value.get('pods',[])]},indent=2))


if __name__=='__main__':main()
