"""Read static sources from the pinned, existing CPU client; never import engines."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/workshop-startup-optimization-20261103'

CLIENT_PROGRAM = r'''
import hashlib,importlib.metadata as m,json
from pathlib import Path
v=m.distribution('vllm');root=Path(v.locate_file('vllm'))
assert v.version=='0.31.1rc1.dev23+g43b4aaea3',v.version
mxroot=root.parent/'modelexpress';assert mxroot.is_dir()
wanted=['engine/arg_utils.py','config/model.py','config/multimodal.py','config/kernel.py','config/compilation.py','config/parallel.py','envs.py','utils/system_utils.py','v1/executor/multiproc_executor.py','v1/worker/gpu_worker.py','v1/worker/gpu_model_runner.py','v1/worker/startup_plan.py','v1/engine/core.py','multimodal/profiling.py','compilation/monitor.py','model_executor/warmup/kernel_warmup.py']
paths={}
for rel in wanted:
 p=root/rel
 if p.is_file():paths['vllm/'+rel]=p
for p in root.rglob('encoder_runner.py'):paths['vllm/'+str(p.relative_to(root))]=p
for p in (root/'model_executor/models').glob('*nemotron*'):
 if p.is_file() and p.suffix=='.py':paths['vllm/'+str(p.relative_to(root))]=p
for p in mxroot.rglob('*.py'):paths['modelexpress/'+str(p.relative_to(mxroot))]=p
versions={d.metadata['Name']:d.version for d in m.distributions() if 'express' in (d.metadata['Name'] or '').lower()}
assert '0.6.0' in versions.values(),versions
print(json.dumps({'vllm_version':v.version,'mx_versions':versions,'scope':'Static installed Python files only; no vLLM/torch/MX import or GPU action','files':{name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':p.read_text()} for name,p in sorted(paths.items())}}))
'''

REMOTE_PROGRAM = """
import json,subprocess
client_program=CLIENT_PROGRAM_LITERAL
namespace='dynamo-ft-r610-1ec4908b-rr'
pod=json.loads(subprocess.check_output(['kubectl','--request-timeout=15s','get','pod','rr-loadgen','-n',namespace,'-o','json']))
assert pod['metadata']['uid']=='b2e69037-fe15-4cf1-a00a-fff65d545588'
assert pod['status']['phase']=='Running'
assert all(c.get('restartCount',0)==0 for c in pod['status']['containerStatuses'])
assert pod['spec']['containers'][0]['image'].endswith('@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d')
r=subprocess.run(['kubectl','--request-timeout=15s','exec','-i','rr-loadgen','-n',namespace,'--','python3','-c',client_program],capture_output=True,text=True,timeout=120)
assert r.returncode==0,r.stderr[-2000:]
v=json.loads(r.stdout);v['client_uid']=pod['metadata']['uid'];v['image']=pod['spec']['containers'][0]['image']
print(json.dumps(v))
""".replace('CLIENT_PROGRAM_LITERAL', repr(CLIENT_PROGRAM))


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
          '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','ForwardAgent=no',
          'ubuntu@3.238.63.5','python3','-c',shlex.quote(REMOTE_PROGRAM)]
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    r=subprocess.run(argv,capture_output=True,text=True,timeout=180)
    (OUT/'stderr.txt').write_text(r.stderr)
    (OUT/'receipt.json').write_text(json.dumps({'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':r.returncode,'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Read-only static source retrieval from existing CPU client'},indent=2)+'\n')
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    value=json.loads(r.stdout)
    (OUT/'runtime-sources.json').write_text(json.dumps(value,indent=2)+'\n')
    for name,record in value['files'].items():
        p=Path(name)
        assert not p.is_absolute() and '..' not in p.parts
        raw=record['text'].encode();assert hashlib.sha256(raw).hexdigest()==record['sha256']
        target=OUT/'sources'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    print(json.dumps({'directory':str(OUT),'files':len(value['files']),'vllm_version':value['vllm_version'],'mx_versions':value['mx_versions'],'client_uid':value['client_uid']}))


if __name__=='__main__':main()
