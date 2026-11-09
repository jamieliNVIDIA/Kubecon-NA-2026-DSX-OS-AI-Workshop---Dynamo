#!/usr/bin/env python3
"""Pin Snapshot requirements and chart values for review; never installs anything."""
import hashlib
import json
import urllib.request
from testlib import ROOT

def fetch(url):
 with urllib.request.urlopen(url,timeout=60) as response:return response.read()


def main():
    ref=json.loads(fetch('https://api.github.com/repos/ai-dynamo/snapshot/commits/main'))['sha']
    records=[]
    for path in ('README.md','docs/limitations.md','docs/operations/install.md','docs/operations/storage.md'):
     url=f'https://raw.githubusercontent.com/ai-dynamo/snapshot/{ref}/{path}'
     content=fetch(url);dst=ROOT/'configs/upstream/snapshot'/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(content)
     records.append({'path':path,'url':url,'sha256':hashlib.sha256(content).hexdigest()})
    lock={'snapshot_revision':ref,'sources':records}
    (ROOT/'configs/snapshot-source.json').write_text(json.dumps(lock,indent=2)+'\n');print(json.dumps(lock,indent=2))


if __name__ == '__main__':
    main()
