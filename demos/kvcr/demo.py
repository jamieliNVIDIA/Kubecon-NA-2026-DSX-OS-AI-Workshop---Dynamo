#!/usr/bin/env python3
"""Move committed coding context to another worker with KVCR (experimental stack)."""
from __future__ import annotations

import argparse
import base64
import contextlib
import copy
import datetime as dt
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import demos.common.runtime as ui
import demos.common.support as support
import demos.kvcr.guard as guard
from testlib import Run

INPUTS = ui.ROOT / 'demos/kvcr'
SOURCE_LOCK = INPUTS / 'source-lock.json'
PLACEMENT = INPUTS / 'placement.json'
OWNER = 'workshop-demo-kvcr'
GRAPH = 'demo-kvcr'
# New runs measure the first-token speedup on one long shared repository. Earlier runs, and the prepared
# children bound to them, keep the two-request READY walkthrough of the legacy profile.
PROFILE = 'super-vl-kvcr-speedup-v3'
LEGACY_PROFILE = 'super-vl-kvcr-host-peer-nightly-v2'
FIXTURE_FUNCTIONS = 120
OUTPUT_TOKENS = 16
SOURCE_SUFFIX = '\nMain agent: acknowledge this context by replying READY.'
TARGET_SUFFIX = '\nParallel subagent: acknowledge this context by replying READY.'
STEPS = [
    ('Let the context move', 'Keep the repository context; select a worker with spare compute.'),
    ('Verify the prepared workers', 'Two TP2 engines, separate host pools and cross-node EFA.'),
    ('Seed the repository context on A', 'A computes the prompt and commits reusable state to its host pool.'),
    ('Continue on B', 'The same prefix reaches B; verify peer transfer and avoided prompt computation.'),
    ('Inspect the evidence', 'Match both ends of the transfer, external-cache tokens and clean delivery.'),
]

# Speedup profile: a main agent reads a long synthetic repository on A; its subagent lands on B.
CONTEXT_LIMIT = 65536
BATCHED_TOKENS = 8448          # two effective 4,224-token pages per prefill chunk
REPOSITORY_MODULES = 420       # about 12-13 effective pages; the tokenizer gate measures the real size
WARMUP_MODULES = 72            # just over two pages: exercises chunked prefill and one peer fetch
MIN_SHARED_PAGES = 10
ANSWER_TOKENS = 32
PLANTED = ('rotate_signing_keys', 'replay_dead_letters')
WARMUP_PLANTED = ('expire_stale_sessions', 'prune_orphaned_blobs')
# A planted function lives in a distinctively named file of a random package. Among 420 numbered files the model
# sometimes recalled a neighboring module number; a distinct name keeps the answer about the context, not digits.
PLANTED_FILES = ('housekeeping', 'maintenance')
PACKAGES = ('api', 'auth', 'billing', 'catalog', 'jobs', 'search', 'storage', 'telemetry')
VERBS = ('build', 'check', 'clean', 'fetch', 'flush', 'index', 'load', 'merge', 'parse', 'route', 'scan', 'sync')
NOUNS = ('batch', 'bundle', 'cache', 'config', 'event', 'header', 'ledger', 'policy', 'record', 'report', 'schema', 'token')
CONTEXTS = {'shared': 'shared-context.txt', 'control': 'control-context.txt', 'warmup': 'warmup-context.txt'}
# role: (worker, repository, planted function, agent). The control repository has the shared one's shape and
# question, but nobody has read it, so B must compute it from scratch.
ROLES = {'warmup_main': ('a', 'warmup', WARMUP_PLANTED[0], 'main'), 'warmup_sub': ('b', 'warmup', WARMUP_PLANTED[1], 'sub'),
         'main': ('a', 'shared', PLANTED[0], 'main'), 'control': ('b', 'control', PLANTED[1], 'sub'),
         'sub': ('b', 'shared', PLANTED[1], 'sub')}
PAIRS = {'main/sub': ['main', 'sub'], 'warmup_main/warmup_sub': ['warmup_main', 'warmup_sub'],
         'control/sub': ['control', 'sub'], 'control/main': ['control', 'main']}
METRICS_PROGRAM = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9090/metrics',timeout=5).read().decode())"
SPEEDUP_STEPS = [
    ('One repository, two agents', 'The main agent read a large repository on A; its subagent lands on B, which has spare compute.'),
    ('Check the warm workers', 'Two TP2 engines, started and warmed offstage, with separate host pools and cross-node EFA.'),
    ('Main agent reads the repository on A', 'A computes the whole context and keeps it in its host pool.'),
    ('Subagents land on B', 'A repository nobody has read is computed from scratch; the main agent\'s repository comes from A.'),
    ('Compare the first token', 'Same worker, same prompt size: recompute versus KVCR reuse.'),
]


def validate_placement(value):
    if set(value) != {'a', 'b'}:
        raise ValueError('Placement needs exactly peers a and b.')
    seen = set()
    for peer, item in value.items():
        names = item.get('gpu_uuids', [])
        if (not item.get('node', '').startswith('kubecon-nke-site-') or len(names) != 2 or
                len(set(names)) != 2 or any(not n.startswith('GPU-') for n in names) or seen.intersection(names)):
            raise ValueError('Each worker needs an explicit node and a unique GPU UUID pair: ' + peer)
        seen.update(names)
    return copy.deepcopy(value)


def selectors(uuids):
    return [{'cel': {'expression': 'device.driver == "gpu.nvidia.com" && '
        'has(device.attributes["gpu.nvidia.com"].uuid) && '
        'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids)}}]


@contextlib.contextmanager
def harness_scope(placement, lease, *, node=None):
    """Legacy harness globals are process-local; other chats retain their own leases."""
    previous = guard.NODE, guard.GRAPH, guard.OWNER, ui.LEASE
    guard.NODE, guard.GRAPH, guard.OWNER = node or placement['a']['node'], GRAPH, OWNER
    ui.LEASE = lease
    try:
        yield
    finally:
        guard.NODE, guard.GRAPH, guard.OWNER, ui.LEASE = previous


def render(namespace, model, candidate, runtime_name, placement):
    placement = validate_placement(placement)
    with harness_scope(placement, Path('/unused-offline-lease')):
        graph, claims = guard.render(namespace, model, candidate, runtime_name)
    for component in graph['spec']['components']:
        spec = component['podTemplate']['spec']
        peer = component['podTemplate']['metadata']['labels'].get('kvcr-peer', 'a')
        spec['nodeSelector'] = {'kubernetes.io/hostname': placement[peer]['node']}
        if component['type'] == 'worker':
            # Functional test budget: shared-node neighbors also need EFA devices.
            # This is deliberately not a throughput comparison to the a4 profile.
            for kind in ('requests', 'limits'):
                spec['containers'][0]['resources'][kind]['vpc.amazonaws.com/efa'] = '4'
            spec['containers'][0]['env'] += [{'name': 'KVCR_MAX_MODEL_LEN', 'value': str(CONTEXT_LIMIT)},
                                             {'name': 'KVCR_MAX_NUM_BATCHED_TOKENS', 'value': str(BATCHED_TOKENS)}]
    for claim, peer in zip(claims, ('a', 'b')):
        claim['spec']['spec']['devices']['requests'][0]['exactly']['selectors'] = selectors(placement[peer]['gpu_uuids'])
    return graph, claims


def interval_log(previous, current):
    if not current.startswith(previous):
        raise ValueError('Worker log rotated or changed during the evidence interval.')
    return current[len(previous):]


def peer_proof(before, after, source_log, target_log, source_ip, source_response, target_response):
    """Require transfer receipts and saved prompt work, not only a correct answer."""
    count = guard.delta(before['b'], after['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'})
    size = guard.delta(before['b'], after['b'], 'vllm:kv_offload_tiering_read_bytes', {'tier': '1:kvcr'})
    tokens = guard.delta(before['b'], after['b'], 'vllm:prompt_tokens_by_source', {'source': 'external_kv_transfer'})
    if not all(math.isfinite(n) and n > 0 and int(n) == n for n in (count, size, tokens)):
        raise ValueError('Need positive finite peer blocks, bytes and external-cache tokens.')
    for scope in ('remote_deliver', 'local_deliver'):
        for outcome in ('failed', 'partial'):
            if guard.delta(before['b'], after['b'], 'vllm:kvcr_duration_seconds_count',
                           {'scope': scope, 'result': outcome}) != 0:
                raise ValueError('Receiver recorded failed or partial cache delivery.')
    targets = [e for e in guard.event_fields(target_log, 'target_transfer_completed')
               if e.get('scope') == 'remote_deliver']
    sources = guard.event_fields(source_log, 'source_transfer_completed')
    if (not targets or any(e.get('result') != 'success' or e.get('source') != f'tcp://{source_ip}:23280'
                           for e in targets)):
        raise ValueError('Receiver did not transfer successfully from the expected source.')
    matched = []
    for target in targets:
        records = [e for e in sources if e.get('op') == target.get('op')]
        if len(records) != 1 or any(records[0].get(k) != target.get(k) for k in ('blocks', 'bytes', 'result')):
            raise ValueError('Source and receiver receipts do not match on the wire operation.')
        matched.append({'source': records[0], 'target': target})
    if sum(int(e['blocks']) for e in targets) != count or sum(int(e['bytes']) for e in targets) != size:
        raise ValueError('Transfer receipts and measured receiver counters disagree.')
    usage = target_response.get('usage') or {}
    cached = usage.get('prompt_tokens_details', {}).get('cached_tokens', 0)
    if cached <= 0 or tokens > cached or usage.get('prompt_tokens', 0) < cached:
        raise ValueError('Response usage does not confirm the external-cache reuse.')
    if source_response['workers'] == target_response['workers']:
        raise ValueError('Source and receiver must be distinct inference workers.')
    return {'status': 'passed', 'simulated': False, 'blocks': int(count), 'bytes': int(size),
            'external_cache_tokens': int(tokens), 'cached_prompt_tokens': cached,
            'prompt_tokens': usage['prompt_tokens'], 'matched_transfers': matched,
            'source_workers': source_response['workers'], 'target_workers': target_response['workers'],
            'scope': 'Controlled peer host-cache reuse; no under-load speedup or automatic routing claim.'}


def object_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def request_body(model, prompt):
    return {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
            'max_completion_tokens': OUTPUT_TOKENS, 'temperature': 0,
            'chat_template_kwargs': {'enable_thinking': False}, 'stream': True,
            'stream_options': {'include_usage': True}, 'nvext': {'extra_fields': ['worker_id', 'timing']}}


TOKENIZER_PROGRAM = '''import hashlib,json,os,sys
from collections.abc import Mapping
from numbers import Integral
from transformers import AutoTokenizer
import transformers
payload=json.load(sys.stdin)
assert os.environ['KVCR_MODEL']==payload['model']
assert os.environ['KVCR_MODEL_REVISION']==payload['revision']
tokenizer=AutoTokenizer.from_pretrained(payload['model'],revision=payload['revision'],trust_remote_code=True,local_files_only=True)
encoded={}
output_types={}
id_types={}
for role,body in payload['requests'].items():
 assert body['model']==payload['model']
 raw=tokenizer.apply_chat_template(body['messages'],tokenize=True,add_generation_prompt=True,return_dict=True,**body['chat_template_kwargs'])
 output_types[role]=type(raw).__module__+'.'+type(raw).__name__
 ids=raw['input_ids'] if isinstance(raw,Mapping) else raw
 id_types[role]=type(ids).__module__+'.'+type(ids).__name__
 if hasattr(ids,'tolist'):ids=ids.tolist()
 if isinstance(ids,tuple):ids=list(ids)
 if isinstance(ids,list) and len(ids)==1 and isinstance(ids[0],list):ids=ids[0]
 if not isinstance(ids,list) or not all(isinstance(t,Integral) and not isinstance(t,bool) and t>=0 for t in ids):
  raise TypeError('Unexpected tokenizer input_ids representation: '+type(raw).__name__+'/'+type(ids).__name__)
 encoded[role]=[int(t) for t in ids]
common=0
for a,b in zip(encoded['source'],encoded['target']):
 if a!=b:break
 common+=1
sha=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
print(json.dumps({'model':payload['model'],'revision':payload['revision'],
 'source_prompt_tokens':len(encoded['source']),'target_prompt_tokens':len(encoded['target']),
 'common_prefix_tokens':common,'input_sha256':sha(payload),
 'request_sha256':{role:sha(body) for role,body in payload['requests'].items()},
 'tokenizer_class':type(tokenizer).__module__+'.'+type(tokenizer).__name__,
 'tokenizer_output_types':output_types,'input_ids_types':id_types,
 'transformers_version':transformers.__version__,
 'scope':'CPU tokenizer only; no generation or cache seeding'}))
'''


def runtime_geometry(log):
    pages = {int(value) for value in re.findall(r'Setting attention block size to ([0-9]+) tokens', log)}
    limits = {int(value) for value in re.findall(r'Using max model len ([0-9]+)', log)}
    if len(pages) != 1 or len(limits) != 1 or min(pages | limits) <= 0:
        raise ValueError('Need unambiguous effective page and context limits from the current engine log; requested flags are insufficient.')
    return {'effective_page_tokens': pages.pop(), 'context_limit_tokens': limits.pop()}


def prompt_preflight_proof(payload, tokenized, geometries):
    if any(set(g) != {'effective_page_tokens', 'context_limit_tokens'} or
           any(type(v) is not int or v <= 0 for v in g.values()) or
           g['effective_page_tokens'] > g['context_limit_tokens'] for g in geometries.values()):
        raise ValueError('Effective page/context measurements must be positive compatible integers.')
    if (set(geometries) != {'a', 'b'} or geometries['a'] != geometries['b'] or
            tokenized.get('model') != payload['model'] or tokenized.get('revision') != payload['revision'] or
            tokenized.get('input_sha256') != object_sha256(payload) or
            tokenized.get('request_sha256') != {r: object_sha256(b) for r, b in payload['requests'].items()}):
        raise ValueError('Tokenizer inputs, model/revision or effective worker geometries do not match.')
    names = ('source_prompt_tokens', 'target_prompt_tokens', 'common_prefix_tokens')
    if any(type(tokenized.get(n)) is not int or tokenized[n] <= 0 for n in names):
        raise ValueError('Need positive integer measured prompt/common-prefix token counts.')
    common = tokenized['common_prefix_tokens']
    if common > min(tokenized['source_prompt_tokens'], tokenized['target_prompt_tokens']):
        raise ValueError('Common prefix cannot exceed either request.')
    page, limit = (geometries['a'][n] for n in ('effective_page_tokens', 'context_limit_tokens'))
    if common < page:
        raise ValueError(f'Shared prefix has {common} tokens, below one effective {page}-token cache page; no source request sent.')
    if any(tokenized[r + '_prompt_tokens'] + payload['requests'][r]['max_completion_tokens'] > limit
           for r in ('source', 'target')):
        raise ValueError('Fully templated prompt plus output budget exceeds the live engine context limit; no source request sent.')
    return {**tokenized, 'status': 'passed', 'simulated': False, 'checked_before_source_request': True,
            'effective_page_tokens': page, 'context_limit_tokens': limit, 'geometry_by_worker': geometries,
            'output_tokens': OUTPUT_TOKENS}


def coding_prefix(tag):
    # A bounded mechanism fixture, not a truncated or substituted AgentX benchmark.
    files = []
    for i in range(FIXTURE_FUNCTIONS):
        files.append(f'# repository/math_helpers/module_{i:03d}.py\n'
                     f'def helper_{i:03d}(values):\n'
                     '    """Return a stable total for the supplied values."""\n'
                     '    total = 0\n    for value in values:\n        total += value\n    return total\n')
    return f'Repository snapshot {tag}. Read this shared coding context:\n' + '\n'.join(files)


def repository(tag, modules, planted):
    """A synthetic Python repository, deterministic for its tag, defining each planted function exactly once.

    Returns the text and the file that defines each planted function. The agents ask where those functions
    live, so a correct answer depends on the whole context, including any part reused from another worker."""
    rng = random.Random(tag)
    homes = dict(zip(planted, rng.sample(range(modules // 4, modules - modules // 8), len(planted))))
    files = {home: PLANTED_FILES[k] for k, home in enumerate(homes.values())}
    parts = [f'Repository snapshot {tag}. Every file in the repository follows, each starting with its path.']
    paths = {}
    for i in range(modules):
        package = PACKAGES[i % len(PACKAGES)]
        noun = rng.choice(NOUNS)
        path = f'repository/{package}/' + (files[i] if i in files else f'{noun}_{i:04d}') + '.py'
        lines = [f'# {path}', f'"""{package.capitalize()} helpers, module {i}."""', '']
        for suffix in 'ab':
            verb, noun, limit = rng.choice(VERBS), rng.choice(NOUNS), rng.randrange(8, 96)
            lines += [f'def {verb}_{noun}_{i:04d}{suffix}(items, limit={limit}):',
                      f'    """{verb.capitalize()} up to {limit} {noun} items."""',
                      '    selected = [item for item in items if item is not None][:limit]',
                      '    return {"count": len(selected), "items": selected}', '']
        for name, home in homes.items():
            if home == i:
                paths[name] = path
                lines += [f'def {name}(store, now):', '    """Scheduled maintenance task."""', '    return store.apply(now)', '']
        parts.append('\n'.join(lines))
    return '\n'.join(parts), paths


def task(agent, function):
    who = 'Main agent' if agent == 'main' else 'Subagent (forked from the main agent)'
    return f'\n\n{who} task: which file defines the function `{function}`? Reply with the file path only.'


def speedup_body(model, prompt):
    return {**request_body(model, prompt), 'max_completion_tokens': ANSWER_TOKENS}


SPEEDUP_TOKENIZER_PROGRAM = '''import hashlib,json,os,sys
from collections.abc import Mapping
from numbers import Integral
from transformers import AutoTokenizer
import transformers
payload=json.load(sys.stdin)
assert os.environ['KVCR_MODEL']==payload['model']
assert os.environ['KVCR_MODEL_REVISION']==payload['revision']
tokenizer=AutoTokenizer.from_pretrained(payload['model'],revision=payload['revision'],trust_remote_code=True,local_files_only=True)
encoded={}
output_types={}
id_types={}
for role,body in payload['requests'].items():
 assert body['model']==payload['model']
 raw=tokenizer.apply_chat_template(body['messages'],tokenize=True,add_generation_prompt=True,return_dict=True,**body['chat_template_kwargs'])
 output_types[role]=type(raw).__module__+'.'+type(raw).__name__
 ids=raw['input_ids'] if isinstance(raw,Mapping) else raw
 id_types[role]=type(ids).__module__+'.'+type(ids).__name__
 if hasattr(ids,'tolist'):ids=ids.tolist()
 if isinstance(ids,tuple):ids=list(ids)
 if isinstance(ids,list) and len(ids)==1 and isinstance(ids[0],list):ids=ids[0]
 if not isinstance(ids,list) or not all(isinstance(t,Integral) and not isinstance(t,bool) and t>=0 for t in ids):
  raise TypeError('Unexpected tokenizer input_ids representation: '+type(raw).__name__+'/'+type(ids).__name__)
 encoded[role]=[int(t) for t in ids]
def common(a,b):
 n=0
 for x,y in zip(a,b):
  if x!=y:break
  n+=1
 return n
sha=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
print(json.dumps({'model':payload['model'],'revision':payload['revision'],
 'prompt_tokens':{role:len(ids) for role,ids in encoded.items()},
 'common_prefix_tokens':{name:common(encoded[a],encoded[b]) for name,(a,b) in payload['pairs'].items()},
 'input_sha256':sha(payload),
 'request_sha256':{role:sha(body) for role,body in payload['requests'].items()},
 'tokenizer_class':type(tokenizer).__module__+'.'+type(tokenizer).__name__,
 'tokenizer_output_types':output_types,'input_ids_types':id_types,
 'transformers_version':transformers.__version__,
 'scope':'CPU tokenizer only; no generation or cache seeding'}))
'''


def speedup_preflight_proof(payload, tokenized, geometries):
    """Size the speedup requests against the live engines: enough shared pages, a cold control, everything fits."""
    if any(set(g) != {'effective_page_tokens', 'context_limit_tokens'} or
           any(type(v) is not int or v <= 0 for v in g.values()) or
           g['effective_page_tokens'] > g['context_limit_tokens'] for g in geometries.values()):
        raise ValueError('Effective page/context measurements must be positive compatible integers.')
    if (set(geometries) != {'a', 'b'} or geometries['a'] != geometries['b'] or
            tokenized.get('model') != payload['model'] or tokenized.get('revision') != payload['revision'] or
            tokenized.get('input_sha256') != object_sha256(payload) or
            tokenized.get('request_sha256') != {r: object_sha256(b) for r, b in payload['requests'].items()}):
        raise ValueError('Tokenizer inputs, model/revision or effective worker geometries do not match.')
    prompts, common = tokenized.get('prompt_tokens'), tokenized.get('common_prefix_tokens')
    if (not isinstance(prompts, dict) or set(prompts) != set(payload['requests']) or
            not isinstance(common, dict) or set(common) != set(payload['pairs']) or
            any(type(v) is not int or v <= 0 for v in prompts.values()) or
            any(type(v) is not int or v < 0 for v in common.values())):
        raise ValueError('Need positive integer token counts for every request and request pair.')
    if any(common[name] > min(prompts[a], prompts[b]) for name, (a, b) in payload['pairs'].items()):
        raise ValueError('A common prefix cannot exceed either request.')
    page, limit = (geometries['a'][n] for n in ('effective_page_tokens', 'context_limit_tokens'))
    if common['main/sub'] < MIN_SHARED_PAGES * page:
        raise ValueError(f'Shared repository has {common["main/sub"]} tokens, below {MIN_SHARED_PAGES} effective '
                         f'{page}-token pages; no request sent.')
    if common['warmup_main/warmup_sub'] < page:
        raise ValueError('Warm-up context is below one effective page; no request sent.')
    if max(common['control/sub'], common['control/main']) >= page:
        raise ValueError('The control repository shares a reusable page with the shared repository.')
    if abs(prompts['control'] - prompts['sub']) > prompts['sub'] // 50:
        raise ValueError('Control and subagent prompts differ by more than 2%, so the comparison is not like for like.')
    if any(prompts[r] + payload['requests'][r]['max_completion_tokens'] > limit for r in payload['requests']):
        raise ValueError('Fully templated prompt plus output budget exceeds the live engine context limit; no request sent.')
    return {**tokenized, 'status': 'passed', 'simulated': False, 'checked_before_source_request': True,
            'effective_page_tokens': page, 'context_limit_tokens': limit, 'geometry_by_worker': geometries,
            'reusable_pages': common['main/sub'] // page, 'output_tokens': ANSWER_TOKENS}


def stream_request(base, body, worker, folder):
    """Send one frozen request pinned to a worker. Keeps the raw stream, this client's chunk times and the
    frontend's own timing record, which excludes the presenter's port-forward."""
    folder.mkdir(exist_ok=False)
    ui.write_json(folder / 'request.json', body)
    headers = {'x-dynamo-worker-instance-id': worker, 'x-dynamo-dp-rank': '0'}
    request = urllib.request.Request(base + '/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', **headers})
    chunks, events, raw = [], [], bytearray()
    status, read_error, done = None, None, False
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as stream:
            status = stream.status
            for line in stream:
                raw.extend(line)
                data = line.decode().strip()
                if data == 'data: [DONE]':
                    done = True
                    events.append({'seconds': time.monotonic() - started, 'done': True})
                elif data.startswith('data: '):
                    if done:
                        raise ValueError('Received more stream data after DONE.')
                    chunk = json.loads(data[6:])
                    chunks.append(chunk)
                    events.append({'seconds': time.monotonic() - started, 'chunk': chunk})
    except urllib.error.HTTPError as error:
        status = error.code
        raw.extend(error.read())
        read_error = str(error)
    except Exception as error:
        read_error = type(error).__name__ + ': ' + str(error)
    finally:
        (folder / 'response.sse').write_bytes(raw)
        ui.write_json(folder / 'events.json', events)
        ui.write_json(folder / 'http.json', {'status': status, 'headers': headers,
                                           'read_error': read_error, 'request_count': 1})
    errors = [c['error'] for c in chunks if c.get('error')]
    finishes = [x.get('finish_reason') for c in chunks for x in c.get('choices', []) if x.get('finish_reason')]
    workers = {str(c['nvext']['worker_id']['decode_worker_id']) for c in chunks
               if c.get('nvext', {}).get('worker_id', {}).get('decode_worker_id') is not None}
    ids = {c['id'] for c in chunks if c.get('id')}
    first = next((e['seconds'] for e in events if any((x.get('delta') or {}).get('content')
                                                      for x in (e.get('chunk') or {}).get('choices', []))), None)
    proof = {'http_requests': 1, 'status': status, 'done': done, 'errors': errors, 'read_error': read_error,
             'finishes': finishes, 'workers': sorted(workers), 'response_ids': sorted(ids),
             'content': ''.join(x.get('delta', {}).get('content') or '' for c in chunks for x in c.get('choices', [])),
             'usage': next((c['usage'] for c in reversed(chunks) if c.get('usage')), None),
             'timing': next((c['nvext']['timing'] for c in reversed(chunks) if c.get('nvext', {}).get('timing')), None),
             'client_first_token_seconds': first, 'client_total_seconds': events[-1]['seconds'] if events else None,
             'sse_sha256': ui.digest(folder / 'response.sse')}
    ui.write_json(folder / 'response.json', proof)
    if (status != 200 or not done or errors or read_error or not finishes or
            any(f not in ('stop', 'length') for f in finishes) or workers != {worker} or len(ids) != 1 or
            any(c.get('model') != body['model'] for c in chunks if c.get('choices')) or not proof['usage']):
        raise ValueError('Request did not finish successfully on its expected worker: ' + folder.name)
    return proof


def first_token_ms(proof):
    """The frontend's time to first token; this client's first chunk only if the frontend sent no timing."""
    timing = proof.get('timing') or {}
    if isinstance(timing.get('ttft_ms'), (int, float)):
        return float(timing['ttft_ms'])
    seconds = proof.get('client_first_token_seconds')
    return seconds * 1000 if isinstance(seconds, (int, float)) else None


def speedup_summary(responses, proof):
    rows = {}
    for role, response in responses.items():
        usage = response.get('usage') or {}
        rows[role] = {'worker': ROLES[role][0], 'repository': ROLES[role][1], 'prompt_tokens': usage.get('prompt_tokens'),
                      'cached_tokens': (usage.get('prompt_tokens_details') or {}).get('cached_tokens'),
                      'first_token_ms': first_token_ms(response),
                      'timing_source': 'frontend' if (response.get('timing') or {}).get('ttft_ms') is not None else 'client',
                      'answer_matches': response.get('answer_matches')}
    cold, warm = rows['control']['first_token_ms'], rows['sub']['first_token_ms']
    return {'simulated': bool(proof.get('simulated')), 'rows': rows,
            'first_token_speedup': round(cold / warm, 2) if cold and warm else None,
            'transfer': {k: proof.get(k) for k in ('blocks', 'bytes', 'external_cache_tokens')},
            'scope': 'Tailored mechanism demo: idle warmed workers, one long shared prefix, requests pinned by hand. '
                     'Not an under-load or automatic-routing result.'}


def bar(value, longest, width=34):
    return '█' * max(1, round(width * value / longest)) if value and longest else ''


class KVCRDemo(ui.Demo):
    """Two prepared Super VL workers share host-offloaded context through KVCR."""
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        args = copy.copy(args)
        args.run = args.run or ui.ROOT / 'results' / ('demo-07-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        self.args, self.run = args, Run(args.run)
        self.path, self.file, self.forward = self.run.path, self.run.path / 'demo.json', None
        lock = ui.read_json(SOURCE_LOCK)
        if self.file.exists():
            self.data = ui.read_json(self.file)
            if self.data['rehearsal'] != args.rehearsal or (
                    self.data.get('kvcr_profile') not in (PROFILE, LEGACY_PROFILE) and args.action != 'cleanup'):
                raise ValueError('Use the same mode/profile, or create a fresh run.')
            if args.placement and validate_placement(ui.read_json(args.placement)) != self.data['placement']:
                raise ValueError('Placement is frozen for this run; use a fresh run.')
            if args.source_bundle and str(args.source_bundle.resolve()) != self.data['source_bundle']:
                raise ValueError('Source-bundle path is frozen for this run; use a fresh run.')
            if args.action != 'cleanup':
                self.check_inputs()
        else:
            placement = validate_placement(ui.read_json(args.placement or PLACEMENT))
            suffix = hashlib.sha256(str(self.path).encode()).hexdigest()[:8]
            self.run.ns = 'dynamo-ft-r610-' + suffix + '-kvcrdemo'
            self.run.state['namespace'] = self.run.ns
            self.run.save()
            bundle = args.source_bundle or ui.ROOT / lock['qualified_source_run'] / 'sources' / lock['bundle_filename']
            candidate = {'configmap': 'kvcr-demo-source-' + lock['bundle_sha256'][:12],
                         'bundle_sha256': lock['bundle_sha256'], 'base_image': ui.read_json(ui.MODEL_LOCK)['runtime_image']}
            runtime = guard.RUNTIME.read_text()
            runtime_name = 'kvcr-demo-runtime-' + hashlib.sha256(runtime.encode()).hexdigest()[:12]
            graph, claims = render(self.run.ns, ui.read_json(ui.MODEL_LOCK), candidate, runtime_name, placement)
            for obj in (graph, *claims):
                obj['metadata']['labels'] = self.run.labels()
            manifest = {'apiVersion': 'v1', 'kind': 'List', 'items': [*claims, graph]}
            ui.write_json(self.path / 'deployment.json', manifest)
            support.write_yaml(self.path / 'deployment.yaml', manifest)
            (self.path / 'runtime.py').write_text(runtime)
            (self.path / 'bootstrap.py').write_bytes(guard.BOOTSTRAP.read_bytes())
            ui.write_json(self.path / 'source-lock.json', lock)
            ui.write_json(self.path / 'placement.json', placement)
            settings = {'workers': [{'name': p.upper(), 'GPUs': 2, 'node': v['node'].removeprefix('kubecon-nke-site-')}
                                     for p, v in placement.items()],
                        'agents': {'main agent': 'on A, reads the whole repository',
                                   'subagent': 'on B, same repository plus its own task'},
                        'context_window_tokens': CONTEXT_LIMIT,
                        'state_path': ['A GPU', 'A host pool', 'B host pool', 'B GPU'],
                        'kv_transfer': {'connector': 'OffloadingConnector', 'tier': 'kvcr',
                                        'host_pool_per_worker': '4 GiB', 'transport': 'NIXL / LIBFABRIC / EFA'},
                        'routing': 'Requests pinned to A and B by hand; choosing B automatically is the router\'s job.',
                        'runtime': 'Experimental pinned Dynamo nightly + vLLM/KVCR adapter.'}
            support.write_yaml(self.path / 'kvcr-settings.yaml', settings)
            facts = {}
            for name, filename in CONTEXTS.items():
                warmup = name == 'warmup'
                text, facts[name] = repository(uuid.uuid4().hex, WARMUP_MODULES if warmup else REPOSITORY_MODULES,
                                               WARMUP_PLANTED if warmup else PLANTED)
                (self.path / filename).write_text(text)
            model = ui.read_json(ui.MODEL_LOCK)
            requests = {}
            for role, (_, context, function, agent) in ROLES.items():
                prompt = (self.path / CONTEXTS[context]).read_text() + task(agent, function)
                requests[role] = speedup_body(model['model'], prompt)
                ui.write_json(self.path / (role + '-request.json'), requests[role])
            ui.write_json(self.path / 'prompt-preflight-input.json', {
                'model': model['model'], 'revision': model['revision'], 'requests': requests, 'pairs': PAIRS})
            (self.path / 'prompt-preflight-tokenizer.py').write_text(SPEEDUP_TOKENIZER_PROGRAM)
            self.data = {'schema': 1, 'kvcr_profile': PROFILE, 'demo_kind': 'kvcr', 'graph': GRAPH,
                         'rehearsal': args.rehearsal, 'namespace': self.run.ns, 'created_at': ui.now(),
                         'model': ui.read_json(ui.MODEL_LOCK)['model'], 'prepared': False, 'step': 0,
                         'repository_modules': REPOSITORY_MODULES, 'facts': facts,
                         'guard_harness_sha256': ui.digest(Path(guard.__file__)),
                         'placement': placement, 'source_bundle': str(Path(bundle).resolve()),
                         'candidate': candidate, 'runtime_configmap': runtime_name,
                         'lease': str(ui.ROOT / '.local' / ('workshop-demo-kvcr-' + suffix + '.gpu-lease')),
                         'pod_selector': 'workshop-kvcr-guard=true', 'resource_kinds': 'dgd',
                         'resource_note': 'Two TP2 workers / 4 H100s / separate host pools / experimental runtime',
                         'log_files': ['a-main.log', 'b-main.log'],
                         'inputs': {n: ui.digest(self.path / n) for n in (
                             'deployment.json', 'deployment.yaml', 'runtime.py', 'bootstrap.py', 'source-lock.json',
                             'placement.json', 'kvcr-settings.yaml', *CONTEXTS.values(),
                             *(role + '-request.json' for role in ROLES), 'prompt-preflight-input.json',
                             'prompt-preflight-tokenizer.py')}}
            self.save()
        self.ns = self.data['namespace']
        self.placement = validate_placement(self.data['placement'])
        self.lease = Path(self.data['lease'])
        self.compact_output = True
        if self.data.get('cleaned_at') and args.action not in ('cleanup', 'preview') and not args.preview:
            raise ValueError('This run was cleaned. Create a fresh run.')

    def check_inputs(self):
        for name, value in self.data['inputs'].items():
            if ui.digest(self.path / name) != value:
                raise ValueError('Frozen input changed: ' + name)
        if self.data.get('guard_harness_sha256') != ui.digest(Path(guard.__file__)):
            raise ValueError('KVCR request/metrics harness changed; use a fresh candidate.')

    @property
    def legacy(self):
        return self.data.get('kvcr_profile') == LEGACY_PROFILE

    @contextlib.contextmanager
    def scoped(self, node=None):
        with harness_scope(self.placement, self.lease, node=node):
            yield

    def preview(self):
        print((self.path / 'kvcr-settings.yaml').read_text())
        print('Full executable manifest: deployment.yaml')
        if self.legacy:
            print('Prime engines offstage; the onstage investigation seeds A then retrieves on B.')
        else:
            print('Prime and warm both engines offstage; onstage, A reads the repository, then B answers a '
                  'subagent from scratch and from A\'s context.')

    def require_lease(self):
        with self.scoped():
            guard.require_lease(self.run)

    def allocated_uuids(self, pod):
        from gpu_claims import verify_allocation
        claim = verify_allocation(self.run, pod, pod['spec']['containers'][0], 2)
        slices = self.run.get('get', 'resourceslices')['items']
        devices = {(s['spec']['pool']['name'], d['name']): d['attributes']['uuid']['string']
                   for s in slices if s['spec']['driver'] == 'gpu.nvidia.com' for d in s['spec'].get('devices', [])}
        results = claim['status']['allocation']['devices']['results']
        return sorted(devices[(d['pool'], d['device'])] for d in results)

    def pods(self):
        return self.run.get('get', 'pods', '-n', self.ns, '-l', self.data['pod_selector'])['items']

    def peers(self):
        peers = {p['metadata']['labels']['kvcr-peer']: p for p in self.pods()
                 if p['metadata']['labels'].get('kvcr-peer')}
        if set(peers) != {'a', 'b'}:
            raise ValueError('Need exactly the two owned worker Pods.')
        for peer, pod in peers.items():
            if (pod['metadata']['namespace'] != self.ns or
                    pod['metadata']['labels'].get('feature-test-run') != self.ns or
                    pod['spec'].get('nodeName') != self.placement[peer]['node'] or
                    pod['spec'].get('hostPID') or pod['spec'].get('shareProcessNamespace')):
                raise ValueError('Worker ownership, placement or isolation changed.')
        return peers

    def prepare(self):
        self.check_inputs()
        if self.data['prepared']:
            if not self.args.rehearsal:
                self.require_lease()
            return
        if not self.args.rehearsal and (self.path / 'model-lock.json').exists():
            raise RuntimeError('Preparation was interrupted before its gates completed. Preserve these receipts, '
                               'run this attempt\'s cleanup, then prime a fresh --run directory. '
                               'Preparation gates and immutable ConfigMaps are not replayed.')
        if self.args.rehearsal:
            print('[REHEARSAL] Model/cache, frozen sources, GPU isolation and CPU API gates simulated.')
        else:
            lock = ui.read_json(self.path / 'source-lock.json')
            bundle = Path(self.data['source_bundle'])
            if not bundle.is_file() or ui.digest(bundle) != lock['bundle_sha256']:
                raise ValueError('Need the exact source bundle recorded in source-lock.json; no cluster changes made.')
            if ui.digest(self.path / 'bootstrap.py') != lock['bootstrap_sha256']:
                raise ValueError('Bootstrap differs from the source-qualified stack.')
            with self.scoped():
                ui.acquire(self.path, OWNER)
            from r610_feature_retests import prepare
            prepare(self.run, self.path, 'kvcrdemo')
            if self.run.ns != self.ns:
                raise ValueError('Preparation namespace mismatch.')
            model = copy.deepcopy(self.run.state['model_lock'])
            model.update(runtime_overlay=lock['nightly'], runtime_release=lock['nightly']['version'])
            self.run.state['model_lock'] = model
            ui.write_json(self.path / 'model-lock.json', model)
            self.run.save()
            shutil.copyfile(bundle, self.path / 'source-bundle.tar.gz')
            candidate = self.data['candidate']
            obj = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {
                'name': candidate['configmap'], 'namespace': self.ns, 'labels': self.run.labels()}, 'immutable': True,
                'data': {'bootstrap.py': (self.path / 'bootstrap.py').read_text()},
                'binaryData': {'bundle.tar.gz': base64.b64encode(bundle.read_bytes()).decode()}}
            if len(json.dumps(obj).encode()) >= 1000000:
                raise ValueError('Source ConfigMap exceeds its budget.')
            ui.write_json(self.path / 'source-configmap.json', obj)
            self.run.k('create', '--dry-run=server', '-f', str(self.path / 'source-configmap.json'))
            self.run.k('create', '-f', str(self.path / 'source-configmap.json'))
            runtime = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': self.data['runtime_configmap']},
                       'immutable': True, 'data': {'runtime.py': (self.path / 'runtime.py').read_text()}}
            self.run.apply([runtime])
            self.cpu_gate()
            self.early_prompt_size_gate()
            for peer in ('a', 'b'):
                self.native_gate(peer)
            self.run.k('apply', '--dry-run=client', '-f', str(self.path / 'deployment.json'))
            self.run.k('apply', '--dry-run=server', '-f', str(self.path / 'deployment.json'))
        self.data['prepared'] = True
        self.save()

    def early_prompt_size_gate(self):
        """Cheap CPU sizing check; final acceptance still uses live worker geometry."""
        from snapshot_tp2_workflow import cpu_probe
        from serving_tests import model_cache_home
        payload = ui.read_json(self.path / 'prompt-preflight-input.json')
        # Linux caps one environment string at 128 KiB; the speedup payload is about 700 KB of JSON before gzip.
        packed = base64.b64encode(gzip.compress(json.dumps(payload).encode(), 9, mtime=0)).decode()
        program = ('import base64,gzip,io,os,sys\nsys.stdin=io.StringIO(gzip.decompress('
                   'base64.b64decode(os.environ["KVCR_PREFLIGHT_PAYLOAD"])).decode())\n' +
                   (self.path / 'prompt-preflight-tokenizer.py').read_text())
        record = cpu_probe(self.run, 'kvcr-prompt-size-cpu', program, [
            {'name': 'HF_HOME', 'value': model_cache_home(self.run)},
            {'name': 'HF_MODULES_CACHE', 'value': '/tmp/kvcr-tokenizer-modules'},
            {'name': 'HF_HUB_OFFLINE', 'value': '1'},
            {'name': 'TRANSFORMERS_OFFLINE', 'value': '1'},
            {'name': 'KVCR_MODEL', 'value': payload['model']},
            {'name': 'KVCR_MODEL_REVISION', 'value': payload['revision']},
            {'name': 'KVCR_PREFLIGHT_PAYLOAD', 'value': packed}], cache=True)
        # Retained a3's pinned model/profile established the 4,224-token page; the speedup profile sets its own
        # context limit. This CPU result does not qualify geometry of the future live engines.
        reference = {'effective_page_tokens': 4224, 'context_limit_tokens': 8192 if self.legacy else CONTEXT_LIMIT}
        (prompt_preflight_proof if self.legacy else speedup_preflight_proof)(payload, record, {'a': reference, 'b': reference})
        ui.write_json(self.path / 'prompt-size-cpu.json', {
            'status': 'passed', 'at': ui.now(), 'tokenizer': record,
            'reference_geometry': reference, 'live_geometry_qualified': False,
            'scope': 'CPU sizing against reference limits before GPU allocation; live-worker preflight remains mandatory.'})
        shared = record['common_prefix_tokens'] if self.legacy else record['common_prefix_tokens']['main/sub']
        print(f'CPU fixture sizing: {shared} shared tokens; '
              'reference bounds pass before GPU startup. Live geometry will be checked after readiness.', flush=True)

    def cpu_gate(self):
        name = 'kvcr-demo-cpu-gate'
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
            'restartPolicy': 'Never', 'activeDeadlineSeconds': 300, 'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': self.placement['a']['node']},
            'imagePullSecrets': [{'name': 'common-runtime-pull'}],
            'containers': [{'name': 'main', 'image': self.data['candidate']['base_image'],
                'command': ['python3', '/candidate/bootstrap.py', 'check'],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                        {'name': 'KVCR_BUNDLE_SHA256', 'value': self.data['candidate']['bundle_sha256']}],
                'securityContext': {'runAsUser': 0}, 'resources': {'requests': {'cpu': '1', 'memory': '4Gi'},
                                                                               'limits': {'memory': '8Gi'}},
                'volumeMounts': [{'name': 'candidate', 'mountPath': '/candidate', 'readOnly': True}]}],
            'volumes': [{'name': 'candidate', 'configMap': {'name': self.data['candidate']['configmap']}}]}}
        self.run.apply([pod])
        try:
            finished = self.run.wait_pod(name, completed=True, timeout=360)
            log = self.run.k('logs', name, '-n', self.ns).stdout
            (self.path / 'cpu-gate.log').write_text(log)
            result = json.loads(log.strip().splitlines()[-1])
            nightly = ui.read_json(self.path / 'source-lock.json')['nightly']['version']
            if (result.get('status') != 'passed' or any(result['packages'][n] != nightly
                    for n in ('ai-dynamo', 'ai-dynamo-runtime')) or any(
                    s['imageID'].split('@')[-1] != self.data['candidate']['base_image'].split('@')[-1]
                    for s in finished['status']['containerStatuses'])):
                raise ValueError('CPU overlay/image gate did not pass.')
            ui.write_json(self.path / 'cpu-gate.json', result)
        finally:
            self.run.k('delete', 'pod', name, '-n', self.ns, '--ignore-not-found', '--wait=true', '--timeout=60s')

    def native_gate(self, peer):
        source = ui.read_json(self.path / 'deployment.json')
        claim = copy.deepcopy(next(o for o in source['items'] if o['kind'] == 'ResourceClaimTemplate'
                                   and o['metadata']['name'].endswith('-' + peer + '-gpus')))
        claim['metadata']['name'] = 'kvcr-native-' + peer + '-gpus'
        spec = {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180, 'runtimeClassName': 'nvidia-legacy',
                'nodeSelector': {'kubernetes.io/hostname': self.placement[peer]['node']},
                'imagePullSecrets': [{'name': 'common-runtime-pull'}], 'automountServiceAccountToken': False,
                'resourceClaims': [{'name': 'gpu-main', 'resourceClaimTemplateName': claim['metadata']['name']}],
                'volumes': [{'name': 'efa', 'configMap': {'name': 'efa-userspace'}}], 'containers': []}
        cuda = """import ctypes,json,uuid
d=ctypes.CDLL('libcuda.so.1');assert d.cuInit(0)==0
n=ctypes.c_int();assert d.cuDeviceGetCount(ctypes.byref(n))==0;assert n.value==2
uuids=[]
for ordinal in range(n.value):
 device=ctypes.c_int();assert d.cuDeviceGet(ctypes.byref(device),ordinal)==0
 value=ctypes.create_string_buffer(16);assert d.cuDeviceGetUuid_v2(ctypes.byref(value),device)==0
 uuids.append('GPU-'+str(uuid.UUID(bytes=value.raw)))
print(json.dumps({'status':'passed','GPUs':n.value,'gpu_uuids':sorted(uuids)}))
"""
        host = "import ctypes,json,glob;ctypes.CDLL('libcuda.so.1');from nixl._api import nixl_agent,nixl_agent_config;a=nixl_agent('kvcr-native-probe',nixl_agent_config(num_threads=1,capture_telemetry=False,enable_listen_thread=True,listen_port=0,backends=['LIBFABRIC']));b=ctypes.create_string_buffer(1048576);r=a.register_memory([(ctypes.addressof(b),len(b),0,'')],mem_type='DRAM');assert a.deregister_memory(r) is not False;assert not glob.glob('/dev/nvidia[0-9]*');print(json.dumps({'status':'passed','GPU_devices':[]}))"
        for name, code in [('main', cuda), ('guard', host)]:
            container = {'name': name, 'image': self.data['candidate']['base_image'],
                'command': (['python3', '-c', code] if name == 'main' else ['bash', '/efa/entrypoint.sh', 'python3', '-c', code]),
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void' if name == 'main' else 'none'}],
                'resources': {'requests': {'cpu': '1', 'memory': '2Gi'}, 'limits': {'memory': '4Gi'}}}
            if name == 'main':
                container['resources']['claims'] = [{'name': 'gpu-main'}]
            else:
                container['env'] += [{'name': k, 'value': v} for k, v in {
                    'NVIDIA_DRIVER_CAPABILITIES': 'compute,utility', 'FI_PROVIDER': 'efa',
                    'FI_EFA_FORK_SAFE': '1', 'FI_EFA_ENABLE_SHM_TRANSFER': '0',
                    'FI_HMEM_CUDA_USE_DMABUF': '1', 'NIXL_LOG_LEVEL': 'INFO'}.items()]
                for kind in ('requests', 'limits'):
                    container['resources'][kind]['vpc.amazonaws.com/efa'] = '1'
                container['securityContext'] = {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK']}}
                container['volumeMounts'] = [{'name': 'efa', 'mountPath': '/efa', 'readOnly': True}]
            spec['containers'].append(container)
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'kvcr-native-' + peer}, 'spec': spec}
        self.run.apply([claim, pod])
        try:
            finished = self.run.wait_pod(pod['metadata']['name'], completed=True, timeout=240)
            logs = {c: self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', c).stdout
                    for c in ('main', 'guard')}
            results = {}
            for container, log in logs.items():
                (self.path / ('native-' + peer + '-' + container + '.log')).write_text(log)
                records = [json.loads(l) for l in log.splitlines() if l.startswith('{')]
                if len(records) != 1 or records[0].get('status') != 'passed':
                    raise ValueError('Native driver/EFA probe failed.')
                results[container] = records[0]
            uuids = results['main'].get('gpu_uuids')
            if uuids != sorted(self.placement[peer]['gpu_uuids']):
                raise ValueError('Native CUDA probe saw a different reserved GPU pair.')
            if any(s['imageID'].split('@')[-1] != self.data['candidate']['base_image'].split('@')[-1]
                   for s in finished['status']['containerStatuses']):
                raise ValueError('Native probe ran another image.')
            if 'using provider=efa' not in logs['guard']:
                raise ValueError('Native host transfer probe did not select EFA.')
            ui.write_json(self.path / ('native-' + peer + '.json'), {'status': 'passed', 'gpu_uuids': uuids,
                          'node': self.placement[peer]['node'], 'pod_uid': finished['metadata']['uid']})
        finally:
            self.run.k('delete', 'pod', pod['metadata']['name'], '-n', self.ns, '--ignore-not-found', '--wait=true', '--timeout=60s')
            self.run.k('delete', 'resourceclaimtemplate', claim['metadata']['name'], '-n', self.ns, '--ignore-not-found')

    def deploy(self):
        self.check_inputs()
        if self.data.get('apply_started_at'):
            return
        self.show_command(self.run.kbase + ['apply', '-f', str(self.path / 'deployment.yaml')])
        if self.args.rehearsal:
            print('[REHEARSAL] Two workers and their host pools created (simulated).')
        else:
            self.require_lease()
            if self.run.get('get', 'dgd', '-n', self.ns)['items']:
                raise ValueError('Expected an empty owned namespace.')
        self.data['apply_started_at'] = ui.now()
        self.save()
        if not self.args.rehearsal:
            self.run.apply(ui.read_json(self.path / 'deployment.json')['items'])

    def wait(self):
        if self.args.rehearsal:
            print('[REHEARSAL] Both engines and host services Ready; startup is not measured.')
        else:
            deadline = time.monotonic() + self.args.timeout
            while time.monotonic() < deadline:
                pods = self.pods()
                support.healthy(pods)
                for pod in pods:
                    peer = pod['metadata']['labels'].get('kvcr-peer')
                    if peer:
                        log = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--timestamps=true', check=False)
                        (self.path / (peer + '-main.log')).write_text(log.stdout + log.stderr)
                if len(pods) == 3 and all(any(c['type'] == 'Ready' and c['status'] == 'True'
                        for c in p.get('status', {}).get('conditions', [])) for p in pods):
                    baseline = self.peers()
                    identities = guard.worker_ids(self.run, baseline)
                    if set(identities) != {'a', 'b'}:
                        time.sleep(3)
                        continue
                    for peer, pod in baseline.items():
                        if self.allocated_uuids(pod) != sorted(self.placement[peer]['gpu_uuids']):
                            raise ValueError('Worker allocated a different reserved GPU pair.')
                        if any(s['imageID'].split('@')[-1] != self.data['candidate']['base_image'].split('@')[-1]
                               for s in pod['status']['containerStatuses']):
                            raise ValueError('Worker image changed.')
                    ui.write_json(self.path / 'ready-pods.json', {'items': pods})
                    ui.write_json(self.path / 'worker-ids.json', identities)
                    break
                time.sleep(8)
            else:
                raise TimeoutError('KVCR engines did not become Ready.')
        self.data.setdefault('ready_observed_at', ui.now())
        self.save()
        total = None if self.args.rehearsal else (dt.datetime.fromisoformat(self.data['ready_observed_at']) -
                dt.datetime.fromisoformat(self.data['apply_started_at'])).total_seconds()
        ui.write_json(self.path / 'timing.json', {'simulated': self.args.rehearsal, 'apply_to_observed_ready_seconds': total,
                      'scope': 'Shared EFS/network can overlap other demos; not an isolated startup benchmark.'})
        print('Startup timing: ' + ('not measured (rehearsal)' if total is None else f'{total:.1f}s apply to observed Ready'))

    def prime(self):
        self.prepare()
        if self.data.get('ready_observed_at'):
            self.check_identity()
            self.ensure_prompt_preflight()
            if not self.legacy:
                self.warm_up()
            print('Already primed; original worker identities and startup clock retained.')
            return
        self.deploy()
        self.wait()
        self.ensure_prompt_preflight()
        if not self.legacy:
            self.warm_up()
        print('Primed. Keep both workers alive for the onstage cache-movement investigation.')

    def check_identity(self):
        if self.args.rehearsal:
            return
        self.require_lease()
        initial = {p['metadata']['labels']['kvcr-peer']: p for p in ui.read_json(self.path / 'ready-pods.json')['items']
                   if p['metadata']['labels'].get('kvcr-peer')}
        current = self.peers()
        support.healthy(list(current.values()))
        guard.stable_containers(initial, current)

    def ensure_prompt_preflight(self):
        """Measure the exact common token prefix before either generation request."""
        self.check_inputs()
        self.check_identity()
        receipt = self.path / 'prompt-preflight.json'
        payload = ui.read_json(self.path / 'prompt-preflight-input.json')
        check = prompt_preflight_proof if self.legacy else speedup_preflight_proof
        if receipt.exists():
            if ui.digest(receipt) != self.data.get('prompt_preflight_sha256'):
                raise ValueError('Prompt-preflight receipt changed or lacks a completed hash binding.')
            proof = ui.read_json(receipt)
            if proof.get('simulated') is not self.args.rehearsal:
                raise ValueError('Prompt-preflight mode changed.')
            for name, sha in proof.get('evidence_sha256', {}).items():
                if ui.digest(self.path / name) != sha:
                    raise ValueError('Prompt-preflight evidence changed: ' + name)
            if not self.args.rehearsal:
                check(payload, proof, proof['geometry_by_worker'])
                current = {p: pod['metadata']['uid'] for p, pod in self.peers().items()}
                if current != proof.get('worker_pod_uids') or proof.get('status') != 'passed':
                    raise ValueError('Prompt preflight does not belong to the current worker Pods.')
            return proof
        if any((self.path / role / 'response.json').exists() for role in ('source', 'target', *ROLES)):
            raise ValueError('Token/page preflight must precede all source and receiver HTTP requests.')
        intent = self.path / 'prompt-preflight-started.json'
        if intent.exists():
            raise ValueError('An earlier prompt preflight is incomplete; preserve it and use a fresh run.')
        with intent.open('x') as stream:
            stream.write(json.dumps({'started_at': ui.now(), 'input_sha256': object_sha256(payload),
                                     'source_request_sent': False}) + '\n')
        evidence = []
        try:
            if self.args.rehearsal:
                proof = {'status': 'illustrative', 'simulated': True, 'checked_before_source_request': True,
                         'source_prompt_tokens': None, 'target_prompt_tokens': None, 'common_prefix_tokens': None,
                         'effective_page_tokens': None, 'context_limit_tokens': None,
                         'scope': 'Simulated token/page preflight; no tokenizer or engine geometry measured.'}
                print('[REHEARSAL] Tokenizer/page preflight simulated; no token counts measured.')
            else:
                pods = self.peers()
                geometries = {}
                for peer, pod in pods.items():
                    log = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'main',
                                     '--timestamps=true', '--limit-bytes=10000000').stdout
                    path = self.path / ('prompt-preflight-worker-' + peer + '.log')
                    with path.open('x') as stream:
                        stream.write(log)
                    evidence.append(path)
                    geometries[peer] = runtime_geometry(log)
                program = (self.path / 'prompt-preflight-tokenizer.py').read_text()
                result = self.run.k('exec', '-i', pods['a']['metadata']['name'], '-n', self.ns, '-c', 'main', '--',
                                    'python3', '-c', program, input_text=json.dumps(payload), timeout=120)
                log_path = self.path / 'prompt-preflight-tokenizer.log'
                with log_path.open('x') as stream:
                    stream.write(result.stdout + result.stderr)
                evidence.append(log_path)
                records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
                if len(records) != 1:
                    raise ValueError('Need one unambiguous cached-tokenizer result.')
                raw = self.path / 'prompt-preflight-tokenized.json'
                ui.write_json(raw, records[0])
                evidence.append(raw)
                proof = check(payload, records[0], geometries)
                proof['worker_pod_uids'] = {p: pod['metadata']['uid'] for p, pod in pods.items()}
                self.check_identity()
                if self.legacy:
                    print(f'Prompt preflight: {proof["common_prefix_tokens"]} shared tokens cover a '
                          f'{proof["effective_page_tokens"]}-token effective page; both requests fit '
                          f'{proof["context_limit_tokens"]} tokens including output.')
                else:
                    print(f'Prompt preflight: {proof["common_prefix_tokens"]["main/sub"]:,} shared repository tokens, '
                          f'{proof["reusable_pages"]} reusable {proof["effective_page_tokens"]}-token pages; every '
                          f'request fits {proof["context_limit_tokens"]:,} tokens including output.')
            proof['evidence_sha256'] = {p.name: ui.digest(p) for p in evidence}
            proof['completed_at'] = ui.now()
            with receipt.open('x') as stream:
                stream.write(json.dumps(proof, indent=2) + '\n')
            self.data['prompt_preflight_sha256'] = ui.digest(receipt)
            self.save()
            return proof
        except BaseException as error:
            ui.write_json(self.path / 'prompt-preflight-failure.json', {
                'status': 'failed', 'at': ui.now(), 'error': type(error).__name__ + ': ' + str(error),
                'source_request_sent': False, 'scope': 'Preflight stopped before generation; original inputs retained.'})
            raise

    def metrics(self, label):
        self.check_identity()
        folder = self.path / label
        folder.mkdir(exist_ok=False)
        pods = self.peers()
        ui.write_json(folder / 'pods.json', pods)
        result = {}
        code = "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9090/metrics',timeout=5).read().decode())"
        for peer, pod in pods.items():
            result[peer] = self.run.k('exec', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--', 'python3', '-c', code).stdout
            (folder / (peer + '-metrics.txt')).write_text(result[peer])
            for container in ('main', 'kvcr-services'):
                log = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', container,
                                 '--timestamps=true', '--limit-bytes=10000000').stdout
                (folder / (peer + '-' + container + '.log')).write_text(log)
        return result

    def source(self):
        self.check_identity()
        preflight = self.ensure_prompt_preflight()
        if self.data.get('source_completed_at'):
            print('Source seeding already completed in this run; its HTTP request is not repeated.')
            print('Saved response: ' + ui.read_json(self.path / 'source/response.json')['content'])
            return
        self.endpoint()
        if self.data.get('source_request_started_at') or (self.path / 'source/response.json').exists():
            raise ValueError('Source request already exists; use a fresh run rather than replaying it.')
        prompt = (self.path / 'shared-context.txt').read_text() + SOURCE_SUFFIX
        ids = {'a': 'example-A', 'b': 'example-B'} if self.args.rehearsal else guard.worker_ids(self.run, self.peers())
        if set(ids) != {'a', 'b'}:
            raise ValueError('Both current endpoints must be registered.')
        ui.write_json(self.path / 'worker-ids.json', ids)
        self.request_command('source', prompt, ids['a'])
        if self.args.rehearsal:
            proof = {'simulated': True, 'workers': ['example-A'], 'content': 'READY', 'usage': {'prompt_tokens': None}}
            (self.path / 'source').mkdir()
            ui.write_json(self.path / 'source/response.json', proof)
            print('[REHEARSAL] A computed and committed the shared prefix; no tokens or bytes measured.')
        else:
            self.metrics('before-seed')
            self.data['source_request_started_at'] = ui.now()
            self.save()
            proof = guard.response(self.run, self.data['base_url'], 'source', prompt, ids['a'])
            if object_sha256(ui.read_json(self.path / 'source/request.json')) != preflight['request_sha256']['source']:
                raise ValueError('Submitted source request differs from the tokenized preflight body.')
            if proof['usage'].get('prompt_tokens') != preflight['source_prompt_tokens']:
                raise ValueError('Source server token usage differs from tokenizer preflight; no receiver request sent.')
            if proof['usage'].get('prompt_tokens_details', {}).get('cached_tokens', 0):
                raise ValueError('Fresh source request unexpectedly reused cached prompt tokens.')
            print(proof['content'])
            # Offload and state-agent publication may trail HTTP completion.
            time.sleep(15)
            before = self.metrics('before-peer')
            old = {p: (self.path / 'before-seed' / (p + '-metrics.txt')).read_text() for p in ('a', 'b')}
            if (guard.delta(old['a'], before['a'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) <= 0 or
                    guard.delta(old['a'], before['a'], 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'}) <= 0 or
                    guard.delta(old['b'], before['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) != 0):
                raise ValueError('Source-only committed host cache was not established.')
            print('A committed reusable context in its host pool; B has not processed this prefix.')
        self.data['source_completed_at'] = ui.now()
        self.save()

    def target(self):
        self.check_identity()
        preflight = self.ensure_prompt_preflight()
        if not self.data.get('source_completed_at'):
            raise ValueError('Source commit gate has not completed; no receiver request sent.')
        if self.data.get('target_completed_at'):
            print('Peer request already completed in this run; original transfer evidence retained, no new HTTP request.')
            return
        if not self.forward:
            self.endpoint()
        if self.data.get('target_request_started_at') or (self.path / 'target/response.json').exists():
            raise ValueError('Receiver request already exists; inspect it instead of replaying.')
        ids = ui.read_json(self.path / 'worker-ids.json')
        prompt = (self.path / 'shared-context.txt').read_text() + TARGET_SUFFIX
        self.request_command('target', prompt, ids['b'])
        if self.args.rehearsal:
            response = {'simulated': True, 'workers': ['example-B'], 'content': 'READY', 'usage': {'cached_tokens': None}}
            proof = {'simulated': True, 'status': 'illustrative', 'blocks': None, 'bytes': None,
                     'external_cache_tokens': None, 'scope': 'No measured cache transfer or performance.'}
        else:
            self.data['target_request_started_at'] = ui.now()
            self.save()
            response = guard.response(self.run, self.data['base_url'], 'target', prompt, ids['b'])
            if object_sha256(ui.read_json(self.path / 'target/request.json')) != preflight['request_sha256']['target']:
                raise ValueError('Submitted receiver request differs from the tokenized preflight body.')
            if response['usage'].get('prompt_tokens') != preflight['target_prompt_tokens']:
                raise ValueError('Receiver server token usage differs from tokenizer preflight.')
            print(response['content'])
            time.sleep(15)
            after = self.metrics('after-peer')
            before = {p: (self.path / 'before-peer' / (p + '-metrics.txt')).read_text() for p in ('a', 'b')}
            logs = {p: interval_log((self.path / 'before-peer' / (p + '-main.log')).read_text(),
                                   (self.path / 'after-peer' / (p + '-main.log')).read_text()) for p in ('a', 'b')}
            source_ip = self.peers()['a']['status']['podIP']
            proof = peer_proof(before, after, logs['a'], logs['b'], source_ip,
                               ui.read_json(self.path / 'source/response.json'), response)
            for peer in ('a', 'b'):
                if 'using provider=efa' not in (self.path / 'after-peer' / (peer + '-main.log')).read_text():
                    raise ValueError('Missing EFA transport evidence for ' + peer)
            proof.update(cross_node=self.placement['a']['node'] != self.placement['b']['node'],
                         placement=self.placement, worker_identities_unchanged=True)
        ui.write_json(self.path / 'response.json', response)
        ui.write_json(self.path / 'peer-proof.json', proof)
        ui.write_json(self.path / 'peer-summary.json', {k: proof[k] for k in (
            'status', 'blocks', 'bytes', 'external_cache_tokens', 'cached_prompt_tokens', 'prompt_tokens', 'cross_node') if k in proof})
        self.data['target_completed_at'] = ui.now()
        self.save()
        print('Receiver cache-reuse evidence saved.')

    def request_command(self, label, prompt, worker):
        if request_body(self.data['model'], prompt) != ui.read_json(self.path / (label + '-request.json')):
            raise ValueError('Displayed request differs from the frozen preflight body.')
        print(f'Request: shared repository context, {len(prompt)} characters; new {label} instruction. Full JSON retained.')
        self.show_command(['curl', '--fail', '--silent', '--show-error', '--no-buffer',
                           self.data['base_url'] + '/v1/chat/completions', '-H', 'Content-Type: application/json',
                           '-H', 'x-dynamo-worker-instance-id: ' + worker, '-H', 'x-dynamo-dp-rank: 0',
                           '--data-binary', '@' + label + '-request.json'])

    def evidence(self):
        self.check_identity()
        proof = ui.read_json(self.path / 'peer-proof.json')
        self.command(['cat', self.path / 'peer-summary.json'])
        print('Same prefix, different worker. Host cache moves through KVCR and avoids repeated prompt work.')
        print('Full receipts: peer-proof.json. This proof does not measure a speedup under load.')
        print('Routing selects where to compute; KVCR supplies committed context to that worker.')

    def require_primed(self):
        """Require the completed offstage startup and token/page checks."""
        self.check_inputs()
        receipt, warmup = self.path / 'prompt-preflight.json', self.path / 'warmup.json'
        if (not self.data.get('prepared') or not self.data.get('ready_observed_at') or
                not receipt.is_file() or not self.data.get('prompt_preflight_sha256') or
                (not self.legacy and (not warmup.is_file() or not self.data.get('warmup_sha256')))):
            command = shlex.join(ui.presenter_command(self.entrypoint, 'prime', '--run', ui.repo_path(self.path)))
            raise RuntimeError('Prime this run offstage before opening the demo:\n' + command)
        if ui.digest(receipt) != self.data['prompt_preflight_sha256']:
            raise ValueError('Prompt-preflight receipt changed or lacks a completed hash binding.')
        if not self.legacy and ui.digest(warmup) != self.data['warmup_sha256']:
            raise ValueError('Warm-up receipt changed or lacks a completed hash binding.')

    def prepared_workers(self):
        self.require_primed()
        self.check_identity()
        self.ensure_prompt_preflight()
        if self.args.rehearsal:
            print('[REHEARSAL] Workers ready: two TP2 engines and separate host pools; no startup measurement.')
        else:
            print('Workers ready: two TP2 engines and separate host pools; startup completed offstage.')
            print(ui.compact_resource_table(self.pods(), pods_only=True))

    def guided(self):
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive mode needs a terminal; use --rehearsal --plain --auto offline.')
        if self.args.rehearsal and not (self.data.get('ready_observed_at') and
                                      (self.path / 'prompt-preflight.json').is_file()):
            # Simulate an offstage-primed pair, without projecting preparation.
            previous_auto = self.args.auto
            self.args.auto = True
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.prime()
            finally:
                self.args.auto = previous_auto
        self.require_primed()
        print('\nDynamo workshop · ' + ('KVCR context movement' if self.legacy else 'KVCR: reuse another worker\'s context') +
              '\n' + ('REHEARSAL / SIMULATED OUTPUT / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE CLUSTER / EXPERIMENTAL STACK'))
        if self.legacy:
            self.run_steps(STEPS, [lambda: self.command(['cat', self.path / 'kvcr-settings.yaml']),
                                   self.prepared_workers, self.source, self.target, self.evidence])
        else:
            self.run_steps(SPEEDUP_STEPS, [self.scenario, self.warm_workers, self.main_agent, self.subagents, self.compare])

    @contextlib.contextmanager
    def offstage_endpoint(self):
        """A private port-forward for warm-up requests; nothing is shown on the projected screen."""
        services = [s for s in self.run.get('get', 'services', '-n', self.ns)['items']
                    if s['metadata']['name'].startswith(GRAPH + '-') and any(p['port'] == 8000 for p in s['spec'].get('ports', []))]
        if len(services) != 1:
            raise RuntimeError('Expected exactly one frontend HTTP Service.')
        args = self.run.kbase + ['port-forward', '-n', self.ns, 'service/' + services[0]['metadata']['name'],
                                 f'{self.args.port}:8000', '--address=127.0.0.1']
        with (self.path / 'warmup-port-forward.log').open('a') as output:
            forward = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT)
        base = f'http://127.0.0.1:{self.args.port}'
        try:
            for _ in range(30):
                if forward.poll() is not None:
                    raise RuntimeError('Warm-up port forward stopped; see warmup-port-forward.log.')
                try:
                    with urllib.request.urlopen(base + '/v1/models', timeout=2) as response:
                        if self.data['model'] in [m['id'] for m in json.load(response).get('data', [])]:
                            break
                except (OSError, ValueError):
                    pass
                time.sleep(1)
            else:
                raise TimeoutError('Warm-up model discovery did not become available.')
            yield base
        finally:
            forward.terminate()
            try:
                forward.wait(timeout=10)
            except subprocess.TimeoutExpired:
                forward.kill()
                forward.wait()

    def metric_text(self, pod):
        return self.run.k('exec', pod['metadata']['name'], '-n', self.ns, '-c', 'main', '--',
                          'python3', '-c', METRICS_PROGRAM).stdout

    def snapshot(self, label, texts=None):
        """Both workers' metrics under a label (no logs, so it costs two short execs). A recorded label is read
        back, never retaken."""
        folder = self.path / label
        if (folder / 'snapshot.json').is_file():
            return {p: (folder / (p + '-metrics.txt')).read_text() for p in ('a', 'b')}
        if texts is None:
            texts = {'a': '', 'b': ''} if self.args.rehearsal else {p: self.metric_text(pod) for p, pod in self.peers().items()}
        folder.mkdir(exist_ok=True)
        for peer, text in texts.items():
            (folder / (peer + '-metrics.txt')).write_text(text)
        ui.write_json(folder / 'snapshot.json', {'at': ui.now(), 'simulated': self.args.rehearsal})
        return texts

    def settle(self, label, peer, name, labels, before, *, timeout=60, required=True):
        """Poll until one worker's counter has moved and then held still for a second, and record both workers.
        Replaces fixed sleeps: offload commits and transfer receipts can trail the HTTP response."""
        if self.args.rehearsal or (self.path / label / 'snapshot.json').is_file():
            return self.snapshot(label)
        pods = self.peers()
        deadline, last = time.monotonic() + timeout, None
        while True:
            texts = {p: self.metric_text(pod) for p, pod in pods.items()}
            value = guard.delta(before[peer], texts[peer], name, labels)
            if value > 0 and value == last:
                return self.snapshot(label, texts)
            if time.monotonic() > deadline:
                if not required:
                    return self.snapshot(label, texts)
                raise TimeoutError(f'{name} on {peer.upper()} did not settle within {timeout}s.')
            last = value if value > 0 else None
            time.sleep(1)

    def send(self, role, base):
        """Send one frozen request to its worker, once. A completed role is read back; a partial one is refused."""
        worker, context, function, _ = ROLES[role]
        folder = self.path / role
        if self.data.get(role + '_completed_at'):
            return ui.read_json(folder / 'response.json')
        if self.data.get(role + '_started_at') or folder.exists():
            raise ValueError(f'A {role} request already started; inspect it instead of replaying, or use a fresh run.')
        expected = self.data['facts'][context][function]
        if self.args.rehearsal:
            folder.mkdir()
            proof = {'simulated': True, 'workers': ['example-' + worker.upper()], 'content': expected,
                     'usage': None, 'timing': None, 'client_first_token_seconds': None}
        else:
            body = ui.read_json(self.path / (role + '-request.json'))
            preflight = ui.read_json(self.path / 'prompt-preflight.json')
            if object_sha256(body) != preflight['request_sha256'][role]:
                raise ValueError('Request differs from the tokenized preflight body: ' + role)
            self.data[role + '_started_at'] = ui.now()
            self.save()
            proof = stream_request(base, body, ui.read_json(self.path / 'worker-ids.json')[worker], folder)
            if proof['usage'].get('prompt_tokens') != preflight['prompt_tokens'][role]:
                raise ValueError('Server token usage differs from the tokenizer preflight: ' + role)
        proof.update(expected_answer=expected, answer_matches=expected in proof['content'])
        ui.write_json(folder / 'response.json', proof)
        self.data[role + '_completed_at'] = ui.now()
        self.save()
        return proof

    def show_request(self, role):
        worker, context, function, _ = ROLES[role]
        ids = {'a': 'example-A', 'b': 'example-B'} if self.args.rehearsal else ui.read_json(self.path / 'worker-ids.json')
        what = {'shared': 'the main agent\'s repository', 'control': 'a repository nobody has read'}[context]
        size = len((self.path / CONTEXTS[context]).read_text())
        print(f'Request to {worker.upper()}: {what} ({size:,} characters) + "which file defines {function}?". '
              'Full JSON retained.')
        self.show_command(['curl', '--fail', '--silent', '--show-error', '--no-buffer',
                           self.data['base_url'] + '/v1/chat/completions', '-H', 'Content-Type: application/json',
                           '-H', 'x-dynamo-worker-instance-id: ' + ids[worker], '-H', 'x-dynamo-dp-rank: 0',
                           '--data-binary', '@' + role + '-request.json'])

    @staticmethod
    def report(proof):
        if proof.get('simulated'):
            print('[REHEARSAL] Answer and first token simulated; the planted file is ' + proof['expected_answer'])
            return
        mark = '✓ the planted file' if proof['answer_matches'] else '✗ expected ' + proof['expected_answer']
        print(f'Answer: {proof["content"].strip()}   {mark}')
        reused = (proof['usage'].get('prompt_tokens_details') or {}).get('cached_tokens', 0)
        ms = first_token_ms(proof)
        print(f'First token after {"—" if ms is None else f"{ms:,.0f}"} ms · '
              f'{proof["usage"]["prompt_tokens"]:,} prompt tokens, {reused:,} reused')

    def warm_up(self):
        """Offstage: each engine serves its first request (which pauses once after the first token) and B fetches
        one small context from A, so the onstage requests meet warm engines and an open EFA path."""
        receipt = self.path / 'warmup.json'
        if receipt.is_file():
            if ui.digest(receipt) != self.data.get('warmup_sha256'):
                raise ValueError('Warm-up receipt changed or lacks a completed hash binding.')
            return ui.read_json(receipt)
        self.check_identity()
        if self.args.rehearsal:
            result = {'status': 'illustrative', 'simulated': True, 'warmup_main': None, 'warmup_sub': None,
                      'efa_provider': None, 'scope': 'Simulated warm-up; no requests sent.'}
        else:
            with self.offstage_endpoint() as base:
                before = self.snapshot('warmup-before')
                main = self.send('warmup_main', base)
                middle = self.settle('warmup-after-main', 'a', 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'}, before)
                sub = self.send('warmup_sub', base)
                after = self.settle('warmup-after-sub', 'b', 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'}, middle)
            external = guard.delta(middle['b'], after['b'], 'vllm:prompt_tokens_by_source', {'source': 'external_kv_transfer'})
            if not (main['answer_matches'] and sub['answer_matches']):
                raise ValueError('The model did not name the planted file during warm-up: ' +
                                 repr([main['content'], sub['content']]))
            if external <= 0:
                raise ValueError('Warm-up did not move any context from A to B.')
            logs = {p: self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'main',
                                  '--limit-bytes=20000000').stdout for p, pod in self.peers().items()}
            if not all('using provider=efa' in text for text in logs.values()):
                raise ValueError('Missing EFA provider evidence in the engine logs.')
            result = {'status': 'passed', 'simulated': False, 'at': ui.now(), 'efa_provider': True,
                      'warmup_main': {'first_token_ms': first_token_ms(main), 'client_total_seconds': main['client_total_seconds']},
                      'warmup_sub': {'first_token_ms': first_token_ms(sub), 'client_total_seconds': sub['client_total_seconds'],
                                     'external_cache_tokens': int(external)},
                      'scope': 'Offstage warm-up: each engine\'s first request and one A-to-B fetch. Not part of the onstage comparison.'}
            print(f'Warm-up: A answered in {main["client_total_seconds"]:.1f}s, B in {sub["client_total_seconds"]:.1f}s '
                  f'with {int(external):,} tokens fetched from A. Both engines are warm.')
        with receipt.open('x') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
        self.data['warmup_sha256'] = ui.digest(receipt)
        self.save()
        return result

    def scenario(self):
        print('The main agent has read a whole repository on A. It forks a subagent with the same context and a')
        print('new task. The subagent lands on B, which has spare compute but has never seen the repository.')
        self.command(['cat', self.path / 'kvcr-settings.yaml'])

    def warm_workers(self):
        self.require_primed()
        self.check_identity()
        warm = ui.read_json(self.path / 'warmup.json')
        if self.args.rehearsal:
            print('[REHEARSAL] Workers ready: two TP2 engines and separate host pools, warmed offstage; nothing measured.')
            return
        print('Workers ready: two TP2 engines and separate host pools; startup and warm-up ran offstage.')
        print(ui.compact_resource_table(self.pods(), pods_only=True))
        print(f'Warm-up: each engine has served a request, and B has already fetched '
              f'{warm["warmup_sub"]["external_cache_tokens"]:,} tokens of another context from A.')

    def main_agent(self):
        self.check_identity()
        self.ensure_prompt_preflight()
        if self.data.get('main_completed_at') and (self.args.rehearsal or (self.path / 'after-main/snapshot.json').is_file()):
            print('Main agent request already completed in this run; its saved response is shown, no new request.')
            self.report(ui.read_json(self.path / 'main/response.json'))
            return
        if not self.forward:
            self.endpoint()
        before = self.snapshot('before-main')
        self.show_request('main')
        self.report(self.send('main', self.data['base_url']))
        if self.args.rehearsal:
            print('[REHEARSAL] A keeps the repository in its host pool; no bytes measured.')
            return
        after = self.settle('after-main', 'a', 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'}, before)
        if (guard.delta(before['a'], after['a'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) <= 0 or
                guard.delta(before['b'], after['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'local_fill'}) != 0):
            raise ValueError('Source-only committed host cache was not established.')
        written = guard.delta(before['a'], after['a'], 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'})
        print(f'A kept {written / 2 ** 30:.2f} GiB of this context in its host pool. B has never seen the repository.')

    def subagents(self):
        self.check_identity()
        if self.data.get('sub_completed_at') and (self.args.rehearsal or (self.path / 'after-sub/snapshot.json').is_file()):
            print('Subagent requests already completed in this run; their saved responses are shown, no new request.')
            for role in ('control', 'sub'):
                self.report(ui.read_json(self.path / role / 'response.json'))
            return
        # A resumed live presenter needs its own port-forward; a rehearsal has already shown the simulated one.
        if not self.forward and not (self.args.rehearsal and self.data.get('base_url')):
            self.endpoint()
        after_main = self.snapshot('after-main')
        print('\nFirst, a subagent from another session: a repository of the same size that nobody has read.')
        self.show_request('control')
        control = self.send('control', self.data['base_url'])
        self.report(control)
        # B also commits the control repository to its own host pool; let that finish before the next request.
        after_control = self.settle('after-control', 'b', 'vllm:kv_offload_tiering_write_bytes', {'tier': '1:kvcr'},
                                    after_main, timeout=30, required=False)
        if not self.args.rehearsal and (
                (control['usage'].get('prompt_tokens_details') or {}).get('cached_tokens', 0) or
                guard.delta(after_main['b'], after_control['b'], 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'})):
            raise ValueError('The control request reused cached context, so it is not a cold comparison.')
        print('\nNow the main agent\'s subagent: the repository A already holds, plus its own task.')
        self.show_request('sub')
        self.report(self.send('sub', self.data['base_url']))
        self.settle('after-sub', 'b', 'vllm:kvcr_transfer_blocks', {'operation': 'remote_deliver'}, after_control)

    def compare(self):
        self.check_identity()
        responses = {r: ui.read_json(self.path / r / 'response.json') for r in ('main', 'control', 'sub')}
        if self.args.rehearsal:
            proof = {'status': 'illustrative', 'simulated': True, 'blocks': None, 'bytes': None,
                     'external_cache_tokens': None, 'scope': 'No measured cache transfer or performance.'}
        else:
            before, after = self.snapshot('after-control'), self.snapshot('after-sub')
            # Transfer receipts are log lines; read only the interval since the control request settled.
            since = dt.datetime.fromisoformat(ui.read_json(self.path / 'after-control/snapshot.json')['at'])
            since = (since - dt.timedelta(seconds=10)).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            pods = self.peers()
            logs = {}
            for peer, pod in pods.items():
                logs[peer] = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', 'main',
                                        '--timestamps=true', '--since-time=' + since).stdout
                (self.path / 'after-sub' / (peer + '-main.log')).write_text(logs[peer])
            proof = peer_proof(before, after, logs['a'], logs['b'], pods['a']['status']['podIP'],
                               responses['main'], responses['sub'])
            proof.update(cross_node=self.placement['a']['node'] != self.placement['b']['node'], placement=self.placement,
                         worker_identities_unchanged=True, efa_provider=ui.read_json(self.path / 'warmup.json')['efa_provider'])
        summary = speedup_summary(responses, proof)
        ui.write_json(self.path / 'response.json', responses['sub'])   # the receiver's response, as in legacy runs
        ui.write_json(self.path / 'peer-proof.json', proof)
        ui.write_json(self.path / 'peer-summary.json', {k: proof[k] for k in (
            'status', 'blocks', 'bytes', 'external_cache_tokens', 'cached_prompt_tokens', 'prompt_tokens', 'cross_node') if k in proof})
        ui.write_json(self.path / 'speedup.json', summary)
        rows = summary['rows']
        labels = {'main': 'A · main agent · its repository', 'control': 'B · subagent · unseen repository',
                  'sub': 'B · subagent · main agent\'s repository'}
        longest = max(rows[r]['first_token_ms'] or 0 for r in rows)
        number = lambda value: '—' if value is None else f'{value:,}'
        print(f'\n{"":40}{"prompt":>8}{"reused":>8}{"first token":>13}')
        for role in ('main', 'control', 'sub'):
            row = rows[role]
            ms = row['first_token_ms']
            print(f'{labels[role]:40}{number(row["prompt_tokens"]):>8}{number(row["cached_tokens"]):>8}'
                  f'{("—" if ms is None else f"{ms:,.0f} ms"):>13}  {bar(ms, longest)}')
        if self.args.rehearsal:
            print('\n[REHEARSAL] No transfer or timing measured.')
        else:
            print(f'\nOn B, the first token arrived {summary["first_token_speedup"]}x sooner with A\'s context: '
                  f'{proof["external_cache_tokens"]:,} tokens in {proof["blocks"]} blocks, '
                  f'{proof["bytes"] / 2 ** 30:.2f} GiB over EFA, matched on both ends.')
        print('Tailored to show the mechanism: warm idle workers, one long shared prefix, requests pinned by hand.')
        print('Under real agent traffic the gain depends on load and reuse; benchmark results follow in the slides.')
        self.data['compared_at'] = ui.now()
        self.save()

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] No cluster resources to clean.')
            return
        if self.data.get('cleaned_at'):
            print('Already cleaned.')
            return
        self.require_lease()
        from common_runtime_tests import stop
        stop(self.run, [GRAPH])
        for _ in range(40):
            if not self.run.get('get', 'pods', '-n', self.ns)['items'] and not self.run.get('get', 'resourceclaims', '-n', self.ns)['items']:
                with self.scoped():
                    support.release(self.path, OWNER)
                self.data['cleaned_at'] = ui.now()
                self.save()
                ui.write_json(self.path / 'cleanup-proof.json', {'status': 'passed', 'namespace': self.ns,
                              'pods': [], 'claims': [], 'at': ui.now()})
                print('Verified zero owned Pods and GPU claims. Namespace/cache/artifacts retained.')
                return
            time.sleep(3)
        raise RuntimeError('Cleanup incomplete; reservation retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='run', choices=['run', 'prepare', 'prime', 'preview', 'cleanup', 'observe', 'hold'])
    parser.add_argument('--run', type=Path)
    parser.add_argument('--placement', type=Path, help='Freeze explicit worker nodes and GPU UUID pairs.')
    parser.add_argument('--source-bundle', type=Path, help='Exact pinned experimental source bundle; hash checked before cluster changes.')
    for name in ('rehearsal', 'preview', 'plain', 'auto', 'detach', 'once'):
        parser.add_argument('--' + name, action='store_true')
    parser.add_argument('--port', type=int, default=18007)
    parser.add_argument('--timeout', type=int, default=2700)
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    args = parser.parse_args()
    if not 0 < args.port < 65536 or args.timeout <= 0:
        parser.error('Port must be 1..65535; timeout must be positive.')
    if args.action == 'hold':
        while True:
            time.sleep(30)
    if args.action == 'observe':
        if not args.run:
            parser.error('observe needs --run')
        support.observe(args.run.resolve(), args.view, args.once)
        return
    if args.action in ('prime', 'cleanup') and not args.run:
        parser.error(args.action + ' needs --run')
    demo = KVCRDemo(args)
    print('Demo files: ' + str(demo.path), flush=True)
    if args.preview or args.action == 'preview':
        demo.preview()
        print('Preview only: no cluster commands executed.')
    elif args.action in ('prepare', 'prime', 'cleanup'):
        with ui.presenter_lock(demo.path):
            getattr(demo, args.action)()
    else:
        if not args.rehearsal:
            demo.require_primed()
        if args.plain:
            with ui.presenter_lock(demo.path):
                demo.guided()
        else:
            ui.tmux_layout(demo)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Owned resources retained; use this run\'s cleanup command.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('\nDemo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
