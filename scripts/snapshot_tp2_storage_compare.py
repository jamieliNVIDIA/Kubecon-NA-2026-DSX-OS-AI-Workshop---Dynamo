#!/usr/bin/env python3
"""Same-artifact EFS/RAM/EFS restore control for the qualified CuInterpose TP2 run."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import uuid

import snapshot_cuinterpose_tests as model
from snapshot_storage_compare import (agent, artifact_path, dump, execute, go_seconds,
    labels, mount_probe, mount_ram_view, owned, restore_efs_view)
from testlib import ROOT, Run

BASELINE = ROOT / 'results/20261022-snapshot-cuinterpose-tp2-keepalive'
SYSTEM = 'dynamo-system'


def ready(obj):
    return any(c['type'] == 'Ready' and c['status'] == 'True'
               for c in obj.get('status', {}).get('conditions', []))


def source(run):
    saved = json.loads((run.path / 'source-snapshot.json').read_text())
    live = run.get('get', 'podsnapshot', saved['metadata']['name'], '-n', run.ns)
    content = run.get('get', 'podsnapshotcontent', live['status']['boundSnapshotContentName'])
    if (live['metadata']['uid'] != saved['metadata']['uid'] or not ready(live)
            or content['metadata']['uid'] != run.state['artifact_uid'] or not ready(content)
            or content['spec']['snapshotRef']['uid'] != live['metadata']['uid']):
        raise ValueError('Retained artifact identity/readiness changed')
    return live, content


def idle(run):
    if run.get('get', 'resourceclaims', '-A')['items']:
        raise ValueError('Requires idle GPU claims')
    pods = run.get('get', 'pods', '-A')['items']
    active = [p for p in pods if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
              and p['metadata']['namespace'].startswith('dynamo-ft-')]
    if active:
        raise ValueError('Active feature workload exists')


def inspect(run):
    if 'source_namespace' in run.state:
        raise ValueError('Use a fresh comparison run')
    baseline = json.loads((BASELINE / 'state.json').read_text())
    if baseline['checks']['cuinterpose-restore']['status'] != 'passed':
        raise ValueError('Baseline restore is not qualified')
    run.state['model_lock'] = copy.deepcopy(baseline['model_lock'])
    run.state['namespace'] = baseline['namespace'];run.ns = baseline['namespace']
    run.ensure_namespace()
    idle(run)
    live = run.get('get', 'podsnapshot', model.NAME, '-n', run.ns)
    recorded = json.loads((BASELINE / 'cuinterpose-artifact.json').read_text())
    content = run.get('get', 'podsnapshotcontent', live['status']['boundSnapshotContentName'])
    previous_content = json.loads((BASELINE / 'cuinterpose-restored-content.json').read_text())
    if (live['metadata']['uid'] != recorded['metadata']['uid'] or not ready(live)
            or content['metadata']['uid'] != previous_content['metadata']['uid'] or not ready(content)
            or content['spec'].get('storage') is not None):
        raise ValueError('Needs the exact Ready legacy-filesystem artifact')
    p = agent(run)
    pins = json.loads((ROOT / 'configs/snapshot-upgrade-20261022/images.json').read_text())
    for name in ('agent', 'pagebroker'):
        pin = next(x['image'] for x in pins if '/'+name+'@' in x['image'])
        status = next(c for c in p['status']['containerStatuses'] if c['name'] == name)
        if status['imageID'] != pin or not status['ready'] or status['restartCount']:
            raise ValueError('Snapshot build or component readiness changed')
    run.state.update(source_run=str(BASELINE), source_namespace=run.ns,
                     artifact_uid=str(uuid.UUID(content['metadata']['uid'])), agent_uid=p['metadata']['uid'])
    measured = json.loads((BASELINE / 'snapshot-measurements-latest.json').read_text())
    run.state['expected_files'] = measured['file_count']
    run.state['expected_bytes'] = measured['logical_bytes']
    run.save()
    dump(run, 'source-snapshot.json', live);dump(run, 'source-content.json', content)
    dump(run, 'agent-before.json', p);dump(run, 'nodes-before.json', run.get('get', 'nodes'))
    for name in ('snapshotjob.json', 'cuinterpose-source-pod.json'):
        (run.path / name).write_bytes((BASELINE / name).read_bytes())
    result = execute(run, 'set -eu; findmnt -T "$1"; '
                     'test "$(findmnt -n -o FSTYPE -T "$1")" = nfs4; '
                     'grep MemAvailable /proc/meminfo; cat /etc/snapshot/*; '
                     'command -v gcc findmnt sha256sum; '
                     'ps -eo pid,stat,comm | awk \'NR==1 || /criu|cuda-checkpoint/\'', artifact_path(run))
    (run.path / 'inspection.log').write_text(result.stdout)
    available = next(int(line.split()[1])*1024 for line in result.stdout.splitlines() if line.startswith('MemAvailable:'))
    if available < 512*1024**3:
        raise ValueError('Need at least 512 GiB currently available for bounded RAM control')
    run.result('storage-control-inspection', 'passed', artifact_uid=run.state['artifact_uid'],
               source_run=str(BASELINE), files=measured['file_count'], logical_bytes=measured['logical_bytes'])
    print(result.stdout, flush=True)


def prepare_ram(run):
    source(run);idle(run)
    if run.state.get('checks', {}).get('ram-staging', {}).get('status') == 'passed':
        raise ValueError('RAM staging already completed')
    name = ('tp2-ram-' + run.state['run_id'])[:63].rstrip('-')
    pin = next(x['image'] for x in json.loads((ROOT / 'configs/snapshot-upgrade-20261022/images.json').read_text())
               if '/agent@' in x['image'])
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': SYSTEM, 'labels': labels(run)},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 7200, 'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
            'containers': [{'name': 'stage', 'image': pin, 'command': ['sh', '-c', 'sleep 7200'],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                'resources': {'requests': {'cpu': '4', 'memory': '160Gi'}, 'limits': {'cpu': '8', 'memory': '256Gi'}},
                'volumeMounts': [{'name': 'source', 'mountPath': '/source', 'readOnly': True},
                                 {'name': 'staging', 'mountPath': '/stage'}]}],
            'volumes': [{'name': 'source', 'persistentVolumeClaim': {'claimName': 'snapshot-artifacts-cuinterpose', 'readOnly': True}},
                        {'name': 'staging', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '128Gi'}}]}}
    run.state['helper_name'] = name;run.save()
    dump(run, 'ram-helper-manifest.json', pod)
    run.k('create', '--dry-run=server', '-f', '-', input_text=json.dumps(pod))
    run.k('create', '-f', '-', input_text=json.dumps(pod))
    run.k('wait', 'pod/'+name, '-n', SYSTEM, '--for=condition=Ready', '--timeout=180s', timeout=195)
    helper = run.get('get', 'pod', name, '-n', SYSTEM)
    run.state['helper_uid'] = helper['metadata']['uid'];run.save()
    mount_probe(run)
    script = r'''set -eu
test ! -e /stage/artifact
test "$(findmnt -n -o FSTYPE -T /stage)" = tmpfs
started=$(date +%s)
cp -a "/source/artifacts/$1" /stage/artifact
copied=$(date +%s)
(cd "/source/artifacts/$1"; find . -type f -print0 | sort -z | xargs -0 sha256sum) > /stage/source.sha256
(cd /stage/artifact; sha256sum -c /stage/source.sha256) > /stage/verified.log
verified=$(date +%s)
printf 'copy_seconds %s\nverification_seconds %s\n' "$((copied-started))" "$((verified-copied))"
sha256sum /stage/source.sha256
find /stage/artifact -type f -printf '%s\n' | awk '{n++;b+=$1} END {printf "files %d bytes %.0f\n",n,b}'
touch /stage/verified
findmnt -T /stage
'''
    result = run.k('exec', name, '-n', SYSTEM, '-c', 'stage', '--', 'sh', '-c', script,
                   'copy-verify-owned-artifact', run.state['artifact_uid'], timeout=2400)
    (run.path / 'ram-stage.log').write_text(result.stdout + result.stderr)
    hashes = run.k('exec', name, '-n', SYSTEM, '-c', 'stage', '--', 'cat', '/stage/source.sha256').stdout
    (run.path / 'artifact-files.sha256').write_text(hashes)
    expected = f'files {run.state["expected_files"]} bytes {run.state["expected_bytes"]}'
    if expected not in result.stdout or len(hashes.splitlines()) != run.state['expected_files']:
        raise ValueError('Staged checkpoint size/count differs from the exact baseline')
    run.result('ram-staging', 'passed', logical_bytes=run.state['expected_bytes'], files=run.state['expected_files'],
               hash_manifest_sha256=hashlib.sha256(hashes.encode()).hexdigest())
    print(result.stdout, flush=True)


def delete_worker(run, name):
    found = run.k('get', 'pod', name, '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
        run.k('delete', 'pod', name, '-n', run.ns, '--wait=true', '--timeout=150s', timeout=165)
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)


def restore_one(run, mode, iteration):
    from snapshot_diagnostics import collect_resources
    source(run);idle(run)
    actual = execute(run, 'findmnt -n -o FSTYPE -T "$1"', artifact_path(run)).stdout.strip()
    if actual != {'efs': 'nfs4', 'ram': 'tmpfs', 'nvme': 'ext4'}[mode]:
        raise ValueError('Storage view does not match trial mode')
    name = f'tp2-storage-{mode}-{iteration}-{run.state["attempt_id"]}'
    pod = model.restore_manifest(run, name)
    pod['metadata']['labels'] = labels(run)
    dump(run, name+'-manifest.json', pod)
    run.state.setdefault('workers', []).append(name);run.save()
    try:
        run.apply([pod])
        model.verify(run, name)
        for kind in ('pod', 'claim', 'content', 'inference'):
            (run.path / (name+'-'+kind+'.json')).write_bytes((run.path / ('cuinterpose-restored-'+kind+'.json')).read_bytes())
        current = json.loads((run.path / (name+'-pod.json')).read_text())
        claim = json.loads((run.path / (name+'-claim.json')).read_text())
        pair = sorted((a['pool'], a['device']) for a in claim['status']['allocation']['devices']['results'])
        baseline_claim = json.loads((BASELINE / 'cuinterpose-restored-claim.json').read_text())
        expected_pair = sorted((a['pool'], a['device']) for a in baseline_claim['status']['allocation']['devices']['results'])
        if pair != expected_pair:
            raise ValueError('Physical GPU pair changed; do not compare these timings')
        if any(m['pod_uid'] == current['metadata']['uid'] for m in run.state.get('measurements', [])):
            raise ValueError('A previous restore Pod UID was reused')
        logs = run.k('logs', agent(run)['metadata']['name'], '-n', SYSTEM, '-c', 'agent', '--timestamps', '--tail=1600').stdout
        (run.path / (name+'-agent.log')).write_text(logs)
        summaries = [json.loads(line[line.index('{'):]) for line in logs.splitlines()
                     if 'Restore timing summary' in line and f'{run.ns}/{name}' in line]
        if len(summaries) != 1 or summaries[0]['content_uid'] != run.state['artifact_uid']:
            raise ValueError('Missing exact-content/Pod restore timing summary')
        summary = summaries[0]['restore']
        created = dt.datetime.fromisoformat(current['metadata']['creationTimestamp'].replace('Z', '+00:00'))
        ready_at = next(c['lastTransitionTime'] for c in current['status']['conditions'] if c['type'] == 'Ready')
        record = {'mode': mode, 'iteration': iteration, 'pod': name, 'pod_uid': current['metadata']['uid'],
            'content_uid': run.state['artifact_uid'], 'inference': 'passed',
            'physical_gpu_pair': pair,
            'agent_seconds': go_seconds(summary['duration']),
            'phases': {k: go_seconds(v) for k,v in summary['phases'].items()},
            'pod_to_ready_seconds': (dt.datetime.fromisoformat(ready_at.replace('Z', '+00:00'))-created).total_seconds(),
            'agent_summary': summaries[0]}
        dump(run, name+'-measurement.json', record)
        run.state.setdefault('measurements', []).append(record);run.save()
        collect_resources(run)
        print(json.dumps(record, indent=2), flush=True)
    finally:
        result = run.k('logs', name, '-n', run.ns, '-c', 'main', '--tail=100', check=False)
        (run.path / (name+'-app.log')).write_text(result.stdout + result.stderr)
        delete_worker(run, name)


def compare(run):
    if run.state.get('checks', {}).get('storage-comparison', {}).get('status') == 'passed':
        raise ValueError('Completed control; use a fresh run')
    if run.state.get('checks', {}).get('ram-staging', {}).get('status') != 'passed':
        raise ValueError('Stage and verify the exact artifact first')
    run.state['attempt_id'] = str(time.time_ns())[-10:];run.save()
    try:
        restore_efs_view(run)
        restore_one(run, 'efs', 1)
        mount_ram_view(run)
        try:
            restore_one(run, 'ram', 1)
        finally:
            restore_efs_view(run)
        restore_one(run, 'efs', 2)
        run.result('storage-comparison', 'passed', measurements=run.state['measurements'])
    finally:
        cleanup(run)


def cleanup(run):
    for name in run.state.get('workers', []):
        delete_worker(run, name)
    if run.state.get('artifact_uid'):
        restore_efs_view(run)
    if run.state.get('helper_name'):
        found = run.k('get', 'pod', run.state['helper_name'], '-n', SYSTEM, '-o', 'json', check=False)
        if found.returncode == 0:
            helper = json.loads(found.stdout);owned(run, helper)
            if run.state.get('helper_uid') and helper['metadata']['uid'] != run.state['helper_uid']:
                raise ValueError('Helper identity changed')
            run.k('delete', 'pod', run.state['helper_name'], '-n', SYSTEM, '--wait=true', '--timeout=120s', timeout=135)
        elif 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
    if run.state.get('mount_helper'):
        path = '/tmp/snapshot-storage-tools-' + run.state['run_id']
        if run.state['mount_helper'] != path+'/ram-bind':
            raise ValueError('Unexpected mount helper path')
        execute(run, 'set -eu; rm -f "$1/ram-bind"; rmdir "$1"', path)
        run.state.pop('mount_helper');run.save()
    if (run.path / 'agent-before.json').exists():
        p = agent(run);dump(run, 'agent-after.json', p)
        if p['spec'] != json.loads((run.path / 'agent-before.json').read_text())['spec']:
            raise ValueError('Shared agent specification changed')
        source(run);idle(run)
        run.result('storage-comparison-cleanup', 'passed', scope='EFS view restored, owned Pods removed; no disk/config changes')


def progress(run):
    source(run)
    if run.state.get('helper_name'):
        from snapshot_storage_compare import progress as stage_progress
        stage_progress(run)
    for name in run.state.get('workers', []):
        found = run.k('get', 'pod', name, '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0:
            pod = json.loads(found.stdout);owned(run, pod)
            dump(run, name+'-progress-'+str(time.time_ns())+'.json', pod)
            print(name, pod['status'].get('conditions'), flush=True)
    p = agent(run)
    result = run.k('logs', p['metadata']['name'], '-n', SYSTEM, '-c', 'agent', '--tail=100')
    (run.path / ('agent-progress-'+str(time.time_ns())+'.log')).write_text(result.stdout)
    print(result.stdout[-5000:], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'prepare-ram', 'compare', 'cleanup', 'progress'))
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args();run = Run(args.run)
    if args.action == 'prepare-ram':
        try:
            prepare_ram(run)
        except BaseException:
            cleanup(run)
            raise
    else:
        globals()[args.action.replace('-', '_')](run)


if __name__ == '__main__':
    main()
