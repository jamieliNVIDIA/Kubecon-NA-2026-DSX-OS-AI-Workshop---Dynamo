#!/usr/bin/env python3
"""Read installed sources and GMS diagnostic RPCs; never create a CUDA context."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PROGRAM = '''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
names=['gpu_memory_service/integrations/vllm/model_loader.py',
'gpu_memory_service/integrations/common/utils.py','gpu_memory_service/client/torch/allocator.py',
'vllm/model_executor/kernels/linear/nvfp4/humming.py',
'vllm/model_executor/layers/quantization/utils/humming/linear.py',
'vllm/model_executor/layers/quantization/utils/humming/moe.py',
'vllm/model_executor/layers/quantization/utils/humming/utils.py',
'vllm/model_executor/layers/quantization/modelopt.py',
'vllm/model_executor/layers/fused_moe/fused_humming_moe.py',
'humming/forward.py','humming/ops/gemm.py','humming/ops/launcher.py']
print(json.dumps({'files':{n:(root/n).read_text() if (root/n).is_file() else None for n in names},
'packages':{p:m.version(p) for p in ['vllm','ai-dynamo','ai-dynamo-runtime','gpu-memory-service']}}))
'''


def collect(run_path, output):
    run_path, output = Path(run_path).resolve(), Path(output).resolve()
    state = json.loads((run_path / 'state.json').read_text())
    demo = json.loads((run_path / 'demo.json').read_text())
    ns = state['namespace']
    if state['owner'] != 'kubecon-dynamo-feature-tests' or demo.get('demo_kind') != 'shadow' or demo['namespace'] != ns:
        raise ValueError('Require owned existing Shadow run.')
    output.mkdir(parents=True, exist_ok=False)
    base = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'), '--request-timeout=25s']
    receipts = {}

    def record(name, args):
        result = subprocess.run(base + args, capture_output=True, text=True, timeout=75)
        (output / name).write_text(result.stdout)
        (output / (name + '.stderr')).write_text(result.stderr)
        receipts[name] = {'args': args, 'exit_code': result.returncode,
                          'sha256': hashlib.sha256(result.stdout.encode()).hexdigest()}
        if result.returncode:
            raise RuntimeError(name + ' failed; preserve this diagnostic attempt.')
        return json.loads(result.stdout)

    try:
        inventory = record('pods.json', ['get', 'pods', '-n', ns, '-o', 'json'])
        pods = inventory['items']
        if any(p['metadata'].get('labels', {}).get('feature-test-run') != ns for p in pods):
            raise ValueError('Refuse to inspect foreign Pods.')
        workers = [p for p in pods if {c['name'] for c in p['spec']['containers']} >= {'engine-0', 'engine-1'}]
        frontends = [p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'frontend']
        if len(workers) != 1 or len(frontends) != 1:
            raise ValueError('Need one owned Shadow worker and frontend.')
        worker, frontend = workers[0], frontends[0]
        # Metadata/source reads only: SOURCE_PROGRAM does not import torch/GMS.
        sources = record('runtime-sources.json', ['exec', frontend['metadata']['name'], '-n', ns,
            '-c', 'main', '--', 'python3', '-c', SOURCE_PROGRAM])
        for name, source in sources['files'].items():
            if source is not None:
                target = output / 'sources' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
        # shadow_probe gms uses only GetRuntimeState/GetEventHistory RPCs and
        # does not acquire pool handles or import torch. Its engine/kill actions
        # are deliberately not exposed by this diagnostic helper.
        record('gms-state.json', ['exec', worker['metadata']['name'], '-n', ns, '-c', 'gms-server',
            '--', 'python3', '-c', (ROOT / 'scripts/shadow_probe.py').read_text(), 'gms'])
    finally:
        (output / 'manifest.json').write_text(json.dumps({'at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'read_only': True, 'no_cuda_context': True, 'run': str(run_path), 'namespace': ns,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'receipts': receipts}, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    collect(args.run, args.output)
