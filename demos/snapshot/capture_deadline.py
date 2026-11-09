"""Extend only this presenter's owned capture Jobs from one hour to two hours.

This is an offstage workload policy, not a shared operator change. Every write
has UID/resourceVersion tests and a server dry-run. Failure stops the caller;
there is no automatic conflict retry or replacement/capture replay.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
GRAPH, COMPONENT = 'ft-snapshot', 'VllmSnapshotWorker'
OWNER = 'kubecon-dynamo-feature-tests'
ORIGINAL, TARGET = 3600, 7200
POLICY = 'capture-deadline-policy.json'
RECEIPTS = 'capture-deadline-receipts'


class NotCreatedYet(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def metadata(obj, namespace, name=None):
    value = obj['metadata']
    if (value.get('namespace') != namespace or not value.get('uid') or not value.get('resourceVersion')
            or value.get('deletionTimestamp') or (name is not None and value.get('name') != name)):
        raise ValueError('Changed, deleting or incomplete resource identity.')
    return value


def terminal(obj):
    return any(c.get('status') == 'True' and c.get('type') in
               ('Failed', 'FailureTarget', 'Complete', 'Completed')
               for c in obj.get('status', {}).get('conditions', []))


def validate(state, graph, snapshot, source, pods):
    """Pure ownership/deadline checks, run before any server dry-run or write."""
    namespace = state['namespace']
    gm = metadata(graph, namespace, GRAPH)
    if (gm['uid'] != state.get('snapshot_dgd_uid') or
            gm.get('labels', {}).get('feature-test-run') != namespace or
            gm.get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER or
            graph.get('status', {}).get('state') == 'failed'):
        raise ValueError('Creating DGD ownership or state differs.')
    name = graph.get('status', {}).get('checkpoints', {}).get(COMPONENT, {}).get('checkpointName')
    if not name:
        raise NotCreatedYet('DGD has no capture Job name yet.')
    sm = metadata(snapshot, namespace, name)
    labels = sm.get('labels', {})
    controlled = any(o.get('kind') == 'DynamoGraphDeployment' and o.get('uid') == gm['uid']
                     for o in sm.get('ownerReferences', []))
    if (labels.get('nvidia.com/dynamo-component') != COMPONENT or
            labels.get('nvidia.com/dynamo-graph-deployment-name') != GRAPH or
            (sm.get('annotations', {}).get('nvidia.com/dynamo-checkpoint-owner-uid') != gm['uid'] and not controlled) or
            (state.get('snapshot_job_uid') not in (None, sm['uid']))):
        raise ValueError('SnapshotJob is not owned by the recorded creating DGD/component.')
    jm = metadata(source, namespace)
    owners = [o for o in jm.get('ownerReferences', []) if o.get('controller')]
    jl = jm.get('labels', {})
    if (snapshot.get('status', {}).get('sourceJobUID') != jm['uid'] or len(owners) != 1 or
            owners[0].get('kind') != 'SnapshotJob' or owners[0].get('uid') != sm['uid'] or
            owners[0].get('name') != sm['name'] or
            jl.get('feature-test-run') != namespace or jl.get('app.kubernetes.io/managed-by') != OWNER or
            jl.get('nvidia.com/dynamo-component') != COMPONENT or
            jl.get('nvidia.com/dynamo-graph-deployment-name') != GRAPH or
            jl.get('nvidia.com/snapshot-job-uid') != sm['uid'] or
            jl.get('nvidia.com/snapshot-job') != sm['name']):
        raise ValueError('Source Job UID/ownership differs from this SnapshotJob.')
    for obj in (snapshot, source):
        if terminal(obj):
            raise ValueError('Refusing a terminal capture/source Job.')
        if obj['spec'].get('activeDeadlineSeconds') not in (ORIGINAL, TARGET):
            raise ValueError('Unexpected capture/source Job deadline; only3600→7200 is permitted.')
    limits = []
    for kind, spec in (('SnapshotJob capture template', snapshot['spec'].get('podTemplate', {}).get('spec', {})),
                       ('source Job Pod template', source['spec'].get('template', {}).get('spec', {}))):
        limits.append({'location': kind, 'activeDeadlineSeconds': spec.get('activeDeadlineSeconds')})
    owned_pods = []
    for pod in pods:
        pm = pod['metadata']
        refs = [o for o in pm.get('ownerReferences', []) if o.get('controller')]
        mentioned = (pm.get('labels', {}).get('batch.kubernetes.io/controller-uid') == jm['uid'] or
                     any(o.get('uid') == jm['uid'] for o in refs))
        if not mentioned:
            continue
        metadata(pod, namespace)
        if (len(refs) != 1 or refs[0].get('kind') != 'Job' or refs[0].get('uid') != jm['uid'] or
                pm.get('labels', {}).get('feature-test-run') != namespace or
                pm.get('labels', {}).get('nvidia.com/snapshot-job-uid') != sm['uid'] or
                pod.get('status', {}).get('phase') in ('Failed', 'Succeeded')):
            raise ValueError('Source Pod has conflicting ownership or is terminal.')
        owned_pods.append(pod)
        limits.append({'location': 'source Pod/' + pm['name'], 'uid': pm['uid'],
                       'activeDeadlineSeconds': pod['spec'].get('activeDeadlineSeconds')})
    if not owned_pods:
        raise NotCreatedYet('Wait for the source Pod so its actual deadline is checked.')
    if len(owned_pods) != 1:
        raise ValueError('Expected one exact source Pod; refuse ambiguous capture ownership.')
    if any(limit['activeDeadlineSeconds'] is not None and limit['activeDeadlineSeconds'] < TARGET for limit in limits):
        raise ValueError('A source Pod/template has a shorter deadline; report it and do not patch it: ' + json.dumps(limits))
    return {'dgd_uid': gm['uid'], 'snapshot_job_uid': sm['uid'], 'source_job_uid': jm['uid'],
            'source_pod_uids': sorted(p['metadata']['uid'] for p in owned_pods), 'pod_deadlines': limits}


def deadline_patch(obj):
    """An already-owned7200s resource is accepted without another mutation."""
    value = obj['spec']['activeDeadlineSeconds']
    if value == TARGET:
        return None
    if value != ORIGINAL:
        raise ValueError('Unexpected deadline.')
    return [{'op': 'test', 'path': '/metadata/uid', 'value': obj['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']},
            {'op': 'test', 'path': '/spec/activeDeadlineSeconds', 'value': ORIGINAL},
            {'op': 'replace', 'path': '/spec/activeDeadlineSeconds', 'value': TARGET}]


def confirm_only_deadline(before, after):
    if any(before['metadata'][k] != after['metadata'][k] for k in ('uid', 'name', 'namespace')):
        raise ValueError('Patch changed resource identity.')
    expected = copy.deepcopy(before['spec'])
    expected['activeDeadlineSeconds'] = TARGET
    if after['spec'] != expected:
        raise ValueError('Server admission changed fields beyond the approved Job lifetime.')


class Client:
    def __init__(self, run):
        self.run = Path(run).resolve()
        self.folder = self.run / RECEIPTS
        self.folder.mkdir(exist_ok=True)
        self.base = [str(ROOT / '.local/bin/kubectl'), '--kubeconfig=' + str(ROOT / '.local/kubeconfig'),
                     '--request-timeout=20s']

    def command(self, name, args):
        started = now()
        try:
            result = subprocess.run(self.base + args, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired as error:
            def output(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            result = subprocess.CompletedProcess(self.base + args, 124, output(error.stdout), output(error.stderr))
        receipt = {'at': started, 'args': self.base + args, 'exit_code': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr}
        path = self.folder / (str(time.time_ns()) + '-' + name + '.json')
        write(path, receipt)
        if result.returncode:
            raise RuntimeError('Capture lifetime command rejected; no automatic retry: ' + result.stderr[-2000:])
        return json.loads(result.stdout)

    def bundle(self, state):
        namespace = state['namespace']
        graph = self.command('get-dgd', ['get', 'dgd', GRAPH, '-n', namespace, '-o', 'json'])
        name = graph.get('status', {}).get('checkpoints', {}).get(COMPONENT, {}).get('checkpointName')
        if not name:
            raise NotCreatedYet('DGD checkpoint entry not created yet.')
        jobs = self.command('get-capture-jobs', ['get', 'snapshotjobs,jobs,pods', '-n', namespace, '-o', 'json'])['items']
        snapshots = [x for x in jobs if x['kind'] == 'SnapshotJob' and x['metadata']['name'] == name]
        if len(snapshots) != 1:
            raise NotCreatedYet('SnapshotJob not created yet.')
        snapshot = snapshots[0]
        source_uid = snapshot.get('status', {}).get('sourceJobUID')
        sources = [x for x in jobs if x['kind'] == 'Job' and x['metadata']['uid'] == source_uid]
        if len(sources) != 1:
            if terminal(snapshot):
                raise ValueError('Capture Job became terminal before lifetime policy.')
            raise NotCreatedYet('Source Job identity not published yet.')
        return graph, snapshot, sources[0], [x for x in jobs if x['kind'] == 'Pod']

    def patch(self, kind, before, patch, *, dry_run):
        args = ['patch', kind, before['metadata']['name'], '-n', before['metadata']['namespace'],
                '--type=json', '-p', json.dumps(patch), '-o', 'json']
        if dry_run:
            args.append('--dry-run=server')
        return self.command(('dry-run-' if dry_run else 'patch-') + kind, args)


def require_lease(run):
    owner = json.loads((ROOT / '.local/workshop-measurements-20261030.gpu-lease/owner.json').read_text())
    if owner.get('agent') != 'workshop-snapshot-dgd' or owner.get('run') != str(Path(run).resolve()):
        raise ValueError('Exact Snapshot run must own its reservation before any deadline mutation.')


def apply_policy(run, state, bundle, client, policy):
    """Two individually guarded writes; a partial failure stays explicitly failed."""
    identity = validate(state, *bundle)
    policy.update(status='applying', identity=identity, initial_bundle_sha256=sha(bundle))
    write(Path(run) / 'capture-deadline-before.json', {'graph': bundle[0], 'snapshot_job': bundle[1],
        'source_job': bundle[2], 'pods': bundle[3]})
    write(Path(run) / POLICY, policy)
    for kind, index in (('snapshotjob', 1), ('job', 2)):
        if policy['changes']:
            bundle = client.bundle(state)
            if validate(state, *bundle) != identity:
                raise ValueError('Capture ownership or Pod identities changed between guarded writes.')
        require_lease(run)
        before = bundle[index]
        patch = deadline_patch(before)
        change = {'kind': kind, 'name': before['metadata']['name'], 'uid': before['metadata']['uid'],
                  'before_resource_version': before['metadata']['resourceVersion'],
                  'before_sha256': sha(before), 'before_spec_sha256': sha(before['spec']),
                  'before_deadline': before['spec']['activeDeadlineSeconds'], 'json_patch': patch}
        if patch:
            dry = client.patch(kind, before, patch, dry_run=True)
            confirm_only_deadline(before, dry)
            change['dry_run_sha256'] = sha(dry)
            after = client.patch(kind, before, patch, dry_run=False)
            confirm_only_deadline(before, after)
            change['status'] = 'patched'
        else:
            after = before
            change['status'] = 'already_7200'
        change.update(after_resource_version=after['metadata']['resourceVersion'], after_sha256=sha(after),
                      after_spec_sha256=sha(after['spec']), after_deadline=after['spec']['activeDeadlineSeconds'],
                      spec_diff={'/spec/activeDeadlineSeconds': {'before': before['spec']['activeDeadlineSeconds'], 'after': TARGET}})
        policy['changes'].append(change)
        write(Path(run) / POLICY, policy)
    final = client.bundle(state)
    if validate(state, *final) != identity or any(x['spec']['activeDeadlineSeconds'] != TARGET for x in final[1:3]):
        raise ValueError('Final Job lifetime/identity verification differs.')
    write(Path(run) / 'capture-deadline-after.json', {'graph': final[0], 'snapshot_job': final[1],
        'source_job': final[2], 'pods': final[3]})
    policy.update(status='passed', finished_at=now(), final_bundle_sha256=sha(final))
    write(Path(run) / POLICY, policy)
    return policy


def watch(run, *, timeout=900, stop_event=None):
    run = Path(run).resolve()
    if (run / POLICY).exists():
        raise ValueError('A lifetime-policy attempt already exists; inspect it rather than silently retrying.')
    policy = {'schema': 1, 'status': 'waiting', 'started_at': now(), 'run': str(run), 'original_seconds': ORIGINAL,
        'target_seconds': TARGET, 'changes': [], 'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'object_hash_encoding': 'SHA256 of sorted compact UTF-8 JSON; helper hash is raw source bytes',
        'scope': 'Only this creating DGD/component SnapshotJob and its exact source batch Job. No engine settings, source Pod deadlines or shared platform changes.'}
    write(run / POLICY, policy)
    client = Client(run)
    stop_event = stop_event or threading.Event()
    until = time.monotonic() + timeout
    try:
        while time.monotonic() < until:
            if stop_event.is_set():
                raise RuntimeError('Prime observer ended before lifetime policy completed.')
            state = json.loads((run / 'state.json').read_text())
            if state.get('snapshot_dgd_uid'):
                require_lease(run)
                try:
                    bundle = client.bundle(state)
                    validate(state, *bundle)
                except NotCreatedYet:
                    pass
                else:
                    # Discovery may wait for initial objects. Once writes start,
                    # disappearance or conflict is a failed partial attempt,
                    # never a reason to retry and overwrite its before evidence.
                    return apply_policy(run, state, bundle, client, policy)
            stop_event.wait(2)
        raise TimeoutError('Capture/source Job identity did not become inspectable within the lifetime-policy watch window.')
    except BaseException as error:
        policy.update(status='failed', finished_at=now(), error=str(error))
        write(run / POLICY, policy)
        raise
