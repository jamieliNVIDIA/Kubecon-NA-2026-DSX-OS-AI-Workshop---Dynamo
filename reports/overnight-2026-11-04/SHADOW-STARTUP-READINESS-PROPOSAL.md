# Full-a3 readiness gate: host-only repair proposal

Status: root closed a3 and released the source hold at 01:18:15Z. The host-only
fix is implemented; six author regressions and twenty existing composed tests
pass; eight independent tests/review also passed. Root accepted fresh producer
identity and optional full-a4 is frozen offline. The v6 backend adapter is unchanged and passed actual GPU reader
initialization, warmup and parking in a3.

## Exact observed failure

The 1,263-file collection is `results/shadow-full-a3-remote-collected-a1`.
Independent rehash and comparison are recorded at
`results/shadow-full-a3-readiness-failure-audit-a1/verification.json`. The first
controller failure is at `2026-11-06T01:04:42.174865+00:00`, in the comparison
after the initial three coding calls. No engine traceback/AttributeError or
intentional fault occurred.

`shadow-observation-1793927043550929835.json` versus
`shadow-observation-1793927082120160388.json` differ in exactly two fields used
by the guard: engine-1 `ready` and `started` change from false to true. Pod UID,
all three container IDs/restart counts, active/standby states and every GMS
state/layout/event field remain identical. Comparing whole Kubernetes
ContainerStatus dictionaries treated normal startup-probe progress as identity
drift.

Both reader ranks imported 36.79 GiB and validated 120 already-private Humming
workspace owners each, with zero extra copies. Loading took 7.176613 and
7.321655 seconds. Native engine profile/KV/warmup completed in 84.06 seconds;
the reader parked at 01:03:58.787Z. Control flow reached the post-coding
snapshot, so all three existing coding validators returned; their raw returned
streams were written only after the failing guard and are not retained. This
does not qualify fresh coding, promotion, recovery or an SLO.

## Proposed narrow change

Only the host controller changes; reader/native/GMS code, v6 CPU payload,
profile and GPU/model flags stay unchanged.

1. While polling active/standby state, require engine-0, engine-1 and GMS to
   have `ready is True`, `started is True`, a running state, nonempty container
   identity and exact integer-zero restart count before sending coding work.
   A still-settling startup probe keeps polling within the existing deadline.
2. Save the qualifying before snapshot immediately. Save each successful
   coding response in its own numbered JSON file as soon as its validator
   returns, and maintain the aggregate list. A later request or identity
   failure preserves the already completed payloads.
3. Save the after snapshot before any final comparison. Require that all three
   containers are still Ready/Started/running with zero restarts, validate the
   physical GPU pair/node, and compare Pod UID, active/standby roles and each
   container ID/restart count for stable identity. Whole ContainerStatus
   dictionaries are not identity keys.
4. Retain strict equality of the complete GMS state/layout/event observations,
   including both weights and KV sockets. Other guards and the single-fault
   capture flow remain unchanged.

The existing `validate_ready_observation` already projects Pod/role/container
identity; the startup-specific guard can reuse it and add probe health plus
strict full-GMS equality. Do not weaken pre-fault/final mutation guards or
reinterpret a3 as qualified.

## Regression tests to add after the source hold is released

- Replay the two retained a3 snapshots: the before sample remains pending
  because kubelet readiness is false; the after sample qualifies probe health.
  Metadata flags outside identity may settle without implying replacement.
- Reject missing/false/bool-coerced Ready/Started, absent running state,
  missing/changed container ID, nonzero or noninteger restart count, changed Pod
  UID, changed active/standby roles, GPU pair or node.
- Reject every changed GMS state, layout or event field, including KV sockets;
  accept exact unchanged full GMS observations.
- Make the second coding request fail: preserve the before snapshot and first
  complete raw response, without a ready pass or fault.
- Make the final comparison fail: retain all three raw responses and both
  snapshots, with no ready pass or fault.
- Exercise a pending probe followed by Ready/Started in a bounded fake wait;
  prove no coding request is issued before all three probes are healthy.

Actual retained-snapshot/host lifecycle tests and independent source review
are appropriate for this harness change. A new native CPU adapter test is not
needed unless reader/backend/source contracts change. Root alone may freeze
and execute the next fresh full-a4 after closeout and review; optional RAM
cache mode additionally requires independent acceptance of its actual full
stream qualification.

## Separate KV budget observation

The 2 GiB CLI flag is **requested**, not a validated allocation cap. A3 native
GMS logs project approximately 14.55 GiB active KV and 14.36 GiB reader KV,
with 0.50 GiB physical backing for the reader scratch allocator. The requested
flag remains unchanged. Whether this is intended GMS budget semantics is an
open source/integration question; it is not the observed readiness failure and
does not establish an upstream bug.

## Implemented after root closeout

Root closeout is
`results/workshop-shadow-full-a3-root-closeout-20261105-a1/complete.json`. After
release, only `workshop_shadow_composed.py` changed among the original thirty
critical sources. Current host source SHA is
`14580c35ed0520a2b1546df21d4ab734f057d4244a63e9618aa15f3a7de0658c`.
The v6 helper, actual CPU program, schema and native/GMS/model/GPU flags remain
unchanged; failed a3 run/collection/snapshot bytes remain immutable.

`startup_probes_ready` distinguishes probe health from identity and requires
all three containers to be Ready, Started and running with nonempty IDs and
exact integer-zero restart counts. `validate_startup_observation` requires
healthy before/after probes, stable Pod/active-standby/container generations
and exact complete GMS JSON. Existing physical pair/node checks remain on both
snapshots. The wait loop polls until probe health settles before any coding
request. It writes the before snapshot, each numbered validated response and
aggregate as work completes, then saves the after snapshot before final guards.

`tests/test_workshop_shadow_startup_readiness.py` passes six tests using actual
a3 observations and bounded host doubles. They cover probe settling before
work, all three health/type guards, stable-generation/full-GMS rejection,
allowed nonidentity metadata progress, failed second-request preservation and
retained snapshots/payloads for final GMS/node/GPU/health failures. Twenty
existing composed tests also pass. Eight independent tests/source review
passed, covering actual a3 snapshots, thirty health variants, stable
generation/full-GMS drift, physical-pair gating and partial/full payload
retention. After root's actual cache qualification and fresh source proof,
optional `results/overnight-shadow-super-vl-20261105-full-a4` was frozen offline;
its spec SHA is `e6dc90dffc04072e8f0b1edd7b253624c43cb5f94f8a1fbeb0c200f88efa8053`.
All thirty-two a4 sources are held through cleanup. Root alone handles live
execution; no GPU attempt or fault was created by this workstream.
