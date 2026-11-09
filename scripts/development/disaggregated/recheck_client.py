#!/usr/bin/env python3
"""Fresh read-only client/cache/idle gate for an already-prepared P/D campaign.

No inference, reconstruction, deployments, cleanup or frozen-input changes.
Only the parent/root executor should run this against the live cluster.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import scripts.development.disaggregated.probe_client as probe
import scripts.development.disaggregated.benchmark as benchmark
from testlib import Run


def recheck(path, output):
    path, output = Path(path).resolve(), Path(output).resolve()
    frozen_run = SimpleNamespace(path=path, state=json.loads((path / 'state.json').read_text()))
    benchmark.verify(frozen_run)
    campaign = json.loads((path / 'campaign.json').read_text())
    if frozen_run.state['checks'].get('disagg-cpu-qualified', {}).get('status') != 'passed':
        raise ValueError('The campaign never passed its actual-profile CPU qualification.')
    if any(path.glob('*/intent.json')) or any(path.glob('controller*-start.json')):
        raise ValueError('This is a prelaunch gate for an unattempted campaign; preserve attempted arms.')
    binding = campaign['client_binding']
    specification = probe.expected()
    if (binding['pod_uid'] != specification['uid'] or binding['namespace'] != specification['namespace'] or
            binding['image'] != specification['runtime_image'] or binding['cache_key'] != specification['cache_key']):
        raise ValueError('Frozen client binding differs from the acknowledged qualified source.')
    specification['new_remote_arms'] = list(campaign['arm_names'].values())
    if output.exists():
        raise ValueError('Use a fresh immutable prelaunch-recheck output directory.')
    run = Run(output)
    (run.path / 'probe-spec.json').write_text(json.dumps(specification, indent=2) + '\n')
    pod = run.get('get', 'pod', binding['pod'], '-n', binding['namespace'])
    if (pod['metadata']['uid'] != binding['pod_uid'] or pod['spec']['nodeName'] != binding['node'] or
            pod['metadata']['labels'].get('feature-test-run') != binding['namespace'] or
            pod['status'].get('phase') != 'Running' or
            any(v.get('restartCount', 0) or not v.get('ready') or
                not v['imageID'].endswith(binding['image'].split('@')[1])
                for v in pod['status']['containerStatuses'])):
        raise ValueError('Bound CPU client changed, restarted or expired.')
    gpu_resources = {kind: run.get('get', kind, '-n', binding['namespace'])['items']
                     for kind in ('dgd', 'resourceclaims')}
    if any(gpu_resources.values()):
        raise ValueError('The handed-off namespace is not GPU-empty before this campaign.')
    (run.path / 'source-pod.json').write_text(json.dumps(pod, indent=2) + '\n')
    result = run.k('exec', '-i', binding['pod'], '-n', binding['namespace'], '--',
        '/tmp/workshop-rr/aiperf-source/.venv/bin/python', '-B', '-c', probe.PROGRAM,
        input_text=json.dumps(specification), timeout=600)
    qualification = json.loads(result.stdout)
    qualification.update(at=benchmark.e.now(), source_namespace=binding['namespace'],
        source_pod_uid=binding['pod_uid'], source_node=binding['node'],
        campaign_sha256=benchmark.sha(path / 'campaign.json'),
        prior_profile_qualification=frozen_run.state['checks']['disagg-cpu-qualified'],
        source_namespace_gpu_empty=True, no_inference=True, frozen_inputs_unchanged=True)
    (run.path / 'qualification.json').write_text(json.dumps(qualification, indent=2) + '\n')
    print(json.dumps({k: qualification[k] for k in ('passed', 'source_pod_uid', 'source_namespace_gpu_empty',
          'elapsed_seconds', 'no_inference', 'frozen_inputs_unchanged')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    recheck(args.run, args.output)


if __name__ == '__main__':
    main()
