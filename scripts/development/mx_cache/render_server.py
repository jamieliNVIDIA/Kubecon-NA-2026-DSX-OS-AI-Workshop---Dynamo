#!/usr/bin/env python3
"""Render a persistent owned CPU/RAM MX service from the tested coordinator."""
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
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--namespace',required=True);p.add_argument('--id',required=True);p.add_argument('--node',default='kubecon-nke-site-cp-0198');a=p.parse_args()
 if not re.fullmatch(r'dynamo-ft-[a-z0-9-]+',a.namespace) or not re.fullmatch(r'[a-z][a-z0-9-]{1,35}',a.id):p.error('Use a proved owned namespace and unique shortid.')
 a.output.mkdir(parents=True,exist_ok=False)
 lock=json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text());baseline=json.loads((ROOT/'results/20261015-super-vl-tp2/state.json').read_text())['checks']['model-staging']
 assert baseline['status']=='passed' and (baseline['model'],baseline['revision'])==(lock['model'],lock['revision'])
 tree_path=ROOT/'results/mx-dev-source-hf-tree-20261105-a1/tree.json';tree_receipt_path=tree_path.parent/'receipt.json';tree_receipt=json.loads(tree_receipt_path.read_text())
 assert tree_receipt['http_status']==200 and tree_receipt['entries']==114 and hashlib.sha256(tree_path.read_bytes()).hexdigest()==tree_receipt['sha256']
 assert tree_receipt['url']=='https://huggingface.co/api/models/'+lock['model']+'/tree/'+lock['revision']+'?recursive=true&expand=false&limit=1000'
 spec={'schema':1,'id':a.id,'model':lock['model'],'revision':lock['revision'],'model_metadata_sha256':lock['model_metadata_sha256'],'weight_files':baseline['weight_files'],'weight_bytes':baseline['weight_bytes'],'cache_limit_bytes':96*1024**3}
 spec.update(hf_manifest_json=tree_path.read_text(),hf_manifest_sha256=tree_receipt['sha256'],hf_manifest_url=tree_receipt['url'],hf_manifest_entries=tree_receipt['entries'],hf_manifest_receipt_sha256=hashlib.sha256(tree_receipt_path.read_bytes()).hexdigest())
 labels={'app.kubernetes.io/managed-by':'kubecon-dynamo-feature-tests','feature-test-run':a.namespace,'mx-development-run':a.id}
 names={'mx-redis':a.id+'-redis','mx-coordinator':a.id+'-server'};groups={'redis':[],'server':[]}
 objects=yaml.safe_load((ROOT/'configs/dgd/super-vl-textonly-fast-startup/coordinator.yaml').read_text())['items']
 cm={'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':a.id+'-seed','namespace':a.namespace,'labels':labels},'data':{'seed.py':(ROOT/'scripts/development/mx_cache/seed.py').read_text(),'seed-spec.json':json.dumps(spec)}}
 groups['server'].append(cm)
 for original in objects:
  o=copy.deepcopy(original);old=o['metadata']['name'];name=names[old];group='redis' if old=='mx-redis' else 'server'
  o['metadata'].update(name=name,namespace=a.namespace);o['metadata'].setdefault('labels',{}).update(labels)
  if o['kind']=='Service':o['spec']['selector']['mx-startup-service']=name
  else:
   pod=o['spec'];pod.pop('activeDeadlineSeconds',None);pod['restartPolicy']='Always';pod['nodeSelector']={'kubernetes.io/hostname':a.node}
   template_labels=copy.deepcopy(o['metadata']['labels']);template_labels['mx-startup-service']=name
   if old=='mx-coordinator':
    c=pod['containers'][0];c['command']=['./modelexpress-server'];c['args']=['--cache-directory','/cache','--port','8001','--cache-eviction-enabled','false']
    for e in c['env']:
     if e['name']=='REDIS_URL':e['value']='redis://'+names['mx-redis']+':6379'
    c['resources']={'requests':{'cpu':'2','memory':'96Gi'},'limits':{'cpu':'4','memory':'112Gi'}}
    pod['volumes']=[{'name':'cache','emptyDir':{'medium':'Memory','sizeLimit':'96Gi'}},{'name':'source','persistentVolumeClaim':{'claimName':'feature-cache','readOnly':True}},{'name':'seed','configMap':{'name':cm['metadata']['name']}}]
    pod['initContainers']=[{'name':'seed','image':lock['runtime_image'],'command':['python3','/bootstrap/seed.py'],'args':['--spec','/bootstrap/seed-spec.json','--source-hf-home','/source/feature-tests/20261015-super-vl-tp2/hf','--cache','/cache','--timeout-seconds','2400'],'env':[{'name':'NVIDIA_VISIBLE_DEVICES','value':'void'},{'name':'HF_HUB_OFFLINE','value':'1'}],'resources':{'requests':{'cpu':'2','memory':'96Gi'},'limits':{'cpu':'4','memory':'112Gi'}},'volumeMounts':[{'name':'seed','mountPath':'/bootstrap','readOnly':True},{'name':'source','mountPath':'/source','readOnly':True},{'name':'cache','mountPath':'/cache'}]}]
   o={'apiVersion':'apps/v1','kind':'Deployment','metadata':o['metadata'],'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'mx-development-run':a.id,'mx-startup-service':name}},'template':{'metadata':{'labels':template_labels},'spec':pod}}}
  groups[group].append(o)
 for group,items in groups.items():(a.output/(group+'.yaml')).write_text(yaml.safe_dump({'apiVersion':'v1','kind':'List','items':items},sort_keys=False))
 (a.output/'seed-spec.json').write_text(json.dumps(spec,indent=2)+'\n')
 plan={'schema':1,'id':a.id,'namespace':a.namespace,'node':a.node,'server_address':names['mx-coordinator']+'.'+a.namespace+'.svc.cluster.local:8001','gpu_requests':0,'cache_limit_gib':96,'server_memory_request_gib':96,'server_memory_limit_gib':112,'redis_memory_limit_mib':512,'expected_weight_files':spec['weight_files'],'expected_weight_bytes':spec['weight_bytes'],'lifecycle':'Persistent until explicit owned cleanup; RAM contents disappear on server Pod replacement.','model':lock['model'],'revision':lock['revision'],'metadata_hashes':lock['model_metadata_sha256'],'files_sha256':{q.name:hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(a.output.iterdir()) if q.is_file()},'gates':['actual a2CPU RPC capability independently accepted','fresh root memory/headroom and existing namespace/PVC/pull-secret ownership','client/server admission of Redis and server manifests','Redis Ready before serverDeployment','seed fullinventory/hash receipt and same serverPodUID','fresh CPU file-stream validation into localclient cache before any GPUcandidate','explicit futurecandidate RAMbudget and all-file hash validation; no heldfull-a2 changes']}
 plan.update(hf_manifest_sha256=tree_receipt['sha256'],hf_manifest_url=tree_receipt['url'],hf_manifest_entries=tree_receipt['entries'],hf_manifest_receipt_sha256=hashlib.sha256(tree_receipt_path.read_bytes()).hexdigest(),content_hash_policy='HF LFS data SHA256 for LFS files; Git blob SHA1 for native Git files; declared Xet keys only identify storage paths, never complete-file digests',seed_config_map_immutable=True,first_failure_receipt='/cache/mx-dev-cache-failure.json')
 (a.output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');print(json.dumps(plan,indent=2))


if __name__=='__main__':main()
