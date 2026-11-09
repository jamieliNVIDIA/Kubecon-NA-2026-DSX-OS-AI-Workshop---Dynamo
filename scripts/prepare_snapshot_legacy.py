#!/usr/bin/env python3
"""Pin the Snapshot source matching the installed Dynamo 1.4.2 platform."""
import hashlib
import json
import urllib.request
from testlib import ROOT

def fetch(url):
    with urllib.request.urlopen(url,timeout=60) as response:return response.read()


def main():
    ref=json.loads(fetch('https://api.github.com/repos/ai-dynamo/dynamo/commits/v1.4.2'))['sha']
    paths=['deploy/helm/charts/snapshot/Chart.yaml','deploy/helm/charts/snapshot/values.yaml',
           'deploy/helm/charts/snapshot/README.md','deploy/snapshot/Dockerfile',
           'deploy/helm/charts/platform/values.yaml']
    records=[]
    for path in paths:
        url=f'https://raw.githubusercontent.com/ai-dynamo/dynamo/{ref}/{path}'
        content=fetch(url);target=ROOT/'configs/upstream/dynamo-1.4.2'/path
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        records.append({'path':path,'url':url,'sha256':hashlib.sha256(content).hexdigest()})
    (ROOT/'configs/snapshot-legacy-source.json').write_text(json.dumps({'release':'v1.4.2','revision':ref,'sources':records},indent=2)+'\n')
    print(json.dumps({'release':'v1.4.2','revision':ref,'files':len(records)}))


if __name__ == '__main__':
    main()
