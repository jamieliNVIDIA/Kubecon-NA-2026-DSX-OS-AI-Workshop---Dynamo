# Fresh RR versus KV routing comparison

Requested November 4, 2026. One paired repetition at each previously selected
AgentX load point, C1 and C4. The failed original attempt and all C4 scale-out
results remain separate; no old arm or qualification marker is reused.

## Tasks

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

The user's request authorizes the already agreed model, workload and load
points. Use the file-backed AgentX specification because a generic AIPerf MCP
spec cannot express its full replay semantics. Freeze all inputs before remote
execution, then seal each resolved endpoint/worker/profile before profiling.

## Controls

- Model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, revision
  `8a115b9d966adce8c059a7bcf47f49a1e57957d8`.
- Runtime image: `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Two TP2 H100 workers, one each on cp-0198 and cp-0942; exact GPU pairs
  retained across arms. Native 1,048,576 context, four sequences per worker,
  8,192 batched tokens, memory fraction 0.85, prefix cache/block size 64 and the
  existing Mamba/kernel/event settings. Compiled execution, no MX loader.
- Apply the qualified text-only startup settings to **both** policies:
  `--language-model-only`, canary wait 1 s, startup period 2 s / threshold 1,800,
  readiness period 2 s, other effective probe fields unchanged. Private fresh
  per-Pod caches. This is a new text-only policy experiment, not an extra
  repetition of the older multimodal-capable C4 scale-out campaign.
- AIPerf commit `e2c149ee29d3b64798d8ba2176e9f42e0aa89280` with the same
  dataset-revision-only patch; canonical `inferencex-agentx-mvp` replay of all
  393 eligible source traces at corpus revision
  `23f152f6f0f9399a85901b89a6458def0ef16729`, SHA256
  `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
- C1 / C4 live session trees, seed 20261030, 900 s profiling + 300 s drain,
  canonical primer, source lengths/pacing/generation settings unchanged,
  affinity headers disabled, serial preprocessing, 64 GiB CPU-client request /
  96 GiB limit. No corpus truncation, routing-weight tuning or load-point search.

Fixed order: C1 RR → C1 KV → C4 RR → C4 KV. Each arm starts both workers from
fresh Pods with empty prefix caches, then runs the same bounded smoke and
scenario primer. Only the frontend router mode differs within a pair. Stop and
verify both workers/claims gone between arms. Keep worker event publication
enabled in both policies; KV distribution need not be even.

## Qualification fix and acceptance

Parse only the **current frontend Pod's** log. For KV, require two registered
worker IDs and `kv-events` connection hosts matching the two current worker Pod
IPs. Keep metrics and active-sequence topics as diagnostics, not extra KV
sources. Record evidence before raising any qualification error. Accept duplicate
connection log records without allowing a missing or foreign worker endpoint.
KV smoke requests may choose one worker; RR smoke must exercise both.

Retain the semantic gate after profiling: positive observed KV selection count
and prefix-overlap sum, complete valid AIPerf exports, no request errors/context
overflows/cancelled profiling records, matching model/image/profile/GPU identity,
and no restarts. No routing benefit is assumed. Save realized trace/request mix,
worker distribution, cache use, TTFT/ITL, generation speed, canonical/derived
rate denominators and GPU telemetry. N=1 and fixed-order limits remain explicit.

## Ownership and execution

The user explicitly directed concurrent use of different GPUs while Snapshot
keeps its own. Snapshot stays on cp-0124 with its existing global reservation;
do not alter that reservation, its Pods, agent or storage mounts. Routing uses
only cp-0198 and cp-0942, with a separate scoped reservation at
`.local/workshop-rrkv-20261104.gpu-lease` locally and in the stable controller
workspace. The four exact GPU UUIDs are frozen in the campaign spec and DRA
selector. Verify they are unallocated before startup and belong only to this
run afterward. All routing Pods, including frontend and CPU client, stay off
cp-0124. Snapshot's chat has been notified to preserve the concurrent namespace
and scope its cleanup audit to its own resources.

Frontend and CPU client run on cp-0942, alongside one TP2 worker; both routing
policies use that same placement. The nodes each have 191 allocatable CPU cores
and about 2 TiB RAM. This differs from the earlier C4 scale-out placement, which
is historical evidence rather than one arm of this policy experiment. Record
concurrent Snapshot activity and any shared-storage startup contention; perform
no Snapshot or shared infrastructure changes to obtain results.

A detached stable controller owns the new reservation and runs the benchmark;
no laptop-dependent GPU controller or automatic replay of a started arm.

Estimated execution is about two hours for four profiles plus startup/drain
and fresh CPU qualification. Failures preserve their exact inputs and evidence;
scientific settings must not change silently to obtain a passing result.
