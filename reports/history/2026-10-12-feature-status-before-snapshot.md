# H100/EFA feature qualification — October 12, 2026

Subsequent authorized update: Dynamo platform is now **1.5.1**. All focused
feature retests passed, including the public 1.5.1 runtime and ModelExpress 0.6.0.
KVCR required a worker-only 180s canary timeout for first-use JIT; its adjusted
retry and idle health check passed. See `dynamo-upgrade.md` for the latest results,
runtime defaults, frozen evidence and cleanup. The findings below retain the
original run's software pins and scope.

Shadow Engine failover was subsequently added. Its manifest dry-runs and
runtime-entrypoint inspection passed; live recovery is blocked because GPU
DRA allocation is disabled. See `shadow-engine-failover.md` for the test and
provisioning gap. Shared allocator configuration was not changed.

Snapshot infrastructure was subsequently reviewed, approved and installed with
Dynamo 1.5.1 on one node. See [the October 13 Snapshot qualification
result](../2026-10-13-snapshot-status.md); the baseline table below preserves the
original run's outcome.

Times in raw receipts are UTC (October 13). These are bounded feature tests,
not peak throughput measurements or workshop sizing benchmarks.

## Cluster and software

Three Ready AWS nodes, each with 8 H100 80 GB GPUs and 32 EFA resources:
`kubecon-nke-site-cp-0124`, `kubecon-nke-site-cp-0198`,
`kubecon-nke-site-cp-0942`. Driver `580.173.02`, Ubuntu 24.04.4,
containerd 2.3.5, API Kubernetes 1.34.2 and kubelets 1.34.11.

Existing Dynamo platform 1.4.2, Grove `v0.1.0-alpha.12`, KAI `v0.14.1`,
GPU Operator 26.7.0, EFA device plugin app 0.5.20/chart 0.5.29, EFS CSI 3.5.1.
KAI admission uses the existing `dynamo` queue and `kai.scheduler/queue` label.
No shared queues, operators, drivers or host configuration were changed.

The EFA device plugin works for ordinary `vpc.amazonaws.com/efa` resource requests;
EFA DRA is not required by these tests. The installed NVIDIA DRA component exposes
compute-domain support rather than GPU allocation for this workload.

Dynamo uses Kubernetes discovery, TCP requests and ZMQ events here. These runs
have not required etcd or NATS.

## Preferred model and runtime

All model-serving tests use
`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
`bee7596271d1495f6992ae224aefde4410e816b8`. The exact 52 weight files total
21,561,882,284 bytes. Ungated model; no new HF token needed.

The H100-specific development runtime is
`nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.5.0-nemotron-3.5-lightning-dev.1`,
observed digest
`sha256:a5f95c0e8d0a8c116e6c8a213157ee4338fe066022f8db19b41e37a0ce0c9fe4`.
Its installed packages report Dynamo 1.4.0, vLLM
`0.26.1rc1.dev306+gcb8104839`, NIXL 1.3.1 and ModelExpress 0.5.0.
A model image tag is not a reliable substitute for inspecting package versions.

On H100, the NVFP4 model uses Marlin weight compression with higher-precision
compute. It loaded about 17.84 GiB of weights and fit on one GPU.
Tests use TP1, context 4096, at most 8 sequences, GPU utilization 0.65 and
no speculative draft. This verifies feature functionality, not the complete
DSpark recipe or performance.

## Verified outcomes

| Feature | Result and evidence |
| --- | --- |
| GPU runtime | GPU arithmetic and NIXL plugin inspection passed on all three nodes. |
| EFA/NIXL | VRAM payloads at 1, 16 and 64 MiB transferred correctly over LIBFABRIC/EFA across all three unordered node pairs. One GPU and four EFA devices allocated per endpoint. |
| Shared storage | Two explicitly different nodes concurrently wrote and verified each other's 4 MiB data through the EFS CSI mount. |
| Aggregated serving | Two TP1 workers on different nodes; preferred model registered and returned `READY`. |
| KV-aware routing | Two unique prefixes, six unforced repeats; all requests selected the worker holding the relevant prefix and reused 2176 cached tokens. Frontend applied two new KV store events. |
| Disaggregation | Cross-node prefill/decode returned expected outputs for short and long prompts. Decode recorded 72,155,136 newly transferred KV bytes in two completed transfers, 2638 externally supplied prompt tokens, zero failed transfers and zero failed notifications. |
| ModelExpress P2P | Source on node 0124, receiver on 0198. Receiver imported 761 tensors / 18.87 GB via LIBFABRIC/EFA, used no disk fallback and generated `READY`. Transfer log reported 2.07 seconds; this is a single functional run, not a performance qualification. |
| Grove/KAI | Owned four-clique gang became Ready; scaling group 1→2→1 succeeded. Dummy GPU members tested scheduling; aggregated/disaggregated real-model DGDs also use existing Grove integration. |
| Engine sidecar | Passed: official CPU sidecar 1.5.1 beside stock vLLM 0.28.0, same preferred model, registered through Dynamo and returned `READY`. Engine has no installed ai-dynamo package; GPU allocated only to engine. |
| KVCR | Passed: source on 0942, destination on 0198; five transferred blocks and 33,423,360 bytes matched across the peers over LIBFABRIC/EFA. Destination reused 2176 tokens and returned `READY`; no failed or partial remote deliveries. |
| Snapshot | Blocked: no snapshot-agent DaemonSet and no enabled checkpoint configuration in the existing Dynamo operator. For the installed 1.4.2 integration, that existing operator supplies orchestration; an additional standalone Snapshot operator is not required. No checkpoint/restore was attempted. |

## Provisioning implications

| Topic | Minimum useful functional topology | What DSX must provide |
| --- | --- | --- |
| KV routing | Two workers, one H100 each, plus CPU frontend | Prefix-cache-capable backend with actual KV events; discovery RBAC and pod connectivity. No RDMA requirement for routing itself. |
| Disaggregation | One H100 prefill and one H100 decode on different nodes | EFA devices allocated to each worker, compatible LIBFABRIC/NIXL plus AWS EFA userspace inside the image, pod metadata/control connectivity. Four EFA resources per GPU were tested. |
| ModelExpress P2P | One source and one receiver, each one H100 on different nodes | Matching model revision/quantization/layout and runtime; source-only Kubernetes Service for metadata, EFA/NIXL data plane, enough host RAM for loading and image/model access. The tested decentralized backend needs no Redis, additional server or CRDs. |
| KVCR | Two workers for remote cache reuse; one H100 each was tested | Matched Dynamo router-hint support, vLLM adapter and KVCR/NIXL versions, host-pinned primary offload memory, peer control ports and EFA-capable NIXL backend. This test allocated 4 GiB primary host offload capacity per worker and four EFA devices. Package presence alone is insufficient. |
| Engine sidecar | Stock engine with one H100 and a separate CPU-only sidecar in the same Pod; CPU frontend | Native engine gRPC interface, matched sidecar protocol, startup/readiness settings and sidecar discovery identity/RBAC. Aggregated serving does not need EFA. |
| Snapshot | Single-node TP1 capture/restore; TP2 depends on implementation/version | Current dev workflow needs a compatible Dynamo integration plus Snapshot operator, privileged agent and artifact storage. Dev recipes are absent at v1.5.1; pin a complete compatible build before installation. Requires infrastructure approval. |
| Grove | CPU controller and admitted GPU gang | Existing Grove/KAI controllers, queue and admission labels. Basic gang/scale passed; topology placement, quotas, reclaim and autoscaling were not qualified. |

No multinode NVLink is needed for these TP1 tests. A two-GPU model can use
intranode TP2; validating that configuration would be a separate test.

KVCR used Dynamo 1.6.0 built from the exact public quick-start revision,
vLLM `0.31.1rc1.dev23+g43b4aaea3`, KVCR 0.1.1, NIXL 1.5.0 and NCCL 2.30.7.
The cluster operator remained 1.4.2. `configs/kvcr-lock.json` records the source
pins and base-image digest. The tested runtime exposes source-write bytes as
`vllm:kv_offload_tiering_write_bytes_total`, paired with destination
`vllm:kv_offload_tiering_read_bytes_total`, both for tier `1:kvcr`.
This differs from the older byte-counter name shown in the quick-start guide.
Unused local cascade failures can occur in this peer-only configuration; the
remote delivery counters are the qualification criterion. No local persistence,
Guard recovery, G3 storage, eviction stress or broad context/TP coverage was tested.

The sidecar result covers aggregated vLLM serving only. Sidecar disaggregation,
KV routing parity and SGLang were not qualified. Stock vLLM's native gRPC listener
must be reachable on the Pod IP for Kubernetes's gRPC health probes; the sidecar
uses loopback to connect to it. Its CPU container also needs the model/tokenizer
cache and explicit Kubernetes pod identity for discovery.

The baseline Dynamo images did not include EFA userspace. The saved entrypoint
installs checksum-pinned AWS EFA userspace 1.49.0 inside each disposable Pod,
with kernel module and host-limit changes skipped. A reusable workshop image
should bake in those libraries rather than install them at every startup.

The harness requests 4 CPU cores / 64 GiB host RAM per model worker, with a
128 GiB host-memory limit and 16 GiB shared-memory volume. Frontends request
1 CPU / 4 GiB and limit memory to 8 GiB. The engine sidecar requests an
additional 1 CPU / 1 GiB and limits memory to 4 GiB. These are tested resource
settings, not established minimums. The native NIXL banner in the baseline
runtime reports 1.3.2 although its Python package metadata reports 1.3.1.

The test containers use UID 0 for EFA package installation and EFS cache writes,
with IPC_LOCK/SYS_RESOURCE capabilities on workers; no host mounts, host PID
namespace or privileged serving Pod was required. A non-root workshop image
should bake in EFA userspace and provision compatible EFS directory ownership
before serving. Snapshot's privileged agent is a separate requirement.

EFS exists as a static Retain PV/PVC; no RWX StorageClass is installed. We created
an owned static Retain PV/PVC against the same existing filesystem and wrote only
under `feature-tests/<run>/`. Kubernetes PV capacity is a placeholder for EFS,
not a quota. Snapshot's automatic PVC provisioning will need a suitable class
or an explicitly prebound artifact claim. EFS cross-node correctness has passed;
sustained model-load and checkpoint throughput have not been qualified.

The current dev guide documents single-node multi-GPU TRT-LLM capture with eight
B200s. Its recipes exist on Dynamo main but return 404 at v1.5.1, whose platform
depends on Snapshot 0.1.0. Snapshot's published/main limitations still say
single-GPU only; the newer recipe qualification is linked to an open PR and a
different development build. Resolve this version boundary before installing.
Neither source qualifies H100/Nemotron TP2 or establishes a required driver
upgrade for that exact path. Our driver 580.173.02 meets the general TP1 baseline.
See `reports/snapshot-enablement.md` for the current proposal, memory budgets,
and source pins. Jump-host access recovered after the user's network change;
the current Snapshot preflight completed at 2026-10-13 04:59:07 UTC and reconfirmed
the missing agent, Snapshot operator, SnapshotJob CRD, and checkpoint enablement.
See [compatibility](https://docs.nvidia.com/dynamo/reference/compatibility) and
[Snapshot deployment prerequisites](https://docs.nvidia.com/dynamo/dev/kubernetes/model-deployment/model-loading/dynamo-snapshot-experimental).

## Durable evidence

- Inventory: `results/20261013T022357Z-inventory/`.
- Model/storage/serving: `results/20261013t023201z-features/`.
- Complete EFA/NIXL matrix: `results/20261013t025247z-features/`.
- Grove scale proof: `results/20261013t024623z-features/`.
- Snapshot preflight: find the `snapshot-preflight` check in `results/*/state.json`.
- Frozen passing serving evidence:
  `results/20261013t023201z-features/evidence-1791862622191999000/`.

Scripts preserve initial failed attempts as well as final receipts. Earlier image,
permission, API-name and manifest-shape failures were corrected in test code;
they do not indicate a hardware incompatibility.

All six final DGDs passed client and server dry-run validation. Python syntax,
shell syntax and Git whitespace checks passed. The local concurrent-observer
check also verified fresh run initialization, independent result preservation,
replacement of stale failure details and immutable per-check receipts.

Cleanup passed: no owned test workloads remain. Owned namespaces, static Retain
PV/PVCs, model cache and immutable local evidence were retained. Shared default
EFS claims, operators, queues, drivers, security groups and host configuration
were not modified.

The final read-only inventory at `results/20261013T034200Z-inventory/` confirmed
three Ready nodes, unchanged shared Helm chart/app versions and no remaining
feature-test Pods across the cluster.
