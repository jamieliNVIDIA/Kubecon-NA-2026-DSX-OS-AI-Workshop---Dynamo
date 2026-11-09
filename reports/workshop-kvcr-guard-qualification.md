# Two-engine KVCR-Guard qualification

November 5 clarification: the later actual-image CPU probe observed NIXL
**1.5.0** in the public nightly, superseding the older 1.4.1 inference in the
selection history below. The accepted Guard run still used the explicit private
base plus nightly-wheel/adapter composition; the public image's separate baseline
serving result does not qualify Guard on that image. See the
[actual package receipt](receipts/2026-11-05-take-home-public-runtime-cpu.json).

Status: **nightly a4 passed ordinary peer reuse, controlled Guard retrieval by B,
and warm local-pool handback to replacement A**. Its first unpinned
post-fault request failed HTTP 503, so automatic failover is not qualified.
The original workshop runtime remains unqualified. Attempt a3 served
requests on both engines and committed host-cache blocks, but ordinary peer
reuse failed before fault injection: the state agent quarantined Super VL's
hybrid cache events. The exact rejection has a merged upstream fix absent from
that original runtime. The nightly component result is scoped below:
engine A fails, its Guard remains alive, and
engine B uses A's preserved host-memory cache. Same-GPU Shadow/GMS composition
is deferred until this mechanism passes.

## Nightly follow-up

All 111 current upstream release tags were checked against the merged fix;
none contains it. The latest stable release, v1.6.1, also retains the failing
`normalize_raw_batch` branch. The newest official vLLM nightly is
`nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly:20261103-e37f0b9-efa`; its registry
config records source `e37f0b91f841e12715e412b375a40842ec6010b6`, which contains
the fix. Its amd64 digest is
`sha256:c186817f4669d615d2b14bee5a6119d35d4d0fe186fdfab69920da8de9d09337`.
That image bundles NIXL v1.4.1, while the selected KVCR requires exactly 1.5.0.

Attempt `results/workshop-kvcr-guard-20261104-a4` therefore uses the matching
official **ai-dynamo and ai-dynamo-runtime 1.7.0.dev20261103 wheels** in an
isolated container overlay on the existing Super VL/NIXL 1.5.0 base. Both wheels
are SHA-256 pinned in [the candidate](../configs/kvcr-guard-nightly-runtime.json).
Frontend, workers and state agent load the same pair. No shared runtime default,
inference-engine binary, NIXL library or Kubernetes operator was upgraded.
This candidate is not the unmodified public nightly container.

The actual CPU probe passed: both Dynamo versions are 1.7.0.dev20261103,
vLLM remains 0.31.1rc1.dev23+g43b4aaea3, NIXL remains 1.5.0, and the adapter's
telemetry path and state-agent import pass. A fresh driver/DRA/EFA probe also
passed. Both engines subsequently served, and ordinary peer reuse passed with
4,224 cached input tokens. The controlled recovery result is detailed below.
Release tags, source ancestry, OCI manifests/config and wheel provenance are in
`results/workshop-kvcr-guard-nightly-selection-20261104/`; a4 holds its own
frozen sources, manifests and receipts.

## Nightly Guard retrieval result and routing boundary

The fresh nightly attempt preserved the exact Super VL model and NIXL 1.5.0
stack. Ordinary A-to-B reuse transferred six blocks (99 MiB) and reused 4,224
of 6,051 input tokens. A second, unique prefix was then committed only on A;
B's counters remained unchanged during seeding. The inspected EngineCore was
killed once with identity guards, and its replacement was held down.

A's Guard promoted with 12 committed blocks. The first unpinned post-fault
request failed HTTP 503: the frontend selected the dead A endpoint at
02:40:27 UTC, while Kubernetes discovery removed that endpoint at 02:40:30.
Request migration was explicitly disabled. This failure is retained; it is not
counted as successful automatic failover. B's cache counters did not change.

The actual operator-created Pod also had engine liveness/readiness probes that
were not explicit in the rendered template. The source main container restarted
once after losing `/live`. Its Pod, Guard container, Guard pool and the surviving
engine/Guard containers remained unchanged. The original strict no-container-
restart diagnostic stopped before sending a pinned request; its failed preflight
is retained separately.

A separately labelled request explicitly pinned to B then completed with READY.
Matched source-Guard and target receipts prove a fresh six-block / 103,809,024-byte
transfer after promotion; B recorded 4,224 external-cache input tokens and zero
failed/partial deliveries in that interval. A's EngineCore was absent before and
after the request. Both Guards and Pod UIDs remained unchanged. The diagnostic
admitted the one already-recorded source-main restart and rejects any subsequent
container change. This qualifies **preserved-host-cache retrieval by a surviving
engine with controlled routing**, on one node and with text-only Super VL input.
It does not qualify an unchanged source container, automatic HTTP failover,
in-flight stream migration, cross-node recovery or GMS composition.

The initial receipt matcher incorrectly compared the target handle with the
source-local `source_op`. The pinned upstream code logs the target wire handle
as source `op`; correcting that comparison validated the already-saved transfer.
No generation was replayed. A negative regression rejects matching only the
source-local ID. Fourteen scoped offline tests pass, including engine-incarnation
checks for handback.

### Warm handback result

After releasing the source hold, the Guard logged `handback_start` and
`handback_done` at 02:54:14 UTC. Replacement A became serving-ready. Its
Kubernetes container-discovery worker ID stayed `4063327201741088`; a changed
endpoint ID is not a valid restart prerequisite here. The source main container
ID changed once, and EngineCore changed from PID 1372/start tick 245784469 to
PID 1412/start tick 245935829. Both Guards, both Pod UIDs and B's engine container
remained unchanged.

One separately labelled request pinned to replacement A completed with READY and
valid SSE. It reused 4,224 of 6,050 input tokens. Counter deltas show six
`local_deliver` blocks / 103,809,024 bytes (99 MiB), 4,224 external-cache tokens,
zero remote-delivery blocks and zero failed/partial local deliveries. This proves
warm reuse from the handed-back host pool, beyond merely observing readiness.

The original handback controller waited for a changed worker endpoint ID and
was stopped without sending a generation. The corrected controller checked the
new process/container incarnation before sending the single handback request.
Its predecessor scripts and logs remain as evidence; the reusable readiness gate
now uses EngineCore start time and retains the surviving endpoint check.

Evidence: a4 `controlled-guard-recovery-proof.json`,
`controlled-handback-proof.json`, `controlled-handback-before/`,
`controlled-handback-after/`, `controlled-source-handback/`,
`controlled-diagnostic-identities.json`, `controlled-guard-before/`,
`controlled-guard-after/`, `guard-target-retrieval/`,
`frontend-guard-request-failure.log`, `post-fault-pods.json`, and
`source-pod-events.json`. The original failed `verify-console.log` and all
diagnostic/preflight logs are preserved.

The a4 deployment was removed and its reservation released after evidence
collection. Cleanup verified zero owned Pods, GPU claims and DGDs. The separate
load-sweep reservation and its resources were outside the cleanup scope. See
the [nightly receipt](receipts/2026-11-04-kvcr-guard-nightly.json) for the final
independent audit and evidence hashes.

## Result of the two-engine attempt

Run: `results/workshop-kvcr-guard-20261104-a3`. Same-node, separate TP2 GPU
pairs; text-only requests using the exact Super VL model revision. CPU imports,
the exercised telemetry path, native EFA/driver isolation and both engine
startups passed. Each engine successfully answered its one controlled request.

| Observation | Engine A | Engine B |
| --- | ---: | ---: |
| Prompt tokens | 6,051 | 6,051 |
| Cached prompt tokens | 0 | 0 |
| Committed KVCR local-fill blocks | 6 | 6 |
| KVCR host-tier write bytes | 103,809,024 (99 MiB) | 103,809,024 (99 MiB) |
| Remote-delivery blocks | 0 | 0 |
| External-cache input tokens | 0 | 0 |

The source Guard/state-agent log reports `KVCR event enrichment failed` with
`NonMainAttentionKind`, followed by `Quarantining vLLM KV ingress` and
`CacheOwner residency failed closed`. The target computed the prompt itself;
correct output therefore does not qualify cache reuse. The prerequisite gate
stopped the test. No EngineCore kill or Guard-only retrieval was attempted.

[Dynamo #15535](https://github.com/ai-dynamo/dynamo/pull/15535), merged as
`8bf042187a8f3f4224e608b1045db14e5f712f30`, filters classified recurrent/non-main
events before checking main-attention geometry. Its regressions explicitly
exercise Mamba and sliding-window events while retaining fail-closed checks for
malformed main-attention events. GitHub metadata confirms the PR is merged;
local ancestry verification confirms the commit is absent from the tested
runtime source `ea23e5130c1bfbadec477b99449d0cee5598caa0`. The PR names
[vLLM #59703](https://github.com/vllm-project/vllm/pull/59703) as its companion
classification change. This is evidence of a relevant upstream fix, not a
passing Guard-recovery qualification with that fix.

The a4 follow-up above qualified an isolated runtime containing the Dynamo fix:
ordinary peer reuse passed before fault injection, followed by controlled
Guard-only transfer and replacement-engine handback. A Python-only KVCR overlay
cannot update the Rust state-agent code. Automatic failover, cross-node recovery
and GMS composition remain separate gates.

Evidence: `qualification-result.json`, `ordinary-before/`, `ordinary-after/`,
`peer-reuse-failure/`, both request SSE streams, the frozen candidate/manifest,
and `upstream-hybrid-fix.patch` under the run. The first frontend preflight and
its original log/identities remain in `frontend-preflight-failure/`.

The operator supplied a `DYN_NAMESPACE_PREFIX` different from the common
namespace selected by the qualification wrapper. The first frontend preflight
therefore returned no models and stopped before any request. A separate owned
CPU frontend with the corrected prefix served the two measured requests;
neither loaded engine nor Guard container changed. Its full Pod specification,
creation controller and logs are retained. The reusable runtime wrapper now
sets both namespace and prefix together; that correction has a regression test.
The a3 engine runtime remains frozen in its original ConfigMap.

Twelve scoped offline tests pass. All three attempts were cleaned; a3 cleanup
verified zero owned Pods, GPU claims and DGDs, removed the extra CPU frontend,
and released only the Guard qualification lease. An independent final audit
confirmed all three namespaces empty of Pods/claims/DGDs and no GPU claims on
cp-0124. No Guard cleanup action altered the other workstream's resources;
routing independently closed and released its separate lease, and its successor
load sweep holds its own reservation. See a3 `final-cleanup-proof.json` and the
compact [receipt](receipts/2026-11-04-kvcr-guard.json).

## DGD task list

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
- [x] Hand off to `deploy_dynamo` or `kubectl apply`

Template basis: the qualified `super-vl-tp2/nemotron-agg-functionality.yaml`
through `workshop_demo.render`, with connector settings from
`super-vl-tp2/nemotron-kvcr.yaml` and the upstream memory-service example's
lifecycle requirements. Two workers,
TP2 H100 per worker, four H100s total. The active routing campaign owns two
other nodes; the first trial uses separate GPU pairs on cp-0124. It does not
qualify cross-node recovery. Preserve the exact
workshop model/revision and base-image digest; pin any package/adapter overlay
separately. CPU compatibility gates precede GPU deployment.

## Required proof

1. Verify the exact candidate imports and service/adapter API on the base image.
2. Establish serving readiness and ordinary cross-worker cache reuse.
3. Populate A's Guard-owned secondary pool with committed blocks; prove B lacks
   that unique prefix and snapshot all identities/counters.
4. Kill only A's inspected EngineCore with Pod UID and PID/start-time guards.
   Keep A's Guard, Pod, pool and cache discovery alive and hold its replacement
   engine down during retrieval.
5. Require nonempty Guard recovery and a successful generation on B using
   positive external-cache tokens, matched transfer blocks/bytes, zero failed/
   partial deliveries and LIBFABRIC/EFA transport evidence.
6. Verify pool handback and a fresh generation on the replacement A.
7. Clean owned resources, verify no owned GPU claims remain, and release only
   this qualification's reservation. Preserve unrelated work and raw evidence.

## Candidate preparation

Run: `results/workshop-kvcr-guard-20261104-a1`. KVCR source is pinned to
`dd5df02c076dfee4bb2cdc39bef11164f9dcaec5`, with the matched vLLM adapter at
`a5db4c9ff58a0ec4dc20594ba5cea9f776dcd693`. The base image, NIXL 1.5.0,
Dynamo 1.6.0 and vLLM binaries are unchanged. The CPU probe confirmed imports,
package/API compatibility, libatomic, pidfd support and the state-agent module.
It does not qualify native transfer or inference.

An initial ConfigMap admission failed because client-side apply added an
oversized last-applied annotation. The immutable source bundle uses create
with server dry-run instead. The first CPU build then exposed a missing
Hatchling backend; pinned pure-Python build wheels are staged in the bundle
and installed only into the disposable container's overlay. Failed receipts
and logs remain. The final CPU candidate passed, including diagnostic logging
for exact source/target transfer receipts.

The rendered DGD is under
`configs/dgd/workshop-kvcr-guard/workshop-kvcr-guard-20261104-a1/deployment.yaml`.
Only cp-0124 is eligible. The live RR/KV routing campaign's cp-0198/cp-0942
nodes, UUID reservation and workloads are preserved.

## First GPU startup result and follow-up

Attempt a1 loaded both models, but the Guard's background LIBFABRIC backend
failed to load because `libcuda.so.1` was absent from the CPU-only container.
The library requirement exists even when only DRAM is registered. The Guard
sidecar restarted; the startup gate rejected the candidate, and no engine
fault or recovery request was attempted. Current/previous logs and the failed
receipt are retained under a1. Cleanup verified zero owned Pods/claims/DGDs
and released its reservation.

Fresh attempt `results/workshop-kvcr-guard-20261104-a2` preserves the model,
base image and pinned KVCR/adapter sources. Driver-only CPU probes found that
the default handler still lacked libcuda, while the existing `nvidia-legacy`
handler with `NVIDIA_VISIBLE_DEVICES=none` passed native EFA/LIBFABRIC setup,
1 MiB DRAM registration/deregistration, and exposed no numbered GPU devices.
The combined-runtime probe passed: the engine saw exactly two DRA-assigned GPU
devices, and the Guard saw no GPU devices while registering DRAM over EFA.
The fresh DGD uses that existing runtime handler. Engine legacy device
selection is disabled (`NVIDIA_VISIBLE_DEVICES=void`) so DRA/CDI alone exposes
the assigned GPU pair; the Guard uses `none` plus driver capabilities to get
the libraries without GPU device access. No runtime handlers, drivers or node
configuration were installed or changed.

The handback gate requires a new source EngineCore incarnation, a registered
source endpoint and the original survivor identity before source inference.
The source endpoint ID may remain stable across a container restart. A supervisor container's
successful startup probe can remain successful after its engine child exits;
Pod Ready alone is insufficient evidence that capacity has recovered. A regression
test covers this case.

## Second startup result and matched stats dependency

Attempt a2 passed native Guard initialization, loaded both models, and initialized
their engines. Both EngineCores then exited on their first telemetry collection:
`OffloadingConnectorStats` in the base image lacked `metric_sections()`, called by
the pinned KVCR adapter's `get_stats()`. The original six-file Python overlay did
not include the offloading stats implementation. No request or injected fault ran;
the Guards promoted empty pools, which is not recovery proof. Current/previous
logs are retained under a2 `startup-failure/`. Cleanup verified zero owned
Pods/claims/DGDs and released only this attempt's lease.

Fresh attempt a3 adds
`vllm/distributed/kv_transfer/kv_connector/v1/offloading/metrics.py` from the same
pinned adapter revision. The CPU gate now populates counter/gauge/histogram
stats and invokes the actual KVCR adapter's `get_stats()` namespace translation.
Native package versions and the base image stay fixed. The native runtime/DRA
probe is repeated in the fresh namespace, with raw logs and the observed
Succeeded Pod retained; NIXL destructor logs follow the JSON status, so receipt
extraction selects the status line rather than the final log line.
