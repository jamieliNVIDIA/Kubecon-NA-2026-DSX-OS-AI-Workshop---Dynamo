#!/usr/bin/env python3
"""Render new owned CPU-only MX cache probe resources; never contact Kubernetes."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import yaml
ROOT=Path(__file__).resolve().parents[3]


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--namespace',required=True)
 p.add_argument('--id',required=True)
 p.add_argument('--node',default='kubecon-nke-site-cp-0198')
 a=p.parse_args()
 if not re.fullmatch(r'dynamo-ft-[a-z0-9-]+',a.namespace):p.error('Use a proved owned feature namespace.')
 if not re.fullmatch(r'[a-z][a-z0-9-]{1,35}',a.id):p.error('Use a short unique owned id.')
 a.output.mkdir(parents=True,exist_ok=False)
 objects=yaml.safe_load((ROOT/'configs/dgd/super-vl-textonly-fast-startup/coordinator.yaml').read_text())['items']
 labels={'app.kubernetes.io/managed-by':'kubecon-dynamo-feature-tests','feature-test-run':a.namespace,'mx-development-run':a.id}
 names={'mx-redis':a.id+'-redis','mx-coordinator':a.id+'-server'}
 groups={'redis':[],'server':[]}
 for original in objects:
  o=copy.deepcopy(original);name=o['metadata']['name'];o['metadata'].update(name=names[name],namespace=a.namespace)
  o['metadata'].setdefault('labels',{}).update(labels)
  if o['kind']=='Service':o['spec']['selector']['mx-startup-service']=names[name]
  else:
   o['metadata']['labels']['mx-startup-service']=names[name];spec=o['spec'];spec['nodeSelector']={'kubernetes.io/hostname':a.node};spec['activeDeadlineSeconds']=900
   if name=='mx-coordinator':
    c=spec['containers'][0]
    c['command']=['./modelexpress-server']
    c['args']=['--cache-directory','/cache','--port','8001','--cache-eviction-enabled','false']
    for e in c['env']:
     if e['name']=='REDIS_URL':e['value']='redis://'+names['mx-redis']+':6379'
    spec['volumes']=[{'name':'cache','persistentVolumeClaim':{'claimName':'feature-cache','readOnly':True}}]
    c['volumeMounts']=[{'name':'cache','mountPath':'/cache','subPath':'feature-tests/20261015-super-vl-tp2/hf/hub','readOnly':True}]
  groups['redis' if name=='mx-redis' else 'server'].append(o)
 lock=json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text())
 cm={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':a.id+'-probe','namespace':a.namespace,'labels':labels},'data':{'probe.py':(ROOT/'scripts/development/mx_cache/probe.py').read_text(),'model-lock.json':json.dumps(lock)}}
 job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':a.id+'-probe','namespace':a.namespace,'labels':labels},'spec':{'backoffLimit':0,'activeDeadlineSeconds':300,'template':{'metadata':{'labels':labels},'spec':{
  'restartPolicy':'Never','automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':a.node},'imagePullSecrets':[{'name':'common-runtime-pull'}],
  'containers':[{'name':'probe','image':lock['runtime_image'],'command':['python3','/probe/probe.py'],'args':['--address',names['mx-coordinator']+':8001','--lock','/probe/model-lock.json','--source-hf-home','/model-cache/feature-tests/20261015-super-vl-tp2/hf','--cache','/probe-cache','--rpc-timeout','45'],
   'env':[{'name':'NVIDIA_VISIBLE_DEVICES','value':'void'},{'name':'HF_HUB_OFFLINE','value':'1'}],
   'resources':{'requests':{'cpu':'1','memory':'512Mi'},'limits':{'cpu':'2','memory':'2Gi'}},
   'volumeMounts':[{'name':'probe','mountPath':'/probe','readOnly':True},{'name':'source','mountPath':'/model-cache','readOnly':True},{'name':'cache','mountPath':'/probe-cache'}]}],
  'volumes':[{'name':'probe','configMap':{'name':a.id+'-probe'}},{'name':'source','persistentVolumeClaim':{'claimName':'feature-cache','readOnly':True}},{'name':'cache','emptyDir':{'sizeLimit':'512Mi'}}]}}}}
 groups['probe']=[cm,job]
 for name,items in groups.items():
  (a.output/(name+'.yaml')).write_text(yaml.safe_dump({'apiVersion':'v1','kind':'List','items':items},sort_keys=False))
 plan={'schema':1,'id':a.id,'namespace':a.namespace,'node':a.node,'gpu_requests':0,'server_image':next(o for o in groups['server'] if o['kind']=='Pod')['spec']['containers'][0]['image'],'cache_mode':'existing exact HF cache mounted READ ONLY; capability probe only, not a RAM accelerator',
  'resources':{k:[{'kind':o['kind'],'name':o['metadata']['name']} for o in v] for k,v in groups.items()},
  'inputs_sha256':{q.name:hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(a.output.glob('*.yaml'))},'gates':['prove namespace/PVC/pull-secret ownership and live CPU/memory headroom','client/server admission of all3manifest files','apply Redis and waitReady before server','apply server and waitReady before probeJob','probe must confirm exact revision, fullweightmanifest and metadata hashes','collect all phase logs; delete only this id\'s resources; no candidate/GPU changes']}
 (a.output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
 print(json.dumps(plan,indent=2))


if __name__=='__main__':main()
