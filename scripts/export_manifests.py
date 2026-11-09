#!/usr/bin/env python3
"""Save the actual spec of owned Dynamo test graphs without server-managed fields."""
import argparse
import json
from pathlib import Path
import yaml
from testlib import ROOT, Run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--validate',action='store_true')
    args=parser.parse_args();run=Run(args.run)
    filenames={'ft-agg':'nemotron-agg-functionality.yaml','ft-disagg':'nemotron-disagg-functionality.yaml',
     'ft-sidecar':'nemotron-engine-sidecar.yaml','ft-mx':'nemotron-modelexpress.yaml',
     'ft-mx-target':'nemotron-modelexpress-target.yaml','ft-kvcr':'nemotron-kvcr.yaml'}
    for graph in run.get('get','dgd','-n',run.ns)['items']:
     name=graph['metadata']['name']
     if name not in filenames or graph['metadata'].get('labels',{}).get('feature-test-run')!=run.ns:continue
     export={k:graph[k] for k in ('apiVersion','kind','spec')}
     export['metadata']={'name':name,'namespace':run.ns,'labels':run.labels()}
     destination=ROOT/'configs/dgd'/filenames[name];destination.write_text(yaml.safe_dump(export,sort_keys=False))
     if args.validate:
      for mode in ('client','server'):
       run.k('apply',f'--dry-run={mode}','-f','-',input_text=json.dumps(export))
     print(destination)


if __name__ == '__main__':
    main()
