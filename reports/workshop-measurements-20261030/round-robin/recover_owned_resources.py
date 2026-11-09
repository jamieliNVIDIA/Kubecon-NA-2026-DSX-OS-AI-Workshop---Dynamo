#!/usr/bin/env python3
"""Collect and clean only this workstream's retained GPU resources after reconnect."""
import argparse
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import execute_pair as e


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--label',required=True,help='Unique immutable recovery evidence label')
    p.add_argument('--cleanup',action='store_true',help='Stop the owned DGD and release only our verified lease')
    args=p.parse_args()
    if not e.re.fullmatch(r'[a-z0-9-]+',args.label):raise ValueError('Invalid label')
    run=e.Run(args.run);e.lease_owned()
    dest=run.path/('recovery-'+args.label);dest.mkdir(exist_ok=False)
    for kind in ('pods','resourceclaims','dgd','events'):
        value=run.get('get',kind,'-n',run.ns)
        (dest/(kind+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    e.collect_workers(run,dest.name)
    (dest/'lease-before.json').write_bytes((e.LEASE/'owner.json').read_bytes())
    if args.cleanup:
        e.cleanup_gpu(run)
        e.status(run,'owned GPU resources cleaned after connectivity outage; fresh qualification required',
            recovery=str(dest),previous_attempt='c1-r1-a2',agentx_profiles_started=0)
    else:
        e.status(run,'recovery inventory collected; GPU lease still retained',recovery=str(dest))


if __name__=='__main__':main()
