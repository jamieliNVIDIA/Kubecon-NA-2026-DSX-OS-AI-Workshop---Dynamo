# Remaining text-only decoder startup: caches versus live warmup

Offline investigation, 2026-11-04 UTC. No runtime, flags, frozen helpers, or
active experiments changed. Exact image:
`nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`;
vLLM `0.31.1rc1.dev23+g43b4aaea3`, Triton `3.7.1`,
FlashInfer `0.7.0.post1`.

**There is no newly missing persistent-Triton-tuning flag to enable.** Exact
installed `vllm/env_override.py:176` already defaults
`TRITON_CACHE_AUTOTUNING` to `1`, and a read-only capture of the currently
starting health seed contains seven SSD `.autotune.json` files. MX's existing
Triton transfer includes regular JSON files under that cache root. The useful
next diagnostic is source vs receiver tuning-file/key reuse, followed by narrow
profiling if necessary. None of this attributes all 28.78 seconds to
autotuning or establishes a measured speedup. Do not schedule a third GPU run
merely to enable a flag already active by default.

## What the qualified receiver actually did

Text-only02 target log, `text-only-mx-artifacts/ft-mx-target-0-target-tvl94-main.log`:

| Event | UTC time / duration | Log lines |
|---|---|---|
| MX installs torch / Triton / FlashInfer caches | 34.79 / 62.32 / 2.04 MiB | 220, 231, 255 |
| Both ranks directly load AOT model | 07:00:51.314 / .322; compile 0.19 / 0.20 s | 4623–4626 |
| Mamba2 SSD Triton warmup starts | 07:00:51.459 | 4628 |
| Both initial backbone profiling timers finish | 07:01:20.098; 28.78 s each | 4672–4673 |
| Registered generic JIT warmup | 0.00 s on both ranks | 4704–4707 |
| Engine init, including cache setup and further warmup | 41.21 s | 4754 |

Graph captures and FlashInfer autotuning occur after the 28.78-second interval.
The 41.21-second engine timer contains the profiling interval; do not add them.
The source had 82.00/82.20-second profiling and approximately 29-second torch
compilation; it also built a FlashInfer selective-state-update module during a
later 22-second graph capture. The receiver's corresponding first graph
captures take 2–3 seconds. Existing file reuse has already removed substantial
cold work.

`monitor_profiling_run` checks that no vLLM backend compilation counter changes
inside this timer. That does not rule out Triton autotuning, kernel loading,
allocator work or execution. The INFO log has a start for Mamba warmup but no
per-layer finish: its finish message is DEBUG. Therefore log timing alone cannot
assign the entire interval to Mamba tuning.

## Why compiled binaries do not eliminate this tuning

The exact installed `mamba_mixer2.py:614–710` implements
`_warmup_ssd_kernels` as a **real minimal forward pass**, with random tensors,
one chunk and batch size one. It warms both absent/present initial-state paths
before allocating the large SSM cache. This is not Triton's compile-only
`.warmup()` operation. The object guard is per layer; the autotuner's cached
choices are shared by matching kernel/key within one process.

That forward calls five `@triton.autotune` kernel families:

| Kernel | Candidate configs | Explicit tuning keys |
|---|---:|---|
| Chunk cumsum | 6 | chunk size, head count |
| Chunk state | 14 | head dimension, state dimension, chunk size |
| State passing | 6 | flattened state dimension |
| Chunk BMM | 9 | chunk size, K, causal flag |
| Chunk scan | 23 | chunk size, head dimension, state dimension, causal flag |

The autotuner additionally includes input tensor dtypes in its key. None of
these decorators supplies `cache_results=True`. In Triton `autotuner.py:21–39`,
the default is false, and the effective value is
`(cache_results or knobs.autotuning.cache) and not knobs.runtime.interpret`.
`knobs.py:374–376` maps that knob to `TRITON_CACHE_AUTOTUNING`, default false.
Without enabling it, a new process can reuse compiled binaries and still
benchmark all candidates to select its configuration.

The exact installed persistent path (`autotuner.py:170–240`):

- Hashes the Triton version/content key, backend target hash, kernel source key,
  cache-invalidating environment, tuning key and full candidate list.
- Stores `<kernel>.autotune.json` through `get_cache_manager`, under the same
  configured `TRITON_CACHE_DIR` as compiled kernels.
- On a disk hit, loads recorded timings, chooses the minimum and skips the
  benchmark loop. The chosen kernel still runs and initializes process-local
  handles/workspaces.
- Falls back to benchmarking if the key is empty or a candidate has a pre-hook.
  The inspected SSD candidate lists have no such hooks.

The default-false value in Triton itself is overridden by the exact installed
vLLM: `env_override.py:174–176` explains that repeated tuning adds restart
latency, writes results into `TRITON_CACHE_DIR`, and sets the variable to `1`
unless explicitly overridden. A separate `kubectl exec` process in the current
health seed reports the variable unset, because that process does not inherit
changes made later inside the Python worker. The current source already has
seven persistent SSD tuning files (all five families, plus separate
state-passing/chunk-scan variants). Container-initial environment and frozen
manifest inspection alone would therefore produce the wrong conclusion.
Neither the seven files nor this environment projection proves the older
text-only02 receiver hit or missed them.

## Cache coverage and limits

MX's installed `engines/vllm/artifacts.py:298–366` transfers torch, Triton,
DeepGEMM, TileLang, CuTe DSL and FlashInfer caches; the FlashInfer transfer also
includes its autotune root. The tar packer includes all regular files beneath
the Triton root, without filtering out `.autotune.json`. Thus persistent Triton
tuning files should fit the existing transfer path, without inventing another
artifact type. Both the source and receiver need the setting before kernel
decorators initialize, and the source must finish tuning before publication.

CuTe DSL is already an available MX artifact type. A “no ready CuTe/DeepGEMM/
TileLang source” INFO line is not evidence that any of those libraries runs,
rebuilds files, or explains this interval. The observed Mamba SSD path uses
Triton. Adding caches blindly has no supported time budget here.

CUDA's `/root/.nv/ComputeCache` is outside these six vLLM artifact roots. A
read-only, point-in-time inventory of the currently starting health seed found
that directory populated, and the Triton root contained both `.cubin` and
`.ptx` files. Those observations do not identify the producer or elapsed cost.
Triton's installed compiler reloads the final backend binary from its cache,
then loads that binary into each new process (`compiler.py:414–470`). Merely
finding an intermediate `.ptx` alongside a `.cubin` does not show driver PTX
compilation. Copying ComputeCache has **no defensible savings estimate** yet;
first verify the existing receiver tuning hits and identify actual driver-JIT
work before adding another cache type.

The initial model profile still executes the configured 8192-token dummy
forward, routes tokens through MoE kernels, allocates intermediate tensors and
workspaces, and initializes per-process state. Mamba also creates tiny warmup
tensors and calls `empty_cache()` per layer. File caches cannot restore those
live allocations or replace this execution. Reducing batch/concurrency/context
or skipping profiling changes the serving envelope/accounting and is not an
equivalent cache optimization. Explicit KV-cache budgeting still invokes
`profile_run()` in this installed worker.

## Smallest meaningful next diagnostic, after the health pair

Before scheduling an optimization arm, inspect the current source's seven SSD
`.autotune.json` files and MX bundle membership. For a receiver, compare the
installed files/keys before profiling
with any files created afterward. A new key indicates a lookup mismatch to
explain, not a reason to blindly enable another cache flag. If persistent tuning
is already a hit, this path has no demonstrated remaining optimization.

Only if that inspection establishes missing persistence or a reusable key
mismatch should a fresh source/receiver candidate change it. Keep native 1M
context, TP2/H100, sequences4, batched tokens8192 and memory0.85. Verify actual
worker settings and cache-file provenance, preserving the same phase timers,
correctness and allocation checks as text-only02.

`TRITON_PRINT_AUTOTUNING=1` is available in the pinned source for reporting
benchmark activity/time. A cache hit itself is silent, so absence of its
benchmark print alone is not a positive hit receipt; combine file/key evidence
with the matched phase timing. If further diagnosis is needed, use a separately
authorized narrow timing probe rather than guessing a CUDA cache benefit.

The opportunity is a subset of the **28.78-second profiling budget**, with
ordinary dummy execution and allocations remaining. Do not promise a number
until a fresh receiver demonstrates a reduction. Avoid
`VLLM_TRITON_FORCE_FIRST_CONFIG` as an equivalent comparison: that setting
selects the first valid kernel instead of preserving measured tuning choices,
and can change serving performance. Graph capture/registered JIT switches are
lower priority given the actual short/zero timers.

## Evidence provenance

- Qualified run: `results/workshop-textonly-pullback-20261103-a1/verified/results/workshop-mx-startup-20261103-textonly02/`.
- Installed vLLM/MX archive: `results/workshop-startup-optimization-20261103/`;
  MRv2 runner: `results/workshop-startup-optimization-20261103-extra/`.
- Nine Mamba/Triton source files: `results/workshop-mamba-startup-sources-20261103-a1/`;
  manifest SHA256 `03b8e237c25766342537839f0d9d3b50a0aef9286ee2a0634c5ecb17275eb31b`;
  all nine file hashes independently matched.
- Exact Triton autotuner/knobs: `results/workshop-triton-autotune-sources-20261103-a1/`;
  manifest SHA256 `d8193ca31836415c3a1703361bb535a17a5cd8580841fda6855c17f4ac568c12`;
  both file hashes independently matched.
- Subsequent static vLLM Triton wrapper, selected initial-container environment
  and seven SSD tuning-file paths:
  `results/workshop-triton-autotune-sources-20261103-a1/env-and-vllm-utils.json`.
- Exact installed activation-site search, with file/line/context:
  `results/workshop-triton-autotune-sources-20261103-a1/override-search.json`.

The cache inventories in those captures belong to the current health seed,
not the finished text-only02 receiver, and were taken while startup could
still populate them. They cannot prove cache hits or misses for text-only02.
