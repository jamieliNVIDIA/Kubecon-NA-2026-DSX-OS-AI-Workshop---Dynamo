#!/usr/bin/env python3
"""Run the upstream engine-primary sidecar pattern with the preferred pinned model."""
import argparse
import copy
import json
from pathlib import Path
import yaml
from serving_tests import lock_model, model_cache_home, smoke, worker_args
from testlib import ROOT, Run


def deploy(run):
    lock=lock_model(run)
    images=json.loads((ROOT/'configs/sidecar-images.json').read_text())
    common = bool(lock.get('common_runtime'))
    if common:
        images = [{'image': lock['runtime_image']}, {'image': lock['runtime_image']}]
    graph=yaml.safe_load((ROOT/'configs/upstream/lib/sidecar/vllm/deploy/agg.yaml').read_text())
    graph['metadata']={'name':'ft-sidecar','namespace':run.ns,'labels':run.labels()}
    cache=model_cache_home(run)
    for component in graph['spec']['components']:
        component['podTemplate'].setdefault('metadata', {}).setdefault('labels', {}).update(run.labels())
        if lock.get('runtime_version_override'):
            component['runtimeVersionOverride']=lock['runtime_version_override']
        spec=component['podTemplate']['spec']
        if lock.get('image_pull_secret'):
            spec['imagePullSecrets'] = [{'name': lock['image_pull_secret']}]
        spec['activeDeadlineSeconds']=2700
        main=spec['containers'][0]
        if component['type']=='frontend':
            main.update(image=lock['runtime_image'],command=['python3','-m','dynamo.frontend'],args=['--trust-remote-code'])
            main['resources']={'requests':{'cpu':'1','memory':'4Gi'},'limits':{'memory':'8Gi'}}
        else:
            component['runtimeVersionOverride']=lock.get('runtime_version_override','1.5.1') if common else '1.5.1'
            component['sharedMemorySize']='16Gi'
            spec['nodeSelector']={'kubernetes.io/hostname':'kubecon-nke-site-cp-0942'}
            main['image']=images[1]['image']
            main['command']=['bash','-ec']
            main['args']=['exec "$(python3 -c \'import os,vllm; print(os.path.join(os.path.dirname(vllm.__file__), "vllm-rs"))\')" "$@"','engine',
                'serve',lock['model'],'--revision',lock['revision'],'--served-model-name',lock['model'],
                '--host','0.0.0.0','--grpc-port','50051','--trust-remote-code','--tensor-parallel-size','1',
                '--max-model-len','4096','--max-num-seqs','8','--gpu-memory-utilization','0.65',
                '--mamba-backend','flashinfer','--mamba-ssm-cache-dtype','float16','--mamba-cache-mode','align',
                '--reasoning-parser','nemotron_v3']
            main['resources']={'requests':{'cpu':'4','memory':'64Gi','nvidia.com/gpu':'1'},
                               'limits':{'memory':'128Gi','nvidia.com/gpu':'1'}}
            tp = lock.get('tensor_parallel_size', 1)
            if tp > 1:
                args = worker_args(lock['model'], lock['revision'], 'agg', tp=tp)
                for flag in ('--kv-events-config', '--disaggregation-mode'):
                    index = args.index(flag)
                    del args[index:index + 2]
                main['args'] = main['args'][:2] + ['serve', lock['model'], '--host', '0.0.0.0',
                                                  '--grpc-port', '50051'] + args[2:]
                main['resources'] = {'requests': {'cpu': '8', 'memory': '128Gi', 'nvidia.com/gpu': str(tp)},
                                     'limits': {'memory': '256Gi', 'nvidia.com/gpu': str(tp)}}
            if common and tp > 1:
                # The native frontend otherwise exits after 600s, which can
                # precede TP2 cold EFS loading/warmup under concurrent startup.
                main['args'] += ['--engine-ready-timeout-secs', '1800']
            sidecar=spec['initContainers'][0]
            sidecar['image']=images[0]['image']
            sidecar['args']=['--grpc-endpoint','127.0.0.1:50051']
            sidecar['resources']={'requests':{'cpu':'1','memory':'1Gi'},'limits':{'memory':'4Gi'}}
            sidecar['securityContext']={'runAsUser':0}
            sidecar['volumeMounts']=[{'name':'shared-model-cache','mountPath':'/model-cache'}]
            sidecar['env']=[{'name':key,'value':value} for key,value in {
                'DYN_NAMESPACE':run.ns+'-ft-sidecar','DYN_DISCOVERY_BACKEND':'kubernetes',
                'DYN_REQUEST_PLANE':'tcp','DYN_EVENT_PLANE':'zmq',
                'DYN_SYSTEM_PORT':'9090','HF_HOME':cache,'HF_HUB_OFFLINE':'1'}.items()]
            sidecar['env'] += [{'name': key, 'valueFrom': {'fieldRef': {'fieldPath': path}}}
                for key, path in {'POD_NAME': 'metadata.name', 'POD_NAMESPACE': 'metadata.namespace',
                                  'POD_UID': 'metadata.uid', 'POD_IP': 'status.podIP'}.items()]
            if common:
                sidecar['env'].append({'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'})
        main['env']=[{'name':'HF_HOME','value':cache},{'name':'HF_HUB_OFFLINE','value':'1'},
                     {'name':'HF_MODULES_CACHE','value':'/tmp/hf_modules'},{'name':'PYTHONHASHSEED','value':'0'}]
        if common and component['type']=='frontend':
            main['env'].append({'name':'NVIDIA_VISIBLE_DEVICES','value':'void'})
        main['securityContext']={'runAsUser':0,'capabilities':{'add':['IPC_LOCK','SYS_RESOURCE']}}
        main['volumeMounts']=[{'name':'shared-model-cache','mountPath':'/model-cache'}, {'name':'dshm','mountPath':'/dev/shm'}]
        spec['volumes']=[{'name':'shared-model-cache','persistentVolumeClaim':{'claimName':'feature-cache'}},
                         {'name':'dshm','emptyDir':{'medium':'Memory','sizeLimit':'16Gi'}}]
    destination=ROOT/'configs/dgd'/lock.get('manifest_directory','common-runtime' if common else '')/'nemotron-engine-sidecar.yaml'
    destination.parent.mkdir(parents=True,exist_ok=True)
    run.write_manifest(destination, [graph])
    run.apply([graph])
    run.result('engine-sidecar-deployment','created',model=lock['model'],gpu_count=lock.get('tensor_parallel_size',1),images=images,
        scope='Native vLLM gRPC engine with a separate CPU-only Dynamo sidecar')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['deploy','smoke','verify'])
    parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args()
    run=Run(args.run)
    try:
        if args.action=='deploy':deploy(run)
        elif args.action=='smoke':smoke(run,'sidecar')
        else:verify(run)
    except Exception as exc:
        run.result('engine-sidecar','blocked',error=str(exc));raise

def verify(run):
    response=json.loads((run.path/'sidecar-smoke.json').read_text())
    assert response['choices'][0]['message']['content'].strip().strip('.')=='READY'
    pods=run.get('get','pods','-n',run.ns)['items']
    pod=next(p for p in pods if p['metadata']['name'].startswith('ft-sidecar-0-worker-')
        and not p['metadata'].get('deletionTimestamp')
        and all(c['ready'] for c in p['status'].get('containerStatuses',[]))
        and p['status'].get('containerStatuses'))
    engine=pod['spec']['containers'][0];sidecar=pod['spec']['initContainers'][0]
    tp = lock_model(run).get('tensor_parallel_size', 1)
    if lock_model(run).get('gpu_allocation') == 'dra':
        assert engine['resources'].get('claims') and 'nvidia.com/gpu' not in engine['resources']['limits']
        from gpu_claims import verify_allocation
        verify_allocation(run, pod, engine, tp)
    else:
        assert engine['resources']['limits']['nvidia.com/gpu']==str(tp)
    assert 'nvidia.com/gpu' not in sidecar['resources'].get('limits',{})
    assert sidecar['restartPolicy']=='Always' and sidecar['command']==['dynamo-vllm-sidecar']
    logs=run.k('logs',pod['metadata']['name'],'-n',run.ns,'-c','runtime').stdout
    assert 'vLLM gRPC services are ready' in logs
    (run.path/'engine-sidecar.log').write_text(logs)
    code='''import importlib.metadata as m,json
r={}
for p in ('vllm','ai-dynamo','nixl','torch'):
    try:r[p]=m.version(p)
    except m.PackageNotFoundError:r[p]=None
print(json.dumps(r))
'''
    packages=json.loads(run.k('exec','-i',pod['metadata']['name'],'-n',run.ns,'-c','main','--','python3','-',input_text=code).stdout)
    common=bool(lock_model(run).get('common_runtime'))
    if common:
        assert packages['vllm']=='0.31.1rc1.dev23+g43b4aaea3' and packages['ai-dynamo']=='1.6.0'
        command=run.k('exec',pod['metadata']['name'],'-n',run.ns,'-c','main','--',
                      'python3','-c','from pathlib import Path; print(Path("/proc/1/cmdline").read_bytes().split(b"\\0")[0].decode())').stdout.strip()
        assert command.endswith('/vllm-rs'), 'Common-image engine must use native vLLM gRPC entrypoint'
        assert engine['image']==sidecar['image']==lock_model(run)['runtime_image']
        (run.path/'engine-entrypoint.txt').write_text(command+'\n')
    else:
        assert packages['vllm']=='0.28.0'
        assert packages['ai-dynamo'] is None, 'Engine unexpectedly has an in-process Dynamo installation'
    (run.path/'engine-packages.json').write_text(json.dumps(packages,indent=2)+'\n')
    run.result('engine-sidecar','passed',pod=pod['metadata']['name'],node=pod['spec']['nodeName'],
        engine_image=engine['image'],sidecar_image=sidecar['image'],engine_packages=packages,
        evidence=['sidecar-smoke.json','engine-sidecar.log','engine-packages.json'],
        scope='Native vLLM gRPC engine, separate CPU-only sidecar, registered model and expected inference output. SGLang and feature parity were not tested.')


if __name__=='__main__':main()
