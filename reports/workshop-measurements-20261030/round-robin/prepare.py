#!/usr/bin/env python3
"""Prepare an owned RR benchmark namespace and inspect the pinned runtime on CPU."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from testlib import Run
from r610_feature_retests import prepare
from snapshot_tp2_workflow import cpu_probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    if (args.run / 'model-lock.json').exists():
        raise ValueError('Preparation requires a fresh run directory')
    run = Run(args.run)
    prepare(run, run.path, 'rr')
    for kind in ('nodes', 'pods', 'resourceclaims'):
        values = run.get('get', kind, *(['-A'] if kind != 'nodes' else []))
        (run.path / f'initial-{kind}.json').write_text(json.dumps(values, indent=2)+'\n')
    program = '''import importlib.metadata as m,json,shutil
from pathlib import Path
packages={}
for name in ['ai-dynamo','vllm','aiperf','torch','transformers']:
 try:packages[name]=m.version(name)
 except m.PackageNotFoundError:packages[name]=None
root=Path(m.distribution('ai-dynamo').locate_file('dynamo'))
backend=(root/'vllm/backend_args.py').read_text()
print(json.dumps({'packages':packages,'pip':shutil.which('pip'),'uv':shutil.which('uv'),
 'native_multimodal_flag':'--enable-multimodal' in backend,
 'runtime_root':str(root)}))
'''
    report = cpu_probe(run, 'rr-runtime-inspect', program)
    (run.path / 'runtime-inspection.json').write_text(json.dumps(report, indent=2)+'\n')
    run.result('rr-cpu-preparation', 'passed', **report,
               scope='CPU-only cache/model identity and runtime inspection; no GPU serving qualification')
    print(json.dumps({'run':str(run.path),'namespace':run.ns,'runtime':report},indent=2))


if __name__ == '__main__':
    main()
