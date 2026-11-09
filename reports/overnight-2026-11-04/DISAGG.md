# Disaggregation: overnight investigation

Started November 4, 2026, Pacific. Owner: `/root/disagg_comparison`.

## Current status: November 5, 12:50 Pacific

The **original matched pair is independently accepted and scoped cleanup
passed**. The detached P/D runner exited 0 at 12:26:55; root recovered its
original artifacts without replay and preserved the failed local observer's
receipt. All 52 frozen inputs, both original archives/integrity manifests,
per-request accounting, original worker/GPU identity and startup proofs passed
the offline independent audit. Aggregate has 313 successful requests; P/D has
312; both have zero request errors, cancellations and context skips. Their
source mix shares 312 identical turns, with one extra main-agent turn in aggregate.

[Full result and interpretation](disagg/RESULTS.md) and
[actual console package](../../demos/transcripts/live/03-disaggregated-agentx/20261105-a2/README.md)
are ready for review. Total output throughput is almost unchanged:
**174.75 aggregate / 174.36 P/D tokens/s** across the same four H100s. P/D has
lower observed tail latency but slower medians and mean generation per user.
This low-load, fixed-order N=1 point establishes neither capacity nor universal
P/D speedup. Both official throughput windows are approximately 1,200 seconds;
do not substitute the shorter 900.57 / 901.17-second request-record spans.

P/D recorded **37,752,668,160 bytes / 624 TP-rank transfers**, with zero failed
transfer, failed notification or notification-after-expiry deltas. The separate
prefill KV-expiry delta is **2,406**. Captured same-image sources and one-Hz
expiry logs strongly support unused prefill health-canary leases: the health
payload sets `_HEALTH_CHECK`, while the prefill handler unconditionally enables
the remote-decode handoff path. Exact per-canary tracing remains an open item.
The clean local Dynamo checkout/fetched `origin/main` already contains the
matching fix, [#15594](https://github.com/ai-dynamo/dynamo/pull/15594), commit
`5b4ad1db8946117cb50a12af4901c96c12580d66`. Treat this as a pinned-image gap;
live release/backport status was not refreshed and no runtime changed.

Root's 12:50:32 scoped cleanup receipt confirms owned GPU graph/workers/claims
and lease removed, while the handed-off CPU/PVC/namespace/cache and old archives
remain retained. The independent acceptance is
`results/workshop-disagg-agentx-20261105-a2/independent-pair-acceptance.json`.
The actual console package includes source hashes and explicitly notes that
benchmark JSONL retains stream metrics/metadata rather than literal SSE bodies
or generated answer text. Twenty-two focused tests pass; no frozen execution
input changed.

## Historical 12:15 checkpoint: observer failure and recovery plan

The **aggregate arm is independently accepted**. The P/D arm passed actual
startup and canonical warmup, but the local observer/controller lost API
connectivity at **12:14:57 Pacific**: renewed TLS handshake timeouts followed
by refusal on the laptop's `localhost:16443` tunnel. This is **not an observed
inference failure**. The original AIPerf runner was detached inside the retained
CPU Pod; its original profile may still finish independently. Cleanup failed
on API reads before deleting serving resources. No matched comparison is
accepted yet, and the original controller's blocked receipt stays unchanged.

P/D became Ready at **12:02:03** on the same four physical H100s, with original
prefill/decode UIDs, zero restarts and the pinned model/runtime/common engine
controls. Both TP2 ranks in both workers instantiated NIXL LIBFABRIC. Four
smoke responses identify distinct prefill and decode workers. These establish
startup/handoff routing; final positive transfer-byte counters and zero
transfer/notification errors still need qualification. Independent startup
evidence: `independent-pd-startup/proof.json` within the a2 run.

P/D canonical warmup completed **16/16, zero errors, 198.11 seconds**. Measured
profiling began **12:05:58 Pacific**; admission should close at 12:20:58 and the
bounded drain at approximately 12:25:58, followed by export. The original
controller deadline remains **13:05:29 Pacific**. Do not replay the profile or
delete its workers while its original runner can finish inside that bound.

Root is the sole live executor. Once connectivity returns, recover only the
original runner and its artifacts:

```bash
.local/venv/bin/python scripts/recover_workshop_disagg_profile.py inspect \
  --run results/workshop-disagg-agentx-20261105-a2 --attempt r1

# Only after the original remote exit.json is terminal; use a fresh label.
.local/venv/bin/python scripts/recover_workshop_disagg_profile.py collect \
  --run results/workshop-disagg-agentx-20261105-a2 --attempt r2
```

The helper verifies frozen inputs, the exact CPU UID/image, original profile
hash and process/exit receipts, original serving UIDs and lease ownership. It
preserves before-recovery files and observer-failure receipts, performs the
unchanged acceptance checks and records recovery separately. It never launches
inference or cleans up resources. After collection, root must separately run
the scoped handoff cleanup and audit owned GPUs/claims/DGD absent while retaining
the borrowed CPU/PVC/namespace/cache. If either profile is incomplete, errored
or identity-mismatched, preserve its evidence without a comparison claim.

## Resumed execution: November 5, 11:05 Pacific

The user resumed unfinished work. All **52 frozen inputs still match**, and
neither arm had previously been attempted. Root ran a fresh read-only prelaunch
gate at 11:05:10 Pacific: exact handed-off CPU UID/Ready/image, empty GPU
namespace, thirteen cache/data/model/helper file hashes, all 3,517 pinned source
members, idle client and both fresh a2 remote paths absent. It passed in 6.47
seconds without inference or reconstruction. Evidence:
`results/workshop-disagg-a2-prelaunch-recheck-20261105-1105/`.

Root launched controller attempt **a2** at **11:05:30 Pacific**, process 32792,
with an explicit **13:05:29 Pacific** deadline. The pinned execution wrapper and
all AgentX/model/engine/admission/drain controls remain unchanged. The first
aggregate workers were starting at launch; no result had been accepted. Root
is the sole live executor; the P/D agent only reads local output and qualifies
collected evidence independently. New read-only prelaunch helper:
`scripts/recheck_workshop_disagg_client.py`.

Controller receipts/logs are `controller-a2-start.json`, `controller-a2-status.json`
and `controller-a2-console.log` within `results/workshop-disagg-agentx-20261105-a2`.
Do not relaunch it or rerun `prepare`; the existing controller owns execution.
GPU cleanup retains the explicitly borrowed CPU/PVC/namespace/cache and all old
archives. An unfinished, interrupted or errored arm remains ineligible.

The aggregate arm passed actual startup/allocation checks by **11:18:41**:
four exact assigned H100s on cp0198/cp0942 GPU indices 1/3, two fresh TP2 worker
UIDs, pinned runtime/arguments, text-only mode, native 1,048,576-token context,
128 sequence cap and zero restarts. Four smoke requests exercised both workers.
An independent review froze copies of logs, Kubernetes metadata, specifications,
smoke results and direct `nvidia-smi` command receipts under
`independent-aggregate-startup/proof.json` in the a2 run.

The logs show approximately **516 seconds in the model-loading marker** and
**164 seconds in engine initialization**, including approximately 27 seconds of
compilation. The loading marker includes loading/postprocessing work and does
not isolate disk or EFS time. Each TP2 worker reports 13,691,066 logical cache
tokens. The 27.78-GiB available-cache-memory line comes from TP0 and should not
be presented as the total TP2-worker memory pool.

Canonical warmup completed **16/16, zero errors, 112.29 seconds**. The unchanged
900-second measured profiling phase began **11:21:11 Pacific**. These are
startup/qualification facts.

The aggregate export completed at **11:42:06** and passed independent checks
of both integrity manifests, the full export, all per-request records, runtime
qualification and metrics endpoints. It contains **313 successful requests,
zero errors and zero cancellations**, 33,679,180 input tokens and 209,701 output
tokens. TTFT p50/p99 is **255.48 / 5,056.73 ms**; ITL p50/p99 is
**6.484 / 20.344 ms**; mean generation speed is **143.70 tokens/s/user**.
Observed backend cache-read percentage is **91.09%**, distinct from structural
prefix reuse. `independent-aggregate-acceptance.json` retains full precision,
trace mix, counts and server series.

**Denominator caveat:** the exported total throughput is **174.75 tokens/s**
across four GPUs and uses a **1,200.0009-second** phase window. The configured
admission is 900 seconds with 300 seconds of bounded drain; the exported request
record-span duration is **900.5694 seconds**. Preserve these separate clocks;
do not silently substitute the admission or record span for the official
throughput denominator. The server-metrics completion relay warned about its
30-second timeout, but all three endpoints produced data and the complete export
passed; this warning did not make the profile incomplete.

This C16 point is **not capacity saturation**: mean running requests per worker
were approximately 0.80 / 0.55, observed maxima 6 / 4, peak GPU cache occupancy
approximately 6.5%, and preemptions zero. Rootless lanes, tool/replay pacing,
realized turn mix and true-idle compression matter when interpreting live trees.

Aggregate GPU cleanup passed and the controller began the P/D arm at
**11:43:09 Pacific** on the same four GPUs. Its startup passed as recorded
above; measured-profile recovery and performance qualification remain pending.
No P/D speedup or matched comparison is claimed.

## Earlier disposition: prepared only

The fresh a2 CPU/cache/admission preparation passed at 16:09:57 UTC on
November 5. Neither GPU arm nor its controller was launched. The final live
audit at 18:20:06 UTC shows zero claims, GPU Pods and DGDs cluster-wide; no
P/D GPU reservation was acquired. There is no new performance comparison.
The explicitly borrowed routing CPU/PVC/namespace/cache and old archives remain
retained under the handoff contract. Commands below record the earlier plan;
execution requires a new bounded window and a fresh live ownership/idle check.

## Prepared follow-up: fresh a2 campaign

At 08:03 Pacific a **new immutable campaign** was frozen in
`results/workshop-disagg-agentx-20261105-a2`, SHA256
`0c11f986a428c46baddc2d123dc2f4bf00720251ba1064565250ecc5e770d0e7`.
The original a1 remains a transport-interrupted/expired CPU attempt with no
GPU measurements. Its retained container/snapshot metadata was recovered, but
no original cache contents were adopted or relabeled.

Root approved using the retained, independently qualified routing CPU client
through an **explicit exclusive handoff**. The source workstream acknowledged
this exact Pod and retired its controller; no routing job or CPU cleanup is
scheduled. The receipt is
`reports/receipts/2026-11-05-routing-cpu-handoff-disagg.json` (SHA256
`52ed35012f01418ac9a5369e3b526f962548bfefe256fcecf53ab526edf451a2`).
Source: `dynamo-ft-routing-overnight-20261105-a1/rr-loadgen`, UID
`4385c581-2c2c-446a-8f7d-123617386cf8`, cp0942.

Root's read-only probe passed in **6.39 seconds**: thirteen model/tokenizer,
raw dataset, helper, source-archive and CPU-cache file checks, all **3,517**
extracted pinned source members, exact Pod/image/node, and zero active benchmark
processes. The full 393-trace corpus and cache match the original planned
model/runtime/dataset/AIPerf controls. The source's original CPU preparation was
498.58 seconds; this handoff reuses that qualified work rather than reconstructing
the corpus. Probe evidence:
`results/workshop-disagg-client-handoff-probe-20261105-a1/`.

Implementation: `scripts/workshop_disagg_handoff.py`. The fresh GPU workers run
in the now-GPU-empty **owned source namespace**, which keeps the proven client
transport/collection path unchanged. Claim-template names have new `disagg-a2-`
prefixes; new remote arms are `disagg-a2-aggregate-c16-a1` and
`disagg-a2-disaggregated-c16-a1`. Each topology uses the same four previously
assigned physical GPUs; `offline-four-gpu-proof.json` checks both manifests.
Actual allocation remains a mandatory live gate. GPU cleanup explicitly
**retains** the borrowed CPU, PVC, namespace, cache/source and old archives.

Fifteen focused tests pass, including explicit identity/idle/retired-controller
handoff gates, immutable execution-wrapper hashes and preservation of the
borrowed CPU during cleanup. Root is the sole live executor. Next commands:

```bash
.local/venv/bin/python scripts/workshop_disagg_handoff.py prepare \
  --run results/workshop-disagg-agentx-20261105-a2
```

This does admission checks, an owned EFA ConfigMap and a **cache-only** check of
the actual fresh C16 profile; it sends no inference and creates no GPU workers.
Then Root may launch `scripts/overnight_disagg_controller.py` for this run with
`--attempt a2 --entrypoint scripts/workshop_disagg_handoff.py` and an explicit
fresh timezone-aware `--deadline`. A roughly two-hour execution window is a
bounded attempt; unfinished/errored profiles remain ineligible. No runtime,
load, corpus, replay, 900-second admission or 300-second drain settings changed.

## Current checkpoint: November 5 morning

The user restored VPN access at 07:31 Pacific and resumed the original task;
the earlier overnight cutoff is obsolete. The 07:33 recovered inventory proves
the original CPU Pod **expired at 06:41:19 Pacific** (`DeadlineExceeded`, eight
hours after startup), with the original UID
`f1dff367-76b9-47de-b3ac-39fd5e8a3c99` and zero container restarts. No P/D
ResourceClaims or DGDs exist. This changes the recovery plan: the ordinary
`kubectl exec`-based CPU recovery command below cannot work on this terminated
container. The helper now rejects that condition explicitly; twelve focused tests
pass, including this expiry guard.

First inspect the exact retained container metadata through the existing
toolkit Pod's **read-only host-root** view. No new Pods, mounts, containerd
snapshots or host changes are performed:

```bash
.local/venv/bin/python scripts/inspect_workshop_disagg_cpu.py \
  --run results/workshop-disagg-agentx-20261105-a1 \
  --inventory results/overnight-20261105-recovered-0733/pods.json --attempt a1
```

The source container ID is
`fb4acbaa58617c0a4fea88911779f3cd2792d3ff6a71fcbfa30b91e32885bf3d` on cp0942.
Its retained snapshot may still contain the completed original receipt and cache;
only after exact ownership is established should read-only extraction be
considered. If that source has been garbage-collected, report the CPU attempt
as unrecoverable and create an explicitly fresh preparation/campaign. Do not
silently adopt another client's cache or treat syntax tests as qualification.

The old controller's 07:15 deadline has passed. The controller now accepts an
explicit timezone-aware `--deadline` and rejects a past deadline before creating
an attempt. A new execution attempt needs a fresh documented deadline and
sufficient bounds for both unchanged arms. Its original 8,100-second per-arm cap
is retained; a shorter global execution window can stop an unfinished arm, which
remains blocked/ineligible. Before launching another arm, it requires at least
the unchanged 900-second admission plus 300-second drain budget; startup and
snapshot primers also consume the remaining wall time. The
locked model/runtime, four physical GPUs, AgentX corpus/C16, admission/drain and
engine controls remain fixed. Root is executing live commands because the
subagent's network-escalation hook is unavailable.

## Benchmark tasks

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

Parameters are file-backed because the generic benchmark MCP cannot express
canonical AgentX tree replay, snapshot primers and pacing. The user's instruction
to develop and test these demos overnight authorizes the bounded configuration
chosen before locking. This does not authorize changing a failed arm's parameters
in place. Tasks 1–6 are complete for the fresh a2 pair after original-profile
recovery and independent acceptance. The original blocked local-controller
receipt remains unchanged; the recovery and cleanup dispositions are separate.

Recovery has seven focused passing tests, including refusal to collect an
active profile or a replacement serving Pod, preservation of original failure
receipts, and inspection that cannot launch, export or clean up a profile. The
frozen execution wrapper/controller and their dependencies remain unchanged.

## Decisions

- Keep the already qualified presenter demo 03 as the direct NIXL handoff proof.
  Add an independent measurement harness rather than extending the twelve-minute
  live flow with two fifteen-minute profiles and engine starts.
- Compare two aggregated TP2 workers with KV-aware routing against one TP2
  prefill worker plus one TP2 decode worker. Both configurations use **four H100s**
  on the **same exact node/GPU pairs**, sequentially in that fixed order.
- Use the full pinned AgentX corpus and existing canonical replay contract:
  C16 live session trees, seed 20261030, 900-second admission, 300-second bounded
  drain, mandatory snapshot primers, native model context, and recorded output
  lengths/pacing. C16 is not a claim of sixteen simultaneous HTTP requests.
- Common engine controls: Super VL text-only, same model/revision and image
  digest, TP2, 128 sequences per worker, 8,192 batched tokens, memory fraction
  0.85, existing cache/kernel/Mamba settings. No settings are silently retuned.
  Prefill/decode roles and NIXL connector configuration necessarily differ.
  P/D explicitly sets `VLLM_SSM_CONV_STATE_LAYOUT=DS`; aggregate leaves that
  variable unset, and its effective default has not been independently checked.
  Describe these as qualified paths with required connector/layout differences,
  rather than a literal single-variable topology toggle.
- This is an exploratory **N=1**, fixed-order comparison. Realized turn mix,
  initial cache history, bounded drain, concurrent CPU/EFS/PCIe/network activity,
  and possible cross-role scheduler differences limit interpretation. Neutral or
  negative outcomes remain reportable; no speedup is promised.

## Work and evidence

- Harness: `scripts/workshop_disagg_benchmark.py`.
- Dedicated namespace: `dynamo-ft-overnight-disagg-20261105-a1`.
- Run: `results/workshop-disagg-agentx-20261105-a1`.
- Immutable spec: `campaign.json`, `campaign.sha256`, `inputs-sha256.json`,
  exact manifests and profiles. Each profile gets a separate sealed `spec.json`.
- Scoped reservation: `.local/overnight-disagg.gpu-lease`; no global idle check
  or global cleanup. Coordinator assigned cp0198 GPU indices 1/3 and cp0942 1/3;
  UUID selectors in the spec are authoritative.
- CPU-only preparation was launched. The first API attempt was sandbox-denied
  before resource creation; its receipts are preserved. The same unchanged
  preparation then ran with authorized cluster network access.
- Nine new guard tests pass: equal total GPU budget/UUID selectors, common
  native-context/model/batching controls, distinct role placement and real
  LIBFABRIC NIXL config, rejection of unmatched topology/non-TP2 allocation,
  denominator accounting, invalid/error profile refusal and CPU receipt recovery.
- Python syntax passed with an explicit workspace bytecode cache. The first
  compile used a host cache outside writable roots and was denied; no code
  syntax error occurred.

## Completed validation

1. Exact corpus/cache and C16 profile CPU qualification.
2. Matched startup, physical GPU UUIDs, runtime digest, zero restarts, health and smoke.
3. Both original AIPerf profiles, raw archives, engine metrics and GPU telemetry.
4. Independent request/token accounting, source-turn mix and admission/drain clocks.
5. Positive P/D transfer bytes, zero transfer/notification failures and scoped cleanup.

The new canary-expiry investigation, missing literal SSE bodies, unchanged
connector/layout differences and N=1/low-load limits are retained in the result.

## Transport interruption and recovery

At 22:49–22:50 Pacific the CPU observer lost the cluster API path: API-list
timeouts, TLS handshake timeouts and a lost HTTP/2 connection. The independent
cluster coordinator also found that new SSH connections to the jump host timed
out, indicating an external path interruption rather than an observed model or
CPU failure. The last received CPU sample was approximately 22 GiB with no OOM
events. The reconstruction itself was detached inside the existing client Pod.

The first bounded controller (PID 10485) exited at 22:51:30 Pacific with **zero
GPU arms attempted**. Its scoped cleanup also failed on the unavailable API;
it did not delete the CPU Pod. `controller-exit.json` retains both errors, and
`controller-source-a1.py` preserves the exact controller source/hash. No GPU
lease was acquired. Neither a benchmark result nor cleanup success is claimed.

Do not recreate the client or rerun corpus preparation to recover this observer
failure. After the coordinator verifies connectivity, recover the original Pod,
receipt and exact cache with fresh verification receipts:

```bash
.local/venv/bin/python scripts/recover_workshop_disagg_cpu.py \
  --run results/workshop-disagg-agentx-20261105-a1 --attempt a1
```

That helper verifies the unchanged Pod UID/node/image, frozen source archive,
original C1 receipt/profile/helper/seed, no OOM, and exact cache-file hashes for
C4 and the actual C16 profile. It does not rerun reconstruction or inference.
It then records the qualification gate that was lost with the observer.

Once this passes, launch a **new controller receipt attempt** against the same
unchanged, unattempted benchmark arms:

```bash
.local/venv/bin/python scripts/overnight_disagg_controller.py \
  --run results/workshop-disagg-agentx-20261105-a1 --attempt recoverya1
```

Run it detached with stdout retained, as for the first controller. The deadline
remains 07:15 Pacific; it refuses to start an arm without enough bounded time.
The CPU Pod's original eight-hour deadline also remains unchanged. After both
arms pass, `scripts/analyze_workshop_disagg.py --run results/workshop-disagg-agentx-20261105-a1`
checks immutable evidence, matching profiles and per-request accounting before
writing a fresh `comparison.json`. Current state: **transport-blocked before
GPU qualification; recoverable CPU work retained**.

## Open questions

- Does C16 produce enough concurrent work on this workload to make resource
  specialization observable? Do not reinterpret a low-load result as capacity.
- If the balanced one-prefill/one-decode split loses to two general workers,
  is pool ratio, transfer cost, prefill sizing or the trace mix the explanation?
  A new ratio or load would require a new frozen campaign, not an in-place edit.
- How much of the measured result belongs in a twelve-minute section? A compact
  recorded comparison alongside the existing live handoff remains the default.
- Production sizing needs a broader pool-ratio/load sweep and repeated trials;
  this overnight comparison does not supply those qualifications.

## Upstream candidates

No new inference-engine defect is established by this work yet. Several
usability improvements or investigation leads have concrete saved evidence:

- **Startup/readiness logging:** the pinned Dynamo 1.6 runtime repeatedly logs
  `tower_http::trace::on_failure` ERROR/503 during normal model loading and CUDA
  graph capture. The workers subsequently became Ready without restarts and
  completed all sixteen canonical warmup requests without errors. Include route
  and initialization context, or distinguish expected readiness failures from
  generation failures, so operators/presenters can interpret these logs. Evidence:
  `results/workshop-disagg-agentx-20261105-a2/independent-aggregate-startup/`.
- **AgentX timing terminology:** AIPerf `e2c149ee...` prints a 75,877.7-second
  first-request spread at the start of this 900-second profile. Source
  `timing/strategies/agentic_replay.py` reports the uncapped trajectory schedule;
  its ten-second global cap compresses true system-idle time. Label virtual
  schedule versus wall-clock timing and the active idle cap together. This is
  a logging/documentation proposal, not evidence that requests actually wait
  twenty-one wall-clock hours. Preserve actual running/waiting request counts,
  rootless lanes and the idle-cap summary in performance interpretation.
- **Metrics-finalization relay:** aggregate's console warns that
  `profile_complete` to `server_metrics_manager` timed out at thirty seconds,
  although all three metrics endpoints exported successfully and the profile
  passed. Improve acknowledgement/finalization visibility or distinguish a
  delayed relay from lost metrics. This does not establish missing data.
- **Drain/denominator visibility:** aggregate kept its full 300-second bounded
  drain and reported `grace_period_timeout=True` with 313 completed requests,
  zero cancelled requests and zero in-flight requests. Its request record span
  is 900.57 seconds, while official throughput uses 1,200.00 seconds. Inspect
  outstanding tree/phase-credit accounting and explain these clocks before
  calling this a bug. Keep the exported denominator unchanged. Both leads have
  exact console messages in the aggregate raw `console.log` at 19:36–19:41 UTC.
- **Prefill probe KV leases — existing upstream fix:** P/D's nonzero expiry
  counter and one-Hz warnings strongly match health canaries taking the ordinary
  remote-decode path in the pinned image. Same-image sources confirm that missing
  branch. Local fetched upstream history already contains [#15594](https://github.com/ai-dynamo/dynamo/pull/15594),
  commit `5b4ad1db8946117cb50a12af4901c96c12580d66`, with a local-only probe path
  and regression tests. Track future image/release selection and confirm any
  release-branch inclusion before qualification; do not file a duplicate fix.
  No runtime was changed in the frozen comparison. Full source and ancestry
  evidence: `canary-expiry-source-review.json` in the a2 run.

The repeated API/tunnel observer interruptions and the expired CPU Pod are
workshop harness/lifecycle issues, not Dynamo inference bugs. Future long runs
should keep their controller durable on the jump host or inside the cluster.
Observer failure must be a separate state from benchmark failure: local
exception cleanup could otherwise delete a still-running detached profile if
connectivity returns midway through cleanup. The recovery helper deliberately
does no cleanup. A supported AIPerf CPU-only prepare/check-cache API with
source/profile/cache receipts would remove our dependency on private
DatasetManager APIs; this remains an improvement proposal.
