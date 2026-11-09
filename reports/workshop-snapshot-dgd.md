# Same-node Snapshot recovery through Dynamo

This qualification extends the native-vLLM Snapshot proof to a DGD-managed
worker and an unchanged Dynamo HTTP frontend. **Passed on November 4, 2026:**
the operator captured an initialized Super VL TP2 worker, restored a serving
replica, and automatically restored its replacement after worker Pod deletion.
Both replicas returned correct code through the same frontend. This qualifies
the experimental pinned configuration on EFS, on the same node and GPU pair.
47 scoped offline tests, exact-image CPU inspection, cache verification, and
client/server admission also passed.

The [actual qualification CLI transcript](../demos/transcripts/live/04-snapshot-dgd/20261104-a3/qualification.txt)
and [provenance/timing manifest](../demos/transcripts/live/04-snapshot-dgd/20261104-a3/qualification.json)
are shareable. These are separate from the existing native demo 4 main-panel
recording. The presenter runner has not yet been changed to this DGD flow.

The [November 4 upstream review](2026-11-04-snapshot-upstream-status.md) identifies
merged KV-only capture/CuInterpose work, existing restore-context machinery,
related open PRs, and the proxy/context and offline-policy gaps still found in
the checked main revision. The complete adapter is not all new functionality.

The [follow-up upstream-controller trial](workshop-snapshot-upstream-controller.md)
also passed initial and automatic-replacement inference in the same image.
Use that candidate for further workshop integration: it keeps upstream's native
pause/resume controller and only our destination identity/offline bridge.
This report retains the earlier v3 configuration and its original measurements.

## Measured result and workshop implications

Run `results/workshop-snapshot-dgd-20261104-a3`, namespace
`dynamo-ft-20261104t205143z`, used the [frozen candidate](../configs/dgd/workshop-snapshot-dgd/).
The DGD, frontend Pod, frontend Service, checkpoint/content, node and physical
GPU pair stayed unchanged across replacement. The worker Pod UID changed from
`25f8eeef-ea2d-402c-9218-b384001f94f3` to
`1887a296-3ccc-4ddc-98fa-c36a203d33a4`; its reported decode-worker identity
changed from `852328509295357` to `741928725038905`. Both fresh streaming chat
requests returned `def add(a, b): return a + b` with a successful stop and DONE.

| Boundary | Initial restored worker | Automatic replacement |
| --- | ---: | ---: |
| Pod creation to agent Restored condition | 328 s | 340 s |
| Pod creation to Ready | 340 s | 352 s |
| Deletion intent to first observed successful frontend response | — | 374.72 s |

Replacement deletion intent was recorded at **21:31:49.908 UTC**, replacement
Pod creation at **21:31:50**, Restored at **21:37:30**, Ready at **21:37:42**,
and the verification response completed at **21:38:04.627**. The last boundary
includes polling, API/port-forward setup and the verification request; it is
not a continuous availability probe or the earliest possible response time.
These are single-run EFS observations, without a matched cold-start control.
They establish functionality, not a Snapshot speedup over the other demos.

The automatic checkpoint became Ready at **21:25:14**, 26m48s after its API
object was created. Initialization, capture and slow EFS publication belong
offstage. CUDA checkpointing and CRIU had completed earlier; artifact readiness
remained a distinct gate. Keep the creating DGD alive through the onstage
replacement: retained automatic artifacts remain bound to that DGD's UID.

The functional DGD/frontend gap is closed for this pinned adapter configuration.
Remaining workshop work is presenter/tmux wiring and a new DGD qualification
using pre-staged NVMe. The native NVMe demo's 37.3s agent / 41s Pod-to-Ready
result is a different artifact and execution path. No NVMe DGD time was measured.
Cross-node restoration, KV preservation, in-flight migration and composition
with GMS/Shadow remain outside this result.

## Tasks

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
  - Pinned Super VL revision/image, vLLM TP2, two exact H100 UUIDs on cp-0124.
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Adapt the more specific saved `snapshot-super-vl-tp2-r610` DGD.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
  - Pure renderer in `scripts/workshop_snapshot_dgd.py`; frozen per-run JSON/YAML.
  - Generated candidate manifests may be copied into `configs/dgd/workshop-snapshot-dgd/`.
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
- [x] Hand off to `deploy_dynamo` or `kubectl apply`

The first attempt (`20261104-a1`) was deliberately stopped before capture:
the operator excludes ordinary serving sidecars from capture jobs. The fresh
attempt puts the CPU publication helper in the supported
`checkpoint.job.podTemplate` override and verifies its actual presence early.
Its predecessor's source Job was removed by exact UID and both GPU reservations
were released after zero-Pod/claim/DGD cleanup proof. The cleanup harness now
records parent/source identities before orphaning retained SnapshotJobs and
deletes source Jobs before removing that parent relationship.

Attempt a2 completed capture and engine restoration: the restore proxy identity
bridge and engine wake passed. Dynamo model registration then stalled in an
external Hugging Face metadata lookup after the older lifecycle cleared
`HF_HUB_OFFLINE`. A subsequent CPU probe found a second cache issue: without
`refs/main`, the offline unversioned resolver selected a different cached
revision (`da5b...`) instead of the engine's locked
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`. No successful frontend request was
reported for a2; it qualifies the observed restore stages only.

The a3 runtime overlay preserves the replacement proxy's explicit offline policy
before registration. Separately, root created the previously absent `refs/main`
inside the owned `20261015-super-vl-tp2` cache with exclusive creation, pointing
to the locked revision after verifying its metadata hashes. No existing ref or
snapshot was overwritten. A pinned-image CPU probe using the actual offline
`dynamo.common.model_fetch.fetch_model` then resolved the exact locked snapshot.
The current a3 capture uses immutable ConfigMap `snapshot-dgd-runtime-patch-v3`;
its full patch digest is retained in that run's frozen spec. The frozen a2/a3
manifests and earlier evidence remain unchanged.

## Frozen candidate and lifecycle

The worker uses a root-prepared immutable ConfigMap that overlays only the
runtime's `dynamo/vllm/snapshot.py`. Its exact hash and runtime module path are
frozen with the model, source template, node and GPU UUIDs before deployment.
The image itself is unchanged; report this as an experimental runtime overlay.
The overlay also bridges a protocol-version difference: the newer Snapshot NRI
restore proxy bypasses the older Dynamo restore-standby entrypoint that produced
`restore-context`. The patch reconstructs that context only from whitelisted
PID 1 proxy environment after restoration, verifies the expected proxy command
and a replacement Pod UID, then uses the existing Dynamo configuration-refresh
path. Falling back to captured Pod identity is forbidden. Live initial and
replacement inference passed with the v3 adapter; this does not establish
unmodified-runtime compatibility or production readiness.

Capture remains compiled TP2 with 8k context, text-only input, four sequences,
GPU memory fraction 0.65, `spawn`, and the CuInterpose multi-GPU annotation.
The worker requests 256 GiB RAM with a 512 GiB limit. A CPU-only keepalive
container prevents terminal-source timeout during slow EFS publication. The
operator's SnapshotJob must explicitly capture `main` only. Verification stops
the owned helper only after the durable PodSnapshot/content become Ready.
The helper is supplied through
`experimental.checkpoint.job.podTemplate.spec.containers`, the pinned operator's
capture-Job override. It has no GPU claim and does not appear in serving
replicas. Verification fails immediately if the generated SnapshotJob or source
Pod omits it, before waiting for model initialization/capture.

The first live candidate (a1) placed this helper in the serving Pod template.
The pinned operator intentionally copied only `main` into its SnapshotJob, so
that candidate lacked the required publication helper. It was stopped before
capture. Its frozen manifests/evidence remain unchanged; a2 and a3 use the
capture-Job override.

The pinned operator binds an automatic checkpoint to the creating DGD UID.
Its retained automatic checkpoints cannot be reused as an explicit
`checkpointRef` by a newly created DGD. Prepare the workshop's automatic
checkpoint offstage and retain that DGD through the replacement demonstration.
Deleting the qualification DGD retains its artifact for inspection but does not
make it a portable checkpoint for a later graph incarnation. This follows the
[pinned operator's managed-restore policy](https://github.com/ai-dynamo/dynamo/blob/2093662a4d4e5fd318732935213dde08dc7be818/deploy/operator/internal/checkpoint/native.go).

The harness never acquires, transfers, removes or releases the shared GPU
lease. Its caller must hold `workshop-snapshot-dgd` ownership for this exact run
before deployment, inference, replacement or cleanup. The concurrent compiled
baseline/MX controller's fence must remain intact until independently verified
completion and cleanup.

## CLI

Initial `render` requires `--run`, `--patch-configmap`, `--patch-sha256`, and two
`--gpu-uuid` arguments. The default runtime module path was inspected in the
pinned image: `/usr/local/lib/python3.12/dist-packages/dynamo/vllm/snapshot.py`.
Use `--snapshot-module-path` only for a separately inspected candidate.

- `render`: local, pure object construction and frozen manifest/spec files.
- `prepare`: CPU-only namespace/storage/auth and exact cached-model verification.
- `dry-run`: Kubernetes admission only, no GPU allocation or DGD creation.
- `deploy`: one submission of the frozen DGD and exact GPU claim template.
- `status`: read-only inventory and durable snapshots of relevant objects.
- `verify`: observe operator capture, restored worker and fresh coding response.
- `replace`: delete only the qualified worker using a UID precondition, then
  verify its controller's replacement through the same frontend.
- `cleanup`: stop owned DGD/capture workloads, preserve snapshots/artifacts,
  verify no remaining owned GPU claims, retain the caller's lease.

Cleanup first persists exact DGD/SnapshotJob/source-Job UIDs and their ownership
chain. It stops the recorded source Jobs before orphaning their SnapshotJobs;
Kubernetes orphan propagation removes child owner references. A saved cleanup
plan permits interrupted cleanup to resume using those exact UIDs after refs
are removed, while refusing any reused resource name with a different UID.
The first a1 cleanup exposed the former reversed order; it retained the lease
on uncertainty and required an independently audited source-Job cleanup.

Future CPU preparation requires `refs/main` to match the locked revision and
runs the pinned runtime's actual `fetch_model` resolver with
`HF_HUB_OFFLINE=1`, asserting the returned directory is exactly the locked
snapshot. Shard sizes and metadata hashes are checked in the same read-only
cache probe. The staging receipt includes the ref value, resolved path, offline
policy and resolver identity. GPU deployment refuses older shard-only receipts.
This preflight never repairs or creates refs; a missing or mismatched ref stops
preparation for review. These safeguards were added while a3 was running;
they did not change its frozen configuration or live processes.

## Acceptance

1. Operator-managed checkpoint is Ready and the serving Pod is distinct from
   the capture Pod, with `nvidia.com/Restored=True` and the exact artifact binding.
2. Actual image digest, node and physical GPU UUID pair match frozen inputs.
3. Frontend advertises the expected model and a fresh streaming coding request
   returns correct Python `add(a, b)` code, a stop finish reason, no error frame,
   `[DONE]`, and a Dynamo worker identity.
4. Delete only the owned worker. Its actual controller creates a new Pod UID
   restoring the same artifact on the exact GPU pair. DGD, frontend Pod and
   frontend Service identities remain unchanged.
5. A fresh request through that frontend returns correct code and a different
   decode-worker identity. No in-flight request recovery is inferred.

The receipt distinguishes fault/deletion request, replacement Pod creation,
agent-restored condition, Pod readiness, and first successful frontend request.
Checkpoint creation/publication and operator/controller latency remain visible;
these boundaries are not interchangeable with the native demo's agent timing.
Cross-node restoration, production readiness, cache persistence, Shadow/GMS
composition and in-flight request migration are outside this qualification.

## Evidence

Each fresh run retains a frozen model lock, patched-module hash, effective
manifest, command receipts, timestamped inventories, Snapshot/content identity,
physical allocation evidence, original/replacement identity and actual SSE
responses. Capture and verification save actual main/frontend/helper logs and
bounded Snapshot agent/operator and Dynamo operator logs before cleanup.
`replacement-timing.json` reports the full service-recovery boundary.
Status and cleanup receipts remain separate from deployment submission.

Offline qualification checks cover pure rendering, exact allocation selection,
runtime-module identity, foreign-lease preservation, retained SnapshotJob owner
identity, source-helper publication gates, controller UID lineage, Pod-name
reuse, unchanged frontend/artifact requirements, timestamp precision, and actual
stream completion semantics. These tests do not qualify live capture/restore.

## Cleanup and final audit

The orchestrator finished successfully at **21:38:34 UTC** and released its
matching local and remote reservations after owned workload cleanup. The
independent **21:40 UTC** audit verified all three nodes Ready, zero active GPU
Pods, zero ResourceClaims/DGDs, absent reservations, unchanged Snapshot agent
UID/spec, the original native Snapshot still Ready, and the new DGD Snapshot
and content still Ready.
Kernel logs contained the same 88 historical Xid messages and no new messages.
The audit compares full diagnostic-message multiplicities because `dmesg`'s
rendered historical wall-clock timestamps shifted by a microsecond between reads.

Private proof: `results/workshop-snapshot-dgd-20261104-a3/final-cleanup-proof.json`.
Independent read-only evidence copies and their SHA-256 values are retained in
that run's `qualification-package-evidence/` and the shareable manifest.
The earlier failed timestamp-string audit is retained separately, as are the
unsuccessful a1/a2 trials. Shared operators, drivers, allocator, storage settings,
and the original native Snapshot/recording were not changed by this trial.
