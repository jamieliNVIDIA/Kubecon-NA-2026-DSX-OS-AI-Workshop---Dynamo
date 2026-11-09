# Potential upstream fixes and improvements

Initial ledger assembled November 4, 2026 Pacific from the repository's pinned
source reviews and actual qualification reports. Status below is the status of
that evidence, not a fresh claim about current upstream HEAD. No issue, PR,
external message or upstream change was submitted by this workstream. Reconcile
with the other overnight workstreams' reports before filing anything.

## Runtime behavior

| Candidate | Evidence and scope | Proposed follow-up / acceptance | Ownership or upstream overlap |
| --- | --- | --- | --- |
| Snapshot restore-proxy destination identity/context handoff | New PID-1 proxy bypasses Dynamo's standby-path context writer in the tested combination. The qualified bridge writes allowlisted destination context and reuses ordinary refresh/registration. | Common contract between Snapshot proxy and Dynamo restore path, covering replacement Pod and supported same-Pod restore lifecycles. Capture, initial frontend inference and automatic replacement must pass without custom bridge. Avoid upstreaming the demo's hardcoded proxy path or changed-Pod-UID restriction. | **Already assigned:** Neal will initiate a separate workstream. [Existing scope](../2026-11-04-snapshot-upstream-status.md#open-upstream-workstream); Snapshot #537 and Dynamo #10376/#17246 are related existing work. |
| Restore destination Hugging Face offline policy | Capture forces offline mode; lifecycle removes it after restore. The tested bridge preserves destination `0` / `1` / unset before registration. This is independent of whether a local cache happens to resolve successfully. | Include destination policy in the agreed restore contract; test every policy value and do not retain capture-only state by accident. Same no-overlay lifecycle acceptance as above. | Same user-owned Snapshot workstream; no matching fix found in the November 4 bounded source search. [Evidence](../2026-11-04-snapshot-upstream-status.md). |
| Carry model revision through worker registration and frontend metadata resolution | Engine uses an explicit revision, while current registration can perform unversioned lookup. Fresh pinned cache download may lack `refs/main`; Snapshot preparation found a different cached selection. The new take-home job pins only its dedicated cache and verifies the actual offline resolver. | Register and resolve the intended revision end to end. Add fresh-cache tests with multiple snapshots, missing/mismatched refs and offline mode. Requalify before removing the cache workaround. | Existing proposed [Dynamo #11369](https://github.com/ai-dynamo/dynamo/pull/11369); don't open a duplicate without checking its present state. [Runtime findings](../workshop-snapshot-dgd.md), [take-home decision](TAKEHOME.md). |
| GMS compatibility with vLLM `request_memory(..., external_weight_memory)` | The selected vLLM calls a third argument; bundled GMS wrapper accepted two and failed before loading. A test-local signature/budget overlay allowed a separate Qwen control to pass recovery; it did not qualify Super VL. | Match the supported vLLM/GMS API, account for shared/external weights once, and add budget-exhaustion/zero/shared-weight cases to compatibility tests. Verify current upstream before proposing a new patch. | [Exact overlay and hashes](../../configs/patches/shadow-gms-vllm031/README.md); [live control](../2026-10-14-shadow-engine-retest.md). Overnight Shadow work may supersede this status. |
| GMS reconstruction of processed/quantized model parameter metadata | Super VL reader reports `language_model.lm_head.input_scale` shape `(1,)` versus committed `()` with float32. Earlier Lightning packed-weight mismatch is a different model/result. Writer also reports illegal CUDA access after remap/warm-up; shared root cause is unproven. | Preserve/reconstruct post-processing shape, dtype, layout and scalar semantics. Require both TP ranks to match metadata and produce correct active/standby inference before injecting failure. Investigate invalid access independently until proved related; no blanket reshape workaround. | [Super VL evidence](../2026-10-15-super-vl-tp2-retest.md#shadow-startup-retry), [R610 repeat](../2026-10-22-r610-feature-retest.md), and [fresh proposed-work findings](SHADOW.md). Dynamo #12168 is open draft; #9854 is closed unmerged, detailed below. No successful Super VL promotion inferred. |
| Migration attempt attribution and recovery-gap telemetry | Qualified one-client-stream continuation selected a peer, proved by correlated frontend trace, while SSE worker identity stayed first-write-wins. Maximum adjacent content gap cannot locate the exact last-old/first-new boundary. | Preserve request identity but expose per-backend-attempt worker, start/end, retry reason and retained-token counts through a documented trace/metrics contract. Add a live-peer-retry regression. Decide compatibility before changing public response metadata. | [Live result](../workshop-request-continuity-demo.md) and [source analysis](../2026-11-04-request-migration-technical-notes.md). This is primarily an observability improvement, not evidence that continuation failed. |

## Existing fixes, version selection and integration tests

Fresh Shadow research froze PR metadata in
`results/overnight-shadow-super-vl-20261104-a1/upstream-pr-12168.json` and
`upstream-pr-9854.json`; their status/head fields were independently read for
this ledger:

- [Dynamo #12168](https://github.com/ai-dynamo/dynamo/pull/12168), **open draft**,
  head `2b2d1d9eae467b21de5b5a624fcf8542d0ea626f`: adopts committed quantization
  scale shapes and rebuilds NVFP4 read-mode MoE kernels. Its reported validation
  uses Kimi/vLLM 0.25.1/TP8. The workshop Super VL image selects Humming; this
  proposed code is not proof of compatibility or a qualified drop-in fix.
- [Dynamo #9854](https://github.com/ai-dynamo/dynamo/pull/9854), **closed,
  unmerged draft**, head `a4bf9d538b76d43ebd22cf7b6be48c2da4a8fc56`: structural
  mutable-auxiliary-tensor handling, aliases and final/meta parameter manifests.
  Older #12168 text calls it merged; the frozen PR merge metadata contradicts
  that description. Treat its code as proposed work, not an available merge.
- [Dynamo #11201](https://github.com/ai-dynamo/dynamo/pull/11201) already addresses
  private rebinding of non-parameter tensors; avoid proposing that general fix
  again. Determine what remains for postprocessed/meta parameter reconstruction.

The routing workstream also checked health-related upstream overlap, frozen in
`results/overnight-routing-sweep-diagnosis-20261104/upstream-health-review.json`:

- [Issue #15273](https://github.com/ai-dynamo/dynamo/issues/15273) is open and
  reports large-model canary/liveness crash loops. Its original 3-second case
  differs from the workshop's configured 180-second timeout.
- [PR #12151](https://github.com/ai-dynamo/dynamo/pull/12151) is an open draft
  separating shallow liveness from readiness, head
  `f483e09e9fc36a680f6607491dbc532a03bf87d8` (separate metadata snapshot
  `upstream-shallow-live-12151.json` in the same evidence directory);
  [#15419](https://github.com/ai-dynamo/dynamo/pull/15419) is an open draft for
  busy-aware canaries based on engine progress. Treat both as proposed work.
- [PR #15738](https://github.com/ai-dynamo/dynamo/pull/15738) merged October 9 as
  `bee50eae0a991f71580bf2642fed73a755c23ea5`, resetting the health timer on engine
  progress rather than successful publication. Duplicate #15798 is closed,
  unmerged. The merged change alone does not establish protection during a long
  prefill before the first token.
- Inspected health source blob `1c88e6fa06be324923fbd9eb6297807d32fe3fd5`
  still spawns asynchronous canaries without an in-flight bound. Queue
  amplification is a hypothesis to reproduce, not a measured cause of the old
  worker restart. Acceptance should cover continued engine progress under
  overload, a bounded canary count and detection of a truly stalled engine.

| Item | What the evidence establishes | Next useful action |
| --- | --- | --- |
| Hybrid/recurrent KV-event handling | The old state agent rejected `NonMainAttentionKind` and quarantined residency; merged [Dynamo #15535](https://github.com/ai-dynamo/dynamo/pull/15535) addresses that branch. Official nightly wheel overlay passed ordinary peer reuse and controlled Guard retrieval/handback. | Treat this as image/release selection, not a new unimplemented bug. Confirm the fix and companion adapter classification are in the public runtime chosen for the workshop. [Qualification](../workshop-kvcr-guard-qualification.md). |
| KVCR/vLLM/NIXL supported-version bundle | The partial vLLM Python overlay lacked `OffloadingConnectorStats.metric_sections()`; matching the pinned stats module fixed the CPU/API gate. Selected KVCR requires NIXL 1.5.0; inspected public nightly carries 1.4.1. | Provide a coherent tested image or supported dependency matrix, including adapter telemetry. Test actual stats collection, not just imports. A package overlay is experimental evidence, not a qualified stock nightly. |
| Guard host-memory transport libraries | The CPU Guard could not load LIBFABRIC because `libcuda.so.1` was missing even with DRAM-only registration. Existing `nvidia-legacy` handler plus `NVIDIA_VISIBLE_DEVICES=none` supplied driver libraries without numbered GPU devices; no handler/driver was installed. | Document the native backend/library dependency and a portable way to expose libraries while preserving no-GPU access. Determine whether this is packaging/documentation or a backend dependency that can be reduced. The tested handler name is environment-specific. |
| Discovery lag after engine failure | Guard a4's first unpinned request hit A and returned 503 before discovery removed it; migration was disabled. A later request explicitly pinned to B proved preserved-cache retrieval. | Add composition qualification with migration enabled and actual load. Measure detection, backend retry, Guard readiness and cache transfer independently. This observed window does not by itself establish a retry bug or automatic failover support. |
| Operator-added probes and process readiness | The operator supplied liveness/readiness probes absent from the rendered template. After EngineCore failure the main container restarted once while Guard survived. A supervisor's successful startup probe does not prove the current child engine is ready. | Align examples with effective Pod probes; test child-process death, restart/hold and stable endpoint identity. Observe actual Pod spec rather than assuming rendered defaults. Check current upstream contracts before proposing changes. |
| Multi-rank NIXL telemetry | A single-process exporter failed the two-rank demo; shared per-Pod `prometheus_mp` telemetry allowed qualification. | Keep correct multi-process example/configuration and failure-path diagnostics in upstream recipes. This is already fixed in the workshop harness, not a new NIXL transport failure. [Evidence](../2026-10-15-super-vl-tp2-retest.md). |
| Inference-canary liveness under overload | The failed prior AgentX C32 primer kept processing long prefills with many waiting requests; `generate` canaries exceeded 180 seconds and `/live` returned 503. A shutdown signal followed. Available events do not independently prove who sent it. | Investigate whether queueing should mark a progressing engine non-live, and whether bounded liveness probes should be separate from inference availability. Keep this a configuration-specific finding until reproduced; do not merely disable liveness to produce a clean curve. [Diagnosis](LOAD-SWEEP.md). |
| Shutdown abort with active streams | The same old worker exited 139 while shutting down many streams after discovery withdrawal. No preceding CUDA/OOM traceback was found in the saved evidence. | Investigate cleanup independently of the earlier canary timeout. The shutdown crash is not established as the initiating overload failure. Preserve exact shutdown/discovery logs and a bounded reproducer. [Diagnosis](LOAD-SWEEP.md). |

## Keep local unless a broader use case emerges

- The artifact-specific NVMe copy, hash verification and private agent mount
  overlay are workshop storage plumbing. They are separate from the generally
  useful Snapshot identity/offline fixes.
- Demo keypress controls, compact projection excerpts and recording layout
  belong in this workshop unless upstream maintainers want reusable examples.
- A source-local KVCR `source_op` differs from the destination wire handle.
  Matching the correct logged `op` fixed our receipt verifier; that was a test
  matcher correction, not demonstrated data-plane corruption.
- Engine endpoints can remain stable after container/EngineCore restart.
  Requiring a changed endpoint was a harness assumption. Incarnation checks
  should use the actual process start tick/container identity.
- Controlled pinning isolates a mechanism. It should not be upstreamed as a
  substitute for production routing/retry policy or advertised as automatic
  failover.

## Before filing a new upstream issue or patch

For each candidate, retain the exact repository/runtime revisions, reproducer,
expected/observed behavior and focused failure evidence. Search current merged
and proposed upstream work, then state whether the problem is still present.
Keep unrelated failures and environment-specific assumptions separate. No
production-readiness claim follows from one successful workshop test.

## Additional November 5 closing findings

- **Snapshot lifetime and orchestration:** both new artifacts reached Ready,
  but held source Jobs later hit their 3,600-second deadline. The optional
  SnapshotJob lifetime patch was rejected at server dry-run because its spec
  is immutable, with no actual write. Prefer supported creation-time lifetime
  configuration and durable offstage orchestration; distinguish artifact Ready
  from helper completion and restored serving. This is separate from the user's
  identity/offline upstream workstream. See [SNAPSHOT.md](SNAPSHOT.md).
- **GMS mutable Humming helper state:** actual startup produced read-only write
  faults. Installed-source inspection confirms mutable 1,024-int32 lock tensors
  in both the linear Humming helper and `HummingExpertsBase`. The MoE ownership
  path is outside the current module tensor walk and the writer prototype's
  coverage. Their role in each fault and the complete fix remain unqualified.
  Inventory mutable helpers and test writer-only before reader/promotion; do
  not loosen general shape checks. See [SHADOW-WRITER-CANDIDATE.md](SHADOW-WRITER-CANDIDATE.md).
- **KVCR fixture sizing is local:** a 3,247-token source cannot commit a full
  4,224-token effective hybrid page. Receiver execution correctly stopped. Add
  tokenizer/effective-page-aware fixture preflight; this is not evidence of an
  upstream KVCR data-plane defect. See [KVCR.md](KVCR.md).
- **Routing readiness is a harness gate:** the fresh C32 smoke raced exact model
  publication by about 128 ms before profiling. Wait for the expected frontend
  model ID; preserve the workload settings and failed attempt. Worker Ready and
  model servability need distinct documentation, not an assumed startup speedup.

No item above was submitted upstream. Recheck current proposed/merged work
before filing; the pinned source evidence does not establish current HEAD.

## Resumed run: verified fixes and new findings

- **GMS writer fix now verified:** the a5 private-workspace candidate served
  three correct coding responses and recorded240rebindings (80linear+40MoE per
  TP rank), unchanged committed model weights and no new Xids. Scientific
  evidence was independently frozen before scoped cleanup. This qualifies the
  writer-specific fix, not standby readers, promotion or SLOs. An upstream API
  for mutable non-parameter workspace ownership would be preferable to the
  workshop's exact helper-class hooks. See SHADOW-DESCRIPTOR-WRITER.md and
  SHADOW-READER-CANDIDATE.md for the separate descriptor reconstruction work.
- **Reader Python runtime state:** the instrumented v4 writer subsequently
  passed actual serving and both complete reader-ready manifests, independent
  audit and root closeout. The first full reader imported committed weights,
  then exposed an experimental callback gap: generic ModelOpt configuration
  reads checkpoint attributes already consumed by Humming. The reader-only v5
  callback follows the pinned Humming oracle's final-schema builder. Independent
  source review, 11 focused tests and the pinned-image CPU test for all 80 actual
  roles passed. All 29 other function bodies and the v4 data schema are unchanged.
  This is our adapter gap, not an established upstream GMS defect. GPU parked
  reader, promotion and replenishment are still unqualified. Keep descriptor
  reconstruction and broader final-model runtime support as integration work;
  do not upstream this callback as a standalone fix for an upstream failure
  without reproducing the equivalent native path. [Review](SHADOW-READER-V5-REVIEW.md),
  [actual CPU proof](../../results/workshop-shadow-reader-v5-cpu-live-20261105-a1/result.json).
- **Model-card compatibility includes ancillary assets:** KVCR's admitted
  worker rejection is confirmed by the exact runtime's DEBUG semantic message.
  Its two otherwise-equivalent cards differ in six documentation/image assets;
  exact source hashes sorted extra files into model identity. A concurrent
  take-home cache fetch falls between the registrations, strongly supporting
  the observed cache-metadata race. Confirm current native digests and asset
  inventory after access returns. Stage a settled complete cache and require
  matching admitted worker identities before traffic; do not disable checksums
  or hand-edit registry identity. Upstream topics include deterministic model
  asset contracts and clearer rejected-cohort diagnostics, rather than an
  assumed defect in KVCR transfer. See KVCR.md and its preserved analysis.
- **Take-home fixes are local:** distinguish strict X.Y.Z operator compatibility
  from exact installed dev-package version; expose the cache's run-as UID; fail
  fast on terminal failed preparation Jobs; select frontend Pods using stable
  workload/role labels rather than the operator-owned managed-by label. The
  actual unmodified public runtime served one coding request through the
  corrected Service, and canonical cleanup passed. No Grove runtime bug is
  inferred from its expected ownership-label rewrite.

The latest completed full local regression passed 602 tests; newer v5 and
transport changes have focused checks and require final combined validation.
None of these candidates was submitted upstream; review current upstream work
before filing or porting.

## C32 routing closeout: direct liveness evidence

The fresh exact-model startup gate passed, and both two-worker C32 cells are
independently accepted. The later one-worker canonical primer failed through a
**directly recorded liveness restart**: Kubernetes event for exact Pod UID
`4ce1e139-563d-4bf1-8d05-caa95e19f36b` at 20:51:20 UTC states
`Container main failed liveness probe, will be restarted`. Nearby worker logs
show progressing prefills, an expanding queue and 180-second inference-canary
timeouts. The Pod records one restart, `reason=Error`, `exitCode=1`; no OOM
inference is warranted. This improves on the earlier old campaign's missing
event attribution. It does not prove every queued request was a canary.

Review the existing liveness/readiness and busy-aware-canary work linked above
before proposing a duplicate fix. Acceptance should retain stalled-engine
detection while avoiding restarts of progressing engines solely because an
inference probe queued behind real work. Do not silently relax liveness in the
benchmark to obtain a clean baseline.

A secondary **AIPerf warmup-abort cleanup candidate** is preserved: after
`warmup_failure`, the JSONL writer tried to flush an unopened profiling file and
logged `file handle is not open`. It followed the runtime restart and did not
initiate it. Reproduce warmup cancellation with no profiling writer opened,
test clean finalization, and check current upstream before proposing a patch.

[Accepted pair, exact failure timeline and hashes](routing-c32/C32-RESULTS.md).
No new upstream submission or runtime patch was made during this closeout.
