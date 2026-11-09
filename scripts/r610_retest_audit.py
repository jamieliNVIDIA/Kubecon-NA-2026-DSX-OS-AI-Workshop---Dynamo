#!/usr/bin/env python3
"""Compare saved pre/post inventories and read-only GPU health receipts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def read(path):return json.loads(path.read_text())


def new_xids(before, after):
    # dmesg derives ISO times from the current clock offset; old entries can
    # shift by microseconds. Preserve repeated messages using occurrence counts.
    def body(line):return line.split(' NVRM: ',1)[-1]
    delta=Counter(body(line) for line in after)-Counter(body(line) for line in before)
    added=[]
    for line in reversed(after):
        key=body(line)
        if delta[key]>0:
            added.append(line);delta[key]-=1
    return list(reversed(added))


def audit(before, after, health_before, health_after, output):
    report={'before':str(before),'after':str(after),'nodes':[], 'blockers':[]}
    for directory in (before,after):
        receipt=read(directory/'receipt.json')
        if any(v['status']!='collected' for v in receipt['checks'].values()):
            report['blockers'].append('Incomplete inventory: '+str(directory))
    initial={n['metadata']['name']:n for n in read(before/'nodes.json')['items']}
    final={n['metadata']['name']:n for n in read(after/'nodes.json')['items']}
    if set(initial)!=set(final) or len(final)!=3:report['blockers'].append('Node set changed')
    def health(directory):
        entries={}
        for path in directory.glob('snapshot-gpu-health-*.json'):
            entry=read(path)
            if entry['node'] not in entries or entry['observed_at']>entries[entry['node']]['observed_at']:
                entries[entry['node']]=entry
        return entries
    old_health=health(health_before);new_health=health(health_after)
    if set(old_health)!=set(initial) or set(new_health)!=set(final):raise ValueError('Missing node health receipts')
    for name,node in final.items():
        old=initial[name];h=new_health[name];previous=old_health[name]
        if h['observed_at']<=previous['observed_at']:raise ValueError('Final health predates baseline')
        def xids(directory,entry):
            return (directory/entry['outputs']['kernel-xids']['file']).read_text().splitlines()
        gpu=ET.fromstring((health_after/h['outputs']['nvidia-smi']['file']).read_text())
        entry={'node':name,'driver':node['metadata']['labels'].get('nvidia.com/cuda.driver-version.full'),
            'ready':any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions']),
            'boot_id_unchanged':node['status']['nodeInfo']['bootID']==old['status']['nodeInfo']['bootID'],
            'uid_unchanged':node['metadata']['uid']==old['metadata']['uid'],
            'condition_statuses_unchanged':{c['type']:c['status'] for c in node['status']['conditions']}==
                {c['type']:c['status'] for c in old['status']['conditions']},
            'efa':node['status']['allocatable'].get('vpc.amazonaws.com/efa'),
            'gpu_count':len(gpu.findall('gpu')),'smi_driver':gpu.findtext('driver_version'),
            'new_xids':new_xids(xids(health_before,previous),xids(health_after,h)),
            'preexisting_xid_lines':len(xids(health_before,previous)),
            'health_commands_passed':all(v['exit_code']==0 for v in h['outputs'].values()),
            'health_observed_at':h['observed_at']}
        report['nodes'].append(entry)
        if not all(entry[k] for k in ('ready','boot_id_unchanged','uid_unchanged','condition_statuses_unchanged','health_commands_passed')) or entry['new_xids'] or entry['driver']!='610.57.04' or entry['smi_driver']!='610.57.04' or entry['efa']!='32' or entry['gpu_count']!=8:
            report['blockers'].append('Node health mismatch: '+name)
    report['claims']=len(read(after/'resourceclaims.json')['items'])
    pods=read(after/'pods.json')
    report['active_feature_pods']=[p['namespace']+'/'+p['name'] for p in pods
        if p['namespace'].startswith('dynamo-ft-') and p['phase'] not in ('Succeeded','Failed')]
    namespaces={'gpu-operator','nvidia-dra-driver','nvsentinel','dynamo-system','kube-system','kai-scheduler','grove-system'}
    report['unready_infrastructure']=[p['namespace']+'/'+p['name'] for p in pods if p['namespace'] in namespaces
        and p['phase'] not in ('Succeeded','Failed') and (not p['container_status'] or not all(c['ready'] for c in p['container_status']))]
    old_pods={(p['namespace'],p['name']):p for p in read(before/'pods.json')}
    report['infrastructure_restart_increases']=[]
    for pod in pods:
        previous=old_pods.get((pod['namespace'],pod['name']))
        if not previous or pod['namespace'] not in namespaces:continue
        counts={c['name']:c['restarts'] for c in previous['container_status']}
        for c in pod['container_status']:
            if c['restarts']>counts.get(c['name'],0):report['infrastructure_restart_increases'].append(pod['namespace']+'/'+pod['name']+'/'+c['name'])
    def helm(directory):return sorted((r['namespace'],r['name'],r['revision'],r['chart'],r['app_version'],r['status']) for r in read(directory/'helm.json'))
    report['helm_unchanged']=helm(before)==helm(after)
    if report['claims'] or report['active_feature_pods'] or report['unready_infrastructure'] or report['infrastructure_restart_increases'] or not report['helm_unchanged']:
        report['blockers'].append('Cleanup or infrastructure drift')
    report['status']='blocked' if report['blockers'] else 'passed'
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['blockers']:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','health-before','health-after','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args()
    audit(args.before,args.after,args.health_before,args.health_after,args.output)
