#!/usr/bin/env bash
# Run a published immutable candidate through the bounded feature matrix.
set -euo pipefail
if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    printf 'Usage: bash scripts/qualify_common_runtime.sh BUILD_RUN TEST_RUN [FIRST_FEATURE]\n' >&2
    exit 2
fi
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
source scripts/kubecon-env.sh
test_python="${COMMON_TEST_PYTHON:-${WORKSHOP_PYTHON:-$project_dir/.venv/bin/python}}"
if [[ ! -x "$test_python" ]]; then
    printf 'Run uv sync --locked before qualifying a runtime.\n' >&2
    exit 1
fi
first_feature="${3:-probe}"
case "$first_feature" in probe|agg|sidecar|kvcr|disagg|mx|grove|shadow-runtime|snapshot) ;; *) exit 2 ;; esac
if [ "$#" -eq 2 ]; then
    "$test_python" scripts/common_runtime_tests.py prepare --build-run "$1" --run "$2"
else
    "$test_python" - "$1" "$2" <<'PY'
import json,sys
from pathlib import Path
build,test=map(Path,sys.argv[1:])
candidate=json.loads((build/'common-runtime-candidate.json').read_text())
lock=json.loads((test/'model-lock.json').read_text())
state=json.loads((test/'state.json').read_text())
assert lock['runtime_image']==candidate['image'] and lock['common_runtime']
assert lock['runtime_source_revision']==candidate['dynamo_source']
assert Path(state['common_build_run']).resolve()==build.resolve()
PY
fi
started=false
for feature in probe agg sidecar kvcr disagg mx grove shadow-runtime snapshot; do
    if [ "$feature" = "$first_feature" ]; then started=true; fi
    if [ "$started" != true ]; then continue; fi
    printf '\nCommon-runtime qualification: %s\n' "$feature"
    "$test_python" scripts/common_runtime_tests.py "$feature" --run "$2"
done
"$test_python" scripts/common_runtime_tests.py cleanup --run "$2"
"$test_python" scripts/common_runtime_tests.py status --run "$2"
"$test_python" scripts/validate_common_runtime_manifests.py --run "$2"
"$test_python" scripts/common_runtime_tests.py record --run "$2"
