#!/usr/bin/env bash
# Read-only connection diagnostics. Logs remain local and ignored by Git.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
probe_host=3.238.63.5
proxy_args=(-o ProxyJump=none)
if [[ "${1:-}" == --proxy ]]; then
    [[ "${2:-}" == gemini ]] || { printf 'Supported proxy: gemini\n' >&2; exit 2; }
    proxy_args=(-J gemini)
elif [[ $# -gt 0 ]]; then
    printf 'Usage: bash scripts/check-jump-host.sh [--proxy gemini]\n' >&2
    exit 2
fi
umask 077
probe_dir="${project_dir}/.local/diagnostics/ssh-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$probe_dir"
printf 'Diagnostic logs: %s\n' "$probe_dir"

if [[ "$(uname -s)" == Darwin ]]; then
    route -n get "$probe_host" > "$probe_dir/route.txt" 2>&1 || true
    rg 'destination:|gateway:|interface:' "$probe_dir/route.txt" || true
    nc -vz -G 8 -w 8 "$probe_host" 22 > "$probe_dir/tcp.txt" 2>&1 || true
else
    ip route get "$probe_host" > "$probe_dir/route.txt" 2>&1 || true
    cat "$probe_dir/route.txt"
    nc -vz -w 8 "$probe_host" 22 > "$probe_dir/tcp.txt" 2>&1 || true
fi
cat "$probe_dir/tcp.txt"

if ssh -v -A -S none "${proxy_args[@]}" -o ControlMaster=no -o BatchMode=yes \
    -o StrictHostKeyChecking=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 \
    "ubuntu@${probe_host}" hostname > "$probe_dir/ssh-output.txt" 2> "$probe_dir/ssh-debug.txt"; then
    probe_status=0
else
    probe_status=$?
fi
cat "$probe_dir/ssh-output.txt"
rg 'Connecting to |Connection established|Remote protocol|Authenticated to |Permission denied|timed out|refused|No route|Host key verification failed|REMOTE HOST IDENTIFICATION' \
    "$probe_dir/ssh-debug.txt" || true
printf 'SSH exit code: %s\n' "$probe_status"
exit "$probe_status"
