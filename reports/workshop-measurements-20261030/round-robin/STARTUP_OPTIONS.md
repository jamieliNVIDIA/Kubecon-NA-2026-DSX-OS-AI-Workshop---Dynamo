# Further startup reductions with the pinned vLLM runtime

Research only, November 4, 2026. No runtime/configuration changes or experiments
were made. The active routing pipeline and local delegation fence are untouched.

The user has explicitly chosen **text-only coding agents** for this workshop.
The first candidate is therefore `--language-model-only`, retaining Super VL's
language model, native 1,048,576 context, TP2 H100, four engine sequences,
8,192 batched tokens and the full pinned 393-trace AgentX corpus. It removes
unneeded vision work rather than shrinking text requests. Its time saving is
unmeasured; it needs a fresh source/target startup comparison and compatible
new compiler artifacts.

## Evidence and remaining time budget

Runtime: image `e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`,
vLLM `0.31.1rc1.dev23+g43b4aaea3`, Torch `2.13.0+cu130`, Transformers `5.18.0`,
ModelExpress `0.6.0`. The installed static-source inventory is
`results/workshop-startup-optimization-20261103/runtime-sources.json`, SHA256
`90a79bfe3b832f62673ba17cbaaaf083f7a499d2c48595990917893743ef4a80`.
It was collected without importing Torch/vLLM or allocating GPUs.
The three installed MRv2/config/thread files in
`results/workshop-startup-optimization-20261103-extra/` are bound by source-manifest
SHA256 `7926f8cf1f261ea5c165a0a861360ab1cf9d8cc52aed09552355397e9407eee0`.

The verified artifact04 target log is
`results/workshop-mx-pullback-20261103-breakdown/verified/results/`
`workshop-mx-startup-20261103-artifact04/central-mx-artifacts/`
`ft-mx-target-0-target-b4rt6-main.log`. It gives these boundaries:

| Observed interval | Time | Interpretation |
| --- | ---: | --- |
| Apply to observed Ready | 249.70 s | Includes scheduling, startup and readiness observation |
| Container start → MX loader starts | about 63 s | Python/Dynamo/engine/TP/distributed bootstrap combined; not an import-only timer |
| Maximum logged model-loading time | 57.68 s | Includes construction, loader work, transfer and postprocessing |
| Engine preparation | 74.44 s | Profile, KV allocation and warmup; overlaps nested timers below |
| Engine prep starts ~00:33:30 → encoder profiling log 00:34:01.789 | about 32 s | Includes dummy-media/budget preparation before the encoder log; logs do not independently time that preparation |
| Encoder profiling log → AOT-loaded backbone begins ~00:34:05.9 | about 4 s | Bounds a short encoder/transition interval; not a standalone encoder benchmark |
| Backbone profiling/warmup | 27.67–27.72 s | Remains after skipping MM profiling |
| Torch compile after artifact reuse | 0.14–0.15 s | Both ranks actually loaded AOT cache |
| Graph capture | ~2 s per logged pass | A memory-estimation pass and final capture are distinct; ranks run concurrently |
| Main-process MM processor warmup | 40.172 s | Ends 00:32:47, overlapping engine/weight loading; do not add 40 s to a critical-path saving |

The same log shows generic JIT warmup at 0.00 s, FlashInfer autotuning still
invoked with its imported cache, and tiny decoder graph buckets `[1,2,4,8]`.
There is no evidence that another compile-cache switch removes the remaining
74 s. The plausible MM-related engine interval is around **30–40 s**, pending a
timed text-only candidate; this is an inferred candidate budget, not a predicted
guarantee. The 63 s bootstrap interval remains separately.

## Text-only choice: `--language-model-only`

Supported in the installed argument/config files. It makes every modality limit
zero. `ModelConfig._supports_multimodal_inputs()` then returns false when
`enable_mm_embeds` is false (the existing default). This is more complete than
setting only `image=0` while leaving video enabled. Native text context and
sequence limits are independent settings. [Pinned multimodal config](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/config/multimodal.py),
[pinned model config](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/config/model.py).

The Super VL architecture resolves to `NemotronH_Omni_Reasoning_V3`; its installed
`nano_nemotron_vl.py` marks the vision/projection modules as a tower for image,
video and audio. The common tower context replaces disabled tower modules with
missing-layer placeholders, avoiding their GPU weight allocation/loading.
The renderer creates its MM processor only when multimodal inputs are supported,
so text-only configuration also skips its separate processor warmup. The two
common helper paths were checked through GitHub's pinned `43b4aaea3` contents
API; the model-specific marking and config semantics were checked in installed
files. This is static code evidence, not a measured new launch.
[Pinned model implementation](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/model_executor/models/nano_nemotron_vl.py),
[tower helper](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/model_executor/models/interfaces.py),
[renderer](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/renderers/base.py).

This is the authorized workshop service choice. It changes the loaded tensor
set, can free memory for more KV cache, and changes compilation/model hashes.
Use source **and** target configured text-only and rebuild/publish compatible
MX artifacts; do not count an old full-MM artifact as a valid text-only cache
hit. Record resulting cache bytes/block count and verify the same text workload,
context and concurrency. A timing gain could include removal of tower loading
as well as profiling; do not attribute it all to faster transfer.

Pinned excerpts and Git blob IDs are saved under
`results/workshop-startup-options-public-20261104/`: renderer blob
`8c1d91e032b1beb0c90bfc5ec21e21971e3e25fa`, tower-interface blob
`433c373c8e357b0198ee169355e67581e39faf18`. These are upstream excerpts, not
additional installed-file copies. Source/target weight-manifest compatibility
with an existing full-MM MX source remains unverified; configure both sides
text-only for the proposed comparison.

## Other supported controls and their actual scope

| Control | What it changes | Relevance to this target |
| --- | --- | --- |
| `--skip-mm-profiling` | Omits GPU encoder/cache profiling and its dummy-MM input generation; preserves the decoder profile pass | Useful if retaining a VL service; likely redundant once language-model-only disables all MM inputs. Omitting measured MM activation peaks can alter KV capacity. Does not promise to remove the full 74 s |
| `--kv-cache-memory-bytes N` | Selects an explicit per-GPU KV budget; bypasses memory accounting and graph-memory estimation, but still calls `profile_run()` | A calibrated follow-up could remove a few seconds. Copying the suggestion changes capacity: target suggested 27.14 GiB while actual cache was 27.32 GiB |
| `VLLM_ENABLE_STARTUP_PLAN=1` | Persists/reapplies a KV budget under `VLLM_CACHE_ROOT/startup_plan`, gated by hardware/config/rank/Torch/CUDA and free-memory baseline | Supported, opt-in, absent from the default. It persists the conservative suggestion above; it does not cache live engine state or skip decoder/MM profile execution. MX would need to include this separate artifact explicitly |
| `--compilation-config '{"cudagraph_mode":"NONE"}'` | Disables graph execution/capture | Startup/runtime performance tradeoff. Existing captures are already seconds, not most of engine prep; remeasure interactivity |
| `--enforce-eager` or a lower `--optimization-level` | Removes broader compile/graph optimization | Changes the serving execution strategy and can move work to requests or reduce throughput. Does not eliminate the required model/memory profile |
| `--kernel-config '{"enable_jit_warmup":false}'` | Skips proactive JIT kernel warmup | Existing logged generic warmup is 0.00 s. Misses can reappear in user latency; poor current target |
| `--no-enable-flashinfer-autotune` | Avoids tuning search; uses untuned/heuristic paths | Cache reuse already exists. Remaining call is short; test runtime performance before choosing it |

The first three behaviors are verified in installed `gpu_worker.py`,
`config/multimodal.py` and `startup_plan.py`. Installed MRv2 `profile_run()` places
both dummy-media construction and encoder execution behind the MM profiling
gate, then runs the decoder and sampler. Its `supports_mm_inputs` comes from
`ModelConfig.supports_multimodal_inputs`, confirming that language-model-only
skips this whole MM block and makes the profiling flag redundant.
[MRv2 source](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/v1/worker/gpu/model_runner.py),
[worker](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/v1/worker/gpu_worker.py),
[startup plan](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/v1/worker/startup_plan.py).
Kernel controls are declared in the installed configuration and consumed by
kernel warmup. [Kernel config](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/config/kernel.py),
[warmup implementation](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/model_executor/warmup/kernel_warmup.py).

Two tempting controls do less than their names suggest. In the installed worker,
`VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0` changes accounting **after** graph
profiling was called; it is not a shortcut around that pass. Pinned configuration
also forces graph warmups to one on the normal non-eager graph path, so a user
value `cudagraph_num_of_warmups=0` is overwritten there. Likewise
`fast_moe_cold_start` is forced off on newer Torch with opaque-object support;
the current Torch 2.13 configuration already shows false. [Pinned VllmConfig](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/config/vllm.py).

## Runtime/TP bootstrap: supported options are limited

The installed `VLLM_WORKER_MULTIPROC_METHOD` validator accepts only `fork` and
`spawn`. **`forkserver` is not a supported value in this pin.** The default is
fork, but CUDA initialization, NUMA binding, Ray and platform constraints can
force spawn. Establish the actual image/Dynamo launch environment before
proposing a change; a default alone does not prove which method was used.
[Installed-equivalent environment definition](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/envs.py),
[process context](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/utils/system_utils.py).

There is no inspected vLLM flag that reuses a Python interpreter across new Pods.
Prebuilt Python bytecode can reduce parsing, but does not reuse Torch/CUDA/native
extension initialization or NCCL setup. A persistent preloaded process launcher
would be an additional integration, not an existing ModelExpress switch.
For a later diagnostic, CPython `-X importtime`/`PYTHONPROFILEIMPORTTIME=1` can
identify expensive imports, with multithreaded-output limitations. No such probe
was run against the active serving workload. [CPython 3.12](https://docs.python.org/3.12/using/cmdline.html#cmdoption-X).

The installed executor chooses startup Torch threads before forking/spawning
and reduces them for serving. Current logs show 96→1; unconditionally setting
`OMP_NUM_THREADS=1` can slow CPU-parallel loading. Measure CPU throttling/import
and loader phases before choosing a thread change. [Pinned executor](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/v1/executor/multiproc_executor.py),
[thread policy](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/utils/torch_utils.py).

AOT is already working: installed defaults enable AOT on Torch ≥2.10 and mega
AOT on ≥2.12-dev when caching is enabled; both ranks logged direct cache loads.
Further cache work should demonstrate a remaining miss, not merely enable
already-active flags. An AOT cache preserves compiled code; it does not remove
the measured decoder profiling pass.

## Next decision

The MRv2 and renderer/tower paths are confirmed as above. The exact effective
image/Dynamo multiprocessing environment remains unverified; it is not a reason
to defer the text-only recommendation. Propose one fresh **text-only source/target**
startup comparison after the active benchmark
pipeline completes. Keep native 1M context, TP2, seq4/batch8192, full corpus and
correctness/readiness boundaries. Record the changed tensor set, cache identity
and allocated KV capacity. Do not fold changed text-only timings into the
accepted artifact04 trial, claim an unmeasured saving, or lower text context,
concurrency or trace lengths to make startup look equivalent.
