"""Read selected installed source/cache metadata; never import engine or GPU libs."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-mamba-startup-sources-20261103-a1'
CLIENT=r'''
import hashlib,importlib.metadata as m,json,os
from pathlib import Path
dist=m.distribution('vllm');assert dist.version=='0.31.1rc1.dev23+g43b4aaea3'
root=Path(dist.locate_file('vllm'));site=root.parent
wanted=['vllm/model_executor/layers/mamba/mamba_mixer2.py']
wanted+=['vllm/model_executor/layers/mamba/ops/'+n+'.py' for n in ['ssd_combined','ssd_chunk_state','ssd_chunk_scan','ssd_state_passing','ssd_bmm']]
wanted+=['triton/runtime/jit.py','triton/runtime/cache.py','triton/compiler/compiler.py']
files={};missing=[]
for rel in wanted:
 p=site/rel
 if p.is_file():files[rel]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':p.read_text()}
 else:missing.append(rel)
versions={}
for name in ['triton','pytorch-triton','flashinfer-python','nvidia-cuda-runtime-cu13']:
 try:versions[name]=m.version(name)
 except m.PackageNotFoundError:pass
inventory={}
for p in [Path(os.environ.get('TRITON_CACHE_DIR','/tmp/workshop-triton-cache')),Path.home()/'.nv/ComputeCache']:
 stats={};count=0;size=0
 if p.exists():
  for f in p.rglob('*'):
   if f.is_file():count+=1;size+=f.stat().st_size;stats[f.suffix]=stats.get(f.suffix,0)+1
 inventory[str(p)]={'exists':p.exists(),'file_count':count,'bytes':size,'extensions':stats}
print(json.dumps({'files':files,'missing':missing,'versions':versions,'cache_inventory':inventory,'scope':'Read-only Python source and file metadata; no Torch/vLLM/Triton/GPU import; source startup may still be populating caches'}))
'''
PROGRAM=r'''
import json,subprocess
ns='dynamo-ft-mxstartup-012e66a639';pod='ft-mx-0-source-wfrjq'
p=json.loads(subprocess.check_output(['kubectl','--request-timeout=15s','get','pod',pod,'-n',ns,'-o','json'],timeout=25))
assert p['status']['phase']=='Running'
assert p['spec']['containers'][0]['image'].endswith('@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d')
r=subprocess.run(['kubectl','--request-timeout=15s','exec',pod,'-n',ns,'-c','main','--','python3','-c',CLIENT_LITERAL],capture_output=True,text=True,timeout=60)
assert r.returncode==0,r.stderr[-1500:]
v=json.loads(r.stdout);v['pod_uid']=p['metadata']['uid'];v['image']=p['spec']['containers'][0]['image'];print(json.dumps(v))
'''.replace('CLIENT_LITERAL',repr(CLIENT))


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(PROGRAM)]
    r=subprocess.run(argv,capture_output=True,text=True,timeout=90)
    (OUT/'stderr.txt').write_text(r.stderr)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    v=json.loads(r.stdout);(OUT/'sources.json').write_text(json.dumps(v,indent=2)+'\n')
    for rel,record in v['files'].items():
        p=Path(rel);assert not p.is_absolute() and '..' not in p.parts
        dest=OUT/'sources'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(record['text'])
        assert hashlib.sha256(dest.read_bytes()).hexdigest()==record['sha256']
    print(json.dumps({k:value for k,value in v.items() if k!='files'},indent=2))


if __name__=='__main__':main()
