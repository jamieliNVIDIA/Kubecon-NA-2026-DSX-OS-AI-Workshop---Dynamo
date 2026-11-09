# Durable full Shadow demonstration

Current canonical admission requires reader revision
`workshop-humming-reader-v6-optional-input-state`, retaining writer/schema v4.
Full-a2 below is a closed historical v5 attempt: it failed in later native
warmup, injected no fault, and its 1,221-file evidence, scoped cleanup and root
reservation release were independently accepted. Do not re-execute that run.
A new full candidate must be frozen separately after the optional cache gates
below pass; none is created by this transport change.

This full-specific adapter leaves the accepted writer-only transport and all
old attempts unchanged. Root performs preparation, exact-pair CUDA and fresh
health locally. One detached CPU container then deploys the frozen full graph,
waits for active/parked engines and three coding responses, records exactly one
guarded fault, obtains external post-fault health, finalizes that same recording
and performs scoped cleanup. Failed/uncertain phases are preserved, not retried.

Implementation:

- `scripts/workshop_shadow_full_remote.py`
- `scripts/workshop_shadow_full_remote_controller.py`
- `tests/test_workshop_shadow_full_remote.py`

The frozen full-a2 candidate uses profile/schema v4 and accepted writer/schema
v4, with explicit reader adapter revision
`workshop-humming-reader-v5-native-config-builder`. Its 17 safe frozen inputs
include the six reader-delta/actual-CPU proof files. The adapter verifies all
critical source snapshots, installed-source contracts, writer-basis receipts,
model/config pins and existing scoped lease without constructing a Full `Run`.

Independent review closed with **13 passing offline tests** (five implementation
tests and eight reviewer tests). The review tightened exact node/GPU/integer
fault-count admission, regular lease/ancestor checks, nested accepted-writer
immutability, pending receipt/timeline/before-state/health/evidence seals and
unchanged pending/final provenance. It also verifies uncertain launches do not
replay and a source-guard failure retains ownership when cleanup safely refuses.
Generated bootstrap/status/collector syntax and whitespace checks pass.

Reviewed frozen sources:

- Transport SHA-256:
  `91168fb258ae48166be5f4b777ee675b2b1f29d8dde3b1ef02ed19c64a1b9dcf`.
- Controller SHA-256:
  `eb7a4e4479b805c0f1a92b9e3ec13b6ef06fd90d200182fdaaf0c30305d589f3`.

Read-only admission of actual full-a2 passed against its 17 inputs, 27 critical
sources, runtime contracts, accepted writer basis, exact existing lease and four
fresh health files. Root accepted the review and began packaging once. All
transport/capture/candidate source bytes remain held unchanged through execution,
collection and cleanup. Offline tests/admission are not a live demo result;
append actual terminal evidence separately.

## Historical full-a2 handoff

These commands record the closed a2 launch. Use the same CLI with the next
explicitly reviewed fresh run/health paths after its freeze; preserve the a2
package and source snapshots unchanged.

```bash
.local/venv/bin/python -B scripts/workshop_shadow_full_remote.py build \
  --run results/overnight-shadow-super-vl-20261105-full-a2 \
  --health-before results/workshop-shadow-full-a2-start-health-20261105-a1/snapshot-gpu-health-1793921889251129000.json \
  --health-baseline results/workshop-shadow-full-a2-preflight-inventory-20261105-a1

.local/venv/bin/python -B scripts/workshop_shadow_full_remote.py preflight \
  --run results/overnight-shadow-super-vl-20261105-full-a2

.local/venv/bin/python -B scripts/workshop_shadow_full_remote.py launch \
  --run results/overnight-shadow-super-vl-20261105-full-a2

.local/venv/bin/python -B scripts/workshop_shadow_full_remote.py status \
  --run results/overnight-shadow-super-vl-20261105-full-a2
```

Root's existing Full owner is borrowed exactly:
`.local/dynamo-ft-r610-b06a9a1f-demo-shadow.gpu-lease/owner.json`.
Build reads that regular file and validates owner, run, node and UUIDs. It does
not create, replace or release the local lease. The remote bootstrap mirrors the
same record at the same logical path. Canonical Full cleanup removes that
remote mirror only after its owned workloads/claims/DeviceClass are gone; root's
separate local lease stays held until independent live closeout.

All adapter artifacts live in the sibling
`results/overnight-shadow-super-vl-20261105-full-a2-remote-control/`:
package/launch receipts, exact reused CPU-image provenance, phase logs,
heartbeats, fresh health and private recording. No controller journal, image
receipt or health `Run` is created inside the Full run.

The image is the existing owned curl-enabled image
`sha256:f12b417250bc7d8e150e929114e60762e86f25146ea1f9289990a0fc7b5e9872`.
It reuses the proven Snapshot CPU limits/UID/capability restrictions, host
networking, direct jump-host API access and read-only kubectl/kubeconfig/PyYAML
mounts. There is no image build, credential copy, GPU device mount or shared
infrastructure change. Frozen-source imports are actually probed before the
controller starts cluster work.

## Pending recording boundary

Explicit phases are:

1. `workshop_shadow_composed.py deploy`, then `wait --timeout 1500`.
2. Fresh pre-fault health in the sibling control directory.
3. `capture_workshop_demo.py --demo 08-shadow-engine-composed
   --defer-qualification --pre-fault-health <external receipt>`.
4. Verify the exact sealed pending receipt, raw PTY, timeline, before-state,
   health, source and evidence hashes, plus actual promotion/replenishment.
5. Fresh post-fault health in the sibling control directory.
6. Canonical Full `finalize --health-after <external receipt>`.
7. `capture_workshop_demo.py --finalize-pending` on the original attempt.
8. Verify `live_passed` with the identical first-fault PTY/transcript, frozen
   final evidence and the same provenance; perform canonical scoped cleanup.

Between pending capture and finalization, only canonical Full finalization may
append `health-after.json`, the full-qualification receipt and its allowed state
updates. Phase output/health/heartbeats remain outside the Full run. The adapter
never renders a second fault recording to hide a failed capture. Failure stops
qualification, retains its output, attempts fresh external failure health if
needed, and runs scoped cleanup. It never redeploys or repeats the fault.

Outer bounds: deploy 300 s, wait 2,400 s, each health observation 300 s,
pending capture 2,460 s, Full finalize 180 s, pending-recording finalization
300 s and cleanup 600 s. External observer loss does not stop the detached
controller. An uncertain launch must be inspected using the saved intent and
existing named container; it must not be launched again.

## Collection and independent closeout

After the controller exits:

```bash
.local/venv/bin/python -B scripts/workshop_shadow_full_remote.py collect \
  --run results/overnight-shadow-super-vl-20261105-full-a2 \
  --output results/shadow-full-a2-remote-collected-a1
```

The immutable archive has three roots: `run/`, `recording/` and
`recording-private/`. The last contains the entire sibling control directory;
raw capture and its source/evidence snapshots are nested under
`recording-private/private-recording/`. This retains controller and health
provenance without creating extra Full-run files. A failed attempt is collected
with its actual failed/pending status; no success recording is invented.

Collection requires terminal Docker state and validates all archive membership,
regular paths, sizes and hashes before extracting into a fresh directory. The
archive/files are read-only. It does not adopt remote state into the original
local Full run or release any local reservation. If transfer succeeded and
local extraction was interrupted, preserve the archive/transport receipt and
use generic offline extraction into a new directory rather than downloading
again.

Root must independently verify actual capture/health/fault/source hashes and
fresh live absence of the exact owned namespace workloads, claims and
DeviceClass, plus driver/node health continuity. Only then release the exact
unchanged local scoped owner and save a separate closeout receipt. The raw
recording remains private; only reviewed sanitized recording files are eligible
for export. No KV preservation, in-flight stream, node-loss, production or SLO
claim follows from this experimental same-Pod demonstration.

## Optional persistent development cache

The default full input whitelist remains exactly 17 files. A separately
qualified cache may add only:

- `dev-cache-qualification.json`
- `dev-cache-bootstrap.json`
- `dev-cache-receipt.json`

That 20-file branch requires nonempty `full-spec.json.dev_cache` metadata with
schema 1, this exact full candidate ID, all three file-byte SHA-256 values and
the exact `workshop_mx_dev_cache.py` / `mx_dev_cache_stage.py` source-hash mapping.
Both modules must also belong to the frozen critical source closure. All file,
source, basis and config hashes are checked before invoking the composed
controller's read-only `validate_candidate_cache` validator. Its qualification,
producer/model/staging/owned-ConfigMap fences are mandatory; refusal stops
packaging before control artifacts or lease changes. No external cache files
are followed after freeze: the three artifacts are self-contained.

Build includes every approved optional artifact in the payload and immutable
per-phase map, preserving `dev_cache` verbatim in the launch plan. Plan admission
requires it to match the frozen full specification. The default branch does not
accept optional files or arbitrary additional inputs.

The cache is development-only CPU/RAM file staging for the unchanged native GMS
loader. It does not imply GMS-MX P2P composition, a new serving speedup or a
production-ready integration. Root must complete and review the persistent RAM
seed, actual CPU client qualification and current producer identity before the
new full freeze. The composed controller owns applying/deleting only its
candidate bootstrap ConfigMap and rechecking the producer at its GPU boundary;
the full remote adapter does not change that lifecycle or manage the persistent
source server.

Focused transport checks cover qualification-hash substitution after an input
rehash, foreign candidate/schema, missing or changed cache-source fences,
unapproved input expansion, mandatory deep-validator refusal and immutable
preservation. The original pending-capture/finalization/cleanup controller is
unchanged by this extension. All **17 focused transport/review tests pass**
(nine implementation tests plus the original eight reviewer tests). One new
integration test uses the real composed/cache validators and renderer with a
bounded fake CPU stream and real per-file hash receipts: the exact graph/CM/
qualification is accepted, while producer substitution is rejected even after
its file/spec hashes are rebound. This is an offline contract test, not the
actual MX RPC/client qualification or a full GPU demo.

Current v6/cache-aware transport SHA-256:
`b4d68be9f7101547d1adccc3ae89c74913d5a927e525429c403558abe72805b1`.
The full controller remains byte-identical at
`eb7a4e4479b805c0f1a92b9e3ec13b6ef06fd90d200182fdaaf0c30305d589f3`.
No old writer/full package, source snapshot, capture or qualification artifact
was rewritten. Actual RAM seeding, native CPU client/producer qualification,
cache integration review and a fresh full freeze remain root-owned gates.
