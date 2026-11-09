#!/usr/bin/env python3
"""Verify stale concurrent observers preserve feature results; no cluster access."""
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
from testlib import Run

def writer(path,barrier,feature,delay):
    run=Run(Path(path));barrier.wait();time.sleep(delay)
    run.result(feature,'passed',evidence='independent observer')

def main():
    with tempfile.TemporaryDirectory(prefix='dynamo-receipt-check-') as directory:
        path=Path(directory)
        initial=Run(path);initial.result('recovered','blocked',error='previous failure')
        barrier=mp.Barrier(3)
        processes=[mp.Process(target=writer,args=(str(path),barrier,'recovered',0.15)),
                   mp.Process(target=writer,args=(str(path),barrier,'other',0))]
        for p in processes:p.start()
        barrier.wait()
        for p in processes:p.join(10);assert p.exitcode==0
        state=json.loads((path/'state.json').read_text())
        assert state['checks']['recovered']['status']=='passed'
        assert 'error' not in state['checks']['recovered']
        assert state['checks']['other']['status']=='passed'
        assert len(list(path.glob('check-*.json')))==3
        assert len(state['attempts'])==3
        print('Concurrent observer merge, stale-error replacement and immutable receipts: passed')

if __name__=='__main__':main()
