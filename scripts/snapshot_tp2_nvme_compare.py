#!/usr/bin/env python3
"""Same-artifact EFS/NVMe/NVMe/EFS restore control, without changing shared storage."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import snapshot_tp2_storage_compare as control
from snapshot_storage_compare import agent, artifact_path, dump, execute, owned
from testlib import ROOT, Run

NODE = 'kubecon-nke-site-cp-0124'
UUID = '68d48707-ddd0-4094-b46b-a70255b4d25b'
SERIAL = 'AWS135BFFA82D334433D'
RAM_RUN = ROOT / 'results/20261022-snapshot-tp2-ram-control'
MANIFEST_SHA = '58ebf8c04fc310c3d9a2c924943f7a6f0079ac4fbe4469d8e6177338e314bbea'


def local_path(run):
    return '/proc/1/root/mnt/dynamo-snapshot/artifacts/' + run.state['artifact_uid']


def verify_disk(run):
    result = execute(run, r'''set -eu
nsenter --target 1 --mount --root=/proc/1/root --wd=/ -- sh -c '
set -eu
mountpoint -q /mnt/dynamo-snapshot
test "$(findmnt -n -o UUID -M /mnt/dynamo-snapshot)" = "$1"
test "$(findmnt -n -o FSTYPE -M /mnt/dynamo-snapshot)" = ext4
dev="$(findmnt -n -o SOURCE -M /mnt/dynamo-snapshot)"
test "$(lsblk -dn -o SERIAL "$dev" | xargs)" = "$2"
test "$(blockdev --getsize64 "$dev")" = 3800000000000
findmnt -M /mnt/dynamo-snapshot -o TARGET,SOURCE,FSTYPE,OPTIONS,UUID
df -B1 /mnt/dynamo-snapshot
' nvme-identity "$1" "$2"
''', UUID, SERIAL)
    (run.path / ('nvme-identity-'+str(time.time_ns())+'.log')).write_text(result.stdout)
    print(result.stdout, flush=True)


def inspect(run):
    control.inspect(run)
    verify_disk(run)
    manifest = (RAM_RUN / 'artifact-files.sha256').read_bytes()
    if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA:
        raise ValueError('Qualified artifact hash manifest changed')
    (run.path / 'artifact-files.sha256').write_bytes(manifest)
    run.state['nvme_filesystem_uuid'] = UUID
    run.save()


def stage(run):
    control.source(run);control.idle(run);verify_disk(run)
    if run.state.get('checks', {}).get('nvme-staging', {}).get('status') == 'passed':
        raise ValueError('Artifact already staged; do not overwrite')
    source = artifact_path(run)
    target = local_path(run)
    partial = target + '.partial-' + run.state['run_id']
    if not re.fullmatch('[a-z0-9-]+', run.state['run_id']):
        raise ValueError('Unsafe run identifier')
    run.state['nvme_staging_target'] = target;run.state['nvme_partial'] = partial;run.save()
    result = execute(run, r'''set -eu
source="$1"; target="$2"; partial="$3"
test "$(findmnt -n -o FSTYPE -T "$source")" = nfs4
test "$(stat -f -c %t /proc/1/root/mnt/dynamo-snapshot)" = ef53
test ! -e "$target"; test ! -e "$partial"
mkdir -p /proc/1/root/mnt/dynamo-snapshot/artifacts
started=$(date +%s)
cp -a "$source" "$partial"
sync -f "$partial"
copied=$(date +%s)
printf 'copy_seconds %s\n' "$((copied-started))"
find "$partial" -type f -printf '%s\n' | awk '{n++;b+=$1} END {printf "files %d bytes %.0f\n",n,b}'
''', source, target, partial, timeout=2400)
    (run.path / 'nvme-copy.log').write_text(result.stdout+result.stderr)
    expected = f'files {run.state["expected_files"]} bytes {run.state["expected_bytes"]}'
    if expected not in result.stdout:
        raise ValueError('NVMe copy size/count mismatch')
    manifest = (run.path / 'artifact-files.sha256').read_text()
    if hashlib.sha256(manifest.encode()).hexdigest() != MANIFEST_SHA:
        raise ValueError('Expected hash manifest changed')
    p = agent(run)
    started = time.monotonic()
    verification = run.k('exec', '-i', '-n', control.SYSTEM, p['metadata']['name'], '-c', 'agent', '--',
        'sh', '-c', 'set -eu; cd "$1"; sha256sum -c -', 'verify-owned-nvme-artifact', partial,
        input_text=manifest, timeout=1200)
    elapsed = time.monotonic()-started
    (run.path / 'nvme-hash-verification.log').write_text(verification.stdout+verification.stderr)
    if len(verification.stdout.splitlines()) != run.state['expected_files']:
        raise ValueError('Unexpected checksum verification result count')
    execute(run, 'set -eu; test ! -e "$2"; mv "$1" "$2"; sync -f "$2"', partial, target)
    run.result('nvme-staging', 'passed', files=run.state['expected_files'], logical_bytes=run.state['expected_bytes'],
        hash_manifest_sha256=MANIFEST_SHA, verification_seconds=elapsed,
        copy_seconds=int(re.search(r'copy_seconds (\d+)', result.stdout)[1]), path=target,
        scope='Copy and all file hashes verified against the qualified EFS/RAM manifest; excluded from restore timing')
    print(result.stdout, flush=True)


def build_helper(run):
    source = (ROOT / 'scripts/snapshot_ram_bind.c').read_text()
    start = source.index('static int safe_source(')
    end = source.index('static int safe_target(')
    source = source[:start] + ('static int safe_source(const char *path) {\n'
        f'    return strcmp(path, "{local_path(run)}") == 0;\n}}\n\n') + source[end:]
    source = source.replace('/checkpoints/artifacts/dd493b26-b781-4415-b1f2-090551ae983a', artifact_path(run))
    source = source.replace('source_fs.f_type != TMPFS_MAGIC', 'source_fs.f_type != EXT4_SUPER_MAGIC')
    source = source.replace('tmpfs', 'NVMe ext4')
    directory = '/tmp/snapshot-nvme-tools-' + run.state['run_id']
    p = agent(run)
    run.state['nvme_mount_helper'] = directory+'/nvme-bind';run.save()
    run.k('exec', '-i', '-n', control.SYSTEM, p['metadata']['name'], '-c', 'agent', '--',
        'sh', '-c', 'set -eu; mkdir -p "$1"; chmod 700 "$1"; '
        'gcc -O2 -Wall -Wextra -Werror -x c - -o "$1/nvme-bind"; sha256sum "$1/nvme-bind"',
        'compile-owned-nvme-helper', directory, input_text=source)
    (run.path / 'nvme-bind-effective.c').write_text(source)


def efs_view(run):
    target = artifact_path(run)
    result = execute(run, r'''set -eu
if mountpoint -q "$1"; then
    test "$2" = yes
    test "$(findmnt -n -o FSTYPE -T "$1")" = ext4
    test "$(findmnt -n -o UUID -T "$1")" = "$3"
    umount "$1"
fi
test "$(findmnt -n -o FSTYPE -T "$1")" = nfs4
findmnt -T "$1"
''', target, 'yes' if run.state.get('nvme_overlay') else 'no', UUID)
    (run.path / ('efs-view-'+str(time.time_ns())+'.log')).write_text(result.stdout)
    run.state['nvme_overlay'] = False;run.save()


def nvme_view(run):
    verify_disk(run)
    run.state['nvme_overlay'] = True;run.save()
    result = execute(run, r'''set -eu
test "$(findmnt -n -o PROPAGATION -T /checkpoints)" = private
test "$(findmnt -n -o FSTYPE -T "$2")" = nfs4
! mountpoint -q "$2"
"$3" "$1" "$2"
test "$(findmnt -n -o FSTYPE -T "$2")" = ext4
test "$(findmnt -n -o UUID -T "$2")" = "$4"
findmnt -T "$2" -o TARGET,SOURCE,FSTYPE,OPTIONS,UUID
''', local_path(run), artifact_path(run), run.state['nvme_mount_helper'], UUID)
    (run.path / ('nvme-view-'+str(time.time_ns())+'.log')).write_text(result.stdout)
    print(result.stdout, flush=True)


def cleanup(run):
    for name in run.state.get('workers', []):
        control.delete_worker(run, name)
    if run.state.get('artifact_uid'):
        efs_view(run)
    if run.state.get('nvme_mount_helper'):
        expected = '/tmp/snapshot-nvme-tools-'+run.state['run_id']+'/nvme-bind'
        if run.state['nvme_mount_helper'] != expected:
            raise ValueError('Unexpected helper path')
        execute(run, 'set -eu; rm -f "$1/nvme-bind"; rmdir "$1"', str(Path(expected).parent))
        run.state.pop('nvme_mount_helper');run.save()
    if (run.path / 'agent-before.json').exists():
        p = agent(run);dump(run, 'agent-after.json', p)
        if p['spec'] != json.loads((run.path / 'agent-before.json').read_text())['spec']:
            raise ValueError('Shared agent spec changed')
        control.source(run);control.idle(run);verify_disk(run)
        nodes = run.get('get', 'nodes')
        dump(run, 'nodes-after.json', nodes)
        previous = {n['metadata']['name']: n for n in json.loads((run.path/'nodes-before.json').read_text())['items']}
        for node in nodes['items']:
            old = previous[node['metadata']['name']]
            assert node['status']['nodeInfo']['bootID'] == old['status']['nodeInfo']['bootID']
            assert control.ready(node)
            assert node['status']['allocatable'].get('vpc.amazonaws.com/efa') == old['status']['allocatable'].get('vpc.amazonaws.com/efa')
        run.result('nvme-control-cleanup', 'passed', scope='Owned workers removed; EFS view restored; NVMe checkpoint retained; no Helm/PVC changes')


def compare(run):
    if run.state.get('checks', {}).get('nvme-staging', {}).get('status') != 'passed':
        raise ValueError('Stage and checksum the checkpoint first')
    if run.state.get('checks', {}).get('nvme-comparison', {}).get('status') == 'passed':
        raise ValueError('Completed run; use fresh run for more measurements')
    run.state['attempt_id'] = str(time.time_ns())[-10:];run.save()
    try:
        build_helper(run)
        efs_view(run)
        control.restore_one(run, 'efs', 1)
        nvme_view(run)
        try:
            control.restore_one(run, 'nvme', 1)
            control.restore_one(run, 'nvme', 2)
        finally:
            efs_view(run)
        control.restore_one(run, 'efs', 2)
        run.result('nvme-comparison', 'passed', measurements=run.state['measurements'])
    finally:
        cleanup(run)


def stage_progress(run):
    verify_disk(run)
    result = execute(run, r'''set -eu
for path in "$1" "$2"; do
    if test -d "$path"; then
        printf 'Staging path: %s\n' "$path"
        find "$path" -type f -printf '%s\n' | awk '{n++;b+=$1} END {printf "files %d bytes %.0f\n",n,b}'
    fi
done
ps -eo pid,stat,etime,comm | awk 'NR == 1 || $4 ~ /^(cp|sha256sum)$/'
''', run.state.get('nvme_partial', local_path(run)+'.not-started'), local_path(run))
    (run.path / ('staging-progress-'+str(time.time_ns())+'.log')).write_text(result.stdout)
    print(result.stdout, flush=True)


def diskstats(run):
    import datetime as dt
    verify_disk(run)
    result = execute(run, 'cat /sys/class/block/nvme0n1/stat')
    record = {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'values': [int(v) for v in result.stdout.split()], 'device': 'nvme0n1',
        'measurements_completed': len(run.state.get('measurements', []))}
    run.state.setdefault('nvme_diskstats_observations', []).append(record);run.save()
    dump(run, 'nvme-diskstats-'+str(time.time_ns())+'.json', record)
    print(json.dumps(record, indent=2), flush=True)


def summarize(run):
    import statistics
    checks = run.state.get('checks', {})
    if any(checks.get(name, {}).get('status') != 'passed'
           for name in ('nvme-comparison', 'nvme-control-cleanup')):
        raise ValueError('Needs completed comparison and cleanup')
    measurements = run.state['measurements']
    groups = {}
    for mode in ('efs', 'nvme'):
        values = [m for m in measurements if m['mode'] == mode]
        if len(values) != 2:
            raise ValueError('Expected two distinct qualified trials per storage')
        groups[mode] = {
            'trials': len(values),
            'agent_mean_seconds': statistics.mean(v['agent_seconds'] for v in values),
            'agent_min_seconds': min(v['agent_seconds'] for v in values),
            'agent_max_seconds': max(v['agent_seconds'] for v in values),
            'pod_to_ready_mean_seconds': statistics.mean(v['pod_to_ready_seconds'] for v in values),
            'phase_means_seconds': {k: statistics.mean(v['phases'][k] for v in values)
                                   for k in values[0]['phases']}}
    ram_state = json.loads((RAM_RUN/'state.json').read_text())
    ram = [v for v in ram_state['measurements'] if v['mode'] == 'ram']
    if len(ram) != 1 or ram[0]['content_uid'] != run.state['artifact_uid']:
        raise ValueError('Historical RAM control artifact differs')
    groups['historical_ram'] = {'trials': 1, 'agent_mean_seconds': ram[0]['agent_seconds'],
        'pod_to_ready_mean_seconds': ram[0]['pod_to_ready_seconds'],
        'phase_means_seconds': ram[0]['phases'], 'source_run': str(RAM_RUN.relative_to(ROOT))}
    efs = groups['efs']['agent_mean_seconds']; nvme = groups['nvme']['agent_mean_seconds']
    summary = {'content_uid': run.state['artifact_uid'], 'logical_bytes': run.state['expected_bytes'],
        'groups': groups, 'nvme_speedup_over_efs': efs/nvme,
        'nvme_reduction_percent': (1-nvme/efs)*100, 'nvme_saved_seconds': efs-nvme,
        'staging': checks['nvme-staging'], 'measurements': measurements,
        'scope': 'Same artifact and actual GPU pair; direct CRIU I/O; no global cache flush; staging excluded; RAM is earlier control'}
    observations = run.state.get('nvme_diskstats_observations', [])
    if len(observations) >= 2:
        first, last = observations[0], observations[-1]
        delta = (last['values'][2]-first['values'][2])*512
        if delta < 0.9*2*run.state['expected_bytes']:
            raise ValueError('Observed SSD reads do not establish two artifact-sized reads')
        summary['nvme_device_read_evidence'] = {'device': first['device'],
            'read_bytes_delta': delta, 'observations': observations,
            'scope': 'Observed after staging and before NVMe trials through after both NVMe trials; no other test SSD workload'}
    dump(run, 'nvme-comparison-analysis.json', summary)
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'stage', 'compare', 'cleanup', 'progress', 'stage-progress', 'summarize', 'diskstats'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args();run = Run(args.run)
    if args.action == 'progress':
        control.progress(run)
    else:
        globals()[args.action.replace('-', '_')](run)


if __name__ == '__main__':
    main()
