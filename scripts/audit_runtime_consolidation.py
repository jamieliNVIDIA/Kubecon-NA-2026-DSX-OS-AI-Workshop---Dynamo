#!/usr/bin/env python3
"""Save pinned source-level runtime compatibility evidence; no cluster changes."""
import argparse
import ast
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request
from testlib import ROOT


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    kvcr = json.loads((ROOT / 'configs/kvcr-lock.json').read_text())
    dynamo_revisions = ['2093662a4d4e5fd318732935213dde08dc7be818', kvcr['dynamo_revision']]
    vllm_revision = kvcr['vllm_image'].split('nightly-', 1)[1].split('@', 1)[0]
    sources = [('ai-dynamo/dynamo', revision, path) for revision in dynamo_revisions for path in
               ('pyproject.toml', 'components/src/dynamo/common/constants.py',
                'components/src/dynamo/vllm/snapshot.py', 'lib/sidecar/vllm/Cargo.toml')]
    sources += [('vllm-project/vllm', vllm_revision, path) for path in
                ('vllm/v1/engine/async_llm.py', 'vllm/v1/engine/core_client.py',
                 'vllm/engine/protocol.py', 'vllm/v1/kv_offload/tiering/factory.py')]
    sources += [('ai-dynamo/kvcr', kvcr['kvcr_revision'], 'pyproject.toml')]

    def fetch(source):
        repository, revision, path = source
        url = f'https://raw.githubusercontent.com/{repository}/{revision}/{path}'
        record = {'repository': repository, 'revision': revision, 'path': path, 'url': url}
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'dynamo-workshop-audit'})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            return {**record, 'status': 404}
        text = data.decode()
        destination = output / repository / revision / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        record.update(status=200, sha256=hashlib.sha256(data).hexdigest())
        record['matching_lines'] = [{'line': n, 'text': line.strip()} for n, line in enumerate(text.splitlines(), 1)
                                    if any(s in line for s in ('vllm[', 'nixl', 'checkpoint_prepare',
                                                              'checkpoint_restore', 'router_hint'))]
        if path.endswith('.py'):
            tree = ast.parse(text)
            record['checkpoint_methods'] = [node.name for node in ast.walk(tree)
                                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                                            and node.name in ('checkpoint_prepare', 'checkpoint_restore')]
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(fetch, sources))
    result = {'scope': 'Source audit only; not an image import, inference or Snapshot qualification',
              'sources': records}
    (output / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output)
