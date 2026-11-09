# Reducing startup further within ModelExpress

The largest MX-specific opportunity to investigate is the **40.79/40.97 s
hidden-tensor adoption** step. It is a correctness-preserving model traversal,
not weight transfer and not a global garbage-collector scan. There is no
supported MX 0.6.0 switch to bypass it. Profile and optimize that traversal;
do not remove it. Registration tuning is available, but addresses only the
**0.98/1.97 s** registration step in this particular run.

This is static source research, not a new performance result. No runtime,
cluster resources, frozen helpers or scientific parameters changed. Measured
timings refer to the single matched Super VL TP2 H100/native-1M-context
artifact04 trial documented in [STARTUP_BREAKDOWN.md](STARTUP_BREAKDOWN.md).

## Exact installed implementation

The root agent retrieved installed Python files from the same pinned image
through the existing CPU client, without importing torch/vLLM or using GPUs.
The receipt identifies MX **0.6.0**, vLLM
`0.31.1rc1.dev23+g43b4aaea3` and inference image
`sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
Four relevant installed files match upstream tag **v0.6.0 byte for byte**:

| Installed file | Git blob SHA-1 |
| --- | --- |
| `tensor_utils.py` | `d6707bc9acf30302a5afad813ab140c5ffd1981f` |
| `engines/vllm/adapter.py` | `633646a0dbca9ff35801da9626ab70798aab5c50` |
| `load_strategy/base.py` | `3bed3cd9f7281cec3b64618b376425b8b77e7ccf` |
| `envs.py` | `f14be75ff8433e012e7883b1b228c3b9d5291ec5` |

The vLLM adapter's `discover_tensors()` unconditionally calls
`adopt_hidden_tensors()` before collecting parameters and buffers. The adoption
helper visits module attributes, recursively walks lists/dicts/plain Python
objects to depth 20, and registers discovered accelerator tensors that are not
already represented by a known pointer. It creates a fresh visited set for
each attribute. That permits repeated traversal of shared object subgraphs.
There is no `gc.get_objects()` call in this helper. The observed timer covers
the traversal and buffer adoption together; it does not isolate either cost.
[Installed helper](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/tensor_utils.py:107),
[adapter call](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/engines/vllm/adapter.py:208),
[upstream v0.6.0 implementation](https://github.com/ai-dynamo/modelexpress/blob/v0.6.0/modelexpress_client/python/modelexpress/tensor_utils.py#L176).

Repeated traversal is a plausible performance mechanism, **not a measured
diagnosis of which objects consumed these 41 s**. We do not yet have per-root
walk times, visit counts or the 120 adopted tensor paths for this run. Nor do
we have evidence that explicitly collecting/disabling Python cyclic GC would
help; a Python profiler would need to establish any GC contribution.

## Why bypassing it is unsafe

The original fix, PR **#241**, addressed corrupted NVFP4 MoE inference even
when every registered tensor matched the donor. Quantization postprocessing
had created derived reciprocal activation scales on ordinary Python objects;
those scales retained dummy-weight values on the receiver because they were
absent from its transfer manifest. Adoption made them transferable. The PR's
small scan times on other models do not predict this Super VL run, but show
that 41 s is not an intrinsic constant of the feature.
[Correctness rationale and original validation](https://github.com/ai-dynamo/modelexpress/pull/241).

Our model is itself NVFP4 MoE, and the run adopted 120 tensors. Do not assume
they are optional scratch space. `capture_tensor_attrs()` catches direct
tensor assignments on `nn.Module`; it does not replace recursive discovery of
tensors nested in non-Module objects. Disabling MX compatibility patches is
also not a supported way to skip adoption. The internal
`reuse_discovered=True` path only reuses an already populated tensor catalog;
it does not give a fresh receiver a valid manifest for free.
[Installed registration path](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/load_strategy/base.py:127).

## Options and the size of the opportunity

| Option | Status and intended effect | Bound from this run |
| --- | --- | --- |
| Profile adoption by module/attribute; optimize repeated traversal while retaining the complete manifest | Targeted instrumentation/code work. First candidate for explaining the MX hotspot. | About 41 s currently lies in this step on both ranks in parallel. This is an opportunity ceiling for that step, not a promised wall-clock saving. |
| `MX_POOL_REG=1` | Existing opt-in allocation-level registration. It discovers CUDA allocation boundaries and registers each allocation instead of each tensor; tensor discovery still runs first. | Registration itself is <2 s on the slower rank here. Discovery overhead and transport compatibility can reduce or reverse the gain. |
| `MX_VMM_ARENA=1` | Existing alternative allocator/registration path; requires qualifying this exact GPU/driver/NIXL/transport combination. | Also targets registration/allocation behavior; no evidence that it removes the 41 s object walk. Lower priority here. |
| NIC selection/topology tuning | Installed `MX_RDMA_NIC_PIN` configures `UCX_NET_DEVICES`; it is not an established LIBFABRIC/EFA tuning fix for this run. | Copies are already 4.96–6.75 s per rank; registration is separate. Cannot remove the scan or engine boot. |
| Faster storage / ModelStreamer / InstantTensor / GDS | MX storage strategies for initial source startup or fallback. | Our accepted receivers already use peer weights. Storage-read knobs do not accelerate the successful P2P scan. |
| Artifact transport/chunk-size tuning | Existing `MX_ARTIFACT_TRANSFER_CHUNK_SIZE`; compatible artifacts already transfer and are used. | All three installed artifact lifecycle timers total 0.972 s. Low priority; no evidence of a large remaining transfer bottleneck. |

The installed pool-registration implementation documents the allocation-based
semantics and keeps it off by default. Its initial upstream validation used a
different model and InfiniBand stack, so that speedup cannot be borrowed for
our EFA result.
[Installed pool registration](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/nixl_transfer.py:303),
[upstream pool-registration change](https://github.com/ai-dynamo/modelexpress/pull/267).

**Do not propose forcing `MX_ARENA_SINGLE_MR=1` on our EFA setup.** The installed
code says multi-allocation single-MR operation was validated on dmabuf/IB;
the default may fall back to per-tensor registration for multi-handle arenas.
The UCX/CUDA-IPC caveats are transport-specific, not a general recipe for
LIBFABRIC/EFA.
[Installed arena constraints](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/nixl_transfer.py:413),
[initial arena validation](https://github.com/ai-dynamo/modelexpress/pull/282).

Likewise, `MX_RDMA_NIC_PIN` ultimately writes `UCX_NET_DEVICES` in the installed
`ucx_utils.py`; do not assume that changes EFA rail selection under the
`LIBFABRIC` backend.
[Installed NIC setting](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/modelexpress/ucx_utils.py:428).

## What newer upstream code changes

The inspected upstream snapshot `5200e0393288e3ceb981b0635c1838326ab27e65`
still uses recursive adoption and a fresh visited set per module attribute.
It adds exclusions for `kv_cache` and `aot_compiled_fn`, plus a predicate for
one exact Kimi K3 collective-state object. PR **#911** prevents copying
process-local peer pointers/barriers/workspaces; it preserves hidden
quantization-tensor adoption. These are correctness boundaries, not evidence
of a general Super VL traversal speed fix. An upgrade alone has no established
41 s saving.
[Newer tensor discovery](https://github.com/ai-dynamo/modelexpress/blob/5200e0393288e3ceb981b0635c1838326ab27e65/modelexpress_client/python/modelexpress/tensor_utils.py#L239),
[Kimi K3 fix](https://github.com/ai-dynamo/modelexpress/pull/911).

Issue **#915** discusses the unresolved general boundary between transferable
derived model tensors and instance-local state. It supports using explicit
runtime/model knowledge rather than a blanket exclusion of hidden tensors;
it does not establish a production-ready replacement catalog API.
[Upstream boundary discussion](https://github.com/ai-dynamo/modelexpress/issues/915).

## A behavior-preserving investigation

1. In a fresh diagnostic candidate, time each root attribute walk and count
   objects visited, cacheable shared subgraphs and tensors found. Keep logging
   at INFO and add narrowly scoped diagnostics: existing MX DEBUG logging also
   computes per-tensor GPU checksums, which would distort startup timings.
2. If repeated subgraphs dominate, prototype per-invocation memoization of
   traversal results while preserving relative paths and alias semantics.
   Blindly sharing one global visited set can change discovery names or miss
   an object first reached near the depth limit; do not treat that edit as
   automatically behavior-preserving.
3. Compare old/new discovered names, storage descriptors, pointer-deduplication
   behavior and adopted tensor coverage. CPU fixtures should include shared
   quant objects, cycles, aliases, nested containers, depth-limit cases and
   raising/lazy attributes. Identical manifests are necessary, not sufficient.
4. Qualify both donor and receiver under the same new implementation, then
   compare deterministic source/target outputs across diverse prompts and
   verify chained publication. Use a fresh immutable run with all original
   scientific controls retained before claiming startup savings.

Longer term, having runtime/quantization code register all transferable derived
tensors explicitly, or supply a complete catalog, could avoid generic discovery.
That is an integration/code change requiring a completeness contract; there
is no such supported bypass in the installed configuration reference.

Even eliminating this step would leave roughly **209 s** if every other
boundary were unchanged. That arithmetic is not a prediction: parallel work
and health-probe alignment can change the wall-clock outcome. Dynamo/Python
boot, vLLM profiling/warmup and readiness remain separate opportunities.

## Preserved research evidence

- [Installed runtime receipt](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/runtime-sources.json)
- [Four exact installed/upstream byte comparisons](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-optimization-research-20261103/installed-v060-comparison.json)
- [Upstream file URLs and Git blob identities](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-optimization-research-20261103/source-index.json)
- [v0.6.0 → inspected newer tensor-utils diff](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-optimization-research-20261103/tensor-utils-v060-to-current.diff)
