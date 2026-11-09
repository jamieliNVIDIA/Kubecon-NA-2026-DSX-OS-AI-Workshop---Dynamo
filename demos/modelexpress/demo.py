#!/usr/bin/env python3
"""Add a peer-loaded replica using the running first demo as its source."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

import yaml

import demos.common.runtime as ui
from demos.common import dependencies, weights
from demos.common.allocation import physical_gpus
from demos.common.weights import worker_config, engine_signature
from demos.common.presentation import prose
from demos.modelexpress import source as source_binding

ROOT = ui.ROOT
TARGET_GRAPH = 'demo-mx-target'
OWNER = 'workshop-demo-modelexpress'  # Only retained for cleanup of older isolated runs.
PROFILE = 'mx-intro-source-text-only-eager-v1'
DEFAULT_TARGET_NODE = 'kubecon-nke-site-cp-0198'
STEPS = [
    ('Discover peer weights', 'The first replica already publishes its weights; the new worker discovers its source Service.'),
    ('Start a new worker', 'Load peer weights over NIXL/EFA, then compare the first and second startups.'),
    ('Follow the weight transfer', 'Check both TP ranks, the transport, and whether loading fell back to storage.'),
    ('Use the new worker', 'Send a request through the destination frontend.'),
]
SAMPLE_PEER_LOG = '''ILLUSTRATIVE REHEARSAL LOG — NO GPU TRANSFER IN THIS RUN
Backend LIBFABRIC was instantiated
Created rails using provider=efa
(Worker_TP0) Receiving 1869 tensors from source (P2P)
(Worker_TP0) Transfer complete: 1869 tensors, 40.27 GB in 3.33s
(Worker_TP1) Receiving 1869 tensors from source (P2P)
(Worker_TP1) Transfer complete: 1869 tensors, 40.27 GB in 4.42s
'''


def render(namespace, lock, arm='peer', *, node=None):
    if arm != 'peer':
        raise ValueError('ModelExpress reuses the first replica; only a peer target is rendered.')
    graph, claim = ui.render(namespace, lock)
    weights.configure(graph, lock, role='target')
    graph['metadata']['name'] = TARGET_GRAPH
    claim['metadata']['name'] = TARGET_GRAPH + '-gpus'
    target_node = node or DEFAULT_TARGET_NODE
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        pod['metadata']['labels']['workshop-arm'] = 'peer'
        pod['metadata']['labels']['workshop-demo'] = 'modelexpress'
        if component['type'] == 'worker':
            pod['spec']['nodeSelector'] = {'kubernetes.io/hostname': target_node}
            pod['spec']['resourceClaims'][0]['resourceClaimTemplateName'] = claim['metadata']['name']
    if ui.ALLOCATION is not None:
        ui.ALLOCATION.pin(graph, claim, 'peer')
    return graph, claim


def transfer_receipts(logs):
    result = {}
    pattern = r'Transfer complete: (\d+) tensors, ([0-9.]+) GB in ([0-9.]+)s'
    for line in logs.splitlines():
        rank = re.search(r'Worker_TP(\d+)', line)
        transfer = re.search(pattern, line)
        if rank and transfer:
            value = {'rank': int(rank[1]), 'tensors': int(transfer[1]),
                     'gigabytes': float(transfer[2]), 'seconds': float(transfer[3])}
            if value['rank'] in result and result[value['rank']] != value:
                raise RuntimeError('Multiple distinct transfer receipts for one TP rank; inspect the target log.')
            result[value['rank']] = value
    return result


def verify_peer(logs, tp):
    if re.search(r'Trying strategy:\s*default|falling back to (?:the )?(?:default|disk|storage)', logs, re.I):
        raise RuntimeError('Target fell back to storage; this is not a peer-loading demonstration.')
    expected = set(range(tp))
    received = {int(rank) for rank in re.findall(r'Worker_TP(\d+).*Receiving \d+ tensors from source \(P2P\)', logs)}
    transfers = transfer_receipts(logs)
    if set(transfers) != expected or received != expected:
        raise RuntimeError(f'Peer loading is not proven on every rank: received={received}, completed={set(transfers)}')
    if 'Backend LIBFABRIC was instantiated' not in logs or 'provider=efa' not in logs:
        raise RuntimeError('The expected NIXL LIBFABRIC/EFA transfer path was not observed.')
    if any(value['tensors'] <= 0 or value['gigabytes'] <= 1 for value in transfers.values()):
        raise RuntimeError('Weight transfer receipts are empty or unexpectedly small.')
    return {'transfers': [transfers[r] for r in sorted(transfers)], 'backend': 'LIBFABRIC', 'provider': 'efa',
            'gigabytes_total': sum(v['gigabytes'] for v in transfers.values()),
            'slowest_rank_copy_seconds': max(v['seconds'] for v in transfers.values())}


def transfer_summary(proof):
    """Audience-facing lines for the transfer step; peer-proof.json keeps the Pod, claim and GPU identities."""
    if not proof['transfers']:
        return [proof['note']]
    lines = [f'TP{t["rank"]}: {t["gigabytes"]:.2f} GB in {t["seconds"]:.2f}s' for t in proof['transfers']]
    lines.append(f'NIXL {proof["backend"]} over {proof["provider"].upper()}, '
                 f'{proof["source"]["node"]} -> {proof["target_node"]}; no fallback to storage.')
    return lines


def comparison(storage, peer):
    for key in ('engine_signature', 'source_uid', 'simulated'):
        if storage[key] != peer[key]:
            raise RuntimeError('The two startup records differ in ' + key)
    if storage['worker_uid'] != peer['source_uid']:
        raise RuntimeError('The first replica is not the recorded peer source.')
    if storage['node'] == peer['node']:
        raise RuntimeError('The peer target must run on a different node from the first replica.')
    first, second = storage['ready_seconds'], peer['ready_seconds']
    ratio = (first / second if first is not None and second is not None and first > 0 and second > 0 else None)
    return {'simulated': storage['simulated'], 'storage': storage, 'peer': peer,
            'observed_readiness_ratio': ratio,
            'scope': 'Observed first and second startups on different nodes with the same model and engine settings. '
                     'Checkpoint staged on EFS; page caches and source traffic are uncontrolled.'}


class ModelExpressDemo(ui.Demo):
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        args = copy.copy(args)
        if args.run is None:
            args.run = ROOT / 'results' / ('demo-02-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        existed = (args.run / 'demo.json').exists()
        offline = args.rehearsal or args.preview or args.action == 'preview'
        binding = None
        if not existed and not offline:
            binding = source_binding.snapshot(getattr(args, 'source_run', None) or ui.current_run())
        super().__init__(args)
        self.compact_output = True
        self.legacy = self.data.get('mx_profile') != PROFILE if existed else False
        if existed:
            if self.legacy:
                if args.action == 'cleanup':
                    return
                raise ValueError('This MX run used the old isolated-source flow. Prepare a fresh run from an MX-enabled first replica.')
            if getattr(args, 'source_run', None) and str(args.source_run.resolve()) != self.data['source_binding']['run']:
                raise ValueError('The bound first replica changed; use a fresh MX run.')
            self.check_inputs()
            return
        self.data.update(mx_profile=PROFILE, demo_kind='modelexpress', arms={}, arm_intents={},
                         source_binding=binding, graph=TARGET_GRAPH)
        if binding is not None:
            self.ns = binding['namespace']
            self.run.ns = self.ns
            self.run.state['namespace'] = self.ns
            self.run.save()
            self.data['namespace'] = self.ns
            baseline = binding['baseline']
        else:
            baseline = {'simulated': args.rehearsal, 'worker_uid': 'simulated-source',
                        'source_uid': 'simulated-source', 'node': 'kubecon-nke-site-cp-0124',
                        'ready_seconds': None, 'model_loading_seconds': None, 'engine_init_seconds': None}
        node = getattr(args, 'target_node', None)
        if node is None:
            node = ('kubecon-nke-site-cp-0124' if baseline['node'] == DEFAULT_TARGET_NODE
                    else DEFAULT_TARGET_NODE)
        graph, claim = render(self.ns, ui.read_json(ui.MODEL_LOCK), node=node)
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        node = worker['podTemplate']['spec']['nodeSelector']['kubernetes.io/hostname']
        if node == baseline['node']:
            raise ValueError('Choose --target-node on a different node from the first replica.')
        self.data['target_node'] = node
        token = hashlib.sha256(str(self.path).encode()).hexdigest()[:12]
        self.data.update(target_token=token, pod_selector='workshop-mx-run=' + token, active_arm='peer')
        labels = {**self.run.labels(), 'workshop-mx-run': token}
        graph['metadata']['labels'] = labels
        claim['metadata']['labels'] = labels
        for component in graph['spec']['components']:
            component['podTemplate']['metadata']['labels']['workshop-mx-run'] = token
        for name, obj in (('peer.yaml', graph), ('deployment.yaml', graph), ('gpu-claim-template.yaml', claim)):
            (self.path / name).write_text(yaml.safe_dump(obj, sort_keys=False))
        if binding is None:
            baseline['engine_signature'] = engine_signature(graph)
        if baseline['engine_signature'] != engine_signature(graph):
            raise ValueError('The first replica and target have different model or engine settings; prepare a compatible first replica.')
        self.data['arms']['storage'] = baseline
        ui.write_json(self.path / 'source-binding.json', binding)
        self.data['manifest_sha256'] = ui.digest(self.path / 'deployment.yaml')
        self.data['claim_sha256'] = ui.digest(self.path / 'gpu-claim-template.yaml')
        self.data['mx_inputs'] = {name: ui.digest(self.path / name) for name in
                                 ('peer.yaml', 'deployment.yaml', 'gpu-claim-template.yaml', 'source-binding.json')}
        config = worker_config(graph)
        settings = {'args': ['--load-format', 'modelexpress'],
                    'env': [e for e in config['env'] if e['name'] in {
                        'MX_METADATA_BACKEND', 'MX_K8S_SERVICE_PATTERN', 'MX_NIXL_BACKEND', 'MX_ARTIFACT_TRANSFER'}]}
        (self.path / 'modelexpress-settings.yaml').write_text(
            '# Already enabled on the first replica; the new worker uses the same loader.\n' +
            yaml.safe_dump(settings, sort_keys=False))
        self.save()

    def check_inputs(self):
        for name, expected in self.data['mx_inputs'].items():
            if ui.digest(self.path / name) != expected:
                raise ValueError('A prepared MX input changed: ' + name + '. Use a fresh demo run.')
        if self.data.get('source_binding'):
            frozen = ui.read_json(self.path / 'source-binding.json')
            if (self.data['source_binding'] != frozen or
                    self.data['arms']['storage'] != frozen['baseline']):
                raise ValueError('The recorded first-replica binding changed; prepare a fresh MX run.')
            source_binding.validate_files(self.data['source_binding'])
        self.check_manifests()

    @property
    def source_path(self):
        binding = self.data.get('source_binding')
        if binding is None:
            raise RuntimeError('This preview has no live first replica. Prepare a fresh MX run after completing demo 1.')
        return Path(binding['run'])

    def source_identity(self):
        if self.args.rehearsal:
            return {'uid': 'simulated-source', 'node': self.data['arms']['storage']['node']}
        if not ui.lease_owned(self.source_path):
            raise RuntimeError('The first replica no longer owns its GPU reservation; inspect it before continuing.')
        live = source_binding.identity(self.run, self.data['source_binding'])
        recorded = self.data.get('source_identity')
        if recorded is not None and live != recorded:
            raise RuntimeError('The first replica or its GPU/source identity changed. Prepare a fresh MX run.')
        if recorded is None:
            self.data['source_identity'] = live
            self.save()
        return live

    def prepare(self):
        self.check_inputs()
        if self.args.rehearsal:
            print('[REHEARSAL] First replica and its storage startup are simulated; no cluster commands.')
        else:
            with dependencies.parent_lock(self.source_path):
                self.source_identity()
                dependencies.register(self.source_path, self.path)
                if not self.data.get('mx_prepared'):
                    self.run.apply([yaml.safe_load((self.path / 'gpu-claim-template.yaml').read_text())])
                    for kind in ('client', 'server'):
                        self.run.k('apply', '--dry-run=' + kind, '-f', str(self.path / 'peer.yaml'))
            print('Reusing the running first replica and its recorded storage startup. No extra source or baseline is launched.')
        self.data.update(prepared=True, mx_prepared=True)
        self.save()

    def prime(self):
        # Kept for existing presenter scripts; source loading already happened in demo 1.
        self.prepare()

    def target_graph(self):
        result = self.run.k('get', 'dgd', TARGET_GRAPH, '-n', self.ns, '-o', 'json', check=False)
        if result.returncode:
            if 'NotFound' in result.stderr:
                return None
            raise RuntimeError('Cannot inspect the peer target; preserve it for diagnosis.')
        graph = json.loads(result.stdout)
        labels = graph['metadata'].get('labels', {})
        if (labels.get('feature-test-run') != self.ns or
                labels.get('workshop-mx-run') != self.data['target_token']):
            raise RuntimeError('The peer graph belongs to another run; preserve it for diagnosis.')
        expected = self.data.get('target_graph_uid')
        if expected and graph['metadata']['uid'] != expected:
            raise RuntimeError('The peer graph was replaced; preserve it for diagnosis.')
        return graph

    def start_arm(self, arm='peer'):
        if arm != 'peer':
            raise ValueError('Demo 1 already supplied the storage startup; only the peer target may be started.')
        self.check_inputs()
        self.source_identity()
        if 'peer' in self.data['arms']:
            self.check_peer_identity()
            return self.data['arms']['peer']
        if 'peer' not in self.data['arm_intents']:
            self.show_command(self.run.kbase + ['apply', '-f', str(self.path / 'peer.yaml')])
            if self.args.rehearsal:
                self.data['apply_started_at'] = ui.now()
                self.data['arm_intents']['peer'] = {'apply_started_at': self.data['apply_started_at']}
                self.save()
                print('[REHEARSAL] Peer deployment submitted (simulated).')
            else:
                with dependencies.parent_lock(self.source_path):
                    self.source_identity()
                    if self.target_graph() is not None:
                        raise RuntimeError('A peer target already exists; inspect it before continuing.')
                    dependencies.register(self.source_path, self.path)
                    self.data['apply_started_at'] = ui.now()
                    self.data['arm_intents']['peer'] = {'apply_started_at': self.data['apply_started_at']}
                    self.save()
                    self.run.apply([yaml.safe_load((self.path / 'peer.yaml').read_text())])
                    self.data['target_graph_uid'] = self.target_graph()['metadata']['uid']
                    self.save()
        else:
            self.data['apply_started_at'] = self.data['arm_intents']['peer']['apply_started_at']
            if not self.args.rehearsal:
                with dependencies.parent_lock(self.source_path):
                    self.source_identity()
                    dependencies.register(self.source_path, self.path)
                    if self.target_graph() is None:
                        raise RuntimeError('The interrupted peer graph is missing. Preserve this run and prepare a fresh one.')
            self.save()
        self.wait()
        self.summary()
        self.source_identity()
        folder = self.path / 'arms/peer'
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('worker.log', 'ready-pods.json', 'timing.json', 'allocated-gpus.json'):
            if (self.path / name).exists():
                shutil.copy2(self.path / name, folder / name)
        record = {'simulated': self.args.rehearsal,
                  'engine_signature': engine_signature(yaml.safe_load((self.path / 'peer.yaml').read_text())),
                  'node': self.data['target_node'], 'source_uid': self.data['arms']['storage']['worker_uid'],
                  'worker_uid': 'simulated-peer', 'ready_seconds': None,
                  'model_loading_seconds': None, 'engine_init_seconds': None}
        if not self.args.rehearsal:
            pods = ui.read_json(folder / 'ready-pods.json')['items']
            worker = next(p for p in pods if p['metadata']['labels']['workshop-role'] == 'worker')
            record.update(node=worker['spec']['nodeName'], worker_uid=worker['metadata']['uid'],
                          ready_seconds=self.data['startup']['total_seconds'],
                          model_loading_seconds=self.data['startup']['logged_seconds_slowest_rank']['model_loading'],
                          engine_init_seconds=self.data['startup']['logged_seconds_slowest_rank']['engine_initialization'])
            if record['node'] != self.data['target_node']:
                raise RuntimeError('Peer placement differs from the prepared target node.')
            self.verify_target_gpus(worker)
            shutil.copy2(self.path / 'allocated-gpus.json', folder / 'allocated-gpus.json')
        self.verify_transfer()
        ui.write_json(folder / 'record.json', record)
        self.data['arms']['peer'] = record
        self.save()
        return record

    def track_startup(self, pods, logs):
        self.data['mx_transfer'] = {'completed_ranks': len(transfer_receipts(logs)), 'expected_ranks': 2}

    def show_changes(self):
        print('Running first replica -> its mx-source Service -> second replica\n'
              'The first replica loaded from storage and already publishes compatible weights.\n'
              'That Kubernetes Service is the discovery path; there is no ModelExpress server in this setup.\n'
              'The second uses the same loader and engine settings.\n')
        self.command(['cat', self.path / 'modelexpress-settings.yaml'])

    def peer_startup(self):
        self.require_prepared()
        self.start_arm()
        self.compare()

    def check_peer_identity(self):
        if self.args.rehearsal:
            return
        self.source_identity()
        if self.target_graph() is None:
            raise RuntimeError('The proven peer graph is missing; inspect before continuing.')
        record = self.data['arms']['peer']
        pods = self.run.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']
        if not ui.ready_pods(pods):
            raise RuntimeError('The proven peer target is no longer Ready.')
        worker = next(p for p in pods if p['metadata']['labels']['workshop-role'] == 'worker')
        if worker['metadata']['uid'] != record['worker_uid'] or worker['spec']['nodeName'] != record['node']:
            raise RuntimeError('The peer target was replaced; its earlier proof cannot qualify the replacement.')
        if any(c.get('restartCount', 0) for c in worker['status'].get('containerStatuses', [])):
            raise RuntimeError('The peer target restarted; inspect its new startup before using the old proof.')
        self.verify_target_gpus(worker)

    def verify_target_gpus(self, worker):
        """Bind the transfer to exclusive physical GPUs, including unpinned runs."""
        references = worker['status'].get('resourceClaimStatuses', [])
        if len(references) != 1:
            raise RuntimeError('The peer target has no exact GPU claim binding.')
        claim = self.run.get('get', 'resourceclaim', references[0]['resourceClaimName'], '-n', self.ns)
        uid = worker['metadata']['uid']
        if not any(o.get('kind') == 'Pod' and o.get('uid') == uid
                   for o in claim['metadata'].get('ownerReferences', [])):
            raise RuntimeError('The peer GPU claim is not owned by the target worker.')
        slices = self.run.get('get', 'resourceslices')
        devices = physical_gpus(worker, claim, slices)
        if (len(devices) != 2 or
                set(devices) & set(self.data['source_identity']['gpu_devices'])):
            raise RuntimeError('The peer target needs two GPUs distinct from the first replica.')
        observed = {'pod_uid': uid, 'claim_uid': claim['metadata']['uid'],
                    'node': worker['spec']['nodeName'], 'gpu_uuids': devices}
        if self.data.get('target_gpu_identity', observed) != observed:
            raise RuntimeError('The peer target GPU allocation changed; its earlier proof cannot be reused.')
        self.data['target_gpu_identity'] = observed
        ui.write_json(self.path / 'allocated-gpus.json', observed)
        self.save()

    def verify_transfer(self):
        if self.args.rehearsal:
            proof = {'simulated': True, 'backend': 'LIBFABRIC', 'provider': 'efa', 'transfers': [],
                     'note': 'Rehearsal only; no GPU bytes or transfer time measured.'}
        else:
            if 'peer' in self.data['arms']:
                self.check_peer_identity()
            proof = verify_peer((self.path / 'worker.log').read_text(), 2)
            proof.update(simulated=False, source=self.source_identity(), target_node=self.data['target_node'],
                         target_gpus=self.data['target_gpu_identity'])
        ui.write_json(self.path / 'peer-proof.json', proof)
        return proof

    def show_transfer(self):
        proof = self.verify_transfer()
        if self.args.rehearsal:
            (self.path / 'transfer-excerpts.log').write_text(SAMPLE_PEER_LOG)
        else:
            text = (self.path / 'worker.log').read_text()
            selected = [line for line in text.splitlines() if any(marker in line for marker in
                        ('Receiving ', 'Transfer complete:', 'Backend LIBFABRIC', 'provider=efa', 'Trying strategy:'))]
            (self.path / 'transfer-excerpts.log').write_text('\n'.join(selected) + '\n')
        self.command(['cat', self.path / 'transfer-excerpts.log'])
        print('\n'.join(transfer_summary(proof)))
        print('Full proof with Pod, claim and GPU identities: peer-proof.json in the run directory.')
        print('Tensor-copy duration is inside model loading; the new engine still has to initialize.')

    def compare(self):
        result = comparison(self.data['arms']['storage'], self.data['arms']['peer'])
        ui.write_json(self.path / 'comparison.json', result)
        proof_path = self.path / 'peer-proof.json'
        peer_copy = (ui.read_json(proof_path) if proof_path.exists() else {}).get('slowest_rank_copy_seconds')
        print('\nFirst replica versus new replica · eager profile' + (' · REHEARSAL / not measured' if self.args.rehearsal else ''))
        print(f'{"Boundary":26s} {"Storage":>12s} {"Peer weights":>12s}')
        for label, key in [('Deployment to Ready', 'ready_seconds'), ('Model loading', 'model_loading_seconds'),
                           ('Engine initialization', 'engine_init_seconds')]:
            values = [f'{result[arm][key]:.1f}s' if result[arm][key] is not None else 'not measured' for arm in ('storage', 'peer')]
            print(f'{label:26s} {values[0]:>12s} {values[1]:>12s}')
            if key == 'model_loading_seconds':   # nested: the peer copy is part of model loading
                print(f'{"  peer copy, slowest rank":26s} {"—":>12s} '
                      f'{f"{peer_copy:.1f}s" if peer_copy is not None else "not measured":>12s}')
        if result['observed_readiness_ratio'] is not None:
            print(f'Observed readiness ratio: {result["observed_readiness_ratio"]:.2f}x (first / second replica)')
        print(prose(result['scope']))

    def use_target(self):
        if 'peer' not in self.data['arms']:
            raise RuntimeError('Start and verify the peer target first.')
        self.check_peer_identity()
        self.endpoint()
        self.request()

    def guided(self):
        self.require_prepared()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal; use --rehearsal --plain --auto for an offline check.')
        print('\nDynamo workshop · ModelExpress peer weights\n' +
              ('REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER') +
              '\nRun: ' + str(self.path), flush=True)
        self.run_steps(STEPS, [self.show_changes, self.peer_startup, self.show_transfer, self.use_target])

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        if self.legacy:
            self.cleanup_legacy()
            return
        with dependencies.parent_lock(self.source_path):
            graph = self.target_graph()
            if graph is not None:
                from common_runtime_tests import stop
                stop(self.run, [TARGET_GRAPH])
            for _ in range(36):
                pods = self.run.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']
                claims = self.run.get('get', 'resourceclaims', '-n', self.ns)['items']
                source_claim_uid = self.data.get('source_identity', {}).get('claim_uid')
                target_claims = [c for c in claims if c['metadata']['uid'] != source_claim_uid]
                if not pods and not target_claims:
                    dependencies.unregister(self.source_path, self.path)
                    self.data['cleaned_at'] = ui.now()
                    self.save()
                    print('Verified zero peer target Pods/claims. The first replica and its reservation stay running.')
                    return
                time.sleep(5)
        raise RuntimeError('Target cleanup is incomplete; source dependency retained.')

    def cleanup_legacy(self):
        # Existing isolated runs keep their original ownership/deletion boundary.
        if self.data.get('arm_intents') and not ui.lease_owned(self.path, OWNER):
            raise RuntimeError('This older MX run does not own its GPU lease; inspect before cleanup.')
        from common_runtime_tests import stop
        stop(self.run, [ui.GRAPH, 'demo-mx-source'])
        for _ in range(36):
            pods = self.run.get('get', 'pods', '-n', self.ns, '-l', 'workshop-role')['items']
            claims = self.run.get('get', 'resourceclaims', '-n', self.ns)['items']
            if not pods and not claims:
                if ui.lease_owned(self.path, OWNER):
                    (ui.LEASE / 'owner.json').unlink()
                    ui.LEASE.rmdir()
                self.data['cleaned_at'] = ui.now()
                self.save()
                return
            time.sleep(5)
        raise RuntimeError('Older MX cleanup is incomplete; lease retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run', choices=['run', 'prepare', 'prime', 'preview', 'cleanup', 'observe', 'hold'])
    parser.add_argument('--run', type=Path)
    parser.add_argument('--source-run', type=Path, help='Completed first-replica run; defaults to its selected run.')
    parser.add_argument('--target-node', help='Node for the second replica, distinct from the source.')
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--plain', action='store_true')
    parser.add_argument('--auto', action='store_true')
    parser.add_argument('--detach', action='store_true')
    parser.add_argument('--port', type=int, default=18001)
    parser.add_argument('--timeout', type=int, default=2700)
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    parser.add_argument('--once', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.port < 65536 or args.timeout <= 0:
        parser.error('Port must be 1..65535 and timeout must be positive.')
    if args.action == 'hold':
        while True:
            time.sleep(60)
    if args.action == 'observe':
        if not args.run:
            parser.error('observe requires --run')
        ui.observe(args.run.resolve(), args.view, args.once)
        return
    if args.action in ('cleanup', 'prime') and not args.run:
        parser.error(args.action + ' requires --run')
    demo = ModelExpressDemo(args)
    print('Demo files: ' + str(demo.path), flush=True)
    if args.preview or args.action == 'preview':
        print((demo.path / 'modelexpress-settings.yaml').read_text())
        print('Full manifests: peer.yaml, gpu-claim-template.yaml; source-binding.json records the first replica.')
        for index, (title, explanation) in enumerate(STEPS, 1):
            print(f'{index}. {title}: {explanation}')
        print('Preview only: no cluster commands executed.')
    elif args.action in ('prepare', 'prime', 'cleanup'):
        with ui.presenter_lock(demo.path):
            getattr(demo, args.action)()
    else:
        demo.require_prepared()
        demo.source_identity()
        if args.plain:
            with ui.presenter_lock(demo.path):
                demo.guided()
        else:
            ui.tmux_layout(demo)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. The source/target remain available; use this run\'s cleanup command when finished.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError) as error:
        print('\nMX demo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
