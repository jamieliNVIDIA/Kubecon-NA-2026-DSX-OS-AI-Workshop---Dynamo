#!/usr/bin/env python3
"""Stage one DGD checkpoint on prepared NVMe and expose it in the private agent.

No disk is formatted or mounted here. The reviewed filesystem and agent must
already exist. Staging happens while the capture helper still owns its GPUs;
there is deliberately no global-idle or legacy native-workload prerequisite.
The caller keeps its GPU lease until DGD cleanup and this module's cleanup pass.
"""
import hashlib
import json
import datetime as dt
from pathlib import Path, PurePosixPath
import re
import time
import uuid

import snapshot_tp2_nvme_compare as nvme
from snapshot_storage_compare import agent, artifact_path, execute


KEY = 'workshop_snapshot_nvme'
MANIFEST = 'nvme-artifact-files.sha256'
BASELINE = 'nvme-agent-before.json'
MIN_FREE_MARGIN = 64 * 1024 * 1024


def require_lease(run):
    # Lazy import: the DGD harness imports this module for its pre-release hook.
    from demos.snapshot.dgd import require_lease as check
    check(run)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def spec_digest(pod):
    return digest(json.dumps(pod['spec'], sort_keys=True, separators=(',', ':')).encode())


def write_json(run, name, value):
    (run.path / name).write_text(json.dumps(value, indent=2) + '\n')


def save_record(run, record):
    # Run.save merges and deep-copies state; a prior local dict reference is
    # detached afterwards. Reattach this module's current record every time.
    run.state[KEY] = record
    run.save()


def safe_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected a canonical immutable UUID')
    return value


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', value):
        raise ValueError('Unsafe Kubernetes resource name')
    return value


def validate_run(run):
    identifier = run.state.get('run_id')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', identifier):
        raise ValueError('Unsafe NVMe run identifier')
    if run.state.get('snapshot_dgd_node', nvme.NODE) != nvme.NODE:
        raise ValueError('NVMe staging is restricted to the prepared node')
    safe_name(run.ns)


def ready(obj):
    return any(item.get('type') == 'Ready' and item.get('status') == 'True'
               for item in obj.get('status', {}).get('conditions', []))


def source_identity(run, snapshot, content):
    """Pure validation: no lease, cluster queries, file writes, or mutations."""
    validate_run(run)
    sm, cm = snapshot['metadata'], content['metadata']
    name, namespace = safe_name(sm['name']), safe_name(sm['namespace'])
    content_name = safe_name(cm['name'])
    snapshot_uid, content_uid = safe_uuid(sm['uid']), safe_uuid(cm['uid'])
    source = content['spec']['source']
    if (namespace != run.ns or sm.get('deletionTimestamp') or cm.get('deletionTimestamp')
            or not ready(snapshot) or not ready(content)
            or snapshot['status'].get('boundSnapshotContentName') != content_name
            or content['spec'].get('snapshotRef') != {'name': name, 'namespace': namespace, 'uid': snapshot_uid}
            or source.get('nodeName') != nvme.NODE or content['spec'].get('storage') is not None
            or source.get('podRef', {}).get('containers') != ['main']):
        raise ValueError('Snapshot/content binding, readiness, node, or filesystem storage differs')
    source_uid = safe_uuid(source['podRef']['uid'])
    identity = {'snapshot_name': name, 'snapshot_namespace': namespace, 'snapshot_uid': snapshot_uid,
                'content_name': content_name, 'artifact_uid': content_uid, 'source_pod_uid': source_uid,
                'source_pod_name': safe_name(source['podRef']['name']),
                'node': nvme.NODE, 'filesystem_uuid': nvme.UUID, 'disk_serial': nvme.SERIAL}
    previous = run.state.get(KEY, {}).get('source')
    if previous is not None and previous != identity:
        raise ValueError('NVMe source artifact identity changed')
    if run.state.get('artifact_uid') not in (None, content_uid):
        raise ValueError('Run already names a different artifact UID')
    return identity


def validate_saved_paths(run, artifact_uid=None):
    """Reject corrupted ownership paths before copying or changing a mount."""
    validate_run(run)
    helper = '/tmp/snapshot-nvme-tools-' + run.state['run_id'] + '/nvme-bind'
    if run.state.get('nvme_mount_helper') not in (None, helper):
        raise ValueError('Refusing an unexpected NVMe helper path')
    record = run.state.get(KEY, {})
    if artifact_uid is None:
        if any(run.state.get(k) is not None for k in ('nvme_staging_target', 'nvme_partial')) or any(
                record.get(k) is not None for k in ('target', 'partial')):
            raise ValueError('Saved NVMe paths lack an artifact identity')
        return
    target = '/proc/1/root/mnt/dynamo-snapshot/artifacts/' + safe_uuid(artifact_uid)
    partial = target + '.partial-' + run.state['run_id']
    for value, expected in ((run.state.get('nvme_staging_target'), target),
                            (run.state.get('nvme_partial'), partial),
                            (record.get('target'), target), (record.get('partial'), partial)):
        if value not in (None, expected):
            raise ValueError('Saved NVMe staging path differs from this artifact')


def validate_live_source(run, identity):
    snapshot = run.get('get', 'podsnapshot', identity['snapshot_name'], '-n', run.ns)
    content = run.get('get', 'podsnapshotcontent', identity['content_name'])
    if source_identity(run, snapshot, content) != identity:
        raise ValueError('Live Snapshot/content identity changed')


def initial_capture_gate(run, identity):
    """Require the source helper to fence GPUs until the NVMe view is active."""
    from demos.snapshot.dgd import GRAPH, COMPONENT
    graph = run.get('get', 'dgd', GRAPH, '-n', run.ns)
    entry = graph.get('status', {}).get('checkpoints', {}).get(COMPONENT, {})
    if (not run.state.get('snapshot_dgd_uid')
            or graph['metadata']['uid'] != run.state['snapshot_dgd_uid']
            or graph['metadata'].get('namespace') != run.ns
            or entry.get('checkpointName') != identity['snapshot_name']):
        raise ValueError('DGD checkpoint entry does not own this staging snapshot')
    pod = run.get('get', 'pod', identity['source_pod_name'], '-n', run.ns)
    helper = next((item for item in pod.get('status', {}).get('containerStatuses', [])
                   if item.get('name') == 'capture-keepalive'), {})
    if (pod['metadata']['uid'] != identity['source_pod_uid'] or pod['metadata'].get('deletionTimestamp')
            or pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns
            or pod['spec'].get('nodeName') != nvme.NODE
            or pod.get('status', {}).get('phase') != 'Running'
            or not helper.get('state', {}).get('running')):
        raise ValueError('Exact capture source helper must remain Running during NVMe staging')
    claim_names = {item['resourceClaimName'] for item in pod.get('status', {}).get('resourceClaimStatuses', [])
                   if item.get('resourceClaimName')}
    claim_names.update(item['resourceClaimName'] for item in pod['spec'].get('resourceClaims', [])
                       if item.get('resourceClaimName'))
    claims = run.get('get', 'resourceclaims', '-n', run.ns)['items']
    held = [claim for claim in claims if claim['metadata']['name'] in claim_names
            and claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results')
            and any(item.get('uid') == identity['source_pod_uid']
                    for item in claim.get('status', {}).get('reservedFor', []))]
    if not held:
        raise ValueError('Capture source no longer holds its allocated GPU claim')
    held_names = {claim['metadata']['name'] for claim in held}
    if any(claim['metadata']['name'] not in held_names and claim.get('status', {}).get('allocation')
           for claim in claims):
        raise ValueError('Another GPU claim is allocated before NVMe staging')
    for candidate in run.get('get', 'pods', '-n', run.ns)['items']:
        if candidate['metadata']['uid'] == identity['source_pod_uid']:
            continue
        labels = candidate['metadata'].get('labels', {})
        is_worker = (labels.get('nvidia.com/dynamo-component-type') == 'worker'
                     or labels.get('nvidia.com/dynamo-component') == COMPONENT)
        if is_worker and (candidate.get('status', {}).get('phase') == 'Running'
                          or any(item.get('state', {}).get('running')
                                 for item in candidate.get('status', {}).get('containerStatuses', []))):
            raise ValueError('A serving worker started before NVMe staging')


def checked_agent(run):
    validate_run(run)
    pod = agent(run)
    if pod['spec'].get('nodeName') != nvme.NODE or not ready(pod):
        raise ValueError('Prepared Snapshot agent is not Ready on the expected node')
    for name in ('agent', 'pagebroker'):
        status = next((item for item in pod.get('status', {}).get('containerStatuses', [])
                       if item.get('name') == name), {})
        if not status.get('ready') or status.get('restartCount'):
            raise ValueError('Snapshot agent/PageBroker readiness or restart history changed')
    baseline = run.path / BASELINE
    if baseline.exists():
        previous = json.loads(baseline.read_text())
        if (pod['metadata']['uid'] != previous['metadata']['uid'] or spec_digest(pod) != spec_digest(previous)):
            raise ValueError('Pinned Snapshot agent identity or specification changed')
    return pod


def available_bytes(run):
    # The agent's private mount table cannot resolve a host path reached via
    # /proc/1/root for df. Inspect in its owning namespace, as verify_disk does.
    result = execute(run, 'set -eu; nsenter --target 1 --mount --root=/proc/1/root --wd=/ '
                     '-- df -B1 --output=avail /mnt/dynamo-snapshot')
    if result.returncode:
        raise RuntimeError('Cannot read prepared NVMe available bytes')
    rows = [line.strip() for line in result.stdout.splitlines()]
    if len(rows) != 2 or rows[0] != 'Avail' or not re.fullmatch(r'\d+', rows[1]):
        raise ValueError('Cannot determine prepared NVMe available bytes')
    return int(rows[1])


def inspect(run):
    """Read-only cluster inspection; locally retain agent/disk identity pins."""
    pod = checked_agent(run)
    nvme.verify_disk(run)
    free = available_bytes(run)
    baseline = run.path / BASELINE
    if not baseline.exists():
        write_json(run, BASELINE, pod)
    record = run.state.setdefault(KEY, {})
    pin = {'uid': pod['metadata']['uid'], 'spec_sha256': spec_digest(pod), 'node': nvme.NODE,
           'filesystem_uuid': nvme.UUID, 'disk_serial': nvme.SERIAL, 'device_bytes': 3800000000000}
    if record.get('agent') not in (None, pin):
        raise ValueError('Saved NVMe agent/disk pin changed')
    record['agent'] = pin
    record['available_bytes_at_inspection'] = free
    run.state['agent_uid'] = pod['metadata']['uid']
    run.state['nvme_filesystem_uuid'] = nvme.UUID
    save_record(run, record)
    write_json(run, 'nvme-inspection.json', {**pin, 'available_bytes': free})
    return record


def relative_path(value):
    path = PurePosixPath(value)
    if (not value or value.startswith('/') or str(path) != value
            or any(part in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in path.parts)):
        raise ValueError('Unsafe path inside checkpoint artifact')
    return value


def parse_inventory(text):
    files, directories = {}, set()
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields) != 3 or fields[0] not in ('f', 'd') or not fields[1].isdigit():
            raise ValueError('Invalid checkpoint artifact inventory')
        kind, size, path = fields
        relative_path(path)
        if path in files or path in directories:
            raise ValueError('Duplicate checkpoint artifact entry')
        if kind == 'f':
            files[path] = int(size)
        else:
            if int(size) != 0:
                raise ValueError('Invalid directory inventory size')
            directories.add(path)
    if not files or sum(files.values()) <= 0:
        raise ValueError('Checkpoint artifact has no data files')
    return {'files': files, 'directories': sorted(directories)}


def parse_manifest(text, inventory):
    hashes = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  \./(.+)', line)
        if not match:
            raise ValueError('Invalid checkpoint SHA256 manifest')
        checksum, path = match.groups()
        relative_path(path)
        if path in hashes:
            raise ValueError('Duplicate checkpoint SHA256 entry')
        hashes[path] = checksum
    if set(hashes) != set(inventory['files']):
        raise ValueError('SHA256 manifest does not cover the exact checkpoint inventory')
    return hashes


INVENTORY_SCRIPT = r'''set -eu
test -d "$1"; test ! -L "$1"
test -z "$(find "$1" ! -type d ! -type f -print -quit)"
cd "$1"
LC_ALL=C find . -mindepth 1 -type f -printf 'f\t%s\t%P\n'
LC_ALL=C find . -mindepth 1 -type d -printf 'd\t0\t%P\n'
'''


def inventory(run, path):
    result = execute(run, INVENTORY_SCRIPT, path, timeout=180)
    return parse_inventory(result.stdout)


def path_exists(run, path):
    result = execute(run, 'if test -e "$1" || test -L "$1"; then printf yes; else printf no; fi', path)
    if result.stdout not in ('yes', 'no'):
        raise ValueError('Unexpected artifact path existence result')
    return result.stdout == 'yes'


def mutate(run, script, *args, **kwargs):
    require_lease(run)
    checked_agent(run)
    return execute(run, script, *args, **kwargs)


def verify_local(run, path, expected, manifest):
    if inventory(run, path) != expected:
        raise ValueError('NVMe checkpoint inventory differs from EFS source')
    started = time.monotonic()
    pod = checked_agent(run)
    result = run.k('exec', '-i', '-n', 'dynamo-system', pod['metadata']['name'], '-c', 'agent', '--',
                   'sh', '-c', 'set -eu; cd "$1"; sha256sum -c -', 'verify-dgd-nvme-checkpoint', path,
                   input_text=manifest, timeout=1800)
    lines = result.stdout.splitlines()
    if len(lines) != len(expected['files']) or any(not line.endswith(': OK') for line in lines):
        raise ValueError('Not every NVMe checkpoint file passed checksum verification')
    (run.path / ('nvme-hash-verification-' + str(time.time_ns()) + '.log')).write_text(result.stdout + result.stderr)
    return time.monotonic() - started


def validate_overlay(run):
    result = execute(run, r'''set -eu
test "$(findmnt -n -o PROPAGATION -T /checkpoints)" = private
test "$(findmnt -n -o FSTYPE -T "$1")" = ext4
test "$(findmnt -n -o UUID -T "$1")" = "$2"
mountpoint -q "$1"
options="$(findmnt -n -o OPTIONS -T "$1")"
case ",$options," in *,ro,*) ;; *) exit 1 ;; esac
findmnt -T "$1" -o TARGET,SOURCE,FSTYPE,OPTIONS,UUID
''', artifact_path(run), nvme.UUID)
    (run.path / ('nvme-overlay-verification-' + str(time.time_ns()) + '.log')).write_text(result.stdout)


def saved_material(run):
    record = run.state[KEY]
    expected = json.loads((run.path / 'nvme-source-inventory.json').read_text())
    manifest = (run.path / MANIFEST).read_text()
    parse_manifest(manifest, expected)
    if (digest(manifest.encode()) != record.get('hash_manifest_sha256')
            or len(expected['files']) != record.get('expected_files')
            or sum(expected['files'].values()) != record.get('expected_bytes')):
        raise ValueError('Saved NVMe manifest or inventory changed')
    return expected, manifest


def ensure(run, snapshot, content):
    """Before source release: stage this Ready artifact and select its NVMe view."""
    identity = source_identity(run, snapshot, content)
    validate_saved_paths(run, identity['artifact_uid'])
    validate_live_source(run, identity)
    require_lease(run)
    if KEY not in run.state or not (run.path / BASELINE).exists():
        raise ValueError('Inspect and pin the prepared NVMe agent before staging')
    checked_agent(run)
    nvme.verify_disk(run)
    record = run.state[KEY]
    if not record.get('staged'):
        initial_capture_gate(run, identity)
    record['source'] = identity
    run.state['artifact_uid'] = identity['artifact_uid']
    target = nvme.local_path(run)
    partial = target + '.partial-' + run.state['run_id']
    if record.get('target') not in (None, target) or record.get('partial') not in (None, partial):
        raise ValueError('Saved NVMe staging path differs from the derived artifact path')
    record.update(target=target, partial=partial)
    run.state.update(nvme_staging_target=target, nvme_partial=partial)
    save_record(run, record)

    if not record.get('hash_manifest_sha256'):
        if run.state.get('nvme_overlay'):
            raise ValueError('Cannot hash the EFS source through an existing NVMe overlay')
        source = artifact_path(run)
        execute(run, 'set -eu; test "$(findmnt -n -o FSTYPE -T "$1")" = nfs4; '
                'test "$(findmnt -n -o PROPAGATION -T /checkpoints)" = private', source)
        expected = inventory(run, source)
        expected_bytes = sum(expected['files'].values())
        if available_bytes(run) < expected_bytes + MIN_FREE_MARGIN:
            raise ValueError('Insufficient free space on the prepared NVMe filesystem')
        hash_start = time.monotonic()
        result = execute(run, 'set -eu; cd "$1"; LC_ALL=C find . -type f -print0 | '
                         'LC_ALL=C sort -z | xargs -0 -r sha256sum --', source, timeout=2400)
        manifest = result.stdout
        parse_manifest(manifest, expected)
        if inventory(run, source) != expected:
            raise ValueError('EFS checkpoint inventory changed while hashing')
        for path in (run.path / 'nvme-source-inventory.json', run.path / MANIFEST):
            if path.exists():
                raise ValueError('Refusing to replace incomplete prior NVMe source evidence')
        write_json(run, 'nvme-source-inventory.json', expected)
        (run.path / MANIFEST).write_text(manifest)
        record.update(expected_files=len(expected['files']), expected_bytes=expected_bytes,
                      hash_manifest_sha256=digest(manifest.encode()), source_hash_seconds=time.monotonic() - hash_start)
        run.state.update(expected_files=record['expected_files'], expected_bytes=expected_bytes)
        save_record(run, record)
    expected, manifest = saved_material(run)

    if record.get('staged'):
        # Polling/worker replacement must not reread the entire ~100GB cache.
        # Its full hashes were verified before atomic promotion. An active
        # read-only overlay plus immutable identities is the reuse contract.
        if not run.state.get('nvme_overlay'):
            record['latest_verification_seconds'] = verify_local(run, target, expected, manifest)
    else:
        target_exists, partial_exists = path_exists(run, target), path_exists(run, partial)
        if target_exists and partial_exists:
            raise ValueError('Both final and partial NVMe paths exist; preserve evidence for diagnosis')
        if target_exists:
            if record.get('phase') != 'promote-intent':
                raise ValueError('Refusing to adopt or overwrite an unrecorded NVMe artifact')
            record['verification_seconds'] = verify_local(run, target, expected, manifest)
        else:
            if not partial_exists:
                if record.get('phase'):
                    raise ValueError('Recorded NVMe staging files disappeared; use a fresh diagnosis')
                record['phase'] = 'copy-intent'
                save_record(run, record)
                started = time.monotonic()
                result = mutate(run, r'''set -eu
test "$(findmnt -n -o FSTYPE -T "$1")" = nfs4
test ! -e "$2"; test ! -L "$2"; test ! -e "$3"; test ! -L "$3"
test -d /proc/1/root/mnt/dynamo-snapshot
mkdir -p /proc/1/root/mnt/dynamo-snapshot/artifacts
cp -a "$1" "$3"
sync -f "$3"
''', artifact_path(run), target, partial, timeout=2400)
                (run.path / 'nvme-copy.log').write_text(result.stdout + result.stderr)
                record['copy_seconds'] = time.monotonic() - started
                record['phase'] = 'copied'
                save_record(run, record)
            elif record.get('phase') not in ('copy-intent', 'copied', 'promote-intent'):
                raise ValueError('Refusing an unrecorded partial NVMe artifact')
            record['verification_seconds'] = verify_local(run, partial, expected, manifest)
            record['phase'] = 'promote-intent'
            save_record(run, record)
            mutate(run, 'set -eu; test ! -e "$2"; test ! -L "$2"; '
                   'mv -T -n "$1" "$2"; test ! -e "$1"; sync -f "$2"', partial, target)
        record['staged'] = True
        record['phase'] = 'staged'
        record['staging_complete_at'] = now()
        save_record(run, record)

    validate_live_source(run, identity)
    if run.state.get('nvme_overlay'):
        validate_overlay(run)
    else:
        expected_helper = '/tmp/snapshot-nvme-tools-' + run.state['run_id'] + '/nvme-bind'
        helper = run.state.get('nvme_mount_helper')
        if helper not in (None, expected_helper):
            raise ValueError('Saved NVMe mount helper path changed')
        if helper is None:
            require_lease(run)
            checked_agent(run)
            nvme.build_helper(run)
        require_lease(run)
        checked_agent(run)
        nvme.nvme_view(run)
        validate_overlay(run)
        record['overlay_activated_at'] = now()
    record['overlay_verified'] = True
    save_record(run, record)
    write_json(run, 'nvme-stage-evidence.json', record)
    run.result('snapshot-dgd-nvme-staging', 'passed', **record)
    return record


def cleanup(run):
    """Restore the private EFS view and remove only this run's mount helper."""
    validate_run(run)
    record = run.state.get(KEY, {})
    identity = record.get('source')
    validate_saved_paths(run, identity['artifact_uid'] if identity else run.state.get('artifact_uid'))
    require_lease(run)
    checked_agent(run)
    if identity:
        validate_live_source(run, identity)
        if run.state.get('artifact_uid') != identity['artifact_uid']:
            raise ValueError('Cleanup artifact UID differs from the recorded source')
        if run.state.get('nvme_overlay'):
            validate_overlay(run)
        require_lease(run)
        nvme.efs_view(run)
    helper = run.state.get('nvme_mount_helper')
    if helper:
        expected = '/tmp/snapshot-nvme-tools-' + run.state['run_id'] + '/nvme-bind'
        if helper != expected:
            raise ValueError('Refusing an unexpected NVMe helper cleanup path')
        mutate(run, 'set -eu; rm -f "$1/nvme-bind"; rmdir "$1"', str(PurePosixPath(expected).parent))
        run.state.pop('nvme_mount_helper')
        run.save()
    checked_agent(run)
    if identity:
        validate_live_source(run, identity)
    record['overlay_verified'] = False
    record['cleanup'] = 'EFS view restored; helper removed; NVMe artifact retained'
    save_record(run, record)
    write_json(run, 'nvme-cleanup-evidence.json', record)
    run.result('snapshot-dgd-nvme-cleanup', 'passed', scope=record['cleanup'])
