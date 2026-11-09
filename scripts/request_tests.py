#!/usr/bin/env python3
"""Collect actual routing/cache and disaggregation evidence from owned serving pods."""
import argparse
import json
import re
from pathlib import Path
import time
import urllib.request
import uuid
from serving_tests import frontend, lock_model
from testlib import Run


def send(base, payload, headers=None):
    req = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps({**payload, 'stream': True}).encode(),
        headers={'Content-Type': 'application/json', **(headers or {})})
    chunks = []
    with urllib.request.urlopen(req, timeout=180) as response:
        for line in response:
            text = line.decode().strip()
            if text.startswith('data: ') and text[6:] != '[DONE]':
                chunks.append(json.loads(text[6:]))
    if any(c.get('error') for c in chunks):
        raise ValueError(chunks)
    return {'chunks': chunks,
            'worker': next((c['nvext']['worker_id'] for c in reversed(chunks) if c.get('nvext', {}).get('worker_id')), None),
            'usage': next((c['usage'] for c in reversed(chunks) if c.get('usage')), None)}


def metrics(run, topology, label):
    reports = {}
    for pod in run.get('get', 'pods', '-n', run.ns)['items']:
        if not pod['metadata']['name'].startswith('ft-' + topology + '-'):
            continue
        name = pod['metadata']['name']
        if pod.get('status', {}).get('phase') != 'Running':
            continue
        code = '''import json, urllib.request
r = {}
for port in (8000, 9090, 19090):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics', timeout=5) as f: r[str(port)] = f.read().decode()
    except Exception as e: r[str(port)] = {'error': str(e)}
print(json.dumps(r))
'''
        result = run.k('exec', '-i', name, '-n', run.ns, '-c', 'main', '--', 'python3', '-', input_text=code)
        reports[name] = {'node': pod['spec']['nodeName'], 'metrics': json.loads(result.stdout)}
    (run.path / f'{topology}-metrics-{label}.json').write_text(json.dumps(reports, indent=2) + '\n')
    return reports


def routing(run):
    model = lock_model(run)['model']
    before = metrics(run, 'agg', 'before')
    metadata = run.get('get', 'dynamoworkermetadatas', '-n', run.ns)
    (run.path / 'worker-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    receipts = []
    suffix = uuid.uuid4().hex
    def payload(content, query=False):
        return {'model': model, 'messages': [{'role': 'user', 'content': content}], 'max_tokens': 1, 'temperature': 0,
            'chat_template_kwargs': {'enable_thinking': False},
            'stream_options': {'include_usage': True},
            'nvext': {'extra_fields': ['worker_id', 'timing'], 'annotations': ['query_instance_id:'] if query else []}}
    with frontend(run, 'agg') as base:
        workers = set()
        for i in range(12):
            response = send(base, payload(f'worker discovery {suffix} {i}', query=True))
            receipts.append({'step': 'discover', **response})
            if response['worker']:
                workers.add(response['worker']['decode_worker_id'])
            if len(workers) >= 2: break
        if len(workers) != 2:
            raise ValueError(f'Expected two discoverable workers, got {workers}')
        # Cover an aligned Mamba page; the cached-token checks below prove reuse.
        for index, worker in enumerate(sorted(workers)):
            lock = lock_model(run)
            prefix = f'Unique session {suffix} variant {index}. ' + (' apple' if index == 0 else ' banana') * lock.get('routing_prefix_words',6000 if lock.get('tensor_parallel_size',1)>1 else 2800)
            forced = send(base, payload(prefix), {'x-dynamo-worker-instance-id': str(worker), 'x-dynamo-dp-rank': '0'})
            receipts.append({'step': 'seed', 'expected_worker': worker, **forced})
            assert forced['worker']['decode_worker_id'] == worker
            assert forced['usage']['prompt_tokens'] > 2176
            time.sleep(2)
            for repeat in range(3):
                response = send(base, payload(prefix))
                receipts.append({'step': 'unforced-repeat', 'expected_worker': worker, **response})
                assert response['worker']['decode_worker_id'] == worker, 'Cache prefix selected the wrong worker'
                cached = response['usage']['prompt_tokens_details']['cached_tokens']
                assert cached > 0, 'No engine prefix reuse reported'
    (run.path / 'routing-requests.json').write_text(json.dumps(receipts, indent=2) + '\n')
    after = metrics(run, 'agg', 'after')
    def stored_events(records):
        return sum(float(line.rsplit(' ', 1)[-1]) for name, record in records.items() if 'frontend' in name
            for text in record['metrics'].values() if isinstance(text, str)
            for line in text.splitlines() if line.startswith('dynamo_component_kv_cache_events_applied{')
            and 'event_type="stored"' in line and 'status="ok"' in line)
    event_delta = stored_events(after) - stored_events(before)
    assert event_delta >= 2, 'Frontend did not apply KV store events for both prefixes'
    run.result('kv-routing', 'passed', worker_ids=sorted(workers), independent_prefixes=2, unforced_repeats=6,
               frontend_stored_event_delta=event_delta,
               cached_tokens=[r['usage']['prompt_tokens_details']['cached_tokens'] for r in receipts if r['step']=='unforced-repeat'],
               evidence=['routing-requests.json','agg-metrics-before.json','agg-metrics-after.json'],
               scope='Two cross-node workers, forced cold seeding then unforced cache affinity and engine prefix reuse')


def disagg(run):
    run.k('wait', '--for=condition=Ready', 'dgd/ft-disagg', '-n', run.ns, '--timeout=900s', timeout=930)
    model = lock_model(run)['model']
    before = metrics(run, 'disagg', 'before')
    receipts = []
    with frontend(run, 'disagg') as base:
        for length in (128, 6000 if lock_model(run).get('tensor_parallel_size', 1) > 1 else 2400):
            content = f'Unique transfer {uuid.uuid4().hex}. ' + ' apple' * length + '. Reply with READY.'
            response = send(base, {'model': model, 'messages': [{'role': 'user', 'content': content}],
                'max_tokens': 16, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False},
                'stream_options': {'include_usage': True}, 'nvext': {'extra_fields': ['worker_id','timing']}})
            receipts.append(response)
            assert response['worker']['prefill_worker_id'] != response['worker']['decode_worker_id']
            assert response['usage']['completion_tokens'] > 0
            text=''.join(c.get('choices',[{}])[0].get('delta',{}).get('content','') or ''
                         for c in response['chunks'] if c.get('choices'))
            assert 'READY' in text, f'Unexpected generated output: {text!r}'
    (run.path/'disagg-requests.json').write_text(json.dumps(receipts,indent=2)+'\n')
    after = metrics(run,'disagg','after')
    def counter(records,name,filter_text=''):
        return sum(float(line.rsplit(' ',1)[-1]) for pod,record in records.items() if '-decode-' in pod
            for text in record['metrics'].values() if isinstance(text,str) for line in text.splitlines()
            if line.startswith(name+'{') and filter_text in line)
    fields = {name:counter(after,name)-counter(before,name) for name in (
        'vllm:nixl_bytes_transferred_sum','vllm:nixl_bytes_transferred_count',
        'vllm:nixl_num_failed_transfers_total','vllm:nixl_num_failed_notifications_total')}
    imported=counter(after,'vllm:prompt_tokens_by_source_total','source="external_kv_transfer"')-counter(
        before,'vllm:prompt_tokens_by_source_total','source="external_kv_transfer"')
    assert fields['vllm:nixl_bytes_transferred_sum'] > 0, 'No measured KV bytes transferred'
    assert fields['vllm:nixl_bytes_transferred_count'] >= 2, 'Missing completed transfer samples'
    assert fields['vllm:nixl_num_failed_transfers_total']==0
    assert fields['vllm:nixl_num_failed_notifications_total']==0
    nodes = {p:r['node'] for p,r in after.items() if '-decode-' in p or '-prefill-' in p}
    assert len(set(nodes.values()))==2
    run.result('disaggregation','passed',nodes=nodes,transfer_metric_deltas=fields,imported_prompt_tokens=imported,
        evidence=['disagg-requests.json','disagg-metrics-before.json','disagg-metrics-after.json'],
        scope='Cross-node LIBFABRIC-configured P/D, nonzero completed KV transfer bytes, no transfer failures and expected outputs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['routing','disagg','metrics'])
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--topology', choices=['agg','disagg','sidecar','mx','mx-target','kvcr'], default='agg')
    args = parser.parse_args()
    run = Run(args.run)
    try:
        if args.action == 'routing': routing(run)
        elif args.action == 'disagg': disagg(run)
        else: print(json.dumps(metrics(run,args.topology,'inspect'),indent=2))
    except Exception as exc:
        run.result(args.action, 'blocked', error=str(exc))
        raise


if __name__ == '__main__': main()
