#!/usr/bin/env python3
"""Build the pinned public KVCR integration without upgrading shared infrastructure."""
import argparse
import json
import re
import time
import uuid
from pathlib import Path
import yaml
from serving_tests import render, lock_model, frontend
from request_tests import send, metrics
from testlib import ROOT, Run


def build(run):
    run.ensure_namespace()
    lock=json.loads((ROOT/'configs/kvcr-lock.json').read_text())
    image=json.loads((ROOT/'configs/kvcr-build-image.json').read_text())[0]['image']
    run.apply([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'kvcr-build'},
        'data':{'build.sh':(ROOT/'scripts/kvcr-build.sh').read_text()}}])
    pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':'kvcr-build'},'spec':{
        'restartPolicy':'Never','activeDeadlineSeconds':2400,'automountServiceAccountToken':False,
        'containers':[{'name':'build','image':image,'command':['bash','/scripts/build.sh'],
            'env':[{'name':'DYNAMO_REF','value':lock['dynamo_revision']},{'name':'TEST_RUN','value':run.state['run_id']}],
            'resources':{'requests':{'cpu':'8','memory':'16Gi','ephemeral-storage':'20Gi'},
                         'limits':{'cpu':'8','memory':'32Gi','ephemeral-storage':'60Gi'}},
            'volumeMounts':[{'name':'scripts','mountPath':'/scripts','readOnly':True},
                {'name':'work','mountPath':'/work'},{'name':'efs','mountPath':'/efs'}]}],
        'volumes':[{'name':'scripts','configMap':{'name':'kvcr-build'}},{'name':'work','emptyDir':{'sizeLimit':'40Gi'}},
                   {'name':'efs','persistentVolumeClaim':{'claimName':'feature-cache'}}]}}
    run.apply([pod]);run.result('kvcr-build','created',image=image,compatibility_set=lock,
        note='CPU-only isolated binding build; package presence cannot count as integrated KVCR success')


def status(run):
    pod=run.get('get','pod','kvcr-build','-n',run.ns)
    logs=run.k('logs','kvcr-build','-n',run.ns,'--tail=80',check=False)
    (run.path/'kvcr-build-latest.log').write_text(logs.stdout+logs.stderr)
    print(json.dumps({'phase':pod.get('status',{}).get('phase'),'containers':pod.get('status',{}).get('containerStatuses')},indent=2))
    print(logs.stdout[-3000:])
    if pod.get('status',{}).get('phase')=='Failed':run.result('kvcr-build','blocked',error=logs.stdout[-2500:])
    elif pod.get('status',{}).get('phase')=='Succeeded':
        assert 'KVCR_DYNAMO_BUILD_COMPLETE' in logs.stdout
        run.result('kvcr-build','passed',wheels=f'feature-tests/{run.state["run_id"]}/kvcr-wheels')


def deploy(run):
    model=lock_model(run)
    if model.get('common_runtime'):
        pass  # The matched integration and bindings are already baked into this image.
    elif not run.state.get('kvcr_wheels_run_id'):
        pod=run.get('get','pod','kvcr-build','-n',run.ns)
        if pod.get('status',{}).get('phase')!='Succeeded':
            raise ValueError('Wait for the pinned Dynamo binding build to succeed')
    elif run.state.get('checks',{}).get('upgrade-cache-reuse',{}).get('status')!='passed':
        raise ValueError('Verify the cached wheels before reusing them')
    lock=json.loads((ROOT/'configs/kvcr-lock.json').read_text())
    model=lock_model(run)
    run.apply([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'kvcr-runtime'},'data':{
        'prepare.py':(ROOT/'scripts/kvcr_prepare_runtime.py').read_text(),
        'entrypoint.sh':(ROOT/'scripts/kvcr-entrypoint.sh').read_text(),
        'worker.py':(ROOT/'scripts/kvcr_worker.py').read_text(),
        'kvcr-lock.json':json.dumps(lock),'model-lock.json':json.dumps(model)}}])
    graph=render(run,'agg');graph['metadata']['name']='ft-kvcr'
    nodes=['kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198']
    worker=next(c for c in graph['spec']['components'] if c['type']=='worker')
    worker['podTemplate']['metadata'].setdefault('labels',{}).update({'feature-test-role':'kvcr'})
    worker['podTemplate']['spec']['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]['labelSelector']['matchLabels']={'feature-test-role':'kvcr'}
    for component in graph['spec']['components']:
        component['runtimeVersionOverride']='1.6.0'
        spec=component['podTemplate']['spec'];main=spec['containers'][0]
        common=bool(model.get('common_runtime'))
        main['image']=model['runtime_image'] if common else lock['vllm_image']
        main['securityContext']={'runAsUser':0,'capabilities':{'add':['IPC_LOCK','SYS_RESOURCE']}}
        main['env'] += [{'name':'TEST_RUN','value':run.state.get('kvcr_wheels_run_id',run.state['run_id'])},
            {'name':'POD_IP','valueFrom':{'fieldRef':{'fieldPath':'status.podIP'}}},
            {'name':'VLLM_KV_EVENTS_USE_INT_BLOCK_HASHES','value':'1'},
            {'name':'VLLM_LOGGING_LEVEL','value':'INFO' if model.get('tensor_parallel_size',1)>1 else 'DEBUG'},
            {'name':'NIXL_LOG_LEVEL','value':'INFO'},{'name':'FI_PROVIDER','value':'efa'},
            {'name':'FI_EFA_USE_DEVICE_RDMA','value':'1'},{'name':'FI_EFA_FORK_SAFE','value':'1'},
            {'name':'FI_EFA_ENABLE_SHM_TRANSFER','value':'0'},{'name':'FI_HMEM_CUDA_USE_DMABUF','value':'1'}]
        spec['volumes'].append({'name':'kvcr','configMap':{'name':'kvcr-runtime'}})
        main['volumeMounts'].append({'name':'kvcr','mountPath':'/kvcr','readOnly':True})
        if component['type']=='frontend':
            main['command']=['bash','/kvcr/entrypoint.sh'];main['args']=['python3','-m','dynamo.frontend','--router-mode','kv','--trust-remote-code']
            if common:
                main['command']=['python3','-m','dynamo.frontend']
                main['args']=['--router-mode','kv','--trust-remote-code']
        else:
            if run.state.get('kvcr_canary_timeout'):
                main['env']=[item for item in main['env'] if item['name']!='DYN_HEALTH_CHECK_REQUEST_TIMEOUT']
                main['env'].append({'name':'DYN_HEALTH_CHECK_REQUEST_TIMEOUT',
                                    'value':str(run.state['kvcr_canary_timeout'])})
            for resources in main['resources'].values():resources['vpc.amazonaws.com/efa']=str(4*model.get('tensor_parallel_size',1))
            spec['volumes'].append({'name':'efa','configMap':{'name':'efa-userspace'}})
            main['volumeMounts'].append({'name':'efa','mountPath':'/efa','readOnly':True})
            main['command']=['bash','/efa/entrypoint.sh'];main['args']=['bash','/kvcr/entrypoint.sh','python3','/kvcr/worker.py']
            if common:
                main['args']=['python3','/kvcr/worker.py']
    destination=ROOT/'configs/dgd'/model.get('manifest_directory','common-runtime' if model.get('common_runtime') else '')/'nemotron-kvcr.yaml'
    destination.parent.mkdir(parents=True,exist_ok=True)
    run.write_manifest(destination, [graph])
    run.apply([graph]);run.result('kvcr-deployment','created',model=model['model'],backend='LIBFABRIC',
        scope='Matched public preview binding/adapter set in isolated test containers; no shared operator upgrade')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['build','status','deploy','verify','reset','cleanup'])
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--canary-timeout',type=int,help='Worker-only canary timeout for cold JIT qualification')
    args=parser.parse_args();run=Run(args.run)
    if args.canary_timeout is not None:
        if not 3<=args.canary_timeout<=300:raise ValueError('Canary timeout must be 3..300 seconds')
        if args.action not in ('deploy','reset'):raise ValueError('Timeout changes require deploy/reset')
        run.state['kvcr_canary_timeout']=args.canary_timeout;run.save()
    if args.action=='build':build(run)
    elif args.action=='status':status(run)
    elif args.action=='deploy':deploy(run)
    elif args.action=='verify':verify(run)
    elif args.action=='reset':
        run.ensure_namespace()
        graph=run.get('get','dgd','ft-kvcr','-n',run.ns)
        assert graph['metadata'].get('labels',{}).get('feature-test-run')==run.ns
        run.k('delete','dgd','ft-kvcr','-n',run.ns,'--wait=true','--timeout=120s',timeout=140)
        deploy(run)
    else:run.k('delete','pod','kvcr-build','-n',run.ns,'--ignore-not-found','--wait=false')

def registered_workers(run):
    """Identify both owned peers without assuming KV routing is round robin."""
    pods={p['metadata']['name']:p for p in run.get('get','pods','-n',run.ns)['items']
          if p['metadata'].get('labels',{}).get('feature-test-role')=='kvcr'
          and any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[]))}
    assert len(pods)==2,'Need two Ready owned KVCR Pods'
    metadata=run.get('get','dynamoworkermetadatas','-n',run.ns)
    (run.path/'kvcr-worker-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    workers=set()
    for item in metadata['items']:
        pod=pods.get(item['metadata']['name'])
        if not pod:continue
        if not any(o.get('kind')=='Pod' and o.get('uid')==pod['metadata']['uid']
                   for o in item['metadata'].get('ownerReferences',[])):
            raise ValueError('KVCR metadata is not owned by the live Pod')
        endpoints=item['spec']['data'].get('endpoints',{}).values()
        ids={e['instance_id'] for e in endpoints if e.get('component')=='backend' and e.get('endpoint')=='generate'}
        assert len(ids)==1,'Need exactly one generate endpoint per KVCR Pod'
        workers.update(ids)
    assert len(workers)==2,'Need two registered KVCR endpoints'
    return workers


def verify(run):
    run.k('wait','--for=condition=Ready','dgd/ft-kvcr','-n',run.ns,'--timeout=900s',timeout=930)
    model=lock_model(run)['model'];receipts=[];tag=uuid.uuid4().hex
    def payload(content,query=False):
        return {'model':model,'messages':[{'role':'user','content':content}], 'max_tokens':16,'temperature':0,
            'chat_template_kwargs':{'enable_thinking':False},'stream_options':{'include_usage':True},
            'nvext':{'extra_fields':['worker_id','timing'],'annotations':['query_instance_id:'] if query else []}}
    try:
        with frontend(run,'kvcr') as base:
            workers=registered_workers(run)
            for worker in sorted(workers):
                r=send(base,payload(f'discover {tag} {worker}',True),
                    {'x-dynamo-worker-instance-id':str(worker),'x-dynamo-dp-rank':'0'})
                receipts.append({'step':'discover','expected_worker':worker,**r})
                assert r['worker'] and r['worker']['decode_worker_id']==worker,'Forced endpoint selection failed'
            source,target=sorted(workers)
            before=metrics(run,'kvcr','before')
            lock=lock_model(run)
            prefix=f'Unique KVCR test {tag}. '+' apple'*lock.get('routing_prefix_words',6000 if lock.get('tensor_parallel_size',1)>1 else 2800)
            seed=send(base,payload(prefix+' Source request: reply with READY.'),{'x-dynamo-worker-instance-id':str(source),'x-dynamo-dp-rank':'0'})
            receipts.append({'step':'seed','expected_worker':source,**seed})
            assert seed['worker']['decode_worker_id']==source
            assert seed['usage']['prompt_tokens_details']['cached_tokens']==0
            time.sleep(15)
            retrieved=send(base,payload(prefix+' Target request: reply with READY.'),{'x-dynamo-worker-instance-id':str(target),'x-dynamo-dp-rank':'0'})
            receipts.append({'step':'retrieve','expected_worker':target,**retrieved})
            assert retrieved['worker']['decode_worker_id']==target
            text=''.join(c['choices'][0].get('delta',{}).get('content','') or '' for c in retrieved['chunks'] if c.get('choices'))
            assert 'READY' in text,f'Unexpected target output: {text!r}'
            time.sleep(12)
            after=metrics(run,'kvcr','after')
        def values(records,metric,labels):
            result={}
            for pod,r in records.items():
                if '-agg-' not in pod:continue
                result[pod]=sum(float(line.rsplit(' ',1)[-1]) for text in r['metrics'].values() if isinstance(text,str)
                    for line in text.splitlines() if line.split('{',1)[0].removesuffix('_total')==metric
                    and all(label in line for label in labels))
            return result
        def deltas(metric,labels):
            a=values(after,metric,labels);b=values(before,metric,labels)
            return {p:a[p]-b.get(p,0) for p in a}
        source_blocks=deltas('vllm:kvcr_transfer_blocks',['operation="source_write"'])
        target_blocks=deltas('vllm:kvcr_transfer_blocks',['operation="remote_deliver"'])
        # This matched preview reports source-write bytes through the tiering
        # counter, rather than the older kvcr_transfer_bytes name in the guide.
        source_bytes=deltas('vllm:kv_offload_tiering_write_bytes',['1:kvcr'])
        target_bytes=deltas('vllm:kv_offload_tiering_read_bytes',['1:kvcr'])
        failed=deltas('vllm:kvcr_duration_seconds_count',['scope="remote_deliver"','result="failed"'])
        partial=deltas('vllm:kvcr_duration_seconds_count',['scope="remote_deliver"','result="partial"'])
        assert sum(source_blocks.values())==sum(target_blocks.values())>0, 'Source/target transferred block counts must match and be positive'
        assert sum(source_bytes.values())==sum(target_bytes.values())>0, 'Source-write/destination-read bytes must match and be positive'
        assert sum(failed.values())==sum(partial.values())==0
        source_pod=next(p for p,v in source_blocks.items() if v>0);target_pod=next(p for p,v in target_blocks.items() if v>0)
        assert after[source_pod]['node']!=after[target_pod]['node']
        assert retrieved['usage']['prompt_tokens_details']['cached_tokens']>0
        for pod in (source_pod,target_pod):
            logs=run.k('logs',pod,'-n',run.ns,'-c','main','--tail=5000','--limit-bytes=2097152').stdout
            (run.path/f'kvcr-full-{pod}.log').write_text(logs)
            assert 'using provider=efa' in logs, f'No EFA rail evidence in {pod}'
        run.result('kvcr','passed',model=model,source_node=after[source_pod]['node'],target_node=after[target_pod]['node'],
            blocks=sum(source_blocks.values()),bytes=sum(source_bytes.values()),cached_tokens=retrieved['usage']['prompt_tokens_details']['cached_tokens'],
            backend='LIBFABRIC',provider='efa',
            remote_failed=sum(failed.values()),remote_partial=sum(partial.values()),
            evidence=['kvcr-requests.json','kvcr-metrics-before.json','kvcr-metrics-after.json'],
            scope='Cross-node router-hinted peer cache reuse; matched source/destination blocks and bytes plus expected output')
    except Exception as exc:
        run.result('kvcr','blocked',error=str(exc));raise
    finally:
        (run.path/'kvcr-requests.json').write_text(json.dumps(receipts,indent=2)+'\n')
        for pod in run.get('get','pods','-n',run.ns)['items']:
            if pod['metadata']['name'].startswith('ft-kvcr'):
                logs=run.k('logs',pod['metadata']['name'],'-n',run.ns,'-c','main','--tail=5000','--limit-bytes=2097152',check=False)
                (run.path/f'kvcr-full-{pod["metadata"]["name"]}.log').write_text(logs.stdout+logs.stderr)


if __name__=='__main__':main()
