#!/usr/bin/env python3
"""Check the exact two GPUs from a preserved failed Shadow claim; no reset."""
import argparse
import json
from pathlib import Path
from testlib import Run
from super_vl_tests import idle


def probe(run, execute=False):
    if run.state['checks'].get('r610-feature',{}).get('status')!='blocked' or run.state['checks'].get('shadow-final-cleanup',{}).get('status')!='passed':
        raise ValueError('Requires a failed, cleaned preferred-model Shadow run')
    claims=json.loads(sorted(run.path.glob('shadow-resourceclaims-*.json'))[-1].read_text())['items']
    assert len(claims)==1
    allocations=claims[0]['status']['allocation']['devices']['results']
    assert len(allocations)==2 and len({a['pool'] for a in allocations})==1
    node=allocations[0]['pool']
    slices=run.get('get','resourceslices')
    (run.path/'post-shadow-resource-slices.json').write_text(json.dumps(slices,indent=2)+'\n')
    selected=[]
    for allocation in allocations:
        devices=[d for s in slices['items'] if s['spec']['driver']==allocation['driver']
                 and s['spec']['pool']['name']==allocation['pool']
                 for d in s['spec']['devices'] if d['name']==allocation['device']]
        assert len(devices)==1
        attrs=devices[0].get('basic',devices[0]).get('attributes',{})
        key=next(k for k in attrs if k in ('uuid','gpu.nvidia.com/uuid'))
        selected.append({'device':allocation['device'],'uuid':attrs[key]['string']})
    assert len({s['uuid'] for s in selected})==2
    print(json.dumps({'node':node,'selected':selected,'execute':execute}),flush=True)
    if not execute:return
    expected=[s['uuid'] for s in selected]
    expression='device.attributes["gpu.nvidia.com"].uuid in '+json.dumps(expected)
    name='post-shadow-cuda-probe'
    claim={'apiVersion':'resource.k8s.io/v1','kind':'ResourceClaimTemplate','metadata':{'name':name},
        'spec':{'spec':{'devices':{'requests':[{'name':'gpus','exactly':{
            'deviceClassName':'gpu.nvidia.com','count':2,'selectors':[{'cel':{'expression':expression}}]}}]}}}}
    program='''import json,os,torch
expected=set(json.loads(os.environ['EXPECTED_UUIDS']))
assert torch.cuda.device_count()==2
uuids=[]
for i in range(2):
 value=str(torch.cuda.get_device_properties(i).uuid)
 uuids.append(value if value.startswith('GPU-') else 'GPU-'+value)
 x=torch.arange(1048576,device=f'cuda:{i}',dtype=torch.float64)
 assert (x+1).sum().item()==549756338176.0
 torch.cuda.synchronize(i)
assert set(uuids)==expected,(uuids,expected)
print(json.dumps({'uuids':uuids,'cuda_count':2,'arithmetic':'passed'}),flush=True)
'''
    pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':name},'spec':{
        'restartPolicy':'Never','activeDeadlineSeconds':180,'automountServiceAccountToken':False,
        'nodeSelector':{'kubernetes.io/hostname':node},
        'tolerations':[{'key':'nvidia.com/gpu','operator':'Exists','effect':'NoSchedule'}],
        'imagePullSecrets':[{'name':run.state['model_lock']['image_pull_secret']}],
        'resourceClaims':[{'name':'gpu','resourceClaimTemplateName':name}],
        'containers':[{'name':'cuda','image':run.state['model_lock']['runtime_image'],
            'command':['python3','-c',program],'env':[{'name':'EXPECTED_UUIDS','value':json.dumps(expected)}],
            'resources':{'claims':[{'name':'gpu'}],'requests':{'cpu':'1','memory':'2Gi'},'limits':{'memory':'4Gi'}}}]}}
    run.write_manifest(run.path/'post-shadow-cuda-probe.yaml',[claim,pod])
    try:
        run.apply([claim,pod])
        run.wait_pod(name,completed=True,timeout=240)
        result=run.k('logs',name,'-n',run.ns,'-c','cuda')
        (run.path/'post-shadow-cuda-probe.log').write_text(result.stdout)
        report=json.loads(result.stdout)
        assert set(report['uuids'])==set(expected) and report['cuda_count']==2
        run.result('post-shadow-cuda','passed',node=node,devices=selected,**report,
                   scope='Fresh arithmetic on exact affected GPU pair after process cleanup; no reset and no clearing of Xid history')
    finally:
        run.k('delete','pod',name,'-n',run.ns,'--ignore-not-found','--wait=true','--timeout=90s',timeout=105)
        run.k('delete','resourceclaimtemplate',name,'-n',run.ns,'--ignore-not-found')
        idle(run)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();probe(Run(args.run),args.execute)
