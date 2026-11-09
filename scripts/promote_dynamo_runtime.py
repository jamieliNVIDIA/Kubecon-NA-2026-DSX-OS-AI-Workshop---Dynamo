#!/usr/bin/env python3
"""Adopt public runtime 1.5.1 locally only after its serving/transfer checks pass."""
import argparse
import json
from pathlib import Path
from testlib import ROOT, Run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();run=Run(args.run)
    required=('agg-inference','kv-routing','disaggregation','modelexpress')
    if any(run.state.get('checks',{}).get(key,{}).get('status')!='passed' for key in required):
        raise ValueError('Requires all four public-runtime feature checks to pass')
    candidate=json.loads((run.path/'model-lock.json').read_text())
    public=json.loads((ROOT/'configs/dynamo-1.5.1-runtime.json').read_text())[0]
    if candidate!=run.state['model_lock'] or candidate['runtime_image']!=public['image']:
        raise ValueError('Candidate lock differs from tested/pinned runtime')
    assert candidate['runtime_version_override']=='1.5.1'
    default=ROOT/'configs/model-lock.json'
    previous=json.loads(default.read_text())
    if any(previous[key]!=candidate[key] for key in ('model','revision')):
        raise ValueError('Runtime promotion must preserve model and revision')
    archive=ROOT/'configs/model-lock-original.json'
    if not archive.exists():archive.write_text(json.dumps(previous,indent=2)+'\n')
    default.write_text(json.dumps(candidate,indent=2)+'\n')
    # Existing runs keep their frozen model_lock; this changes only new defaults.
    run.result('runtime-default-promotion','passed',runtime_image=public['image'],
               target_version='1.5.1',required_passes=list(required),
               note='Local serving default updated; prior runs retain their frozen runtime lock')


if __name__=='__main__':main()
