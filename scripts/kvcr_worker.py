"""Launch the preferred model with the matched KVCR secondary-tier adapter."""
import json
import os
from pathlib import Path
import subprocess
lock=json.loads(Path('/kvcr/model-lock.json').read_text())
transfer={'kv_connector':'OffloadingConnector','kv_role':'kv_both','kv_connector_extra_config':{
 'spec_name':'TieringOffloadingSpec','cpu_bytes_to_use':4*1024**3,'self_describing_kv_events':True,
 'secondary_tiers':[{'type':'kvcr','router_capabilities':['router_hint'],'control_host':'0.0.0.0',
  'control_ports':[17771],'control_advertise_host':os.environ['POD_IP'],'operation_timeout_ms':5000,
  'abandon_timeout_ms':10000,'enable_telemetry':True,'local_dram_backend':'LIBFABRIC','remote_fw_dram_backend':'LIBFABRIC'}]}}
args=['python3','-m','dynamo.vllm','--model',lock['model'],'--revision',lock['revision'],
 '--served-model-name',lock['model'],'--trust-remote-code','--tensor-parallel-size',str(lock.get('tensor_parallel_size',1)),
 '--max-model-len','4096','--max-num-seqs','8','--max-num-batched-tokens','8192','--gpu-memory-utilization','0.65',
 '--enable-prefix-caching','--block-size','64','--enforce-eager',
 '--mamba-backend','flashinfer','--mamba-ssm-cache-dtype','float16','--mamba-cache-mode','align',
 '--reasoning-parser','nemotron_v3','--disaggregation-mode','agg',
 '--kv-events-config',json.dumps({'publisher':'zmq','topic':'kv-events','endpoint':'tcp://*:20080','enable_kv_cache_events':True}),
 '--kv-transfer-config',json.dumps(transfer)]
if lock.get('tensor_parallel_size',1)>1:
    for flag,value in [('--max-model-len','8192'),('--max-num-seqs','4'),('--gpu-memory-utilization','0.85')]:
        args[args.index(flag)+1]=value
    args+=['--limit-mm-per-prompt','{"image":1,"video":0}']
print(json.dumps({'kvcr_worker_args':args,'model_revision':lock['revision']}),flush=True)
os.execvp(args[0],args)
