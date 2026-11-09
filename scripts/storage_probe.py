"""Cross-node EFS correctness test, executed in a disposable pod."""
import hashlib
import json
import os
from pathlib import Path
import time

root = Path('/efs/feature-tests') / os.environ['TEST_RUN']
root.mkdir(parents=True, exist_ok=True)
index = int(os.environ['TEST_INDEX'])
payload = bytes([index + 1]) * (4 * 1024 * 1024)
target = root / f'storage-probe-{index}.bin'
started = time.monotonic()
with target.open('wb') as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
elapsed = time.monotonic() - started
(root / f'storage-probe-{index}.ready').touch()
other = 1 - index
deadline = time.monotonic() + 120
while not (root / f'storage-probe-{other}.ready').exists():
    if time.monotonic() > deadline:
        raise TimeoutError('Peer write was not visible in 120s')
    time.sleep(1)
remote = (root / f'storage-probe-{other}.bin').read_bytes()
expected = bytes([other + 1]) * len(payload)
assert remote == expected, 'Cross-node contents differ'
print(json.dumps({'node': os.environ['NODE_NAME'], 'index': index,
                  'cross_node_read_correct': True,
                  'bytes_written': len(payload), 'write_fsync_seconds': elapsed,
                  'remote_sha256': hashlib.sha256(remote).hexdigest()}))
