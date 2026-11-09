# Snapshot presenter: overnight review notes

The integrated DGD/NVMe presenter now has a passed actual
[main-panel recording](../../demos/transcripts/live/04-snapshot-dgd/demo-04-dgd-live-20261105-a3/main.txt).
Fresh a3 completed priming, worker replacement, both frontend coding streams
and scoped cleanup at 20:32:30 UTC on November 5. Independent offline audit of
the collected archive passed at 20:57 UTC. Replacement measured 33.895 s in the
agent, 59 s Pod-to-Ready and 64.288 s deletion-to-observed-Ready, with the fresh
coding request separately sent after the timing summary. Root's independent
owned-resource/agent/storage audit passed at 21:04:19 UTC, and the separate
local mirrored reservation was released at 21:04:45 UTC. Retained snapshots and
artifact copies remain; unrelated workstreams are outside that cleanup scope.

Earlier a1/a2 attempts are retained below. Both captured Ready artifacts but
lost the external observer before source-helper release, then exceeded the
stock source lifetime. The optional a2 deadline extension was rejected at server
dry-run with no writes. A3 used a detached jump-host controller and the unchanged
stock deadline, completing even while the external VPN was unavailable.

## DGD workflow

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
   - Complete: pinned Super VL revision/runtime, vLLM TP2, compiled text-only 8k,
     Kubernetes, same cp-0124 node and exact qualified physical GPU UUID pair.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
   - Complete: existing `snapshot-super-vl-tp2-r610/nemotron-snapshot.yaml`
     through the already-qualified `workshop_snapshot_dgd.render_objects`.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
   - Complete: existing qualified template/candidate remain under `configs/dgd`;
     new presenter freezes complete executable `deployment.yaml` per run.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
   - Offline safety/flow tests pass; fresh live preparation performs CPU cache
     verification plus client and server admission before deployment.
5. Hand off to `deploy_dynamo` or `kubectl apply`
   - Complete: fresh a3 prime, actual main-panel capture, two coding responses
     and scoped cleanup passed. Independent root closeout also passed below.

## Decisions made

- Add a dedicated integrated presenter (`scripts/workshop_snapshot_dgd_demo.py`,
  `demos/04-snapshot/run-dgd.sh`) rather than changing native demo 4's established
  semantics or relabeling its recordings. The parent owns shared capture-map
  integration; the new recording key is `04-snapshot-dgd`.
- Keep native `run.sh` as a qualified fallback until presenter review. The
  integrated candidate has now passed live qualification, through its separate
  entry point and guide.
- Prime creates a fresh automatic checkpoint. Its creating DGD remains alive
  through the onstage worker replacement; retained artifacts from deleted DGDs
  cannot be adopted as a newly primed service.
- Reuse the qualified lifecycle and NVMe modules, exact runtime module hash,
  identity/offline bridge, node and GPU selectors. Do not change engine settings
  to imitate the eager introduction demo or claim a matched startup speedup.
- Separate readiness from the final request. The existing qualification
  `replace()`/`verify()` APIs send coding requests before returning; directly
  calling them would violate the agreed timing-before-request presentation.
  The presenter reuses their ownership/identity/staging validators but waits
  only through readiness, prints timing, then gates the actual curl request.
- Show one focused DGD excerpt. Full executable DGD and runtime overlay remain
  available. Commands displayed relative to the run directory retain exact
  absolute execution arguments in durable receipts.
- Use UID-conditional worker deletion with a durable single-fault intent;
  never overwrite/adopt a reused Pod name or repeat an uncertain fault.
- Keep deletion-to-observed-Ready separate from the later human-gated coding
  request. Otherwise a presenter's explanation/key delays would contaminate a
  purported service-recovery measurement.

## Implemented and checked

- Offline preview and complete plain-terminal rehearsal pass. Restored identities
  are explicitly simulated and durations remain unmeasured in rehearsal.
- Fifteen focused tests pass: projected checkpoint schema, frozen profile/storage
  and runtime overlay, no onstage capture, request-free readiness waiting,
  command submission gates, single-fault resumption, stream/output/worker proof,
  and workload → storage → lease cleanup ordering/failure preservation. They
  include an actual PTY capture of pending-replacement resumption with absolute
  stage numbering and a negative completion check for missing readiness. Existing
  foreign/incomplete result directories are rejected before state mutation.
- Shell syntax and `git diff --check` pass.
- All 113 Snapshot regression tests pass after the final local fixes.
- Actual three-pane tmux rehearsal passed with nine silent key gates, ten
  captured screens and main-pane exit 0. Clearing between steps and timing
  before curl were verified; the simulated coding response and distinct worker
  proof passed. Evidence:
  `results/demo-04-dgd-overnight-tmux-a3/ui-validation.json`, `screens.json` and
  `main-pane-history.txt`. Only those rehearsal sessions were removed.
- Shared capture integration caught a rehearsal-only missing
  `ready_observed_at`; the real waiter already recorded it. Canonical rehearsal
  now records a clearly simulated readiness observation. Independent review
  also found resumed replacement stages were numbered 1..3 instead of 2..4;
  the canonical presenter now preserves absolute stage numbers. Fresh normal
  and pending-intent PTY captures pass; normal evidence is in
  `results/demo-04-dgd-overnight-rehearsal-fixed-capture-a1/`.
- Preserve the interrupted live run's exact source despite those local fixes:
  `frozen-observer/` contains 314 read-only source files and the snapshot-aware
  recorder. All eight original source pins and every frozen per-run input were
  reverified. Only `.local` and `results` are symlinked to the actual workspace;
  credentials were not copied. Its offline preview passed against the same
  original run/spec. `frozen-observer-manifest.json` and
  `post-freeze-presenter-fixes.json` explicitly record the source boundary;
  original live hashes and deployed runtime were not changed.
- A separate immutable `frozen-observer-v2/` retains the same original runtime
  source pins and updates only the recorder. It correctly recognizes
  `initial_identity` as preexisting startup, so the eventual recording will label
  offstage priming accurately. The original tree/manifest remain untouched;
  `frozen-observer-v2-manifest.json` records every source hash and both recorder
  revisions. Its preview/help checks pass. Use the v2 absolute commands in
  `CONTINUATION.md` after access recovers.

## Live work

- Assigned cp-0124 physical pair:
  `GPU-ce4aaec3-4fd1-f047-a303-80986bc29110`,
  `GPU-75461e0d-6588-94c9-2517-dca859f5c68b`.
- Fresh run: `results/demo-04-dgd-overnight-live-20261105-a1`.
- Namespace: `dynamo-ft-snapshot-demo-a0997d7843`.
- Creating DGD UID: `cd7f7877-d948-4cd8-b453-5767162c2a59`.
- CPU cache proof passed against 88 shards / 75,010,188,240 bytes, exact locked
  revision and offline metadata resolver; client/server admission passed.
- Snapshot reservation owner: `workshop-snapshot-dgd`, exact run path.
- Source snapshots retained in this run's `live-sources/`; all runtime/model/
  manifest inputs are frozen. No shared platform changes or global cleanup.
- Shadow may use a disjoint pair on the same node and scaling tests may share
  EFS/network services. Record concurrency; no matched speedup claim.
- The first prime observer stopped around 22:50 Pacific on repeated TLS
  handshake timeouts through the local API tunnel. The last source observation
  was progressing model-weight loading, not a SnapshotJob failure. DGD/source
  and lease remain preserved. The coordinator is checking tunnel health; resume
  verification in this same run without replaying deployment or capture.
  `prime-observer-attempt-01-exit.json` and `prime-main.txt` retain the failure.
- Independent new SSH to the jump host also timed out, confirming an external
  transport problem rather than a demonstrated engine failure. The coordinator
  handles bounded reconnection checks. Exact safe continuation commands are in
  the run's `CONTINUATION.md`: use the frozen observer/recorder with the absolute
  original run/output paths, then perform scoped cleanup and independent audit.
- The frozen observer intentionally retains its original pending-resume
  numbering limitation. No fault has been injected. If a transport interruption
  occurs during the eventual onstage replacement, preserve the partial recording
  and do not relabel its incomplete recorder result as a passing retake.
- November 5 recovery: the 07:33 Pacific root inventory shows the same creating
  DGD UID with `state: failed`, `Ready=False` and an explicit automatic
  SnapshotJob `DeadlineExceeded` / source Job `activeDeadlineSeconds` error.
  Worker replicas and Snapshot GPU claims are zero. The saved SnapshotJob spec
  used a 3,600-second deadline. No staging callback, artifact UID, NVMe overlay,
  initial serving identity or injected fault was recorded locally. The original
  agent UID remains Ready with zero agent/PageBroker restarts. Root/coordinator
  are retaining full live checkpoint/content/source-Job evidence before any
  cleanup; do not blindly resume prime or adopt an artifact from the failed job.
- The complete morning diagnostic distinguishes capture from Job completion:
  PodSnapshot `bfda4954-db72-42ea-a709-51f335278ba8` and content
  `58f3aee3-f978-4e2a-b028-1c8a666c2e5d` became Ready at 07:22:50 UTC, before
  the held source Job failed at 07:40:33 UTC. CRIU succeeded. The helper remained
  held while the observer was disconnected, so it could not run the staging
  callback and finish the source before the one-hour deadline. This is not a
  failed engine dump or proof that the Ready checkpoint was corrupt.
  Agent UID and spec SHA match the original pins; `/checkpoints` is still private
  `nfs4`. Full immutable raw diagnostics are retained under this run's
  `recovery-inspection-20261105-a1/`.
- Capture started at 07:02:22 UTC after roughly 21m50 of source initialization.
  Agent checkpoint duration was 20m28.109s: CRIU 65.471s, CUDA checkpoint 84.131s,
  publication/switch 17m56.697s. Artifact readiness came roughly 42m18 after source
  creation. Those offstage observations, plus hashing/staging, leave limited
  margin under the one-hour parent Job deadline when EFS is contended; they are
  not restoration latency or a matched startup result.
- A fresh offline candidate is prepared under
  `results/demo-04-dgd-live-20261105-a2/`, namespace
  `dynamo-ft-snapshot-demo-3a4e36b875`, with no submission or reservation. Its
  one-shot `run-live.py` is ready for the root's network-enabled execution only
  after old evidence preservation and scoped cleanup/audit. It runs prime,
  actual main-panel capture and scoped cleanup, and stops for diagnosis on any
  failure. It does not retry or silently replay a fault.
- The a2 controller now has an explicitly authorized, workload-local capture
  lifetime policy. `scripts/workshop_snapshot_capture_deadline.py` watches for
  the creating DGD, its exact component SnapshotJob, source batch Job and source
  Pod. It rejects terminal/deleting/reused identities, ownership conflicts,
  unknown deadline values and any shorter source Pod/template deadline. Only
  the two owned Jobs may change, from 3,600 to 7,200 seconds, after server dry
  runs and JSON tests on UID, resourceVersion and the old deadline. Already
  7,200-second resources are accepted without another write. Final GETs verify
  identity, deadlines and that no other spec fields changed.
- The policy writes `capture-deadline-policy.json`, full
  `capture-deadline-before.json` / `capture-deadline-after.json`, and exact
  `capture-deadline-receipts/*.json` command outcomes, hashes, resource versions
  and lifetime-only diffs. Partial/conflict/admission failures are explicit;
  they stop the local prime observer and preserve resources for review. There
  is no retry, automatic fault or cleanup after a policy failure.
- Fourteen focused lifetime-policy tests pass, including foreign/reused owners,
  terminal Jobs, shorter Pod limits, server mutation/admission rejection,
  resourceVersion conflicts, partial-write accounting and idempotent 7,200s.
  The outer controller enforces a 5,400-second prime wall-clock bound. The
  already-frozen presenter, DGD/runtime/model inputs and all a2 source hashes
  were reverified unchanged; only the separate controller/helper were added.
  Root review and server admission remain required before this policy is
  treated as live-validated. It changes owned workload lifetime, not the engine
  or shared platform.
- A pre-launch review tightened the watcher: object discovery may wait before
  any writes, but disappearance after a first Job patch must fail immediately,
  preserving the partial receipt and original before evidence. The original
  helper source copy remains retained; `capture-deadline-helper-revision.json`
  and a separate version-2 source copy record this change before controller
  launch. A regression test verifies that the first patch is never replayed.
- Final pre-launch Snapshot suite: all 127 tests pass (2.73 s). Current helper
  source bytes match the retained version-2 copy, and all existing a2 presenter
  source and executable-manifest pins remain unchanged.
- Live a2 result at 16:10:20 UTC: server dry-run rejected the SnapshotJob patch
  because its spec is immutable. No actual patch was submitted, policy changes
  are empty, and the controller stopped the local observer as designed. The
  new DGD/source continue to exist under the original stock 3,600-second limit;
  no fault, staging or model/engine change was made by that rejected extension.
  The original policy/controller/receipt evidence is retained without rewriting.
- Root authorized a separate explicit execution attempt to dispose the
  unsupported optional extension and continue the same stock-qualified active
  source, subject to fresh identity/nonterminal/default-deadline checks. The
  prepared `run-live-default-attempt-02.py` checks every failed policy command
  was read-only/server-dry-run, records the failed-policy hash and actual stock
  limits in an immutable disposition, and resumes prime without replaying DGD
  creation or capture. Its wall-clock bound is the remaining original source
  lifetime, followed by actual presenter capture and scoped cleanup only on
  success. Separate controller/disposition receipts preserve both attempts.
  Root is the sole network executor; no unsupported guard was silently skipped.
- Closing status at 10:07 Pacific: the prepared stock-default attempt was never
  launched. Neither `live-controller-attempt-02.json` nor the default-policy
  disposition exists. No initial/replacement serving identity, staged artifact
  UID, private NVMe overlay or injected fault was recorded for a2. Its stock
  one-hour source deadline subsequently elapsed, as confirmed by the root's
  fresh read-only collection below. Root ran `recovery-tools/inspect-final.py`
  before scoped cleanup. The collector froze exact namespace, source
  Job/Snapshot/content and agent evidence with original UID checks. No further
  priming or GPU experiments are authorized for this closing phase.
- A2 closing inspection at 18:16:08 UTC matched every original DGD/SnapshotJob/
  source Job identity. PodSnapshot `4ae52c8d-ee7e-4616-9a3b-39a5965ddd3f` and
  content `a7fdcfb6-48af-41aa-a69e-e9c361cd355d` became Ready at 16:44:56 UTC.
  The source Job then hit its unchanged deadline at 17:10:15 UTC and the DGD
  failed with zero allocated claims. Agent UID/spec still match the original
  pins; `/checkpoints` remains private `nfs4`. Thus capture/publication succeeded,
  but staging, restored serving, coding inference, replacement and the actual
  presenter recording remain unqualified for this new runner. Frozen evidence:
  `results/demo-04-dgd-live-20261105-a2/closing-inspection-20261105-a1/`.
- A2 offstage clocks: source Job start 16:10:15 UTC; checkpoint start
  16:26:33.470 UTC; artifact Ready 16:44:56 UTC. Agent checkpoint duration was
  18m22.645s, including CRIU 54.297s, CUDA checkpoint 75.976s and
  publication/switch 16m10.841s. Those are preparation clocks. They neither
  establish restoration latency nor form a matched comparison with a1.
- The old a1 run's scoped cleanup passed and independent root inventory under
  `results/overnight-20261105-post-cleanup-0803/` confirmed zero old Snapshot
  claims/DGDs with the original agent intact. The a2 closing audit is separate
  and must verify its own workloads/claims gone, released reservation, unchanged
  agent/private EFS view and preserved checkpoint objects/artifacts.
- A2 scoped cleanup exited 0. Durable checks record owned workloads/claims gone
  at 18:17:49.903 UTC and storage cleanup at 18:17:51.260 UTC. `demo.json`
  records `cleaned_at=2026-11-05T18:17:51.294668+00:00`; the Snapshot reservation
  is absent, and no overlay/helper remains in local state. The retained EFS
  checkpoint is preserved. This run never staged a new NVMe copy: the generic
  cleanup receipt's artifact-retention wording must not be read as new staging
  proof. No second controller, disposition, response or replacement proof was
  produced. The native fallback and its historical qualified recording are
  unchanged. Root's final independent audit is still required before declaring
  complete cluster closeout.
- The 07:33 recovery inventory supersedes the original overnight cutoff. Work
  continues interactively after the user restored VPN. Child network escalation
  calls hit a malformed permission-hook payload; the root is running the
  explicit read-only diagnostic harness under `recovery-tools/inspect.py`.

## Open questions for review

- Promote the integrated launcher to the default now that its fresh presenter
  run passes, or retain separate candidate/native entry points for the workshop?
- How much of the identity/artifact proof should be visible on screen versus
  saved for review? Current proof is precise but includes long UID/UUID values.
  The later projection preview reduces the YAML excerpt from 32 to 21 lines and
  replaces the full proof JSON with a short changed/same table. Review those
  screens at the intended projector/terminal size.
- Priming requires a new ~94 GB checkpoint plus offstage hashing/staging. How
  much margin beyond the observed 45-minute prime should we allow, and how long
  should the DGD stay alive? Check node-local free space before every new capture.
- Should the booth show the precise request-free readiness clock and separate
  final coding response, or an additional automated availability probe? That
  probe would need its own timing scope and must not be confused with user SLOs.
- Cross-node restore, retained KV and Snapshot + migration/GMS composition
  remain separate qualifications. No new promise is made by the UI integration.
- The integrated runner verifies the NVMe filesystem and artifact view but
  currently takes no block-device read-counter snapshots. Do not claim that its
  restore timings measure cold physical SSD reads rather than page-cache hits.
  The older storage-comparison harness's `diskstats()` is separate and is not
  called by this presenter.

## Resumed a3: durable offstage controller

The user resumed the unfinished demonstrations after the preceding closeout.
Root completed CPU-only preparation for
`results/demo-04-dgd-live-20261105-a3`, namespace
`dynamo-ft-snapshot-demo-5af75fb6dd`, with roughly 3.6 TB free on the prepared
NVMe filesystem. That preparation creates no source DGD/capture Job. Root's
fresh hardware clearance reports no new node conditions or Xids relative to its
saved baseline; the exact cp-0124 GPU1/3 pair remains this workstream's slot.

The new controller runs in a detached, bounded Docker container on the existing
jump host. This reuses the proven routing-controller pattern instead of adding
an in-cluster privileged coordinator or cross-namespace/cluster RBAC:

- A fresh isolated remote workspace is bound at the same logical repo path.
  Existing absolute run paths, source hashes and lease checks remain valid.
- The jump host's existing kubectl and kubeconfig mount read-only. Existing
  Python dependencies mount read-only. Credentials are never copied into the
  payload, result collection or local source tree.
- The source payload contains scripts, the exact pinned config/profile inputs
  and a whitelist of safe run inputs. CPU preparation's command/manifests are
  excluded because Secret-apply manifests may contain pull credentials.
- Before any GPU action, CPU-only/network-disabled probes check the actual
  Python/PyYAML/curl runtime and the frozen presenter/controller imports. The
  existing host API client has a separate read-only readiness check.
- Full mode runs unchanged presenter prime → actual main-panel PTY capture →
  guarded scoped cleanup. It uses the stock 3,600-second source Job limit, with
  a bounded 5,400-second prime observer; it never patches immutable Job specs,
  adopts old artifacts or automatically replays a failed capture/fault.
- The controller checks real, complete streaming coding output and verified
  active NVMe staging before proceeding to the presenter fault. CLI exit 0 or
  Pod readiness alone cannot qualify the run. Failure records diagnostics and
  attempts only the existing ownership-checked cleanup; uncertainty retains the
  reservation for root review.
- The detached controller persists through external VPN/chat interruption.
  Collection requires terminal controller state, verifies complete archive
  membership/hashes and safe paths into a fresh directory, and never silently
  adopts local state or releases root's separate reservation. Root independently
  audits the cluster after collection.

Implementation: `scripts/workshop_snapshot_remote_controller.py` and
`scripts/workshop_snapshot_remote.py`. All 149 Snapshot tests pass, including
22 controller/transport tests for credential exclusion, source/lease/old-run
refusal, real stream/storage gates, no fault after failed prime proof, cleanup
acceptance, archive traversal/hash/no-overwrite safety, and uncertain-launch
replay prevention. A credential-free 163-file isolated copy successfully
imported and previewed the real presenter. Existing a3 model/runtime/engine/
manifest hashes remain unchanged. Full live outcome and root's independent
cleanup audit must be appended when they exist.

The enhanced runtime preflight caught a real dependency gap before any a3 GPU
Job started: the pinned slim Python image has no curl. The original readiness
preflight and the failed dependency receipt remain separate immutable attempts.
Root authorized an owned local controller image derived from that exact base,
adding curl only inside the image. `scripts/workshop_snapshot_controller_image.py`
retains the Dockerfile, pinned base, installed package versions, exact derived
image ID and build log. The transport validates `controller-image.json` plus
raw Dockerfile/package hashes, freezes that provenance in the plan and uses the
exact image ID for both probes and execution. It never overwrites/pushes the
base, copies credentials or installs host packages. Both the normal preflight
and the frozen-source bootstrap prove curl execution before GPU work. The
qualified GPU model/runtime/engine and a3 core input hashes remain unchanged.

### A3 launch receipt

`results/demo-04-dgd-live-20261105-a3/remote-package/launch-result.json`
records a successful detached launch at `2026-11-05T19:45:59.516129224Z`
(11:45:59 Pacific). Controller
`kubecon-snapshot-demo-04-dgd-live-20261105-a3-ef3abdd0` initially reported
running with no OOM or restarts. Its isolated 171-file payload passed hash
verification, and the CPU-only, network-disabled bootstrap actually executed
curl 7.88.1 and imported the frozen presenter/controller before GPU work.

- Payload SHA-256:
  `1f9aa17627d617195410967e2475e294fb70dd2e27a026308dba8bebcc08cfaa`.
- Frozen plan SHA-256:
  `1445d3a5288a49283995cebbf5e3defc177557c7eec1ab05d4ead8defd40c5d0`.
- Exact controller image:
  `sha256:f12b417250bc7d8e150e929114e60762e86f25146ea1f9289990a0fc7b5e9872`.

The original slim-base image-build attempt failed immediately because this
host's legacy Docker CLI rejects `--progress`. A separately recorded fresh
image-build attempt removed only that CLI flag, retained both attempts and
completed successfully; no base image or host packages were modified. The
Snapshot suite passed 156 tests before one additional image-attempt regression;
the latest targeted image-builder suite passed all four tests.

Launch alone does not qualify restored inference or the presenter. Root must
collect terminal controller receipts and the actual recording, then audit the
cluster independently and release its separate local reservation. The local
original run remains CPU-prepared while remote execution updates its isolated
workspace. Collection does not overwrite that local state.

Deferred transport refinement: `build()` currently shadows its local
`controller_name` variable in a payload loop, so its return-only console summary
can show a script path. The persisted plan/manifest have the correct controller
name and were used successfully by launch. Fix after a3 is terminal, preserving
the live bundle's frozen source and original launch evidence. This console-only
name issue was subsequently fixed after the controller became terminal; the
original transport source and bundle remain retained.

### A3 external observation interruption

Root's last verified read-only status at `2026-11-05T20:04:40Z` showed a healthy
Docker controller in `prime`, with a current heartbeat at 20:04:38 UTC. Creating
DGD UID was `dbba0138-63e9-4dbd-b25e-b5cc0e47c624`; automatic SnapshotJob UID was
`885a160b-b005-4144-a61f-0a4be4376352`. The source main/helper were both Running,
the frontend was Ready, and the graph was waiting for its checkpoint. No staged
artifact, initial restored serving proof or presenter fault was recorded yet.
The saved combined status/console receipt is
`remote-package/observations/status-and-prime-tail-20261105-a1.json`.

At approximately 12:15 Pacific, root again lost the external tunnel; a fresh SSH
probe timed out. No remote controller stop/restart, source replay or cleanup was
attempted. This is loss of external observation, not evidence of a Snapshot or
controller failure. The detached design removes that external observer from the
capture/stage/release path, but its continued progress and eventual result still
need fresh verification after access returns. The default source deadline is
approximately 20:46 UTC; the outer prime phase has its separately bounded
5,400-second window. Do not submit another controller or adopt a new run merely
because the external status command cannot connect.

### A3 completed live result and collection

The durable controller completed all three phases without another capture or
fault attempt:

- Prime: 19:45:59.780 → 20:31:00.228 UTC, 2,700.448 s (45.0 minutes).
- Actual presenter: 20:31:00.650 → 20:32:15.504 UTC, 74.818 s.
- Scoped cleanup finished at 20:32:30.243 UTC; controller exited successfully
  at 20:32:30.514 UTC.

The automatic artifact became Ready at 20:24:41 UTC. The controller completely
hashed, copied and verified its 1,818 files / 94,232,801,717 bytes before releasing
the capture helper at 20:29:57.848 UTC. Source hashing took 198.293 s, copy
44.461 s and destination verification 63.843 s. These are offstage preparation
clocks, outside the reported restoration measurements. No source deadline
extension or shared platform change was made.

Initial restored worker `bb2c7d35-4928-40dd-8fd3-47dcf3acdf75` and replacement
`0c6e18f0-1b80-4f91-a57f-f13706e7dda8` differ from each other and the captured
source. The creating DGD, frontend, Service, snapshot/content, node and physical
GPU identities stayed fixed. Both frontend streams completed with fresh
`add(a, b)` code; the decode-worker ID changed from `6197630437751158` to
`2863060121645374`. Initial agent restore was 36.799 s; onstage replacement
agent restore was 33.895 s. Replacement Pod-to-Ready was 59 s and
deletion-to-observed-Ready was 64.288 s. These clock boundaries overlap and must
not be added. The final coding request started at 20:32:13.417 UTC, after the
request-free readiness/timing step.

The first archive transfer succeeded but exposed a local collection-verifier
performance bug. TAR members were written in path order while verification
followed manifest insertion order, causing repeated backwards gzip seeks and
decompression. Root stopped only that local verifier; the remote completed
controller and immutable downloaded archive were untouched. The narrow fix
walks physical TAR member order with manifest lookup, retaining all size, path,
membership and hash checks before extraction. A regression explicitly reverses
manifest order relative to a nonalphabetical TAR and checks forward member
offsets; it fails against the preserved original verifier and passes against
the fix. All 17 transport tests pass. This is workshop tooling, not a Dynamo
Snapshot defect.

The original 73,335,229-byte archive SHA-256 remains
`e7fd40f144ce992819b47bc0649b1768ce63e908ec4a94632b619187aa56d15a`.
Offline verification/extraction to the fresh
`results/workshop-snapshot-a3-collected-vpn2-a2` directory took 6.661 s, without
another SSH/download. Independent audit then rehashed all 9,283 collected files
(805,233,939 uncompressed bytes), all 42 recorder source snapshots and all 33
frozen evidence files. It independently checked the two completed SSE streams,
identity invariants, raw agent summary, separate timing boundaries, staged
artifact inventory/hash manifest, helper-release ordering and scoped cleanup.
Raw/private evidence remains ignored under `results/`.

Only the byte-identical sanitized `main.txt` and `capture.json` were exported to
`demos/transcripts/live/04-snapshot-dgd/demo-04-dgd-live-20261105-a3/`.
Transcript SHA-256 is
`51b580663e2a81bd077b6433dec70cc5a7be723a824b42583750173da7cfcae6`.
Full local audit, original/fixed verifier sources and hashes, regression proof,
offline extraction receipts and export manifest are under
`results/demo-04-dgd-live-20261105-a3/collection-verifier-fix-a1/`.
No local state was adopted and no local reservation was released by collection.

The live recording revealed a presentation issue absent from simulated output:
each identity/readiness poll printed full staging JSON and disk tables. The
actual main transcript is about 47 KB. The subsequent projection-only change
below quiets those checks and keeps this first passed recording unchanged.

### Final root closeout and projection refinement

Root's separate final live audit passed at `2026-11-05T21:04:19.048772Z`:
zero owned DGDs, Pods, ResourceClaims, SnapshotJobs and batch Jobs; the original
agent UID/spec/restart counts; private `nfs4` EFS view restored; mount helper
absent. It retained snapshots and both checkpoint copies. The audit is
`results/workshop-snapshot-a3-root-audit-20261105-a2/audit.json`.
Root then released only the exact local mirrored reservation at
`21:04:45.467836Z`; its receipt and released-owner copy are alongside that audit.
This is scoped Snapshot closeout, not deletion or audit of unrelated workloads.

After that completed qualification, the canonical presenter was refined for
projection:

- Run every NVMe validation as before, saving its verbose stdout in private
  `storage-validation.log` rather than repeatedly printing JSON/disk tables.
  The original command/check receipts still persist. Failures remain visible
  and propagate; no validation, ownership or staging gate is skipped.
- Show one short verified storage summary and a small changed/unchanged
  recovery table. Full `recovery-proof.json` retains exact UID/GPU identities.
- Use the introduction's existing compact YAML formatter for the checkpoint
  fields and argument lists. Schema paths and full executable manifests stay
  available.

The new [offline projection preview](snapshot-projection-a1/rehearsal-main.txt)
is explicitly simulated, with no measured recovery durations or cluster calls.
Its PTY capture passed. All 17 presenter and 16 capture tests pass, including
new checks that repeated quiet validations still execute and retain full
receipts, and failures still surface with their diagnostic log. The actual a3
recording/source snapshots remain byte-identical. No expensive live retest was
performed for these output-only changes; the live functional evidence and the
new layout preview deliberately remain separate artifacts.

## Upstream candidates

- Existing open workstream: destination runtime/Pod context from restore proxy
  and destination `HF_HUB_OFFLINE` policy before registration. Keep the current
  qualified bridge until an image with upstream fixes passes capture, initial
  restore and automatic replacement without the custom runtime module.
- Possible lifecycle API improvement: separate `wait_restored`/identity proof
  from inference verification so operator users and presenters can measure
  readiness without sending a request. The present duplication is in this repo's
  qualification harness; it is not evidence of an upstream Dynamo defect.
- Possible operator usability improvement: document automatic-checkpoint owner
  UID/adoption semantics prominently, including the effect of deleting a DGD.
- Possible operator improvement: expose the automatic SnapshotJob/source-Job
  deadline and report capture/publication/hold phases. The saved installed CRD's
  `checkpoint.job` exposes capture `podTemplate` and `gmsClientContainers`, with
  no SnapshotJob deadline field. Setting a Pod's deadline alone would not extend
  the parent Job's 3,600-second limit. The overnight outage exhausted that bound
  while the helper was meant to fence GPUs until staging; no shared operator
  change is authorized or proposed here.
- Live admission now confirms this is a creation-time configuration gap:
  SnapshotJob `spec` is immutable, so a post-creation extension cannot be the
  workshop mechanism. A proposed DGD field should set the deadline while
  creating the automatic SnapshotJob, with its default and helper-inclusive
  lifetime documented. Do not weaken immutable-spec or ownership guards to
  bypass admission. An owned batch Job-only override is not qualified here.
- Preparation-controller durability is a workshop improvement: the staging
  callback and source-helper completion currently depend on the external
  observer continuing. A VPN outage or stopped controller can leave a valid
  captured artifact while the held helper consumes its remaining Job lifetime.
  Consider running the bounded offstage coordinator where it can survive chat
  interruptions and external VPN loss, retaining receipts and exact GPU/storage
  ownership. A3 now qualifies this using an owned detached container on the
  existing jump host; no new in-cluster coordinator/RBAC was installed. This is
  separate from engine recovery and is workshop orchestration, not a Dynamo
  runtime patch.
- Keep artifact readiness and composite completion/serving readiness distinct.
  A Ready artifact can coexist with a failed helper-inclusive source Job. It
  would be unsafe to treat artifact readiness alone as proof that all helpers
  finished (for example, a GMS saver) or that a restored service actually served
  requests. Document that state and provide clear recovery/adoption guidance
  rather than silently promoting these two failed orchestrations to successes.
- Private artifact-specific NVMe mount handling is environment-specific test
  plumbing. Do not fold it into the general runtime-bridge upstream request.

No upstream issue/PR or external message was submitted by this workstream.
