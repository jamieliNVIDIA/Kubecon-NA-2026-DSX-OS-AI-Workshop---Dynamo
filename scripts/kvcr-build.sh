#!/usr/bin/env bash
# Build pinned Dynamo bindings for the public KVCR integration in an isolated CPU pod.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends cmake git libclang-dev libhwloc-dev libprotobuf-dev libudev-dev pkg-config protobuf-compiler python3-dev python3-pip python3-venv curl ca-certificates
python3 -m venv /tmp/build-tools
/tmp/build-tools/bin/pip install 'uv==0.9.3'
/tmp/build-tools/bin/uv python install 3.12
/tmp/build-tools/bin/uv venv --python 3.12 /tmp/build-python
/tmp/build-tools/bin/uv pip install --python /tmp/build-python/bin/python 'maturin[patchelf]==1.9.6' 'build==1.3.0' wheel
mkdir -p /work/dynamo
git -C /work/dynamo init
git -C /work/dynamo remote add origin https://github.com/ai-dynamo/dynamo.git
git -C /work/dynamo fetch --depth 1 origin "$DYNAMO_REF"
git -C /work/dynamo checkout --detach FETCH_HEAD
test "$(git -C /work/dynamo rev-parse HEAD)" = "$DYNAMO_REF"
export CARGO_BUILD_JOBS=8
cd /work/dynamo/lib/bindings/python
/tmp/build-python/bin/maturin build --release --features select-service,kv-indexer --interpreter /tmp/build-python/bin/python --out /work/wheels
cd /work/dynamo
/tmp/build-python/bin/python -m build --wheel --outdir /work/wheels
mkdir -p "/efs/feature-tests/$TEST_RUN/kvcr-wheels"
cp /work/wheels/*.whl "/efs/feature-tests/$TEST_RUN/kvcr-wheels/"
sha256sum "/efs/feature-tests/$TEST_RUN/kvcr-wheels/"*.whl
printf '%s\n' 'KVCR_DYNAMO_BUILD_COMPLETE'
