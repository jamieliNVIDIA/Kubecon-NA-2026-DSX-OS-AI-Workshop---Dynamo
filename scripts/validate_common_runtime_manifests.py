#!/usr/bin/env python3
"""Validate saved common-image DGDs without creating cluster resources."""
import argparse
import json
from pathlib import Path
import yaml
from serving_tests import lock_model
from testlib import ROOT, Run


def validate(run):
    lock = lock_model(run)
    if not lock.get('common_runtime'):
        raise ValueError('Requires a common-runtime run')
    reports = []
    for path in sorted((ROOT / 'configs/dgd/common-runtime').glob('*.yaml')):
        obj = yaml.safe_load(path.read_text())
        if obj['metadata']['namespace'] != run.ns:
            raise ValueError('Manifest belongs to a different run: ' + str(path))
        for component in obj['spec']['components']:
            assert component['runtimeVersionOverride'] == lock['runtime_version_override']
            spec = component['podTemplate']['spec']
            for container in spec.get('containers', []) + spec.get('initContainers', []):
                assert container['image'] == lock['runtime_image'], path
                names = [item['name'] for item in container.get('env', [])]
                assert len(names) == len(set(names)), (path, container['name'])
        content = json.dumps(obj)
        run.k('apply', '--dry-run=client', '-f', '-', input_text=content)
        run.k('apply', '--dry-run=server', '-f', '-', input_text=content)
        reports.append({'manifest': str(path.relative_to(ROOT)), 'client': 'passed', 'server': 'passed'})
    if len(reports) != 7:
        raise ValueError('Expected all seven qualified feature DGDs')
    run.result('common-manifests', 'passed', image=lock['runtime_image'], manifests=reports,
               scope='Image/version/env consistency plus client/server dry-run; no resources created')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    validate(Run(parser.parse_args().run))
