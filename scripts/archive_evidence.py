#!/usr/bin/env python3
"""Freeze a run's current evidence files with hashes; never access the cluster."""
import argparse
import hashlib
import json
from pathlib import Path
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True,type=Path);parser.add_argument('--pattern',action='append',required=True)
    args=parser.parse_args();root=args.run.resolve();archive=root/f'evidence-{time.time_ns()}';archive.mkdir()
    files={p for pattern in args.pattern for p in root.glob(pattern) if p.is_file()}
    manifest={}
    for p in sorted(files):
     content=p.read_bytes();(archive/p.name).write_bytes(content)
     manifest[p.name]={'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    (archive/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'archive':str(archive),'file_count':len(manifest)}))


if __name__ == '__main__':
    main()
