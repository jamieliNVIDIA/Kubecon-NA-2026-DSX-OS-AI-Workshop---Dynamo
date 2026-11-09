# AgentX routing load sweep

**Morning closeout:** three C16 cells are now independently accepted and have
two usable comparisons. [Results, limits and source hashes](routing-sweep/C16-RESULTS.md).
The controller stopped at **00:56:51 Pacific** on a frontend model-discovery
readiness race before C32 profiling. There are no C32 measurements. All 1,040
transported files and 47 frozen payload sources verified; scoped GPU cleanup
and the recovered live inventory agree. The exact owned local GPU reservation
has been released; the CPU client remains retained. No new benchmark or cluster
mutation was performed during the morning collection/closeout.

**Later fresh C32 campaign:** [the two-worker RR/KV pair is independently
accepted](routing-c32/C32-RESULTS.md), with 650/688 measured requests and no
errors/overflows/canceled profile records. KV improved cache reuse and TTFT tails
while mean decode speed was 4% lower. One-worker C32 failed during the mandatory
primer: Kubernetes explicitly recorded a liveness-triggered restart. This is
separate from the earlier frontend-readiness race, fixed in the new campaign's
startup gate. No eligible one-worker C32 performance comparison exists. The new
run and changed fixed order stay separate from the original C16 observations.

**CPU client handoff:** root's read-only probe subsequently verified exact Pod
UID `4385c581-2c2c-446a-8f7d-123617386cf8`, 13 data/cache/model/helper files,
3,517 pinned source members and no active benchmark processes. Exclusive future
use is explicitly handed to the fresh matched P/D campaign, with root as the
sole live executor. The old routing controller is retired for future execution;
no routing benchmark or CPU cleanup is planned on this client. P/D cleanup must
retain the borrowed Pod, cache, PVC and namespace and preserve old evidence.
[Explicit ownership acknowledgement](../receipts/2026-11-05-routing-cpu-handoff-disagg.json).

Work started November 4 at 22:45:50 Pacific. A workstation-to-cluster transport
outage began around 22:49 and prevented overnight observation; the detached
controller continued independently. The timed notes below preserve what was
known during the outage and are superseded by the verified morning closeout.

### 03:34–03:40 Pacific access and host-identity correction

The controller is on **`ubuntu@3.238.63.5`**, not on Gemini. Its exact launch
receipt is
`results/workshop-routing-overnight-controller-prep-20261105-a1/launch-attempt.json`;
the frozen launcher/BOOTSTRAP and staged payload manifest bind that SSH target
to the Docker ID and workspace recorded below. Gemini being reachable does not
make this controller or its evidence reachable. The independent access receipt
`results/overnight-access-relay-20261105-0335/state.json` records both direct SSH
timeout and Gemini-to-jump TCP timeout. No Gemini containers were inspected and
no credentials were copied.

No alternate location for the **new** campaign artifacts is known. Local files
under the frozen launch run are launch inputs, not collected outcomes; older
diagnosis archives belong to the previous failed campaign. Controller status,
accepted cells, live GPU ownership and cleanup therefore remain **unobserved**
after the last successful 22:48 check. Preserve its reservations. A local
03:40 probe was denied network access by the execution sandbox before contact;
that is not further evidence about the remote host or benchmark.

## Workflow

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

The user authorized overnight independent testing and the parent assigned a
fresh C16/C32 subset of the previously selected C16/32/64/128 range. The
canonical AgentX scenario is represented by a file-backed frozen specification;
the generic benchmark MCP spec does not express its trace/pacing/primer
semantics. No attempted specification is modified.

## Previous failure and preserved evidence

The preceding controller exited at 18:49 Pacific. Its one-worker RR C16 cell
completed with 307 successful requests, zero request errors/overflows and a
valid scenario submission. C32 failed during its mandatory primer, before a
usable matched profile. The restart guard correctly stopped the campaign.

The saved worker still processed long prefills while reporting one running
request, 145–189 waiting requests and approximately 1–3% KV occupancy. At
02:47:08 UTC, ordinary `generate` canaries began exceeding their 180-second
deadline. The worker's `/live` returned 503; it received a shutdown signal at
02:47:28, then exited 139 while shutting down active streams. The saved Pod
reports one restart. No preceding CUDA/OOM traceback was found. This supports
load-induced health failure as the leading explanation; retained Kubernetes
event evidence is insufficient to independently prove the sender of SIGTERM.
The later shutdown segfault is not established as the initiating failure.

Full original run/controller evidence was copied without changing the source:

- Local archive: `results/overnight-routing-sweep-diagnosis-20261104/previous-evidence.tar.gz`
- SHA256: `cdbd30a44044587becea33f47dffc1207444aa8a46eb426a30a8b9f4e35f9759`
- 417 files including the controller; per-file hashes in `preserved-manifest.json`.

## Fresh experiment decisions

- Same immutable Super VL revision, TP2 H100 workers, runtime image, full pinned
  393-trace corpus, AIPerf source/patch, native context, engine cap 128,
  canonical snapshot primer and 900-second admission / 300-second drain.
- Prioritize a matched C16 comparison across one-worker RR, two-worker RR and
  two-worker KV before risking C32. Fresh worker processes for each cell make
  the cache history explicit. This is a different campaign, not continuation
  of the failed one.
- Keep zero-restart acceptance. Do not disable liveness or lengthen canaries
  merely to obtain a clean curve. Preserve failures as failures.
- The coordinator assigned only GPU0+2 on cp-0198 and cp-0942, with fresh scoped
  lease `.local/overnight-routing-sweep.gpu-lease`. Other tests run concurrently
  on disjoint GPUs but share node CPU, EFS and network. These are exploratory
  observations, not isolated peak-capacity claims.
- Report exported and admission-window rates separately; live AgentX trees are
  not simultaneous HTTP requests. Record actual queue, running requests,
  prefix/cache counters, GPU telemetry and client pressure.

## Open questions and upstream candidates

- Should a queued inference canary make an otherwise progressing engine fail
  liveness under overload? Investigate separating engine liveness from inference
  availability and bounding canary work. Do not claim a general bug from this
  single configuration alone.
- Investigate the shutdown-time Rust/Python abort after graceful discovery
  withdrawal with many active streams; it may be a separate cleanup defect.
- Does C32 become a stable stress observation on two workers even when one
  worker cannot complete its primer? It cannot support a clean latency speedup
  against a failed one-worker arm.
- A C16/C32 subset does not identify a capacity knee if both remain lightly
  utilized. Higher loads remain a later fresh specification.

Live upstream review found existing work to evaluate before proposing duplicate
fixes. [Issue #15273](https://github.com/ai-dynamo/dynamo/issues/15273) remains
open; [#12151](https://github.com/ai-dynamo/dynamo/pull/12151) is an open draft
separating shallow `/live` from readiness, and
[#15419](https://github.com/ai-dynamo/dynamo/pull/15419) is an open busy-aware
canary prototype. [#15738](https://github.com/ai-dynamo/dynamo/pull/15738) merged
October 9 as `bee50eae0a991f71580bf2642fed73a755c23ea5`: engine response progress
resets the timer even when publish fails. Its duplicate
[#15798](https://github.com/ai-dynamo/dynamo/pull/15798) closed without merging.
The progress fix does not by itself establish safe handling of a long prefill
that has produced no response yet.

The inspected current `health_check.rs` (Git blob
`1c88e6fa06be324923fbd9eb6297807d32fe3fd5`) still spawns each timed canary
asynchronously and returns without an explicit per-endpoint in-flight bound.
This provides a plausible source mechanism for queue amplification, not a
measured attribution of every queued request in our run. Candidate acceptance:
busy but progressing engines avoid liveness restarts, canary work stays bounded,
and genuinely stalled engines are still detected. Exact fetched metadata/source
are retained beside the private diagnosis archive. No upstream changes were
submitted, and no such patch was added to the frozen experiment.

## Controller and handoff commands

Controller: `kubecon-workshop-routing-overnight-20261105-a1`, Docker ID
`bba75c201f20e3350c77831b8ba3a14e248f80daf42a71be45aea2610f093e89`.
The launcher verified 47 staged files; frozen plan SHA256 is
`78b74d4e044d990bddf6451219133d0f0ebf320bfa4f2f7b6b5c18dadff4e67b`.
The remote workspace is
`/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace`.

Use fresh labels, never overwrite a prior observation or collection:

```bash
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-sweep/controller.py \
  probe --label UNIQUE
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-sweep/collect.py \
  --label UNIQUE
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-sweep/analyze.py \
  --run results/workshop-routing-overnight-collection-UNIQUE/verified/results/workshop-routing-overnight-20261105-a1 \
  --output results/workshop-routing-overnight-collection-UNIQUE/analysis.json
```

Collection snapshots completed immutable cells and verifies all transported
bytes. When the controller is terminal it also retains failed-cell/startup and
controller logs. It does not overwrite the local frozen launch run. Analysis
requires exact integrity checks, clean submission, zero errors/overflow/record
cancellations, worker/discovery qualification and positive KV overlap before
making a routing ratio. It reports the admission-denominator caveat explicitly.
The analyzer was validated against the retained original C16 cell (307 requests,
14 queue/cache pressure series); that validation is not a new measurement.
It also verified that an uncollected current campaign yields **zero eligible
cells and zero comparison ratios**. Three collection tests passed: valid
partial evidence cannot create a completed cell, tampered bytes cannot create a
verification receipt, and archive traversal is rejected.

An initial collection at 22:51 and subsequent status probe timed out at SSH
connect, before any remote program ran. Their empty archive/stderr and failed
observation directories are retained. These are transport failures, not failed
performance cells. Use fresh labels once external access recovers.

The detached controller performs scoped GPU cleanup between cells and deletes
its CPU client only on full completion. If it fails, inspect its cleanup receipt
and Pod identities before releasing the remaining CPU client or **local** launcher
reservation. The remote reservation lives in a separate filesystem; absence of
one does not prove absence of the other. Keep local launch ownership until
terminal remote cleanup has been independently checked.
