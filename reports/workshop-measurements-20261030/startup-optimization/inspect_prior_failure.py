"""Read-only failure/cleanup evidence before an independent startup pilot."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/workshop-textonly-predecessor-audit-20261103-a1'
PROGRAM = r'''
import datetime,hashlib,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
rr=w/'results/workshop-rr-20261103-resume02'
driver=rr/'continuation-stable-a2'
mx=w/'results/workshop-mx-startup-20261103-artifact04'
def get(*parts):
 return json.loads(subprocess.check_output(['kubectl','--request-timeout=20s']+list(parts)+['-o','json'],timeout=30))
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'controller_state':json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-controller-20261103'],timeout=20))[0]['State'],
        'controller_lock_present':(rr/'.remaining-controller.lock').exists(),
        'gpu_lease_present':(w/'.local/workshop-measurements-20261030.gpu-lease').exists(),
        'files':{},'namespaces':{}}
paths=[driver/'exit.json',driver/'routing-c1/exit.json',driver/'routing-c1/console.log',rr/'state.json']
for arm in rr.glob('routing-c1-*'):
 if arm.is_dir():
  paths.extend(p for p in arm.glob('*.json') if p.name in ('discovery-qualification.json','acceptance.json','summary.json','spec.json'))
for p in paths:
 if p.is_file():
  data=p.read_bytes();text=data.decode(errors='replace')
  result['files'][str(p.relative_to(w))]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'text':text if len(text)<60000 else text[-60000:]}
for run in (rr,mx):
 state=json.loads((run/'state.json').read_text());ns=state['namespace']
 namespace=get('get','namespace',ns)
 assert namespace['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
 objects={kind:get('get',kind,'-n',ns)['items'] for kind in ('pods','resourceclaims','dgd')}
 result['namespaces'][ns]=objects
all_pods=get('get','pods','-A')['items']
result['gpu_pods_on_test_nodes']=[{'namespace':p['metadata']['namespace'],'name':p['metadata']['name'],'uid':p['metadata']['uid'],'phase':p.get('status',{}).get('phase')}
 for p in all_pods if p['spec'].get('nodeName') in ('kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198') and any(c.get('resources',{}).get('claims') or any(k.startswith('nvidia.com/') and 'gpu' in k for k in c.get('resources',{}).get('limits',{})) for c in p['spec'].get('containers',[]))]
print(json.dumps(result))
'''


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
          '-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(PROGRAM)]
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    result=subprocess.run(argv,capture_output=True,text=True,timeout=180)
    (OUT/'receipt.json').write_text(json.dumps({'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':result.returncode,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Read-only prior controller/log/state and cluster cleanup audit'},indent=2)+'\n')
    (OUT/'stderr.txt').write_text(result.stderr)
    if result.returncode:raise RuntimeError(result.stderr[-2000:])
    value=json.loads(result.stdout)
    (OUT/'audit.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'at':value['at'],'gpu_lease_present':value['gpu_lease_present'],'gpu_pods_on_test_nodes':value['gpu_pods_on_test_nodes'],'controller_lock_present':value['controller_lock_present'],'files':list(value['files']),'namespaces':{ns:{kind:len(items) for kind,items in objects.items()} for ns,objects in value['namespaces'].items()}},indent=2))


if __name__=='__main__':main()
