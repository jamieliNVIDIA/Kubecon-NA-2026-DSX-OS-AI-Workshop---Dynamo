# Bounded Super VL AgentX round-robin comparison

Prepared October 30, 2026. This is the execution design; per-arm specifications
are sealed after the serving endpoint and token-limit semantics are verified.

## Fixed identities and topology

- Model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`.
- Model/tokenizer revision: `8a115b9d966adce8c059a7bcf47f49a1e57957d8`.
- Image: `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Dynamo 1.6.0, vLLM `0.31.1rc1.dev23+g43b4aaea3`, TP2, H100.
- One worker uses two GPUs; two workers use four GPUs, across cp-0124/cp-0198.
- A dedicated CPU-only load generator runs on cp-0942, using a frozen AIPerf venv.
  Freeze `AIPERF_DATASET_WEKA_PARALLEL_WORKERS=1` for serial, semantics-preserving
  reconstruction. Its resource qualification uses 64Gi requested/96Gi maximum RAM,
  4 requested/8 maximum CPUs, and 40Gi requested/80Gi maximum ephemeral storage.
  No trace filter or scheduling change is introduced by this preprocessing control.
- AIPerf source `e2c149ee29d3b64798d8ba2176e9f42e0aa89280`, package 0.13.0,
  plus the verified single-line public-dataset revision pin.
- Use the native AIPerf CLI with hashed per-arm specs. The available AIPerf MCP
  `create_spec` schema only accepts synthetic/Mooncake/custom/AIMO dataset types
  and requires a request count; it cannot faithfully express the duration-based
  AgentX public-dataset scenario and live-tree concurrency contract.
- Native model context 1,048,576; remove the feature test's explicit 8192 cap.
  Keep four maximum concurrent sequences per worker, 8192 batched tokens,
  GPU memory utilization 0.85, prefix caching, block size 64, and other serving
  parameters unchanged. This configuration must pass fresh startup qualification.
- Explicit round-robin frontend routing. No session-affinity request headers.

## Workload

- Scenario: `inferencex-agentx-mvp`.
- Dataset: `semianalysis_cc_traces_weka_062126`, backed by
  `semianalysisai/cc-traces-weka-062126` at
  `23f152f6f0f9399a85901b89a6458def0ef16729`.
- Original corpus file: 1,847,151,435 bytes, SHA256
  `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
- All 393 source trajectories are eligible at the native context cap. No input,
  output, or trajectory-count truncation; maintain subagent topology and timing.
- Seed 20261030, initial trajectory ratio range 0.0–1.0, system idle-gap cap 10s,
  first-turn-prefix cache busting, streaming, ignore EOS, server token counts.
- Primary concurrency points: **one and four live agent/session trees**. Child
  fan-out may produce more concurrent HTTP requests than the tree limit.
- Profile 900s, profile drain 300s, request timeout 1800s, mandatory snapshot-primer
  warmup grace 1800s. No optional cache-pressure warmup or fixed request-rate cap.
- Endpoint output-token-limit field is resolved with a bounded smoke before the
  immutable arm profiles are sealed. No unbounded-generation assumption.

AgentX is a closed-loop, live-tree-concurrency comparison. Keeping the same load
means keeping the tree limit, corpus/seed, and pacing rules, not forcing an equal
requests-per-second rate. A faster arm may recycle more trajectories during the
same profile duration. Retain selected trajectory IDs and per-request input/output
lengths so differences in achieved request mix remain visible.

## Comparison sequence

1. Qualify the native-context server and verify actual context/cache capacity,
   model ID, image digests, DRA allocations, and bounded completion behavior.
2. For tree concurrency 1, measure one worker, then manually add the second and
   measure the same total offered AgentX load. Both arms use the same seed and
   scenario semantics.
3. Stop owned GPU activity and offer the GPU lease to the MX workstream before
   extending the sweep.
4. For tree concurrency 4, run the corresponding one-versus-two pair under the
   same frozen settings and record it as a separate pair.
5. Initial scope is one paired repetition per concurrency point. More repeats or
   additional load points require a separately recorded extension; do not silently
   expand or tune around failed runs.

Each normal CLI invocation generates a fresh benchmark ID. Its cache-bust marker
includes that ID while remaining stable for a session tree and its descendants,
including warmup-to-profile continuity. Keep normal fresh benchmark IDs; do not
force the same prefix namespace between comparison arms.

This is a labeled operational scale-out design: the first worker survives while
the new worker starts. Existing cache occupancy can differ, so capture cache and
request counters before/after, retain the mandatory scenario warmup in both arms,
and report these conditions. It is not a claim that the two arms begin from
identical empty caches or establish maximum throughput.

## Evidence and outcomes

Retain exact resolved configurations and hashes, all effective commands and
versions, model and image identities, Pod/GPU placement, startup logs, endpoint
smokes, client errors, worker routing/request counters, raw AIPerf exports, and
serving GPU telemetry. Report completed/failed/partial session trees separately
from individual requests. Summarize per-user decode throughput, aggregate output
throughput, TTFT, ITL, end-to-end latency percentiles, achieved concurrency,
cache-reuse observations, and the one-to-two-worker ratios. Report decode-only
`output_token_throughput_per_user` separately from AgentX's end-to-end normalized
interactivity (`e2e_normalized_interactivity_p90/p75`), which includes first-token
delay. Missing client `cached_tokens` fields are unavailable data, not zero hits.

Every GPU phase requires the shared exclusive lease. Hold large downloads and
shared-storage preprocessing while MX runs timed startup intervals. Preserve
failed startup or benchmark attempts instead of changing model, traces, or
context semantics to force a result.
