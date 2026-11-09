# Live demo qualification and booth transcripts

The user authorized running all four presenter demos on the real cluster,
fixing failures, and saving shareable main-panel text for a later demo booth.
Subagents may help with capture tooling and read-only access checks. GPU runs
remain sequential and use the existing exclusive lease.

| Demo | Live run | Main-panel transcript | Cleanup |
| --- | --- | --- | --- |
| 01 Single replica | Passed fresh retake: corrected progress display, model discovery and correct coding response; worker Ready at 460.7s | `demos/transcripts/live/01-single-replica/20261104-a2/main.txt` | Verified zero Pods/claims; own lease released |
| 02 ModelExpress peer weights | Passed: both-rank EFA transfers and correct target inference; 459.4s storage / 250.0s peer Ready (one pair) | `demos/transcripts/live/02-modelexpress/20261104-a1/main.txt` | Verified zero Pods/claims; own lease released |
| 02 ModelExpress, revised flow (intro server as source) | Passed November 7 UTC, accepted as qualified: both-rank EFA transfers, no fallback, correct target inference; 492.98s storage / 247.01s peer Ready (one pair) | Not captured; run evidence and `reports/receipts/2026-11-07-modelexpress-intro-source.json` | Target cleaned November 8, 08:16 UTC, before the recording run; intro server retained |
| 02 ModelExpress, revised flow, recorded | Passed November 8 UTC against the same intro server: both-rank EFA transfers, no fallback, correct target inference; 492.98s storage / 247.6s peer Ready (one pair) | `demos/transcripts/live/02-modelexpress/20261108-a1/main.txt`; `reports/receipts/2026-11-08-modelexpress-recording.json` | Not cleaned: intro/MX pair left running for the presentation |
| 03 Disaggregated serving | Passed: both pools Ready, correct coding output, distinct worker IDs and positive clean KV-transfer deltas | `demos/transcripts/live/03-disaggregated/20261104-a1/main.txt` | Verified zero Pods/claims; own lease released |
| 04 Snapshot | Passed: distinct restored Pod, exact GPU pair, fresh READY; 37.3s agent / 41s Pod Ready from prepared NVMe | `demos/transcripts/live/04-snapshot/20261104-a1/main.txt` | Verified zero claims; EFS view restored, helper removed, agent spec unchanged; own lease released |

The capture must contain actual terminal output from a fresh live attempt.
Retain failed attempts separately, include commands and responses, strip screen
control escapes for plain text, and record model/runtime/manifests plus output
hashes. Offline rehearsals and historical results do not count as live captures.
Preparation and onstage execution have separate receipts when prime is needed.

Initial observation: no local GPU lease directory; API tunnel connection refused
at 127.0.0.1:16443. Independently verify prior remote controller termination and
GPU cleanup before acquiring the lease; absence of its directory is insufficient.

Access was restored. Fresh independent audit at 07:35 UTC November 4 confirmed
terminal remote controllers, absent remote lease/lock, zero active GPU Pods,
ResourceClaims and DGDs, and all three nodes Ready. Evidence:
`results/workshop-demo-live-access-20261103-a1/remote-proof.json`.

The first three demos now use the outline's agreed `--language-model-only`
setting with fresh profile IDs. Snapshot preserves its captured engine settings.

Live fixes so far:

- Model-loading progress recognizes the pinned vLLM prefetch marker.
- Timestamp parsing accepts Kubernetes RFC3339Nano logs on Python 3.9 by
  truncating sub-microsecond precision. MX preparation was interrupted/resumed
  without restarting the GPU worker or resetting its original apply clock.
- Snapshot claim templates now select the verified original GPU UUIDs, rather
  than relying on allocator ordering to choose gpu-1/gpu-3. The expression
  passed a server dry-run; no contingency resource was persisted. Evidence:
  `results/snapshot-demo-preflight-20261104/exact-pair-claim-template.json`.

Demo 1's first recording predates the progress-parser fix: its loading timer
remains unknown until completion, while the final logged loading duration and
Ready timestamp are valid. The preferred retake `20261104-a2` passed with the
corrected display. The first recording remains retained as actual evidence.

## Final verification

All four preferred captures report `live_passed`, contain actual commands and
responses, and have no terminal-control escapes. All source/evidence snapshot
hashes and transcript hashes verified after cleanup; no credential redactions
were needed. The [recordings index](../../demos/transcripts/live/README.md)
selects the four booth artifacts. Private integrity receipt:
`results/workshop-demo-live-20261104-a1/recording-integrity.json`.

38 demo/capture tests, Python/shell syntax, and `git diff --check` passed.

Independent final read-only audit at **2026-11-04 08:47:36 UTC** verified all
three nodes Ready, no active GPU Pods, no ResourceClaims or DGDs, and no local
GPU lease. Snapshot's agent UID/specification are unchanged, its artifact view
is back on `nfs4`, its temporary helper is absent, and the retained Snapshot is
still Ready with its original UID. Proof:
`results/workshop-demo-live-20261104-a1/final-cleanup-proof.json`.

Timings have different scopes: intro/MX include deployment through readiness,
P/D is a two-worker compiled profile, and Snapshot's 41s is Pod creation through
Ready, excluding preceding deletion and offstage preparation. They are not a
controlled cross-feature speedup chart. The Snapshot main-panel recording is
native vLLM same-node recovery. A later DGD qualification is recorded separately.

## Later Snapshot DGD qualification

November 4 run `workshop-snapshot-dgd-20261104-a3` passed operator-managed capture,
restored-worker coding chat, automatic Pod replacement, and coding chat through
the unchanged Dynamo frontend. The checkpoint/node/exact GPUs stayed unchanged;
Pod UID and response worker ID changed. An experimental workload-local runtime
adapter and pinned offline metadata cache preparation were required.

[Actual qualification CLI output](../../demos/transcripts/live/04-snapshot-dgd/20261104-a3/qualification.txt)
is packaged with a separate provenance manifest. It does not replace the demo 4
presenter recording. On EFS, replacement took **352s Pod-to-Ready** and **374.72s
deletion intent to first observed successful response**. No DGD NVMe time or
matched speedup was measured in that trial. Presenter wiring remains; the later
NVMe qualification is recorded below.

Cleanup finished at 21:38:34 UTC. Independent 21:40 UTC audit passed: zero active
GPU Pods/claims/DGDs, all nodes Ready, both reservations absent, agent UID/spec
unchanged, native and DGD snapshots retained Ready, and no new kernel Xids.
47 scoped integration/adapter tests passed. See
[the full report](../workshop-snapshot-dgd.md).

## Upstream-controller Snapshot follow-up

Run `workshop-snapshot-dgd-upstream-20261104-a1` passed capture, initial restored
coding inference, automatic worker replacement and replacement coding inference
through the same frontend. It backports merged PR #15887 into the same image,
retains upstream's native controller/hooks, and keeps only the custom
destination identity/offline bridge. EFS replacement: **342s Pod-to-Ready /
360.98s deletion intent to observed success**. These single-run clocks establish
no matched speedup or NVMe DGD result.

[Actual qualification CLI output](../../demos/transcripts/live/04-snapshot-dgd-upstream/20261104-a1/qualification.txt)
and its manifest retain an incorrect observer check and its correction: CRIU's
expected source exit 137 was initially mistaken for a failure. Observation
resumed without repeating deployment, initialization or capture. This is not a
presenter main-panel retake. The earlier v3 and native recordings remain intact.

Cleanup/reservation release finished at 23:24:48 UTC; independent 23:25:27 audit
passed with zero active GPU workloads/claims/DGDs, all nodes Ready, absent
reservations, unchanged Snapshot agent, retained snapshots Ready and no new
Xids. 55 focused checks passed. See the
[full follow-up report](../workshop-snapshot-upstream-controller.md).

## Upstream-controller Snapshot on NVMe

Run `workshop-snapshot-dgd-upstream-nvme-20261104-a1` passed both initial and
automatic-replacement frontend coding inference from a fully verified 94.2 GB
local artifact. Agent restores were **34.05 / 36.86 s**; Pod-to-Ready was
**48 / 59 s**; deletion intent to observed replacement response was **99.11 s**.
Both Pods were created after staging, and disk counters show 187.8 GB of local
reads through the restores. Capture, publication, copying and hashing are
offstage; prior EFS timings use a different artifact and are not a matched
speedup measurement.

[Actual qualification output](../../demos/transcripts/live/04-snapshot-dgd-upstream-nvme/20261104-a1/qualification.txt)
and its manifest retain the corrected predeployment `df` probe and frozen
evidence. This is separate from the presenter recording. Cleanup released both
Snapshot reservations and restored the private EFS view. The 00:39 UTC audit
passed with no owned GPU workloads/claims/DGDs, no active GPU Pod on cp-0124,
unchanged agent, retained artifacts and no new Xids; concurrent routing resources
on the other nodes were preserved. Presenter wiring remains. See the
[NVMe report](../workshop-snapshot-dgd-nvme.md).

## Request-continuity presenter demo

November 4 run `workshop-continuity-live-20261104-a2` passed the full disabled/
enabled EngineCore-fault walkthrough. The
[actual main-panel recording](../../demos/transcripts/live/05-request-continuity/20261104-a2/main.txt)
is marked `live_passed`. Both cases made one generation POST with no client
retry. Disabled emitted an error and no successful finish; enabled preserved
31 output tokens, continued on its pre-qualified peer, and finished with
`stop` and DONE without a stream error. Frontend and survivor Pod/container
identities and readiness stayed unchanged.

The pinned runtime's SSE worker attribution is first-write-wins. The retake
uses a response-correlated frontend retry/selection trace to prove the peer;
the initial a1 recording remains failed under its stricter SSE-change check.
Maximum adjacent client content gap was 0.511s over the enabled response,
separate from an exact handoff gap, which remains unavailable. This is a
functional demonstration, without load/SLO qualification.

34 scoped offline tests and actual tmux/key gates passed. Offstage preparation
requires eight H100s; concurrent EFS weight loading took roughly seventeen
minutes before initialization/readiness. Cleanup completed at 22:45:09 UTC,
with zero owned Pods/claims/DGDs independently verified. The lease was released
to the waiting Snapshot workstream; its subsequent ownership was preserved.
See the [report](../workshop-request-continuity-demo.md) and
[receipt](../receipts/2026-11-04-request-continuity.json).
