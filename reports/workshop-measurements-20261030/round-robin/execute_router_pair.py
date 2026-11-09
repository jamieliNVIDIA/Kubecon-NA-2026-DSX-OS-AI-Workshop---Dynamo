#!/usr/bin/env python3
"""Run one prespecified fresh-worker RR/KV router-policy pair after scale-out."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import yaml

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import execute_pair as e


def qualify_discovery(run,arm,router_mode):
    files=list((run.path/arm).glob('*frontend*.log'))
    text='\n'.join(re.sub(r'\x1b\[[0-9;]*m','',p.read_text()) for p in files)
    ids=sorted(set(re.findall(r'Adding worker WorkerWithDpRank \{ worker_id: (\d+), dp_rank: 0 \}',text)))
    evidence={'registered_worker_ids':ids,'frontend_logs':[str(p) for p in files]}
    if router_mode=='kv':
        evidence['zmq_event_sources']=sorted(set(re.findall(r'ZMQ single-consumer stream connected.*?endpoint="([^"]+)"',text)))
        if len(ids)!=2 or len(evidence['zmq_event_sources'])!=2:
            raise RuntimeError('Two-worker KV discovery/event ingress is not qualified; see frontend logs')
    (run.path/arm/'discovery-qualification.json').write_text(json.dumps(evidence,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--concurrency',type=int,choices=[1,4],required=True)
    p.add_argument('--attempt',required=True)
    args=p.parse_args();run=e.Run(args.run)
    if not re.fullmatch(r'[a-z0-9-]+',args.attempt):raise ValueError('Invalid attempt label')
    from campaign_prerequisites import resolve
    prerequisite_evidence=resolve(run)
    intent=run.path/f'router-pair-c{args.concurrency}-{args.attempt}-intent.json'
    plan=HERE/'KV_EXTENSION_PLAN.md'
    with intent.open('x') as f:f.write(json.dumps({'at':e.now(),'concurrency':args.concurrency,
        'attempt':args.attempt,'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),
        'order':['round-robin','kv'],'repetitions':1,'fresh_worker_processes_each_arm':True,
        'scaleout_prerequisites':prerequisite_evidence},indent=2)+'\n')
    owned=False
    try:
        for mode in ('round-robin','kv'):
            e.acquire(run,10800);owned=True
            if e.workers(run) or run.get('get','resourceclaims','-n',run.ns)['items']:
                raise RuntimeError('Routing-policy arm requires all previous owned GPU workers/claims to be cleaned')
            arm=f'routing-c{args.concurrency}-{mode}-{args.attempt}'
            dest=run.path/arm;dest.mkdir(exist_ok=False)
            for name in ('execute_router_pair.py','execute_pair.py','cluster.py','PLAN.md','KV_EXTENSION_PLAN.md'):
                shutil.copy2(HERE/name,dest/name)
            template=HERE/'router-extension-candidates'/f'two-worker-{mode}-template.yaml'
            # Frozen candidates carry the old run's namespace. Rebind only its
            # identity/ownership plumbing for a fresh run, keeping serving flags
            # and the router-mode-only arm difference intact.
            content=yaml.safe_load(template.read_text())
            old_namespaces={o.get('metadata',{}).get('namespace') for o in content['items']}
            old_namespaces.discard(None)
            if len(old_namespaces)!=1:raise ValueError('Expected one candidate namespace')
            old_namespace=next(iter(old_namespaces))
            def rebind(value):
                if isinstance(value,dict):return {k:rebind(v) for k,v in value.items()}
                if isinstance(value,list):return [rebind(v) for v in value]
                if isinstance(value,str):return value.replace(old_namespace,run.ns)
                return value
            content=rebind(content)
            manifest=dest/'deployment.yaml'
            manifest.write_text(yaml.safe_dump(content,sort_keys=False))
            objects=content['items']
            if any(o.get('metadata',{}).get('namespace')!=run.ns for o in objects):
                raise ValueError('Fresh routing arm namespace mismatch')
            (dest/'manifest-provenance.json').write_text(json.dumps({
                'template':str(template),'template_sha256':hashlib.sha256(template.read_bytes()).hexdigest(),
                'source_namespace':old_namespace,'effective_namespace':run.ns,
                'effective_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
                'change_scope':'namespace/ownership identity only'},indent=2)+'\n')
            run.k('apply','--dry-run=client','-f',str(manifest));run.k('apply','--dry-run=server','-f',str(manifest))
            e.status(run,'deploying fresh two-worker routing-policy arm',arm=arm,router_mode=mode)
            run.apply(objects);pods=e.wait_serving(run,2,arm)
            from gpu_claims import verify_allocation
            for pod in pods:verify_allocation(run,pod,pod['spec']['containers'][0],2)
            e.collect_workers(run,arm)
            for pod in pods:
                log=(dest/(pod['metadata']['name']+'.log')).read_text()
                if not re.search(r'(?:max_model_len|max_seq_len|Using max model len)[^\n]{0,40}(?:1048576|1,048,576)',log):
                    raise RuntimeError('Native1M context missing from routing-policy worker log')
            base=e.endpoint(run)
            ids=e.smoke(run,base,2,arm,require_distribution=mode=='round-robin')
            e.collect_workers(run,arm);qualify_discovery(run,arm,mode)
            spec=e.seal_profile(run,base,pods,args.concurrency,2,arm,router_mode=mode,
                initial_gpu_cache='fresh worker processes before bounded endpoint smoke and canonical AgentX primer')
            run.result('router-'+arm+'-qualified','passed',worker_ids=ids,
                spec_sha256=hashlib.sha256((dest/'spec.json').read_bytes()).hexdigest())
            e.collect_frontend_metrics(run,base,arm,'before')
            e.status(run,'starting matched routing-policy AgentX profile',arm=arm,spec=spec)
            e.telemetry_start(run,pods,arm)
            try:e.launch_profile(run,arm);outcome=e.poll_profile(run,arm)
            finally:e.telemetry_stop(run,arm)
            e.collect_workers(run,arm);e.collect_frontend_metrics(run,base,arm,'after');e.collect_profile(run,arm)
            run.result('router-'+arm,'completed' if outcome['exit_code']==0 else 'failed',**outcome)
            if outcome['exit_code']:raise RuntimeError(f'Routing-policy AgentX arm exited {outcome["exit_code"]}')
            e.validate_profile(run,arm)
            e.cleanup_gpu(run);owned=False
        run.result(f'router-pair-c{args.concurrency}','completed')
        e.status(run,'matched routing-policy pair complete; analysis pending',concurrency=args.concurrency)
    except Exception as error:
        run.result(f'router-pair-c{args.concurrency}','blocked',error=str(error))
        e.status(run,'routing-policy experiment blocked; evidence preserved',error=str(error))
        raise
    finally:
        if owned:e.cleanup_gpu(run)


if __name__=='__main__':main()
