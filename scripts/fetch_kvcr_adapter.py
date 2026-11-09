#!/usr/bin/env python3
"""Save immutable public adapter source for integration review and provenance."""
import json
from pathlib import Path
import urllib.request
from testlib import ROOT


def main():
    lock=json.loads((ROOT/'configs/kvcr-lock.json').read_text())
    paths=['vllm/v1/kv_offload/tiering/kvcr/manager.py',
     'vllm/distributed/kv_transfer/kv_connector/v1/offloading/config.py']
    for path in paths:
     url=f'https://raw.githubusercontent.com/vllm-project/vllm/{lock["vllm_adapter_revision"]}/{path}'
     with urllib.request.urlopen(url,timeout=60) as response:content=response.read()
     target=ROOT/'configs/upstream/vllm-kvcr'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
     print(path)


if __name__ == '__main__':
    main()
