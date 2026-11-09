# Stable observer: do not start a duplicate local controller

The detached controller is already running on bastion `ip-172-31-10-102`
(`ubuntu@3.238.63.5`), container `kubecon-workshop-controller-20261103`, started
2026-11-03T23:34:29Z. Physical workspace:
`/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace`.
Inside Docker it retains the exact original logical workspace path.

The local lease is an execution fence owned by `/root/stable_controller`.
Only the delegated remote controller may mutate benchmark GPU resources; do
not launch local batch/cleanup helpers or remove the fence while it is active.
Its fixed sequence completes original C4 r2 (first worker retained), then runs
artifact04, then the routing C1/C4 pairs and owned client cleanup. There is no
automatic restart or replay of completed arms. Parent reviews failures before
any continuation.

Root retrieves read-only progress into
`results/workshop-stable-controller-20261103/REMOTE_STATUS.json`. These are
bounded snapshots; a failed SSH/VPN read does not imply the detached controller
has stopped. Docker logs/inspect and its persisted stage/exit receipts on the
bastion are authoritative for recovery.

## Artifact04 validation and completion

Artifact04 completed and passed the remote driver gates. The read-only snapshot
at 2026-11-04T00:43:33Z records 553.59 / 340.86 / 249.70 s observed readiness
for native / weights / weights plus artifacts, actual both-rank cache-hit
acceptance, and verified MX GPU/claim/graph/coordinator cleanup before routing
C1. Do not rerun MX. The completed MX raw pullback has now been locally verified:
560 selected files, zero hash mismatches. It is preserved under
`results/workshop-mx-pullback-20261103-breakdown/verified/`; parent
`verification.json` records the copy check. STARTUP_BREAKDOWN.md and
`results/workshop-mx-breakdown-20261103-analysis/` provide the read-only raw-log
timing analysis. The full campaign's final combined archive remains separate.

The CPU preflight passed and scientific pins are unchanged. All three target
startup arms use the same stable observer, within artifact04 only. Require
correct model/context 1048576, matching runtime/TP2 H100 and zero restarts,
both peer-weight transfers without fallback, and real compile-cache hits on
TP ranks 0 and 1 with installed-cache selection and no unused/recompile warning.
Transfer alone is insufficient. Preserve any explicit feature-effectiveness
failure; shared transport, cleanup, identity and unknown failures stop work.

After the remote stages finish, retrieve new results byte-for-byte. Preserve
original preflight evidence and immutable source/spec/profile bytes when merging
with local results; the consumed-input bundle is not the complete archive.
An original artifact04 preflight inventory copy is preserved in the stable-
controller result directory. Seal complete local inventories after merging.
Independently verify remote zero GPU Pods/claims/graphs and absent lease, plus
terminal controller/client cleanup proof, before removing the local fence.

Artifact03 is historical interrupted evidence, fully collected/cleaned with
372 verified files. The completed 8k pair04 is unchanged. Do not rerun either.
See STABLE_CONTROLLER_PLAN.md and mx-controller-provenance.json for the reviewed
migration, image/runtime metadata, delegation and bundle hashes.
