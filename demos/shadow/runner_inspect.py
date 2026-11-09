"""Additional actual-image CPU read; does not alter the frozen a4 controller."""
import hashlib
import json
from pathlib import Path

from snapshot_tp2_workflow import cpu_probe

PROGRAM = r'''import importlib.metadata as metadata,json
from pathlib import Path
import torch,vllm
assert not torch.cuda.is_initialized()
root=Path(metadata.distribution('vllm').locate_file(''))
directory=root/'vllm/model_executor/layers/fused_moe/runner'
files={str(p.relative_to(root)):p.read_text() for p in sorted(directory.rglob('*.py'))}
assert files and sum(len(v.encode()) for v in files.values())<4000000
print(json.dumps({'files':files,'vllm_file':vllm.__file__,'vllm_version':vllm.__version__,
    'cuda_initialized':torch.cuda.is_initialized()}))
'''


def inspect_runner(run):
    target = run.path / 'runtime-runner-sources'
    if target.exists(): raise ValueError('Preserve the existing runner inspection.')
    result = cpu_probe(run, 'descriptor-runner-source-read', PROGRAM)
    target.mkdir()
    hashes = {}
    for name, source in result.pop('files').items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.suffix != '.py':
            raise ValueError('Unexpected runner source path.')
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
    result['files'] = hashes
    (target / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    run.result('shadow-writer-runner-inspection', 'passed', **result,
        scope='Additional matching-image CPU runner source inspection only; no CUDA context')
