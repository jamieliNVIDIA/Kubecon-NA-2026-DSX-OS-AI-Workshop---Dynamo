#!/usr/bin/env python3
"""Read two existing AgentX mmap conversations; emit sizes/hashes, never text."""
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ['AIPERF_DATASET_MMAP_PREFAULT']='false'
from aiperf.dataset.memory_map_utils import MemoryMapDatasetClient

CACHE=Path('/tmp/workshop-rr/mmap-cache/42d97db1b0977336274f9bb686585572')
IDS=['085aacf44ac5428ad3c6b4f6cd431e083832::fa:005',
     '085aacf44ac5428ad3c6b4f6cd431e083832::fa:006']
if sys.argv[1:]:IDS=sys.argv[1:]
assert len(IDS)==2


def common(a,b):
    limit=min(len(a),len(b));i=0
    while i<limit and a[i]==b[i]:i+=1
    return i


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(value).hexdigest()


with MemoryMapDatasetClient(CACHE/'dataset.dat',CACHE/'index.dat') as client:
    conversations=[client.get_conversation(i) for i in IDS]
messages=[c.turns[0].raw_messages for c in conversations]
assert all(isinstance(m,list) for m in messages)
encoded=[canonical(m) for m in messages]
encoded_bytes=[x.encode('utf-8') for x in encoded]
rows=[];leading=0;prefix_active=True
for i,(a,b) in enumerate(zip(*messages)):
    if prefix_active and a==b:leading+=1
    else:prefix_active=False
    av=a.get('content');bv=b.get('content')
    if isinstance(av,str) and isinstance(bv,str):
        n=common(av,bv);raw=[av.encode('utf-8'),bv.encode('utf-8')]
        content={'types':['str','str'],'characters':[len(av),len(bv)],
            'utf8_bytes':[len(x) for x in raw],'lcp_characters':n,
            'lcp_utf8_bytes':common(*raw),'lcp_sha256':digest(av[:n].encode('utf-8')),
            'sha256':[digest(x) for x in raw]}
    else:
        raw=[canonical(av).encode('utf-8'),canonical(bv).encode('utf-8')]
        content={'types':[type(av).__name__,type(bv).__name__],
            'canonical_json_utf8_bytes':[len(x) for x in raw],
            'canonical_json_lcp_utf8_bytes':common(*raw),
            'canonical_json_sha256':[digest(x) for x in raw]}
    rows.append({'index':i,'roles':[a.get('role'),b.get('role')],
        'messages_equal':a==b,'content':content})
n=common(*encoded_bytes)
print(json.dumps({'purpose':'CPU-only existing-cache equality inspection; no tokenizer or inference',
    'cache_key':CACHE.name,'conversation_ids':IDS,'turn_index':0,
    'message_roles':[[x.get('role') for x in m] for m in messages],
    'message_counts':[len(m) for m in messages],'identical_leading_messages':leading,
    'whole_message_arrays_equal':messages[0]==messages[1],
    'canonical_json_characters':[len(x) for x in encoded],
    'canonical_json_lcp_characters':common(*encoded),
    'canonical_json_utf8_bytes':[len(x) for x in encoded_bytes],
    'canonical_json_lcp_utf8_bytes':n,'canonical_json_lcp_sha256':digest(encoded_bytes[0][:n]),
    'canonical_json_sha256':[digest(x) for x in encoded_bytes],
    'message_comparisons':rows},indent=2))
