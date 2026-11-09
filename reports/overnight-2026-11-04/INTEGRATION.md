# Shared presenter and recording integration

Owner: parent chat. November 4–5 overnight work, Pacific time.

## Implemented

- Added an opt-in `WORKSHOP_ALLOCATION` contract for demos 01/02. Validated
  assignment JSON selects a scoped local lease, pins each actual worker to its
  assigned node and physical GPU UUID pair, and freezes `allocation.json` in
  each fresh run. A resumed run must supply the same assignment. The coordinator
  still verifies live ownership and disjoint slots; a local lease is not a
  cluster-wide scheduler reservation.
- Both MX comparison arms use the same target pair, separate from the source
  pair. The actual target claim is written with the target UUID selector.
  Source and target remain on different nodes for the EFA transfer demonstration.
- Tmux children receive the frozen allocation explicitly. Default unassigned
  execution retains the original global-lease behavior.
- Extended the main-panel recorder to Snapshot DGD, routing, KVCR and Shadow.
  Freeze relevant manifests, profiles, overlay sources and mechanism evidence
  before later cleanup can change them. Successful response output alone does
  not qualify transfer, restore or promotion.
- Routing replay uses `recorded_evidence_passed` / `recorded-main.txt`, distinct
  from `live_passed` / `main.txt`. Rehearsals always remain simulated captures.
  Recorded values are independently checked against their frozen AIPerf exports.

## Validation so far

- 26 focused allocation/intro/MX checks passed after correcting a test fixture
  whose two arms accidentally shared the same mutable Python list. No live
  behavior was inferred from that fixture correction.
- Full recorder rehearsal check found a new Snapshot rehearsal missing its
  simulated readiness timestamp. The real wait loop sets the actual timestamp;
  the agent will fix the rehearsal-only branch after its source-frozen live run.
  The readiness requirement in the recorder remains enforced.
- Shadow rehearsal header now states `NO CLUSTER CALLS`; its source before
  that label-only change remains frozen with its already-running live attempt.
- The normal-mode routing recording passed, with no live cluster operations.

## Follow-up gates

- Finish recorder regression after the Snapshot rehearsal timestamp fix.
- Review actual live captures against mechanism-specific evidence and independent
  allocation audits; preserve unsuccessful capture attempts.
- Reconcile all agent reports into REVIEW.md and STATUS.json; update the demo
  index with exact runnable commands and remaining qualification gates.
- Run the full appropriate local suite once sources settle. Do not alter
  source-hashed presenter modules while their live attempts rely on them.
- Do not automatically commit, push or submit upstream changes overnight.

## Independent review follow-ups

The cluster coordinator reviewed the shared code without modifying active runs:

- **Intro claim immutability:** the DGD hash is checked, but the intro's GPU claim
  YAML has no independent hash. Require its original bytes before apply and
  verify actual assigned UUIDs/node, beyond the count-only check. Current live
  placement is independently audited correct. Apply this guard after the
  source-frozen migration attempt, then test fresh and resume behavior.
- **MX evidence bytes:** include the full source/native/peer manifests, claims,
  source Service and `arms/` evidence in the immutable capture. Implemented in
  the recorder before the new live MX capture.
- **Allocation schema:** require `intro` for this explicitly intro/MX contract;
  the current valid assignments already include it. Nondefault MX node names
  remain constrained by its original verification contract and should either
  be parameterized consistently or rejected explicitly.

## Latest validation and disposition

- The canonical Snapshot rehearsal now records simulated readiness, and a
  resumed replacement preserves absolute step numbering. A pending-intent PTY
  recording passed the completion guard.
- Intro now freezes and checks the claim hash before preparation/deployment,
  and assigned runs join actual claims to ResourceSlice UUIDs/node before
  accepting readiness. MX saves each arm's observed placement and uses the
  frozen assignment's node names consistently.
- Snapshot capture startup provenance recognizes the offstage initial identity.
- Exact old sources for interrupted Snapshot, intro and migration attempts are
  retained in read-only observer trees with only `.local` and `results` links.
  No credentials were copied, prior hashes rewritten or graphs redeployed.
- **296 local tests passed** with loopback sockets enabled. Log:
  `results/overnight-local-suite-a3.log`. Earlier failures remain retained.
- Metrics demo 09 additionally passed a real three-pane tmux rehearsal: six
  silent gates, correct resource/metric observers, main exit zero and scoped
  session cleanup. Receipt: `results/demo-09-root-tmux-20261105-a1/tmux-validation.json`.
- These are local/observer checks. Fresh live qualification and terminal GPU
  cleanup still require connectivity recovery and coordinator re-audit.

## Bounded read recovery follow-up

The first scheduled continuation confirmed that direct SSH still times out and
the prior tunnel control socket is absent. Existing runs, leases and prior
failure receipts were preserved; no live readiness or cleanup was inferred.

The canonical intro/MX observer's actual phase-reset problem is now fixed:
10-second read caps, a 60-second consecutive transport budget within the original
deadline, stale/disconnected labels and UID/apply/arm-bound log snapshots. Fatal
API/container/identity errors still fail closed. Only reads retry; deployments,
faults and generation requests do not. Side panes remain read-only. The recorder
now freezes `startup-observations/` bytes as well as their hashes in metadata.

Twelve focused tests cover recovery, exhaustion, Pending workers, identity and
context changes, unchanged physical-GPU acceptance gates and cache integrity.
The **full 308-test suite passes** with local loopback sockets enabled:
`results/overnight-local-suite-a4.log`. The offline classifier also recognizes
both retained transport-failure receipts from the interrupted intro attempt.
This establishes local observer behavior, not fresh cluster qualification.

Exact source transition and commands are in [BASELINE-MX.md](BASELINE-MX.md).

## Final November 5 integration check

The current full suite passes **350/350 tests**:
`results/overnight-local-suite-final-20261105-a2.log` (20.918 s).
The first final pass had one stale test-path error after C16 became the default
routing profile. The narrow test correction exercises both C16 and the historical
recording, preserving recorded-versus-live labels, immutable evidence and tamper
rejection. It changed no runtime code. That failed log remains preserved.
`git diff --check` also passed. Live qualifications and incomplete deliverables
are enumerated in [MORNING-REVIEW.md](MORNING-REVIEW.md).

## Resumed November 5 suite

All **477 local tests pass** in23.730s:
`results/workshop-resumed-local-suite-20261105-a1.log`. This includes the new
take-home selector/user/version fixes, prompt and capture gates, restricted
reader descriptor tests and durable Snapshot transport/controller guards.
`git diff --check` passes. No new live result is inferred from this suite.
The active remote profiles and external transport interruption are tracked in
[RESUMED.md](RESUMED.md) and STATUS.json.

## Earlier combined checkpoint, November 5 afternoon

All **530 local tests pass** in35.010s: `results/workshop-resumed-local-suite-20261105-a4.log`. This includes compact Snapshot validation output, KVCR prepared captures/cleanup and the new Shadow log retention and full-composition identity fences. The earlier a2 suite was denied five local HTTP socket binds by the sandbox; its failure log remains unchanged. The permitted-loopback a3 and a4 suites pass. Live qualification is recorded separately in REVIEW.md.

## Current combined checks

All **557 local tests pass** in31.980s: `results/workshop-resumed-local-suite-20261105-a5.log`. The reviewed v3 metadata inventory, nonce/ACK barrier, safe formatting, frozen actual-image CPU action and deployment gates are included. Its actual pinned-image CPU preflight also passed with real Torch CPU/meta tensors and no CUDA initialization; the GPU parameter inventory remains a separate diagnostic. See REVIEW.md for live status.
