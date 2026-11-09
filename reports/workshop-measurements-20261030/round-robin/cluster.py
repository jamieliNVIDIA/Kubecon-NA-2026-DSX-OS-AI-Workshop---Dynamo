#!/usr/bin/env python3
"""Owned rendering, CPU loadgen preparation, and leased GPU deployment for RR runs."""
import argparse
import copy
import json
from pathlib import Path
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from testlib import Run
from serving_tests import lock_model, model_cache_home

LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
OWNER = '/root/round_robin_scaling'


def lease_owned():
    try:
        owner = json.loads((LEASE / 'owner.json').read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError('GPU execution requires this workstream\'s exclusive lease') from exc
    if owner.get('agent') != OWNER:
        raise ValueError(f'GPU lease belongs to another agent: {owner}')


def render(run, replicas):
    source = ROOT / 'configs/dgd/super-vl-tp2/nemotron-agg-functionality.yaml'
    content = yaml.safe_load(source.read_text())
    graph = copy.deepcopy(next(o for o in content['items'] if o['kind']=='DynamoGraphDeployment'))
    claims = copy.deepcopy([o for o in content['items'] if o['kind']=='ResourceClaimTemplate'])
    graph['metadata'] = {'name':'ft-agg', 'namespace':run.ns, 'labels':run.labels()}
    for component in graph['spec']['components']:
        is_worker = component['type']=='worker'
        component['replicas'] = replicas if is_worker else 1
        template = component['podTemplate']
        template['metadata'] = {'labels':{**run.labels(), **({'feature-test-role':'agg'} if is_worker else {})}}
        spec=template['spec']
        spec['activeDeadlineSeconds']=14400
        main=spec['containers'][0]
        assert main['image']==lock_model(run)['runtime_image']
        for env in main['env']:
            if env['name']=='HF_HOME': env['value']=model_cache_home(run)
        if is_worker:
            args=main['args']
            i=args.index('--max-model-len')
            del args[i:i+2]
            assert args[args.index('--max-num-seqs')+1]=='4'
            assert args[args.index('--tensor-parallel-size')+1]=='2'
            terms=spec['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
            for term in terms:
                term['matchExpressions'].append({'key':'kubernetes.io/hostname','operator':'In',
                    'values':['kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198']})
        else:
            main['args'][main['args'].index('--router-mode')+1]='round-robin'
    for claim in claims:
        claim['metadata']={'name':claim['metadata']['name'],'namespace':run.ns,'labels':run.labels()}
        assert claim['spec']['spec']['devices']['requests'][0]['exactly']['count']==2
    destination=run.path/f'rr-{replicas}-replica.yaml'
    destination.write_text(yaml.safe_dump({'apiVersion':'v1','kind':'List','items':claims+[graph]},sort_keys=False))
    return graph,claims,destination


def loadgen(run):
    lock=lock_model(run)
    pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':'rr-loadgen'},'spec':{
        'restartPolicy':'Never','activeDeadlineSeconds':28800,'automountServiceAccountToken':False,
        'nodeSelector':{'kubernetes.io/hostname':'kubecon-nke-site-cp-0942'},
        'imagePullSecrets':[{'name':lock['image_pull_secret']}],
        'containers':[{'name':'loadgen','image':lock['runtime_image'],
            'command':['sleep','28800'],'env':[{'name':'NVIDIA_VISIBLE_DEVICES','value':'void'},
                {'name':'AIPERF_DATASET_WEKA_PARALLEL_WORKERS','value':'1'}],
            'resources':{'requests':{'cpu':'4','memory':'64Gi','ephemeral-storage':'40Gi'},
                'limits':{'cpu':'8','memory':'96Gi','ephemeral-storage':'80Gi'}},
            'volumeMounts':[{'name':'cache','mountPath':'/model-cache'}]}],
        'volumes':[{'name':'cache','persistentVolumeClaim':{'claimName':'feature-cache'}}]}}
    run.apply([pod]); run.wait_pod('rr-loadgen',timeout=240)
    run.result('rr-loadgen','ready',node='kubecon-nke-site-cp-0942',image=lock['runtime_image'],
               scope='CPU-only benchmark client; no GPU requests or claims')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['render','dry-run','loadgen','deploy','cleanup'])
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--replicas',type=int,choices=[1,2],default=1)
    args=p.parse_args();run=Run(args.run)
    if args.action=='loadgen': loadgen(run);return
    if args.action=='cleanup':
        lease_owned()
        from common_runtime_tests import stop
        stop(run,['ft-agg']);run.result('rr-gpu-cleanup','passed');return
    graph,claims,path=render(run,args.replicas)
    if args.action in ('dry-run','deploy'):
        run.k('apply','--dry-run=client','-f',str(path))
        run.k('apply','--dry-run=server','-f',str(path))
    if args.action=='deploy':
        lease_owned()
        run.apply(claims+[graph])
        run.result('rr-deployment','created',replicas=args.replicas,manifest=str(path),
                   total_h100_gpus=2*args.replicas,router_mode='round-robin',
                   max_model_len='native model default (no CLI cap)',max_num_seqs=4)
    print(path)


if __name__=='__main__':main()
