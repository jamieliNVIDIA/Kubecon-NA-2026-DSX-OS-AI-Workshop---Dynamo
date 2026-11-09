# MX measurement and investigation history

This preserves earlier conditions, validated results and failed attempts.
The latest completed native-context summary is in REPORT.md.

## Completed weight-only comparison

One matched target pair reduced observed deployment-to-Ready from **524.67 s
to 315.51 s (1.66x)**. Both targets returned the exact expected `READY` response,
advertised the locked model, and had zero container restarts. This is a bounded
single-pair result, not a startup distribution or a production-readiness claim.

| Boundary | Native EFS loading | MX P2P weights |
| --- | ---: | ---: |
| DGD apply → observed Ready | 524.67 s | 315.51 s |
| DGD apply → first observed correct response | 534.53 s | 325.51 s |
| DGD apply → worker container start | 11.71 s | 12.37 s |
| vLLM model-loading phase, slower TP rank | 276.69 s | 53.72 s |
| NIXL tensor transfer per TP rank | — | 3.32 / 3.33 s |
| vLLM engine initialization | 146.67 s | 150.30 s |
| torch.compile, slower rank, included in engine initialization | 26.85 s | 28.54 s |
| Initial profiling/warmup, slower rank, included in engine initialization | 80.52 s | 82.25 s |
| CUDA graph capture, two passes, included in engine initialization | 22 s + 3 s | 22 s + 3 s |

The transfer logs show 1,869 tensors and 40.27 GB per TP rank, with approximately
97 Gbps logged per rank. Those 3.3-second transfers are a subphase of the
53.7-second model-loading interval; the loader also constructs and registers the
target tensors. Engine initialization then remains necessary. Do not sum nested
phase durations or present the transfer duration as complete startup time.

The first correctness request follows log/claim collection and port-forward
setup, so its timestamp is an upper bound on first-possible successful inference.
Ready polling uses five-second intervals. The complete JSON observations and
Kubernetes condition timestamps preserve those measurement boundaries.

## Matched identity and conditions

- Model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`.
- Revision: `8a115b9d966adce8c059a7bcf47f49a1e57957d8`.
- Runtime: `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Packages checked in that exact image: vLLM `0.31.1rc1.dev23+g43b4aaea3`,
  MX 0.6.0, Dynamo 1.6.0, NIXL 1.5.0.
- Each worker: TP2 H100, driver 610.57.04, max model length 8192,
  max sequences 4, max batched tokens 8192, GPU memory fraction 0.85.
- Source placement: `kubecon-nke-site-cp-0124`; both sequential target arms:
  `kubecon-nke-site-cp-0198`. Actual GPU UUIDs and DRA allocations are saved.
- Source bootstrapped once using MX's storage fallback, then stayed idle except
  normal health/canary activity and its tiny correctness probe. Source startup
  (556.55 s) is not the native target baseline.
- Both target arms used the same existing exact-revision EFS model cache.
  Serving metadata hashes match the lock; 88 staged checkpoint files total
  75,010,188,240 bytes. No HF download was part of these measurements.
- Filesystem page-cache state was uncontrolled and never globally flushed.
  This is neither a cold-download baseline nor a local-NVMe comparison.
- Every target Pod used fresh private vLLM, Triton, DeepGEMM and FlashInfer
  filesystem cache directories; artifact transfer was explicitly disabled.
- The native target used vLLM's native loader; the peer target enabled
  `--load-format modelexpress`. All other engine flags were matched.
- This batch used Kubernetes Service metadata discovery and NIXL LIBFABRIC/EFA.
  Both peer ranks selected the RDMA strategy; neither fell back to storage.
- There was no AgentX throughput load. The other GPU workstream was idle and
  paused large downloads during the timed comparison. No source-interference,
  latency-SLO, or steady-state-throughput claim follows from this result.

## Evidence

Raw evidence directory: `results/workshop-mx-startup-20261030-pair04/`.

- `spec.json`, `spec.sha256`, `model-lock.json`: frozen identity and procedure.
- `source.json`, `target-native.json`, `target-p2p.json`: authoritative JSON
  manifests; client and server dry-runs passed.
- `comparison.json`: complete target results and ratio.
- `startup-analysis.json`, `startup-summary.csv`: observed startup boundaries.
- Per-arm directories: full timestamped worker/frontend logs, phase events,
  Pod observations/events/conditions, DRA allocations, GPU UUIDs and response.
- Full command receipts and `evidence-sha256.json`: 435 files verified with no
  hash mismatches or untracked evidence additions after the batch completed.

Owned GPU Pods and ResourceClaims were checked absent after cleanup, and the
exclusive measurement lease was released to the round-robin workstream.
Earlier `pair01`–`pair03` directories preserve CPU-only preflight failures
(Kubernetes YAML boolean parsing, then an optional missing README); no GPUs ran.

## Native-context artifact comparison: failed coordinator precondition

The installed MX 0.6.0 wheel contains handlers for torch.compile/Triton,
DeepGEMM, TileLang, CuTe DSL, FlashInfer kernel caches and applicable persistent
autotune files. That list is installed code capability, not proof that every
cache type is produced or reused by this exact model/backend configuration.

Its Kubernetes Service metadata path publishes weight manifests only. NIXL
artifact discovery requires a central metadata service. The isolated candidate
uses digest-pinned official MX server 0.6.0 plus Redis; no shared operator,
cluster-wide CRD, storage configuration or runtime upgrade is involved.

A fresh matched native-context matrix is prepared for storage, peer weights,
and peer weights plus artifacts, conditional on the AgentX workstream's serving
qualification. All participants share an explicit native-context compile-config
digest. The result must include artifact publication/install, both ranks
selecting the installed cache directories, and actual engine cache-hit logs.
File transfer alone will not count as effective compiler-cache reuse.

The isolated coordinator passed CPU-only preflight in
`results/workshop-mx-startup-20261030-artifact02/`: both service Pods became
Ready and the locked workload image successfully issued `ListSources`. Its
exact vLLM compiler sources and hashes were captured, confirming the positive
engine cache-load markers used by the planned validation. `artifact01` retains
an earlier CPU-only output-framing failure; its metadata RPC itself succeeded,
and its CPU Pods were cleaned.

The artifact02 controller ran under this workstream's GPU lease, following an
explicit RR-approved turn reorder during CPU-only local
trace reconstruction. No competing GPU or bulk shared-storage/network activity
is running. The source bootstrap passed at 587.23 s apply-to-Ready: the model API
advertises context 1,048,576, the exact expected response completed, and there were
zero restarts. It logged 26.73 GiB available KV memory per rank and a 13,178,693-token
cache with max sequences 4. Compiler artifacts were actually published:
torch_compile 37.30 MiB, Triton 62.57 MiB and FlashInfer 2.04 MiB.

The native-storage target exposed an unintended configuration interaction:
legacy MODEL_EXPRESS_URL also activated Dynamo's Rust model-download path. The
isolated coordinator's cache emptyDir exceeded its 2 GiB limit and the Pod was
Evicted at 00:55:44Z. The target's metadata request waited 123 seconds before
falling back to the existing offline checkpoint. This is a failed precondition
for clean matched startup timings, not an artifact-transfer or cache-hit result.

The sole owned controller was interrupted for its finally-cleanup and GPU
handoff to RR. Frozen artifact02 parameters remain unchanged; terminal Pod
status, native target logs and a matrix-failure receipt are preserved. There is
**no target artifact cache-hit or artifact-speedup result**. The completed 8k
weight-only result remains separate and valid. A fresh metadata-only worker
environment must be verified against the installed Rust/Python env handling
before another matched artifact attempt.

The corrected `artifact03` candidate removes legacy MODEL_EXPRESS_URL and uses
MX_SERVER_ADDRESS for the Python metadata client, with HF_HUB_OFFLINE enabled
on the coordinator. Primary Rust/Python source inspection confirms these
separate resolution paths; the fresh run preserves copies and source pointers.
The recorded runtime's [Rust hub source](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/hub.rs)
overrides its client endpoint through the legacy URL; the
[MX Rust connection default](https://github.com/ai-dynamo/modelexpress/blob/v0.6.0/modelexpress_common/src/config.rs)
uses localhost. The exact installed Python client separately supports
MX_SERVER_ADDRESS, as captured in the runtime-capability evidence.
Its CPU cluster preflight stopped before namespace creation during the tunnel
outage. At the 2026-10-31T16:41Z reconciliation, no corrected GPU arm has run;
the RR workstream retains its lease pending access recovery. Do not interpret
the prepared candidate as measured cache reuse.

Offline validation of the corrected source and all three target manifests
passed, including model/runtime identity, identical engine flags, a loader-only
native-versus-peer difference and an artifact-opt-in-only target difference.
All 17 candidate evidence files are hashed and verified. Exact recovery and
execution gates are in RESUME.md. RR reports both SSH routes timing out with
the prior VPN route absent; the latest bounded API check still returns
connection refused. Cluster reachability is the external blocker.
All 979 saved evidence files across successful, failed and prepared attempts
were hash-verified with zero mismatches; see integrity-summary.json.

The native-context source's correctness request was small. Its advertised
1,048,576-token context and initialized cache fit were verified; this was not
an end-to-end 1M-token prompt or a canonical AgentX replay.

The separate matrix will retain source/target engine and model identity. Its
speedups will be computed within that configuration, independently of the
completed 8k pair. Artifact reuse transfers filesystem compilation/kernel/cache
files; it is distinct from restoring initialized engine state with Snapshot.

## Remaining measurement work

1. Native-context serving qualification and source artifact publication passed.
2. Resolve the isolated coordinator's model-download coupling CPU-side; prepare
   a fresh immutable matched matrix and retry in a coordinated later GPU turn,
   reporting transfer, actual cache hits, and full readiness separately.
3. Add paired repetitions if time/resources permit. The completed comparison is
   N=1 and must retain that qualification.
4. A later source-interference experiment, if run, must use the pinned real
   AgentX workload under the same native-context configuration. None is claimed.

## November 2 resume: corrected candidate interrupted by connectivity

Artifact03's frozen source/helper hashes matched, and its repeated CPU
preflight passed: exact model metadata/checkpoint files, runtime/package/image
identity, legacy URL absence, Python coordinator resolution, ListSources and
all effective manifest dry-runs. Redis/MX were healthy with zero restarts.

After RR completed its first C1 pair and explicitly handed over zero owned GPU
Pods/claims at 07:34:22Z, the single artifact03 controller acquired the lease.
Its source passed at **588.13 s apply-to-Ready**, advertised native context
1,048,576, returned the expected answer and had zero restarts. Publication
included torch_compile 37.30 MiB, Triton 62.57 MiB and FlashInfer 2.04 MiB. The
corrected coordinator did not route model downloads during this observed run.

The native target loaded weights in **278.09 s** on the slower rank, compiled
in 26.60 s, completed initial warmup in 80.57 s, and was capturing CUDA graphs
when API connectivity failed. Logs retain the last observed 23-second graph
capture at 07:53:40Z. These are partial initialization observations, **not** a
complete native-target startup/correctness result. No peer or artifact target
started, so there is no native-context speedup or effective artifact reuse result.

TLS handshake timeouts began at approximately 07:54:00Z, followed by loopback
connection refusal. The controller exited code 1; collection and finally-cleanup
also failed to reach the API. A bounded same-host SSH restart timed out.
The MX lease remains retained; remote GPU cleanup is unverified. RR's C4 arm
must wait for verified recovery/cleanup and explicit handoff. See RESUME.md.

Evidence is preserved in artifact03: source result/allocation/logs, compiler
publication log, CPU preflight receipt, native progress log, failed command
receipts, `connectivity-failure.json`, controller identity and local integrity
inventory. This interrupted attempt does not alter the valid 8k pair04 result.

## November 3 recovery and fresh retry

The interrupted artifact03 run was collected and cleaned after access returned.
Its pre-recovery inventory was copied before changes and all 322 previously
hashed files matched. Current remote Pods, DGDs, ResourceClaims, services,
events and logs were collected into `recovery-20261103-resume02/`. At
22:27:38Z the scoped recovery helper independently verified zero GPU Pods,
zero ResourceClaims and zero graphs before releasing the retained lease; it
also cleaned the isolated coordinator/Redis Pods. RR received explicit handoff
for C4. This closes the cleanup uncertainty, without creating a target startup
or artifact-reuse result for artifact03.

The fresh `results/workshop-mx-startup-20261103-artifact04/` candidate preserves
the exact specification bytes and five effective manifests after owned-namespace
normalization. Its CPU preflight passed with exit 0 before RR's C4 timing, including exact
model/runtime checks, metadata discovery and all 15 dry-runs. The next MX GPU
turn requires C4's explicit cleanup/handoff. No original model,
context, runtime, hardware, workload or treatment setting was changed.

The reviewed continuation driver stopped during C4 at approximately
2026-11-03T23:01Z after API TLS timeouts and loopback tunnel refusal. It never
entered the MX stage. Artifact04 therefore remains CPU-prepared only: all 82
sealed files still match, and no source/target GPU result directory exists.
RR retains its lease pending remote collection/cleanup; no artifact04 GPU
workload was started. Current remote coordinator health is unverified during
this shared access outage. C4 completion and verified handoff remain prerequisites
for the artifact04 matrix. There is still no compiler-cache reuse/speedup result.

## Stable observer deployed November 3

A detached, bounded controller started on the existing bastion at 23:34:29Z,
using a pinned native-amd64 Python controller image and current PyYAML 6.0.3 pure
sources. The exact logical workspace path and all consumed source/reference
hashes are preserved. Existing host kubectl/kubeconfig are mounted read-only;
no credentials, inference weights or dataset were copied and no RBAC changed.
The recovered C4 first arm remains accepted unchanged (122 requests, zero errors),
with its original worker retained for the second arm. Controller relocation and
the idle gap are recorded separately from scientific settings.

The cluster-local AIPerf client, model/runtime, hardware, workload and benchmark
parameters are unchanged. All three artifact04 target startup arms will be
measured by this same stable observer and compared only within that group.
The old 8k pair remains a separate result. At the launch snapshot, C4 r2 was
initializing its second worker and no artifact04 GPU arm had started; deployment
of the controller establishes neither cache reuse nor a speedup.

Provenance and current timestamped snapshots are under
`results/workshop-stable-controller-20261103/`. The local lease is a delegation
fence; only the remote controller may mutate GPU resources. Final result import
must retain original local preflight evidence as well as the new remote outputs,
then verify cleanup/integrity before removing the fence.
