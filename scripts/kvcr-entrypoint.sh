#!/usr/bin/env bash
set -euo pipefail
python3 /kvcr/prepare.py
exec "$@"
