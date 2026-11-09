#!/usr/bin/env python3
"""Resolve public image tags into immutable registry digests without Docker pulls."""
import argparse
import json
from pathlib import Path
import urllib.parse
import urllib.request


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), dict(response.headers)


def resolve(image):
    host, path = image.split('/', 1)
    repo, tag = path.rsplit(':', 1)
    scope = f'repository:{repo}:pull'
    if host == 'nvcr.io':
        token_url = 'https://nvcr.io/proxy_auth?' + urllib.parse.urlencode({'scope': scope})
        registry = host
    elif host == 'docker.io':
        token_url = 'https://auth.docker.io/token?' + urllib.parse.urlencode({'service':'registry.docker.io', 'scope':scope})
        registry = 'registry-1.docker.io'
    elif host == 'ghcr.io':
        token_url = 'https://ghcr.io/token?' + urllib.parse.urlencode({'service': 'ghcr.io', 'scope': scope})
        registry = host
    else: raise ValueError('Only public NGC/DockerHub/GHCR images supported')
    token = json.loads(fetch(token_url)[0])['token']
    body, headers = fetch(f'https://{registry}/v2/{repo}/manifests/{tag}', {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
    digest = next(v for k,v in headers.items() if k.lower()=='docker-content-digest')
    manifest = json.loads(body)
    return {'tag':image,'image':f'{host}/{repo}@{digest}','digest':digest,'platforms':[
        {'digest':m['digest'],'platform':m.get('platform')} for m in manifest.get('manifests',[])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = [resolve(image) for image in args.images]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
