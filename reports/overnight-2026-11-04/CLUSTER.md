# Overnight cluster coordination

Started November 4, 2026, 22:34 Pacific. This is an allocation and evidence log,
not a statement that every assigned experiment has completed.

## Authorization and initial inventory

Neal granted the whole cluster for overnight development and asked us to use all
GPUs effectively. The first API attempt failed because the local SSH tunnel was
absent and sandbox networking was denied. An authorized tunnel start succeeded.
The live inventory found all three nodes Ready, 24 H100 GPUs advertised through
GPU DRA, **zero GPU Pods, zero ResourceClaims and zero DGDs**.

Each node has 191 allocatable CPU cores, approximately 1.93 TiB memory and 32
EFA resources. Scalar `nvidia.com/gpu=0` is expected: the GPUs use DRA claims.
Raw initial inventory is retained privately in
`results/overnight-2026-11-04-coordinator/`.

## Nonoverlapping assignments

The exact UUIDs and owners are in [allocations.json](allocations.json). Each row
is a reservation, not an assertion that the GPUs are currently busy.

| Workstream | cp-0124 GPU indexes | cp-0198 GPU indexes | cp-0942 GPU indexes | GPUs |
| --- | --- | --- | --- | ---: |
| Snapshot presenter | 1, 3 | — | — | 2 |
| Shadow/GMS presenter | 4, 5 | — | — | 2 |
| Intro, then MX source/target | 0, 2 | 6, 7 | — | 4 |
| KVCR cross-node peer reuse | — | 4, 5 | 4, 5 | 4 |
| Fresh routing load sweep | — | 0, 2 | 0, 2 | 4 |
| Matched aggregate / P-D | — | 1, 3 | 1, 3 | 4 |
| Request migration under load | 6, 7 | — | 6, 7 | 4 |
| **Total** | **8** | **8** | **8** | **24** |

The MX target was moved from cp-0124 to cp-0198 before deployment to retain its
cross-node EFA contract. Migration takes the vacated cp-0124 pair. Its disabled
and enabled cases run sequentially on four GPUs; the existing presenter primes
both cases on eight GPUs and therefore cannot be used unchanged in this slot.

The Snapshot pair is the exact pair from the qualified artifact profile.
Snapshot uses its existing exclusive Snapshot lease; other agents use distinct
per-workstream leases with explicit node/UUID selectors. A global lease must
never be silently bypassed: parallelism requires proved disjoint assignments.

EFA budgets also matter. P/D keeps eight per node. The existing KVCR Guard
template requests eight for the engine plus one for Guard; that nine-device
total would oversubscribe a node at peak concurrency. KVCR was asked to freeze
a functional test-local budget of at most eight total, preferably four plus
one, and disclose that difference from earlier qualification. The KVCR agent
accepted **four engine + one Guard EFA** per node in its new presenter renderer;
the historical qualification manifests remain unchanged.

At 22:41 Pacific, an independent read-only audit found **4 of 24 GPUs allocated**:
Snapshot's capture helper on cp-0124 GPU 1/3 and Shadow on cp-0124 GPU 4/5.
All exact assignments matched, with no overlap or EFA oversubscription.
Other agents were preparing code, admission and CPU workload caches. Reservation
of all 24 GPUs does not mean all 24 are running at that checkpoint.
The immutable snapshot is
`results/overnight-2026-11-04-coordinator/audit-2247/audit.json` (its folder label
is approximate; use `observed_at`).

The read-only helper `scripts/overnight_cluster_inventory.py --output
results/NEW-SNAPSHOT` records fresh node/slice/claim/Pod/DGD JSON and reports
physical allocation, restarts, readiness and EFA budgets. It refuses to overwrite
a snapshot. Its retained-live-fixture checks accepted the correct four-GPU
placement and rejected deliberately duplicated/cross-slot claims. This audits
placement, not GPU utilization, container-owner identity or demo correctness.

## Existing load sweep: found stopped

The old higher-load sweep was not running. A read-only remote probe found its
Docker controller exited with code 1 at 18:49 Pacific, not OOM-killed. It stopped
during one-worker RR C32 because the post-profile verifier detected a container
restart. Its GPU cleanup receipt passed with zero claims and workers. The remote
lease was absent. Its CPU preparation passed; a C16 result may be recoverable,
but a lone one-worker point is not a routing-policy comparison.

The exact probe is retained at
`results/workshop-load-sweep-observations-20261104/overnight-2235/status.json`.
The old local lease was stale. Its owner JSON was copied byte-for-byte and
hashed before removing only that local lease directory. The closeout receipt is
`results/overnight-2026-11-04-coordinator/old-load-sweep-lease-closeout.json`.
No old campaign input, remote result, controller or evidence was overwritten.
A separate agent owns diagnosis and a fresh immutable retry on the same pairs.

## Measurement limits and operating decisions

- Independent runs may overlap CPU, EFS and network traffic. Record that fact;
  do not describe overnight wall-clock timings as isolated performance results.
- Verify physical GPU allocations before any process fault or replacement.
- Cleanup is limited to each run's proved owned workloads, claims and temporary
  classes. Never remove another workstream's resources or reservations.
- No driver, operator, shared Helm setting, host formatting or shared storage
  configuration changes are authorized by these demo assignments.
- A successful response alone does not prove transfer, cache reuse, recovery
  or migration. Each feature keeps its own evidence gates.

## Open questions and upstream candidates

- Diagnose the C32 worker restart before treating the old sweep as capacity
  evidence. It may be a workload/runtime failure; the verifier correctly failed
  closed and preserved the cleanup result.
- The detached sweep's `LIVE_STATUS.json` still said “profile running” after its
  controller had exited. Prefer terminal controller/exit receipts; propagate
  terminal failure to that user-facing status in a future controller revision.
- Existing demo leases assume exclusive whole-cluster execution. The parent is
  adding an explicit frozen allocation contract for safe parallel rehearsals;
  retain exact UUID validation rather than a generic force/ignore switch.

## Parent integration review

A read-only review of the new allocation helper and shared intro/MX/capture code
found the intended exact UUID CEL selectors and node selectors in executable
manifests. Environment intent is frozen to `allocation.json`, resume rejects a
changed or missing allocation, and tmux children receive the frozen path. The
current coordinator assignment uses the MX runner's existing source/target
nodes. This is a source/placement review, not production inference evidence.

Concrete follow-ups sent to the parent before further captures:

1. Intro froze the DGD hash but not its applied GPU-claim-template hash. Its
   allocation verifier checked two NVIDIA devices rather than the exact intended
   node/UUID pair. Add both the claim-input hash guard and observed exact-device
   check; the independent live audit currently matches the intended pair.
2. MX's immutable capture evidence did not include source/native/peer manifests,
   claim templates, source Service or per-arm records/logs/readiness objects.
   The parent is adding these files before the MX capture; keep actual bytes
   alongside their recorded hashes.
3. The allocation schema allowed source/native/peer targets without `intro`,
   although the MX renderer starts from the intro renderer. Require the shared
   intro target for this explicitly intro/MX-only contract. Arbitrary alternate
   MX node names also need aligned validation against the allocation rather
   than hardcoded historical nodes, or an explicitly constrained schema.

No source-hash-frozen live module was edited by the coordinator. The parent will
sequence source changes around active runs and retain pre/post provenance.

## Transport interruption, beginning 22:49 Pacific

At 22:46, the independent placement audit found **10 of 24 GPUs allocated**,
without overlap or budget issues: Snapshot 2, Shadow 2, intro 2 and migration 4.
The other GPU workstreams were doing CPU/cache preparation.

At approximately 22:49, every local observer began receiving TLS-handshake and
context-deadline failures through `127.0.0.1:16443`. A central check found:

- The local SSH control socket still reported its master PID running.
- A ten-second API `/readyz` request failed with a context deadline.
- A new independent direct SSH connection to the jump host's port 22 also
  timed out after ten seconds.

This establishes an unavailable external transport path. It does **not** prove
an inference failure, cluster API saturation, GPU fault or a specific VPN cause.
All agents were told to preserve workloads, timestamps, leases and failed
observer receipts; do not replay capture/deployment or repeatedly restart the
shared tunnel. The old master is preserved until a fresh external connection
can succeed. The routing controller is remote and may continue independently;
the disaggregation CPU reconstruction was detached in its client Pod and may
also finish despite its local observer stopping.

The take-home admission-only probe passed four device-plugin dry-runs, then hit
the same transport failures and a subprocess timeout. No resources were
materialized. A fresh sequential attempt with per-call timeout receipts is
prepared but unexecuted pending recovery; the partial attempt is retained.
The incident receipt is
`results/overnight-2026-11-04-coordinator/transport-incident-a1.json`.

At 22:48, just before the interruption, a read-only cp-0124 GPU/kernel baseline
showed unchanged node conditions and no new Xids; the latest retained Xids were
from October 22. Driver Pod UID and full XML/kernel output are retained under
`results/overnight-2026-11-04-coordinator/shadow-gpu-health-before/`. Collect a
second baseline after recovery and compare exact lines, without resetting GPUs.

## Completion and cleanup

Pending. Agents must report terminal run IDs, evidence paths and independent
cleanup before reservations are released or reassigned. The parent will
integrate final presenter captures and the morning review packet.

## November 5 recovery and active resumption

The user restored VPN access at approximately 07:31 Pacific and resumed the
original demo-development task. The parent restored the shared SSH tunnel. The
old overnight 07:30 cutoff is obsolete; it does not authorize cleanup or ending
the resumed work.

The parent's independent inventory at **07:34:09 Pacific** is frozen in
`results/overnight-20261105-recovered-0733/`. The coordinator reviewed its raw
Pods, claims, DGD objects and all retained local reservations. The advertised
inventory remains **24 H100s**, with **8 allocated**, exact intended UUIDs and
no overlapping GPU assignments or EFA oversubscription.

| Workstream | Recovered state | Clearance |
| --- | --- | --- |
| Intro / MX | Original intro worker UID unchanged, Ready, zero restarts on cp-0124 GPU 0/2. MX target pair on cp-0198 is free. | Resume observation of the original run without reapplying; complete health checks before fresh qualification. |
| Migration | Both original worker UIDs unchanged, Ready, zero restarts on cp-0124 and cp-0942 GPU 6/7. Frontend identity retained. | Resume readiness/baseline observation; process fault waits for current GPU/kernel health. |
| Shadow | Exact cp-0124 GPU 4/5 retained, but the worker Pod UID changed during disconnection; current engine-1 has seven restarts and is not Ready. | Diagnosis only. No promotion fault or blind redeployment. Preserve current/previous logs and controller history. |
| Snapshot | Creating DGD UID retained; automatic source Job failed its deadline and worker replicas remain zero. Assigned pair is free. | Preserve failed checkpoint resources and inspect before cleanup or a fresh run; do not replay the failed capture. |
| KVCR | Assigned cross-node GPU 4/5 pairs are free; retained a2 is CPU preparation only. | Verify its namespace/PVC/secret identity, then resume preparation within its original slot. |
| Routing | Original reserved pairs currently unallocated. | Collect the existing detached controller and evidence before planning any further GPU run. |
| P/D | Assigned cross-node GPU 1/3 pairs are free. | Recover the original CPU client/preprocessing evidence first; the original eight-hour Pod deadline may have expired. |

Snapshot's existing shared agent remains the exact pinned Pod:
`dynamo-system/dynamo-platform-snapshot-agent-v2bp8`, UID
`b6e7ad74-ea5b-433f-98e9-07ab2003b85c`; both agent and pagebroker are Ready
with zero restarts. This proves agent identity, not capture success or storage
overlay integrity.

The coordinator's new elevated read-only health requests encountered malformed
approval-hook errors (`invalid hook payload: permission request does not match
the recorded tool call`). Default subprocess calls were sandbox-denied. These
are tool execution failures, distinct from the recovered network and from demo
results. The parent was given the existing read-only health helper and exact
node commands to collect from its working access. No user permission was
re-requested and no privilege/configuration change was attempted.

### Recovered GPU health: scoped clearances, Shadow held

The parent collected read-only GPU XML and kernel evidence from the existing
driver Pods on all three nodes at approximately **07:39 Pacific**. All commands
returned zero and no node conditions changed. The exact driver Pod UIDs,
per-GPU identities, raw-log hashes and scoped decisions are frozen in:

`results/overnight-2026-11-04-coordinator/recovered-0739-health-clearance.json`

SHA-256:
`6dd9c69e898de8acb83e982bf029a4e564e13c04060e1041c21b5ec4843966b0`.

The receipt's overall status is `scoped_clearance_with_shadow_hold`, never a
whole-cluster pass. The KVCR, intro/MX, Snapshot, migration, routing and P/D
assigned pairs have no reported new kernel Xids since test start. Their agents
received per-workstream clearance to continue their authorized task after each
test's own current ownership/readiness gates. Hardware clearance does not erase
Snapshot's failed checkpoint or establish any feature acceptance.

**Shadow has six new Xid 31 events**, all on its assigned cp-0124 GPU 4/5 pair
(PCI `97:00` / `a8:00`). They occur in pairs at **22:58:58 November 4**, **03:07:22
November 5**, and **07:14:37 November 5**, Pacific. Each reports an MMU
read-only violation on a virtual write at `0x5d_3dbfe000`. These events were
absent from the 22:48 baseline and occurred without an intentional demo fault.
This establishes a real startup/runtime failure during disconnection; it is
separate from the observer's transport failure. The exact software cause still
requires its retained worker/GMS stack traces. No intentional Shadow fault or
new startup is cleared; preserve logs and coordinate a scoped DGD stop before
further diagnosis. No GPU reset or Xid-history clearing was performed.

### Routing closeout and released slot

The routing agent recovered and verified 1,040 transported files, 47 frozen
payload files and three C16 cells. Its terminal controller and GPU-cleanup
receipts matched the parent's recovered inventory: the routing namespace had
zero DGDs, zero ResourceClaims, and only its retained CPU client, UID
`4385c581-2c2c-446a-8f7d-123617386cf8`. The coordinator independently checked
the raw inventory for this namespace. The agent preserved its exact local
lease owner and released **only** `.local/overnight-routing-sweep.gpu-lease`.

Receipts:
`results/workshop-routing-overnight-collection-recovered-20261105-0739/independent-acceptance-and-cleanup.json`
and adjacent `local-lease-release.json`. No cluster resources changed in this
closeout. Its original four GPUs are now free for a future explicit assignment;
the original allocation JSON is historical and remains unchanged because the
health receipt and run inputs pin its hash. This closeout does not claim the
uncompleted C32 cells or a capacity knee.

## Final scoped cleanup: November 5, 10:20 Pacific

Tunnel restoration succeeded for final collection and cleanup. A fresh live
audit observed at `2026-11-05T18:20:06.246696+00:00` found 24 advertised GPUs,
**zero allocated GPUs, zero ResourceClaims, zero GPU Pods, zero DGDs and no
allocation issues**. All local `.gpu-lease` directories are absent.
Evidence: `results/overnight-20261105-final-audit-postcleanup-a1/audit.json`.

Canonical owned cleanups passed for MX, KVCR, migration-enabled, DGD Snapshot
and the CPU-prepared Shadow writer candidate. The completed disabled migration,
intro, old Shadow and old Snapshot cleanups remain separately recorded. No
unknown workload, driver, operator or shared platform was changed. Snapshot
artifacts/caches/PVCs/namespaces and the explicitly borrowed routing CPU client
are retained; zero GPU allocation does not mean those retained objects vanished.
