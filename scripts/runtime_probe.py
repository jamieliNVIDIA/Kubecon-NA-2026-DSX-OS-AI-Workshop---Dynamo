"""Executed inside a disposable GPU/EFA test pod; does not change host software."""
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def execute(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return {'command': args, 'exit_code': result.returncode,
                'stdout': result.stdout[-12000:], 'stderr': result.stderr[-3000:]}
    except Exception as exc:
        return {'command': args, 'error': str(exc)}


report = {'versions': {}, 'devices': {}, 'commands': []}
for name in ('ai-dynamo', 'ai-dynamo-runtime', 'vllm', 'nixl', 'torch', 'modelexpress', 'kvcr'):
    try:
        report['versions'][name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        report['versions'][name] = None
report['devices']['infiniband'] = [str(p) for p in Path('/dev/infiniband').glob('*')]
report['devices']['gdrdrv'] = Path('/dev/gdrdrv').exists()
for args in (
    ['nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used', '--format=csv,noheader'],
    ['bash', '-lc', 'command -v fi_info; command -v dynamo-vllm-sidecar; command -v dynamo-sglang-sidecar; command -v cuda-checkpoint; command -v criu'],
    ['bash', '-lc', 'if command -v fi_info >/dev/null; then fi_info -p efa -t FI_EP_RDM; elif test -x /opt/amazon/efa/bin/fi_info; then /opt/amazon/efa/bin/fi_info -p efa -t FI_EP_RDM; else exit 127; fi'],
):
    report['commands'].append(execute(args))
try:
    import torch
    report['torch_cuda'] = torch.version.cuda
    report['cuda_available'] = torch.cuda.is_available()
    x = torch.arange(1024, device='cuda', dtype=torch.float32)
    report['gpu_arithmetic_ok'] = x.sum().item() == 523776
except Exception as exc:
    report['cuda_error'] = str(exc)
try:
    from nixl._api import nixl_agent
    agent = nixl_agent('feature-test-probe')
    report['nixl_plugins'] = agent.get_plugin_list()
    report['nixl_api_path'] = __import__('nixl._api', fromlist=['_api']).__file__
    report['nixl_api_methods'] = [name for name in dir(agent) if not name.startswith('_')]
except Exception as exc:
    report['nixl_error'] = str(exc)
print(json.dumps(report, indent=2, default=str))
