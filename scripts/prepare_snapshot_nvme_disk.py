#!/usr/bin/env python3
"""Inspect, explicitly initialize, mount and verify one approved Snapshot NVMe SSD.

No Kubernetes storage objects, Helm values, fstab or node services are changed.
The host mount is deliberately runtime-only; inspect it again before every test.
"""
import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

from snapshot_storage_compare import agent, execute
from testlib import Run

NODE = 'kubecon-nke-site-cp-0124'
SERIAL = 'AWS135BFFA82D334433D'
SIZE = 3800000000000
MOUNT = '/mnt/dynamo-snapshot'
LABEL = 'dyn-snap-demo'

HOST_SCRIPT = r'''
set -eu
mode="$1"
expected_uuid="$2"
expected_machine="$3"
test "$(cat /etc/machine-id)" = "$expected_machine"
exec 9>/run/lock/dynamo-snapshot-nvme.lock
flock -n 9
# Discover by immutable serial; never assume an NVMe enumeration number.
dev=''
for serial_file in /sys/class/block/nvme*n1/device/serial; do
    test -f "$serial_file" || continue
    if test "$(tr -d '[:space:]' < "$serial_file")" = AWS135BFFA82D334433D; then
        test -z "$dev"
        block_dir="${serial_file%/device/serial}"
        dev="/dev/${block_dir##*/}"
    fi
done
test -n "$dev"
test -b "$dev"
test "$(lsblk -dn -o MODEL "$dev" | xargs)" = 'Amazon EC2 NVMe Instance Storage'
test "$(blockdev --getsize64 "$dev")" = 3800000000000
test "$(blockdev --getro "$dev")" = 0
printf 'Verified candidate: %s\n' "$dev"
lsblk -J -b -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL "$dev"
# No partitions, stacked devices, root backing, swap or device holders.
test "$(lsblk -nr -o NAME "$dev" | wc -l)" -eq 1
test -z "$(ls -A "/sys/class/block/${dev##*/}/holders")"
root_source="$(findmnt -n -o SOURCE /)"
if lsblk -s -nr -o NAME "$root_source" | awk '{print "/dev/"$1}' | grep -Fx "$dev"; then
    echo 'Refusing root backing device' >&2; exit 1
fi
if swapon --show=NAME --noheadings | grep -Fx "$dev"; then
    echo 'Refusing swap device' >&2; exit 1
fi
command -v mkfs.ext4 blkid wipefs findmnt mount mountpoint sha256sum dd sync
printf 'Signatures:\n'
wipefs --no-act "$dev"
if test "$mode" = inspect; then
    printf 'Host target directory:\n'
    ls -ld /mnt/dynamo-snapshot 2>/dev/null || true
    findmnt -rn -M /mnt/dynamo-snapshot || true
    printf 'Existing boot configuration references:\n'
    grep -nE 'dynamo-snapshot|AWS135BFFA82D334433D' /etc/fstab || true
    exit 0
fi
if test "$mode" = initialize; then
    test -n "$expected_uuid"
    # Fail closed on any recognized filesystem/partition signature or mount.
    test -z "$(lsblk -nro MOUNTPOINTS "$dev" | tr -d '[:space:]')"
    if findmnt -rn -S "$dev"; then echo 'Device is mounted' >&2; exit 1; fi
    test -z "$(wipefs --no-act --noheadings --output TYPE "$dev")"
    if blkid -p "$dev"; then
        echo 'Existing signature: refusing initialization' >&2; exit 1
    else
        test "$?" = 2
    fi
    # No -F/force or discard. Fully initialize metadata before timing any tests.
    mkfs.ext4 -U "$expected_uuid" -L dyn-snap-demo -m 0 -T largefile \
        -E nodiscard,lazy_itable_init=0,lazy_journal_init=0 "$dev"
    sync -f "$dev"
    test "$(blkid -s UUID -o value "$dev")" = "$expected_uuid"
    test "$(blkid -s TYPE -o value "$dev")" = ext4
    blkid "$dev"
    exit 0
fi
test "$mode" = mount || test "$mode" = verify
test -n "$expected_uuid"
test "$(blkid -s UUID -o value "$dev")" = "$expected_uuid"
test "$(blkid -s TYPE -o value "$dev")" = ext4
test "$(blkid -s LABEL -o value "$dev")" = dyn-snap-demo
if test "$mode" = mount && ! mountpoint -q /mnt/dynamo-snapshot; then
    test ! -L /mnt/dynamo-snapshot
    mkdir -p /mnt/dynamo-snapshot
    test -z "$(ls -A /mnt/dynamo-snapshot)"
    mount -t ext4 -o noatime "/dev/disk/by-uuid/$expected_uuid" /mnt/dynamo-snapshot
fi
mountpoint -q /mnt/dynamo-snapshot
test "$(findmnt -n -o UUID -M /mnt/dynamo-snapshot)" = "$expected_uuid"
test "$(findmnt -n -o FSTYPE -M /mnt/dynamo-snapshot)" = ext4
findmnt -M /mnt/dynamo-snapshot -o TARGET,SOURCE,FSTYPE,OPTIONS,UUID
df -B1 /mnt/dynamo-snapshot
if test "$mode" = verify; then
    probe="$(mktemp -d /mnt/dynamo-snapshot/.workshop-nvme-check.XXXXXX)"
    trap 'rm -f "$probe/probe.bin" "$probe.expected"; rmdir "$probe"' EXIT
    dd if=/dev/urandom of="$probe/probe.bin" bs=1048576 count=4 conv=fsync status=none
    sha256sum "$probe/probe.bin" > "$probe.expected"
    # Read through direct I/O, then compare without retaining a test artifact.
    actual="$(dd if="$probe/probe.bin" bs=1048576 iflag=direct status=none | sha256sum | cut -d ' ' -f1)"
    expected="$(cut -d ' ' -f1 "$probe.expected")"
    rm "$probe.expected"
    test "$actual" = "$expected"
    printf '4 MiB fsync/direct-read checksum verification passed: %s\n' "$actual"
fi
'''


def host(run, mode):
    p = agent(run)
    if not p['spec'].get('hostPID'):
        raise ValueError('Existing Snapshot agent does not use hostPID')
    if p['spec']['nodeName'] != NODE:
        raise ValueError('Wrong Snapshot node')
    node = run.get('get', 'node', NODE)
    machine = node['status']['nodeInfo']['machineID']
    run.state.setdefault('nvme_node_before', node)
    run.state.setdefault('nvme_agent_before', p)
    run.save()
    result = execute(run,
        'exec nsenter --target 1 --mount --root=/proc/1/root --wd=/ -- /bin/sh -c "$1" nvme-disk "$2" "$3" "$4"',
        HOST_SCRIPT, mode, run.state.get('nvme_filesystem_uuid', ''), machine,
        timeout=240 if mode == 'initialize' else 60)
    (run.path / f'nvme-{mode}-{dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")}.log').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)
    run.state[f'nvme_{mode}_completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    run.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'initialize', 'mount', 'verify'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--approved-serial', choices=[SERIAL])
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'initialize':
        if args.approved_serial != SERIAL:
            parser.error('Initialization requires explicit user authorization and --approved-serial')
        if run.state.get('nvme_initialize_completed_at'):
            raise ValueError('Already initialized in this run; do not reformat')
        run.state.setdefault('nvme_filesystem_uuid', str(uuid.uuid4()))
        run.state['nvme_initialization_authorization'] = {
            'user_request': 'ok can we prep the disk on one node to test it out',
            'explicit_confirmation': 'yes, authorized',
            'confirmation_scope': 'Format the single 3.8 TB SSD as ext4 and mount at /mnt/dynamo-snapshot',
            'scope': f'One instance SSD serial {SERIAL} on {NODE}',
            'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        run.save()
    if args.action in ('mount', 'verify') and not run.state.get('nvme_filesystem_uuid'):
        raise ValueError('Use the initializing run with its recorded filesystem UUID')
    host(run, args.action)
    if args.action == 'verify':
        node = run.get('get', 'node', NODE)
        before = run.state['nvme_node_before']
        assert node['status']['nodeInfo']['bootID'] == before['status']['nodeInfo']['bootID']
        assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions'])
        p = agent(run)
        assert p['metadata']['uid'] == run.state['nvme_agent_before']['metadata']['uid']
        assert p['spec'] == run.state['nvme_agent_before']['spec']
        efs = execute(run, 'set -eu; test "$(findmnt -n -o FSTYPE -T /checkpoints)" = nfs4; findmnt -T /checkpoints')
        (run.path / 'efs-still-active.log').write_text(efs.stdout + efs.stderr)
        (run.path / 'node-after.json').write_text(json.dumps(node, indent=2)+'\n')
        (run.path / 'agent-after.json').write_text(json.dumps(p, indent=2)+'\n')
        run.result('nvme-disk-preparation', 'passed', node=NODE, serial=SERIAL,
                   filesystem_uuid=run.state['nvme_filesystem_uuid'], mount=MOUNT,
                   mount_persistence='Runtime only; no boot configuration changes',
                   snapshot_storage='EFS unchanged; no Helm or PV/PVC changes')


if __name__ == '__main__':
    main()
