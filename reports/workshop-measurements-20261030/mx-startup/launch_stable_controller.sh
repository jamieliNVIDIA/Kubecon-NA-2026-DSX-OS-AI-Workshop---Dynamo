#!/usr/bin/env bash
# Run only after root reviews the bundle and explicitly delegates the retained lease.
set -euo pipefail
umask 077
controller_workspace="${1:?staged absolute workspace path required}"
controller_kubeconfig="${2:?existing bastion kubeconfig path required}"
controller_image='docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337'
controller_root='/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop'
controller_name='kubecon-workshop-controller-20261103'
test -d "$controller_workspace"
test -f "$controller_kubeconfig"
test -x /usr/bin/kubectl
test -f "$controller_workspace/controller-delegation.json"
test -f "$controller_workspace/controller-bundle-manifest.json"
test -f "$controller_workspace/reports/workshop-measurements-20261030/round-robin/resume_c4_r2.py"

# This verifies staged bytes without reading or copying credential contents.
python3 - "$controller_workspace" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'controller-bundle-manifest.json').read_text())
for name,record in m['files'].items():
 f=p/name
 assert f.is_file() and not f.is_symlink(),name
 assert hashlib.sha256(f.read_bytes()).hexdigest()==record['sha256'],name
d=json.loads((p/'controller-delegation.json').read_text())
assert d['local_controllers_stopped'] is True and d['local_gpu_execution_frozen'] is True
assert d['lease_metadata_sha256']==m['lease_metadata_sha256']
print('Staged bundle and explicit controller delegation verified')
PY

mkdir -p "$controller_workspace/.local/bin" "$controller_workspace/.local/venv/bin"
ln -s /usr/local/bin/python "$controller_workspace/.local/venv/bin/python"
: > "$controller_workspace/.local/bin/kubectl"
: > "$controller_workspace/.local/kubeconfig"

# Detached Docker supervision survives SSH/VPN loss. No automatic restart/replay.
docker run --detach --pull=never --name "$controller_name" --restart=no \
  --network host --user 1000:1000 --cpus=2 --memory=4g \
  --cap-drop ALL --security-opt no-new-privileges \
  --env "PYTHONPATH=$controller_root/.controller-deps" \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,src=$controller_workspace,dst=$controller_root" \
  --mount "type=bind,src=/usr/bin/kubectl,dst=$controller_root/.local/bin/kubectl,readonly" \
  --mount "type=bind,src=$controller_kubeconfig,dst=$controller_root/.local/kubeconfig,readonly" \
  --workdir "$controller_root" --entrypoint /bin/sh "$controller_image" -ec \
  '.local/venv/bin/python -B -c "import sys,yaml; assert yaml.__version__ == \"6.0.3\"; print(sys.version, yaml.__version__)"; .local/venv/bin/python -B reports/workshop-measurements-20261030/round-robin/resume_c4_r2.py --label stable-a1; exec .local/venv/bin/python -B reports/workshop-measurements-20261030/round-robin/continue_remaining.py --label stable-a2 --start-at mx'
