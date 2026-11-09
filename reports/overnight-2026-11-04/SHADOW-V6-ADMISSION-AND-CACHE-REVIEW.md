# Independent v6 admission and optional cache review

Source-only review on 2026-11-06 UTC. **No remaining source-review blocker** in
the reviewed admission/cache implementation. This does not qualify RAM
population, native full-file client streaming or a fresh GPU candidate. No
network, cluster, GPU or candidate-freeze actions were performed by this
reviewer. Old source/evidence and approved seed renders remain preserved.

## V6 actual CPU admission

Six independent tests use temporary copies of the actual accepted v6 CPU
result, intent, canonical check, seven-source packet and accepted a6 basis.
The positive gate remains read-only and binds all 80 unique roles and all three
SwiGLU cases. Native source, helper, packet/program/intent, case coverage,
ordinary-state/config/alias flags, warmup behavior and exact image checks are
required before any candidate Run is created.

Two concrete findings were fixed during review:

- The canonical check previously used Python equality, allowing numeric types
  such as `0`/`False`, `80.0`/`80` and `1`/`True` to compare equal. The canonical
  payload now matches the result through strict canonical JSON, stripping only
  `status` and `updated_at`; a nonempty string timestamp is required.
- Image admission previously accepted arbitrary strings ending in the expected
  digest. It now requires the exact locked runtime image identity.

All six actual-evidence tests pass, including malformed canonical types,
malformed image suffixes, changed native source hashes, missing/duplicate
cases/checks, changed packet/program/intent, disabled/altered native warmup and
failure before candidate creation. The actual v6 CPU run was separately audited
in `SHADOW-READER-V6-REVIEW.md`; these tests do not execute it again.

## Optional cache contract

The optional contract contains exactly:

1. `dev-cache-qualification.json`
2. `dev-cache-bootstrap.json`
3. `dev-cache-receipt.json`

The explicit `full-spec.dev_cache` binding names the candidate, hashes all three
files and pins `workshop_mx_dev_cache.py` plus `mx_dev_cache_stage.py`. Without
that binding, optional cache inputs are rejected. The transport must retain the
strict **17-file default input whitelist** and allow only these three additions
when this static binding validates; transport adaptation is a separate gate.

The qualification embeds the CPU plan, actual completed CPU Pod, actual
immutable bootstrap ConfigMap and full stream receipt. The review required and
independently tested these safeguards:

- Exactly one completed CPU stage container, no init/extra containers, no GPU
  claims/resources, no shared source/PVC/hostPath access and exact private
  volume, command, argument, environment and resource wiring.
- Actual immutable bootstrap data/source/spec matching the renderer, plus exact
  pinned image identity and integer zero exit/restart metadata.
- A direct qualified producer Pod IP endpoint, bound to the same Ready server
  Pod/container/seed generation. DNS Service routing is not used as proof of
  producer identity.
- Complete semantic revalidation of the embedded CPU model/revision/address,
  source Pod UID, seed/spec hashes, integer totals, full per-file inventory and
  CUDA-false result, even when a summary hash is recomputed.
- Full native file manifest matching, per-file sizes/hashes, exact returned
  commit, complete index coverage and no publication on missing/duplicate,
  overflowing, wrong-commit or CUDA-initializing streams.

The graph patch preserves engine args/env, GPU allocation and native GMS loader.
It adds only bounded CPU staging into a 96 GiB private RAM cache, read-only to
engines, and explicit memory reservations. The validator reverses that narrow
delta and regenerates the graph, bootstrap and receipt with strict canonical
comparison; resealed modifications to source, memory, GPU fields, arguments,
environment or mount permissions are rejected. A stable short stage ID is
derived from the full candidate ID.

## Composed lifecycle

Optional qualification validation precedes creation of a candidate Run. During
live orchestration, a current producer check precedes GPU intent/deployment.
The prepared bootstrap must retain its UID, immutable flag, ownership and data;
it is never silently recreated if it disappears. The sole successful target
init generation must produce a full all-file receipt at the exact HF_HOME,
with exact image/int metadata and unchanged producer generation. Engine/GMS
readiness observations wait until that staging proof passes.

On failure, init logs are preserved before the owned graph is stopped. Cleanup
waits for owned Pods and claims, then removes the owned bootstrap, then releases
the parent reservation. Failure to prove ownership or workload removal retains
the remaining resources/reservation for root investigation.

## Validation and limits

All **22 focused cache tests** passed together: six stage tests, nine independent
negative tests and seven composed lifecycle/static tests. Separately, the six
actual v6 admission tests passed in 28.326 seconds. No root-owned live receipt
or approved seed input was edited. Small-data stream doubles are unit tests;
they are not native RPC or performance measurements.

Reviewed source SHA-256 values:

| File | SHA-256 |
| --- | --- |
| Cache contract | `33dffab52d2b1f823de139dc1d56ad07bf7fdf26a6f1f4a3cd4736c55b378cf3` |
| Stage helper | `3df3c2e86c1c78f261e27b9b7c4ef62432051de83eda7bb300e94ef432aca95f` |
| Composed controller | `5d84e7bdaffd73b6ef81924bb4006bd1e341fb64a2030b73b992d79664c23a65` |
| Independent cache tests | `fbd5a1d5a074a53b38b7e6e25152bbedd9eb449c72c7548ff69a27cfd527a9c3` |
| Independent admission tests | `577ea38aa06358eece585445f22770c4cc6e9f38785a5df6beeaf685de2fc042` |

Actual server seed completion, full native client qualification, the optional
transport whitelist adaptation and a fresh full GPU candidate remain separate
gates. No GMS/MX/P2P integration, speedup, parked reader, recovery or SLO claim
follows from this source review.

## Final source-provenance extension and closeout

The earlier 22-test snapshot above is retained as review history. The final
cache contract additionally revalidates the embedded raw seed receipt and
exact HF tree: each `source_blob_id` must be a string declared by that file's
Git/LFS/Xet source record, and its data-hash kind must match the authoritative
content identity. Storage keys and complete-file data hashes are separate.
The review found that `row.get('xetHash')` could implicitly put `None` in the
allowed storage-key set for a native Git file. That edge is now fixed;
resealed null/unknown keys, changed hash kinds, raw seed edits and changed
tree provenance all reject.

All **23 focused cache tests pass** together: six stage, ten independent and
seven composed tests. The added independent case exercises that provenance
extension with freshly recomputed summary hashes. Final reviewed SHA-256:

| File | SHA-256 |
| --- | --- |
| Cache contract | `af47bc71086d6d8ad3bdbbf50b229ca60535e11cfe2d203013c3d1d869ec9b53` |
| Stage helper | `3df3c2e86c1c78f261e27b9b7c4ef62432051de83eda7bb300e94ef432aca95f` |
| Composed controller | `5d84e7bdaffd73b6ef81924bb4006bd1e341fb64a2030b73b992d79664c23a65` |
| Independent cache tests | `2ff2aa5f8b221ad17c4056a7ab51d6df0e9dfdac2e24b9093bd5ae914d24d07f` |

This optional helper changed only after root released the local build-to-launch
hold for default full-a3. The already launched default candidate has no cache
binding or cache critical sources; its frozen payload remains the historical
executed source of truth. Its 30 critical sources and transport stay held
through cleanup. A later audit must distinguish this permitted noncritical
local drift from the frozen remote payload rather than comparing every local
working source indiscriminately. Actual seed/client/full execution acceptance
still requires independent evidence review.

## Actual optional cache evidence follow-up

The independent seed and native CPU client gates have since passed, recorded
in the final two sections of `MX-CPU-CAPABILITY-AND-RAM-SEED-REVIEW.md` and the
fresh result directories it names. Root's complete qualification SHA-256 is
`f543e915ecd64759fed478fa0456915f55d804bd67047788ac4f547ec4102667` and matches
exact actual evidence canonically. This closes the previously pending CPU
population/client qualification gates only. The default full-a3 candidate
remains separate and has no cache dependency. No optional GPU candidate or
GMS-MX/P2P composition is accepted by these CPU results.
