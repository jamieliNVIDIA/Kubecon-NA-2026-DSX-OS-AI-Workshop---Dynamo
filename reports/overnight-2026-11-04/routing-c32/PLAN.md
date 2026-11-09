# Fresh C32 routing comparison after model-discovery readiness race

Root explicitly authorized continuing unfinished workshop work with a fresh
C32 campaign. Only root executes network/cluster actions. Preparation here is
offline until root performs the fresh live allocation/admission checks.

## Workflow

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

The resumed user task and root's explicit authorization supply the fresh C32
iteration approval. Canonical AgentX semantics use a file-backed immutable
specification, as in the preceding campaigns; no attempted spec is modified.

## Scope

- Fresh run: `results/workshop-routing-c32-20261105-a1`.
- Fresh owned namespace: `dynamo-ft-routing-c32-20261105-a1`.
- Fresh CPU Pod: `rr-loadgen` in that namespace, new preparation of the exact
  pinned full 393-trace AgentX corpus. Never use the CPU Pod in the old routing
  namespace; it was exclusively handed to the matched P/D workstream.
- Fresh scoped lease: `.local/workshop-routing-c32-20261105.gpu-lease`.
- Only original routing GPU0+2 UUID pairs on cp-0198 and cp-0942. Recheck current
  DRA allocations before every cell. Other workstreams remain independent.

## Fixed parameters and order

Run **two-worker RR → two-worker KV → one-worker RR**, all at C32. Root approved
this fixed order to obtain the routing pair before the previously observed
one-worker overload boundary. Each cell has fresh workers/private compiler
caches; canonical bounded smoke and the mandatory AgentX snapshot primer
precede the measured profile. Do not combine the separate C16 and C32 campaigns
into a claimed controlled capacity curve. Record order, realized mix, prior
node/storage cache history and concurrent node CPU/EFS/network activity.

Keep the exact prior Super VL model/revision, pinned runtime, TP2 H100s, native
1,048,576 context, max-num-seqs 128, 8,192 batched tokens, memory fraction 0.85,
text-only compiled serving, Mamba/cache/kernel flags, 393-trace corpus and
AIPerf source/dataset patch. C means 32 live trees, not HTTP concurrency.
Admission is 900 seconds with 300-second drain. Primer, pacing, seed and context
controls remain unchanged. No canary/liveness relaxation and zero restarts
required. Censored/failed cells cannot support latency speedup or an SLO claim.

## Minimal readiness correction

The old C32 startup smoke requested `/v1/models` about 128 ms before the
frontend committed the discovered model. Worker Ready did not establish model
availability at the frontend. A standalone stdlib helper now polls for the exact
expected model ID, for at most 120 seconds, before the existing four smoke
inferences. HTTP 200, an empty list or another model never passes. Every poll
and the final bounded outcome are retained. This startup gate sends no inference
and does not change profile/primer timing or engine/workload parameters.

The gate lives only in this new campaign. Shared helpers and all old frozen
sources/results are unchanged. Root's P/D frozen input files remain untouched.

## Acceptance and failure handling

Qualify exact model/runtime/args/probes/physical GPU identities, zero restarts,
frontend model presence and current worker discovery/event sources. Preserve
actual running/waiting requests, cache pressure, client cgroups and GPU telemetry.
KV comparison requires positive observed predicted overlap and server usage
evidence. Exported rates retain their actual drain-inclusive denominators.

Collection occurs before a post-run restart check can reject a cell. Preserve
all failed attempts, Kubernetes events and raw exports. Stop the controller on
an engine/infrastructure/collection failure; never silently retune or replay.
Scoped GPU cleanup runs after each attempted cell. This campaign may delete
its own new CPU Pod only after complete successful collection; it never deletes
the borrowed P/D client, caches/PVCs or namespaces. Full controller success
establishes execution/cleanup; comparison eligibility remains per cell.
