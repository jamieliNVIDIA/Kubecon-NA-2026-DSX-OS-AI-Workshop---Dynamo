#!/usr/bin/env python3
"""Compare the same checkpoint on EFS and tmpfs without formatting any disk."""
import argparse
import copy
import datetime as dt
import json
import re
import time
from pathlib import Path
from testlib import Run, ROOT

SOURCE_RUN = ROOT / 'results/20261013-common-runtime-features'
NODE = 'kubecon-nke-site-cp-0124'
DEVICE = '/dev/nvme0n1'


def dump(run, name, obj):
    (run.path / name).write_text(json.dumps(obj, indent=2) + '\n')


def agent(run):
    pods = run.get('get', 'pods', '-n', 'dynamo-system')['items']
    matches = [p for p in pods if p['metadata']['name'].startswith('dynamo-platform-snapshot-agent-')
               and p['spec'].get('nodeName') == NODE and p['status'].get('phase') == 'Running']
    if len(matches) != 1:
        raise ValueError('Expected one running Snapshot agent on cp-0124')
    if run.state.get('agent_uid') and matches[0]['metadata']['uid'] != run.state['agent_uid']:
        raise ValueError('Agent identity changed; inspect the temporary mount before proceeding')
    return matches[0]


def execute(run, script, *args, timeout=60, check=True):
    p = agent(run)
    return run.k('exec', '-n', 'dynamo-system', p['metadata']['name'], '-c', 'agent', '--',
                 'sh', '-c', script, 'snapshot-storage-compare', *args, timeout=timeout, check=check)


def inspect(run):
    p = agent(run)
    dump(run, 'agent-before.json', p)
    dump(run, 'nodes-before.json', run.get('get', 'nodes'))
    dump(run, 'pods-before.json', run.get('get', 'pods', '-A'))
    snapshot = json.loads((SOURCE_RUN / 'snapshot-artifact.json').read_text())
    live = run.get('get', 'podsnapshot', snapshot['metadata']['name'], '-n', snapshot['metadata']['namespace'])
    content = run.get('get', 'podsnapshotcontent', live['status']['boundSnapshotContentName'])
    if live['metadata']['uid'] != snapshot['metadata']['uid']:
        raise ValueError('Source snapshot identity changed')
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in content['status']['conditions']):
        raise ValueError('Source content is not Ready')
    dump(run, 'source-snapshot.json', live)
    dump(run, 'source-content.json', content)
    result = execute(run, 'set -eu; '
                     'echo "Host block devices"; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL; '
                     'echo "Host mounts"; findmnt -N 1 -o TARGET,SOURCE,FSTYPE,OPTIONS | head -35; '
                     'echo "Artifact mount"; findmnt -T /checkpoints; '
                     'echo "Disk capacity"; df -h /checkpoints /proc/1/root /proc/1/root/mnt; '
                     'echo "Agent executables"; command -v snapshot-agent nsrestore nsenter mount umount cp sha256sum; '
                     'echo "Agent config"; cat /etc/snapshot/*; '
                     'echo "Artifact top level"; ls -la "/checkpoints/artifacts/$1"; '
                     'echo "CRIU activity"; ps -eo pid,ppid,stat,etime,wchan:32,comm | awk "NR == 1 || /criu/"',
                     content['metadata']['uid'])
    (run.path / 'storage-inspection.log').write_text(result.stdout + result.stderr)
    run.state['source_run'] = str(SOURCE_RUN)
    run.state['source_namespace'] = live['metadata']['namespace']
    run.state['artifact_uid'] = content['metadata']['uid']
    run.state['agent_uid'] = p['metadata']['uid']
    run.save()
    print(result.stdout, flush=True)


def disks(run):
    result = execute(run, 'set -eu; '
                     'echo "NVMe signatures (read only)"; '
                     'for d in /dev/nvme*n1; do echo "$d"; '
                     'blkid -p "$d" || test "$?" = 2; '
                     'wipefs --no-act "$d"; done; '
                     'echo "Host local block mounts"; '
                     'findmnt -N 1 -rn -o TARGET,SOURCE,FSTYPE | awk \'$2 ~ /^\\/dev\\//\'; '
                     'echo "Host mount propagation"; findmnt -N 1 -rn -o TARGET,PROPAGATION | head -15; '
                     'echo "Agent mount propagation"; findmnt -rn -o TARGET,PROPAGATION | head -15; '
                     'echo "Host scratch paths"; '
                     'ls -ld /proc/1/root/mnt /proc/1/root/mnt/* /proc/1/root/local* /proc/1/root/data* 2>/dev/null || true',
                     timeout=60)
    (run.path / f'nvme-signatures-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
    (run.path / 'nvme-signatures.log').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)


def plan(run):
    result = execute(run, 'set -eu; '
                     'lsblk -J -b -d -o NAME,SIZE,MODEL,SERIAL "$1"; '
                     'echo "Filesystem tools"; command -v mkfs.ext4 blockdev blkid wipefs flock; '
                     'echo "Read-only checks"; blockdev --getro "$1"; '
                     'ls -la /sys/class/block/nvme0n1/holders; '
                     'echo "Partitions"; ls /sys/class/block/nvme0n1/ | head -25', DEVICE)
    (run.path / 'nvme-plan-inspection.log').write_text(result.stdout + result.stderr)
    device = json.JSONDecoder().raw_decode(result.stdout)[0]['blockdevices'][0]
    if device['model'].strip() != 'Amazon EC2 NVMe Instance Storage':
        raise ValueError('Candidate is not EC2 instance storage')
    proposal = {'prepared_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'node': NODE, 'device': DEVICE, 'identity': device,
                'source_snapshot': json.loads((run.path / 'source-snapshot.json').read_text())['metadata']['name'],
                'artifact_uid': run.state['artifact_uid'], 'artifact_bytes': 35871594315,
                'filesystem': 'ext4, whole device, no partition table, no discard, zero reserved percentage',
                'format_requires_explicit_user_approval': True,
                'format_effect': 'Persistent filesystem metadata is written to this device; formatting is destructive to any unidentified raw data.',
                'mount_scope': 'Temporary private Snapshot agent mount namespace; no host mount/fstab/DaemonSet/PVC changes',
                'comparison': 'Existing checkpoint, EFS baseline then local NVMe restore then EFS repeat, same image/model/GPU/resources',
                'cache_policy': 'Existing direct CRIU image I/O retained; no global cache flush',
                'cleanup': 'Delete owned test Pods/frontend; unmount read-only artifact overlay and temporary NVMe mount; original EFS artifact untouched; formatted device remains'}
    dump(run, 'nvme-plan.json', proposal)
    run.state['nvme_plan'] = proposal
    run.save()
    report = ROOT / 'reports/2026-10-13-snapshot-nvme-plan.md'
    report.write_text('# Snapshot local NVMe comparison proposal\n\n'
        f'Prepared {proposal["prepared_at"]}. No device writes performed.\n\n'
        f'On **{NODE}**, **{DEVICE}** is `{device["model"].strip()}`, '
        f'serial **{device["serial"]}**, {device["size"]:,} bytes. '
        'Read-only blkid/wipefs checks found no filesystem or partition signature. '
        'None of the eight instance devices is mounted. The EBS root filesystem has only about 33 GiB free.\n\n'
        'The proposal initializes only this device with ext4. It must be explicitly approved: '
        'absence of recognizable signatures does not prove absence of raw data. '
        'The filesystem metadata persists after test cleanup.\n\n'
        'Use a temporary mount in the existing agent\'s private mount namespace. Copy and verify '
        'the existing 35,871,594,315-byte checkpoint, then temporarily bind the local copy read-only '
        'over that artifact path for a single restore. EFS artifact contents, host mounts, fstab, '
        'the Helm release, agent specification and PVC configuration stay unchanged. '
        'Only the selected artifact\'s view inside this agent changes during the local test.\n\n'
        'Run EFS / NVMe / EFS restores with the same image, model, TP1 GPU allocation and resource requests. '
        'Record CRIU/CUDA/total restore timing, Pod readiness and a fresh inference result. '
        'Retain direct image I/O and avoid system-wide cache flushing. Include copy time separately '
        'from restore time: pre-staging costs are not startup acceleration.\n\n'
        'Cleanup deletes only owned test resources and unmounts the artifact overlay and local filesystem. '
        'The original checkpoint remains on EFS.\n\n'
        'Reusable inspection: `scripts/snapshot_storage_compare.py inspect|disks|plan '
        '--run results/20261013-snapshot-storage-compare`.\n')
    print(json.dumps(proposal, indent=2), flush=True)


def adopt_namespace(run):
    # PodSnapshot references are namespace-local. Reuse the source test namespace
    # and its PVC/registry secret; never migrate or rewrite the retained artifact.
    namespace = run.state['source_namespace']
    if not namespace.startswith('dynamo-ft-'):
        raise ValueError('Not a feature test namespace')
    run.state['namespace'] = namespace
    run.ns = namespace
    run.save()
    run.ensure_namespace()


def labels(run):
    return {**run.labels(), 'snapshot-storage-experiment': run.state['run_id']}


def owned(run, obj):
    if obj['metadata'].get('labels', {}).get('snapshot-storage-experiment') != run.state['run_id']:
        raise ValueError('Resource is not owned by this storage comparison')


def prepare(run):
    if run.state.get('checks', {}).get('storage-comparison', {}).get('status') == 'passed':
        raise ValueError('Completed comparison: use a fresh --run directory for another test')
    adopt_namespace(run)
    active = [p for p in run.get('get', 'pods', '-A')['items']
              if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
              and p['metadata'].get('annotations', {}).get('nvidia.com/restore-from')]
    if active:
        raise ValueError('Concurrent Snapshot restore Pods exist; defer isolated comparison')
    graph = json.loads((SOURCE_RUN / 'snapshot-dgd.json').read_text())
    graph['metadata'] = {'name': 'ft-snapshot', 'namespace': run.ns, 'labels': labels(run),
                         'annotations': {'nvidia.com/enable-grove': 'false'}}
    # Restore a standalone Pod; this frontend-only graph cannot capture or
    # initialize another worker, and provides the original discovery namespace.
    graph['spec']['components'] = [c for c in graph['spec']['components'] if c['type'] == 'frontend']
    for component in graph['spec']['components']:
        component['podTemplate']['metadata']['labels'] = labels(run)
    found = run.k('get', 'dgd', 'ft-snapshot', '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    run.state['frontend_planned'] = True
    run.save()
    run.apply([graph])
    # Default Dynamo discovery joins WorkerMetadata with ready EndpointSlices.
    # A standalone restore Pod has no DGD-generated worker Service, so give the
    # harness its own Service rather than changing engine/discovery behavior.
    service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {
        'name': 'ft-snapshot-storage-worker', 'namespace': run.ns,
        'labels': {**labels(run), 'nvidia.com/dynamo-discovery-backend': 'kubernetes',
                   'nvidia.com/dynamo-discovery-enabled': 'true'}},
        'spec': {'selector': {'snapshot-storage-experiment': run.state['run_id'],
                              'nvidia.com/dynamo-component-type': 'worker'},
                 'ports': [{'name': 'system', 'port': 9090, 'targetPort': 9090}]}}
    run.apply([service])
    run.k('wait', '--for=condition=Ready', 'dgd/ft-snapshot', '-n', run.ns, '--timeout=300s', timeout=320)
    print('Original discovery namespace frontend is Ready; no capture worker created.', flush=True)
    name = 'snapshot-ram-control-' + run.state['run_id'].replace('snapshot-storage-compare', 'storage')
    name = name[:63].rstrip('-')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
        'name': name, 'namespace': 'dynamo-system', 'labels': labels(run)},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 3600,
                 'automountServiceAccountToken': False, 'nodeSelector': {'kubernetes.io/hostname': NODE},
                 'tolerations': [{'key': 'nvidia.com/gpu', 'operator': 'Exists', 'effect': 'NoSchedule'}],
                 'containers': [{'name': 'stage', 'image': json.loads((ROOT / 'configs/snapshot-0.1.0-images.json').read_text())[1]['image'],
                     'command': ['sh', '-c', 'sleep 3600'],
                     'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                     'resources': {'requests': {'cpu': '2', 'memory': '48Gi'}, 'limits': {'memory': '64Gi'}},
                     'securityContext': {'runAsUser': 0},
                     'volumeMounts': [{'name': 'source', 'mountPath': '/source', 'readOnly': True},
                                      {'name': 'staging', 'mountPath': '/stage'}]}],
                 'volumes': [{'name': 'source', 'persistentVolumeClaim': {'claimName': 'snapshot-artifacts', 'readOnly': True}},
                             {'name': 'staging', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '48Gi'}}]}}
    run.state['helper_name'] = name
    run.save()
    dump(run, 'ram-helper-manifest.json', pod)
    found = run.k('get', 'pod', name, '-n', 'dynamo-system', '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
    else:
        if 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
        run.k('create', '--dry-run=server', '-f', '-', input_text=json.dumps(pod))
        run.k('create', '-f', '-', input_text=json.dumps(pod))
    run.k('wait', '--for=condition=Ready', 'pod/' + name, '-n', 'dynamo-system', '--timeout=180s', timeout=200)
    helper = run.get('get', 'pod', name, '-n', 'dynamo-system')
    run.state['helper_uid'] = helper['metadata']['uid']
    run.save()
    mount_probe(run)
    print('RAM helper is Ready; copying the retained artifact and verifying all file hashes.', flush=True)
    result = run.k('exec', '-n', 'dynamo-system', name, '-c', 'stage', '--', 'sh', '-c',
        'set -eu; source="/source/artifacts/$1"; dest=/stage/artifact; '
        'test ! -e "$dest"; started=$(date +%s); cp -a "$source" "$dest"; copied=$(date +%s); '
        '(cd "$source"; find . -type f -print0 | sort -z | xargs -0 sha256sum) > /stage/source.sha256; '
        '(cd "$dest"; sha256sum -c /stage/source.sha256) > /stage/verified.log; '
        'verified=$(date +%s); '
        'printf "copy_seconds %s\\nverification_seconds %s\\n" "$((copied-started))" "$((verified-copied))"; '
        'sha256sum /stage/source.sha256; '
        'find "$dest" -type f -printf "%s\\n" | awk \'{n++;b+=$1} END {printf "files %d bytes %.0f\\n",n,b}\'; '
        'findmnt -T /stage; touch /stage/verified',
        'stage-snapshot-artifact', run.state['artifact_uid'], timeout=1800)
    (run.path / 'ram-stage.log').write_text(result.stdout + result.stderr)
    # Hash the manifest as well as verifying every file; retain the complete list
    # locally so exact source-copy identity is reviewable after helper deletion.
    hashes = run.k('exec', '-n', 'dynamo-system', name, '-c', 'stage', '--', 'cat', '/stage/source.sha256').stdout
    (run.path / 'artifact-files.sha256').write_text(hashes)
    if 'files 1140 bytes 35871594315' not in result.stdout:
        raise ValueError('Source artifact size/count differs from the qualified checkpoint')
    run.result('ram-staging', 'passed', helper_uid=helper['metadata']['uid'],
               logical_bytes=35871594315, files=1140, staging_log='ram-stage.log',
               scope='All file SHA256 hashes verified; tmpfs copy, not an NVMe measurement')
    print(result.stdout, flush=True)


def artifact_path(run):
    import uuid
    return '/checkpoints/artifacts/' + str(uuid.UUID(run.state['artifact_uid']))


def build_mount_helper(run):
    import hashlib
    import uuid
    source = (ROOT / 'scripts/snapshot_ram_bind.c').read_text()
    # Compile a helper restricted to exactly the recorded artifact, including
    # newer TP2 artifacts; retain the historical helper's narrow target guard.
    artifact_uid = str(uuid.UUID(run.state['artifact_uid']))
    original = '/checkpoints/artifacts/dd493b26-b781-4415-b1f2-090551ae983a'
    if source.count(original) != 1:
        raise ValueError('Mount helper target guard changed')
    source = source.replace(original, '/checkpoints/artifacts/' + artifact_uid)
    if not re.fullmatch(r'[a-z0-9-]+', run.state['run_id']):
        raise ValueError('Unsafe temporary helper directory')
    directory = '/tmp/snapshot-storage-tools-' + run.state['run_id']
    binary = directory + '/ram-bind'
    p = agent(run)
    run.k('exec', '-i', '-n', 'dynamo-system', p['metadata']['name'], '-c', 'agent', '--',
          'sh', '-c', 'set -eu; mkdir -p "$1"; chmod 700 "$1"; '
          'gcc -O2 -Wall -Wextra -Werror -x c - -o "$1/ram-bind"; sha256sum "$1/ram-bind"',
          'build-private-ram-mount-helper', directory, input_text=source, timeout=60)
    run.state['mount_helper'] = binary
    run.state['mount_helper_source_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    run.save()
    return binary


def restore_efs_view(run):
    result = execute(run, 'set -eu; path="$1"; '
                     'if mountpoint -q "$path"; then '
                     'test "$(findmnt -n -o FSTYPE -T "$path")" = tmpfs; umount "$path"; fi; '
                     'test "$(findmnt -n -o FSTYPE -T "$path")" = nfs4; findmnt -T "$path"',
                     artifact_path(run))
    (run.path / f'efs-mount-{time.time_ns()}.log').write_text(result.stdout)
    run.state['ram_overlay'] = False
    run.save()


def mount_ram_view(run):
    helper = run.get('get', 'pod', run.state['helper_name'], '-n', 'dynamo-system')
    owned(run, helper)
    if helper['metadata']['uid'] != run.state['helper_uid']:
        raise ValueError('RAM helper identity changed')
    # The agent's kubelet-pods bind has no HostToContainer propagation, so a
    # newly created emptyDir submount is reached through the host's mount view.
    # hostPID is already enabled on the installed privileged agent. Do not
    # change its volume propagation or mount anything in the host namespace.
    source = '/proc/1/root/var/lib/kubelet/pods/' + helper['metadata']['uid'] + '/volumes/kubernetes.io~empty-dir/staging/artifact'
    run.state['ram_overlay'] = True  # Save cleanup intent before the mutation.
    run.save()
    result = execute(run, 'set -eu; source="$1"; target="$2"; '
                     'test "$(findmnt -n -o PROPAGATION -T /checkpoints)" = private; '
                     'test "$(stat -f -c %T "$source")" = tmpfs; '
                     'test -f "${source%/artifact}/verified"; '
                     '! mountpoint -q "$target"; '
                     '"$3" "$source" "$target"; findmnt -T "$target"; '
                     'test "$(findmnt -n -o FSTYPE -T "$target")" = tmpfs', source, artifact_path(run), run.state['mount_helper'])
    (run.path / 'ram-artifact-mount.log').write_text(result.stdout + result.stderr)


def restored_manifest(run, name):
    original = json.loads((SOURCE_RUN / 'snapshot-restored-pod.json').read_text())
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': run.ns,
        'labels': {**original['metadata']['labels'], **labels(run)},
        'annotations': {'nvidia.com/restore-from': json.loads((run.path / 'source-snapshot.json').read_text())['metadata']['name']}},
        'spec': copy.deepcopy(original['spec'])}
    pod['metadata']['labels'].pop('pod-template-hash', None)
    spec = pod['spec']
    spec.pop('nodeName', None)
    spec.pop('serviceAccount', None)
    spec['restartPolicy'] = 'Never'
    spec['activeDeadlineSeconds'] = 900
    spec['volumes'] = [v for v in spec['volumes'] if not v['name'].startswith('kube-api-access-')]
    for container in spec['containers']:
        container['volumeMounts'] = [m for m in container['volumeMounts'] if not m['name'].startswith('kube-api-access-')]
    return pod


def go_seconds(value):
    multipliers = {'h': 3600, 'm': 60, 's': 1, 'ms': 1e-3, 'µs': 1e-6, 'ns': 1e-9}
    parts = re.findall(r'([0-9]+(?:\.[0-9]+)?)(ns|µs|ms|s|m|h)', value)
    if ''.join(n + unit for n, unit in parts) != value:
        raise ValueError('Unrecognized Go duration: ' + value)
    return sum(float(n) * multipliers[unit] for n, unit in parts)


def delete_worker(run, name):
    found = run.k('get', 'pod', name, '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
        run.k('delete', 'pod', name, '-n', run.ns, '--wait=true', '--timeout=150s', timeout=170)
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)


def restore_one(run, mode, iteration):
    from serving_tests import frontend
    from shadow_failover_tests import completion
    from snapshot_diagnostics import collect_resources
    name = f'ft-snapshot-storage-{mode}-{iteration}-{run.state["comparison_attempt"]}'
    pod = restored_manifest(run, name)
    dump(run, f'{name}-manifest.json', pod)
    run.state.setdefault('workers', []).append(name)
    run.save()
    try:
        run.apply([pod])
        deadline = time.monotonic() + 600
        observe_at = time.monotonic()
        last = None
        while time.monotonic() < deadline:
            current = run.get('get', 'pod', name, '-n', run.ns)
            status = current.get('status', {})
            conditions = {c['type']: c for c in status.get('conditions', [])}
            state = (status.get('phase'), conditions.get('nvidia.com/Restored', {}).get('status'),
                     conditions.get('Ready', {}).get('status'))
            if state != last:
                print(json.dumps({'pod': name, 'state': state}), flush=True)
                last = state
            if status.get('phase') == 'Failed' or conditions.get('nvidia.com/Restored', {}).get('reason') == 'RestoreFailed':
                raise RuntimeError('Restore failed: ' + json.dumps(status))
            if conditions.get('nvidia.com/Restored', {}).get('status') == 'True' and conditions.get('Ready', {}).get('status') == 'True':
                break
            if time.monotonic() >= observe_at:
                collect_resources(run)
                observed = execute(run, 'ps -eo pid,ppid,stat,etime,wchan:32,comm | awk \'NR == 1 || /criu/\'; '
                                   'for pid in $(pgrep -x criu); do echo "PID $pid"; cat /proc/$pid/io; '
                                   'tail -12 /proc/$pid/root/var/criu-work/restore.log 2>/dev/null || true; done', check=False)
                (run.path / f'{name}-progress-{time.time_ns()}.log').write_text(observed.stdout + observed.stderr)
                observe_at = time.monotonic() + 25
            time.sleep(3)
        else:
            raise TimeoutError('Restore/readiness did not complete within 600s')
        dump(run, f'{name}-restored-pod.json', current)
        original = json.loads((SOURCE_RUN / 'snapshot-restored-pod.json').read_text())
        if current['metadata']['uid'] in (original['metadata']['uid'], json.loads((run.path / 'source-content.json').read_text())['spec']['source']['podRef']['uid']):
            raise ValueError('Restore did not create a new Pod UID')
        for container in current['status']['containerStatuses']:
            if container.get('restartCount') or 'sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d' not in container.get('imageID', ''):
                raise ValueError('Restart or changed workload image')
        p = agent(run)
        logs = run.k('logs', p['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--timestamps', '--tail=1200').stdout
        (run.path / f'{name}-agent.log').write_text(logs)
        summaries = [json.loads(line[line.index('{'):]) for line in logs.splitlines()
                     if 'Restore timing summary' in line and f'{run.ns}/{name}' in line]
        if len(summaries) != 1 or summaries[0]['content_uid'] != run.state['artifact_uid']:
            raise ValueError('Expected one matching agent restore summary')
        summary = summaries[0]['restore']
        created = dt.datetime.fromisoformat(current['metadata']['creationTimestamp'].replace('Z', '+00:00'))
        elapsed = lambda c: (dt.datetime.fromisoformat(c['lastTransitionTime'].replace('Z', '+00:00')) - created).total_seconds()
        record = {'mode': mode, 'iteration': iteration, 'pod': name, 'pod_uid': current['metadata']['uid'],
                  'content_uid': run.state['artifact_uid'], 'agent_restore_seconds': go_seconds(summary['duration']),
                  'phases_seconds': {k: go_seconds(v) for k, v in summary['phases'].items()},
                  'pod_creation_to_restored_seconds': elapsed(conditions['nvidia.com/Restored']),
                  'pod_creation_to_ready_seconds': elapsed(conditions['Ready']),
                  'inference': 'pending', 'agent_summary': summaries[0]}
        dump(run, f'{name}-measurement.json', record)
        with frontend(run, 'snapshot') as base:
            response = completion(base, 'nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4', timeout=60)
        dump(run, f'{name}-inference.json', response)
        record.update(inference='passed', worker_id=response['worker'])
        dump(run, f'{name}-measurement.json', record)
        run.state.setdefault('comparison_measurements', []).append(record)
        run.save()
        print(json.dumps(record, indent=2), flush=True)
    finally:
        result = run.k('logs', name, '-n', run.ns, '--tail=400', check=False)
        (run.path / f'{name}-worker.log').write_text(result.stdout + result.stderr)
        delete_worker(run, name)


def cleanup(run):
    adopt_namespace(run)
    for name in set(run.state.get('workers', [])):
        delete_worker(run, name)
    restore_efs_view(run)
    found = run.k('get', 'service', 'ft-snapshot-storage-worker', '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
        run.k('delete', 'service', 'ft-snapshot-storage-worker', '-n', run.ns, '--wait=true', '--timeout=60s')
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    if run.state.get('frontend_planned'):
        found = run.k('get', 'dgd', 'ft-snapshot', '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0:
            owned(run, json.loads(found.stdout))
            run.k('delete', 'dgd', 'ft-snapshot', '-n', run.ns, '--wait=true', '--timeout=90s', timeout=110)
        elif 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
    if run.state.get('helper_name'):
        found = run.k('get', 'pod', run.state['helper_name'], '-n', 'dynamo-system', '-o', 'json', check=False)
        if found.returncode == 0:
            owned(run, json.loads(found.stdout))
            run.k('delete', 'pod', run.state['helper_name'], '-n', 'dynamo-system', '--wait=true', '--timeout=120s', timeout=140)
        elif 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
    if run.state.get('mount_helper'):
        directory = '/tmp/snapshot-storage-tools-' + run.state['run_id']
        if run.state['mount_helper'] != directory + '/ram-bind' or Path(run.state['run_id']).name != run.state['run_id']:
            raise ValueError('Unexpected temporary mount helper path')
        execute(run, 'set -eu; rm -f "$1/ram-bind"; if test -d "$1"; then rmdir "$1"; fi', directory)
    after = agent(run)
    before = json.loads((run.path / 'agent-before.json').read_text())
    dump(run, 'agent-after.json', after)
    if after['spec'] != before['spec']:
        raise ValueError('Shared Snapshot agent specification changed during the comparison')
    nodes = run.get('get', 'nodes')
    dump(run, 'nodes-after.json', nodes)
    if not all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions']) for n in nodes['items']):
        raise ValueError('A cluster node is not Ready after cleanup')
    pods = run.get('get', 'pods', '-A')
    dump(run, 'pods-after.json', pods)
    if any(p['metadata'].get('labels', {}).get('snapshot-storage-experiment') == run.state['run_id']
           and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in pods['items']):
        raise ValueError('An active experiment Pod remains after cleanup')
    source = json.loads((run.path / 'source-snapshot.json').read_text())
    retained = run.get('get', 'podsnapshot', source['metadata']['name'], '-n', run.ns)
    dump(run, 'source-snapshot-after.json', retained)
    if (retained['metadata']['uid'] != source['metadata']['uid']
            or retained['status']['boundSnapshotContentName'] != source['status']['boundSnapshotContentName']
            or not any(c['type'] == 'Ready' and c['status'] == 'True' for c in retained['status']['conditions'])):
        raise ValueError('Retained source snapshot identity/readiness changed')
    run.result('storage-comparison-cleanup', 'passed', scope='EFS view restored; owned worker/frontend/RAM helper removed; disks unmodified')


def compare(run):
    if run.state.get('checks', {}).get('storage-comparison', {}).get('status') == 'passed':
        raise ValueError('Completed comparison: use a fresh --run directory for another test')
    adopt_namespace(run)
    run.state['comparison_attempt'] = str(time.time_ns())[-8:]
    run.save()
    try:
        if run.state.get('checks', {}).get('ram-mount-probe', {}).get('status') != 'passed':
            raise ValueError('Pass the one-byte private RAM mount probe before copying/restoring')
        if not run.state.get('mount_helper'):
            raise ValueError('No reviewed temporary mount helper')
        restore_efs_view(run)
        if not any(m['mode'] == 'efs' and m['iteration'] == 1 and m['inference'] == 'passed'
                   for m in run.state.get('comparison_measurements', [])):
            restore_one(run, 'efs', 1)
        mount_ram_view(run)
        try:
            restore_one(run, 'ram', 1)
        finally:
            restore_efs_view(run)
        restore_one(run, 'efs', 2)
        run.result('storage-comparison', 'passed', measurements=run.state['comparison_measurements'],
                   scope='Single RAM-backed control bracketed by EFS restores; no NVMe performance claim')
    finally:
        cleanup(run)


def progress(run):
    name = run.state.get('helper_name')
    if not name:
        raise ValueError('No RAM helper planned')
    helper = run.get('get', 'pod', name, '-n', 'dynamo-system')
    owned(run, helper)
    result = run.k('exec', '-n', 'dynamo-system', name, '-c', 'stage', '--', 'sh', '-c',
                   'ps -eo pid,ppid,stat,etime,wchan:32,comm; '
                   'find /stage/artifact -type f -printf "%s\\n" | '
                   'awk \'{n++;b+=$1} END {printf "staged_files %d staged_bytes %.0f\\n",n,b}\'; '
                   'wc -l /stage/source.sha256 /stage/verified.log 2>/dev/null || true; '
                   'echo "Memory current / peak / events"; '
                   'cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events', check=False)
    (run.path / f'ram-progress-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)


def worker_status(run):
    adopt_namespace(run)
    for name in set(run.state.get('workers', [])):
        found = run.k('get', 'pod', name, '-n', run.ns, '-o', 'json', check=False)
        if found.returncode:
            if 'NotFound' in found.stderr:
                continue
            raise RuntimeError(found.stderr)
        pod = json.loads(found.stdout)
        owned(run, pod)
        dump(run, f'{name}-status-{time.time_ns()}.json', pod)
        logs = run.k('logs', name, '-n', run.ns, '--timestamps', '--tail=200', check=False)
        (run.path / f'{name}-status-{time.time_ns()}.log').write_text(logs.stdout + logs.stderr)
        print(json.dumps({'pod': name, 'conditions': pod.get('status', {}).get('conditions', []),
                          'logs_tail': logs.stdout.splitlines()[-30:]}, indent=2), flush=True)
    for pod in run.get('get', 'pods', '-n', run.ns)['items']:
        if pod['metadata'].get('labels', {}).get('nvidia.com/dynamo-component-type') != 'frontend':
            continue
        name = pod['metadata']['name']
        dump(run, f'{name}-status-{time.time_ns()}.json', pod)
        logs = run.k('logs', name, '-n', run.ns, '--timestamps', '--tail=120', check=False)
        (run.path / f'{name}-status-{time.time_ns()}.log').write_text(logs.stdout + logs.stderr)
        print(json.dumps({'frontend': name,
            'namespace_environment': [e for e in pod['spec']['containers'][0].get('env', []) if e['name'].startswith('DYN_NAMESPACE')],
            'logs_tail': logs.stdout.splitlines()[-8:]}, indent=2), flush=True)


def agent_logs(run):
    p = agent(run)
    result = run.k('logs', p['metadata']['name'], '-n', 'dynamo-system', '-c', 'agent', '--timestamps', '--tail=1200')
    (run.path / f'agent-observation-{time.time_ns()}.log').write_text(result.stdout)
    for line in result.stdout.splitlines():
        if 'Restore timing summary' in line and run.state['artifact_uid'] in line:
            print(line, flush=True)


def mount_probe(run):
    # Exercise a one-byte RAM mount first, without copying the checkpoint or
    # overlaying the real artifact. A successful helper can be reused by prepare.
    pod = json.loads((run.path / 'ram-helper-manifest.json').read_text())
    name = pod['metadata']['name']
    found = run.k('get', 'pod', name, '-n', 'dynamo-system', '-o', 'json', check=False)
    if found.returncode == 0:
        owned(run, json.loads(found.stdout))
    else:
        if 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
        run.k('create', '--dry-run=server', '-f', '-', input_text=json.dumps(pod))
        run.k('create', '-f', '-', input_text=json.dumps(pod))
    run.k('wait', '--for=condition=Ready', 'pod/' + name, '-n', 'dynamo-system', '--timeout=180s', timeout=200)
    helper = run.get('get', 'pod', name, '-n', 'dynamo-system')
    run.state['helper_uid'] = helper['metadata']['uid']
    run.save()
    run.k('exec', name, '-n', 'dynamo-system', '-c', 'stage', '--', 'sh', '-c',
          'set -eu; mkdir -p /stage/probe; printf x > /stage/probe/marker')
    source = '/proc/1/root/var/lib/kubelet/pods/' + helper['metadata']['uid'] + '/volumes/kubernetes.io~empty-dir/staging/probe'
    target = '/tmp/snapshot-ram-probe-' + run.state['run_id']
    binary = build_mount_helper(run)
    result = execute(run, 'set -eu; source="$1"; target="$2"; '
        'mkdir -p "$target"; trap \'mountpoint -q "$target" && umount "$target"; rmdir "$target"\' EXIT; '
        'echo "Source filesystem"; stat -f -c %T "$source"; '
        '"$3" "$source" "$target"; '
        'test "$(cat "$target/marker")" = x; '
        'test "$(findmnt -n -o FSTYPE -T "$target")" = tmpfs; '
        'findmnt -T "$target"', source, target, binary, check=False)
    (run.path / f'ram-mount-probe-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    run.result('ram-mount-probe', 'passed', scope='One-byte tmpfs bind in private agent namespace; automatically unmounted')


def report(run):
    measurements = run.state.get('comparison_measurements', [])
    rows = []
    for item in measurements:
        phases = item['phases_seconds']
        rows.append(f'| {item["mode"].upper()} {item["iteration"]} | {phases["criu_restore"]:.3f} | '
                    f'{phases["cuda_restore"]:.3f} | {item["agent_restore_seconds"]:.3f} | '
                    f'{item["pod_creation_to_ready_seconds"]:.0f} | {item["inference"]} |')
    cleanup_status = run.state.get('checks', {}).get('storage-comparison-cleanup', {}).get('status', 'not verified')
    body = '# Snapshot same-artifact EFS / RAM comparison\n\n'
    body += f'Updated {dt.datetime.now(dt.timezone.utc).isoformat()}. Cleanup: **{cleanup_status}**.\n\n'
    body += ('The user declined NVMe formatting and approved a RAM-backed control. No disk was '
             'formatted. The test reused Snapshot 0.1.0, the same pinned common workload image, '
             'the Nemotron model/revision, cp-0124 and TP1 worker resource requests/limits. '
             'The original 33.41 GiB artifact was copied into a disposable tmpfs volume; '
             'every file SHA256 was checked against EFS. This is not an NVMe performance result.\n\n')
    body += ('| Restore | CRIU seconds | CUDA seconds | Agent total seconds | Pod → Ready seconds | Fresh inference |\n'
             '| --- | ---: | ---: | ---: | ---: | --- |\n' + '\n'.join(rows) + '\n\n')
    if (run.path / 'ram-stage.log').exists():
        stage = (run.path / 'ram-stage.log').read_text()
        for key in ('copy_seconds', 'verification_seconds'):
            found = re.search(r'^' + key + r' (\d+)$', stage, re.M)
            if found:
                body += f'{key.replace("_", " ").capitalize()}: **{found[1]}** (excluded from restore measurements).\n\n'
    efs = [m for m in measurements if m['mode'] == 'efs']
    ram = [m for m in measurements if m['mode'] == 'ram']
    if efs and ram:
        mean_efs = sum(m['agent_restore_seconds'] for m in efs) / len(efs)
        mean_criu = sum(m['phases_seconds']['criu_restore'] for m in efs) / len(efs)
        body += (f'Mean observed EFS agent restore: **{mean_efs:.3f}s**; RAM control: '
                 f'**{ram[0]["agent_restore_seconds"]:.3f}s**, '
                 f'**{mean_efs / ram[0]["agent_restore_seconds"]:.2f}×** faster. '
                 'This is a bounded storage control, not a concurrency/cold-cache benchmark or '
                 'a guaranteed production startup time. Pre-staging costs and memory reservation remain separate.\n\n')
        body += (f'CRIU fell from **{mean_criu:.3f}s** on EFS to '
                 f'**{ram[0]["phases_seconds"]["criu_restore"]:.3f}s** in RAM. '
                 'The EFS process samples show NFS RPC waits while reading memory pages. '
                 'This control establishes the EFS read path as the dominant delay for this artifact; '
                 'it does not identify an EFS service throughput cap, exhausted credits or a specific NFS/TLS bottleneck. '
                 'Copying the checkpoint again for every Pod would repay the EFS read cost. '
                 'Startup acceleration therefore needs pre-staging and a reusable node cache, '
                 'or faster artifact storage, rather than per-Pod copying.\n\n')
    body += ('During the RAM restore, only the selected artifact path was bound read-only to tmpfs '
             'inside the existing agent\'s private mount namespace. The EFS contents, Helm release, '
             'agent specification, PVC and persistent host storage configuration were preserved. '
             'A narrow checked-in C helper uses the same detached-mount APIs as Snapshot 0.1.0. '
             'It enters the source namespace only to clone the tmpfs subtree, then returns '
             'to the agent namespace before attaching it read-only. No mount is attached in the host namespace. '
             'Only the disposable helper\'s ordinary Kubernetes tmpfs volume adds a temporary host mount. '
             'Direct CRIU image I/O '
             'was retained and no system-wide cache flush was used.\n\n'
             'The sequential worker restores use one GPU at a time. The CPU-only staging helper '
             'requests 2 CPU / 48 GiB RAM, limits RAM to 64 GiB and uses a 48 GiB tmpfs volume.\n\n'
             'Reusable commands:\n\n```sh\n'
             'RUN=results/<fresh-storage-comparison>\n'
             '.local/venv/bin/python scripts/snapshot_storage_compare.py inspect --run "$RUN"\n'
             '.local/venv/bin/python scripts/snapshot_storage_compare.py prepare-ram --run "$RUN"\n'
             '.local/venv/bin/python scripts/snapshot_storage_compare.py compare --run "$RUN"\n'
             '# compare cleans up automatically; cleanup is also available after interruption.\n'
             '.local/venv/bin/python scripts/snapshot_storage_compare.py cleanup --run "$RUN"\n'
             '.local/venv/bin/python scripts/snapshot_storage_compare.py report --run "$RUN"\n'
             '```\n\nEvidence: `results/20261013-snapshot-storage-compare/`, including '
             '`artifact-files.sha256`, the source API objects, per-Pod manifests, phase summaries '
             'and fresh inference responses.\n')
    body += ('\nAn initial harness attempt completed EFS restore but had no worker discovery Service '
             'for EndpointSlices, so fresh inference failed. Its evidence is retained and excluded '
             'from the passed comparison. A subsequent EFS baseline passed inference; a legacy '
             'cross-namespace bind then failed before the RAM restore started. One-byte probes '
             'validated the detached-mount method before the final control. The passed EFS baseline '
             'was reused, and the final EFS repeat follows the RAM result.\n')
    destination = ROOT / 'reports/2026-10-13-snapshot-storage-comparison.md'
    destination.write_text(body)
    print(str(destination), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'disks', 'plan', 'prepare-ram', 'compare', 'cleanup', 'progress', 'worker-status', 'agent-logs', 'mount-probe', 'report'))
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'prepare-ram':
        try:
            prepare(run)
        except BaseException:
            try:
                cleanup(run)
            except Exception as exc:
                run.result('storage-comparison-cleanup', 'failed', reason=str(exc))
            raise
    else:
        {'inspect': inspect, 'disks': disks, 'plan': plan, 'compare': compare,
         'cleanup': cleanup, 'progress': progress, 'worker-status': worker_status,
         'agent-logs': agent_logs, 'mount-probe': mount_probe, 'report': report}[args.action](run)


if __name__ == '__main__':
    main()
