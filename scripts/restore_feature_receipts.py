#!/usr/bin/env python3
"""Reconstruct qualified receipts from durable evidence after an old observer overwrote state.

No requests or cluster changes: verify the existing logs/responses/metrics and retain
hashes of the exact evidence. Current testlib also writes separate check receipts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from testlib import Run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True,type=Path)
    args=parser.parse_args();run=Run(args.run)
    archive=run.path/f'evidence-{time.time_ns()}'
    archive.mkdir()
    def data(name):return json.loads((run.path/name).read_text())
    def proof(names):
        receipts={}
        for name in names:
            content=(run.path/name).read_bytes()
            (archive/name).write_bytes(content)
            receipts[f'{archive.name}/{name}']=hashlib.sha256(content).hexdigest()
        return receipts
    pods=data('owned-pods-status.json')
    source=next(p for p in pods if p['metadata'].get('labels',{}).get('mx-role')=='source')
    target=next(p for p in pods if p['metadata'].get('labels',{}).get('mx-role')=='target')
    assert source['spec']['nodeName']!=target['spec']['nodeName']
    log=(run.path/'modelexpress-target.log').read_text();answer=data('modelexpress-inference.json')
    assert 'Backend LIBFABRIC was instantiated' in log and 'using provider=efa' in log
    assert re.search(r'Receiving \d+ tensors from source \(P2P\)',log)
    assert 'Trying strategy: default' not in log
    assert answer['choices'][0]['message']['content']=='READY'
    matches=re.findall(r'Transfer complete: (\d+) tensors, ([0-9.]+) GB in ([0-9.]+)s',log);assert len(matches)==1
    n,gb,secs=matches[0]
    run.result('modelexpress','passed',source_node=source['spec']['nodeName'],target_node=target['spec']['nodeName'],
     tensors=int(n),gigabytes_from_log=float(gb),transfer_seconds_from_log=float(secs),backend='LIBFABRIC',provider='efa',
     evidence_sha256=proof(['modelexpress-target.log','modelexpress-inference.json','owned-pods-status.json']),
     scope='Recovered from existing P2P and expected-inference evidence; no new workload submitted')
    before=data('disagg-metrics-before.json');after=data('disagg-metrics-after.json');requests=data('disagg-requests.json')
    def counter(records,name):
     return sum(float(l.rsplit(' ',1)[-1]) for pod,r in records.items() if '-decode-' in pod
      for t in r['metrics'].values() if isinstance(t,str) for l in t.splitlines() if l.startswith(name+'{'))
    fields={name:counter(after,name)-counter(before,name) for name in ('vllm:nixl_bytes_transferred_sum',
     'vllm:nixl_bytes_transferred_count','vllm:nixl_num_failed_transfers_total','vllm:nixl_num_failed_notifications_total')}
    assert fields['vllm:nixl_bytes_transferred_sum']>0 and fields['vllm:nixl_bytes_transferred_count']>=2
    assert fields['vllm:nixl_num_failed_transfers_total']==fields['vllm:nixl_num_failed_notifications_total']==0
    nodes={p:r['node'] for p,r in after.items() if '-decode-' in p or '-prefill-' in p};assert len(set(nodes.values()))==2
    for r in requests:
     assert r['worker']['prefill_worker_id']!=r['worker']['decode_worker_id']
     text=''.join(c['choices'][0].get('delta',{}).get('content','') or '' for c in r['chunks'] if c.get('choices'))
     assert 'READY' in text
    run.result('disaggregation','passed',nodes=nodes,transfer_metric_deltas=fields,
     evidence_sha256=proof(['disagg-metrics-before.json','disagg-metrics-after.json','disagg-requests.json']),
     scope='Recovered from existing cross-node completed-transfer metrics and expected-inference evidence')
    build=next(p for p in pods if p['metadata']['name']=='kvcr-build')
    assert build['status']['phase']=='Succeeded'
    assert 'KVCR_DYNAMO_BUILD_COMPLETE' in (run.path/'kvcr-build-latest.log').read_text()
    run.result('kvcr-build','passed',evidence_sha256=proof(['kvcr-build-latest.log','owned-pods-status.json']),
     scope='Compatible binding build only; integrated KVCR qualification remains separate')


if __name__ == '__main__':
    main()
