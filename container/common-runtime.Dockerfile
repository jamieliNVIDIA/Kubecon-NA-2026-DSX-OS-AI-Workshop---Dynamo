# syntax=docker/dockerfile:1.7
# Build only on linux/amd64. Runtime references and Python inputs are frozen by
# scripts/common_runtime_build.py prepare before this context is uploaded.
ARG VLLM_IMAGE
ARG RUST_IMAGE
FROM ${RUST_IMAGE} AS build-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake git libclang-dev libhwloc-dev libprotobuf-dev libudev-dev pkg-config \
    protobuf-compiler python3-dev python3-pip python3-venv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /tools && /tools/bin/pip install 'uv==0.9.3' \
    && /tools/bin/uv python install 3.12 \
    && /tools/bin/uv venv --python 3.12 /build-python \
    && /tools/bin/uv pip install --python /build-python/bin/python \
       'maturin[patchelf]==1.9.6' 'build==1.3.0' wheel

FROM build-base AS dynamo-builder
ARG DYNAMO_REF
ENV CARGO_BUILD_JOBS=8
RUN git init /src/dynamo && git -C /src/dynamo remote add origin https://github.com/ai-dynamo/dynamo.git \
    && git -C /src/dynamo fetch --depth 1 origin ${DYNAMO_REF} \
    && git -C /src/dynamo checkout --detach FETCH_HEAD \
    && test "$(git -C /src/dynamo rev-parse HEAD)" = "${DYNAMO_REF}"
WORKDIR /src/dynamo/lib/bindings/python
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    /build-python/bin/maturin build --release --locked --features select-service,kv-indexer \
       --interpreter /build-python/bin/python --out /wheels
WORKDIR /src/dynamo
RUN /build-python/bin/python -m build --wheel --outdir /wheels
RUN /build-python/bin/python -m build --wheel --outdir /wheels lib/gpu_memory_service
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    cargo build --locked --release -p dynamo-vllm-sidecar \
    && cp target/release/dynamo-vllm-sidecar /wheels/dynamo-vllm-sidecar

FROM ${VLLM_IMAGE} AS runtime
ARG DYNAMO_REF
LABEL org.opencontainers.image.revision=${DYNAMO_REF}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dynamo-builder /wheels /tmp/dynamo-wheels
COPY inputs /opt/common-build-inputs
COPY install-efa.sh /tmp/install-efa.sh
RUN python3 -m pip install --no-cache-dir --no-deps /tmp/dynamo-wheels/*.whl \
    && install -m 0755 /tmp/dynamo-wheels/dynamo-vllm-sidecar /usr/local/bin/dynamo-vllm-sidecar \
    && python3 -m pip install --no-cache-dir /opt/common-build-inputs/kvcr \
    && python3 -m pip install --no-cache-dir --no-deps \
       /opt/common-build-inputs/modelexpress-*.whl 'nvidia-nccl-cu13==2.30.7' \
    && VLLM_DIR="$(python3 -c 'import os,vllm; print(os.path.dirname(vllm.__file__))')" \
    && cp -a /opt/common-build-inputs/vllm-overlay/. "${VLLM_DIR}/" \
    && bash /tmp/install-efa.sh \
    && python3 -m pip freeze > /opt/common-build-inputs/installed-packages.txt \
    && sha256sum /tmp/dynamo-wheels/*.whl /usr/local/bin/dynamo-vllm-sidecar \
       > /opt/common-build-inputs/built-artifacts.sha256 \
    && rm -rf /tmp/dynamo-wheels /tmp/install-efa.sh
ENV PATH=/opt/amazon/efa/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/amazon/efa/lib:/opt/amazon/efa/lib64:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}
ENV PYTHONHASHSEED=0 VLLM_KV_EVENTS_USE_INT_BLOCK_HASHES=1
COPY common-runtime-probe.py /opt/common-runtime-probe.py
RUN python3 /opt/common-runtime-probe.py --build
WORKDIR /workspace
ENTRYPOINT []
