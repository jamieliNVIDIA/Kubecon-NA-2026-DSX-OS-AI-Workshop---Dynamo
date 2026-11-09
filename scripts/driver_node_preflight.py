#!/usr/bin/env python3
"""Read-only header/module and GPU-client inspection for the driver upgrade."""
import argparse,json
from pathlib import Path
from testlib import Run


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True,type=Path)
    run=Run(parser.parse_args().run)
    program=r'''set -eu
uname -r
cat /proc/driver/nvidia/version
for p in /lib/modules/$(uname -r)/build /lib/modules/$(uname -r)/source; do ls -ld "$p" || true; readlink -f "$p" || true; done
if test -f /lib/modules/$(uname -r)/build/Makefile; then echo KERNEL_HEADERS_PRESENT; fi
command -v gcc || true
gcc --version | head -n 1
command -v make || true
ls -d /usr/src/* 2>/dev/null || true
ls /dev/nvidia* 2>/dev/null || true
lsmod | awk 'NR==1 || /nvidia|gdrdrv|efa/'
nvidia-smi --query-gpu=uuid,driver_version,memory.used --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader
ps -eo pid,comm,args | awk 'NR==1 || /nv-hostengine|dcgm|nvidia-fabricmanager|gpu-health|dra-driver/'
'''
    pods=run.get('get','pods','-n','gpu-operator')['items']
    for p in pods:
     if not p['metadata']['name'].startswith('nvidia-driver-daemonset-'):continue
     result=run.k('exec',p['metadata']['name'],'-n','gpu-operator','-c','nvidia-driver-ctr','--','bash','-c',program,check=False)
     (run.path/(p['spec']['nodeName']+'-driver-preflight.log')).write_text(result.stdout+result.stderr)
     print(p['spec']['nodeName'],result.returncode,result.stdout[:1800],flush=True)
    for resource in ('daemonsets','deployments','pods','resourceclaims','dynamographdeployments'):
     obj=run.get('get',resource,'-A');(run.path/('before-'+resource+'.json')).write_text(json.dumps(obj,indent=2)+'\n')


if __name__ == '__main__':
    main()
