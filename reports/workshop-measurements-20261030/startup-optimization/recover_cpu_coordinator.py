"""Retry the unchanged failed CPU coordinator after Redis is Ready; no GPUs."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-textonly-cpu-recovery-20261103-a1'
PROGRAM=r'''
import datetime,hashlib,json,subprocess,time
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-mx-startup-20261103-textonly02'
state=json.loads((run/'state.json').read_text());ns=state['namespace']
assert ns=='dynamo-ft-mxstartup-593b482e50' and state['owner']=='kubecon-dynamo-feature-tests'
assert state['model_lock']==json.loads((run/'spec.json').read_text())['model_lock']
assert not (run/'batch-started.json').exists() and not (w/'.local/workshop-measurements-20261030.gpu-lease').exists()
controller=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-textonly-20261103-a4'],timeout=20))[0]
assert controller['Id']=='0cade9000a7e366acea8097346bbe884f369bcf99558385515bd657aaa72137d'
assert controller['State']['Status']=='exited' and controller['State']['ExitCode']==1
def command(*args,data=None):
 r=subprocess.run(['kubectl','--request-timeout=20s']+list(args),input=data,capture_output=True,text=True,timeout=45)
 if r.returncode:raise RuntimeError(r.stderr[-2000:])
 return r.stdout
def get(*args):return json.loads(command(*args,'-o','json'))
assert get('get','namespace',ns)['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
redis=get('get','pod','mx-redis','-n',ns)
assert any(c['type']=='Ready' and c['status']=='True' for c in redis['status']['conditions'])
old=get('get','pod','mx-coordinator','-n',ns)
assert old['metadata']['uid']=='b1b5944b-2226-4d92-8741-ea56fe7bd478'
assert old['metadata']['labels']['feature-test-run']==ns and old['status']['phase']=='Failed'
endpoints=get('get','endpointslices','-n',ns,'-l','kubernetes.io/service-name=mx-redis')
assert any(e.get('conditions',{}).get('ready') and e.get('addresses') for item in endpoints['items'] for e in item.get('endpoints',[]))
assert not get('get','resourceclaims','-n',ns)['items'] and not get('get','dgd','-n',ns)['items']
receipt={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'namespace':ns,'old_coordinator_uid':old['metadata']['uid'],'old_phase':old['status']['phase'],'old_logs':command('logs','mx-coordinator','-n',ns),'redis_uid':redis['metadata']['uid'],'redis_ready':True,'redis_endpoints':endpoints}
recovery=run/'cpu-preparation-recovery-a1';recovery.mkdir(exist_ok=False)
(recovery/'before.json').write_text(json.dumps(receipt,indent=2)+'\n')
command('delete','pod','mx-coordinator','-n',ns,'--wait=true','--timeout=30s')
obj=next(o for o in json.loads((run/'coordinator.json').read_text())['items'] if o['kind']=='Pod' and o['metadata']['name']=='mx-coordinator')
obj['metadata']['namespace']=ns
obj['metadata'].setdefault('labels',{}).update({'app.kubernetes.io/managed-by':'kubecon-dynamo-feature-tests','feature-test-run':ns})
assert obj['spec']['containers'][0]['image']==old['spec']['containers'][0]['image']
(recovery/'effective-coordinator.json').write_text(json.dumps(obj,indent=2)+'\n')
command('apply','--dry-run=server','-f','-',data=json.dumps(obj))
command('apply','-f','-',data=json.dumps(obj))
deadline=time.monotonic()+120
while True:
 pod=get('get','pod','mx-coordinator','-n',ns)
 if pod.get('status',{}).get('phase')=='Failed':raise RuntimeError('Unchanged coordinator retry failed: '+command('logs','mx-coordinator','-n',ns)[-2500:])
 if any(c['type']=='Ready' and c['status']=='True' for c in pod.get('status',{}).get('conditions',[])):break
 if time.monotonic()>deadline:raise TimeoutError('Coordinator retry readiness timeout')
 time.sleep(2)
receipt.update({'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'new_coordinator_uid':pod['metadata']['uid'],'coordinator_ready':True,'new_logs':command('logs','mx-coordinator','-n',ns),'state_sha256':hashlib.sha256((run/'state.json').read_bytes()).hexdigest(),'scope':'Only failed owned CPU Pod retried with unchanged manifest after Redis readiness; no GPU batch started'})
(recovery/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
'''


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(PROGRAM)]
    result=subprocess.run(argv,capture_output=True,text=True,timeout=180)
    (OUT/'stderr.txt').write_text(result.stderr)
    (OUT/'execution.json').write_text(json.dumps({'exit_code':result.returncode,'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
    if result.returncode:raise RuntimeError(result.stderr[-3000:])
    value=json.loads(result.stdout);(OUT/'receipt.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k not in ('old_logs','new_logs','redis_endpoints')},indent=2))


if __name__=='__main__':main()
