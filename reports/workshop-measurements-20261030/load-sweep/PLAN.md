# Higher-load AgentX scaling and routing sweep

The user selected **16, 32, 64 and 128 live session trees** on November 4, 2026,
for one TP2 worker with RR, two TP2 workers with RR, and two TP2 workers with
KV-aware routing. This replaces C1/C4 as the performance investigation. Preserve
those earlier results as low-load diagnostics; they establish neither capacity
nor the need for a second worker. Sequential requests can still benefit from
cache locality at C1, and an AgentX tree can include parallel descendants.

## Tasks

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

The user's selected range authorizes the new sweep. Parameters are file-backed
because the generic MCP specification cannot express canonical AgentX replay.
Freeze model, workload, manifests and controller sources before execution.

## Fixed controls

- Same Super VL model/revision, runtime digest, full 393-trace pinned AgentX
  corpus, AIPerf commit and dataset-only patch as the preceding campaign.
- Compiled text-only TP2 H100 serving, native 1,048,576 context, 8,192 batched
  tokens, memory fraction 0.85, prefix caching and the same kernel/Mamba flags.
- Raise `--max-num-seqs` from 4 to **128 per worker**, consistently across all
  three configurations. This is a new engine configuration. Qualify startup,
  available KV capacity and bounded inference before profiling. Stop and report
  an admission failure; do not silently lower the cap or context to obtain data.
- AgentX C16/C32/C64/C128, seed 20261030, 900 s admission plus 300 s bounded
  drain, canonical snapshot primers, recorded prompt/output lengths and pacing,
  fresh CLI benchmark IDs/cache-bust namespaces, no affinity headers or tuning.
- C counts live trees, not simultaneous HTTP requests. Record actual engine
  running/waiting requests, cache occupancy/preemptions and active sequences.
  Cache capacity and engine scheduling can limit effective batch size.
- CPU client on cp-0942: requests 4 CPU / 64 GiB / 40 GiB ephemeral, limits
  8 CPU / 96 GiB / 80 GiB ephemeral, serial preprocessing. Fresh qualification
  and 24-hour Pod deadline; record CPU throttling/memory during each profile.

## Order and cache handling

Run three configurations serially: one-worker RR, two-worker RR, two-worker KV.
Within each, run C16 → C32 → C64 → C128. Fresh worker processes/private compiler
caches for each configuration, retained workers across its load points. Each
profile uses its own normal cache-bust namespace and mandatory snapshot primer;
previous load points' cache entries remain evictable. This avoids twelve full
model startups. Record that initial occupancy is not identical across points.
Retain the default router weights, event publication in every configuration,
and fixed GPU pairs. These are N=1 curves in fixed order, with realized trace
mix and cache-history limitations, not a universal routing or capacity claim.

One worker uses the frozen TP2 pair on cp-0198; the second adds the frozen TP2
pair on cp-0942. Frontend/client stay on cp-0942. Use only the four UUIDs already
reserved for routing, rechecking live DRA allocations before each deployment.
Use a separate load-sweep namespace and scoped lease. Preserve cp-0124 and all
other workstreams/global leases; cp-0124 is currently used by the KVCR workstream.

## Acceptance and interpretation

Require correct model/runtime/args/probes/GPU identity, zero engine restarts,
healthy endpoint, and current-Pod discovery/event sources. Cache-aware runs
must observe positive predicted prefix overlap before claiming cache reuse.
Keep complete raw exports, source/cell hashes, per-request phases and trace
identity, distributions, actual drain durations, cache counters and GPU/client
telemetry. Report both canonical exported rates and separately labeled rates
over the common 900 s admission window; do not treat different drain-inclusive
denominators as serving-capacity differences.

Treat bounded phase-end cancellations and request errors as explicit stress
outcomes, never discard them to improve a latency curve. A censored/invalid
cell cannot support an SLO or speedup claim. Preserve it and continue the fixed
matrix only if the profile terminated normally, the runtime stayed healthy,
and the artifacts can be interpreted. Infrastructure, startup or corrupt/missing
export failures stop the controller. Never lower load, truncate data or tune
router/engine flags within this frozen sweep.

Present throughput versus per-user decode/interactivity, TTFT/ITL and queue/
cache pressure for each configuration. Identify the observed knee rather than
assuming saturation at a chosen C. If C128 still leaves capacity, report that
the tested range has not found the knee. Any extension needs a new spec.
