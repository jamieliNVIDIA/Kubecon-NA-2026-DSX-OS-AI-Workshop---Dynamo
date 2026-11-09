# November 5 resumed work

The user explicitly asked to continue unfinished work after reviewing the
morning packet. The former overnight cutoff does not apply to this resumption.
The morning packet remains an accurate historical checkpoint.

- [x] Reaudit cluster: 24 GPUs advertised, zero allocated, no conflicts at 19:02:25 UTC.
- [x] Recheck prepared P/D campaign source hashes, exact CPU UID, idle state, cache and unused arm paths.
- [x] Finish locked AgentX P/D pair: Super VL/vLLM, same four H100s, C16, full 393-trace corpus, 900 s admission / 300 s drain.
- [x] Verify actual frontend model, run both profiles, analyze and compare only accepted results; scoped GPU cleanup passed.
- [x] Revise KVCR token-aware fixture/preflight and restore strict two-worker admission with supported B/frontend replacement.
- [x] Capture and independently qualify fresh successful KVCR a6 peer reuse; scoped cleanup passed and owning parent lease is absent.
- [x] Run Snapshot preparation durably through stage/source-release, capture integrated replacement, audit collected files and final live cleanup, and release mirrored lease.
- [x] Complete and live-qualify Shadow mutable linear/MoE writer lock coverage; scoped cleanup passed.
- [x] Clean failed descriptor-writer a3 and verify final health; original crash cause remains unknown because its log disappeared with Pod deletion.
- [ ] Prepare a fresh Shadow diagnostic with continuous/previous-log capture; qualify actual descriptors, reader, promotion and replenishment separately.
- [x] Run fresh C32 routing on original four routing GPUs with an independent CPU client and exact frontend model readiness; accept two-RR/two-KV, reject one-RR after liveness restart, collect original terminal evidence and verify cleanup without replay.
- [x] Verify accessible public runtime and actual cached take-home rendered service; cleanup passed.
- [ ] Qualify fresh network download and other take-home allocation/composition modes separately.

Use the existing qualified manifest renderers, actual v1beta1 CRD and unchanged
locked workload parameters. Exact physical assignments remain in allocations.json.
Root executes live commands. Agents prepare narrow changes and independently
check evidence. No commits, pushes, upstream submissions or external messages.

## Live checkpoint, 11:42 Pacific

- Revised Shadow writer a5 passed: three coding responses,240rebindingrows
  (80linear+40MoE per TP rank), no new Xids, exact GPU identity, independently
  frozen evidence and scoped cleanup. Reader descriptor reconstruction remains
  separate and unfinished.
- KVCR a4 stopped CPU-only on BatchEncoding handling; cleanup passed. Fresh a5
  actualtokenizer measured6426/6427prompt tokens,6406common; both CUDA/EFA probes
  passed and engines are loading. Real worker geometry/reuse still pending.
- Public runtime CPU check passed unmodified/no imagePullSecret. Admission version
  format and cacheUID mismatches were caught beforeGPU deployment. Compatibility
  version split is fixed; user-ID parameter and fast failedJob handling are next.
- Snapshot a3 remainsCPUprepared. Slim controller lackedcurl, and the first
  derivedimagebuild rejected a legacyDockerunsupportedflag. Dedicatedownedimage
  buildattempta2 preserves both failures; no sharedDocker/platformchange.
- P/D aggregate completed warmup and is finishing its full900s+300s measured
  phase. C32controller has its ownGPU workers. No interim throughput claims.

## Completed public baseline and renewed transport interruption

The unmodified official public runtime served the pinned Super VL model on the
assigned two H100s. A Service-only revision removed the controller-owned label
from the selector; one original coding request completed normally. Namespace,
DGD, frontend, worker, image and GPUs were verified unchanged. Canonical cleanup
passed and the renderer now has the regression fix. Final public/cached receipt:
`reports/receipts/2026-11-05-take-home-public-baseline.json`. Cold network weight
download, other allocation modes and advanced compositions are not qualified.

At about12:15Pacific, the external API tunnel dropped and a fresh SSH connection
timed out. A new VPN reconnect question is pending. P/D's local observer ended,
while its original remote900s/300s profile can finish independently. Snapshot
and C32 detached controllers remain preserved. Do not replay any original
profile or clean productive work merely because local access failed. Current
cluster state/cleanup require fresh observation after recovery.

KVCR's actual6406-token prefix and4224-token geometry passed, but its first
request was rejected before generation. A separate debug frontend confirmed
the pinned source worker was not in the admitted worker set. Retained model
cards differ in six ancillary docs/images which participate in the runtime's
compatibility checksum. Read-only native checksum/current-assets/admission
confirmation is prepared; no checksum identity bypass or final peer request
has been performed. All failed captures remain intact.

## Current checkpoint, 1:20 Pacific

VPN access recovered after the interruption described above; there is no pending
VPN question. Root remains the sole live/network executor and uses sandbox
escalation for network access. Historical interruption and failure receipts
remain unchanged.

- Both original P/D arms are independently accepted and scoped GPU cleanup
  passed. Aggregate/P-D throughput was **174.75 / 174.36 output tokens/s**, with
  **313 / 312 successful records**, zero errors/cancellations/overflows and
  **37.75 GB** transferred without transfer/notification failures. Observed
  tails improved while medians slowed. This is fixed-order N=1 under shared
  resources, not a universal speedup. See [results](disagg/RESULTS.md).
- Snapshot a3's full integrated NVMe presenter, both coding responses,
  independent **9,283-file** audit and sanitized main recording passed. Root's
  final live resource/private-agent/EFS audit and subsequent mirrored local
  lease release also passed. Its separate clocks are **59 s Pod-to-Ready**,
  **64.29 s deletion intent to observed Ready** and **33.89 s agent restore**.
  Final receipts: `results/workshop-snapshot-a3-root-audit-20261105-a2/`.
- C32's original terminal-a2 collection verified **883 files / 48 frozen source
  files** and independently accepted the completed two-RR/two-KV pair. The
  one-RR cell is rejected for a liveness restart during mandatory warmup; no
  scale-out ratio and no replay. Independent scoped cleanup and the root's
  mirrored lease release passed. Receipts:
  `results/workshop-routing-c32-collection-terminal-20261105-a2/`.
- KVCR a5's failed first HTTP request remains failed. Read-only inventories and
  supported B/frontend replacement restored strict admission while preserving
  A. Fresh a6 child binding and token/page preflight passed: **6,406 common
  tokens**, 6,426/6,427-token prompts, **4,224-token page**, 8,192-token context.
  Actual a6 capture and independent acceptance **passed**: 48 source hashes,
  417 evidence hashes, six transferred blocks / 103,809,024 bytes and 4,224
  external/cached tokens across nodes. [Actual main recording](../../demos/transcripts/live/07-kvcr/20261105-a6/main.txt)
  and `results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json`
  retain the proof. Scoped cleanup passed at **21:19:03 UTC**, with zero owned
  Pods/claims/DGD and absent owning parent lease; original failed captures and
  fresh child/recording bytes are unchanged. Preparation/startup predates
  capture. Projected source/target steps were 224.8 / 216.0 seconds, while HTTP
  to DONE was 19.55 / 19.43 seconds; this proves controlled peer reuse on the
  pinned experimental stack, not automatic routing, workload speedup or
  production readiness.
- Shadow descriptor-writer a2's local sandbox denial occurred before resource
  creation; intent and failed attempt are preserved. Fresh same-code a3 passed
  runtime checks, exact-pair CUDA and health gates and created its deployment
  at 21:06:04 UTC, DGD UID `f1f6dfa0-7898-426a-89c2-af1dc17a8ae5`.
  Main exited 1 at **21:11:50 UTC** after weight loading and restarted; the
  serving gate failed at 21:11:58. Automatic UID-matched owned DGD deletion
  returned success. Sessions 27737 (deployment) and 32235 (verification) are
  terminal. Scoped cleanup passed at **21:16:08 UTC**; post-failure health found
  no new Xids/conditions and the same driver/boot identity. The original log
  disappeared with Pod deletion, so crash cause remains unknown. A fresh
  diagnostic with continuous/previous-log capture is being prepared, without
  an inferred runtime fix. No serving, descriptor, reader or recovery
  qualification is claimed from a3. The earlier cleaned writer-only a5 result
  remains valid; reader/promotion/replenishment remain separately gated.
- The public take-home cached baseline remains live-qualified and cleaned on
  official unmodified development nightly, DRA/H100, explicit cache UID,
  strict X.Y.Z compatibility version and corrected Service selector. Fresh
  network download, device-plugin serving and advanced compositions remain
  separate. Receipt:
  `reports/receipts/2026-11-05-take-home-public-baseline.json`.
- Fresh inventory at **21:19:33 UTC / 1:19:33 p.m. Pacific** found **24 advertised
  / zero allocated GPUs and no issues** after component closeouts and failed
  Shadow a3 cleanup. The next diagnostic had not been prepared/launched;
  CPU/cache/artifacts are intentionally retained. This is a timestamp-specific
  clean interval. The 21:00:43 UTC / four-KVCR-GPU observation is historical.
  Latest full local suite is now **513/513** in **32.097 s** with permitted
  loopback access, `results/workshop-resumed-local-suite-20261105-a3.log`.
  Its same-code a2 attempt preserves five sandbox `PermissionError` failures
  binding local HTTP listeners; earlier a1's 477/477 remains historical.
  These tests do not substitute for live qualification or qualify subsequent
  edits by implication. This documentation pass did not run tests.

The full-composition controller's pre-fault identity checks and negative tests
are independently source-reviewed; the author reports 12 focused tests passed,
without a rerun by this reviewer. Continue the fresh Shadow diagnostic and
actual writer-descriptor gate before any full reader/recovery experiment.
Completed KVCR, Snapshot, P/D and C32 collection/audit/cleanup steps are no
longer pending. Presentation pacing and separate qualification gates remain
visible in [REVIEW.md](REVIEW.md).

## 2026-11-05T21:28:05.884596+00:00 — final component closeouts and diagnostic continuation

Snapshot final agent/private-EFS/resource audit and mirrored lease closeout passed. KVCR a6 peer reuse, immutable recording and independent evidence/cleanup audits passed; 103,809,024 reported transfer bytes and 4,224 cached tokens. The fresh 21:19:33Z inventory showed zero allocated GPUs and no issues. Combined local suite now 530/530 passed in 35.010 s (`workshop-resumed-local-suite-20261105-a4.log`). Shadow a3 exited 1 after loading weights; no new Xids, owned cleanup passed, original exception unavailable. A4 adds current/previous/continuous log retention with unchanged runtime helper/profile. Actual image top-level and nested runner CPU reads passed without CUDA; underscore-only `_quant_method` forwarding rules out the public alias/count hypothesis. Exact reserved CUDA pair passed; fresh health complete; starting one bounded diagnostic model load. These writer-only gates do not qualify a reader or fault-test result, no shared infrastructure changes, commits or external submissions.

## 2026-11-05T21:38:02.422957+00:00 — Shadow original exception retained

A4 failed on both ranks at 21:33:46Z in the experimental exporter `tensor_layout`: `ValueError: Unexpected inference parameter dtype/gradient contract.` The exact parameter/dtype/flag is not present in that exception. Supplemental main/GMS followers with `--request-timeout=0` retained the traceback after built-in followers inherited a 30-second client deadline. The frozen candidate stayed unchanged. No successful writer publication/descriptor/reader is claimed. Post-failure GPU/node audit found no new Xids/conditions and the same driver/boot. Owned DGD/Pods/claims/DeviceClass cleanup passed 21:37:16Z. Preparing exact parameter metadata inventory rather than relaxing the guard blindly.

## 2026-11-05T23:20:38.176098+00:00 — first actual full reader import and reconstruction gap

Full-a1 passed CPU/source/admission, exact CUDA and fresh health and deployed. Both standby ranks acquired committed RO weights at 23:12:56Z. At 23:13:06Z the reader failed in restore_reader_runtime → generic ModelOpt get_fused_moe_quant_config, which read removed RoutedExperts.w13_input_scale. No fault was injected. A distinct local TLS observer timeout was recorded earlier; fresh SSH succeeded and restarting only this workspace tunnel restored /readyz. Original errors remain separate. Canonical cleanup passed; post-failure audit has no new Xids/conditions and same driver/boot. Preparing a source-reviewed reader-only Humming builder patch and real-source CPU test, preserving accepted writer/schema v4 instead of repeating a passing writer test.

### 3:35 p.m. Pacific — current review reconciled

Updated REVIEW.md and STATUS.json to replace stale writer-failure wording with accepted a6 writer/cleanup, separate full-a1 callback failure and passed v5 CPU/independent review (11 tests, 80 actual roles). Fresh read-only placement at 23:34:26 UTC found 24 advertised/zero allocated GPUs, no issues and no local GPU leases. Fresh full candidate and durable full-only capture supervisor remain in preparation; no new GPU deployment or fault. Original failed and accepted evidence preserved.

### 3:38 p.m. Pacific — fresh full-a2 preflight passed

Full-a2 binds accepted writer basis and reader-only v5 repair, 17 inputs, 16 writer receipts, 134 contracts and 27 held critical sources (spec SHA4bb21f9a4425e7edfd669375ff6a5b2c6f86b62378e0da6d5ce416d4e6fbbb60). Root prepare, exact GPU4/5 CUDA arithmetic and external fresh health passed; no new Xids, driver/boot/conditions unchanged. Full deployment and fault not started; independent durable supervisor review pending. Scoped root reservation retained.

### 3:43 p.m. Pacific — durable full-a2 launched; combined tests passed

Reviewed transport/controller13tests accepted; package372files payload9fbd88e3a346c222ff0c48604addb0fc0c8d976c3bef9e36df89093bd8ccf286 plan ceeb2359815fdab477bd0253ff32e0b419939a8c18e67f6c3d299397fdf57c45. Existing CPU image and read-only API preflight passed. Controller30017f022c300a74ffcfa4a2de4c33a2ccdb6690d0ac73bba1d909336f734a74 started23:42:29Z, deploy passed, waiting active/parked+coding gates. No fault qualified. Final combined local suite631/631passed56.804s (a7 log). Root original a2state remains CPU-prepared; local reservation held for eventual independent closeout.

### 3:58–4:04 p.m. Pacific — failed full-a2 closed; persistent MX requested

Independent failure audit rehashed1221files/372payloadentries/27critical/134runtimecontracts/16writerreceipts. Both ranks completed v5RO reconstruction (~7.42/7.55s,36.79GiB each) and privateworkspace checks; later DeepGEMM eligibility probe invokes generic ModelOpt callback and lacksw13_input_scale. No guarded fault/capture occurred. Fresh rootlive health/resource checks passed, originalpreparedstate unchanged, exactrootmirror released23:58:44Z. Preserve failedfull-a2 unchanged.

User requested persistentModelExpressdevelopmentserver. Actualpinned-imageCPUprobe read14vLLM/MXsourcefiles+versions withoutTorch/GPU (results/workshop-shadow-mx-runtime-sources-20261105-a2). Initiala1lackedpreparedpullsecretname and failed before anyPodapply; preserved separately. ExistingGMSabsoluteEFScache means serveralonecouldbe no-op. PlanownedCPUcache+per-candidatelocalstaging, strictrevision; nativeGMS-MXcomposition separatelyqualified. Additionalactualreplace_parameter source-onlyprobe inprogress for nextreaderfix. No commits/pushes/externalmessages/sharedplatformchanges.

### 4:25–4:42 p.m. Pacific — persistent CPU/RAM cache preflight and layout findings

RAMseed/render reviewed (10tests), ownednamespace/PVC/pullsecret and admissionpassed. Firstpersistent a2seed stoppedbeforecopy because actual source has centralizedhub/blobs/<prefix>/<64key> links outsideperrepo. Originalfatal preserved, scopedcleanup passed. Narrowv2/a3 acceptedexactCASlayoutwith unchangeddigestchecks, newrender/admission/review passed. A3copiedthree smallGitmetadatafiles thenstopped; originalfirsttracegoneafterinitretries, repeatedfreshnessfailures retained. Rootattemptownedgeneration0kubeletlog returnedNotFound. Ownedread-only ephemeralforensics capturedpartialcopy4 andsourcehashes withoutmodel/GPU load. FreshpublicHFtree at EXPLICITpinned8a115b9... returned114entries: PNGactualSHA06abb...matcheslfs.oid; CASkey07d9...matchesxetHash, notfileSHA orBLAKE3. FrozenHFtree+receipt retained; newseedmustbind authoritative LFS/Git checksums anddistinguish Xetaddresskeys, plusdurablefirstfailure.json. No corruptionassertion or reconstructedoriginaltrace; no weightpayload copiedyet. A3ownedcleanup inprogress; alloriginalartifacts retained, zeroGPUrequests throughout.

### 5:18–5:34 p.m. Pacific — host-only fix and cache-enabled full-a4

Closed full-a3 after1263-file independent audit and fresh live namespace/claim/DGD/DC absence plusGPUhealth; exactrootmirror released01:18:15Z. Readerhadactuallywarmed/parked; onlyKubeletready/startedsettling causedfalseidentityguard. Newhosthelpers require all3healthyprobes andstableUID/containerID/restarts, retainstrictGMS/pairchecks andpersistnumberedcodingpayloads+before/after beforelaterguards.34focusedtests+independentreviewpassed; nativev6backend/CPUunchanged.

Persistentserverseed andnativecrossnode fullCPUstage independentlyaccepted (114files,88weights75,010,188,240B,117.852848s,noCUDA). CompletedclientJob/bootstrapremoved; producerUIDe32f.../containerd7ca... unchangedandReady, server/Redisremainrunning. Self-containedQf543e915... pinnedactualCPUbootstrap/Pod/producer/sourcebytes. Freshoptionalfull-a4 froze20inputs/32criticals withQ; CPU/cache/source/admissionprepare,exactGPUarithmetic,freshhealthand393-filecontrollerpackagepassed. Combinedlocalsuite717/717passed113.960s. Firstbuildwrapperhadwronghealthfilename andfailedbeforepackagedirectory; correctedbuildreadexactroot-audit path, preserveda1errorlog. RemoteCPUimage/clientpreflightpassed; one-timelaunchinprogress. No commit/push/upstreamsubmission/sharedplatformchange.

### 5:44–5:50 p.m. Pacific — full-a4 startup passed; controller Helm packaging gap

Fresh live status found controller terminal exit 1 after successful actual GPU-worker RAM staging and active/parked readiness with three retained coding responses. Original main-panel capture fails before fault in shadow_failover_tests.preflight: FileNotFoundError /opt/homebrew/bin/helm inside the Linux CPU controller. Post-failure health and scoped remote cleanup passed at 01:44:13Z; remote mirror released, root mirror retained pending independent closeout. Fresh immutable collection verified 1,978 files; original failed transcript preserved. Live inventory at 01:47:12Z reports 24 advertised/zero allocated GPUs/no issues. Independent audit and read-only host-packaging review assigned to existing internal agents; all candidate/transport/native sources remain held until root closeout. Persistent CPU cache remains retained. No recovery/SLO or startup-speedup claim.

### November 5, 2026, 7:22 PM Pacific — user-requested GitLab checkpoint

User explicitly authorized committing/pushing all local repository work. Quiesced internal source edits; no fresh GPU run started. Fetched GitLab and fast-forwarded main to preserve its new slide-deck commit5801f74. Complete current local regression passed734/734 in109.216s (results/workshop-prepush-local-suite-20261105-a1.log);109JSON/YAML files parsed, no credential payloads found in changed/nonignored files. FullHelmtransport fix source-reviewed, generatedCPU/fullfault run still pending. Rawresults/localcredentials remain ignored; shareablecaptures/receipts/reports/code/tests included. PersistentMXcache/Redis retained at userrequest.
