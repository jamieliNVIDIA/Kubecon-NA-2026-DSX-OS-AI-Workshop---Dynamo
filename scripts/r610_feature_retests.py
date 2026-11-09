#!/usr/bin/env python3
"""Bounded R610 feature rechecks using frozen Super VL TP2 inputs and cache.

Independent namespaces permit small parallel groups. No software upgrades,
Snapshot store changes or disk operations. Prior results are never promoted.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from testlib import ROOT, Run
from serving_tests import lock_model, model_cache_home

BASELINE = ROOT / 'results/20261015-super-vl-tp2'
FEATURES = ('agg', 'sidecar', 'image-smoke', 'grove', 'kvcr', 'disagg', 'mx', 'shadow')
GROUPS = (FEATURES[:4], FEATURES[4:7], FEATURES[7:])


def prepare(run, root, feature):
    old = json.loads((BASELINE/'state.json').read_text())
    lock = json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text())
    if old['owner'] != run.state['owner'] or old['checks']['model-staging']['status'] != 'passed':
        raise ValueError('Need owned, qualified baseline cache')
    for key in ('model', 'revision', 'runtime_image', 'tensor_parallel_size'):
        if old['model_lock'][key] != lock[key]:
            raise ValueError('Baseline mismatch: '+key)
    suffix = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
    namespace = 'dynamo-ft-r610-'+suffix+'-'+feature
    if (run.path/'model-lock.json').exists():
        raise ValueError('Use a fresh feature run; never inherit old pass receipts')
    run.ns = namespace;run.state['namespace'] = namespace
    lock['manifest_directory'] = 'super-vl-r610-'+suffix+'/'+feature
    (run.path/'model-lock.json').write_text(json.dumps(lock, indent=2)+'\n')
    run.state.update(model_cache_run_id=old.get('model_cache_run_id', old['run_id']),
                     baseline_run=str(BASELINE), feature=feature)
    run.save();lock_model(run)
    from storage_tests import prepare as storage
    from common_runtime_tests import pull_secret, efa
    storage(run);pull_secret(run);efa(run)
    from snapshot_tp2_workflow import cpu_probe
    program = '''import hashlib,json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK'])
root=Path(os.environ['HF_HOME'])/'hub'/('models--'+lock['model'].replace('/','--'))/'snapshots'/lock['revision']
index=json.loads((root/'model.safetensors.index.json').read_text())
weights=sorted(set(index['weight_map'].values()))
sizes={name:(root/name).stat().st_size for name in weights}
assert all(v>0 for v in sizes.values())
assert len(sizes)==lock['checkpoint_weight_files']
assert sum(sizes.values())==int(os.environ['EXPECTED_FILE_BYTES'])
for name in ('config.json','tokenizer_config.json','model.safetensors.index.json'):
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==lock['model_metadata_sha256'][name],name
print(json.dumps({'model':lock['model'],'revision':lock['revision'],'weight_files':len(sizes),
 'weight_bytes':sum(sizes.values()),'snapshot_path':str(root)}))
'''
    report = cpu_probe(run, 'retest-cache-check', program, [
        {'name':'HF_HOME','value':model_cache_home(run)},
        {'name':'MODEL_LOCK','value':json.dumps(lock)},
        {'name':'EXPECTED_FILE_BYTES','value':str(old['checks']['model-staging']['weight_bytes'])}], cache=True)
    run.result('model-staging','passed',**report,cache_source=run.state['model_cache_run_id'],
               scope='Fresh size/metadata-hash validation of exact cached revision; no download')


def cleanup(run, feature):
    from common_runtime_tests import stop, stop_grove
    if feature == 'grove':
        stop_grove(run)
    elif feature == 'shadow':
        from shadow_live_tests import finish_cleanup
        finish_cleanup(run)
    else:
        graphs = {'agg':['ft-agg'], 'sidecar':['ft-sidecar'], 'image-smoke':['ft-image'],
                  'kvcr':['ft-kvcr'], 'disagg':['ft-disagg'], 'mx':['ft-mx-target','ft-mx']}
        stop(run,graphs[feature])
    from super_vl_tests import idle
    idle(run)


def one(root, feature):
    run = Run(root/feature)
    prepare(run,root,feature)
    # Actual GPU/EFA probe on this namespace/image; no copied qualification.
    from super_vl_tests import feature as test
    test(run,'probe')
    from super_vl_tests import idle
    idle(run)
    log = run.path/(feature+'-console.log')
    command=[sys.executable,str(ROOT/'scripts/super_vl_tests.py'),'feature','--feature',feature,'--run',str(run.path)]
    # MX loads the source and then initializes a distinct receiver. Do not
    # undercut the existing 2400s per-engine startup waits with a 30m wrapper.
    timeout=5400 if feature=='mx' else 3600 if feature!='shadow' else 1500
    interrupted=False
    try:
        with log.open('w') as out:
            process=subprocess.Popen(command,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                interrupted=True
                os.killpg(process.pid,signal.SIGINT)
                try:
                    process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=30)
            code=process.returncode
        run.state=json.loads((run.path/'state.json').read_text())
        if code or interrupted:
            status='blocked'
        else:
            if run.state['checks'].get('super-vl-'+feature,{}).get('status')!='passed':
                raise ValueError('Child returned success without feature pass receipt')
            status='passed'
    finally:
        cleanup(run,feature)
    run.result('r610-feature',status,tested_feature=feature,exit_code=code,
               timed_out=interrupted,evidence=log.name)
    result={'feature':feature,'status':run.state['checks']['r610-feature']['status'],
            'run':str(run.path.relative_to(ROOT)),'namespace':run.ns}
    print(json.dumps(result),flush=True)
    return result


def recover_result(root, feature):
    run = Run(root/feature)
    state = run.state
    suffix = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
    expected_namespace = 'dynamo-ft-r610-'+suffix+'-'+feature
    expected_lock = json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text())
    if run.ns != expected_namespace:
        raise ValueError('Resume only this campaign namespace')
    for key in ('model','revision','runtime_image','tensor_parallel_size','gpu_allocation'):
        if state.get('model_lock',{}).get(key)!=expected_lock[key]:
            raise ValueError('Resume identity mismatch: '+key)
    child = state.get('checks',{}).get('super-vl-'+feature,{})
    if child.get('status') not in ('passed','blocked'):
        raise ValueError('Child has no terminal feature receipt; inspect instead of rerunning')
    cleanup(run,feature)
    run.result('r610-feature',child['status'],tested_feature=feature,
        evidence=feature+'-console.log',scope='Recovered same-campaign terminal child receipt after supervisor repair; no repeated workload')
    return {'feature':feature,'status':child['status'],'run':str(run.path.relative_to(ROOT)),'namespace':run.ns}


def matrix(root, resume=False):
    if root.exists() and not resume:
        raise ValueError('Matrix requires a fresh output directory')
    if not root.exists() and resume:
        raise ValueError('Resume requires an existing campaign')
    root.mkdir(parents=True,exist_ok=resume)
    guard=Run(root/'preflight')
    nodes=guard.get('get','nodes')['items']
    for n in nodes:
        if (n['metadata'].get('labels',{}).get('nvidia.com/cuda.driver-version.full')!='610.57.04'
            or not any(c['type']=='Ready' and c['status']=='True' for c in n['status']['conditions'])):
            raise ValueError('Requires all nodes Ready on 610.57.04')
    if guard.get('get','resourceclaims','-A')['items']:
        raise ValueError('Start only with idle GPU claims')
    if not resume:
        (root/'nodes-before.json').write_text(json.dumps({'items':nodes},indent=2)+'\n')
    results=[]
    for group in GROUPS:
        pending=[]
        for feature in group:
            if resume and (root/feature/'model-lock.json').exists():
                results.append(recover_result(root,feature))
            else:
                pending.append(feature)
        if not pending:
            (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
            continue
        print('Starting feature group: '+', '.join(pending),flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending)) as pool:
            futures={pool.submit(one,root,feature):feature for feature in pending}
            for future in concurrent.futures.as_completed(futures):
                feature=futures[future]
                try:
                    results.append(future.result())
                except Exception as error:
                    # Cleanup failure halts subsequent groups rather than admitting more GPUs.
                    results.append({'feature':feature,'status':'error','error':str(error)})
                (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        if any(r['status']=='error' for r in results):
            raise RuntimeError('Preparation or cleanup failure; inspect before proceeding')
    print(json.dumps(results,indent=2),flush=True)


def handoff_sidecar(root):
    import shlex
    run=Run(root/'sidecar')
    if run.state['checks'].get('sidecar-startup-grace',{}).get('status')!='applied':
        raise ValueError('Only after the recorded owned sidecar rollout')
    for feature in ('agg','image-smoke','grove'):
        state=json.loads((root/feature/'state.json').read_text())
        if state['checks'].get('super-vl-'+feature,{}).get('status')!='passed':
            raise ValueError('Other first-group workloads must already have passed')
    def processes():
        matches={'parent':[],'child':[]}
        for line in subprocess.check_output(['ps','-axo','pid=,uid=,command='],text=True).splitlines():
            fields=line.strip().split(None,2)
            if len(fields)!=3 or int(fields[1])!=os.getuid():continue
            try:argv=shlex.split(fields[2])
            except ValueError:continue
            if len(argv)<3 or not Path(argv[0]).name.lower().startswith('python'):continue
            script=Path(argv[1]);script=script if script.is_absolute() else ROOT/script
            if '--run' not in argv:continue
            target=Path(argv[argv.index('--run')+1]);target=target if target.is_absolute() else ROOT/target
            if script.resolve()==Path(__file__).resolve() and argv[2]=='matrix' and target.resolve()==root:
                matches['parent'].append(int(fields[0]))
            if script.resolve()==ROOT/'scripts/super_vl_tests.py' and argv[2:5]==['feature','--feature','sidecar'] and target.resolve()==run.path:
                matches['child'].append(int(fields[0]))
        return matches
    found=processes()
    if len(found['parent'])!=1 or len(found['child'])!=1:
        raise ValueError('Need one exact owned matrix and one sidecar child: '+str(found))
    record={'parent_pid':found['parent'][0],'child_pid':found['child'][0],
        'reason':'Original 1800s watchdog includes superseded cold-start attempts; preserve independently running replacement verification',
        'signal':'SIGTERM to local matrix only; child has its own session', 'max_remaining_wait_seconds':900}
    (root/'sidecar-watchdog-handoff.json').write_text(json.dumps(record,indent=2)+'\n')
    os.kill(record['parent_pid'],signal.SIGTERM)
    deadline=time.monotonic()+900
    while record['child_pid'] in processes()['child']:
        if time.monotonic()>deadline:
            os.kill(record['child_pid'],signal.SIGINT)
            raise TimeoutError('Sidecar verification exceeded fresh bounded wait; SIGINT invokes owned cleanup')
        time.sleep(5)
    print(json.dumps(recover_result(root,'sidecar')),flush=True)


def handoff_transfers(root):
    """Preserve current healthy children when the old wrapper deadline is short."""
    import shlex
    expected={'disagg','mx'}
    for feature in FEATURES[:4]+('kvcr',):
        state=json.loads((root/feature/'state.json').read_text())
        if state['checks'].get('r610-feature',{}).get('status') not in ('passed','blocked'):
            raise ValueError('Earlier feature is not terminal: '+feature)
    if (root/'shadow/model-lock.json').exists():raise ValueError('Shadow has already started')
    def processes():
        parents=[];children={}
        for line in subprocess.check_output(['ps','-axo','pid=,uid=,command='],text=True).splitlines():
            fields=line.strip().split(None,2)
            if len(fields)!=3 or int(fields[1])!=os.getuid():continue
            try:argv=shlex.split(fields[2])
            except ValueError:continue
            if len(argv)<3 or not Path(argv[0]).name.lower().startswith('python') or '--run' not in argv:continue
            script=Path(argv[1]);script=script if script.is_absolute() else ROOT/script
            target=Path(argv[argv.index('--run')+1]);target=target if target.is_absolute() else ROOT/target
            if script.resolve()==Path(__file__).resolve() and argv[2]=='resume' and target.resolve()==root:
                parents.append(int(fields[0]))
            if script.resolve()==ROOT/'scripts/super_vl_tests.py' and argv[2:4]==['feature','--feature']:
                feature=argv[4]
                if feature in expected and target.resolve()==root/feature:
                    if feature in children:raise ValueError('Duplicate feature process')
                    children[feature]=int(fields[0])
        return parents,children
    parents,children=processes()
    if len(parents)!=1 or not children:raise ValueError('Need one exact supervisor and live transfer children')
    record={'parent_pid':parents[0],'children':children,'signal':'SIGTERM to local supervisor only',
        'max_remaining_wait_seconds':900,
        'reason':'Old 30-minute wrapper undercuts per-engine startup waits after concurrent EFS loading; preserve bounded existing verifiers'}
    (root/'transfer-watchdog-handoff.json').write_text(json.dumps(record,indent=2)+'\n')
    os.kill(parents[0],signal.SIGTERM)
    deadline=time.monotonic()+900
    while processes()[1]:
        if time.monotonic()>deadline:
            for pid in processes()[1].values():os.kill(pid,signal.SIGINT)
            raise TimeoutError('Transfer verifiers exceeded fresh bounded wait; owned cleanup requested')
        time.sleep(5)
    for feature in children:
        print(json.dumps(recover_result(root,feature)),flush=True)


def extend_sidecar_grace(root):
    import copy
    run=Run(root/'sidecar')
    graph=run.get('get','dgd','ft-sidecar','-n',run.ns)
    if graph['metadata'].get('labels',{}).get('feature-test-run')!=run.ns:
        raise ValueError('Graph not owned')
    pods=[p for p in run.get('get','pods','-n',run.ns)['items'] if '-worker-' in p['metadata']['name']]
    if len(pods)!=1:raise ValueError('Expected one sidecar worker')
    pod=pods[0]
    if any(c['type']=='Ready' and c['status']=='True' for c in pod['status'].get('conditions',[])):
        run.result('sidecar-startup-grace','not-needed',scope='Worker already Ready; no mutation')
        return
    evidence=list((run.path/'diagnostics').glob('*/main-previous.log'))
    if not any('startup handshake timed out while waiting for READY after 600s' in p.read_text() for p in evidence):
        raise ValueError('Need exact preserved startup-timeout evidence')
    helper=run.path/'native-engine-help.txt'
    if '--engine-ready-timeout-secs' not in helper.read_text():
        raise ValueError('Native timeout option not verified in installed image')
    candidate=copy.deepcopy(graph)
    candidate.pop('status',None)
    candidate['metadata']={k:v for k,v in graph['metadata'].items() if k in ('name','namespace','labels','annotations')}
    candidate['metadata'].get('annotations',{}).pop('kubectl.kubernetes.io/last-applied-configuration',None)
    worker=next(c for c in candidate['spec']['components'] if c['type']!='frontend')
    main=worker['podTemplate']['spec']['containers'][0]
    if main['name']!='main' or main['image']!=run.state['model_lock']['runtime_image']:
        raise ValueError('Unexpected worker identity')
    if '--engine-ready-timeout-secs' in main['args']:
        raise ValueError('Startup grace already set; inspect instead of overwriting')
    main['args']+=['--engine-ready-timeout-secs','1800']
    (run.path/'sidecar-before-startup-grace.json').write_text(json.dumps(graph,indent=2)+'\n')
    run.write_manifest(run.path/'sidecar-startup-grace-applied.yaml',[candidate])
    run.apply([candidate])
    run.result('sidecar-startup-grace','applied',seconds=1800,old_pod_uid=pod['metadata']['uid'],
        scope='Owned sidecar DGD only; native engine handshake matches existing 30-minute startup probe; image/model unchanged')


def sidecar_help(root):
    run=Run(root/'sidecar')
    pods=[p for p in run.get('get','pods','-n',run.ns)['items'] if '-worker-' in p['metadata']['name']]
    if len(pods)!=1:raise ValueError('Need one owned sidecar worker')
    pod=pods[0]
    if pod['metadata'].get('labels',{}).get('feature-test-run')!=run.ns:raise ValueError('Worker not owned')
    code="import os,vllm,subprocess; print(subprocess.check_output([os.path.join(os.path.dirname(vllm.__file__),'vllm-rs'),'serve','--help'],text=True))"
    result=run.k('exec',pod['metadata']['name'],'-n',run.ns,'-c','main','--','python3','-c',code)
    (run.path/'native-engine-help.txt').write_text(result.stdout)
    for line in result.stdout.splitlines():
        if any(x in line.lower() for x in ('timeout','startup','handshake','engine-ready')):print(line)


def io_progress(root):
    observer=Run(root/'observer')
    states={json.loads(p.read_text())['namespace']:p.parent for p in root.glob('*/state.json') if p.parent.name in FEATURES}
    program = """import json
from pathlib import Path
out=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  comm=(p/'comm').read_text().strip()
  if not any(x in comm.lower() for x in ('worker','python','engine','vllm')):continue
  metrics=dict(line.split(':',1) for line in (p/'io').read_text().splitlines())
  out.append({'pid':p.name,'comm':comm,'io':{k:int(v) for k,v in metrics.items()},'wchan':(p/'wchan').read_text().strip()})
 except (FileNotFoundError,PermissionError):pass
print(json.dumps(out))
"""
    for pod in observer.get('get','pods','-A')['items']:
        ns=pod['metadata']['namespace']
        if ns not in states or pod['status'].get('phase')!='Running':continue
        if pod['metadata'].get('labels',{}).get('nvidia.com/dynamo-component-type')=='frontend':continue
        names={c['name'] for c in pod['spec'].get('containers',[])+pod['spec'].get('initContainers',[])}
        container='main' if 'main' in names else 'engine-0' if 'engine-0' in names else None
        if not container:continue
        result=observer.k('exec',pod['metadata']['name'],'-n',ns,'-c',container,'--','python3','-c',program,check=False)
        (states[ns]/('io-progress-'+pod['metadata']['name']+'-'+str(time.time_ns())+'.log')).write_text(result.stdout+result.stderr)
        print(ns,pod['metadata']['name'],result.stdout or result.stderr[-300:],flush=True)


def shadow_control(root):
    # A different model is permitted only after fresh preferred-model evidence.
    preferred=json.loads((root/'shadow/state.json').read_text())
    expected=json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text())
    for key in ('model','revision','runtime_image','tensor_parallel_size'):
        if preferred.get('model_lock',{}).get(key)!=expected[key]:
            raise ValueError('Preferred-model evidence identity mismatch')
    logs=list((root/'shadow').rglob('*.log'))
    if preferred['checks'].get('r610-feature',{}).get('status')!='blocked' or not any(
        'Shape/dtype mismatch for language_model.lm_head.input_scale' in p.read_text(errors='replace') for p in logs):
        raise ValueError("Alternate control needs this campaign's recorded Nemotron/GMS shape incompatibility")
    baseline=ROOT/'results/20261014-shadow-qwen-control'
    old=json.loads((baseline/'state.json').read_text())
    if old['model_lock']['runtime_image']!=expected['runtime_image']:
        raise ValueError('Control would change the frozen runtime image')
    if old['checks'].get('shadow-failover',{}).get('status')!='passed':
        raise ValueError('Control baseline not qualified')
    run=Run(root/'shadow-control')
    if (run.path/'model-lock.json').exists():raise ValueError('Use a fresh control run')
    suffix=hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8]
    run.ns='dynamo-ft-r610-'+suffix+'-shadow-control';run.state['namespace']=run.ns
    lock=dict(old['model_lock'])
    lock.update(gpu_allocation='dra',tensor_parallel_size=1,
        manifest_directory='super-vl-r610-'+suffix+'/shadow-control',
        model_substitution_reason='Fresh Super VL GMS parameter-shape mismatch; isolate driver/DRA process recovery',
        source_failure_run=str((root/'shadow').relative_to(ROOT)))
    (run.path/'model-lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    run.state.update(model_cache_run_id=old.get('model_cache_run_id',old['run_id']),baseline_run=str(baseline))
    run.save();lock_model(run)
    from storage_tests import prepare as storage
    from common_runtime_tests import pull_secret
    from snapshot_tp2_workflow import cpu_probe
    storage(run);pull_secret(run)
    program="""import json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK'])
path=Path(os.environ['HF_HOME'])/'hub'/('models--'+lock['model'].replace('/','--'))/'snapshots'/lock['revision']
weights=list(path.glob('*.safetensors'))
assert len(weights)==1 and sum(p.stat().st_size for p in weights)==1503300328
assert json.loads((path/'config.json').read_text())['model_type']=='qwen3'
print(json.dumps({'model':lock['model'],'revision':lock['revision'],'weight_files':len(weights),'weight_bytes':sum(p.stat().st_size for p in weights)}))
"""
    report=cpu_probe(run,'shadow-control-cache-check',program,[
        {'name':'MODEL_LOCK','value':json.dumps(lock)},{'name':'HF_HOME','value':model_cache_home(run)}],cache=True)
    run.result('model-staging','passed',**report,scope='Reverified original Qwen cache; no download')
    from super_vl_tests import shadow
    shadow(run)  # Existing hash-guarded overlay, active/standby, fault/recovery and cleanup gates.
    run.result('r610-shadow-control','passed',model=lock['model'],tensor_parallel_size=1,
        scope='Small-model process failover only; does not qualify preferred Nemotron or TP2 recovery')


def summarize(root, kvcr_retry=None):
    expected=json.loads((ROOT/'configs/super-vl-tp2-lock.json').read_text())
    required={'agg':('agg-inference','kv-routing'), 'sidecar':('sidecar-inference','engine-sidecar'),
        'image-smoke':('image-inference','super-vl-image'), 'grove':('grove-kai',),
        'kvcr':('kvcr-inference','kvcr','kvcr-canary-stability'),
        'disagg':('disagg-inference','disaggregation'), 'mx':('modelexpress',),
        'shadow':('shadow-failover',)}
    results={}
    for feature in FEATURES:
        path=root/feature/'state.json'
        state=json.loads(path.read_text())
        prior=None
        if feature=='kvcr' and kvcr_retry is not None:
            if state['checks'].get('kvcr',{}).get('error')!='Need two ready KVCR endpoints':
                raise ValueError('KVCR retry override requires the preserved discovery-test failure')
            prior={'state':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                   'status':state['checks'].get('r610-feature',{}).get('status'),
                   'error':state['checks']['kvcr']['error']}
            path=kvcr_retry/'kvcr/state.json'
            state=json.loads(path.read_text())
            suffix=hashlib.sha256(str(kvcr_retry.resolve()).encode()).hexdigest()[:8]
            if state['namespace']!='dynamo-ft-r610-'+suffix+'-kvcr' or state.get('feature')!='kvcr':
                raise ValueError('Retry namespace/feature identity mismatch')
            if state['checks'].get('r610-feature',{}).get('status')!='passed':
                raise ValueError('KVCR retry must have a fresh completed pass')
        for key in ('model','revision','runtime_image','tensor_parallel_size','gpu_allocation'):
            if state['model_lock'][key]!=expected[key]:raise ValueError('Input drift: '+feature+'/'+key)
        status=state['checks'].get('r610-feature',{}).get('status')
        if status not in ('passed','blocked'):raise ValueError('Incomplete feature: '+feature)
        if state['checks'].get('super-vl-idle',{}).get('status')!='passed':raise ValueError('Cleanup incomplete: '+feature)
        if status=='passed' and any(state['checks'].get(k,{}).get('status')!='passed' for k in required[feature]):
            raise ValueError('Missing underlying feature proof: '+feature)
        results[feature]={'status':status,'namespace':state['namespace'],'state':str(path.relative_to(ROOT)),
            'checks':{k:v for k,v in state['checks'].items() if k in required[feature] or k.startswith('shadow-') or k in ('sidecar-startup-grace','post-shadow-cuda','super-vl-'+feature,'r610-feature')},
            'state_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        if prior:results[feature]['prior_attempt']=prior
    summary={'driver':'610.57.04','model':expected['model'],'revision':expected['revision'],
        'runtime_image':expected['runtime_image'],'tensor_parallel_size':2,'features':results,
        'scope':'Bounded functionality; not capacity/performance; blocked preferred-model Shadow is not a pass',
        'validation':'Per-feature input locks, underlying receipts, wrapper outcome and idle cleanup receipts; final inventory/health separate'}
    control_path=root/'shadow-control/state.json'
    if control_path.exists():
        control=json.loads(control_path.read_text())
        if control['model_lock']['runtime_image']!=expected['runtime_image'] or control['model_lock']['model']!='Qwen/Qwen3-0.6B' or control['model_lock']['tensor_parallel_size']!=1:
            raise ValueError('Shadow control identity mismatch')
        for key in ('r610-shadow-control','shadow-failover','shadow-final-cleanup'):
            if control['checks'].get(key,{}).get('status')!='passed':raise ValueError('Incomplete Shadow control: '+key)
        summary['shadow_control']={'state':str(control_path.relative_to(ROOT)),
            'state_sha256':hashlib.sha256(control_path.read_bytes()).hexdigest(),
            'model':control['model_lock']['model'],'tensor_parallel_size':1,
            'checks':{k:control['checks'][k] for k in ('shadow-failover','shadow-final-cleanup','r610-shadow-control')},
            'scope':'Separate small-model control; does not qualify preferred-model or TP2 recovery'}
    (root/'feature-qualification-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    prior_summary=root/'summary-before-final-validation.json'
    if (root/'summary.json').exists() and not prior_summary.exists():
        prior_summary.write_bytes((root/'summary.json').read_bytes())
    (root/'summary.json').write_text(json.dumps([
        {'feature':feature,'status':result['status'],'namespace':result['namespace'],
         'run':str(Path(result['state']).parent)} for feature,result in results.items()],indent=2)+'\n')
    print(json.dumps({k:v['status'] for k,v in results.items()},indent=2),flush=True)


def progress(root,brief=False):
    observer=Run(root/'observer')
    states={}
    for feature in FEATURES:
        path=root/feature/'state.json'
        if path.exists():
            s=json.loads(path.read_text())
            states[s['namespace']]={'feature':feature,'checks':{k:v['status'] for k,v in s.get('checks',{}).items()}}
    pods=observer.get('get','pods','-A')['items']
    for pod in pods:
        ns=pod['metadata']['namespace']
        if ns not in states:continue
        statuses=pod['status'].get('containerStatuses',[])+pod['status'].get('initContainerStatuses',[])
        states[ns].setdefault('pods',[]).append({'name':pod['metadata']['name'],'node':pod['spec'].get('nodeName'),
            'phase':pod['status'].get('phase'),'containers':[{k:c.get(k) for k in ('name','ready','restartCount','state')} for c in statuses]})
        for c in statuses:
            result=observer.k('logs',pod['metadata']['name'],'-n',ns,'-c',c['name'],'--tail=100',check=False)
            (root/ states[ns]['feature']/('progress-'+pod['metadata']['name']+'-'+c['name']+'.log')).write_text(result.stdout+result.stderr)
    if brief:
        for ns,state in states.items():
            statuses=state['checks']
            pods=state.get('pods',[])
            print(json.dumps({'feature':state['feature'],
                'result':statuses.get('r610-feature',statuses.get('super-vl-'+state['feature'],'starting')),
                'pods':len(pods),'ready_containers':sum(c.get('ready',False) for p in pods for c in p['containers']),
                'restarts':sum(c.get('restartCount',0) for p in pods for c in p['containers'])}),flush=True)
    else:
        print(json.dumps(states,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['matrix','progress','resume','one','io-progress','sidecar-help','extend-sidecar-grace','handoff-sidecar','handoff-transfers','summarize','shadow-control'])
    parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--feature',choices=FEATURES)
    parser.add_argument('--kvcr-retry',type=Path,help='Fresh passing retry; preserves original discovery failure')
    parser.add_argument('--brief',action='store_true')
    args=parser.parse_args()
    if args.action=='progress':
        progress(args.run.resolve(),brief=args.brief)
    elif args.action=='resume':
        matrix(args.run.resolve(),resume=True)
    elif args.action=='one':
        if not args.feature:parser.error('one requires --feature')
        one(args.run.resolve(),args.feature)
    elif args.action=='summarize':
        summarize(args.run.resolve(),args.kvcr_retry.resolve() if args.kvcr_retry else None)
    else:
        globals()[args.action.replace('-', '_')](args.run.resolve())
