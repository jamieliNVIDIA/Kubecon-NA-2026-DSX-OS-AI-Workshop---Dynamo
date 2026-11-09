# Independent review of overnight demos

Reviewed November 4–5, 2026 Pacific. Read-only source review; no cluster action,
source-code edit, commit, push or upstream submission was performed. This note
records findings and their disposition as sources changed during review.

## Review disposition

The reviewed findings below are resolved in the current source. Fourteen focused
allocation/MX/capture checks passed during the follow-up review. No additional
open defect was found in those fixes. Cluster access subsequently returned;
the closing evidence review below supersedes that earlier transport-held
checkpoint without upgrading incomplete feature attempts to qualified results.

## Findings resolved after the first review

### P2 — Primed DGD Snapshot capture had incorrect startup provenance

At first review, `scripts/capture_workshop_demo.py:372–373` classified pre-existing
startup only through `apply_started_at`, `arms`, `restores` or `cases` in
`demo.json`. The new DGD Snapshot presenter stores its successful offstage prime
as `initial_identity` (`scripts/workshop_snapshot_dgd_demo.py:203–206`), with the
DGD submission timestamp in `state.json`. It does not set any of those four
tested keys.

The required prime-then-capture flow therefore produces
`preexisting_startup=false` and the statement “Run had no startup record when
capture began,” despite already having captured/staged an engine and restored
the initial serving worker offstage. This affects the capture's provenance
description, not the separately recorded onstage replacement clocks.

**Resolved:** the recorder now recognizes `initial_identity`. The new
`test_offstage_snapshot_prime_is_labeled_preexisting_startup` regression passed
and verifies the second capture retains the pre-existing-startup description.
This metadata correction does not claim a new GPU startup or replacement run.

### P2 — Intro claim drift and intended physical allocation were not checked

This was the coordinator's existing finding, independently confirmed rather
than a newly discovered upstream defect. The original code froze only the DGD
hash and checked only the observed GPU count.

**Resolved:** `scripts/workshop_demo.py` now records `claim_sha256` and calls
`check_manifests()` before preparation, application and projection. Older runs
without that hash are refused for new execution; their original runners remain
available and cleanup does not silently adopt a new hash. The live wait path
resolves actual claims against ResourceSlices through
`scripts/workshop_demo_allocation.py:79–109`, checks the intended node and UUIDs,
and saves `allocated-gpus.json`. MX updates its target claim hash and retains the
per-arm allocation receipt; its expected nodes follow the frozen assignment.

The new negative tests passed:

- `test_gpu_claim_drift_is_rejected_before_preparation` changes the count in the
  claim bytes and proves rejection before apply.
- `test_same_gpu_count_cannot_qualify_wrong_physical_devices` retains two GPUs
  but substitutes a physical UUID, then separately changes the worker node;
  both cases are rejected.

I also ran the new verifier against the retained **actual** 22:46 Pacific
intro Pod, claim and ResourceSlices from the coordinator's `audit-2250` directory.
It accepted the intended cp-0124 pair. This is offline verification of saved
Kubernetes objects, not a current cluster-state audit or live inference proof.

## Findings addressed during this review

### Snapshot resumed steps previously ended at 3 rather than 4

The interrupted-replacement branch resumed `STEPS[1:]` through the shared
enumerator starting at one. A successful request then left `demo.json.step=3`,
while the recorder required four. The current presenter now uses a local
`run_steps(..., start=2)` at
`scripts/workshop_snapshot_dgd_demo.py:427–442`.

I exercised the pending-replacement-intent branch locally with a temporary
rehearsal run and no API calls. It ended at step four with a response file and
passed the recorder's completion check. The separate known simulated-readiness
omission is also corrected in the current source at lines 249–250. These are
presenter/rehearsal fixes, not upstream Snapshot runtime findings.

### KVCR offstage preparation was not resumable despite broad resume wording

The reused baseline preparation deliberately requires a fresh run. In addition,
KVCR's immutable source ConfigMap used unconditional creation before later
CPU/native/admission gates. A failure after those side effects could not simply
resume `prime` under the same run.

The author confirmed the intended contract and added the explicit pre-mutation
guard at `scripts/workshop_kvcr_demo.py:267–270`, with matching
`demos/07-kvcr/README.md:73–81` instructions. Incomplete offstage preparation
requires preserved evidence, scoped cleanup and a fresh run; a completed prime
and completed onstage stages can resume without replaying their HTTP requests.
The author reports 11 focused tests passing, including this guard. I did not
rerun the live preparation or independently execute that full test suite.

## Checks and limits

- Reviewed allocation validation/freeze, actual manifest pinning, recorder mode
  separation/evidence selection, DGD Snapshot identity/delete/request gates,
  KVCR peer proof and explicit request placement, Shadow pair/fault verifier,
  and portable take-home rendering/download/smoke paths.
- Verified that the generated take-home cache-reference suffix evaluates to one
  newline character in Python; it is not a literal backslash-plus-`n` bug.
- The recorder separates historical routing/metrics walkthroughs from live
  measurements and simulated rehearsal captures. Its KVCR generator requires
  positive finite transfers plus external-cache tokens, and the Shadow verifier
  retains the existing exact-once fault and unchanged-Pod/GMS invariants.
- Read `results/overnight-local-suite-a2.log`: 288 tests ran with one failure,
  the known Snapshot rehearsal readiness omission. That log predates the fixes
  above and is not a verdict on the current source. Parent owns the fresh full
  regression run and final report.
- Follow-up review independently ran 14 tests: the allocation suite, MX suite
  and offstage Snapshot capture-provenance regression, all passing. It also
  checked the actual saved-intro allocation objects as described above.
- Shared SSH/VPN reachability failed before live qualifications completed.
  No source review, rehearsal or admission result here establishes live serving,
  promotion, transfer, performance, cleanup or production readiness.
- No additional upstream bug is inferred from these presenter lifecycle issues.
  Runtime candidates and existing upstream overlap remain in
  [UPSTREAM-CANDIDATES.md](UPSTREAM-CANDIDATES.md).

## Closing review — November 5 after the 10:20 a.m. audit

This follow-up inspected saved receipts, capture labels, reports and the final
test log only. No new tests, network operations, inference, faults or cleanup
were performed by the reviewer.

| Item | Evidence label supported at closeout | Limit |
| --- | --- | --- |
| Intro retake | `20261105-overnight-a2/capture.json` is `live_passed`, exit 0 | Same retained startup/run after observation recovery; do not invent a new cold-start measurement. |
| AgentX routing | Three C16 cells independently accepted; fresh recorded presenter profile | N=1, fixed order, differing realized request mixes, shared CPU/storage/network. No capacity knee or C32 profile. |
| Concurrent request continuity | Migration enabled completes 4/4 fault-batch streams; disabled completes 2/4; both baselines complete 4/4 | Four controlled HTTP clients, not AgentX session replay or an SLO/capacity result. Two faults and 16 posts total, zero client retries. |
| KVCR presenter | Fresh prime passed; source returned READY with 3,247 prompt tokens; source commit gate stopped the demo | Effective page is 4,224 tokens; B was not sent a request, so no presenter peer-transfer qualification. Capture remains `failed`. |
| Integrated Snapshot presenter | Earlier artifact reached Ready; held source Job expired; a2 optional lifetime extension was rejected at immutable-spec dry-run | No new presenter restore, replacement or coding-inference qualification. Preserve the separately qualified earlier component evidence. |
| Fresh MX attempt | Source startup observed; native observer interrupted; peer absent | No fresh peer-weight or matched comparison result. Historical qualified recordings keep their earlier scope. |
| Shadow writer a4 | CPU/cache/source preflight and local candidate checks only | No a4 GPU deployment or promotion. Earlier actual writer/reader failures remain unresolved; a missing MoE lock path is documented. |
| Take-home bundle | All 14 sequential client/server admission checks in a2 exit 0 | No resources materialized, and no image pull, download, CPU resolver execution, GPU scheduling or serving qualification follows from admission. |

The migration result receipt at
`reports/receipts/2026-11-05-migration-load.json` records separate response-correlated
retry proof for both affected enabled streams, each retaining 32 output tokens.
Its 0.588/0.587-second largest adjacent content gaps are correctly labeled as
whole-response observations, not exact handoff times. The receipt records
92 scientific files and independent cleanup verification; the historical console
overwrite/recovery is disclosed rather than presented as a new run.

The saved final audit at
`results/overnight-20261105-final-audit-postcleanup-a1/audit.json`, observed
**10:20:06 a.m. Pacific**, shows 24 advertised GPUs, **zero allocated GPUs**,
empty ResourceClaims and GPU-Pod lists, zero DGDs, zero requested EFA resources
and no audit issues. This is a resource-allocation/cleanup observation, not a
GPU-health or feature-qualification claim, and does not assert that every
non-GPU Pod or retained namespace/cache was removed.

`results/overnight-local-suite-final-20261105-a2.log` records **350 tests, OK**.
The preceding final-suite attempt's stale capture-test path was corrected in a
test only. This reviewer read the successful log and did not rerun the suite.

During review, TAKEHOME.md still contained its old “a2 has not run” checkpoint
and BASELINE-MX.md's closing table still listed independent cleanup review as
pending. Parent was notified to reconcile those current summaries with the
newer receipts. Preserve immutable historical receipts and mark later closeout
explicitly; do not relabel interrupted feature attempts as successful.
