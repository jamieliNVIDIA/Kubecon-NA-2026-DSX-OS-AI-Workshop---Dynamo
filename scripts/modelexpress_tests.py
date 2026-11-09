#!/usr/bin/env python3
"""Stage a source then a cross-node target for actual ModelExpress P2P loading."""
import argparse
import copy
import json
import re
from pathlib import Path
import yaml
from serving_tests import render, lock_model, frontend, request
from testlib import ROOT, Run


def deploy(run,target=False):
    lock=lock_model(run)
    graph=render(run,'agg')
    graph['metadata']['name']='ft-mx'
    worker=next(c for c in graph['spec']['components'] if c['type']=='worker')
    worker['name']='source';worker['replicas']=1
    worker['podTemplate']['spec'].pop('affinity',None)
    workers=[worker]
    if target:
        startup_timeout=2400 if lock.get('tensor_parallel_size',1)>1 else 900
        run.k('wait','--for=condition=Ready','dgd/ft-mx','-n',run.ns,f'--timeout={startup_timeout}s',timeout=startup_timeout+30)
        destination=copy.deepcopy(worker);destination['name']='target';workers=[destination]
        # DGD component topology is immutable; preserve the source and create
        # the target as a separate graph with its own inference frontend.
        graph['metadata']['name']='ft-mx-target'
    graph['spec']['components']=[c for c in graph['spec']['components'] if c['type']=='frontend']+workers
    for component in workers:
        role=component['name']
        pod=component['podTemplate']
        pod['metadata'].setdefault('labels',{}).update({'mx-role':role})
        spec=pod['spec']
        spec['nodeSelector']={'kubernetes.io/hostname':'kubecon-nke-site-cp-0124' if role=='source' else 'kubecon-nke-site-cp-0198'}
        main=spec['containers'][0]
        main['args']+=['--load-format','modelexpress']
        main['command']=['bash','/efa/entrypoint.sh']
        main['args']=['python3','-m','dynamo.vllm']+main['args']
        main['env']+=[{'name':key,'value':value} for key,value in {
            'MX_METADATA_BACKEND':'k8s-service',
            'MX_K8S_SERVICE_PATTERN':'mx-source' if lock.get('tensor_parallel_size',1)>1 else 'mx-source:6555',
            'MX_MODEL_REVISION':lock['revision'],'MX_NIXL_BACKEND':'LIBFABRIC','MX_P2P_METADATA':'1',
            'MX_WORKER_GRPC_PORT':'6555','MX_METADATA_PORT':'5555',
            'MX_ARTIFACT_TRANSFER':'0','MX_ARTIFACT_READY_URL':'http://127.0.0.1:9090/health',
            'FI_PROVIDER':'efa','FI_EFA_USE_DEVICE_RDMA':'1','FI_EFA_FORK_SAFE':'1',
            'FI_EFA_ENABLE_SHM_TRANSFER':'0','FI_HMEM_CUDA_USE_DMABUF':'1',
            'NIXL_LIBFABRIC_USE_DEVICE_RDMA':'1','NIXL_LOG_LEVEL':'INFO',
            'NIXL_TELEMETRY_ENABLE':'y',
            'NIXL_TELEMETRY_EXPORTER':'prometheus_mp' if lock.get('tensor_parallel_size',1)>1 else 'prometheus',
            'NIXL_TELEMETRY_PROMETHEUS_PORT':'19090',
            **({'NIXL_TELEMETRY_MULTIPROC_DIR':'/tmp/nixl-metrics'} if lock.get('tensor_parallel_size',1)>1 else {})}.items()]
        main['env'].append({'name':'MX_WORKER_HOST','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}})
        for resource in main['resources'].values():resource['vpc.amazonaws.com/efa']=str(4*lock.get('tensor_parallel_size',1))
        spec['volumes'].append({'name':'efa','configMap':{'name':'efa-userspace'}})
        main['volumeMounts'].append({'name':'efa','mountPath':'/efa','readOnly':True})
    run.apply([{'apiVersion':'v1','kind':'Service','metadata':{'name':'mx-source'},
        'spec':{'selector':{'mx-role':'source'},'ports':[
            {'name':'mx' if rank==0 else f'mx-{rank}','port':6555+rank,'targetPort':6555+rank}
            for rank in range(lock.get('tensor_parallel_size',1))]}}])
    directory=ROOT/'configs/dgd'/lock.get('manifest_directory','common-runtime' if lock.get('common_runtime') else '')
    directory.mkdir(parents=True,exist_ok=True)
    destination=directory/('nemotron-modelexpress-target.yaml' if target else 'nemotron-modelexpress.yaml')
    run.write_manifest(destination, [graph])
    run.apply([graph])
    run.result('modelexpress-deployment','created',stage='source-and-target' if target else 'source',
        model=lock['model'],revision=lock['revision'],backend='LIBFABRIC',metadata_backend='k8s-service',
        note='Fallback disk loading is allowed but cannot count as P2P success')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['source','target','verify'])
    parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args();run=Run(args.run)
    try:
        if args.action=='verify': verify(run)
        else: deploy(run,args.action=='target')
    except Exception as exc:run.result('modelexpress','blocked',error=str(exc));raise

def verify(run):
    startup_timeout=2400 if lock_model(run).get('tensor_parallel_size',1)>1 else 900
    run.k('wait','--for=condition=Ready','dgd/ft-mx-target','-n',run.ns,f'--timeout={startup_timeout}s',timeout=startup_timeout+30)
    pods=run.get('get','pods','-n',run.ns)['items']
    source=next(p for p in pods if p['metadata'].get('labels',{}).get('mx-role')=='source')
    target=next(p for p in pods if p['metadata'].get('labels',{}).get('mx-role')=='target')
    assert source['spec']['nodeName']!=target['spec']['nodeName']
    logs=run.k('logs',target['metadata']['name'],'-n',run.ns,'-c','main').stdout
    (run.path/'modelexpress-target.log').write_text(logs)
    assert 'Receiving 761 tensors from source (P2P)' in logs or re.search(r'Receiving \d+ tensors from source \(P2P\)',logs)
    assert 'Backend LIBFABRIC was instantiated' in logs
    assert 'using provider=efa' in logs
    transfers=re.findall(r'Transfer complete: (\d+) tensors, ([0-9.]+) GB in ([0-9.]+)s',logs)
    tp=lock_model(run).get('tensor_parallel_size',1)
    assert len(transfers)==tp, f'Expected {tp} completed per-rank weight transfers'
    assert 'Trying strategy: default' not in logs, 'Receiver fell back to disk'
    tensors=sum(int(t[0]) for t in transfers);gigabytes=sum(float(t[1]) for t in transfers);seconds=max(float(t[2]) for t in transfers)
    assert tensors>0 and gigabytes>1
    model=lock_model(run)['model']
    with frontend(run,'mx-target') as base:
        response=request(base+'/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':'Reply with the word READY.'}],
            'max_tokens':128,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}})
    (run.path/'modelexpress-inference.json').write_text(json.dumps(response,indent=2)+'\n')
    assert 'READY' in response['choices'][0]['message'].get('content','')
    run.result('modelexpress','passed',source_node=source['spec']['nodeName'],target_node=target['spec']['nodeName'],
        tensors=int(tensors),gigabytes_from_log=float(gigabytes),transfer_seconds_from_log=float(seconds),
        backend='LIBFABRIC',provider='efa',model=model,usage=response['usage'],
        evidence=['modelexpress-target.log','modelexpress-inference.json'],
        scope='Full model weights transferred cross-node via P2P; receiver generated expected output without disk fallback. Timing is not a benchmark.')


if __name__=='__main__':main()
