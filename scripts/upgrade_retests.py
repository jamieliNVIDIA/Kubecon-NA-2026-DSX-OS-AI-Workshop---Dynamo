#!/usr/bin/env python3
"""Fresh receipts for the authorized platform upgrade's existing feature tests."""
import argparse
import json
import time
from pathlib import Path
from feature_tests import BASE_IMAGE
from serving_tests import deploy, smoke
from storage_tests import prepare
from testlib import ROOT, Run


def cache(run, source):
    old = json.loads((source / 'state.json').read_text())
    if old['owner'] != run.state['owner'] or old['checks']['model-staging']['status'] != 'passed':
        raise ValueError('Requires a previously verified owned model cache')
    current_model=json.loads((ROOT / 'configs/model-lock.json').read_text())
    if any(old['model_lock'][key]!=current_model[key] for key in ('model','revision')):
        raise ValueError('Baseline model identity/revision differs')
    prepare(run)
    run.state['baseline_run'] = str(source.resolve())
    run.state['model_cache_run_id'] = old['run_id']
    run.state['kvcr_wheels_run_id'] = old['run_id']
    run.save()
    program = '''import hashlib,json,os
from pathlib import Path
root=Path('/efs/feature-tests')/os.environ['CACHE_RUN']
snapshot=root/'hf/hub/models--nvidia--NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4/snapshots/bee7596271d1495f6992ae224aefde4410e816b8'
index=json.loads((snapshot/'model.safetensors.index.json').read_text())
weights=sorted(set(index['weight_map'].values()))
assert len(weights)==52 and all((snapshot/name).is_file() for name in weights)
weight_bytes=sum((snapshot/name).stat().st_size for name in weights)
assert weight_bytes==21561882284
wheels=sorted((root/'kvcr-wheels').glob('*.whl'))
assert any(p.name.startswith('ai_dynamo_runtime-1.6.0') for p in wheels)
assert any(p.name.startswith('ai_dynamo-1.6.0') for p in wheels)
print(json.dumps({'source_run':os.environ['CACHE_RUN'],'snapshot_path':str(snapshot),'weight_files':len(weights),'weight_bytes':weight_bytes,
 'wheels':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in wheels]}))
'''
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'model-download-cache-check'},
           'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 120,
                    'automountServiceAccountToken': False,
                    'containers': [{'name': 'check', 'image': BASE_IMAGE, 'command': ['python3', '-c', program],
                                    'env': [{'name': 'CACHE_RUN', 'value': old['run_id']}],
                                    'resources': {'requests': {'cpu': '1', 'memory': '1Gi'},
                                                  'limits': {'memory': '2Gi'}},
                                    'volumeMounts': [{'name': 'cache', 'mountPath': '/efs', 'readOnly': True}]}],
                    'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': 'feature-cache'}}]}}
    run.apply([pod])
    try:
        run.wait_pod(pod['metadata']['name'], completed=True, timeout=180)
        report = json.loads(run.k('logs', pod['metadata']['name'], '-n', run.ns).stdout)
        run.result('upgrade-cache-reuse', 'passed', **report)
        run.result('model-staging', 'passed', model=old['model_lock']['model'], revision=old['model_lock']['revision'],
                   scope='Reverified preexisting exact model revision and weight sizes; no redownload', **report)
    finally:
        run.k('delete', 'pod', pod['metadata']['name'], '-n', run.ns, '--wait=false', '--ignore-not-found', check=False)


def platform(run):
    obj = run.get('get', 'deployment', 'dynamo-platform-dynamo-operator-controller-manager', '-n', 'dynamo-system')
    pods = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    summary = {'deployment': obj.get('status'), 'images': [c['image'] for c in
               obj['spec']['template']['spec'].get('initContainers', []) + obj['spec']['template']['spec']['containers']],
               'pods': [{'name': p['metadata']['name'], 'phase': p.get('status', {}).get('phase'),
                         'init': p.get('status', {}).get('initContainerStatuses'),
                         'containers': p.get('status', {}).get('containerStatuses')} for p in pods]}
    print(json.dumps(summary, indent=2), flush=True)
    (run.path / 'platform-status.json').write_text(json.dumps(summary, indent=2))
    for pod in pods:
        if 'dynamo-operator' not in pod['metadata']['name']:
            continue
        for container in pod['spec'].get('initContainers', []) + pod['spec'].get('containers', []):
            logs = run.k('logs', pod['metadata']['name'], '-n', 'dynamo-system', '-c', container['name'], '--tail=150', check=False)
            (run.path / f'platform-{pod["metadata"]["name"]}-{container["name"]}.log').write_text(logs.stdout + logs.stderr)


def stop(run, graphs):
    required = {'ft-agg': 'kv-routing', 'ft-sidecar': 'engine-sidecar',
                'ft-disagg': 'disaggregation', 'ft-kvcr': 'kvcr',
                'ft-mx': 'modelexpress', 'ft-mx-target': 'modelexpress'}
    for name in graphs:
        if name not in required or run.state.get('checks', {}).get(required[name], {}).get('status') != 'passed':
            raise ValueError(f'{name}: stop requires its completed pass receipt')
        obj = run.get('get', 'dgd', name, '-n', run.ns)
        if obj['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Refusing to stop an unowned DGD')
        run.k('delete', 'dgd', name, '-n', run.ns, '--wait=false')
    run.result('completed-workloads-stopped', 'requested', graphs=graphs)


def diagnose(run, prefix):
    pods=run.get('get','pods','-n',run.ns)['items']
    stamp=__import__('time').time_ns()
    for pod in pods:
        name=pod['metadata']['name']
        if not name.startswith(prefix):continue
        (run.path/f'diagnose-{name}-{stamp}.json').write_text(json.dumps(pod,indent=2))
        for previous in (False,True):
            result=run.k('logs',name,'-n',run.ns,'-c','main','--tail=3000',
                         *(['--previous'] if previous else []),check=False)
            (run.path/f'diagnose-{name}-{stamp}-{"previous" if previous else "current"}.log').write_text(result.stdout+result.stderr)
        code='''import json,urllib.request,urllib.error
r={}
for path in ('/live','/health','/healthz','/ready'):
 try:
  with urllib.request.urlopen('http://127.0.0.1:9090'+path,timeout=5) as f:r[path]={'status':f.status,'body':f.read().decode()}
 except urllib.error.HTTPError as e:r[path]={'status':e.code,'body':e.read().decode()}
 except Exception as e:r[path]={'error':str(e)}
print(json.dumps(r))
'''
        result=run.k('exec','-i',name,'-n',run.ns,'-c','main','--','python3','-',input_text=code,check=False)
        (run.path/f'diagnose-{name}-{stamp}-health.json').write_text(result.stdout+result.stderr)
        print(name,result.stdout[-2500:],flush=True)


def canary_stability(run):
    if run.state.get('checks',{}).get('kvcr',{}).get('status')!='passed':
        raise ValueError('Complete KVCR peer-reuse verification before the idle health check')
    samples=[]
    for index in range(3):
        if index:time.sleep(15)
        pods=[p for p in run.get('get','pods','-n',run.ns)['items']
              if p['metadata']['name'].startswith('ft-kvcr-') and '-agg-' in p['metadata']['name']
              and not p['metadata'].get('deletionTimestamp')]
        assert len(pods)==2
        for pod in pods:
            main=pod['spec']['containers'][0]
            env={item['name']:item.get('value') for item in main.get('env',[])}
            assert env.get('DYN_HEALTH_CHECK_ENABLED')=='true'
            assert env.get('DYN_HEALTH_CHECK_REQUEST_TIMEOUT')=='180'
            assert all(c.get('ready') and c.get('restartCount')==0 for c in pod['status']['containerStatuses'])
            code='''import json,urllib.request
r={}
for path in ('/live','/health'):
 with urllib.request.urlopen('http://127.0.0.1:9090'+path,timeout=5) as f:
  assert f.status==200
  r[path]=json.load(f)
  assert r[path]['status']=='ready' and r[path]['endpoints']['generate']=='ready'
print(json.dumps(r))
'''
            result=run.k('exec','-i',pod['metadata']['name'],'-n',run.ns,'-c','main','--','python3','-',input_text=code)
            samples.append({'sample':index,'pod':pod['metadata']['name'],'health':json.loads(result.stdout),'restarts':0})
        print(f'KVCR idle health sample {index+1}/3: both workers Ready, zero restarts',flush=True)
    (run.path/'kvcr-idle-health.json').write_text(json.dumps(samples,indent=2)+'\n')
    run.result('kvcr-canary-stability','passed',canary_enabled=True,canary_timeout_seconds=180,
               samples_per_worker=3,idle_interval_seconds=15,evidence=['kvcr-idle-health.json'],
               scope='Both tuned KVCR workers remain Ready with zero restarts during a bounded idle health check')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'platform', 'agg', 'disagg', 'mx', 'sidecar', 'kvcr', 'grove', 'stop', 'diagnose', 'canary-stability'))
    parser.add_argument('--prefix', default='ft-kvcr-')
    parser.add_argument('--graphs', nargs='+', default=[])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'results/20261013t023201z-features')
    parser.add_argument('--runtime', choices=('baseline', '1.5.1'), default='baseline',
                        help='prepare an immutable per-run lock for the selected runtime')
    args = parser.parse_args()
    run = Run(args.run)
    print(f'Retest run: {run.path}', flush=True)
    if args.action == 'prepare':
        if args.runtime == '1.5.1':
            lock = json.loads((ROOT / 'configs/model-lock.json').read_text())
            candidate = json.loads((ROOT / 'configs/dynamo-1.5.1-runtime.json').read_text())[0]
            lock.update(runtime_image=candidate['image'], runtime_version_override='1.5.1',
                        runtime_release='1.5.1')
            destination = run.path / 'model-lock.json'
            content = json.dumps(lock, indent=2) + '\n'
            if destination.exists() and destination.read_text() != content:
                raise ValueError('Candidate lock changed; create a new run')
            destination.write_text(content)
        cache(run, args.baseline)
    elif args.action == 'platform':
        platform(run)
    elif args.action == 'stop':
        if not args.graphs:
            raise ValueError('Specify the completed graphs to stop')
        stop(run,args.graphs)
    elif args.action == 'diagnose':
        if not args.prefix.startswith('ft-'):
            raise ValueError('Diagnostics must target owned test workloads')
        diagnose(run,args.prefix)
    elif args.action == 'canary-stability':
        canary_stability(run)
    elif args.action == 'agg':
        from request_tests import routing
        deploy(run, 'agg'); smoke(run, 'agg'); routing(run)
    elif args.action == 'disagg':
        from request_tests import disagg
        deploy(run, 'disagg'); smoke(run, 'disagg'); disagg(run)
    elif args.action == 'mx':
        from modelexpress_tests import deploy as mx_deploy, verify
        mx_deploy(run); mx_deploy(run, target=True); verify(run)
    elif args.action == 'sidecar':
        from sidecar_tests import deploy as sidecar_deploy, verify
        sidecar_deploy(run); smoke(run, 'sidecar'); verify(run)
    elif args.action == 'kvcr':
        from kvcr_tests import deploy as kvcr_deploy, verify
        kvcr_deploy(run); smoke(run, 'kvcr'); verify(run)
    else:
        from grove_tests import test
        test(run)


if __name__ == '__main__':
    main()
