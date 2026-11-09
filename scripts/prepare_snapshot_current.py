#!/usr/bin/env python3
"""Save immutable current/release Snapshot source evidence; no cluster mutations."""
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from testlib import ROOT


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'dynamo-workshop-preflight'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    sources = {
        'dynamo': {
            'refs': ['v1.5.1', 'main'],
            'paths': [
                'deploy/helm/charts/platform/Chart.yaml',
                'deploy/helm/charts/platform/values.yaml',
                'examples/backends/trtllm/deploy/snapshot/qwen3-0.6b.yaml',
                'examples/backends/trtllm/deploy/snapshot/glm-5.3.yaml',
            ],
        },
        'snapshot': {
            'refs': ['v0.1.0', 'main'],
            'paths': [
                'README.md', 'docs/limitations.md', 'docs/operations/install.md',
                'docs/operations/storage.md', 'docs/guides/vllm.md',
                'docs/reference/workload-contract.md',
                'docs/guides/cuda-shared-memory.md',
                'charts/snapshot/Chart.yaml', 'charts/snapshot/values.yaml',
            ],
        },
    }
    lock = {'repositories': []}
    for repo, settings in sources.items():
        remote = subprocess.check_output(
            ['git', 'ls-remote', f'https://github.com/ai-dynamo/{repo}.git',
             *[pattern for ref in settings['refs'] for pattern in
               (f'refs/heads/{ref}', f'refs/tags/{ref}', f'refs/tags/{ref}^{{}}')]],
            text=True, timeout=60,
        )
        revisions = dict(line.split()[::-1] for line in remote.splitlines())
        for ref in settings['refs']:
            revision = next((revisions[key] for key in
                             (f'refs/tags/{ref}^{{}}', f'refs/tags/{ref}', f'refs/heads/{ref}')
                             if key in revisions), None)
            if not revision:
                raise RuntimeError(f'Cannot resolve {repo}:{ref}')
            record = {'repository': f'ai-dynamo/{repo}', 'ref': ref, 'revision': revision, 'files': []}
            for path in settings['paths']:
                url = f'https://raw.githubusercontent.com/ai-dynamo/{repo}/{revision}/{path}'
                entry = {'path': path, 'url': url}
                try:
                    content = fetch(url)
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
                    entry['status'] = 404
                else:
                    target = ROOT / 'configs/upstream/snapshot-current' / repo / revision / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.read_bytes() != content:
                        raise RuntimeError(f'Immutable source changed: {target}')
                    target.write_bytes(content)
                    entry.update(status=200, sha256=hashlib.sha256(content).hexdigest())
                record['files'].append(entry)
            lock['repositories'].append(record)
            print(json.dumps({'repository': record['repository'], 'ref': ref, 'revision': revision,
                              'found': sum(f['status'] == 200 for f in record['files']),
                              'missing': [f['path'] for f in record['files'] if f['status'] == 404]}), flush=True)
    (ROOT / 'configs/snapshot-current-source.json').write_text(json.dumps(lock, indent=2) + '\n')


if __name__ == '__main__':
    main()
