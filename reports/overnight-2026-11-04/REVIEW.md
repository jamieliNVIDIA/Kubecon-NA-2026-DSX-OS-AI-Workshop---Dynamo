# Dynamo workshop demo review

Updated: November 5, 2026, 7:22 PM Pacific. Repository checkpoint requested before ending for the night. The earlier
[MORNING-REVIEW.md](MORNING-REVIEW.md) is a historical checkpoint; this page is
the current review entry point. Detailed execution notes are in
[RESUMED.md](RESUMED.md) and [STATUS.json](STATUS.json).

[Current patches and workarounds](PATCHES-AND-WORKAROUNDS.md) inventories runtime
overlays, upstream backports, package combinations and workshop-specific plumbing,
including the older prototypes that are not used by the latest tested paths.

## End-of-day checkpoint

The user explicitly requested committing and pushing all local repository work
on November 5. The newer GitLab slide-deck commit `5801f74` was preserved with a
fast-forward before adding this work. All **734 local tests passed** in
**109.216 seconds**, including the reviewed Full-only Helm transport fix;
109 new/changed JSON/YAML configuration and receipt files parsed successfully.
The source/report/recording credential-pattern check found no matches.
Raw private `results/` evidence and `.local/` credentials remain excluded by the
existing ignore rules; review notes, receipts and shareable captures are included.

The Helm repair is implemented and independently source-reviewed. Root's earlier
manual same-image driver-values query passed; execution of the newly generated
preflight and the fresh Shadow fault/promotion/replenishment run remain pending.
No new GPU run was started for this repository checkpoint. Internal source edits
were quiesced; there are no local GPU lease files. The persistent MX CPU cache
and Redis are retained as requested. Resume with current cluster/producer checks.

## Latest results

The **public take-home service now works** on the tested DRA/H100 configuration:
unmodified official runtime, prepared cache, one successful coding response and
verified cleanup. The Service selector fix is in the renderer. Snapshot's new
**durable controller completed the full integrated NVMe presenter and cleanup**
while the external VPN was unavailable. Collection and independent offline
audit passed; the sanitized recording is exported. Final root resource/storage
audit and local reservation closeout also passed. **KVCR's controlled cross-node
peer-reuse capture is now live-qualified and cleaned**, with an independent
audit and shareable main recording. C32's completed two-worker routing pair is
accepted; its one-worker arm remains rejected. **Shadow's instrumented writer
has now passed live and independent audit.** The first full reader imported
the committed weights, then exposed reader-adapter gaps. The source-backed
v6 repair now has actual-image CPU and independent acceptance. Fresh full-a4
passed actual worker-local RAM staging, active/parked-reader readiness and
three retained coding responses. Its presenter then failed before fault
injection because the Linux controller invoked the Mac-specific Helm path
`/opt/homebrew/bin/helm`. Remote cleanup passed; promotion/replenishment remain
unqualified. The [original failed capture](../../results/shadow-full-a4-remote-collected-20261105-a1/recording/failed-main.txt)
and [1,978-file collection](../../results/shadow-full-a4-remote-collected-20261105-a1/collection-verification.json)
are preserved; [independent audit](SHADOW-FULL-A4-REVIEW.md) and [root closeout](../../results/workshop-shadow-full-a4-root-closeout-20261105-a1/complete.json) passed, including exact local reservation release.

The preceding full-a2 passed preparation/CUDA/health and deployed under the reviewed
[durable controller](SHADOW-FULL-REMOTE.md). It then **failed during reader
warmup before any fault injection**: DeepGEMM's eligibility probe calls the same
generic ModelOpt configuration method, which still reads the consumed
`w13_input_scale`. This is a later call site than the repaired reconstruction
callback. The controller preserved previous-generation logs and completed scoped
cleanup at **3:51:30 p.m. Pacific**. The [1,221-file collection](../../results/shadow-full-a2-remote-collected-a1/collection-verification.json)
and [independent failure audit](../../results/shadow-full-a2-independent-audit-a1/verification.json) passed. Root's [fresh live audit](../../results/workshop-shadow-full-a2-root-closeout-20261105-a1/live-audit.json)
found no owned Pods/claims/DGD/DeviceClass, no new Xids and unchanged driver/boot.
The original local prepared state remains unchanged. [Root closeout and exact
reservation release](../../results/workshop-shadow-full-a2-root-closeout-20261105-a1/complete.json) passed at 3:58:44 p.m. Pacific. No parked-reader or recovery result.

At the user's request, an owned **persistent ModelExpress development cache**
is running on cp-0198: **96 GiB RAM, 112 GiB container limit, zero GPUs**.
The [development notes](MX-DEV-CACHE.md) and [independent review](MX-CPU-CAPABILITY-AND-RAM-SEED-REVIEW.md)
retain the failed attempts and exact current recipe. Two seed checks exposed
local cache assumptions: centralized blob layout, then Xet storage keys being
different from full-file checksums. A fresh [pinned public model manifest](../../results/mx-dev-source-hf-tree-20261105-a1/receipt.json)
confirmed the source data and all 114 files. The corrected **a4-reviewed** seed
checks authoritative LFS SHA256 / Git blob hashes, preserves the first failure
durably and completed all 114 files in **316.35 seconds**. Its server is Ready and
kept running. The separate cross-node CPU transfer also passed: **114 files / 75.063 GB
in 117.85 seconds**, CUDA uninitialized, all file hashes checked. [Seed](../../results/mx-dev-persistent-a4-independent-audit-20261105-a1/verification.json)
and [client](../../results/mx-dev-stage-a1-independent-audit-20261105-a1/verification.json)
were independently accepted. The completed client Job/RAM was cleaned while
the persistent producer/Redis remained unchanged. This qualifies development
file staging. Full-a4 subsequently passed the same all-file staging inside its
actual GPU worker Pod, before native engine loading. A startup benefit remains
a separate measurement gate.
The earlier CPU RPC/shard test is accepted by a [supplemental audit](../../results/mx-dev-cache-capability-a2-independent-audit-20261105-a1/supplemental-disposition.json),
while its original wrapper remains failed for its incorrect Torch-import
assertion. No startup speedup or direct GMS-MX/P2P composition is claimed.

The [v6 reader repair](SHADOW-READER-V6.md) now also passed its
[actual-image CPU check](../../results/workshop-shadow-reader-v6-cpu-live-20261105-a1/result.json):
all 80 observed roles, three SwiGLU cases, preserved parameter aliases, CUDA
uninitialized, the original native warmup failure reproduced before repair,
and native warmup selection/count passing afterwards. It restores only the
source-prescribed optional `None` attributes. Fresh **default full-a3** (without development-cache staging)
has passed preparation, exact-pair CUDA arithmetic, fresh health and remote
preflight; its durable controller ran from **4:55:04–5:05:00 p.m. Pacific**.
The reader reached parked standby. Exact retained snapshots differ only in
engine-1 `ready` / `started` becoming true; Pod/container generations, roles
and the complete GMS state remained unchanged. The [readiness repair proposal](SHADOW-STARTUP-READINESS-PROPOSAL.md)
waits for kubelet probe health, compares stable identity and saves each coding
payload before later checks. A3 remains failed, with no fault or retained
initial-coding qualification; its original responses were not saved before the
old guard threw. Scoped cleanup and fresh GPU health passed; independent/root closeout and [review of the host-only fix](SHADOW-STARTUP-READINESS-REVIEW.md) passed.
Fresh cache-enabled full-a4 passed preparation, exact-pair CUDA arithmetic,
fresh health and remote preflight. Its durable controller launched at
**5:34:24 p.m. Pacific**. It passed worker RAM staging, active/parked readiness
and all three retained coding responses at **5:43:25 p.m. Pacific**. The actual
capture failed on missing `/opt/homebrew/bin/helm` before any fault. Post-failure
health and scoped remote cleanup passed; the controller exited at
**5:44:13 p.m. Pacific**. The fresh **5:47:12 p.m. Pacific** inventory shows
24 advertised / zero allocated GPUs and no placement issues. Independent
failure audit and final root mirror release passed. This is a local
controller packaging gap, not evidence of a native engine or GMS defect.

| Area | Current status | Remaining work / evidence |
| --- | --- | --- |
| Single replica | **Live-qualified**; recordings and cleanup passed | [Intro/MX notes](BASELINE-MX.md); existing booth recordings remain available. |
| ModelExpress | **Earlier presenter live-qualified**; later repeat interrupted before peer loading | [Notes](BASELINE-MX.md). No new matched result is claimed from the interrupted repeat; preserve the earlier passing recording. |
| Routing / metrics | **C16 and C32 two-worker routing pairs accepted**; recorded presenters passed | [C16 results](routing-sweep/C16-RESULTS.md), [recorded walkthrough](../../demos/transcripts/recorded/06-routing/c16-20261105-a1/recorded-main.txt). C32's original terminal collection verified 883 files and 48 frozen source files; two-RR/two-KV passed independent acceptance and cleanup. One-RR is rejected after a liveness restart during mandatory warmup: no C32 scale-out ratio and no replay. |
| Disaggregated comparison | **Both four-GPU arms independently accepted and cleaned** | [Results](disagg/RESULTS.md): aggregate/P-D 174.75/174.36 output tokens/s; P/D improved observed tails but slowed medians. 37.75 GB transferred, zero transfer/notification failures. Fixed-order N=1; the interrupted observer was not replayed. Earlier P/D mechanism recording remains valid. |
| Request continuity | **Paired C4 test live-qualified**, both cases cleaned | [Actual consoles and proof](../../demos/transcripts/live/05-request-continuity-load/README.md): baseline 4/4 in both modes; after fault, enabled 4/4 versus disabled 2/4. Functional continuity, not an SLO claim. |
| Integrated Snapshot | **Presenter, collection audit, final root live audit and lease release passed** | [Notes](SNAPSHOT.md). Fresh creating DGD, verified NVMe staging, initial coding inference, automatic replacement and fresh final coding inference. Stock 3,600-second source deadline; no extension. Root confirmed zero owned workloads/claims, unchanged private agent and restored EFS view before releasing the mirrored reservation. |
| KVCR | **a6 cross-node peer reuse live-qualified, independently accepted and cleaned** on the pinned experimental stack | [Main recording](../../demos/transcripts/live/07-kvcr/20261105-a6/main.txt), [audit](../../results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json), [notes](KVCR.md). Six blocks / 103,809,024 bytes transferred and 4,224 external/cached tokens reused. The recorded child used prepared workers after supported B/frontend replacement; startup is outside capture. Final cleanup removed owned Pods/claims/DGD and parent lease. Original failed captures remain failed. No automatic-routing, under-load speedup or production claim. |
| KVCR Guard recovery | **Earlier same-node component qualification passed with controlled routing**, including warm handback and cleanup | [November 4 receipt](../receipts/2026-11-04-kvcr-guard-nightly.json), [report](../workshop-kvcr-guard-qualification.md). After killing A's engine, a request pinned to B retrieved A's preserved host cache: six blocks / 103,809,024 bytes and 4,224 reused tokens. Replacement A later reused the handed-back pool. First unpinned post-fault request returned 503. Automatic HTTP failover, in-flight Guard-assisted migration, cross-node failure recovery and GMS/Shadow composition remain unqualified. Demo 7's later cross-node capture tested ordinary peer reuse without a fault. |
| Shadow Engine | **Full-a4 passed RAM staging, active/parked readiness and three retained coding responses; capture failed before fault on missing Helm** | [Original failed capture](../../results/shadow-full-a4-remote-collected-20261105-a1/recording/failed-main.txt), [collection verification](../../results/shadow-full-a4-remote-collected-20261105-a1/collection-verification.json). Linux controller invoked a Mac-only path. Independent/root closeout and exact lease release passed; a packaging repair is in progress. Promotion/replenishment remain unqualified. |
| Take-home managed service | **Public cached baseline live-qualified and cleaned** | [Attendee guide](../../take-home/README.md), [final receipt](../receipts/2026-11-05-take-home-public-baseline.json). Official image/version, strict CRD compatibility version, explicit cache UID and corrected frontend selector are documented. Fresh weight download, device-plugin serving and advanced compositions are separate gates. |

## What changed since the morning review

- Snapshot's offstage prime, storage staging, actual PTY capture and cleanup now
  run on an isolated jump-host controller. It finished during the VPN outage,
  addressing the observer-lifecycle gap from the earlier failed attempts. Its
  reported recovery clocks are **59 s Pod-to-Ready**, **64.29 s deletion intent
  to observed Ready**, and **33.89 s agent restore**. These are separate clocks;
  the independent audit rehashed all 9,283 collected files, 42 source files and 33 capture-evidence files and verified both completed coding streams. The [sanitized recording](../../demos/transcripts/live/04-snapshot-dgd/demo-04-dgd-live-20261105-a3/main.txt) is exported. The [final root live audit](../../results/workshop-snapshot-a3-root-audit-20261105-a2/audit.json) passed at 1:04 p.m. Pacific, confirming the private agent/EFS view and no owned DGD, Pod, claim or job. The adjacent local-lease-release receipt records the subsequent mirrored reservation release; the earlier audit's `lease_released: false` is its pre-release observation.
- Take-home qualification caught and fixed three local recipe issues: the CRD
  needs an X.Y.Z compatibility override rather than a dev-package suffix; the
  reused cache needs an explicit compatible UID; Grove overwrites managed-by,
  so a Service must select stable workload/role labels. The unchanged running
  engine served the original coding request after the Service-only revision.
  The final generated selector has a regression test.
- Shadow's instrumented writer a6 passed three correct coding streams, both
  complete reader-ready manifests and independent audit of 626 collected files.
  It preserves the exact 40 legitimate FP32 correction-bias gradient flags per
  rank, without relaxing other dtype, alias or allocation checks. Both reservation
  mirrors were released after [root closeout](../../results/shadow-writer-a6-root-closeout-a1/complete.json).
  The first full candidate then imported committed read-only weights on both
  ranks, passed skeleton/materialization, and failed because our generic ModelOpt
  callback reads consumed checkpoint attributes (`w13_input_scale`). No fault
  was injected; canonical cleanup and post-failure GPU health passed. The
  [reader-only v5 repair](SHADOW-READER-V5.md) follows the pinned Humming oracle's
  final-schema builder. **11 focused tests and independent review passed**;
  the [actual-image CPU test](../../results/workshop-shadow-reader-v5-cpu-live-20261105-a1/result.json)
  passed all 80 observed roles with real Humming configs and CUDA uninitialized.
  All 29 non-reader function bodies and the v4 data schema remain identical.
  Earlier failed attempts remain preserved; this is our experimental adapter
  gap, not an established upstream GMS defect. A separate earlier observer TLS
  failure was resolved by restarting the owned tunnel, with fresh SSH working.
- KVCR's revised fixture measured **6,406 common tokens** against an actual
  **4,224-token cache page**, with both prompts fitting the 8,192-token context.
  The earlier failure was worker admission, not insufficient context. The
  take-home download ran between the workers' registrations and added ancillary
  assets to their shared cache, strongly supporting a cross-test metadata race.
  Current matching inventories were confirmed; replacing only B and frontend
  from settled metadata restored two-worker admission at 12:57 p.m. Pacific.
  Strict model-identity checks and all failed captures are preserved. The
  [a6 binding](../../results/workshop-kvcr-demo-20261105-a6/prepared-binding.json)
  and [fresh preflight](../../results/workshop-kvcr-demo-20261105-a6/prompt-preflight.json)
  passed, followed by a successful actual source/peer capture. The [independent
  audit](../../results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json)
  verified **48 source files / 417 evidence files**, six transferred blocks,
  **103,809,024 bytes**, and **4,224 external/cached tokens** across the two
  nodes, including matching wire operation and EFA-provider evidence. The
  [recording](../../demos/transcripts/live/07-kvcr/20261105-a6/main.txt) is
  exported. [Final scoped cleanup](../../results/workshop-kvcr-demo-20261105-a6-cleanup-controller/terminal.json)
  passed at 1:19:03 p.m. Pacific with zero owned Pods/claims/DGD and the parent's
  lease absent; original failed and fresh captured bytes remain unchanged.
  The projected source/target steps took **224.8 / 216.0 s**, while their HTTP
  requests took **19.55 / 19.43 s** to DONE. Proof collection and gate waits
  are part of the presenter pacing, not inference speed; this is functional
  peer reuse on an experimental stack, not a matched performance comparison.
- P/D used the original full AgentX workload and four-GPU budget. The aggregate
  arm has **313 successful records**, versus **312 for P/D**, both with zero
  errors/cancellations/overflows. Exported throughput uses each official
  1,200-second phase window. Both arms and scoped GPU cleanup are accepted;
  borrowed CPU/cache remain intact. The health-probe expiry noise matches the
  already-merged upstream fix #15594, an image/release gap rather than a new bug.
- C32's original terminal collection and [independent acceptance](../../results/workshop-routing-c32-collection-terminal-20261105-a2/independent-acceptance-and-cleanup.json)
  accepted the completed two-RR/two-KV pair. Scoped GPU cleanup and the root's
  later mirrored lease release passed, retaining the CPU client. The one-RR
  liveness restart occurred during mandatory warmup, so that arm is rejected
  and cannot establish a scale-out ratio. [Detailed C32 analysis](routing-c32/C32-RESULTS.md) records the accepted pair
  and exact failure timeline; C16 and C32 remain separate observations.

## Next steps

1. Full-a4 independent evidence audit and exact local reservation release
   passed. Preserve that failed capture; Worker RAM staging, active/parked readiness
   and three retained coding responses passed. The failure was missing Helm in
   the Linux controller before fault injection; native v6 and the accepted writer
   basis remain unchanged.
2. Implement and review the [Full-only Helm compatibility bind](SHADOW-CONTROLLER-HELM-PROPOSAL.md),
   with the real driver-values query before GPU deployment. Root's separate
   [same-image CPU probe](../../results/workshop-shadow-full-a4-root-closeout-20261105-a1/host-helm-same-image-cpu-probe.json)
   passed using the existing Linux Helm binary. That manual check does not fix
   the packaged controller. Preserve the late pre-fault check; use a fresh
   candidate for the actual single-fault promotion/replenishment recording.
3. Keep the persistent MX producer and Redis running. Seed, cross-node CPU
   staging and actual GPU-worker file staging passed; native full-a4 engines
   subsequently initialized. Quantify startup benefit separately before making
   a performance claim; direct native GMS-MX/P2P composition remains unqualified.
4. Investigate the C32 one-RR liveness issue from its completed
   [written interpretation and saved evidence](routing-c32/C32-RESULTS.md). Do not replay or blend C16/C32 into a
   controlled capacity curve.
5. Iterate on presentation pacing, especially KVCR's proof-collection pauses;
   Snapshot's compact [projection preview](snapshot-projection-a1/rehearsal-main.txt)
   is offline-verified, with guards and full private evidence retained. Keep completed
   recordings intact and track remaining take-home/runtime gates separately.

## Validation, resources and limits

The latest completed full local suite passed **734/734 tests** in **109.216 seconds**
with permitted loopback access:
`results/workshop-prepush-local-suite-20261105-a1.log`. This includes the
Full-only Helm transport fix and independent review coverage. The prior
717/717 result remains historical. Staged source/configuration whitespace checks
passed; hash-bound console captures retain their original whitespace. Nine
staged capture transcript hashes were verified. These local tests are separate
from live qualification and do not establish Shadow recovery.

Root's live network commands require sandbox escalation. The [fresh inventory
at **01:47:12 UTC / 5:47:12 p.m. Pacific**](../../results/workshop-shadow-full-a4-root-closeout-20261105-a1/inventory/audit.json)
confirms **24 advertised / zero allocated GPUs and no issues** after full-a4
remote cleanup. The [exact namespace audit](../../results/workshop-shadow-full-a4-root-closeout-20261105-a1/live-audit.json)
found no owned Pods, claims, DGD or DeviceClass; persistent producer/Redis are
Ready with unchanged identities and zero restarts. The
[fresh health/source audit](../../results/workshop-shadow-full-a4-root-closeout-20261105-a1/source-health-audit.json)
found no new Xid message bodies, unchanged driver/boot and all 20 inputs / 32
held sources unchanged. The exact root local mirror was released after independent
closeout. This is a timestamp-specific placement observation, not utilization
proof. CPU clients, model caches and Snapshot artifacts remain retained.
P/D, Snapshot, C32, KVCR and Shadow writer have separate cleanup receipts.

Keep all failed attempts, original raw evidence and earlier passing recordings.
No shared drivers/operators/platform changes, external messages or upstream
submissions were made. The user has now explicitly authorized the repository
commit and push recorded in the end-of-day checkpoint. The dedicated curl-enabled controller
image is an owned local build; the shared base and host packages were unchanged.

## Runtime readiness and upstream items

- The take-home result uses an official **development nightly**, cached weights,
  DRA and the explicit tested UID/GPU profile. It is not stable-release or
  all-feature qualification.
- Snapshot still uses the previously qualified identity/offline bridge. Neal's
  separate upstream workstream remains open; the artifact-specific NVMe mount
  handling is workshop plumbing. Node-local path/hash proof does not establish
  uncached physical SSD read bytes or a matched cold-start speedup.
- KVCR's controlled peer reuse passed on its explicitly pinned experimental
  dependency bundle. Automatic routing and under-load performance remain open.
- Shadow runtime descriptor integration remains experimental. The writer is
  live-qualified and the reader repair CPU-qualified; actual parked-reader,
  promotion and replenishment gates remain open.

[Upstream candidates](UPSTREAM-CANDIDATES.md) distinguishes actual runtime
findings, packaging gaps and local harness fixes. [Open review questions](MORNING-DECISIONS.md)
remain useful, with the status table on this page taking precedence over older
checkpoints.
