"""Verify remote cleanup, then release only the matching local execution fence."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-startup-final-cleanup-20261103-a1'
PROGRAM=r'''
import datetime,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
assert not (w/'.local/workshop-measurements-20261030.gpu-lease').exists()
assert not (w/'results/workshop-rr-20261103-resume02/.remaining-controller.lock').exists()
expected={'kubecon-workshop-controller-20261103':('5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411',1),
          'kubecon-workshop-textonly-20261103-a5':('a25a5e257b7ffb73467d73c4733dffca70e82b91cc7934698c0d15974f4b45ee',0),
          'kubecon-workshop-health-20261103-a1':('03712d3c27495bab8e66d871666370dcfca8395fa1dca306bae47123d40de958',0)}
controllers={}
for name,(uid,exit_code) in expected.items():
 p=json.loads(subprocess.check_output(['docker','inspect',name],timeout=20))[0]
 assert p['Id']==uid and p['State']['Status']=='exited' and p['State']['ExitCode']==exit_code,name
 controllers[name]={'id':p['Id'],'state':p['State']}
def get(*parts):return json.loads(subprocess.check_output(['kubectl','--request-timeout=15s']+list(parts)+['-o','json'],timeout=25))
def uses_gpu(p):return any(c.get('resources',{}).get('claims') or any(k.startswith('nvidia.com/') and 'gpu' in k for k in c.get('resources',{}).get('limits',{})) for c in p['spec'].get('containers',[]))
namespaces={}
for run in ['workshop-rr-20261103-resume02','workshop-mx-startup-20261103-artifact04','workshop-mx-startup-20261103-textonly02','workshop-mx-startup-20261103-textonly-health01']:
 ns=json.loads((w/'results'/run/'state.json').read_text())['namespace']
 namespace=get('get','namespace',ns)
 assert namespace['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
 pods=get('get','pods','-n',ns)['items'];claims=get('get','resourceclaims','-n',ns)['items'];graphs=get('get','dgd','-n',ns)['items']
 gpu=[p['metadata']['name'] for p in pods if uses_gpu(p)]
 assert not gpu and not claims and not graphs,ns
 namespaces[ns]={'gpu_pods':gpu,'resourceclaims':[],'dgd':[],'retained_non_gpu_pods':[{'name':p['metadata']['name'],'phase':p.get('status',{}).get('phase')} for p in pods]}
unexpected=[p['metadata']['namespace']+'/'+p['metadata']['name'] for p in get('get','pods','-A')['items'] if p['spec'].get('nodeName') in ['kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198'] and uses_gpu(p)]
assert not unexpected,unexpected
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controllers':controllers,'namespaces':namespaces,'benchmark_node_gpu_pods':unexpected,'remote_gpu_lease_absent':True,'old_remaining_controller_lock_absent':True}))
'''


def main():
    OUT.mkdir(exist_ok=False)
    for name in ['workshop-textonly-pullback-20261103-a1','workshop-health-pullback-20261103-a1']:
        v=json.loads((ROOT/'results'/name/'verification.json').read_text())
        assert v['mismatches']==0 and v['controller_state']['ExitCode']==0 and v['gpu_lease_absent']
    args=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(PROGRAM)]
    r=subprocess.run(args,capture_output=True,text=True,timeout=180)
    (OUT/'stderr.txt').write_text(r.stderr)
    if r.returncode:raise RuntimeError(r.stderr[-2500:])
    proof=json.loads(r.stdout);(OUT/'remote-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    directory=ROOT/'.local/workshop-measurements-20261030.gpu-lease';owner=directory/'owner.json'
    fence=json.loads(owner.read_text())
    assert fence['agent']=='/root/stable_controller'
    assert fence['authorized_followup']['controller_name']=='kubecon-workshop-health-20261103-a1'
    assert fence['authorized_followup']['plan_sha256']=='79f12f7d99424f1af984fd93a47e5a6de2a094461c7e7b388249a48873370454'
    assert {p.name for p in directory.iterdir()}=={'owner.json'}
    (OUT/'released-local-fence.json').write_text(json.dumps(fence,indent=2)+'\n')
    owner.unlink();directory.rmdir()
    proof.update({'local_gpu_fence_released':True,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (OUT/'receipt.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps({'verified':True,'local_gpu_fence_released':True,'benchmark_node_gpu_pods':proof['benchmark_node_gpu_pods'],'namespaces':proof['namespaces']},indent=2))


if __name__=='__main__':main()
