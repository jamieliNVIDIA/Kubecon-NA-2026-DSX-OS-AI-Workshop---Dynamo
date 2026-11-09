#!/usr/bin/env python3
"""Read installed same-image sources without starting inference or changing a run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import scripts.development.disaggregated.handoff as handoff


PROGRAM = r'''import hashlib,importlib.util,json
from pathlib import Path
wanted={
 'dynamo':['health_check.py','vllm/health_check.py','vllm/handlers.py','vllm/worker_factory.py'],
 'vllm':['envs.py','distributed/kv_transfer/kv_connector/v1/nixl/base_worker.py',
         'distributed/kv_transfer/kv_connector/v1/nixl/stats.py',
         'distributed/kv_transfer/kv_connector/v1/nixl/scheduler.py']}
files={}
for package,names in wanted.items():
 spec=importlib.util.find_spec(package)
 assert spec and spec.submodule_search_locations,package+' package absent'
 roots=list(spec.submodule_search_locations)
 for name in names:
  candidates=[Path(root)/name for root in roots if (Path(root)/name).is_file()]
  assert len(candidates)==1,(package,name,str(candidates))
  path=candidates[0];content=path.read_bytes()
  files[package+'/'+name]={'path':str(path),'sha256':hashlib.sha256(content).hexdigest(),
                         'text':content.decode()}
print(json.dumps({'files':files,'inference_started':False,'sources_modified':False}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    if not args.attempt.isalnum():
        raise ValueError('Use a fresh alphanumeric source-inspection attempt.')
    run = handoff.setup(args.run)
    handoff.b.verify(run)
    client = handoff.check_client(run)
    destination = run.path / ('installed-source-inspection-' + args.attempt)
    destination.mkdir(exist_ok=False)
    # The benchmark helper intentionally uses an isolated AIPerf virtualenv;
    # inspect the runtime image's Python instead of that dataset-only environment.
    binding = handoff.b.spec(run)['client_binding']
    result = run.k('exec', binding['pod'], '-n', binding['namespace'], '--',
                   'python3', '-c', PROGRAM)
    value = json.loads(result.stdout)
    assert value['inference_started'] is False and value['sources_modified'] is False
    for relative, entry in value['files'].items():
        content = entry.pop('text')
        if hashlib.sha256(content.encode()).hexdigest() != entry['sha256']:
            raise ValueError('Source transport hash changed: ' + relative)
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    handoff.b.write(destination / 'proof.json', {
        'at': handoff.b.e.now(), 'passed': True, 'inference_started': False,
        'sources_modified': False, 'client_pod_uid': client['metadata']['uid'],
        'client_binding': handoff.b.spec(run)['client_binding'],
        'campaign_sha256': handoff.b.sha(run.path / 'campaign.json'),
        'helper_sha256': handoff.b.sha(__file__), **value})
    print(json.dumps({'passed': True, 'files': len(value['files']),
                      'destination': str(destination), 'inference_started': False}, indent=2))


if __name__ == '__main__':
    main()
