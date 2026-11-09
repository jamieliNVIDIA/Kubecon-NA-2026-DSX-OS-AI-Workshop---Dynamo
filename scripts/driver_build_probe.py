#!/usr/bin/env python3
"""Stage a CPU-only R610 container with read-only host headers for build validation."""
import argparse
import json
import time
from pathlib import Path
from testlib import Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--node', default='kubecon-nke-site-cp-0124')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--build', action='store_true', help='Extract and compile only; never install or load modules')
    parser.add_argument('--build-deps', action='store_true', help='Install header build dependencies inside the disposable Pod')
    args = parser.parse_args()
    run = Run(args.run)
    name = 'r610-build-probe'
    if not args.inspect and not args.build and not args.build_deps:
        run.ensure_namespace()
        image = json.loads((run.path / 'target-image.json').read_text())[0]['image']
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': {
            'nodeName': args.node, 'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'containers': [{'name': 'build', 'image': image,
                'command': ['/bin/bash', '-c', 'sleep 7200'],
                'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                'resources': {'requests': {'cpu': '2', 'memory': '2Gi'}, 'limits': {'cpu': '8', 'memory': '12Gi'}},
                'volumeMounts': [{'name': 'headers', 'mountPath': '/usr/src', 'readOnly': True},
                                 {'name': 'modules', 'mountPath': '/lib/modules', 'readOnly': True}]}],
            'volumes': [{'name': 'headers', 'hostPath': {'path': '/usr/src', 'type': 'Directory'}},
                        {'name': 'modules', 'hostPath': {'path': '/lib/modules', 'type': 'Directory'}}]}}
        run.apply([pod])
        run.wait_pod(name, timeout=600)
    program = r'''set -eu
uname -r
ls -l /drivers /usr/src /opt /usr/local/bin 2>/dev/null || true
find / -maxdepth 4 -name '*610*' 2>/dev/null | head -40
command -v gcc make || true
test -f /lib/modules/$(uname -r)/build/Makefile
'''
    if args.build_deps:
        # Host mounts are read-only. Only this disposable container's package DB changes.
        program = r'''set -euo pipefail
apt-get -qq update
apt-cache depends linux-headers-$(uname -r)
apt-cache depends linux-aws-7.0-headers-7.0.0-1012
apt-get install -y --no-install-recommends libdw1t64
apt-get download linux-headers-$(uname -r) linux-image-$(uname -r)
ldd /lib/modules/$(uname -r)/build/scripts/gendwarfksyms/gendwarfksyms
'''
    elif args.build:
        program = r'''set -euo pipefail
sha256sum /drivers/NVIDIA-Linux-x86_64-610.57.04.run
if ! test -d /tmp/r610-source; then
    sh /drivers/NVIDIA-Linux-x86_64-610.57.04.run --extract-only --target /tmp/r610-source > /tmp/r610-extract.log 2>&1
fi
cd /tmp/r610-source/kernel-open
make -j8 SYSSRC=/lib/modules/$(uname -r)/build modules > /tmp/r610-build.log 2>&1 || { tail -120 /tmp/r610-build.log; exit 1; }
tail -35 /tmp/r610-build.log
find . -name '*.ko' -exec modinfo -F vermagic {} \;
printf 'R610_MODULE_BUILD_PASSED_NO_INSTALL_OR_LOAD\n'
'''
    result = run.k('exec', name, '-n', run.ns, '--', 'bash', '-c', program, timeout=1200, check=False)
    label = 'r610-build-deps' if args.build_deps else 'r610-module-build' if args.build else 'r610-build-layout'
    (run.path / f'{label}-{time.time_ns()}.log').write_text(result.stdout + result.stderr)
    print(result.stdout)
    if args.build:
        run.result('r610-module-build', 'passed' if result.returncode == 0 else 'blocked',
            node=args.node, exit_code=result.returncode, scope='Compilation only; no module install or load')
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
