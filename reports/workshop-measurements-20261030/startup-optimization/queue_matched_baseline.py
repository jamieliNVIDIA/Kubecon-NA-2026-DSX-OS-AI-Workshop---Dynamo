"""Run the frozen matched baseline after the qualified health pair is cleaned.

No predecessor signals, deletes or lease changes. Docker identity/terminal
state is checked by the parent launcher; this CPU container checks immutable
receipts and live Kubernetes cleanup again before any prepare action.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'results/workshop-mx-startup-20261104-baseline01'
PRIOR = ROOT / 'results/workshop-mx-startup-20261103-textonly-health01'
PRIOR_CONTROLLER = ROOT / 'results/workshop-health-controller-20261103-a1'
PRIOR_ID = '03712d3c27495bab8e66d871666370dcfca8395fa1dca306bae47123d40de958'
LEASE = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
PYTHON = ROOT / '.local/venv/bin/python'
KUBECTL = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig='+str(ROOT / '.local/kubeconfig'), '--request-timeout=30s']


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, value):
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,indent=2)+'\n')
    tmp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--plan-sha256',required=True)
    args=parser.parse_args()
    os.umask(0o077)
    assert sha(args.plan)==args.plan_sha256,'Frozen matched baseline plan changed'
    plan=json.loads(args.plan.read_text())
    assert plan['run_directory']==str(RUN.relative_to(ROOT))
    assert plan['predecessor_id']==PRIOR_ID
    path=ROOT/plan['controller_directory']
    path.mkdir(exist_ok=False)
    atomic(path/'consumed-plan.json',{'plan':plan,'plan_sha256':sha(args.plan),'at':now()})
    started=now();child=None

    def state(stage,**details):
        atomic(path/'STATUS.json',{'at':now(),'stage':stage,**details})

    def unchanged():
        for name,expected in plan['source_sha256'].items():
            assert sha(ROOT/name)==expected,'Frozen baseline input changed: '+name

    def get(*parts):
        result=subprocess.run(KUBECTL+list(parts)+['-o','json'],capture_output=True,text=True,timeout=45)
        if result.returncode:raise RuntimeError('Read-only gate failed: '+result.stderr[-1500:])
        return json.loads(result.stdout)

    def gpu_pods(pods):
        return [p['metadata']['namespace']+'/'+p['metadata']['name'] for p in pods if any(
            c.get('resources',{}).get('claims') or any(k.startswith('nvidia.com/') and 'gpu' in k
            for k in c.get('resources',{}).get('limits',{})) for c in p['spec'].get('containers',[]))]

    def prior_success():
        handoff=json.loads((ROOT/plan['predecessor_handoff_path']).read_text())
        assert handoff['predecessor_id']==PRIOR_ID and handoff['accepted_terminal_exit_code']==0
        for name,expected in handoff['required_existing_sha256'].items():
            assert sha(ROOT/name)==expected,'Prior terminal evidence changed: '+name
        exit_path=PRIOR_CONTROLLER/'exit.json'
        deadline=time.monotonic()+plan['predecessor_wait_timeout_seconds']
        while not exit_path.exists():
            if time.monotonic()>=deadline:raise TimeoutError('Prior controller did not finish')
            state('waiting for prior health trial terminal success; no preparation')
            time.sleep(10)
        exited=json.loads(exit_path.read_text())
        assert exited['exit_code']==0,'Prior health trial did not exit successfully'
        qualification=json.loads((PRIOR/'qualification.json').read_text())
        cleanup=json.loads((PRIOR/'cleanup-proof.json').read_text())
        prior_state=json.loads((PRIOR/'state.json').read_text())
        assert qualification['passed'] and prior_state['checks']['text-only-health-pair']['status']=='passed'
        assert cleanup['verified'] and cleanup['gpu_lease_absent']
        for key in ['gpu_pods','resourceclaims','graphs','coordinator_pods']:assert not cleanup[key]
        assert prior_state['namespace']==handoff['prior_namespace']
        assert not LEASE.exists(),'Prior GPU lease remains present'
        ns=handoff['prior_namespace']
        namespace=get('get','namespace',ns)
        assert namespace['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
        pods=get('get','pods','-n',ns)['items']
        claims=get('get','resourceclaims','-n',ns)['items']
        graphs=get('get','dgd','-n',ns)['items']
        assert not gpu_pods(pods) and not claims and not graphs,'Prior live cleanup no longer holds'
        assert not any(p['metadata']['name'] in ['mx-coordinator','mx-redis'] for p in pods)
        all_pods=get('get','pods','-A')['items']
        unexpected=gpu_pods([p for p in all_pods if p['spec'].get('nodeName') in
            ['kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198']])
        assert not unexpected,'Benchmark nodes have other GPU Pods: '+repr(unexpected)
        nodes=get('get','nodes')['items']
        for name in ['kubecon-nke-site-cp-0124','kubecon-nke-site-cp-0198']:
            node=next(n for n in nodes if n['metadata']['name']==name)
            assert any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions'])
        atomic(path/'predecessor-cleanup-verified.json',{'at':now(),'prior_exit':exited,
            'qualification_passed':True,'prior_namespace':ns,'live_gpu_pods':[],
            'live_claims':[],'live_graphs':[],'benchmark_node_gpu_pods':[],'lease_absent':True})

    def command(stage):
        nonlocal child
        unchanged()
        directory=path/stage['name'];directory.mkdir(exist_ok=False)
        argv=[str(PYTHON),'-B']+[str(x) for x in stage['argv']]
        began=now()
        atomic(directory/'command.json',{'argv':argv,'started_at':began,'timeout_seconds':stage['timeout_seconds']})
        with (directory/'console.log').open('w') as stream:
            child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stream,
                                   stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+stage['timeout_seconds']
            while child.poll() is None:
                state(stage['name'],child_pid=child.pid,started_at=began)
                if time.monotonic()>=deadline:
                    os.killpg(child.pid,signal.SIGINT)
                    try:child.wait(timeout=180)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    atomic(directory/'exit.json',{'exit_code':124,'started_at':began,'finished_at':now()})
                    raise TimeoutError(stage['name'])
                time.sleep(10)
            code=child.returncode;child=None
        atomic(directory/'exit.json',{'exit_code':code,'started_at':began,'finished_at':now()})
        if code:raise RuntimeError(stage['name']+' failed: exit '+str(code))

    def interrupted(signum,frame):
        raise KeyboardInterrupt('Matched baseline controller received signal '+str(signum))

    signal.signal(signal.SIGTERM,interrupted)
    try:
        unchanged();prior_success();unchanged()
        for stage in plan['stages']:command(stage)
        assert not LEASE.exists()
        assert json.loads((RUN/'qualification.json').read_text())['passed'] is True
        state('matched baseline completed; evidence sealed')
        atomic(path/'exit.json',{'exit_code':0,'started_at':started,'finished_at':now()})
    except BaseException as error:
        if child is not None and child.poll() is None:
            os.killpg(child.pid,signal.SIGINT)
            try:child.wait(timeout=180)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        state('stopped; inspect failure before continuing',error=repr(error),traceback=traceback.format_exc())
        atomic(path/'exit.json',{'exit_code':1,'started_at':started,'finished_at':now(),
            'error':repr(error),'gpu_lease_present':LEASE.exists()})
        raise


if __name__=='__main__':main()
