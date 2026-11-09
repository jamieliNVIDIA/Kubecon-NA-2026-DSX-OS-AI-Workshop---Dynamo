#!/usr/bin/env bash
# Image layer only: no kernel modules, host limits or hardware requirement.
set -euo pipefail
version=1.49.0
checksum=cf2e9281a2328a243c76f911a490faed43ca0fecfe4733c25e34b2e92a32c309
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
curl -fsSL "https://efa-installer.amazonaws.com/aws-efa-installer-${version}.tar.gz" -o "$workdir/efa.tar.gz"
printf '%s  %s\n' "$checksum" "$workdir/efa.tar.gz" | sha256sum -c -
tar -xzf "$workdir/efa.tar.gz" -C "$workdir"
cd "$workdir/aws-efa-installer"
export DEBIAN_FRONTEND=noninteractive
apt-get update
./efa_installer.sh -y --skip-kmod --skip-limit-conf
rm -rf /var/lib/apt/lists/*
test -x /opt/amazon/efa/bin/fi_info
