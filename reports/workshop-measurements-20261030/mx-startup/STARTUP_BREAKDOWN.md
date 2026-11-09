# What remains in the 4m10s MX startup?

The matched native-context MX weights-plus-artifacts target reached observed
Ready in **249.70 s**, compared with **553.59 s** for native EFS and **340.86 s**
for peer weights alone. MX made the actual weight copy and compilation short;
process boot, model setup, profiling/warmup and readiness progression remain.
This is one trial per arm, Super VL TP2 H100, native 1,048,576 context, an idle
source, an existing EFS checkpoint and no benchmark load.

## Exclusive wall-clock timeline

All timestamps below are UTC on November 4, 2026 (November 3 Pacific). These
rows are contiguous and **do not overlap**. Model/engine timer starts are
back-calculated from their end logs and reported durations. Kubernetes
timestamps have second precision, and the engine timer is rounded to 0.01 s;
the extra decimal places in machine-readable outputs are arithmetic, not that
level of measurement precision.

| Interval | Time | What the evidence establishes |
| --- | ---: | --- |
| Apply 00:31:20.736 → container started 00:31:29 | 8.26 s | Deployment/operator reconciliation, scheduling and container launch. Pod created 00:31:27, bound 00:31:28; image already present. Costs within this interval are not separately instrumented. |
| Container start → model-load timer start ≈00:32:31.896 | 62.90 s | Worker/runtime and model configuration, EngineCore/TP process startup, distributed/CUDA/NCCL setup. Internal costs are not isolated. |
| Model loading → 00:33:29.576 | 57.68 s | Slower-rank vLLM model-load timer. Includes artifact setup, hidden tensor adoption, NIXL registration, weight copy and postprocessing. |
| Model-load end → engine timer start ≈00:33:30.016 | 0.44 s | Residual between timers; no exclusive operation attribution. |
| Engine initialization → 00:34:44.456 | 74.44 s | vLLM's profile/create-KV-cache/warmup timer. Includes cached AOT loading, profiling, warmup and fresh graph capture. |
| Engine end → observed Ready 00:35:30.435 | 45.98 s | Post-engine setup, endpoint/health registration, canary/probe progression and observer sampling. Exact successful health/probe timestamps are absent. |
| **Total** | **249.70 s** | Monotonic controller measurement: 249.699052976 s. Sum from wall timestamps: 249.699063 s, about 10 μs different. |

The **109.31 s outside the model-load and engine-init timers after container
start** is therefore 62.90 s of pre-loader boot, 0.44 s between timers and
45.98 s after engine initialization. It is not another unreported weight
transfer or compilation timer.

The frontend started in parallel and was Ready at 00:31:39, well before the
GPU worker. Its startup is not an additional sequential cost.

## Where the 63 s before model loading goes

| Observed boundary | Time | Attribution limit |
| --- | ---: | --- |
| Container start → first worker log at 00:31:39.326 | 10.33 s | No logs within this bootstrap interval; imports/runtime launch are an interpretation. |
| First worker log → EngineCore initialization announcement at 00:32:08.426 | 29.10 s | Dynamo/Python/model configuration and EngineCore startup; not separately profiled. |
| EngineCore announcement → inferred model-load start | 23.47 s | TP worker startup and distributed/CUDA/NCCL preparation occur here. This is not a CUDA-only timer. |

Markers include rank-0 distributed initialization at 00:32:18.981, rank-1 at
00:32:28.274, NCCL version at 00:32:29.413, and rank assignments at
00:32:31.502. These locate the work; they do not measure each operation's
exclusive cost. See raw worker lines 1, 48 and 54–65.

## Why model loading still takes 58 s

The prominent measured step is **adopting 120 hidden accelerator tensors as
module buffers: 40.792 s on TP0 and 40.972 s on TP1** (raw lines 295 and 669).
Those rank operations overlap, so this is roughly 41 s of elapsed work, not
82 s. The logs establish this step's name and duration; they do not establish
its implementation-level cause or what optimization would remove it.

| Nested measurement | TP0 | TP1 | Raw worker lines |
| --- | ---: | ---: | --- |
| Hidden accelerator tensor adoption | 40.792 s | 40.972 s | 295, 669 |
| NIXL registration, 1,869 regions per rank | 0.979 s | 1.973 s | 2870, 4052 |
| Actual NIXL copy, 1,869 tensors / 40.27 GB per rank | 6.75 s | 4.96 s | 4081, 4065 |
| Full vLLM model load | 57.680596 s | 57.242886 s | 4103, 4099 |

The tensor-adoption step ends at 00:33:20.976/21.190; registration and copies
follow. Do not label the 41 s step as network transfer or NIXL registration.
Other work inside the full loader includes model construction, metadata,
artifact setup and postprocessing; those costs are not all separately timed.

Compiler-artifact installation is small here: the torch, Triton and FlashInfer
lifecycle timers report **0.381 + 0.407 + 0.184 = 0.972 s**. Their completion
logs run from 00:32:33.560 to 00:32:34.171 (lines 220, 231 and 251). These
timers already include transfer/install work; their nested network and unpack
timers must not be added again. Installation is inside model loading.

## Cache reuse is demonstrated on both TP ranks

After MX installs the torch artifact under `/tmp/workshop-vllm-cache`, the
engine logs **“Directly load AOT compilation from path”** for:

- **TP1:** 00:34:05.898634, cache suffix `rank_1_0/model`, raw line 4164;
  `torch.compile` reports **0.14 s** on the next line.
- **TP0:** 00:34:05.945437, cache suffix `rank_0_0/model`, raw line 4167;
  `torch.compile` reports **0.15 s** on the next line.

Both paths share artifact cache key
`74e5dc7e8394aeae5f7af0996e62e61b3bc40502a81424741c44b39fd7fe0527`.
No installed-cache-unused or recompilation-on-load-failure warning matches
the frozen acceptance checks. This proves real engine use, beyond transfer.

The later two “which ModelExpress installed” lines are duplicate logging from
**Worker 1**, not evidence for two distinct ranks. The rank-specific AOT-load
records above establish the two-rank result independently.

The remaining **74.44 s engine timer is not compilation time**. It includes
encoder profiling (line 4154), initial profiling/warmup of 27.72/27.67 s
(4221–4222), KV-cache sizing/allocation and two fresh CUDA-graph capture
passes (4238/4240 and 4280/4290, about 2 s per pass per rank). The logs show
FlashInfer using its installed autotune cache file (4259), followed by an
autotune invocation that completes in about 0.10 s. These are nested and/or
parallel timers; summing them would not yield an exclusive breakdown of 74 s.
The early part of that timer is not fully profiled by the collected logs.

Separately, the main process reports **40.172 s multimodal warmup** ending at
00:32:47.035 (line 293). It overlaps model loading in other processes and
must not be added as another 40 s phase. Likewise, the shared-memory
broadcast warning mentioning 60 s occurs inside engine initialization; it
does not establish an additional 60 s startup phase.

## What the 46 s readiness tail means

| Boundary | Time |
| --- | ---: |
| Engine initialization ends → generate endpoint registered at 00:34:49.474 | 5.02 s |
| Generate endpoint registered → Pod Ready at 00:35:28 | 38.53 s |
| Pod Ready → controller observes Ready | 2.44 s |

The worker is initialized at 00:34:47.506; generate endpoint and health task
register at 00:34:49.474. The configured canary wait is 10 s, and first request
warnings appear at 00:34:59.482, consistent with that delay. The last recorded
startup-probe failure is 00:34:58; `/live` startup probes have a **30 s period**,
and `/health` readiness probes a **10 s period**. Pod Ready changes at 00:35:28.

This pattern makes probe/canary alignment a plausible contributor. Successful
canary and startup/readiness probe timestamps are not recorded, so the logs
cannot tell exactly how much of 38.53 s was health work versus waiting for the
next probe. Do not describe all 46 s as engine compute, or all as removable
probe delay. First independently checked correct response is recorded at
251.96 s after apply, following readiness and evidence collection.

## Evidence and reproducibility

The parent verified **560 copied files, zero hash mismatches**. The verified
raw tree and old inventories were read only during this analysis. The original
local preflight and full campaign's final combined seal remain separate from
this selected, verified pullback. No serving parameters or cluster resources
changed for this analysis.

- [Raw target worker log](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-pullback-20261103-breakdown/verified/results/workshop-mx-startup-20261103-artifact04/central-mx-artifacts/ft-mx-target-0-target-b4rt6-main.log)
- [Pullback verification](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-pullback-20261103-breakdown/verification.json)
- [Machine-readable timeline and eight input hashes](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-breakdown-20261103-analysis/startup-breakdown.json)
- [Line-numbered evidence excerpts](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-breakdown-20261103-analysis/evidence-excerpts.txt)
- [Exclusive timeline CSV](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-breakdown-20261103-analysis/exclusive-timeline.csv)
- [Read-only derivation script](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-mx-breakdown-20261103-analysis/analyze_breakdown.py)
