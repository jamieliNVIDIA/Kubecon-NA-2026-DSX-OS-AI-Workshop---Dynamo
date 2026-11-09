# Reader v6: ordinary optional state needed by native warmup

Status: implementation, independent source review and the actual-image CPU
preflight pass. Thirteen focused helper/input tests and seven full-admission
tests pass. Reader/admission/cache source reviews are closed clean. Root chose
to qualify the default, no-development-cache Shadow mechanism while RAM cache
preparation proceeds independently. Full-a3 reached an actual warmed, parked
v6 GPU reader, then a host readiness comparison rejected normal kubelet
Ready/Started settling. Root closed a3 and approved the independently reviewed
host-only repair. Fresh cache-enabled full-a4 is frozen offline with thirty-two
sources held through cleanup; root handles live preparation and execution. No
fault, promotion, recovery or SLO has qualified. See the checkpoints below.

## Why v5 was insufficient

Full-a2 passed reader descriptor restoration and imported 36.79 GiB per rank,
then native DeepGEMM warmup called the generic ModelOpt metadata wrapper. That
wrapper reads `w13_input_scale` and `w2_input_scale` before its Humming dispatch.
The reader manifest covers final registered parameters and optional parameter
slots, while these two final attributes are **ordinary, unregistered None**
state. Their absence therefore survived the v5 callback repair.

The source chain is now exact and image-bound:

1. Humming's final conversion removes its raw input-scale parameters and
   returns `a13_scale = a2_scale = None`.
2. ModelOpt imports `replace_parameter` from `vllm.model_executor.utils` and
   invokes it for both input-scale names after conversion.
3. That exact helper's first branch uses `setattr(layer, name, None)` and
   returns without tensor allocation. Because the old parameters were removed,
   this creates ordinary attributes rather than registered None parameters.
4. Native warmup queries ModelOpt before filtering out non-DeepGEMM configs.

Do not confuse ModelOpt's imported helper with the different
`quantization.utils.layer_utils.replace_parameter`, which lacks this branch.
The exact native helper source SHA is
`9d7d6bee0331cbac232a0f542096d779e28a7c158d092afe3756317395f4b46d`.
Old writer manifests did not record ordinary attrs, so the historical writer
attribute values are source-derived, not newly claimed runtime observations.

## Narrow repair and preserved contracts

`scripts/workshop_shadow_descriptors_v6.py` retains the v4 format and writer
code. It adds one reader helper and a single call before v5's direct Humming
config builder. The helper admits only the final seven-parameter Humming MoE
layout, exact HummingInputSchema class/backend and the observed fully disabled
input-quantization fields. It restores exactly the two ordinary None attrs.
Registered parameters, buffers, non-None attrs and inherited/class attrs are
rejected; both sublayers validate before any mutation. Seven existing
parameters, routing gradients, aliases, dtype/layout rules and stock GMS
materialization stay unchanged. No native warmup is disabled or bypassed.

`scripts/workshop_shadow_reader_delta_v6.py` proves exact source substitution
from the accepted v4 helper through the reviewed v5 callback to v6. All 29
other functions remain byte-identical. The writer export data is identical.
The v4/v5 helpers, previous CPU programs and immutable full attempts are intact.

- Revision: `workshop-humming-reader-v6-optional-input-state`.
- Reader helper SHA: `5a59b4c6e24574e3017bff5197b4603961f396da8504fb2594033b44ca410528`.
- Accepted writer helper remains `ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e`.
- Three author input/export tests and ten independent review tests pass.

## Actual-image CPU gate passed

`scripts/workshop_shadow_reader_cpu_v6.py` writes
`results/workshop-shadow-reader-v6-cpu-packet-20261105-a1`. The packet is derived
from all 80 accepted a6 rank/owner roles, reduced to one identical final runtime
group, and binds seven exact installed-source hashes. It uses the same four
DESCRIPTOR/MOE_PACKET base64/hash variables as v5. Root alone executes it in a
fresh bounded CPU evidence run, with a new one-attempt intent and phase/check
named `reader-v6-source-cpu`.

The CPU program uses real imported ModelOpt/Humming oracle/config classes and
real meta-only RoutedExperts/MoERunner objects. It executes the exact native
`replace_parameter` and warmup metadata bodies from installed source, checks
ModelOpt's actual import, and compares restored ordinary state to native
replacement. Before repair, native warmup must reproduce missing
`w13_input_scale`; after repair, the real generic callback must construct a
Humming config and native selection/count must return false/zero. Both
DeepGEMM flags are explicitly true. Hardware helpers are documented tripwires;
unused provider/expert types and empty warmup caches are CPU metadata doubles.
It tests absent/default, zero and nondefault SwiGLU settings, preserves all
seven parameter IDs/layouts/gradients and routing gate aliases, and requires
CUDA to remain uninitialized. This is a metadata preflight, not GPU recovery.

Root's pinned-image CPU execution passed at
`2026-11-06T00:17:46.908690+00:00`:
`results/workshop-shadow-reader-v6-cpu-live-20261105-a1/result.json`. All three
cases reproduced the original missing attribute, restored native ordinary None
state, created a real Humming config through the generic ModelOpt callback and
returned native warmup predicate false/count zero with both flags true. Seven
parameter identities and the routing gate alias remained unchanged; CUDA was
uninitialized. Independent source/Pod/intent/check/stdout audit passed in
`results/workshop-shadow-reader-v6-independent-audit-20261105-a1/verification.json`;
see [SHADOW-READER-V6-REVIEW.md](SHADOW-READER-V6-REVIEW.md).

CPU program SHA: `8b7fd10730c2bb80a01d8a5e1975d50c9b53b2244bd0c5b8de93c85150b19288`.

After independent review and the actual-image CPU pass, root authorized v6
admission in the current composed bridge. It recomputes the exact seven-source
packet and source delta, binds the actual one-attempt CPU receipt and requires
all three exact cases, native calls/doubles, counterfactual failure, ordinary
state and enabled warmup predicate/count. Seven negative admission tests and
twenty existing composed tests pass; real read-only admission of the accepted
a6 writer plus this CPU result also passed. The next full source closure adds
the three v6 files while retaining unchanged v5 dependencies. At this CPU gate
checkpoint no full freeze had run; subsequent a3/a4 outcomes are below.

The accepted v4 writer basis stays valid for this reader-only change; no writer reload is needed.
The full retry must still prove fresh active/parked readiness, three complete
correct coding streams, exact-pair health and the existing single-fault capture
gates. Preserve all failed CPU/full attempts rather than recycling intents.

## Optional development-cache integration, not frozen

The full controller accepts optional `--dev-cache-qualification`. Cache inputs
are entirely self-contained: `dev-cache-qualification.json`,
`dev-cache-bootstrap.json` and `dev-cache-receipt.json`. Full-spec `dev_cache`
binds the full candidate ID, three raw file hashes and the exact
`workshop_mx_dev_cache.py` / `mx_dev_cache_stage.py` source hashes. The default
seventeen-input contract stays unchanged; the optional variant has exactly
twenty. The durable transport preserves the same distinction and validates
the static graph/ConfigMap/receipt contract before packaging.

Freeze validates the cache graph and CPU qualification before creating a Run
or output directory. Prepare applies the owned bootstrap ConfigMap. Deploy
requires that same ConfigMap UID/data and the current qualified Ready producer
Pod UID, container generation, image and direct Pod IP before writing GPU
intent. Init stages the complete pinned model into a 96 GiB RAM cache at the
existing HF_HOME; GMS/native engine arguments and environment stay unchanged.
The agreed conservative engine budget is 224 GiB requested / 352 GiB limited
per engine, 448 / 704 GiB across both cloned engines on the 2 TiB node.

Readiness first collects the sole completed init's logs, full all-file hash
receipt and actual worker Pod/init image/container ID/exit status, then
rechecks producer identity. No GMS/engine snapshots run while staging is still
pending. Incomplete, restarted, corrupt or differently sourced staging cannot
qualify reader startup. Failure diagnostics preserve init logs. Cleanup waits
for owned Pods/claims to disappear, removes the owned bootstrap ConfigMap and
then delegates lease release. The persistent source service is retained.

Seven focused integration tests pass, including no Run on a bad cache gate,
producer validation before GPU intent, static tamper rejection, complete stage
proof, missing/replaced bootstrap rejection and cleanup ordering. Existing
twenty composed tests pass. A combined run passed 49 focused tests across
composed startup, cache stream/graph, independent cache review, cache lifecycle
and reader CPU admission. Independent review also closed clean after fixing
typed receipt equality, exact image identities, immutable bootstrap ownership
and exact integer-zero termination/restart checks. Actual RAM seed/CPU client
qualification and root source acceptance remain prerequisites to an optional
cache-enabled full freeze. The default full-a3 source closure omits the cache
helper/stage sources so cache development can proceed independently.
This is development-only CPU file staging, with no GPU P2P, combined GMS/MX
loader qualification or startup-speedup claim.

## Default full-a3 frozen for root execution

Root explicitly authorized a fresh default candidate without
`--dev-cache-qualification` so core reader/recovery qualification can use the
idle assigned GPU4/5 pair while RAM cache seeding continues. Offline freeze and
`load` passed at `2026-11-06T00:47:10.216851+00:00` without source edits:

- Run: `results/overnight-shadow-super-vl-20261105-full-a3`.
- Namespace: `dynamo-ft-r610-f69e4b16-demo`.
- Full spec SHA: `7902aca8d072fadadcf66cde76ac087d6fa3e1bef5bc79fc362f5f71fbda7455`.
- Reader overlay SHA: `bd851d2ba3c5690cdb27d6daee7f9ec7ebe2faa1ebae67cb99958949be5ed5c8`.
- Accepted writer overlay remains `82ed5fbe40821a377dd6c8a5769c17b488cbc44bf8ada6fd4312345248e80247`.
- Exact seventeen inputs, thirty critical sources, 134 writer runtime contracts
  and sixteen accepted writer receipts. Neither cache helper/stage source is
  in the default critical closure; no `dev_cache` metadata is present.

The thirty core sources are held through canonical cleanup. Root alone runs
prepare, exact-pair probe, fresh health, durable build/launch, actual readiness
and the guarded single-fault capture. No GPU intent or fault existed at this
offline checkpoint. The durable package includes all current Python scripts,
so unrelated cache script edits must pause briefly from package build through
launch verification; after launch the copied remote package is independent.
This keeps Shadow and development caching separately qualified.

## Full-a3 result: v6 reader parked; host comparison failed

The reader passed the former native warmup failure, imported 36.79 GiB per
rank, retained 120 private workspace owners per rank without extra copies, and
loaded in 7.176613 / 7.321655 seconds. Profile/KV/warmup completed in 84.06
seconds; the reader parked in standby at 01:03:58.787Z. Active/standby roles
were observed on the same unchanged Pod/container generations.

At `2026-11-06T01:04:42.174865+00:00`, the host full-readiness guard failed after
the initial coding calls. The exact selected-field delta between its retained
before/after observations is only engine-1 `ready` and `started` changing from
false to true. Pod UID, container IDs/restart counts, roles and all GMS
state/layout/events are identical. The whole-ContainerStatus comparison
incorrectly interpreted startup-probe progress as identity drift. No new
backend state gap or engine traceback was observed. Control flow shows all
three coding validators returned, but the returned raw payloads were not saved
before the failing comparison, so this is not retained coding qualification.

The immutable 1,263-file collection and independently rehashed failure audit
are `results/shadow-full-a3-remote-collected-a1` and
`results/shadow-full-a3-readiness-failure-audit-a1/verification.json`. Canonical
remote cleanup passed at 01:05:00Z. Root completed local lease/audit closeout
at 01:18:15Z and released the thirty-source hold for the reviewed host repair.
No intentional fault or presenter capture ran; failed a3 snapshots remain
immutable. The host-only proposal and regression matrix are in
[SHADOW-STARTUP-READINESS-PROPOSAL.md](SHADOW-STARTUP-READINESS-PROPOSAL.md).

Separately, 2 GiB is the requested CLI KV budget, not an established allocation
cap: a3 native GMS logs project 14.55 GiB active KV and 14.36 GiB reader KV, with
0.50 GiB reader scratch physical backing. Flag semantics remain an open
integration question; no flag change or inferred upstream bug follows from
this observation.

## Upstream scope and remaining questions

This exposes a final-runtime serialization gap in the experimental
Humming/GMS integration. A production fix should represent backend-owned
ordinary optional state explicitly or let the backend reconstruct it under a
versioned post-materialization contract. The narrow demo helper is tied to
this observed model/backend/schema and should not be presented as a general
GMS serialization solution. Whether native warmup should avoid the generic
wrapper before checking backend eligibility is a separate upstream design
question; this repair restores the state native postprocessing prescribes.

Host readiness qualification, promotion correctness and observed recovery
latency remain open. Persistent
ModelExpress cache development is separate; no unqualified MX loading change
is mixed into this reader repair.

## Reviewed host repair and cache-enabled full-a4

Root closed a3 and released its source hold at 01:18:15Z:
`results/workshop-shadow-full-a3-root-closeout-20261105-a1/complete.json`.
The host fix changes only `workshop_shadow_composed.py` among the old thirty
critical sources. It waits for all three Ready/Started/running containers,
uses stable generation identities plus strict full-GMS equality, and saves
each coding payload and both observations before subsequent guards. Six author,
eight independent and twenty existing composed tests pass (34 total). The v6
reader/native flags/schema/actual CPU program remain unchanged. See
[SHADOW-STARTUP-READINESS-PROPOSAL.md](SHADOW-STARTUP-READINESS-PROPOSAL.md).

Root separately accepted the actual 114-file cache seed and CPU native stream
(117.853 seconds, CUDA uninitialized) and freshly verified the same producer
Pod/container/image/IP. The immutable self-contained qualification is
`results/mx-dev-stage-20261105-a1/qualification.json`, SHA
`f543e915ecd64759fed478fa0456915f55d804bd67047788ac4f547ec4102667`;
fresh producer proof is `producer-pre-full-a4.json` beside it. This qualifies
CPU file staging, not a combined native GMS/MX loader or a GPU startup speedup.

After those gates, optional full-a4 freeze and `load`/deep-cache validation
passed offline without another source change:

- Run: `results/overnight-shadow-super-vl-20261105-full-a4`.
- Namespace: `dynamo-ft-r610-2f515dd0-demo`.
- Spec SHA: `e6dc90dffc04072e8f0b1edd7b253624c43cb5f94f8a1fbeb0c200f88efa8053`.
- Exact twenty inputs, thirty-two critical sources, 134 runtime contracts and
  sixteen accepted writer receipts.
- Host source: `14580c35ed0520a2b1546df21d4ab734f057d4244a63e9618aa15f3a7de0658c`.
- Cache helper: `af47bc71086d6d8ad3bdbbf50b229ca60535e11cfe2d203013c3d1d869ec9b53`.
- Stage source: `3df3c2e86c1c78f261e27b9b7c4ef62432051de83eda7bb300e94ef432aca95f`.
- Reader overlay remains `bd851d2ba3c5690cdb27d6daee7f9ec7ebe2faa1ebae67cb99958949be5ed5c8`.
- Stage ID: `shadow-mx-899d55e55118`; producer UID
  `e32f8b4f-83f1-4291-879f-404d5e811514`, direct target `192.168.100.50:8001`.

All thirty-two sources, including the cache helper/stage, are held through
canonical cleanup. Root alone performs live preparation, exact GPU probe,
fresh producer/GPU health checks, durable launch and any guarded single fault.
No GPU intent or fault existed at the offline freeze checkpoint. The old a3
failed collection/run/snapshots remain preserved and unqualified.
