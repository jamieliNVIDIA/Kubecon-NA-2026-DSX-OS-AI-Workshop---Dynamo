"""Inspect optional feature entrypoints inside an owned serving container."""
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import subprocess

report = {'packages': {}, 'modules': {}, 'commands': {}}
for package in ('ai-dynamo', 'ai-dynamo-runtime', 'vllm', 'nixl', 'modelexpress', 'kvcr'):
    try:
        report['packages'][package] = metadata.version(package)
    except metadata.PackageNotFoundError:
        report['packages'][package] = None
for name in ('dynamo.vllm.sidecar', 'dynamo.sglang.sidecar',
             'vllm.v1.kv_offload.tiering.kvcr.manager',
             'modelexpress.k8s_service_client', 'modelexpress.vllm_loader'):
    try:
        spec = importlib.util.find_spec(name)
        report['modules'][name] = spec.origin if spec else None
    except Exception as exc:
        report['modules'][name] = {'error': str(exc)}
for name in ('dynamo.vllm.sidecar', 'dynamo.sglang.sidecar'):
    if isinstance(report['modules'].get(name), str):
        try:
            result = subprocess.run(['python3', '-m', name, '--help'], text=True,
                                    capture_output=True, timeout=30)
            report['commands'][name] = {'exit_code': result.returncode,
                'stdout': result.stdout[-12000:], 'stderr': result.stderr[-3000:]}
        except Exception as exc:
            report['commands'][name] = {'error': str(exc)}
spec = importlib.util.find_spec('vllm')
if spec and spec.origin:
    binary = Path(spec.origin).parent / 'vllm-rs'
    report['vllm_native_grpc_binary'] = str(binary) if binary.exists() else None
print(json.dumps(report, indent=2))
