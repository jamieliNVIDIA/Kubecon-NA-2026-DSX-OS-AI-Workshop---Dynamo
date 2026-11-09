#!/usr/bin/env python3
"""Stop only owned feature-test workloads, retaining cache PVCs and EFS data."""
import argparse
import json
from pathlib import Path
import time
from testlib import ROOT, OWNER, Run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args();run=Run(args.run)
    namespaces=run.get('get','namespaces','-l',f'app.kubernetes.io/managed-by={OWNER}')['items']
    recorded={json.loads(p.read_text()).get('namespace') for p in (ROOT/'results').glob('*/state.json')
              if json.loads(p.read_text()).get('owner')==OWNER}
    namespaces=[n for n in namespaces if n['metadata']['name'] in recorded]
    removed=[]
    for ns in namespaces:
     name=ns['metadata']['name']
     if not name.startswith('dynamo-ft-'):continue
     for resource in ('dgd','podcliquesets','pods'):
      objects=run.get('get',resource,'-n',name)['items']
      for obj in objects:
       identifier=obj['metadata']['name']
       if resource in ('dgd','podcliquesets'):
        if obj['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')!=OWNER:continue
       elif not (identifier.startswith(('ft-','runtime-probe','nixl-','storage-','model-download','kvcr-build'))
                 or obj['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==OWNER):continue
       run.k('delete',resource,identifier,'-n',name,'--ignore-not-found','--wait=false')
       removed.append({'namespace':name,'kind':resource,'name':identifier})
    end=time.monotonic()+180
    while time.monotonic()<end:
     remaining=[]
     for ns in namespaces:
      name=ns['metadata']['name']
      for p in run.get('get','pods','-n',name)['items']:
       if (p['metadata']['name'].startswith(('ft-','runtime-probe','nixl-','storage-','model-download','kvcr-build'))
           or p['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')==OWNER):
        remaining.append({'namespace':name,'name':p['metadata']['name'],'phase':p.get('status',{}).get('phase')})
     if not remaining:break
     time.sleep(5)
    run.result('cleanup','passed' if not remaining else 'incomplete',removed=removed,remaining=remaining,
     scope='Only owned test workloads stopped. Namespaces, PV/PVCs, images and cached EFS data retained.')


if __name__ == '__main__':
    main()
