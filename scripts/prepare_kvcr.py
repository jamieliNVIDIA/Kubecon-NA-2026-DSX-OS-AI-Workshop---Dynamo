#!/usr/bin/env python3
"""Save a pinned public KVCR compatibility set and source instructions."""
import hashlib
import json
from pathlib import Path
import urllib.request
from testlib import ROOT

def fetch(url):
 with urllib.request.urlopen(url,timeout=60) as response:return response.read()


def main():
    revision=json.loads(fetch('https://api.github.com/repos/ai-dynamo/kvcr/commits/main'))['sha']
    paths=['Dockerfile.quick-start','docs/quick-start.md','docs/dev-guide.md','pyproject.toml']
    records=[]
    for path in paths:
     url=f'https://raw.githubusercontent.com/ai-dynamo/kvcr/{revision}/{path}'
     content=fetch(url);dst=ROOT/'configs/upstream/kvcr'/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(content)
     records.append({'path':path,'url':url,'sha256':hashlib.sha256(content).hexdigest()})
    lock={'kvcr_revision':revision,'dynamo_revision':'ea23e5130c1bfbadec477b99449d0cee5598caa0',
     'vllm_adapter_revision':'08567505b09324f891797f4a13c1bd73fc75a827',
     'vllm_image':'docker.io/vllm/vllm-openai:nightly-43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5@sha256:f8696a5176c1fb61e025b0772505674a3e092c25597eb26117003945b5121e8d',
     'sources':records}
    (ROOT/'configs/kvcr-lock.json').write_text(json.dumps(lock,indent=2)+'\n');print(json.dumps(lock,indent=2))


if __name__ == '__main__':
    main()
