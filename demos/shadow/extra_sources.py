#!/usr/bin/env python3
"""CPU-only installed-source inspection; no GMS connection or GPU allocation."""
import argparse
import hashlib
import json
from pathlib import Path
from snapshot_tp2_workflow import cpu_probe
from demos.shadow.writer import load

PROGRAM = '''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('vllm').locate_file(''))
names=['vllm/model_executor/layers/fused_moe/experts/fused_humming_moe.py',
'vllm/model_executor/layers/fused_moe/modular_kernel.py',
'vllm/model_executor/layers/quantization/base_config.py',
'humming/kernel/humming.py']
print(json.dumps({n:(root/n).read_text() if (root/n).is_file() else None for n in names}))
'''

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    run, spec = load(args.run)
    target = run.path / 'extra-runtime-sources'
    if target.exists():
        raise ValueError('Extra source snapshot already exists; do not overwrite.')
    report = cpu_probe(run, 'writer-extra-source-read', PROGRAM)
    target.mkdir()
    manifest = {'image_id': report.pop('image_id'), 'files': {}}
    for name, source in report.items():
        if source is not None:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
            manifest['files'][name] = hashlib.sha256(source.encode()).hexdigest()
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(target)
