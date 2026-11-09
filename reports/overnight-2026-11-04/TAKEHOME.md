# Take-home development notes

Prepared November 4, 2026 Pacific. **Portable baseline implemented and validated
offline; the earlier two-profile admission study passed 14/14 checks. The
resumed unmodified public-image candidate has passed CPU capability and actual
cached preparation; its eight DRA bundle dry-runs also passed. GPU serving is
now qualified through an explicit Service-selector correction, with scoped cleanup passed.** Root executes only owned qualification
resources; no shared driver/operator/platform change is part of this work.

## DGD workflow

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
   - Complete: pinned Super VL revision, text-only vLLM, TP2 H100, Kubernetes,
     existing compatible operator, explicit immutable runtime supplied by attendee.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
   - Complete: derive from `workshop_demo.render()` and its qualified
     `configs/dgd/super-vl-tp2/nemotron-agg-functionality.yaml` input. Keep the
     actual repository's `v1beta1/spec.components` schema; the DGD skill's older
     `v1alpha1/spec.services` example is not the executable schema here.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
   - Complete through `take-home/render.py`: freeze attendee manifests in a new
     local output directory, without changing qualified configurations. A static
     cluster-bound DGD is intentionally not introduced as a portable default.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
   - Offline structure/identity/cache tests complete. Device-plugin DGD and CPU
     download Job passed client/server dry-run. Fresh a2 passed all 14 client/server checks for both allocation profiles.
     This does not qualify actual serving or scalar GPU availability on these DRA nodes.
5. Hand off to `deploy_dynamo` or `kubectl apply`
   - Complete as explicit attendee steps. Live application remains a release
     gate until the public runtime and target operator/allocation mode are chosen.

## Files and concrete behavior

- [Attendee guide](../../take-home/README.md): prerequisites, generate/inspect,
  exact-revision model download, apply, discover, request, inspect and scoped
  cleanup. No workshop kubeconfig, EFS ID, private pull secret, node name or
  cached-artifact assumption.
- [Renderer](../../take-home/render.py): requires attendee namespace, immutable
  image digest, runtime version and existing cache PVC. Generates a CPU download
  Job, DGD, frontend Service, request and hashed provenance; optional DRA claim.
  It makes no Kubernetes calls and refuses to overwrite a local output directory.
- [Response check](../../take-home/check-response.py): requires the expected
  advertised/response model, nonempty content and normal completion. Generated
  code is never executed. It is a serving smoke, not quality/performance proof.
- [Follow-up investigations](../../take-home/INVESTIGATIONS.md): constant
  coding-agent workload and one operational question per experiment, with links
  to existing evidence and explicit limits on portable follow-up coverage.
- [Six focused tests](../../tests/take_home/test_portable_bundle.py): both GPU allocation
  contracts, private-cluster exclusion, explicit image/output immutability,
  cache-ref safety, presenter-allocation isolation and negative HTTP response cases.

## Decisions

1. **Start from a deployable service.** The package first teaches the operator,
   frontend/worker separation and model-serving verification. Do not start with
   a full experimental integration or a long installation procedure.
2. **Preserve Super VL identity.** No smaller unqualified substitute is supplied
   automatically. Two H100s are the tested baseline, not a claim about the
   mathematical minimum or a portable fit on arbitrary GPUs.
3. **Separate image access from model access.** The model is marked ungated in
   the lock, but the qualified image is private. A placeholder registry name is
   visibly incomplete; the renderer refuses tags and requires an explicit digest.
4. **Offer existing allocation modes.** A device-plugin profile uses the normal
   scalar `nvidia.com/gpu: 2`; DRA uses one two-device claim. Neither installs,
   switches or co-enables cluster allocators. Both portable variants still need
   live tests. Shadow's shared-claim requirements are not implied by baseline
   device-plugin support.
5. **Keep cache preparation off the serving clock.** The exact-revision CPU Job
   runs first. It checks metadata hashes and weight inventory, then invokes the
   actual runtime metadata resolver offline. The initial engine retains eager
   execution, four sequences, TP2 and 85% HBM settings from demo 1.
6. **Carry the metadata-resolution workaround explicitly.** Current registration
   can resolve without the engine revision. Fresh `snapshot_download(revision=SHA)`
   alone does not establish `refs/main`. The Job creates that ref only if absent,
   requires a matching ref if present, and refuses an existing different revision.
   It then checks the runtime resolver selects the exact snapshot in a new
   `HF_HUB_OFFLINE=1` interpreter. Do not silently reassign shared cache refs.
7. **Preserve attendee data on cleanup.** Delete the named DGD before its Service
   and Job, verify Pods/claims are gone, then remove the claim template. Retain
   the namespace/cache PVC unless its owner separately decides otherwise.
8. **Ignore presenter GPU allocation settings.** Import an isolated copy of the
   pure intro renderer with `WORKSHOP_ALLOCATION` temporarily absent, then restore
   the caller's environment immediately. Do not mutate an already-imported
   presenter module or copy its private node/UUID selectors. Include the
   allocation helper's source hash in generated provenance because the isolated
   intro module imports it.

## Validation actually performed

```bash
.local/venv/bin/python -m unittest discover -s tests -p test_take_home.py -v
PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python -m py_compile \
  take-home/render.py take-home/check-response.py tests/test_take_home.py
```

All six tests pass. The cache test runs the generated download program against
a local fixture: a valid dedicated cache gets the matching ref and an offline
resolver subprocess; a foreign existing ref stops before download/subprocess
and remains unchanged. Network download and actual Dynamo metadata resolution
are mocked in that test and are not claimed as executed successfully.
The allocation test covers valid, missing and malformed assignment-file paths,
including an already-loaded presenter module with an active assignment; its
environment and module global remain unchanged, and attendee output has no
node/physical-UUID selectors.

The first standalone compile attempted the system's Python cache outside the
workspace and was denied by the sandbox. Rerunning with the local cache prefix
above passed. No source change or broader permission was required.

### Nonmaterializing Kubernetes admission

Two independent real-image bundles are retained in
`results/take-home-admission-20261104-a1/{device-plugin,dra}/`. They use the
qualified image/version supplied explicitly, an existing owned namespace/PVC,
and no presenter node/UUID/CEL selectors. The manifests did not create resources.

The coordinator first verified namespace
`dynamo-ft-overnight-disagg-20261105-a1`, UID
`cdde6b92-29a5-4c9d-b0c3-2cd6b47c829c`, and its ownership label. This was a
validation namespace only; it is not a portable default.

| a1 check | Result |
| --- | --- |
| Device-plugin DGD, client and server dry-run | Both exit 0 |
| CPU download Job, client and server dry-run | Both exit 0 |
| DRA-profile CPU Job, client dry-run | OpenAPI TLS handshake timeout; no schema rejection established |
| Device-plugin Service and remaining DRA checks | Transport/subprocess timeouts interrupted collection; no complete final admission receipt |

The initial sandbox API request was denied. A separate escalation attempt was
rejected by the approval hook with `invalid hook payload: permission request does
not match the recorded tool call`; the coordinator executed the reviewed
dry-run-only program through its working authorized path instead. Its four
successful checks and failed/incomplete attempt remain preserved; nothing was
relabelled as serving qualification.

Fresh a2 under `results/take-home-admission-20261104-a2/` completed at
18:19:03 UTC on November 5. **All 14 checks passed**: client/server dry-runs of
both profile DGDs, download Jobs and frontend Services, plus the DRA claim
template. The program used one kubectl subprocess at a time, preserved schema
validation, verified the exact owned namespace, and created no resources.
The interrupted a1 remains unchanged.
[Shareable receipt](../receipts/2026-11-05-take-home-admission.json).

The full admission pass does not establish image pull, download, Pod
scheduling, available HBM, model kernels or serving behavior. Public attendee
image/live-profile qualification remains a separate gate.

## Open questions and release gates

- Which accessible runtime digest can the attendee use, and which operator
  version/CRD schema is supported with it? The fresh unmodified nightly CPU probe now reports NIXL 1.5.0,
  but that does not qualify its other dependency combinations or make it a
  blanket all-feature substitute for the selected experimental KVCR stack.
- Is a two-H100 model an appropriate take-home hardware requirement? If a
  smaller exercise is wanted, choose its own model/revision and qualify it.
- Qualify the generated DRA path and/or device-plugin path on the advertised
  attendee cluster. Current workshop nodes use DRA; scalar GPU availability
  must not be inferred from their ResourceSlices.
- Qualify the generated CPU download Job, metadata resolver, shared cache
  permissions, H100 labels/taints and Pod policy in the selected public runtime.
- Confirm practical PVC capacity/download duration and publicly distributable
  model/AgentX trace artifacts. The present package does not bundle trace data.
- Portable follow-up overlays for MX, routing, KVCR, P/D, migration and Snapshot
  remain a later deliverable; workshop-private demo launchers are linked as
  references and are not presented as attendee copy-and-run commands.
- Keep the Snapshot bridge upstream workstream separate, as Neal requested.
  The take-home baseline does not depend on that experimental restore path.

## Upstream candidates

See [the candidate ledger](UPSTREAM-CANDIDATES.md). The metadata-registration
revision gap affects fresh-cache reproducibility beyond Snapshot and is already
related to proposed Dynamo #11369. The small guarded-ref workaround belongs in
this exact exercise until revision-aware registration is available and tested.

## Resumed November 5 public-runtime qualification

The user resumed unfinished work after the review packet. A candidate unmodified
public nightly is frozen by digest in
`results/take-home-live-public-20261105-a2`, with explicit Dynamo version
`1.7.0.dev20261103`. Its original source/registry metadata is in the November 4
nightly selection receipt; that work qualified extracted wheels on the private
base, not the unmodified image. No public runtime or serving success is inferred.

New maintainer harness: `take-home/qualify.py`; exact steps and scope are in
[take-home/QUALIFICATION.md](../../take-home/QUALIFICATION.md). The parent is the
sole live executor. This agent froze a1 and its UID-hardened successor a2 offline;
a1 was superseded before any cluster action. A2 creates a new namespace, stores
its returned UID once, and refuses reused names on every later mutation and
cleanup. It retains source/input hashes, exact assigned GPU proofs and one-shot
request intents. It never installs packages or modifies shared infrastructure.

The generic optional `--cache-subpath` now mounts an existing relative PVC
directory consistently in downloader/frontend/worker. Traversal, absolute,
empty, dot-segment and shell-like paths are refused. Defaults remain unchanged.
The live candidate reuses the exact qualified cache, and must be described as
cached deployment/metadata qualification rather than a fresh-download test.

Ten focused tests passed after these changes, including offline-only freezing,
unchanged engine controls under exact placement fencing, input tamper rejection,
namespace reuse refusal and DGD UID refusal during cleanup. Syntax checks passed
for the harness/runtime probe/renderer. Runtime execution remains with root;
the CPU pull/capability probe, actual cached deployment, request and cleanup
results will be appended after observing their own receipts.

### Actual unmodified public-image CPU result

Root's CPU probe passed at 19:19:17 UTC (11:19 Pacific), November 5. The
independent offline audit accepted twelve checks: original namespace UID, exact
image digest/program, no Pod pull secret or overlay/init-container, no GPU
claim/numbered devices, successful no-restart exit, actual model registry and
required engine fields, matching Dynamo packages and owned probe deletion.
Frozen source/input hashes remain unchanged.

Actual versions: Dynamo/runtime `1.7.0.dev20261103`, vLLM `0.32.0`, Torch
`2.13.0+cu130`, Transformers `5.19.0`, NIXL **`1.5.0`**. The installed NIXL
package supersedes the earlier source-ref-derived `1.4.1` inference for this
exact digest; it does not establish KVCR/NIXL transport compatibility. The old
selection receipt is preserved.

[Shareable independent CPU receipt](../receipts/2026-11-05-take-home-public-runtime-cpu.json).
Actual root-owned cached preparation and serving remain the next gates. A
successful pull without a Pod pull secret does not alone prove anonymous
registry access outside the cluster credential-provider configuration.

### Public a2 admission failure and explicit a3 correction

A2 stopped at server dry-run before any cache Job or GPU deployment. The installed
CRD accepts only strict `X.Y.Z` in `runtimeVersionOverride`, so the nightly package
version `1.7.0.dev20261103` was rejected. This was the new harness conflating
package identity with operator compatibility, not an engine/model failure.
Root's scoped a2 cleanup passed; namespace/PV/PVC/cache and all original evidence
remain retained. No attempt input was edited in place.

The fresh a3 spec now separates compatibility override `1.7.0` from expected
installed Dynamo package `1.7.0.dev20261103`. It preserves the same unmodified
image digest, model/revision, engine flags, request and physical GPU pair. The
renderer now rejects prerelease, malformed and out-of-range override values
before rendering. Eleven focused tests passed. A3's own namespace creation UID,
CPU result, admission, cache Job, serving and cleanup remain distinct gates.

Exact source bytes for both a2 and a3 are saved read-only under each run's
`source-snapshot/`. A2's two changed files were recovered by inverting only the
explicit compatibility/package split and accepted only after every byte matched
the originally frozen SHA256; the other six files matched directly. No original
result/input was overwritten. This preserves the failed implementation as well
as its hashes. The current source remains frozen for root's a3 execution.

### Public a3 cache-permission failure and explicit a4 correction

A3 passed the actual unmodified CPU probe and eight DRA bundle client/server
dry-runs (plus storage setup's own server dry-run). The prior fourteen-check
study tested both allocation profiles; it is a separate count, not this live
DRA-only admission pass. The cache Job then failed with `PermissionError`
creating a temporary directory under `/model-cache/hf/hub`. Its actual Pod ran
UID 1000; the reused cache is root-owned. The frontend would also use that image
default, while the inherited worker already uses UID 0. This is a cache/profile
identity mismatch, not evidence of a model-kernel failure.

Root preserved exact failed Pod JSON/logs and completed a3 scoped cleanup. The
old local `kubectl wait --for=complete` observer remained bounded but could not
recognize terminal Job failure early; it performed no GPU deployment.

Fresh a4 preserves image, model/revision, request, engine flags and assigned GPUs.
It explicitly adds generic `--run-as-user 0` for downloader/frontend/worker to
match the existing cache, without a chown or cache-ref repair. UID choice is now
explicit provenance, not an invisible runtime substitution. Portable defaults
remain unchanged, and attendees need an administrator-provided cache identity
and Pod policy. The new observer fences the exact Job UID, fails immediately
on Failed/FailureTarget and preserves actual owned Pod JSON/logs in finally.
Thirteen focused tests pass, including immediate terminal failure, Job UID reuse,
consistent explicit UID and unchanged worker capabilities.

A4 is frozen offline in `results/take-home-live-public-20261105-a4`, namespace
`dynamo-ft-takehome-9812d1b965`, with exact source/input hashes and a read-only
eight-file source snapshot. Root owns all actual CPU/cache/GPU actions.

### Actual a4 cached preparation passed; serving pending

Root's a4 pipeline passed CPU, preparation and deployment submission. The
generated cache Job `31954d7d-7d51-4c96-9d65-ceedb677dcf9` owned exactly one
Succeeded Pod, with actual UID 0, zero restarts, the exact public image digest,
no Pod pull secret and no GPU claim. Its metadata hashes/shard inventory and
actual offline Dynamo resolver selected the pinned revision. Independent raw
object/log verification passed and source hashes remain unchanged.

[Shareable preparation receipt](../receipts/2026-11-05-take-home-public-runtime-preparation.json).
The 114-file traversal reused cached weights; it is not a fresh weight download.
Worker weight prefetch is in progress, frontend is Ready, and neither GPU serving
nor cleanup has yet been accepted at this checkpoint. All engine/model/profile
controls remain frozen while root's bounded controller continues.

### Anonymous image metadata verified; GPU initialization continues

Root's fresh anonymous probe passed for the exact manifest and config digests,
with no local registry credentials. The independent audit matched the CPU-tested
image, verified both expected digests and preserved the probe/result hashes in
[the public metadata receipt](../receipts/2026-11-05-take-home-anonymous-image-metadata.json).
It downloaded no layers; the manifest lists 82 layers. The first probe failed
on a too-specific service-name assumption. The corrected parser accepts NGC's
observed `service="registry"`, while keeping the exact HTTPS realm/repository
pull scope. A focused negative test covers wrong host/service, HTTP and push
scope; fourteen take-home tests pass. None of these edits affect a4's frozen
runtime/renderer/harness dependencies.

A4's latest saved worker logs show both ranks completed checkpoint prefetch,
weight loading logged 872.27 seconds, then FlashInfer JIT initialization began.
Both serving containers have zero restarts; frontend is Ready, worker still
initializing. This is startup progress, not a completed serving qualification
or an isolated startup benchmark.

### Final public cached baseline serving and cleanup passed

The unmodified public image reached Ready on the assigned H100 pair. A4's
first port-forward then failed before any request because the generated Service
selected `app.kubernetes.io/managed-by=dynamo-workshop-take-home`, while Grove
materialized the Pods with `managed-by=grove-operator`. The preserved custom
`workshop-service` and `workshop-role` labels identify the endpoint correctly.

Root ran the explicit sibling Service-selector revision with unchanged ready
engines. It froze original identities and patch preimage, server-dry-ran a
UID/resourceVersion-guarded selector-only patch, proved EndpointSlice targeting
the unchanged frontend, and sent the original request exactly once. HTTP 200,
expected model, nonempty function code and normal stop passed. Namespace, DGD,
frontend/worker UIDs, actual image, zero restarts and exact GPU pair matched
before/after. Original bundle, failed port-forward and earlier failures remain.

Canonical a4 cleanup passed at 20:13:29.798 UTC, with zero owned Pods/claims and
no local take-home lease. Cache/PV/PVC/namespace/evidence remain. An independent
closing audit rehashed all scientific revision evidence unchanged. Only after
that cleanup did the canonical renderer drop `managed-by` from its selector.
The Grove-label regression also rejects worker and other-service matches; all
fifteen focused tests pass. The attendee guide now supplies the concrete tested
public digest, strict compatibility version, DRA mode and explicit UID profile.

[Final baseline receipt](../receipts/2026-11-05-take-home-public-baseline.json).
[Detailed serving revision](../receipts/2026-11-05-take-home-public-serving.json).
This qualifies cached DRA serving with the explicit corrected Service and UID 0
on this H100/driver/operator stack. A pristine full run of the corrected
renderer was not repeated after the Service-only correction; the exact fixed
selector was exercised against the unchanged real service. Fresh network weight
download, device-plugin serving, other storage/Pod policies, stable release and
advanced feature composition remain separate release gates.
