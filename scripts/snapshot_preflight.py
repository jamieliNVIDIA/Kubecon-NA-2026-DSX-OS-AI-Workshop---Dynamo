#!/usr/bin/env python3
"""Read-only Snapshot infrastructure check; never installs privileged node agents."""
import argparse
import json
import yaml
from pathlib import Path
from testlib import Run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path)
    parser.add_argument('--implementation',choices=('current','legacy'),default='current',
     help='current requires both operators and SnapshotJob APIs; legacy checks the installed 1.4.2 integration')
    args=parser.parse_args();run=Run(args.run)
    report={}
    report['dynamo_operators']=[]
    for resource in ('daemonsets','deployments'):
     items=run.get('get',resource,'-A')['items']
     report[resource]=[{'namespace':i['metadata']['namespace'],'name':i['metadata']['name'],'status':i.get('status'),
       'images':[c['image'] for c in i['spec']['template']['spec'].get('containers',[])]}
      for i in items if any(x in (i['metadata']['name']+' '+json.dumps(i['spec']['template']['spec'])).lower()
        for x in ('snapshot-agent','snapshot-operator'))]
     if resource=='deployments':
      for obj in items:
       if obj['metadata'].get('labels',{}).get('app.kubernetes.io/name')!='dynamo-operator':continue
       operator={'namespace':obj['metadata']['namespace'],'name':obj['metadata']['name'],'checkpoint':None}
       for volume in obj['spec']['template']['spec'].get('volumes',[]):
        if volume['name']=='operator-config' and 'configMap' in volume:
         cm=run.get('get','configmap',volume['configMap']['name'],'-n',operator['namespace'])
         config=yaml.safe_load(cm.get('data',{}).get('config.yaml','')) or {}
         operator['checkpoint']=config.get('checkpoint')
       report['dynamo_operators'].append(operator)
    report['crds']=[c['metadata']['name'] for c in run.get('get','crds')['items'] if any(x in c['metadata']['name'] for x in ('snapshot','checkpoint'))]
    report['nodes']=[{'name':n['metadata']['name'],'kernel':n['status']['nodeInfo']['kernelVersion'],
     'driver':n['metadata']['labels'].get('nvidia.com/cuda.driver-version.full'),
     'gpus':n['status']['allocatable'].get('nvidia.com/gpu')}
     for n in run.get('get','nodes')['items']]
    (run.path/'snapshot-preflight.json').write_text(json.dumps(report,indent=2)+'\n')
    checkpoint_enabled=any((o.get('checkpoint') or {}).get('enabled') for o in report['dynamo_operators'])
    missing=[]
    if not report['daemonsets']:missing.append('Snapshot agent DaemonSet')
    if not checkpoint_enabled:missing.append('Dynamo operator checkpoint.enabled=true')
    required_crds={'dynamocheckpoints.nvidia.com'}
    if args.implementation=='current':
     if not report['deployments']:missing.append('Snapshot operator Deployment')
     required_crds={'snapshotjobs.nvidia.com','podsnapshots.nvidia.com','podsnapshotcontents.nvidia.com'}
    missing.extend(sorted(required_crds-set(report['crds'])))
    run.result('snapshot-preflight','blocked' if missing else 'present',
     **report,implementation=args.implementation,missing=missing,
     reason='Resource presence only; does not prove controller readiness, version compatibility, or successful restore',
     action_required='Review and approve the shared Snapshot infrastructure installation before a restore test')


if __name__ == '__main__':
    main()
