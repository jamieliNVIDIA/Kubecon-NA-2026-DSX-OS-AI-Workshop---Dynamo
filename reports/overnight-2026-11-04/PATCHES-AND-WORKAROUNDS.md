# Current patches and workarounds

Inventory checked November 5, 2026 Pacific against the current source, frozen
manifests and accepted run evidence. This records what the workshop uses; it
does not refresh the status of upstream PRs. No new cluster run, package change,
commit or upstream submission was performed to assemble this inventory.

The largest custom runtime integration is Shadow's Super VL/GMS adapter.
Snapshot has a smaller remaining identity/offline bridge plus a backport of
already-merged code. KVCR uses an experimental combination of pinned upstream
packages and Python adapter files. The public take-home baseline has no runtime
overlay.

The earlier [same-node Guard trial](../receipts/2026-11-04-kvcr-guard-nightly.json)
also passed engine-failure cache retrieval and warm handback with explicit
routing. The later cross-node Demo 7 capture tested ordinary peer reuse only;
it did not repeat the Guard fault. Automatic failover and GMS/Shadow composition
remain separate gates.

## Runtime and package changes

| ID / where | What we apply | Why it exists | Evidence and disposition |
| --- | --- | --- | --- |
| R1. Common workshop image | A custom assembled image, pinned by `configs/super-vl-tp2-lock.json` to `e98d074e…`: vLLM nightly `43b4aaea3`, Dynamo source `ea23e513…`, GMS 0.9.0, KVCR 0.1.1, six upstream vLLM KVCR adapter files from `08567505…`, ModelExpress 0.6.0, NCCL 2.30.7, EFA userspace 1.49.0 and libatomic. | Provides a working combination of Super VL support, inference features and the cluster's EFA transport. This is dependency assembly and upstream-file backporting, rather than a fresh handwritten patch to the inference kernels. | [Build recipe](../../container/common-runtime.Dockerfile), [input builder](../../scripts/common_runtime_build.py), [pins](../../configs/kvcr-lock.json). Intro, MX, P/D, routing and request-continuity evidence uses this base without additional per-demo Python runtime patches. `common-runtime-qualified.json` describes an older Lightning TP1 test and is not qualification of all present Super VL compositions. |
| R2. Snapshot KV-only backport | One immutable ConfigMap mounts `dynamo/vllm/snapshot.py`. Its base is the module from merged Dynamo #15887, retaining the native pause controller and communicator checkpoint hooks. | The pinned image predates the KV-only wrapper needed to release request state without copying model weights to host memory during checkpoint preparation. | [Current profile](../../demos/snapshot/dgd-profile.json), [exact candidate/overlay](../../configs/dgd/workshop-snapshot-dgd-upstream/), [passing upstream-controller trial](../workshop-snapshot-upstream-controller.md). Same-node DGD/NVMe capture, restore, automatic replacement and fresh inference passed. Remove this backport only after a selected newer image passes the same lifecycle. |
| R3. Snapshot destination identity/offline bridge | In that same module overlay, copy allowlisted destination settings from Snapshot's PID-1 restore proxy to the restore-context file; restore the destination's explicit `HF_HUB_OFFLINE` value before normal registration. | The proxy bypasses Dynamo's old standby context writer. Otherwise restored code can retain source-Pod identity or lose the destination's offline policy. | [Bridge](../../scripts/snapshot_dgd_runtime_patch.py), [upstream scope](../2026-11-04-snapshot-upstream-status.md#open-upstream-workstream). This is the remaining custom Snapshot runtime change. Neal's separately owned upstream workstream is open; no upstream submission was made here. |
| R4. Shadow memory-budget API bridge | Shadow workers mount a patched GMS `integrations/vllm/patches.py` accepting `request_memory(..., external_weight_memory)` and accounting for external/shared weights. | The installed GMS wrapper accepted two arguments; selected vLLM passed three and failed before weight loading. | [Patch and rationale](../../configs/patches/shadow-gms-vllm031/README.md). Retained by the latest composed candidate. Initial Super VL writer/reader serving passed with it; full crash/recovery remains unqualified. General version compatibility is a potential upstream fix, subject to checking current upstream. |
| R5. Shadow private Humming workspaces | Patch GMS's loader to visit the exact Humming linear/MoE helper owners and move mutable lock/scratch tensors outside shared GMS weight pools. | Those runtime helpers write their workspaces. Sharing them as read-only weights caused CUDA write faults; a generic module tensor walk missed the nested MoE owner. | [Helper](../../demos/shadow/humming.py), [writer integration](../../demos/shadow/writer.py), [current accepted run](SHADOW-FULL-A4-REVIEW.md). Writer qualification and active/parked-reader startup passed; 120 workspace owners per rank are checked. Upstream direction: a supported mutable-workspace ownership contract, rather than retaining our exact helper-class hooks. |
| R6. Shadow processed-model descriptors and reader reconstruction | A patched loader plus `workshop_descriptors.py` exports validated final parameter/runtime metadata, prepares the reader's meta skeleton, calls the unchanged stock GMS materializer and rebuilds Humming/attention runtime objects and private workspaces. It preserves the observed routing-bias gradients/aliases. | Quantization changes shapes, strides and Python runtime state. Re-running incomplete weight postprocessing on a meta model did not reconstruct the writer's final state; parameter bytes alone were insufficient. | [Current v6 helper](../../demos/shadow/reader_descriptors.py), [v4 schema review](SHADOW-DESCRIPTORS-V4-REVIEW.md), [v6 repair](SHADOW-READER-V6.md). Latest overlay contains five files: `model_loader.py`, `patches.py`, `workshop_humming.py`, `workshop_descriptors.py`, `workshop_parameter_inventory.py`. The latter is metadata-only diagnostic instrumentation. All three retained coding responses and the parked reader passed in full-a4; promotion/replenishment remain open. This is experimental integration, not a ready-to-submit generic patch. |
| R7. Shadow v5/v6 reader callback repairs | Use the pinned native Humming config builder; restore exactly `w13_input_scale = None` and `w2_input_scale = None` as ordinary attributes for the reviewed final Humming layout. | Our first reconstruction callback and later native warmup queried a generic ModelOpt wrapper that reads raw-checkpoint attributes already consumed by Humming. | [v5 callback](SHADOW-READER-V5.md), [v6 source chain and actual-image CPU proof](SHADOW-READER-V6.md). Included within R6, not another independent runtime overlay. These repair our experimental adapter; an upstream-native defect must be separately reproduced before filing. |
| R8. KVCR preview bundle | In disposable containers, install KVCR 0.2.0 at `dd5df02…`, seven upstream vLLM adapter/event/metrics files at `a5db4c9…`, and matching official Dynamo/runtime `1.7.0.dev20261103` wheels. Keep the private base's native vLLM/NIXL stack. | New Guard/API contracts require matched source versions. The seventh file supplies the missing offloading `metric_sections()` API. The Dynamo wheels contain merged #15535, which fixes rejection of hybrid/recurrent KV events absent from the original base. | [Exact source lock](../../demos/kvcr/source-lock.json), [bootstrap](../../scripts/kvcr_guard_bootstrap.py), [nightly wheel pins](../../configs/kvcr-guard-nightly-runtime.json). Controlled cross-node peer reuse passed. Primarily a version/package integration gap; no separate local Rust fix or native-kernel replacement. A single public image with this exact combination is not qualified. |

## Environment and demo orchestration

| ID / where | Workaround and purpose | Current scope / removal condition |
| --- | --- | --- |
| E1. Model metadata and stable cache inventory | Pin a dedicated/owned cache's `refs/main` to the requested revision and verify the actual Dynamo metadata resolver offline. Finish ancillary model-file downloads before starting workers. | Registration can resolve metadata without carrying the engine's explicit revision; different cached refs or changing documentation/image assets can produce mismatched model cards. The take-home downloader creates a missing ref and refuses a conflicting one. KVCR's original admitted-cohort mismatch was repaired by a recorded B/frontend replacement after the cache settled, without weakening identity checks. See [take-home downloader](../../take-home/render.py), [KVCR investigation](KVCR-PREPARED-CHILD.md). Revision propagation is tracked in the saved upstream review under #11369. |
| E2. Snapshot capture helper | Use a CPU capture-only keepalive through supported `checkpoint.job.podTemplate`; retain source GPUs through artifact publication and verified NVMe staging, then release the helper. | Handles source-Pod lifetime during offstage preparation. It is absent from serving replicas. The stock 3,600-second Job deadline was retained; an attempted immutable-spec lifetime change was rejected and is not an active workaround. [Renderer](../../demos/snapshot/dgd.py). |
| E3. Snapshot local storage | Copy and hash the artifact, then attach an artifact-specific read-only NVMe clone inside the Snapshot agent's private mount namespace. Restore its EFS view during scoped cleanup. | Environment-specific way to test local storage against the installed EFS-backed setup. No shared Helm/PVC or agent-spec change, disk format or global cache flush. This is not part of the identity/offline upstream request. [Implementation](../../demos/snapshot/nvme.py), [qualification](../workshop-snapshot-dgd-nvme.md). |
| E4. EFA and Guard driver exposure | Use the existing driver-library-capable runtime handler and explicit EFA library/provider configuration. The CPU Guard receives driver libraries but no numbered GPUs; DRA controls engine GPU assignment. | LIBFABRIC needs `libcuda.so.1` even for DRAM registration. This is container runtime/library exposure, not GPU computation by the Guard or a new host-driver patch. [Guard renderer](../../demos/kvcr/guard.py), [image-only EFA installer](../../scripts/install_efa_image.sh). |
| E5. Persistent MX development RAM cache | An official ModelExpress server plus Redis retains CPU files. Custom seed/stage helpers copy the pinned model into RAM, verify authoritative HF/LFS/Git file hashes, stream all files to worker-local RAM and mount the resulting cache read-only for the unchanged native GMS loader. | Accelerates development preparation without assuming native GMS/MX loader composition. Merely setting a server-cache strategy could leave an existing absolute EFS path as the load source. Seed helpers handle centralized HF blob layout and distinguish Xet storage keys from full-file checksums. CPU and actual worker staging passed; matched startup benefit and native GMS/MX P2P composition are unqualified. [Notes](MX-DEV-CACHE.md), [seed](../../scripts/development/mx_cache/seed.py), [stage](../../scripts/development/mx_cache/stage.py). |
| E6. Durable demo controllers and tools | Run preparation/capture/cleanup in owned detached CPU containers on the jump host so VPN loss does not end orchestration. An owned derivative image adds curl. Full Shadow transport now binds the existing Linux Helm binary read-only at the Mac-specific path expected by the frozen native preflight, with an early same-image driver-values query. | These change presenter/development tooling, not inference code. Durable Snapshot execution passed. The Helm repair has focused tests and independent source review; root's manual same-image query passed, but the fresh packaged full-run check remains a separate gate. [Controller image](../../demos/snapshot/controller_image.py), [Helm review](SHADOW-FULL-HELM-REVIEW.md). |
| E7. Readiness, model admission and evidence guards | Wait for all relevant startup probes to settle; compare stable container identities rather than complete status dictionaries; check exact frontend model publication and both admitted workers; persist each completed coding response immediately. | Fixes to our observers, which previously rejected normal Ready/Started transitions or raced model registration. They do not relax native readiness, GPU/GMS identity or checksum checks. [Startup review](SHADOW-STARTUP-READINESS-REVIEW.md), [routing/KVCR notes](REVIEW.md). |
| E8. Take-home manifests | Use CRD-compatible `runtimeVersionOverride: 1.7.0` separately from the exact dev package version; select Pods by stable service/role labels; expose explicit run-as UID, with UID 0 used only for the reused root-owned workshop cache. | Manifest and environment corrections: CRD accepts X.Y.Z; Grove rewrites its managed-by label; the existing cache was root-owned. No chown or inference-image modification. The public baseline actually served and cleaned up; these settings do not qualify other storage permissions or advanced features. [Qualification](../../take-home/QUALIFICATION.md). |
| E9. P/D metrics and hybrid layout | Use `prometheus_mp` with a shared metrics directory for TP2; explicitly select the compatible Mamba convolution layout and LIBFABRIC/EFA transport. | The earlier single-process metrics exporter returned HTTP 500; the multiprocess backend is a configuration workaround. Layout/transport flags select the tested hybrid P/D path without patching its kernels. The frozen image's prefill-canary expiry noise remains visible; existing upstream #15594 was not backported during the benchmark. [Original TP2 finding](../2026-10-15-super-vl-tp2-retest.md), [current comparison and existing fix](disagg/RESULTS.md). |

## Configuration choices, rather than code fixes

- Intro and MX use eager, text-only inference to keep the coding-agent flow
  simple. Compiled P/D and benchmark profiles have different explicit cache and
  batching settings. Those profiles are not interchangeable startup controls.
- The P2P MX demo sets `MX_ARTIFACT_TRANSFER=0`: compilation-cache reuse is not
  part of that demo. Its EFA environment/discovery settings select the transport
  rather than modify the ModelExpress implementation. The separate compiled
  startup experiment uses the official MX server plus Redis, not a workshop
  replacement server.
- Exact GPU UUID/node placement, private image pull credentials and an existing
  shared cache are cluster preparation requirements.
- Shadow retains diagnostic settings including `CUDA_LAUNCH_BLOCKING=1` and an
  explicitly requested KV-memory flag. The requested 2 GiB value has not been
  established as the actual native GMS allocation cap; this remains an open
  interpretation, not a silently applied allocation fix or SLO result.
- No liveness workaround was applied to turn the failed C32 one-worker arm into
  a passing measurement. Its liveness restart remains a rejected result.
- Request continuity uses native retry/migration behavior. The stale SSE worker
  identity is documented and checked against frontend/backend traces; no
  response-metadata patch was installed to conceal it.

## Older paths still present in the repository

- Snapshot's old custom v3 pause controller is superseded in the canonical
  `demos/04-snapshot/run-dgd.sh` profile by the upstream KV-only backport. The
  older native application-checkpoint launcher and historical artifacts remain.
- Shadow's older `demos/08-shadow-engine/run.sh` still invokes the initial
  experimental candidate with a singleton meta-scale shape exception. It is
  distinct from the current `run-composed.sh` descriptor path.
- The latest composed Shadow path does **not** mount a modified GMS
  `client/torch/module.py` or apply the older scalar/FP8 materializer shims.
  It prepares validated final meta layouts before calling the stock materializer,
  preserving its shape/dtype guards. Early scalar-only/FP8 candidates and failed
  reader versions remain as historical sources/evidence.
- The old common-image KVCR 0.1.1/six-file adapter remains baked in the shared
  private base. Demo 7 overrides it inside its own containers with R8; the public
  take-home baseline uses its official image unmodified.

## Upstream versus workshop ownership

1. **Already merged, missing from selected base:** Snapshot KV-only behavior
   and Dynamo hybrid-event handling. Prefer release/image alignment after
   requalification rather than proposing duplicate changes.
2. **Remaining upstream integration:** Snapshot destination-context/offline
   handoff (Neal's separate workstream), GMS/vLLM API compatibility and complete
   processed-model/runtime/workspace reconstruction. Shadow's exact adapter
   implementation still needs generalization and actual recovery evidence.
3. **Primarily workshop/environment work:** NVMe mounts, cache staging, exact
   placement, driver-library exposure, detached controllers, Helm/curl packaging,
   observer guards and take-home label/UID/version fixes.

The [upstream candidate ledger](UPSTREAM-CANDIDATES.md) retains original findings
and saved upstream overlap. Historical rows are not evidence that an old patch
is still used, nor that a later upstream PR has remained open.
