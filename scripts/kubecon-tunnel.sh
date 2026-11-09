#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${project_dir}/.local"
control_socket="${state_dir}/ssh-control"
jump_host="ubuntu@3.238.63.5"
forward="127.0.0.1:16443:172.31.51.173:6443"

umask 077
mkdir -p "$state_dir"
chmod 700 "$state_dir"

running() {
    ssh -S "$control_socket" -O check "$jump_host" >/dev/null 2>&1
}

case "${1:-start}" in
    start)
        if running; then
            printf 'KubeCon API tunnel is already running on 127.0.0.1:16443.\n'
            exit 0
        fi
        ssh -M -S "$control_socket" -fNT \
            -o BatchMode=yes \
            -o StrictHostKeyChecking=yes \
            -o ConnectTimeout=15 \
            -o ExitOnForwardFailure=yes \
            -o ServerAliveInterval=30 \
            -o ServerAliveCountMax=3 \
            -o ForwardAgent=no \
            -L "$forward" "$jump_host"
        printf 'KubeCon API tunnel started on 127.0.0.1:16443.\n'
        ;;
    status)
        ssh -S "$control_socket" -O check "$jump_host"
        ;;
    stop)
        if running; then
            ssh -S "$control_socket" -O exit "$jump_host"
        else
            printf 'KubeCon API tunnel is not running.\n'
        fi
        ;;
    *)
        printf 'Usage: %s [start|status|stop]\n' "$0" >&2
        exit 2
        ;;
esac
