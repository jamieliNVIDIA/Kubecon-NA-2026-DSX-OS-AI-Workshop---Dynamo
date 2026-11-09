#!/usr/bin/env bash
# Container-only userspace setup: no host mounts, kernel modules, or limit changes.
set -euo pipefail
export EFA_INSTALLER_VERSION=1.49.0
export EFA_INSTALLER_SHA256=cf2e9281a2328a243c76f911a490faed43ca0fecfe4733c25e34b2e92a32c309
if [ ! -x /opt/amazon/efa/bin/fi_info ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    bash /tests/check-efa-userspace.sh install
fi
export PATH="/opt/amazon/efa/bin:$PATH"
export LD_LIBRARY_PATH="/opt/amazon/efa/lib:/opt/amazon/efa/lib64:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi_info -p efa -t FI_EP_RDM >/tmp/efa-provider.txt
exec "$@"
