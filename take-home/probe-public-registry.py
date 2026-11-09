#!/usr/bin/env python3
"""Read exact official image metadata with anonymous registry auth, never local credentials."""
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'nvidia/ai-dynamo/vllm-runtime-nightly'
DIGEST = 'sha256:c186817f4669d615d2b14bee5a6119d35d4d0fe186fdfab69920da8de9d09337'
ACCEPT = ', '.join(('application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.v2+json'))


def parse_challenge(challenge):
    if not challenge.lower().startswith('bearer '):
        raise ValueError('Unexpected registry authentication challenge')
    values = dict(re.findall(r'([a-z]+)="([^"]*)"', challenge[7:]))
    realm = urllib.parse.urlsplit(values['realm'])
    if realm.scheme != 'https' or realm.hostname != 'nvcr.io' or realm.username or realm.password:
        raise ValueError('Anonymous token realm is not the expected registry host')
    if values.get('service') not in ('nvcr.io', 'registry') or values.get('scope') != 'repository:' + REPOSITORY + ':pull':
        raise ValueError('Registry challenge does not match the exact public pull scope')
    return values, realm


def probe():
    url = 'https://nvcr.io/v2/' + REPOSITORY + '/manifests/' + DIGEST
    headers = {'Accept': ACCEPT}
    used_anonymous_token = False
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            manifest = response.read()
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        values, realm = parse_challenge(error.headers.get('WWW-Authenticate', ''))
        token_url = values['realm'] + ('&' if realm.query else '?') + urllib.parse.urlencode({
            'service': values['service'], 'scope': values['scope']})
        # urllib does not read Docker auth files or .netrc. No username/password,
        # account token, cookies or local registry credentials are supplied.
        with urllib.request.urlopen(token_url, timeout=30) as response:
            payload = json.load(response)
        token = payload.get('token', payload.get('access_token'))
        if not isinstance(token, str) or not token:
            raise ValueError('No anonymous pull token returned')
        headers['Authorization'] = 'Bearer ' + token
        used_anonymous_token = True
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            manifest = response.read()
    observed = 'sha256:' + hashlib.sha256(manifest).hexdigest()
    if observed != DIGEST:
        raise ValueError('Anonymous manifest digest differs from the pinned image')
    data = json.loads(manifest)
    config = data['config']['digest']
    config_url = 'https://nvcr.io/v2/' + REPOSITORY + '/blobs/' + config
    with urllib.request.urlopen(urllib.request.Request(config_url, headers=headers), timeout=30) as response:
        content = response.read()
    if 'sha256:' + hashlib.sha256(content).hexdigest() != config:
        raise ValueError('Anonymous config digest mismatch')
    return {'status': 'passed', 'image': 'nvcr.io/' + REPOSITORY + '@' + DIGEST,
            'anonymous_token_used': used_anonymous_token, 'local_credentials_used': False,
            'manifest_sha256': observed, 'config_sha256': config, 'manifest_bytes': len(manifest),
            'config_bytes': len(content), 'layer_count': len(data['layers']),
            'scope': 'Anonymous access to exact manifest/config metadata; layers are not downloaded by this probe. No registry credential or bearer token is printed.'}


if __name__ == '__main__':
    try:
        print(json.dumps(probe(), indent=2))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': type(error).__name__ + ': ' + str(error)}))
        raise SystemExit(1)
