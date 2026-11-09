# Reducing startup before Snapshot

November 3, 2026. Static research against the installed workshop image, not a
new startup result. The current measured MX weights-plus-artifacts startup is
249.70 s. The user has now selected **text-only Super VL** for the coding-agent
workload; multimodal serving is unnecessary here.

## First candidate: disable multimodal serving

Use the installed vLLM **`--language-model-only`** option, rather than merely
avoiding image requests or skipping encoder profiling. It makes the configured
limit zero for every modality. With precomputed multimodal embeddings disabled
(the normal configuration), `ModelConfig.supports_multimodal_inputs` becomes
false. In the actual ModelRunnerV2 used by this image, this skips both
`MultiModalBudget` dummy-input construction and encoder-cache profiling.
Decoder profiling, KV-cache allocation and graph/warmup work still run.

Pinned common vLLM helpers also avoid creating a multimodal processor and
replace disabled tower modules with missing-layer placeholders; the installed
Super VL implementation uses that tower mechanism. Thus the text-only path
also avoids processor warmup and GPU allocation/loading for those towers.
This remains static code evidence, not a qualified new MX launch.
See [the detailed vLLM investigation](../round-robin/STARTUP_OPTIONS.md) for
the pinned tower/renderer excerpts and blob identities.

- [Installed CLI definition](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/vllm/engine/arg_utils.py:1441)
- [Installed modality-limit behavior](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/vllm/config/multimodal.py:699)
- [Installed text-only detection](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/vllm/config/model.py:909)
- [Installed ModelRunnerV2 profiling path](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103-extra/sources/vllm/v1/worker/gpu/model_runner.py:973)
- [Pinned public implementation](https://github.com/vllm-project/vllm/blob/43b4aaea3/vllm/config/multimodal.py#L304)

The accepted full-multimodal run spends roughly 36 s between engine-preparation
start and AOT loading. The GPU encoder profile begins about 32 s into that
interval; dummy-media preparation is a plausible contributor to the preceding
gap, but it is not separately instrumented. **Roughly 30–40 s is a candidate
budget to investigate, not a demonstrated saving.** Main-process multimodal
preprocessor warmup separately reports 40.17 s, but overlaps model loading;
do not add another 40 s to the projected elapsed-time improvement.

Text-only mode changes the serving configuration and is explicitly included in
vLLM's model-configuration hash; it may also change the GPU tensor manifest and
available KV-cache capacity. Configure the
MX source and target alike, generate fresh compatible compiler artifacts and
record the new identity. Do not assume the previous multimodal source/artifacts
are interchangeable. Preserve the previous frozen results. A fair new storage
versus peer-weights versus peer-weights-plus-artifacts comparison must use the
same text-only setting in all arms.

[Installed compilation-identity factor](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-startup-optimization-20261103/sources/vllm/config/model.py:510).

## Other candidates, ranked by evidence and effort

| Candidate | Evidence / opportunity | Next action and constraints |
| --- | --- | --- |
| Text-only Super VL | Supported flag; eliminates unused MM profiling paths. Roughly 30–40 s of candidate work in the present engine timeline. | First configuration experiment, keeping the same model/revision, TP2, native 1M context, sequence and batching limits. Measure first correct response, readiness and output behavior. |
| Faster health/probe progression | 45.98 s from engine initialization to observed Ready; includes 5.02 s to endpoint registration. Current canary wait is 10 s, startup probe period 30 s, readiness period 10 s. | Compare 1–2 s probe periods while retaining the total startup failure window and real health checks. `DYN_CANARY_WAIT_TIME=1` also shortens idle-canary intervals tenfold; a code change sending the first canary immediately could preserve the steady-state interval. Not all 46 s is removable. |
| Optimize MX tensor discovery | Hidden tensor adoption takes 40.79/40.97 s on parallel ranks. It walks Python model-object graphs and may revisit shared objects. | Profile per-attribute time/visits, then optimize repeated traversal while preserving the complete tensor catalog. No supported bypass. Derived NVFP4 quantization scales are necessary for correct inference. |
| Profile bootstrap before loading | 62.90 s between container start and model-loader start, including process setup and distributed initialization. | Add import/process/collective timing before changing thread counts or start method. Current sources support fork/spawn, not forkserver. No established whole-phase saving. |
| Reuse a vLLM startup plan / fixed KV budget | Existing experimental path can avoid some memory-measurement work. It still calls the decoder/MM profile path as applicable. | Lower priority. Reconcile actual allocated cache bytes/blocks; the logged suggested KV budget is slightly smaller than the measured allocation, so applying it is not automatically capacity-equivalent. |

The readiness behavior is supported by the exact Dynamo runtime source at
`ea23e5130c1bfbadec477b99449d0cee5598caa0`:
[health task](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/health_check.rs#L80),
[configuration](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/config.rs#L265).
Successful canary/probe timestamps were not captured in the original trial;
the exact removable wait remains an open measurement.

See [MX tensor-discovery research](../mx-startup/TENSOR_ADOPTION_RESEARCH.md)
for the installed/upstream comparison, correctness history and transport
caveats. About 41 s is the present discovery-step budget, not a promise of
41 s savings, and text-only mode may itself change that cost.

## Low-priority changes for this run

- Compiler artifact reuse is already working on both ranks. Torch compilation
  reports about 0.15 s; enabling AOT again adds no new feature here.
- Actual NIXL weight copies take roughly 5–7 s per rank; registration takes
  roughly 1–2 s. NIC/registration tuning cannot explain away the 41 s traversal.
- Artifact transfer/install lifecycle timers total about 0.97 s.
- CUDA-graph captures take about 2 s per pass; FlashInfer autotuning uses its
  transferred cache and finishes in about 0.1 s. Disabling graphs/autotuning
  is not the leading opportunity, and can change serving performance.
- Reducing the native context, batch or concurrency limits would change the
  serving envelope. They are not part of this proposed text-only optimization.

## Measurement sequence

1. Finish the already-running fixed routing comparisons; do not mutate them.
2. Freeze a fresh text-only configuration and artifact identity. Qualify a
   matching seed/receiver, successful MX P2P transfer, real two-rank compilation
   cache hits and correct text generation. Record actual KV-cache capacity.
3. Compare the original full-MM setting with the text-only setting under the
   same existing probe policy. Then isolate health/probe changes in a separate
   arm. Do not mix their effects in one reported speedup.
4. Once the text-only baseline is measured, decide whether MX traversal code
   work is still worthwhile. Profile before modifying discovery semantics.
5. Re-run the three loading paths with the final qualified configuration for
   workshop comparison, retaining single-trial and storage-cache caveats.

These options stay within ordinary MX loading plus reusable compiler files.
They do not restore a running process, initialized GPU state or a Snapshot.
Opportunity estimates overlap and must not be summed into a promised result.

## Provenance

- [Measured startup breakdown](../mx-startup/STARTUP_BREAKDOWN.md)
- Static installed sources and SHA-256 records:
  `results/workshop-startup-optimization-20261103/runtime-sources.json`
  and `results/workshop-startup-optimization-20261103-extra/runtime-sources.json`.
- vLLM `0.31.1rc1.dev23+g43b4aaea3`; MX `0.6.0`; inference image
  `sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Source retrieval read only static Python files from the existing CPU client,
  verified its image/UID and did not import torch/vLLM/MX or launch GPU work.
- No new GPU run, source patch, runtime flag change or probe mutation has been
  performed as part of this investigation.
