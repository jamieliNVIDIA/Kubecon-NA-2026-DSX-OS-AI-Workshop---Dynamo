#!/usr/bin/env bash
# Model-pinned feature retests; logs/receipts remain under the selected run.
set -euo pipefail
runner_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
project_dir="$(cd -- "$(dirname -- "$runner_source")/.." && pwd)"
cd "$project_dir"
# Bash can resume reading this file between long feature actions. Execute a
# content-addressed copy so edits to the tracked runner cannot shift that offset.
if [[ "$runner_source" != "$project_dir"/.local/retest-super-vl-*.sh ]]; then
    runner_sha="$(shasum -a 256 "$runner_source" | awk '{print $1}')"
    frozen_runner="$project_dir/.local/retest-super-vl-$runner_sha.sh"
    mkdir -p "$project_dir/.local"
    if [[ ! -f "$frozen_runner" ]]; then
        cp "$runner_source" "$frozen_runner"
        chmod 400 "$frozen_runner"
    fi
    [[ "$(shasum -a 256 "$frozen_runner" | awk '{print $1}')" == "$runner_sha" ]]
    exec bash "$frozen_runner" "$@"
fi
if [[ $# -lt 1 || $# -gt 2 ]]; then
    printf 'Usage: bash scripts/retest_super_vl.sh RUN [FIRST_FEATURE]\n' >&2
    exit 2
fi
run_dir="$1"
first_feature="${2:-probe}"
case "$first_feature" in probe|agg|image-smoke|sidecar|kvcr|disagg|mx|grove|snapshot-runtime|snapshot|shadow) ;; *) exit 2 ;; esac
source scripts/kubecon-env.sh
test_python="${WORKSHOP_PYTHON:-$project_dir/.venv/bin/python}"
if [[ ! -x "$test_python" ]]; then
    printf 'Run uv sync --locked before starting feature retests.\n' >&2
    exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -f "$run_dir/model-lock.json" ]]; then
    "$test_python" scripts/super_vl_tests.py metadata --run "$run_dir"
fi
"$test_python" - "$run_dir" <<'PY'
import json,sys
from pathlib import Path
run=Path(sys.argv[1])
lock=json.loads((run/'model-lock.json').read_text())
assert lock['model']=='nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'
assert lock['tensor_parallel_size']==2 and lock['gpu_allocation']=='dra'
PY
if ! "$test_python" - "$run_dir" <<'PY'
import json,sys
from pathlib import Path
state=json.loads((Path(sys.argv[1])/'state.json').read_text())
sys.exit(state.get('checks',{}).get('model-staging',{}).get('status')!='passed')
PY
then
    "$test_python" scripts/super_vl_tests.py download --run "$run_dir" > "$run_dir/staging-console.log" 2>&1
fi
"$test_python" scripts/super_vl_tests.py runtime-source --run "$run_dir" > "$run_dir/runtime-source-console.log" 2>&1
started=false
failures=0
for feature in probe agg image-smoke sidecar kvcr disagg mx grove snapshot-runtime snapshot shadow; do
    if [[ "$feature" == "$first_feature" ]]; then started=true; fi
    if [[ "$started" != true ]]; then continue; fi
    if "$test_python" - "$run_dir" "$feature" <<'PY'
import json,sys
from pathlib import Path
state=json.loads((Path(sys.argv[1])/'state.json').read_text())
sys.exit(state.get('checks',{}).get('super-vl-'+sys.argv[2],{}).get('status')!='passed')
PY
    then
        printf 'Already passed in this run: %s\n' "$feature"
        continue
    fi
    printf 'Super VL TP2 retest: %s\n' "$feature"
    if "$test_python" scripts/super_vl_tests.py feature --feature "$feature" --run "$run_dir" > "$run_dir/$feature-console.log" 2>&1; then
        printf 'Completed: %s\n' "$feature"
    else
        failures=$((failures + 1))
        printf 'Blocked: %s (see %s/%s-console.log)\n' "$feature" "$run_dir" "$feature"
        # Failure cleanup is part of the Python feature action. Never start a
        # new graph when that action could not release the preceding workload.
        "$test_python" scripts/super_vl_tests.py idle --run "$run_dir"
    fi
done
"$test_python" scripts/super_vl_tests.py idle --run "$run_dir"
printf 'Feature actions with blockers: %s\n' "$failures"
[[ "$failures" -eq 0 ]]
