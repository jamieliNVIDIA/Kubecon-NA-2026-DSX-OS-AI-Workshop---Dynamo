"""Read-only immutable status snapshots for the text-only controller."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-textonly-controller-observations-20261103'
PROGRAM=r'''
import datetime,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-mx-startup-20261103-textonly02'
controller=w/'results/workshop-textonly-controller-20261103-a4'
v={'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
v['docker_state']=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}','kubecon-workshop-textonly-20261103-a4'],timeout=20))
v['receipts']={}
for p in [controller/'STATUS.json',controller/'exit.json',controller/'predecessor-cleanup-verified.json',run/'LIVE_STATUS.json',run/'comparison.json',run/'cleanup-proof.json',run/'startup-analysis.json',run/'text-only-qualification.json']:
 if p.exists():v['receipts'][str(p.relative_to(w))]=json.loads(p.read_text())
v['console_tails']={str(p.relative_to(w)):p.read_text()[-7000:] for p in controller.glob('*/console.log')}
state=json.loads((run/'state.json').read_text());ns=state['namespace']
r=subprocess.run(['kubectl','--request-timeout=15s','get','pods','-n',ns,'-o','json'],capture_output=True,text=True,timeout=25)
if r.returncode:v['pod_query_error']=r.stderr[-1200:]
else:v['pods']=[{'name':p['metadata']['name'],'uid':p['metadata']['uid'],'phase':p.get('status',{}).get('phase'),'conditions':p.get('status',{}).get('conditions',[]),'containers':p.get('status',{}).get('containerStatuses',[])} for p in json.loads(r.stdout)['items']]
print(json.dumps(v))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    parser.add_argument('--generation',choices=['4','5'],default='5')
    args=parser.parse_args();assert re.fullmatch('[a-z0-9-]+',args.label)
    OUT.mkdir(exist_ok=True);dest=OUT/args.label;dest.mkdir(exist_ok=False)
    program=PROGRAM.replace('20261103-a4','20261103-a'+args.generation)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(program)]
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    result=subprocess.run(argv,capture_output=True,text=True,timeout=90)
    (dest/'receipt.json').write_text(json.dumps({'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':result.returncode,'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
    (dest/'stderr.txt').write_text(result.stderr)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    value=json.loads(result.stdout);(dest/'status.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'at':value['at'],'docker_state':value['docker_state'],'stages':{k:v for k,v in value['receipts'].items() if k.endswith(('STATUS.json','LIVE_STATUS.json','exit.json'))},'pods':[(p['name'],p['phase'],[(c['name'],c.get('ready'),c.get('restartCount')) for c in p['containers']]) for p in value.get('pods',[])]},indent=2))


if __name__=='__main__':main()
