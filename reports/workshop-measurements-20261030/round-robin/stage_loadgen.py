#!/usr/bin/env python3
"""Stage the committed AIPerf source archive in the owned CPU-only client Pod."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
from testlib import Run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--source-location',type=Path,required=True)
    args=p.parse_args();run=Run(args.run)
    location=json.loads(args.source_location.read_text())
    data=Path(location['source_archive']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==location['source_sha256']
    program='''import base64,hashlib,json,sys,tarfile
from pathlib import Path
root=Path('/tmp/workshop-rr');root.mkdir(exist_ok=True)
data=base64.b64decode(sys.stdin.read())
assert hashlib.sha256(data).hexdigest()==sys.argv[1]
archive=root/'aiperf-source.tar'
archive.write_bytes(data)
source=root/'aiperf-source';source.mkdir(exist_ok=False)
with tarfile.open(archive) as tf:tf.extractall(source,filter='data')
print(json.dumps({'archive_sha256':hashlib.sha256(data).hexdigest(),'source':str(source)}))
'''
    result=run.k('exec','-i','rr-loadgen','-n',run.ns,'--','python3','-c',program,
                 location['source_sha256'],input_text=base64.b64encode(data).decode(),timeout=120)
    (run.path/'loadgen-source-staging.json').write_text(json.dumps({
        **location,'remote':json.loads(result.stdout)},indent=2)+'\n')
    print(result.stdout)


if __name__=='__main__':main()
