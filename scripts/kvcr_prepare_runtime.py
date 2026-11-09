"""Install the public KVCR compatibility set only inside an owned disposable pod."""
import hashlib
import importlib.util
import importlib.metadata as md
import inspect
import json
import os
from pathlib import Path
import subprocess
import urllib.request

lock=json.loads(Path('/kvcr/kvcr-lock.json').read_text())
cache=Path('/model-cache/feature-tests')/os.environ['TEST_RUN']/'kvcr-wheels'
wheels=sorted(cache.glob('*.whl'))
assert any(p.name.startswith('ai_dynamo_runtime-') for p in wheels), 'Build pinned Dynamo bindings first'
assert any(p.name.startswith('ai_dynamo-') for p in wheels), 'Build pinned Dynamo components first'
subprocess.run(['python3','-m','pip','install','--no-cache-dir','--no-deps',*[str(p) for p in wheels]],check=True)
subprocess.run(['python3','-m','pip','install','--no-cache-dir',
    f'https://github.com/ai-dynamo/kvcr/archive/{lock["kvcr_revision"]}.tar.gz'],check=True)
# The validated NCCL override intentionally differs from torch's declared pin.
# Install it separately without dependency resolution to preserve the base ABI.
subprocess.run(['python3','-m','pip','install','--no-cache-dir','--no-deps','nvidia-nccl-cu13==2.30.7'],check=True)
root=Path(importlib.util.find_spec('vllm').origin).parent.parent
paths=[
 'vllm/distributed/kv_events.py','vllm/distributed/kv_transfer/kv_connector/v1/offloading/events.py',
 'vllm/v1/kv_offload/base.py','vllm/v1/kv_offload/tiering/factory.py',
 'vllm/v1/kv_offload/tiering/kvcr/__init__.py','vllm/v1/kv_offload/tiering/kvcr/manager.py']
sources=[]
for path in paths:
 url=f'https://raw.githubusercontent.com/vllm-project/vllm/{lock["vllm_adapter_revision"]}/{path}'
 with urllib.request.urlopen(url,timeout=60) as response:content=response.read()
 target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
 sources.append({'path':path,'sha256':hashlib.sha256(content).hexdigest()})
import dynamo.vllm
import kvcr
from dynamo.common.constants import KV_HINT_TRANSFER_CAPABILITY_KEY
from vllm.v1.kv_offload.tiering.kvcr import manager
from vllm.v1.kv_offload.tiering.factory import SecondaryTierFactory
from vllm.v1.kv_offload.tiering.base import TransferJob
from vllm.v1.kv_offload.base import OffloadPolicy
assert md.version('nixl')=='1.5.0'
assert md.version('nvidia-nccl-cu13')=='2.30.7'
assert 'abandon_timeout_ms' in inspect.signature(manager.KVCRSecondaryTierManager.__init__).parameters
assert 'chunk_ids' in TransferJob.__dataclass_fields__
assert OffloadPolicy.CHUNK_LEVEL.value=='chunk_level'
assert KV_HINT_TRANSFER_CAPABILITY_KEY=='router_hint'
assert SecondaryTierFactory.get_tier_class({'type':'kvcr'}) is manager.KVCRSecondaryTierManager
print(json.dumps({'kvcr_compatibility':'passed','packages':{p:md.version(p) for p in ('ai-dynamo','ai-dynamo-runtime','vllm','kvcr','nixl','nvidia-nccl-cu13')},
 'wheels':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in wheels], 'adapter_sources':sources}),flush=True)
