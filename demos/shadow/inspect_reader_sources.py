"""Read installed reader contracts in a CPU-only probe of the pinned writer image."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from snapshot_tp2_workflow import cpu_probe
from demos.shadow.writer import load

PROGRAM = r'''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
files=set()
for pattern in ('humming/**/*.py',
 'vllm/model_executor/kernels/linear/scaled_mm/**/*.py',
 'vllm/model_executor/kernels/linear/fp8*.py',
 'vllm/model_executor/kernels/linear/scaled_mm.py',
 'vllm/model_executor/layers/quantization/utils/humming/**/*.py',
 'vllm/utils/humming.py'):
 files.update(p for p in root.glob(pattern) if p.is_file())
assert files and sum(p.stat().st_size for p in files)<12000000
print(json.dumps({'files':{str(p.relative_to(root)):p.read_text() for p in sorted(files)}}))
'''
EXTRA_PROGRAM = r'''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
names=('gpu_memory_service/client/torch/tensor.py',
       'gpu_memory_service/client/memory_manager.py',
       'vllm/model_executor/layers/fused_moe/oracle/nvfp4.py')
files={n:(root/n).read_text() for n in names if (root/n).is_file()}
assert len(files)==len(names), 'Requested installed reader contract source is absent'
print(json.dumps({'files':files}))
'''
ATTENTION_PROGRAM = r'''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
names=('vllm/model_executor/layers/quantization/kv_cache.py',
       'vllm/attention/layer.py','vllm/v1/attention/layer.py',
       'vllm/model_executor/layers/attention.py',
       'vllm/model_executor/model_loader/utils.py',
       'vllm/model_executor/layers/fused_moe/config.py')
files={n:(root/n).read_text() for n in names if (root/n).is_file()}
files.update({str(p.relative_to(root)):p.read_text() for p in root.glob('vllm/model_executor/layers/attention/**/*.py') if p.is_file()})
assert names[0] in files and names[-1] in files and any('attention' in n for n in files), sorted(files)
print(json.dumps({'files':files}))
'''
MODEL_PROGRAM = r'''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
names=('vllm/v1/attention/backends/flashinfer.py','vllm/v1/attention/backend.py')
files={n:(root/n).read_text() for n in names if (root/n).is_file()}
files.update({str(p.relative_to(root)):p.read_text() for p in root.glob('vllm/model_executor/models/nemotron*.py') if p.is_file()})
assert all(n in files for n in names) and len(files)>2, sorted(files)
print(json.dumps({'files':files}))
'''

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', default='a1')
    kinds = parser.add_mutually_exclusive_group()
    kinds.add_argument('--extra', action='store_true')
    kinds.add_argument('--attention', action='store_true')
    kinds.add_argument('--model', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'a[1-9][0-9]*', args.attempt):
        raise ValueError('Use an explicit new attempt label.')
    run, _ = load(args.run)
    output = run.path / ('reader-runtime-model-sources' if args.model else
                         'reader-runtime-attention-sources' if args.attention else
                         'reader-runtime-extra-sources' if args.extra else 'reader-runtime-sources')
    if args.attempt != 'a1':
        output = output.with_name(output.name + '-' + args.attempt)
    if output.exists():
        raise ValueError('Use a fresh source inspection; never overwrite evidence.')
    label = 'reader-model-source-read' if args.model else 'reader-attention-source-read' if args.attention else (
        'reader-extra-contract-source-read' if args.extra else 'reader-contract-source-read')
    if args.attempt != 'a1':
        label += '-' + args.attempt
    report = cpu_probe(run, label, MODEL_PROGRAM if args.model else ATTENTION_PROGRAM if args.attention else EXTRA_PROGRAM if args.extra else PROGRAM)
    output.mkdir()
    manifest = {'image_id': report['image_id'], 'scope': 'CPU file reads only; no reader reconstruction or GPU qualification.', 'files': {}}
    for name, content in report['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.suffix != '.py':
            raise ValueError('Unexpected installed source path.')
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x') as stream:
            stream.write(content)
        target.chmod(0o400)
        manifest['files'][name] = hashlib.sha256(content.encode()).hexdigest()
    with (output / 'manifest.json').open('x') as stream:
        stream.write(json.dumps(manifest, indent=2) + '\n')
    print('Preserved', len(manifest['files']), 'installed source files at', output)
