#!/usr/bin/env python3
"""Collect optional-feature packaging evidence from owned test pods."""
import argparse
import json
from pathlib import Path
from testlib import ROOT, Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--source', action='store_true')
    args = parser.parse_args()
    run = Run(args.run)
    pods = run.get('get', 'pods', '-n', run.ns)['items']
    worker = next(p for p in pods if p['metadata']['name'].startswith('ft-agg-')
                  and p['metadata'].get('labels', {}).get('nvidia.com/dynamo-component-type') == 'worker'
                  and p.get('status', {}).get('phase') == 'Running')
    result = run.k('exec', '-i', worker['metadata']['name'], '-n', run.ns, '-c', 'main',
                   '--', 'python3', '-', input_text=(ROOT / 'scripts' / ('runtime_source_probe.py' if args.source else 'runtime_capabilities.py')).read_text(), timeout=120)
    log = result.stdout
    marker = log.rfind('\n{')
    report = json.loads(log[marker + 1:] if marker >= 0 else log)
    destination = 'runtime-sources.json' if args.source else 'capabilities.json'
    (run.path / destination).write_text(json.dumps(report, indent=2) + '\n')
    if args.source:
        print(json.dumps({'source_files': list(report)}))
        return
    print(json.dumps(report, indent=2))
    run.result('optional-feature-packaging', 'collected', pod=worker['metadata']['name'],
               report_file='capabilities.json', note='Packaging evidence only; not end-to-end feature qualification')


if __name__ == '__main__':
    main()
