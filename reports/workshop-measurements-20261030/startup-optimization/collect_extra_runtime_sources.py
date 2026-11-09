"""Read the remaining static files using the already-reviewed read-only collector."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess

BASE = Path(__file__).with_name('collect_runtime_sources.py')
ns = runpy.run_path(str(BASE))
OUT = ns['ROOT'] / 'results/workshop-startup-optimization-20261103-extra'
CLIENT_PROGRAM = r'''
import hashlib,importlib.metadata as m,json
from pathlib import Path
v=m.distribution('vllm');root=Path(v.locate_file('vllm'))
assert v.version=='0.31.1rc1.dev23+g43b4aaea3',v.version
wanted=['v1/worker/gpu/model_runner.py','utils/torch_utils.py','config/vllm.py']
files={}
for rel in wanted:
 p=root/rel;assert p.is_file(),str(p)
 files['vllm/'+rel]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':p.read_text()}
print(json.dumps({'vllm_version':v.version,'scope':'Static Python files only; no engine imports or GPU actions','files':files}))
'''
REMOTE_PROGRAM = ns['REMOTE_PROGRAM'].replace(repr(ns['CLIENT_PROGRAM']), repr(CLIENT_PROGRAM))


def main():
    OUT.mkdir(exist_ok=False)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15',
          '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','ForwardAgent=no',
          'ubuntu@3.238.63.5','python3','-c',shlex.quote(REMOTE_PROGRAM)]
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    r=subprocess.run(argv,capture_output=True,text=True,timeout=180)
    (OUT/'stderr.txt').write_text(r.stderr)
    (OUT/'receipt.json').write_text(json.dumps({'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':r.returncode,'collector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'base_collector_sha256':hashlib.sha256(BASE.read_bytes()).hexdigest(),'scope':'Read-only static source retrieval from existing CPU client'},indent=2)+'\n')
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    value=json.loads(r.stdout)
    (OUT/'runtime-sources.json').write_text(json.dumps(value,indent=2)+'\n')
    for name,record in value['files'].items():
        p=Path(name)
        assert not p.is_absolute() and '..' not in p.parts
        raw=record['text'].encode();assert hashlib.sha256(raw).hexdigest()==record['sha256']
        target=OUT/'sources'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    print(json.dumps({'directory':str(OUT),'files':len(value['files']),'vllm_version':value['vllm_version'],'client_uid':value['client_uid']}))


if __name__=='__main__':main()
