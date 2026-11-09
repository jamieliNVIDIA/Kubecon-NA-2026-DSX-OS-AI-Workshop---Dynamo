#!/usr/bin/env python3
"""Bounded concurrent-client continuity qualification; not an AgentX/SLO benchmark."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace

import demos.common.runtime as ui
import demos.request_continuity.demo as migration

ROOT = Path(__file__).resolve().parents[2]
LEASE = ROOT / '.local/overnight-migration.gpu-lease'
PROFILE = 'coding-stream-c4-continuity-v1'
ORIGINAL_RENDER = migration.render
MODES = {'disabled': 0, 'enabled': 3}


def validate_assignment(value):
    nodes = value.get('nodes', {})
    if len(nodes) != 2 or any(len(uuids) != 2 or len(set(uuids)) != 2 for uuids in nodes.values()):
        raise ValueError('Need two nodes with exactly two distinct physical GPU UUIDs each.')
    uuids = [u for values in nodes.values() for u in values]
    if len(set(uuids)) != 4 or any(not re.fullmatch(
            r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', u) for u in uuids):
        raise ValueError('Need four distinct physical GPU UUIDs.')
    return copy.deepcopy(value)


def assigned_render(namespace, lock, arm, assignment):
    graph, claim = ORIGINAL_RENDER(namespace, lock, arm)
    nodes = sorted(assignment['nodes'])
    uuids = sorted(u for values in assignment['nodes'].values() for u in values)
    claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'] = [{'cel': {
        'expression': 'device.driver == "gpu.nvidia.com" && '
        'has(device.attributes["gpu.nvidia.com"].uuid) && '
        'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids)}}]
    for component in graph['spec']['components']:
        if component['type'] == 'worker':
            spec = component['podTemplate']['spec']
            spec['affinity']['nodeAffinity'] = {'requiredDuringSchedulingIgnoredDuringExecution': {
                'nodeSelectorTerms': [{'matchExpressions': [{'key': 'kubernetes.io/hostname',
                    'operator': 'In', 'values': nodes}]}]}}
    return graph, claim


def stream_summary(result, model):
    chunks = [e for e in result['events'] if e['type'] == 'chunk']
    content = [e for e in chunks if e.get('content')]
    finishes = [c['finish_reason'] for e in chunks for c in e['chunk'].get('choices', [])
                if c.get('finish_reason')]
    errors = [e['chunk']['error'] for e in chunks if e['chunk'].get('error')]
    ids = {e['chunk'].get('id') for e in chunks if e['chunk'].get('choices')}
    models = {e['chunk'].get('model') for e in chunks if e['chunk'].get('choices')}
    done = [e for e in result['events'] if e['type'] == 'done']
    successful = (result['http_status'] == 200 and result['request_count'] == 1 and bool(content)
                  and len(ids) == 1 and None not in ids and models == {model}
                  and len(finishes) == 1 and finishes[0] in ('length', 'stop')
                  and len(done) == 1 and result['events'][-1]['type'] == 'done'
                  and not errors and result['read_error'] is None)
    return {'successful_completion': successful, 'http_status': result['http_status'],
            'response_ids': sorted(ids, key=str), 'sse_initial_worker': content[0]['worker'] if content else None,
            'ttft_seconds': content[0]['seconds'] if content else None,
            'max_client_inter_content_gap_seconds': max((b['seconds'] - a['seconds']
                for a, b in zip(content, content[1:])), default=None),
            'last_content_seconds': content[-1]['seconds'] if content else None,
            'visible_content_chunks': len(content), 'finish_reasons': finishes,
            'done': bool(done), 'error_frames': errors, 'read_error': result['read_error'],
            'client_retries': 0, 'exact_handoff_gap_seconds': None}


def capture_batch(base, body, directory, *, fault=None, count=4):
    """Start fixed concurrent requests once; one selected stream may inject one fault."""
    directory.mkdir(exist_ok=False)
    barrier = threading.Barrier(count)
    guard = threading.Lock()
    active, results, failures = {}, {}, {}
    batch_start = time.monotonic()

    def inject(worker):
        with guard:
            outstanding = sorted(i for i, record in active.items() if 'finished_seconds' not in record)
            at_fault = {'batch_seconds': time.monotonic() - batch_start,
                        'outstanding_client_indices': outstanding,
                        'client_state': copy.deepcopy(active),
                        'scope': 'Outstanding HTTP clients; does not establish engine running-request count.'}
        ui.write_json(directory / 'load-at-fault.json', at_fault)
        return fault(worker, directory / 'request-00')

    def client(index):
        target = directory / ('request-%02d' % index)
        target.mkdir()
        barrier.wait(timeout=30)
        with guard:
            active[index] = {'started_seconds': time.monotonic() - batch_start}
        try:
            result = migration.capture_stream(base, body, target, inject,
                threshold=migration.FAULT_AFTER_CHUNKS if index == 0 and fault else 1_000_000,
                echo=False)
            with guard:
                results[index] = result
        except Exception as error:
            with guard:
                failures[index] = {'type': type(error).__name__, 'message': str(error)}
        finally:
            with guard:
                active[index]['finished_seconds'] = time.monotonic() - batch_start

    threads = [threading.Thread(target=client, args=(i,), daemon=True) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=310)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError('A client has not quiesced; retain the run and lease for diagnosis.')
    ui.write_json(directory / 'client-state.json', active)
    ui.write_json(directory / 'client-exceptions.json', failures)
    if failures or len(results) != count:
        raise RuntimeError('A client capture failed; inspect client-exceptions.json.')
    summaries = {str(i): stream_summary(result, body['model']) for i, result in results.items()}
    ui.write_json(directory / 'stream-summaries.json', summaries)
    return results, summaries


class LoadDemo(migration.MigrationDemo):
    entrypoint = Path(__file__).resolve()

    def __init__(self, args, arm, assignment):
        self.load_arm, self.assignment = arm, assignment
        migration.ARMS = {arm: MODES[arm]}
        migration.render = lambda namespace, lock, mode: assigned_render(namespace, lock, mode, assignment)
        ui.LEASE = LEASE
        super().__init__(args)
        self.data['graph'] = migration.GRAPH + '-' + arm
        self.data['resource_note'] = 'One two-worker case, four pinned H100s; modes run sequentially.'
        self.save()
        spec = {'profile': PROFILE, 'mode': arm, 'migration_limit': MODES[arm],
                'assignment': assignment, 'concurrency': 4, 'requests_per_batch': 4,
                'batches': ['baseline', 'fault'], 'fault_stream': 0,
                'fault_after_nonempty_chunks': migration.FAULT_AFTER_CHUNKS,
                'request_sha256': ui.digest(self.path / 'request.json'),
                'client_retries': 0, 'endpoint': 'run-local frontend Service',
                'model_lock_sha256': ui.digest(ui.MODEL_LOCK),
                'scope': 'Controlled coding-stream integration qualification; not AgentX replay or an SLO benchmark.',
                'limitations': ['Fixed-order N=1, warm baseline precedes fault batch.',
                    'Other assigned nodes/GPUs may run concurrently; shared EFS/network are not isolated.',
                    'Four HTTP clients are not four AgentX sessions or proof of GPU saturation.']}
        target = self.path / 'load-spec.json'
        if target.exists() and ui.read_json(target) != spec:
            raise ValueError('Frozen load spec changed; use a fresh run.')
        if not target.exists():
            ui.write_json(target, spec)
        self.load_spec = spec

    def prepare(self):
        super().prepare()
        if not ui.lease_owned(self.path, migration.OWNER):
            raise ValueError('Lost the scoped migration lease.')
        owner_path = ui.LEASE / 'owner.json'
        owner = ui.read_json(owner_path)
        owner['physical_assignment'] = self.assignment
        ui.write_json(owner_path, owner)

    def allocations(self):
        from gpu_claims import verify_allocation
        observed = {}
        for pod in self.pods(self.load_arm):
            if pod['metadata']['labels']['workshop-role'] != 'worker':
                continue
            node = pod['spec']['nodeName']
            claim = verify_allocation(self.run, pod, pod['spec']['containers'][0], 2)
            devices = claim['status']['allocation']['devices']['results']
            program = 'import json,subprocess; print(json.dumps(subprocess.check_output(["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],text=True).split()))'
            value = self.run.k('exec', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--',
                               'python3', '-c', program)
            uuids = json.loads(value.stdout)
            if node not in self.assignment['nodes'] or sorted(uuids) != sorted(self.assignment['nodes'][node]):
                raise ValueError('Worker allocated GPUs outside the assigned physical pair.')
            observed[node] = {'pod': pod['metadata']['name'], 'uid': pod['metadata']['uid'],
                              'gpu_uuids': uuids, 'claim_devices': devices}
        if set(observed) != set(self.assignment['nodes']):
            raise ValueError('Need one verified worker on each assigned node.')
        ui.write_json(self.path / 'physical-allocation.json', observed)
        return observed

    def qualify(self):
        self.prime()
        self.allocations()
        self.endpoint()
        arm = self.load_arm
        body = ui.read_json(self.path / 'request.json')
        baseline_path = self.path / 'baseline-load'
        if baseline_path.exists():
            raise ValueError('This immutable run already started sampling; use a fresh run.')
        print('\nBaseline: four concurrent coding streams, no fault.', flush=True)
        _, baseline = capture_batch(self.data['base_url'], body, baseline_path)
        if not all(s['successful_completion'] for s in baseline.values()):
            raise ValueError('Baseline did not complete all four requests; do not inject a fault.')
        fault_path = self.path / 'fault-load'
        print('\nFault: four identical concurrent coding streams, one observed EngineCore SIGKILL.', flush=True)
        before = self.snapshot_evidence(arm, self.path, 'load-before')
        results, summaries = capture_batch(self.data['base_url'], body, fault_path,
            fault=lambda wid, directory: self.inject(arm, wid, directory))
        after = self.snapshot_evidence(arm, self.path, 'load-after')
        receipt = results[0].get('fault', {}).get('receipt', {})
        migration.verify_survivors(before, after, receipt.get('pod_uid'))
        frontend = next(p['metadata']['name'] for p in before if p['metadata']['labels']['workshop-role'] == 'frontend')
        log = (self.path / ('load-after-' + frontend + '.log')).read_text()
        proof = migration.validate_stream(results[0], arm, self.data['model'], self.data['cases'][arm]['workers'],
                                          frontend_log=log)
        ui.write_json(fault_path / 'foreground-proof.json', proof)
        load = ui.read_json(fault_path / 'load-at-fault.json')
        if len(load['outstanding_client_indices']) != 4:
            raise ValueError('All four client requests must still be outstanding at fault submission.')
        if arm == 'enabled' and not all(s['successful_completion'] for s in summaries.values()):
            raise ValueError('An enabled concurrent stream failed; retain all evidence.')
        report = {'profile': PROFILE, 'mode': arm, 'simulated': False,
            'spec_sha256': ui.digest(self.path / 'load-spec.json'), 'baseline': baseline, 'fault': summaries,
            'baseline_completed': sum(s['successful_completion'] for s in baseline.values()),
            'fault_completed': sum(s['successful_completion'] for s in summaries.values()),
            'foreground_continuity_proof': proof, 'load_at_fault': load,
            'scope': self.load_spec['scope'], 'limitations': self.load_spec['limitations']}
        ui.write_json(self.path / 'load-qualification.json', report)
        print(json.dumps({k: report[k] for k in ('mode', 'baseline_completed', 'fault_completed', 'scope')}, indent=2), flush=True)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preview', 'prime', 'run', 'cleanup'])
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--assignment', type=Path, required=True)
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--port', type=int, default=18154)
    parser.add_argument('--timeout', type=int, default=2700)
    args = parser.parse_args()
    assignment = validate_assignment(ui.read_json(args.assignment))
    ui_args = SimpleNamespace(run=args.run, action='cleanup' if args.action == 'cleanup' else 'prime',
        rehearsal=False, preview=args.action == 'preview', auto=True, plain=True, port=args.port,
        timeout=args.timeout)
    demo = LoadDemo(ui_args, args.mode, assignment)
    with ui.presenter_lock(demo.path):
        if args.action == 'preview':
            print(json.dumps(demo.load_spec, indent=2))
        elif args.action == 'cleanup':
            demo.cleanup()
        elif args.action == 'prime':
            demo.prime()
            demo.allocations()
        else:
            try:
                demo.qualify()
            finally:
                if demo.forward:
                    demo.forward.terminate()
                    demo.forward.wait(timeout=10)


if __name__ == '__main__':
    main()
