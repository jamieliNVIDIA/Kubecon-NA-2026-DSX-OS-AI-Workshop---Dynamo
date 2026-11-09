#!/usr/bin/env python3
"""Paired text-only MX startup: default health then faster worker health.

freeze/verify are offline. The delegated controller must wait for pilot02's
qualification and verified full cleanup before prepare/batch.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import text_only_startup_02 as core

base = core.base
previous = core.previous
CONTROL = ROOT / 'results/workshop-mx-startup-20261103-textonly02'
CONTROL_HELPER_SHA256 = 'cc000df2c9e38c1169acfdfee898a85453e76eca918f97ce5d4b0edcdbc13fa3'
CONTROL_SPEC_SHA256 = '2295888db6a944047e707c85a27e3aa729d2ea6ad0fe2b34ba3555080c52e2bf'
COMPILE_DIGEST = 'supervl-tp2-native1048576-seqs4-batch8192-textonly-e98d074e-health01'
ACTIVE_ARM = 'default'


def write(path, value):
    core.write(path, value)


def spec(run):
    return core.spec(run)


def generated(run, role, native=False, fast=False):
    objects = core.generate(run, role, native)
    if fast:
        baseline = json.loads((run.path / 'baseline-reference.json').read_text())
        for obj in objects:
            if obj['kind'] != 'DynamoGraphDeployment':
                continue
            c = next(x for x in obj['spec']['components'] if x['type']=='worker')['podTemplate']['spec']['containers'][0]
            original = c['startupProbe']
            budget = original['periodSeconds'] * original['failureThreshold']
            assert budget == 3600 and budget % 2 == 0
            original['periodSeconds'] = 2
            original['failureThreshold'] = budget // 2
            c['readinessProbe'] = copy.deepcopy(baseline['worker_probes']['readinessProbe'])
            c['readinessProbe']['periodSeconds'] = 2
            assert not any(e['name']=='DYN_CANARY_WAIT_TIME' for e in c['env'])
            c['env'].append({'name':'DYN_CANARY_WAIT_TIME','value':'1'})
    return objects


def manifests(run, role, native=False):
    name = 'source' if role=='source' else 'target-native' if native else (
        'target-fast-health' if ACTIVE_ARM=='fast' else 'target-default-health')
    return copy.deepcopy(json.loads((run.path / (name+'.json')).read_text())['items'])


def freeze(run):
    if (run.path / 'inputs-sha256.json').exists():
        verify(run)
        return
    assert not (run.path / 'spec.json').exists(), 'Preserve partial freeze and create a fresh attempt'
    assert base.digest(core.__file__)==CONTROL_HELPER_SHA256
    assert base.digest(CONTROL/'spec.json')==CONTROL_SPEC_SHA256
    control = json.loads((CONTROL/'spec.json').read_text())
    assert run.state['model_lock']==control['model_lock']
    baseline = json.loads((CONTROL/'baseline-reference.json').read_text())
    write(run.path/'baseline-reference.json',baseline)
    write(run.path/'pilot02-reference.json',{'control_helper_sha256':CONTROL_HELPER_SHA256,
        'control_spec_sha256':CONTROL_SPEC_SHA256,'spec':control,
        'scope':'Identity/control reference only; pilot02 result is not yet consumed'})
    frozen = copy.deepcopy(control)
    frozen.update(schema=4,script_sha256=base.digest(__file__),
        control_helper_sha256=CONTROL_HELPER_SHA256,
        baseline_reference_sha256=base.digest(run.path/'baseline-reference.json'),
        compile_config_digest=COMPILE_DIGEST,
        sequence=['text-only-source-bootstrap','text-only-default-health','text-only-fast-health'],
        comparison_group='One fixed-order matched receiver pair, same retained idle text-only source',
        changed_worker_args=['--language-model-only'],
        control_changes='Only receiver health policy differs; engine/model/GPU/context/batching/memory/transport unchanged',
        receiver_arms=[
            {'name':'default','tag':'text-only-default-health','manifest':'target-default-health.json',
             'canary_wait_seconds':10,'startup_period_seconds':30,'startup_failure_threshold':120,'readiness_period_seconds':10},
            {'name':'fast','tag':'text-only-fast-health','manifest':'target-fast-health.json',
             'canary_wait_seconds':1,'startup_period_seconds':2,'startup_failure_threshold':1800,'readiness_period_seconds':2}],
        startup_failure_budget_seconds=3600,
        health_scope='Worker probes/canary only; frontend probes, liveness and all probe timeouts unchanged',
        health_tradeoff='More frequent startup/readiness probes and idle canaries; readiness failure detection nominally 6 s rather than 30 s')
    write(run.path/'spec.json',frozen)
    (run.path/'spec.sha256').write_text(base.digest(run.path/'spec.json')+'\n')
    definitions=[('source','source',False,False),('target-native','target',True,False),
        ('target-p2p','target',False,False),('target-artifacts','target',False,False),
        ('target-default-health','target',False,False),('target-fast-health','target',False,True)]
    for name,role,native,fast in definitions:
        write(run.path/(name+'.json'),{'apiVersion':'v1','kind':'List','items':generated(run,role,native,fast)})
    write(run.path/'coordinator.json',{'apiVersion':'v1','kind':'List','items':previous.coordinator_objects(run)})
    paths=[Path(__file__),Path(core.__file__),Path(previous.__file__),Path(base.__file__),
        core.MX/'analyze_startup.py',Path(control['source_template']),Path(control['target_template']),
        ROOT/'configs/super-vl-tp2-lock.json',
        ROOT/'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh',
        HERE/'pinned-dynamo-config.rs',HERE/'pinned-dynamo-health_check.rs']
    paths += [ROOT/'scripts'/name for name in ['testlib.py','storage_tests.py','common_runtime_tests.py',
        'common_runtime_build.py','serving_tests.py','gpu_claims.py','feature_tests.py']]
    paths += [run.path/name for name in ['spec.json','baseline-reference.json','pilot02-reference.json',
        'source.json','target-native.json','target-p2p.json','target-artifacts.json',
        'target-default-health.json','target-fast-health.json','coordinator.json']]
    write(run.path/'inputs-sha256.json',{str(p.relative_to(ROOT)):base.digest(p) for p in paths})
    verify(run)
    core.status('Health pair frozen offline; no Kubernetes activity')


def verify(run):
    core.verify_inputs(run)
    frozen=spec(run)
    assert base.digest(core.__file__)==CONTROL_HELPER_SHA256
    assert frozen['receiver_arms'][0]['name']=='default' and frozen['receiver_arms'][1]['name']=='fast'
    assert frozen['startup_failure_budget_seconds']==3600
    for arm in frozen['receiver_arms']:
        objects=json.loads((run.path/arm['manifest']).read_text())['items']
        dgd=next(x for x in objects if x['kind']=='DynamoGraphDeployment')
        c=next(x for x in dgd['spec']['components'] if x['type']=='worker')['podTemplate']['spec']['containers'][0]
        assert c['startupProbe']['periodSeconds']==arm['startup_period_seconds']
        assert c['startupProbe']['failureThreshold']==arm['startup_failure_threshold']
        assert c['startupProbe']['periodSeconds']*c['startupProbe']['failureThreshold']==3600
        env={e['name']:e.get('value') for e in c['env']}
        assert env.get('DYN_CANARY_WAIT_TIME')==('1' if arm['name']=='fast' else None)
        if arm['name']=='fast':assert c['readinessProbe']['periodSeconds']==2


def prepare(run):
    # Untimed CPU plumbing: ensure Redis Ready before starting its coordinator.
    # This avoids the observed first-prepare Redis-connection timeout in pilot02.
    original_apply=run.apply
    def ordered(objects,**kwargs):
        server=[o for o in objects if o['kind']=='Pod' and o['metadata']['name']=='mx-coordinator']
        redis=[o for o in objects if o['kind']=='Pod' and o['metadata']['name']=='mx-redis']
        if server and redis:
            original_apply([o for o in objects if o not in server],**kwargs)
            run.wait_pod('mx-redis',timeout=300)
            return original_apply(server,**kwargs)
        return original_apply(objects,**kwargs)
    run.apply=ordered
    try:previous.prepare(run)
    finally:run.apply=original_apply
    path=run.path/'target-fast-health.json'
    run.k('apply','--dry-run=client','-f',str(path))
    run.k('apply','--dry-run=server','-f',str(path))
    verify(run)
    run.result('health-pair-preparation','passed',scope='CPU-only preparation and both receiver manifest dry-runs')


def validate(run,tag,role,result,arm='default'):
    folder=run.path/tag
    pod=core.worker_from(folder,role)
    c=pod['spec']['containers'][0]
    expected=next(o for o in manifests(run,role) if o['kind']=='DynamoGraphDeployment')
    expected_c=next(o for o in expected['spec']['components'] if o['type']=='worker')['podTemplate']['spec']['containers'][0]
    assert c['args']==expected_c['args'] and c['image']==expected_c['image']
    wanted=copy.deepcopy(json.loads((run.path/'baseline-reference.json').read_text())['worker_probes'])
    if arm=='fast':
        wanted['startupProbe']['periodSeconds']=2
        wanted['startupProbe']['failureThreshold']=1800
        wanted['readinessProbe']['periodSeconds']=2
    assert {k:c[k] for k in wanted}==wanted,'Effective probes differ from this arm'
    env={e['name']:e.get('value') for e in c['env']}
    assert env.get('DYN_CANARY_WAIT_TIME')==('1' if arm=='fast' else None)
    assert result['models']['data'][0]['context_window']==1048576
    assert pod['spec']['nodeName']==spec(run)['source_node' if role=='source' else 'target_node']
    assert all(x.get('restartCount',0)==0 for x in pod['status']['containerStatuses'])
    assert all(x['imageID'].endswith(spec(run)['model_lock']['runtime_image'].split('@')[1]) for x in pod['status']['containerStatuses'])
    gpu=(folder/'gpu-visible.csv').read_text().strip().splitlines()
    assert len(gpu)==2 and all('H100' in x for x in gpu)
    logs=previous.logs_for(run,folder,role)
    waits=sorted(set(re.findall(r'canary_wait_time_secs=(\d+)',logs)))
    assert waits==(['1'] if arm=='fast' else ['10']),waits
    marker=[s for s in logs.splitlines() if 'running in text-only mode' in s]
    unexpected=[s for s in logs.splitlines() if 'Multi-modal warmup completed' in s or 'Encoder cache will be initialized with a budget' in s]
    assert marker and not unexpected,'Text-only engine execution not established'
    proof={'passed':True,'worker_uid':pod['metadata']['uid'],'arm':arm,
        'native_context':1048576,'text_only_mode_lines':marker,'unexpected_mm_lines':unexpected,
        'canary_wait_seconds_observed':waits,'effective_probes':wanted,
        'nominal_startup_failure_budget_seconds':wanted['startupProbe']['periodSeconds']*wanted['startupProbe']['failureThreshold']}
    write(folder/'identity-health-proof.json',proof)


def retained_source(run,folder,uid):
    pod=core.worker_from(folder,'source')
    assert pod['metadata']['uid']==uid
    assert all(c.get('restartCount',0)==0 for c in pod['status']['containerStatuses'])
    assert any(c['type']=='Ready' and c['status']=='True' for c in pod['status']['conditions'])


def stop_target(run,uid):
    before=run.get('get','pods','-n',run.ns)
    target=next(p for p in before['items'] if p['metadata']['uid']==uid)
    claim_names={x['resourceClaimName'] for x in target.get('status',{}).get('resourceClaimStatuses',[]) if x.get('resourceClaimName')}
    claim_names.update(x['resourceClaimName'] for x in target['spec'].get('resourceClaims',[]) if x.get('resourceClaimName'))
    base.stop_graph(run,'ft-mx-target')
    deadline=time.monotonic()+180
    while True:
        pods=run.get('get','pods','-n',run.ns)
        claims=run.get('get','resourceclaims','-n',run.ns)
        old_claims=[c['metadata']['name'] for c in claims['items'] if c['metadata']['name'] in claim_names or
                    c['metadata']['name'].startswith('ft-mx-target-') or
                    any(r.get('uid')==uid for r in c['metadata'].get('ownerReferences',[]))]
        assert not any(p['metadata']['uid']==uid for p in pods['items'])
        if not old_claims:
            write(run.path/'between-arm-cleanup.json',{'at':base.now(),'deleted_receiver_uid':uid,
                'old_receiver_claims':old_claims,'remaining_pods':[p['metadata']['name'] for p in pods['items']]})
            return
        if time.monotonic()>=deadline:raise RuntimeError('First receiver ResourceClaims were not cleaned')
        time.sleep(5)


def batch(run):
    global ACTIVE_ARM
    verify(run)
    assert run.state.get('checks',{}).get('health-pair-preparation',{}).get('status')=='passed'
    assert not (run.path/'batch-started.json').exists(),'No replay of a started paired trial'
    base.acquire(run)
    write(run.path/'batch-started.json',{'at':base.now(),'sequence':spec(run)['sequence']})
    try:
        ACTIVE_ARM='default'
        source=previous.run_arm(run,'text-only-source-bootstrap','source')
        validate(run,'text-only-source-bootstrap','source',source)
        core.status('Default-health text-only seed Ready; awaiting fresh compiler artifacts')
        previous.await_artifact_publication(run)
        arms={};proofs={}
        for arm in spec(run)['receiver_arms']:
            ACTIVE_ARM=arm['name']
            core.status('Starting paired receiver: '+ACTIVE_ARM)
            result=previous.run_arm(run,arm['tag'],'target')
            validate(run,arm['tag'],'target',result,ACTIVE_ARM)
            retained_source(run,run.path/arm['tag'],source['pod_uid'])
            proof=core.cache_proof(run,arm['tag'])
            write(run.path/arm['tag']/'artifact-reuse-evidence.json',proof)
            arms[ACTIVE_ARM]=result;proofs[ACTIVE_ARM]=proof
            core.status(ACTIVE_ARM+' receiver Ready/correct; both TP artifact-cache hits passed')
            stop_target(run,result['pod_uid'])
        assert arms['default']['pod_uid']!=arms['fast']['pod_uid']
        assert proofs['default']['installed_torch_artifact_ids']==proofs['fast']['installed_torch_artifact_ids'], 'Receiver artifacts changed within matched pair'
        write(run.path/'artifact-reuse-evidence.json',proofs)
        delta=arms['default']['apply_to_ready_observed_seconds']-arms['fast']['apply_to_ready_observed_seconds']
        write(run.path/'comparison.json',{'source':source,'default':arms['default'],'fast':arms['fast'],
            'ready_seconds_default_minus_fast':delta,
            'ready_fraction_reduction':delta/arms['default']['apply_to_ready_observed_seconds'],
            'same_installed_torch_artifact_ids':proofs['default']['installed_torch_artifact_ids'],
            'scope':'One fixed-order matched text-only receiver pair; health-policy change; no throughput/SLO/fault-detection qualification'})
        run.result('text-only-health-pair','passed',ready_seconds_default_minus_fast=delta)
    except Exception as error:
        try:base.collect(run,'failed-attempt')
        finally:run.result('text-only-health-pair','failed',error=repr(error))
        raise
    finally:
        core.clean_resources(run)
        core.seal(run)


def finalize(run):
    verify(run)
    cleanup=json.loads((run.path/'cleanup-proof.json').read_text())
    assert cleanup['verified'] and cleanup['gpu_lease_absent'] and not base.LEASE.exists()
    assert run.state['checks']['text-only-health-pair']['status']=='passed'
    import runpy
    runpy.run_path(str(core.MX/'analyze_startup.py'))['extract'](run.path)
    comparison=json.loads((run.path/'comparison.json').read_text())
    for arm in spec(run)['receiver_arms']:
        proof=json.loads((run.path/arm['tag']/'artifact-reuse-evidence.json').read_text())
        assert proof['actual_engine_cache_hit_ranks']==['0','1'] and not proof['failure_lines']
    write(run.path/'qualification.json',{'passed':True,'scope':comparison['scope'],
        'helper_sha256':base.digest(__file__),'cleanup_verified':True})
    core.seal(run)
    core.status('Paired health startup analysis and final evidence seal completed')
    core.seal(run)  # Include the terminal status in the final inventory.


def configure(run):
    core.COMPILE_DIGEST=COMPILE_DIGEST
    core.configure(run)
    previous.COMPILE_DIGEST=COMPILE_DIGEST
    base.OWNER='/root/startup_textonly_health'
    base.manifests=manifests
    previous.central_manifests=manifests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['freeze','verify','prepare','batch','cleanup','finalize'])
    parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args()
    run=base.setup_run(args.run)
    configure(run)
    if args.action=='freeze':freeze(run);return
    verify(run)
    if args.action=='verify':core.status('Paired health inputs verified offline')
    elif args.action=='prepare':prepare(run)
    elif args.action=='batch':batch(run)
    elif args.action=='finalize':finalize(run)
    else:core.clean_resources(run);core.seal(run)


if __name__=='__main__':main()
