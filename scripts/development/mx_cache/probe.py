#!/usr/bin/env python3
"""Bounded CPU-only ModelExpress ModelService compatibility/read probe."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--address',required=True)
    p.add_argument('--lock',type=Path,required=True)
    p.add_argument('--source-hf-home',type=Path,required=True)
    p.add_argument('--cache',type=Path,default=Path('/probe-cache'))
    p.add_argument('--rpc-timeout',type=float,default=45)
    a=p.parse_args()
    if not 0<a.rpc_timeout<=120:p.error('RPC timeout must be in (0,120].')
    lock=json.loads(a.lock.read_text());model=lock['model'];revision=lock['revision']
    source=a.source_hf_home/'hub'/('models--'+model.replace('/','--'))/'snapshots'/revision
    for name,expected in lock['model_metadata_sha256'].items():
        if digest(source/name)!=expected:raise RuntimeError('Source metadata hash differs: '+name)
    import grpc
    from modelexpress import model_pb2
    from modelexpress.model_client import ModelCacheClient
    from modelexpress.model_snapshot import split_by_weight
    client=ModelCacheClient(server_url=a.address,cache_directory=a.cache,chunk_size=1024*1024)
    raw=client.stub
    # The installed client intentionally has no download deadline; this
    # capability probe adds finite deadlines without changing package sources.
    client._stub=SimpleNamespace(**{name:(lambda method:lambda request:method(request,timeout=a.rpc_timeout))(getattr(raw,name))
        for name in ('EnsureModelDownloaded','ListModelFiles','StreamModelFiles')})
    started=time.monotonic()
    resolved=client.ensure_downloaded(model,ignore_weights=True,revision=revision)
    if resolved!=revision:raise RuntimeError('Server did not confirm the exact pinned revision: '+str(resolved))
    metadata=client.list_files(model,ignore_weights=True,revision=revision)
    full=client.list_files(model,ignore_weights=False,revision=revision)
    _,metadata_weights=split_by_weight(metadata)
    if metadata_weights:raise RuntimeError('Server ignored metadata-only manifest selection.')
    _,weights=split_by_weight(full)
    expected_index=json.loads((source/'model.safetensors.index.json').read_text())
    expected_weights=set(expected_index['weight_map'].values())
    if set(weights)!=expected_weights:raise RuntimeError('Full manifest did not expose the exact pinned weight set.')
    for name in weights:
        if full[name]!=(source/name).stat().st_size:raise RuntimeError('Weight size mismatch: '+name)
    snapshot=client.install_metadata_snapshot(model,requested_revision=revision)
    if snapshot.name!=revision:raise RuntimeError('Installed revision differs.')
    for name,expected in lock['model_metadata_sha256'].items():
        if digest(snapshot/name)!=expected:raise RuntimeError('Streamed metadata hash differs: '+name)
    full_revision=client.ensure_downloaded(model,ignore_weights=False,revision=revision)
    if full_revision!=revision:raise RuntimeError('Full-weight claim did not confirm the exact revision.')
    sample=min(weights,key=lambda name:full[name])
    if full[sample]>1024**3:raise RuntimeError('Smallest weight shard exceeds this bounded 1GiB probe.')
    class HashSink:
        def __init__(self):self.hash=hashlib.sha256();self.bytes=0
        def begin_file(self,name):
            if name!=sample:raise RuntimeError('Unexpected sample path.')
        def write(self,data):self.hash.update(data);self.bytes+=len(data)
        def end_file(self):
            if self.bytes!=full[sample]:raise RuntimeError('Incomplete sample weight stream.')
    sink=HashSink()
    client._stream_into(model,model_pb2.HUGGING_FACE,[sample],{sample:full[sample]},sink,expected_commit=revision,revision=revision)
    expected_sample=digest(source/sample)
    if sink.hash.hexdigest()!=expected_sample:raise RuntimeError('Streamed sample weight hash differs from the pinned cache.')
    meminfo={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1)
        if key in ('MemTotal','MemAvailable'):meminfo[key]=value.strip()
    cgroup={}
    for name in ('memory.max','memory.current'):
        q=Path('/sys/fs/cgroup')/name
        cgroup[name]=q.read_text().strip() if q.exists() else None
    result={'schema':1,'status':'passed','scope':'CPU-only exact revision, metadata/full file selection, metadata hashes and one bounded weight-shard read/hash; no CUDA/model load.',
        'model':model,'revision':revision,'address':a.address,'weight_files':len(weights),'weight_bytes':sum(full[n] for n in weights),
        'metadata_files':len(metadata),'installed_snapshot':str(snapshot),'metadata_hashes':{n:digest(snapshot/n) for n in lock['model_metadata_sha256']},
        'sample_weight':{'path':sample,'bytes':sink.bytes,'sha256':expected_sample},
        'elapsed_seconds':time.monotonic()-started,'host_memory':meminfo,'client_cgroup':cgroup,'torch_imported':'torch' in sys.modules}
    client.close()
    print('MX_DEV_CACHE_PROBE='+json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    main()
