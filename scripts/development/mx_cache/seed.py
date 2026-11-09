#!/usr/bin/env python3
"""Seed an owned RAM-backed HF cache once, with complete file hashes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import time
import traceback

GiB=1024**3


def hf_manifest(spec):
    raw=spec['hf_manifest_json'].encode()
    if hashlib.sha256(raw).hexdigest()!=spec['hf_manifest_sha256']:
        raise ValueError('Frozen HF tree bytes/hash differ.')
    expected_url=('https://huggingface.co/api/models/'+spec['model']+'/tree/'+spec['revision']+
        '?recursive=true&expand=false&limit=1000')
    if spec['hf_manifest_url']!=expected_url:raise ValueError('HF tree URL is not the exact pinned revision.')
    rows=json.loads(raw)
    if len(rows)!=spec['hf_manifest_entries']:raise ValueError('Frozen HF tree entry count differs.')
    manifest={}
    for row in rows:
        name=row['path'];p=PurePosixPath(name)
        if (row.get('type')!='file' or not name or str(p)!=name or p.is_absolute() or '..' in p.parts or
            '\\' in name or '\0' in name or name in manifest or type(row['size']) is not int or row['size']<0 or
            not re.fullmatch(r'[a-f0-9]{40}',row['oid'])):
            raise ValueError('Unsafe/incomplete pinned HF file entry: '+name)
        if 'lfs' in row:
            if (not re.fullmatch(r'[a-f0-9]{64}',row['lfs']['oid']) or row['lfs']['size']!=row['size']):
                raise ValueError('Invalid authoritative LFS data identity: '+name)
        if 'xetHash' in row and not re.fullmatch(r'[a-f0-9]{64}',row['xetHash']):
            raise ValueError('Invalid declared Xet storage identity: '+name)
        manifest[name]=row
    return manifest


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def memory_state():
    values={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1)
        if key in ('MemTotal','MemAvailable'):values[key]=int(value.split()[0])*1024
    for name in ('memory.max','memory.current'):
        p=Path('/sys/fs/cgroup')/name
        values[name]=p.read_text().strip() if p.exists() else None
    return values


def preflight(cache,total_bytes,cache_limit_bytes):
    m=memory_state();limit=m.get('memory.max')
    if m.get('MemAvailable',0)<cache_limit_bytes+32*GiB:raise ValueError('Host memory headroom below cache plus32GiB reserve.')
    if limit not in (None,'max'):
        current=int(m.get('memory.current') or 0)
        if int(limit)-current<total_bytes+4*GiB:raise ValueError('Init cgroup available memory cannot hold cache plus4GiB reserve.')
    if total_bytes+GiB>cache_limit_bytes:raise ValueError('Snapshot exceeds bounded cache size.')
    if os.statvfs(cache).f_bavail*os.statvfs(cache).f_frsize<total_bytes+GiB:raise ValueError('Insufficient cache filesystem space.')
    print('MX_DEV_CACHE_MEMORY='+json.dumps(m,sort_keys=True),flush=True)
    return m


def seed(spec,source_hf_home,cache,resource_gate=preflight):
    started=time.monotonic();model=spec['model'];revision=spec['revision']
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,35}',spec['id']):raise ValueError('Invalid owned seed identifier.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',model) or not re.fullmatch(r'[a-f0-9]{40}',revision):raise ValueError('Invalid pinned model identity.')
    source_hf_home=Path(source_hf_home);cache=Path(cache)
    repo_name='models--'+model.replace('/','--')
    source_repo=source_hf_home/'hub'/repo_name;source=source_repo/'snapshots'/revision
    if not source.is_dir():raise ValueError('Pinned source snapshot is absent.')
    files={str(p.relative_to(source)):p for p in sorted(source.rglob('*')) if p.is_file()}
    manifest=hf_manifest(spec)
    if set(files)!=set(manifest):raise ValueError('Source file set differs from complete pinned HF tree.')
    for name,p in files.items():
        row=manifest[name]
        if p.stat().st_size!=row['size']:raise ValueError('Source file size differs from pinned HF tree: '+name)
        resolved=p.resolve()
        try:
            resolved.relative_to(source_repo.resolve())
        except ValueError:
            # ModelExpress publishes shared CAS blobs beside models-- repositories.
            # Admit only exact CAS layout; file content identity comes from HF LFS/Git,
            # because an Xet storage key is not a SHA256 of the complete file.
            shared=source_hf_home.resolve()/'hub'/'blobs'
            try:relative=resolved.relative_to(shared)
            except ValueError:raise ValueError('Source symlink escapes pinned repository/shared CAS: '+name)
            parts=relative.parts
            if (len(parts)!=2 or not re.fullmatch(r'[a-f0-9]{64}',parts[1]) or parts[0]!=parts[1][:2]):
                raise ValueError('Source shared CAS layout is not exact/content-addressed: '+name)
        allowed={row['oid']}
        if 'lfs' in row:allowed.add(row['lfs']['oid'])
        if 'xetHash' in row:allowed.add(row['xetHash'])
        if resolved.name not in allowed:raise ValueError('Source blob key is not declared by pinned HF tree: '+name)
    for name,h in spec['model_metadata_sha256'].items():
        if name not in files or sha256(files[name])!=h:raise ValueError('Pinned source metadata hash differs: '+name)
    index=json.loads(files['model.safetensors.index.json'].read_text());weights=set(index['weight_map'].values())
    if not weights.issubset(files):raise ValueError('Indexed weights are missing.')
    if len(weights)!=spec['weight_files'] or sum(files[n].stat().st_size for n in weights)!=spec['weight_bytes']:raise ValueError('Qualified source weight count/bytes differ.')
    for name in weights:
        if 'lfs' not in manifest[name]:raise ValueError('Weight has no authoritative pinned HF LFS data hash: '+name)
    if any(name.endswith('.safetensors') and name not in weights for name in files):raise ValueError('Unexpected safetensor outside qualified index.')
    total=sum(p.stat().st_size for p in files.values())
    cache.mkdir(parents=True,exist_ok=True)
    memory=resource_gate(cache,total,spec['cache_limit_bytes'])
    destination=cache/repo_name;staging=cache/('.mx-staging-'+spec['id']);receipt_path=cache/'mx-dev-cache-seed.json'
    if destination.exists() or staging.exists() or receipt_path.exists():raise ValueError('Cache is not fresh; inspect preserved state instead of overwriting.')
    (staging/'blobs').mkdir(parents=True);snapshot=staging/'snapshots'/revision;snapshot.mkdir(parents=True)
    inventory={}
    for number,(name,p) in enumerate(files.items(),1):
        size=p.stat().st_size;blob_id=p.resolve().name
        temporary=staging/'blobs'/('.copy-'+str(number));h=hashlib.sha256();git=hashlib.sha1();git.update(b'blob '+str(size).encode()+b'\0')
        written=0
        with p.open('rb') as inp,temporary.open('xb') as out:
            for block in iter(lambda:inp.read(4*1024*1024),b''):
                out.write(block);h.update(block);git.update(block);written+=len(block)
            out.flush();os.fsync(out.fileno())
        actual=h.hexdigest()
        if written!=size:raise ValueError('Source file changed during copy: '+name)
        row=manifest[name]
        if 'lfs' in row and actual!=row['lfs']['oid']:raise ValueError('Pinned HF LFS data checksum differs: '+name)
        if 'lfs' not in row and git.hexdigest()!=row['oid']:raise ValueError('Pinned HF Git-blob checksum differs: '+name)
        if name in spec['model_metadata_sha256'] and actual!=spec['model_metadata_sha256'][name]:raise ValueError('Metadata changed during copy: '+name)
        blob=staging/'blobs'/actual
        if blob.exists():
            if sha256(blob)!=actual:raise ValueError('Conflicting staged content.')
            temporary.unlink()
        else:os.replace(temporary,blob)
        target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(os.path.relpath(blob,target.parent))
        inventory[name]={'bytes':written,'sha256':actual,'weight':name in weights,'source_blob_id':blob_id,
            'hf_data_hash_kind':'sha256-lfs' if 'lfs' in row else 'sha1-git-blob',
            'hf_data_hash':row['lfs']['oid'] if 'lfs' in row else row['oid'],'hf_git_oid':row['oid'],
            'hf_xet_storage_key':row.get('xetHash')}
        if number%10==0 or number==len(files):print(json.dumps({'seed_files':number,'total_files':len(files),'copied_bytes':sum(x['bytes'] for x in inventory.values())}),flush=True)
    (staging/'refs').mkdir();(staging/'refs/main').write_text(revision+'\n')
    os.replace(staging,destination)
    receipt={'schema':1,'status':'passed','id':spec['id'],'model':model,'revision':revision,'source_hf_home':str(source_hf_home),'cache':str(cache),'files':inventory,'file_count':len(inventory),'weight_files':len(weights),'weight_bytes':sum(inventory[n]['bytes'] for n in weights),'logical_bytes':total,'elapsed_seconds':time.monotonic()-started,'memory':memory,'hf_manifest_sha256':spec['hf_manifest_sha256'],'hf_manifest_url':spec['hf_manifest_url'],'hf_manifest_entries':spec['hf_manifest_entries'],'hf_manifest_receipt_sha256':spec.get('hf_manifest_receipt_sha256'),'storage_scope':'Private RAM emptyDir; survives candidate runs while this server Pod exists, not server Pod replacement.'}
    with receipt_path.open('x') as out:out.write(json.dumps(receipt,sort_keys=True)+'\n')
    print('MX_DEV_CACHE_SEED='+json.dumps(receipt,sort_keys=True),flush=True)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True);p.add_argument('--source-hf-home',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--timeout-seconds',type=int,default=2400);a=p.parse_args()
    if not 1<=a.timeout_seconds<=7200:p.error('Seed timeout must be between1 and7200 seconds.')
    def timed_out(signum,frame):
        raise TimeoutError('Bounded MX RAM cache seed timed out; preserved partial cache needs inspection.')
    signal.signal(signal.SIGALRM,timed_out)
    signal.alarm(a.timeout_seconds)
    failure_path=a.cache/'mx-dev-cache-failure.json'
    if failure_path.exists():
        print('MX_DEV_CACHE_FIRST_FAILURE='+failure_path.read_text().strip(),flush=True)
        raise RuntimeError('Previous seed fatal preserved; inspect it before replacing this owned cache Pod.')
    try:
        seed(json.loads(a.spec.read_text()),a.source_hf_home,a.cache)
    except BaseException as error:
        signal.alarm(0)
        failure={'schema':1,'status':'failed','exception_type':type(error).__name__,'error':str(error),
            'traceback':traceback.format_exc(),'spec_sha256':hashlib.sha256(a.spec.read_bytes()).hexdigest()}
        a.cache.mkdir(parents=True,exist_ok=True)
        try:
            with failure_path.open('x') as out:
                out.write(json.dumps(failure,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno())
        except FileExistsError:
            pass
        print('MX_DEV_CACHE_FIRST_FAILURE='+failure_path.read_text().strip(),flush=True)
        raise
    finally:
        signal.alarm(0)


if __name__=='__main__':main()
