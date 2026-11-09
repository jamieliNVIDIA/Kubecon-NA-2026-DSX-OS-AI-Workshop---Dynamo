# H100/EFA feature status — updated October 22, 2026

**R610 driver rollout completed on all three nodes.** GPU Operator 26.7.0 now
manages driver **610.57.04**; all 24 H100s passed DRA allocation, CUDA and
eight-rank intra-node NCCL correctness. Snapshot's R610 `--launch-job` probe
creates the required job file after refreshing the idle agent Pod. All three
EFA node pairs and shared DRA claims passed; maintenance labels are restored.
The driver-rollout audit at 00:57 UTC October 22, before the Snapshot runs,
found unchanged boot IDs, 32 EFA resources per node, no new health-condition
failures, no active test Pods and zero ResourceClaims.
See the [driver upgrade report](2026-10-21-driver-upgrade.md).

**October 22 Snapshot TP2 pass:** operator, agent and PageBroker now use matching
digest-pinned build `v0.0.0-gd752d982` in platform Helm revision 4. Native
SnapshotJob capture, distinct-Pod restore and fresh `READY` inference passed
with the same Super VL model, TP=2 and unchanged common workload image. The run
uses CuInterpose, upstream direct-vLLM preparation and a CPU companion that
keeps the source Pod running through EFS publication, then exits after artifact
readiness. Capture **19m12s** (EFS publication **16m55s**); restore **5m40s**
(CRIU **5m17s**); artifact **98.90 GB**. Same node/GPU pair, caches not cleared.
The unmodified single-container path failed the hardcoded five-minute source
grace. Dynamo DGD integration, cross-node and vision/video Snapshot remain
unqualified. Post-inference health found no new kernel Xids or changed node
conditions; preexisting contained Xid 94 remains recorded. The passing run was
cleaned at 18:13 UTC. Final inventory at 18:14 UTC found all three nodes Ready,
unchanged boot IDs/health conditions, 32 EFA resources each, no active feature
Pods and zero ResourceClaims cluster-wide. See the
[CuInterpose upgrade/retest report](2026-10-22-snapshot-cuinterpose.md).

**TP2 RAM storage control also passed:** same 98.90 GB artifact, common image,
model/revision and physical GPU pair. Sequential EFS / RAM / EFS restores took
**337.01 / 42.05 / 335.85s**, each with fresh `READY` inference. CRIU fell from
an EFS mean of **316.32s to 25.63s**; CUDA restoration stayed around 15-16s.
Pre-staged RAM removed **294.38s (87.5%)** of agent restore time, an **8.00x**
speedup. Copying to RAM cost **334s**, plus 139s checksum verification, excluded
from restore timing. A reusable node cache is needed to retain this benefit;
copying per restore would repay the EFS delay. The temporary RAM view was
removed and EFS restored at 18:46 UTC; no shared storage configuration changed.
Final inventory at 18:46:56 UTC confirmed all nodes Ready, unchanged health/boot
IDs, no new Xids, no active feature Pods and zero GPU claims.
See the [same-artifact storage comparison](2026-10-22-snapshot-tp2-storage-comparison.md).

**TP2 NVMe restore control passed:** same 98.90 GB artifact and physical GPU
pair, pinned image/model/revision and direct CRIU I/O. EFS / NVMe / NVMe / EFS
restores took **338.32 / 37.81 / 36.91 / 334.16s**, each passing fresh inference.
NVMe mean **37.36s** versus EFS **336.24s** gives **9.00x** faster restore /
**88.89%** less time; NVMe Pods reached Ready in **40-41s**. SSD counters recorded
**196.82 GB** reads across the NVMe trials. Copy/flush **188s** and all-file hash
verification **68.84s** are excluded from restore timing. Cleanup passed at
20:24 UTC; final inventory at 20:25 UTC confirmed all nodes Ready, unchanged
boot IDs/conditions, 32 EFA each, zero claims/active feature Pods, and no new Xids.
The private overlay is removed, EFS remains active, and the verified checkpoint
is retained on cp-0124's runtime-only NVMe mount. Capture/publication to NVMe
and production cache integration remain unqualified. See the
[NVMe restore comparison](2026-10-22-snapshot-tp2-nvme-comparison.md).

**October 22 R610 feature retests completed.** The same Super VL TP=2
model/revision and common image freshly passed serving/KV routing, image input,
native engine sidecar, KVCR, disaggregation, ModelExpress P2P and Grove/KAI.
Sidecar needed a 30-minute native startup allowance for concurrent EFS loading;
KVCR passed after correcting its peer-discovery test. Super VL Shadow still
fails GMS startup before fault injection. A separate Qwen TP1 control passed
actual failover in **2.62s**, with one failed request and a new standby.

Final checks at 22:05 UTC found all nodes Ready, unchanged boot IDs/conditions,
32 EFA resources each, zero GPU claims/active feature Pods, unchanged Helm
versions and no infrastructure restart increases. The failed Super VL writer
logged **two new Xid 31 faults on cp-0124**; its exact GPU pair subsequently
passed CUDA arithmetic without reset. The audit retains those errors; other
nodes had no new Xids. See the [R610 feature report](2026-10-22-r610-feature-retest.md).

**October 15 full-model baseline: Super VL TP=2 completed with two blockers.** Revision
`8a115b9d966adce8c059a7bcf47f49a1e57957d8` passed aggregated inference/KV routing,
vLLM engine sidecar, a real image request, KVCR with idle health, disaggregation,
ModelExpress P2P and Grove two-GPU-claim scaling. Snapshot runtime pause/resume
passed; native capture failed at the CUDA launch-job requirement on R580.
The October 21 driver/tool and actual source-launch gates now pass. Fresh R610
TP2 pause/resume also passed (54.73s / 3.15s). Native capture with default NCCL
allocation stalled in first-rank CUDA checkpointing before CRIU and was bounded
and stopped. The compiled legacy-allocation retry also stalled and was cleaned
up. Eager-mode preparation passed; after access recovered on October 22, its
native capture was confirmed failed at the one-hour source Job deadline. The
first-rank CUDA call waited 52m52s until source termination; no usable capture
or restore was produced. The owned graph and capture Jobs have been removed.
Small CUDA IPC and NCCL checkpoint controls passed,
including NCCL on the same GPU pair. See the
[R610 TP2 Snapshot report](2026-10-21-snapshot-tp2-r610.md).

Recovery audit at 16:30 UTC October 22 confirms all three nodes Ready, no active
test Pods and zero GPU claims. **cp-0124 has a new `GpuAllWatch=True` contained
Xid 94 condition dating to the first native run**; kernel logs show NVLink
PRIV errors and worker faults during preparation before all three captures.
A fresh two-GPU CUDA probe passed, but this does not clear the
recorded GPU errors. Read-only diagnostics are saved; no GPU reset was performed.

Shadow failed GMS/model startup on both default and eager FlashInfer settings;
no new-model recovery fault was injected. See the
[Super VL retest report](2026-10-15-super-vl-tp2-retest.md).

The October 15 run's final inventory at 00:35:20 UTC October 16 found all three nodes
Ready, zero test Pods and zero ResourceClaims. A fresh cp-0124 two-H100 CUDA/EFA
probe passed after the Shadow failures. Scripts, manifests and results summaries
are committed. The current October 22 R610 retest supersedes completed feature
rows below; the October 15 receipts remain historical evidence.

GPU DRA works on all three nodes. Both the earlier and fresh October 22 Shadow
recovery controls use Qwen and a test-local compatibility overlay; Lightning
NVFP4 and current Super VL remain blocked by their runtime/model startup issues.
The retained Lightning TP1 Snapshot pass predates the GPU allocator transition.

This is the current status page; its filename is retained for existing links.
The [previous report](history/2026-10-12-feature-status-before-snapshot.md) preserves
original software pins and outcomes. Raw receipt times are UTC. These are bounded
functionality tests, not workshop capacity or peak-performance benchmarks.

## Current Super VL TP=2 results

October 22 R610 retests use revision `8a115b9d…`, common workload digest
`e98d074e…`, TP=2 and GPU DRA. Transfer tests use eight EFA resources per
two-GPU endpoint. These are bounded functionality results, with video untested.
All non-Snapshot rows were freshly rechecked; preferred-model Shadow remains
blocked and its separate Qwen TP1 control is reported explicitly. Snapshot is the
separately completed October 22 CuInterpose/native capture and storage comparison.

| Feature | Result | Evidence and limits |
| --- | --- | --- |
| Aggregated inference / KV routing | Passed | Two cross-node TP2 workers; READY, six unforced cache repeats, 4,224 reused tokens each, two stored events. |
| Image input | Passed | Separate TP2 worker with `--enable-multimodal` correctly identified a synthetic red image. No video or image-aware routing qualification. |
| Engine sidecar | Passed | Native vLLM gRPC TP2 engine and separate CPU Dynamo sidecar; identical common image, READY. Native handshake allowance increased from 600s to 1800s for concurrent EFS loading; replacement passed with zero restarts. No SGLang/parity qualification. |
| KVCR | Passed on R610 | Six matched blocks / 103,809,024 reported bytes, 4,224 cached tokens, EFA, READY, no failed/partial deliveries; three idle-health samples per worker, zero restarts. Fresh retry after replacing probabilistic peer discovery with live Pod-owned endpoint selection; initial attempt retained. |
| Disaggregation | Passed on R610 | Four completed rank-level transfer samples / 224,591,872 reported bytes; 6,237 imported prompt tokens, correct responses, no failed transfers/notifications. TP ranks require the NIXL multiprocess telemetry exporter. |
| ModelExpress P2P | Passed | Both ranks loaded 1,869 tensors / 40.27 GB each from a different node over LIBFABRIC/EFA. No disk fallback; receiver returned READY. |
| Grove/KAI | Passed | Real two-GPU claims, gang creation and GPU arithmetic; four → eight → four allocated GPUs, cleanup verified. No model inference or policy qualification. |
| Snapshot | **Passed, native CuInterpose SnapshotJob with lifecycle workaround** | October 22: same model/common image, TP2, distinct restored Pod UID, `Restored=True`, exact image/DRA2 and fresh READY response. 98.90 GB artifact; capture 19m12s (16m55s publication). Same-artifact controls passed: EFS ~336s, RAM 42s (earlier trial), NVMe 37.4s mean (two trials; Pods Ready 40-41s), all fresh inference passed. NVMe pre-staging costs 188s copy plus 68.84s verification. NVMe capture/publication remains untested. CPU-only source companion avoids five-minute terminal-source grace, exits after Ready, and permits Completed=True. Same node/GPU pair; caches not cleared. Dynamo DGD lifecycle and cross-node/vision remain unqualified. No new Xids; older contained Xid 94 retained. Cleaned; see CuInterpose report. |
| Shadow recovery | Super VL TP2 blocked; Qwen TP1 control passed on R610 | Super VL reproduces GMS scalar-versus-(1,) input_scale mismatch and writer CUDA illegal access; no recovery fault injected. Writer logged two new Xid 31 faults; exact affected pair passed fresh arithmetic without reset. Separate Qwen control: active EngineCore killed, verified response in 2.619s, one failed request, same Pod/GMS and new standby confirmed. Does not qualify Super VL or TP2 recovery. |

Inputs, reusable scripts, generated manifests and detailed receipts are described
in [the R610 feature report](2026-10-22-r610-feature-retest.md) and
[the original Super VL report](2026-10-15-super-vl-tp2-retest.md).

## Retained Lightning TP1 results

These rows describe the earlier model and allocator configuration; they are
retained for comparison and do not imply Super VL compatibility. Their R580
Snapshot artifacts and measurements do not qualify restore on the new driver.

| Feature | Status | Verified evidence and limits |
| --- | --- | --- |
| GPU runtime and EFA/NIXL | **Passed** | Baseline: GPU arithmetic on all three nodes and correct 1/16/64 MiB VRAM payloads across all node pairs over EFA. Common image: allocated H100/EFA probe and real cross-node feature transfers passed. Four EFA devices per one-GPU endpoint tested. |
| Shared storage | **Passed** | Different nodes concurrently wrote and verified each other's 4 MiB data through EFS CSI. Dedicated Snapshot artifact export also passed aligned direct I/O. |
| Aggregated serving | **Passed on common image** | Dynamo 1.6.0 preview loaded the pinned Nemotron model and returned `READY`; retained public 1.5.1 baseline also passed. |
| KV-aware routing | **Passed on common image** | Two cross-node TP1 workers, two independent prefixes, six unforced repeats, 2176 reused tokens each, two applied frontend KV events. |
| Disaggregation | **Passed on common image** | Prefill cp-0124 → decode cp-0198; two completed KV transfers / 72,155,136 bytes, 2639 imported prompt tokens, zero transfer/notification failures and expected output. |
| ModelExpress P2P | **Passed on common image** | ModelExpress 0.6.0; cp-0124 → cp-0198, 761 tensors / 20.43 GB, LIBFABRIC/EFA, no receiver disk fallback, `READY`. One transfer log reported 1.68s; not a benchmark. |
| KVCR | **Passed on common image** | cp-0198 → cp-0124; five matched blocks / 33,423,360 bytes, 2176 reused tokens, expected output, zero failed/partial remote deliveries. Baked integration; 180s canary timeout and three idle-health samples per worker with zero restarts. |
| Engine sidecar | **Passed on common image, vLLM aggregated** | Native vLLM 0.31.1 gRPC engine plus external CPU Dynamo sidecar 1.6.0, identical image digests, native engine PID 1, registration and `READY`. SGLang/parity remain unqualified. |
| Dynamo Snapshot | **Passed on common image, TP1 same node** | Snapshot 0.1.0; fresh artifact Ready, distinct restored Pod UID, matching restore annotation, `nvidia.com/Restored=True`, correct Nemotron inference. 35.87 GB artifact; capture 16m29s, restore 2m05s on EFS. TP2/cross-node remain unqualified. |
| Grove/KAI | **Passed on common image** | Gang admission, logged GPU arithmetic and reversible group scale 1→2→1; two→four→two GPU Pods. Quota reclaim/autoscaling/topology policy not qualified. |
| Shadow Engine failover | **Control passed; Nemotron blocked** | GPU DRA shared-claim CUDA passed on every node. Qwen3-0.6B + common image + source-hashed GMS signature overlay: active engine killed, standby served correct response in 2.953s, unchanged Pod/GMS, reused weights, new standby confirmed. One request failed. Nemotron NVFP4 standby rejects packed weight layout; writer also hit a CUDA warm-up error. |

Snapshot baseline details are in [the qualification report](2026-10-13-snapshot-status.md);
the new common-image result is in [common runtime qualification](2026-10-13-common-runtime-progress.md).
Shadow requirements and the fault-injection contract are in
[the failover report](shadow-engine-failover.md).

## Cluster and installed infrastructure

Three Ready AWS nodes, each with **8 H100 80GB GPUs and 32 EFA devices**:
`kubecon-nke-site-cp-0124`, `kubecon-nke-site-cp-0198`,
`kubecon-nke-site-cp-0942`. Driver **610.57.04**, Ubuntu 24.04.4,
kernel `7.0.0-1012-aws`, containerd 2.3.5, API Kubernetes 1.34.2 and kubelets 1.34.11.

Dynamo platform **1.5.1**, Helm revision **4**. Snapshot development build
**v0.0.0-gd752d982** is enabled; its privileged agent/PageBroker remain restricted
to cp-0124 and its operator is Ready. The chart still labels its static appVersion
`v0.1.0`; the installed build is identified by its source SHA and image digests.
Grove `0.1.0-alpha.12`, KAI `0.14.1`, GPU Operator 26.7.0,
EFA device plugin app 0.5.20/chart 0.5.29 and EFS CSI 3.5.1 remain at the
previously inventoried versions. Existing KAI queue `dynamo` is used.

Reviewed shared changes applied by this harness include Dynamo 1.4.2 → 1.5.1,
single-node Snapshot installation/enablement and the October 21 R610 driver
upgrade with DRA client-eviction wiring. The October 14 GPU allocator transition
was applied externally and qualified by these tests. EFA, Grove/KAI, queues and
security groups retain their prior configuration. See [platform upgrade results](dynamo-upgrade.md),
[Snapshot installation review](snapshot-install-review.md) and
[driver upgrade results](2026-10-21-driver-upgrade.md).

EFA device-plugin resource requests work; **EFA DRA is not required** for the
qualified disaggregation/P2P/KVCR paths. October 14: NVIDIA GPU DRA 0.5.0 has
both GPU flags enabled, eight H100s advertised per node and no competing NVIDIA
GPU device-plugin Pods. Both containers sharing one claim executed CUDA on each
node. ComputeDomain support remains enabled. GPU Operator Helm revision is now
**4** and separate DRA revision **3**; DRA 0.5.0's kubelet plugin now selects
`nvidia.com/gpu.deploy.client=true` for coordinated eviction during driver reload.

Kubernetes discovery, TCP request plane and ZMQ event plane were used. These
runs required neither etcd/NATS nor multinode NVLink. Snapshot's TP1 attempt
allocated no EFA resources.

## Model and current runtime sets

The earlier serving qualification retained
`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
`bee7596271d1495f6992ae224aefde4410e816b8`. Its 52 weight files total
21,561,882,284 bytes. The model is ungated; no new HF token was required.
On H100 the NVFP4 model uses Marlin weight compression with higher-precision
compute and loaded 19.11 GiB of weights in the common image (17.84 GiB in the retained
stable baseline). TP1, context 4096, maximum eight
sequences, GPU utilization 0.65 and no speculative draft were tested.

| Workload set | Actual versions | Image/source lock |
| --- | --- | --- |
| Qualified common workload image | Dynamo 1.6.0 preview, vLLM `0.31.1rc1.dev23+g43b4aaea3`, KVCR 0.1.1, NIXL 1.5.0, NCCL 2.30.7, ModelExpress 0.6.0, GMS 0.9.0 | `configs/common-runtime-qualified.json`; common image digest `e98d074e…` |
| Retained integrated serving, routing, disaggregation, ModelExpress and Snapshot | Dynamo 1.5.1, vLLM 0.28.0, NIXL 1.3.2, ModelExpress 0.6.0 | `configs/model-lock.json`; vllm-runtime digest `2b224a82…` |
| Stock-engine sidecar | CPU Dynamo sidecar 1.5.1; stock vLLM 0.28.0, NIXL 1.3.2, no engine ai-dynamo package | `configs/sidecar-images.json`; stock-engine digest `61fc8a89…`, sidecar digest `2f63534c…` |
| KVCR preview | Dynamo 1.6.0 built at `ea23e5130c1bfbadec477b99449d0cee5598caa0`; vLLM `0.31.1rc1.dev23+g43b4aaea3` plus pinned adapter overlay; KVCR 0.1.1, NIXL 1.5.0, NCCL 2.30.7 | `configs/kvcr-lock.json`; base digest `f8696a51…` plus exact wheel/source hashes |

The retained baseline's default integrated image is
`nvcr.io/nvidia/ai-dynamo/vllm-runtime@sha256:2b224a823d52a198ec0eeb0e3e4f5cf26cd8a7fc2e9812ee16204b6b1e974870`.
Older run locks are preserved; `configs/model-lock-original.json` retains the
initial development image. Its tag did not match its installed Dynamo version.
The table above uses measured packages, not image-tag inference.

**One common workload image is now qualified for these bounded vLLM tests.**
Use `configs/common-runtime-qualified.json` and the manifests under
`configs/dgd/common-runtime/`. Frontend, integrated worker, native engine and
external CPU sidecar all use this immutable image:

```text
nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d
```

The native sidecar pattern retains separate containers/commands. The engine
contains the Dynamo package but launches native `vllm-rs`; the external sidecar
runs its Rust binary. KVCR, ModelExpress, the adapter and EFA userspace are baked
in. No per-startup package installation is required. This private image needs an
NGC pull secret, which the common test harness creates in its owned namespace.

This is an exact-source development stack, not a released production bundle.
The shared Dynamo operator stays 1.5.1; common DGDs set
`runtimeVersionOverride: 1.6.0`. Snapshot/Grove/KAI/driver images stay separate.
The original baseline locks remain available. See [full qualification and
reusable commands](2026-10-13-common-runtime-progress.md) and the [source
consolidation assessment](runtime-consolidation.md).

## Provisioning requirements for DSX

For the current Super VL model, allocate **two H100s per worker**. Routing,
disaggregation, ModelExpress and KVCR tests use **four GPUs across two nodes**;
sidecar uses two GPUs on one node. The tested TP2 worker requests 8 CPUs /
128 GiB host RAM with a 256 GiB memory limit. Grove scales four → eight → four
GPUs. Native Snapshot TP2 capture and same-node restore now pass on R610 with
CuInterpose and the source lifecycle companion. Its artifact is 98.90 GB;
pre-staged NVMe restore averages 37.36s (40-41s Pod Ready), versus about 336s
on EFS. Dynamo DGD integration and cross-node restore remain unqualified. Shadow
needs preferred-model GMS startup and actual recovery qualification. The table below
retains the earlier TP1 feature requirements as a baseline.

| Topic | Useful functional topology | Requirements established by these tests |
| --- | --- | --- |
| KV routing | Two one-H100 workers plus CPU frontend | Prefix cache, backend KV events, discovery RBAC and Pod connectivity; no RDMA prerequisite for routing itself. |
| Disaggregation | One-H100 prefill and decode on separate nodes | Allocate EFA devices, matching LIBFABRIC/NIXL and AWS EFA userspace, peer/control connectivity. Four EFA resources per GPU tested. |
| ModelExpress P2P | One-H100 source and receiver on separate nodes | Same model revision, quantization/layout and runtime; source-only metadata Service, EFA/NIXL transfer, model access and host RAM. Tested decentralized path needs no Redis/server/CRDs. |
| KVCR | Two one-H100 workers on separate nodes | Matched router-hint protocol, vLLM adapter and KVCR/NIXL versions; 4 GiB primary host-pinned offload per worker, peer control ports and four EFA resources. A package import alone is not qualification. |
| Engine sidecar | One-H100 native engine plus CPU sidecar in the same Pod; CPU frontend | Matched gRPC/sidecar protocol, explicit Pod identity/discovery RBAC, reachable engine probe endpoint and tokenizer cache. Both containers can use the qualified common image. Aggregated demo needs no EFA. |
| Snapshot | One H100 on cp-0124 for tested TP1 capture/restore | Enabled integration, Snapshot operator and privileged node agent, runtime/cgroup/process access, seccomp profile and dedicated artifact PVC. Common artifact 33.41 GiB; capture RAM peak 53.76 GiB. No GPU DRA or EFA required. |
| Grove | Existing CPU controllers plus admitted GPU gang | Grove/KAI, queue and admission labels; real graphs and basic gang/scale passed. Further policies need separate tests. |
| Shadow Engine failover | Active engine, parked standby and GMS sharing one H100 claim | GPU DRA/CDI now verified on all nodes; no legacy allocator. Qwen control passed with the GMS/vLLM signature overlay. Nemotron NVFP4 layout/warm-up remains blocked. No Snapshot/EFA prerequisite. |

Ordinary workers request 4 CPU / 64 GiB RAM, limit memory to 128 GiB and use
16 GiB shared memory. Frontends request 1 CPU / 4 GiB, limit 8 GiB. The sidecar
adds 1 CPU / 1 GiB with a 4 GiB memory limit. Snapshot agent requests 2 CPU /
1 GiB, limits 4 CPU / 16 GiB. These are tested bounds, not universal minimums.
Common-image Snapshot host RAM peaks were 53.76 GiB for capture and 33.26 GiB
for restore; agent peak was 1.20 GiB. All had zero OOM events. The current agent
request is 1 GiB with a 16 GiB limit; allow the measured peak when planning
reservations, for example 2 GiB. Budget artifact retention and temporary staging
separately from model cache.

Live read-only inspection on October 13 confirmed `default/dynamo-shared-pvc`
and `dynamo-system/snapshot-artifacts` are Bound RWX claims backed by EFS CSI
filesystem `fs-07acea4e27fbda414`. Recheck with
`scripts/storage_tests.py --inspect-only --run results/<fresh-storage-inspection>`.
EFS uses static Retain PV/PVCs; no EFS StorageClass exists for dynamic provisioning.
Snapshot mounts only
its dedicated artifact subdirectory, preventing orphan cleanup from seeing model
cache or unrelated data. PV capacity is advisory, not an EFS quota. EFS passed
correctness and actual capture/restore, but the common-image **2m05s agent restore**
is not seconds-scale startup. Pod creation to Ready was 140s. The 8.55s CUDA
restore phase excludes the 115.44-second CRIU phase and other overhead. Faster artifact storage or
smaller captured state would require a separate qualification.

The October 13 same-artifact RAM control now isolates the storage delay:
two EFS restores took **124.42s / 123.97s**, while a pre-staged tmpfs restore
took **14.20s**. CRIU fell to **5.38s** and CUDA remained **8.28s**; Pod creation
to Ready fell from **139s to 30s**. Every reported restore passed fresh inference.
The EFS read path is the dominant delay for this 33.41 GiB checkpoint. Copying
it into RAM took **127s**, so startup acceleration needs a reusable node cache
or faster artifact storage. This is a RAM-backed control, not an NVMe benchmark
or a production cache deployment. No disk was formatted, the temporary helper
and private artifact mount were removed, and the shared Snapshot agent spec
was preserved. See the [comparison and reusable scripts](2026-10-13-snapshot-storage-comparison.md).

The qualified common image includes checksum-pinned AWS EFA userspace 1.49.0.
The retained baseline entrypoint installs those libraries inside disposable
containers, skipping kernel/host-limit changes. Ordinary serving Pods used
UID 0 and IPC_LOCK/SYS_RESOURCE, without privileged host access; Snapshot's agent
is the approved privileged exception.

## Remaining qualification gaps

- Snapshot: cross-node restore, disaggregated composition, NVMe capture/publication
  and concurrent/cold-cache startup qualification. The repeated EFS/NVMe
  restores and single RAM control do not qualify attendee concurrency. Dev multi-GPU
  TRT-LLM recipes do not qualify H100/Nemotron TP2.
- Sidecar: SGLang and KV routing/disaggregation parity. Common-image aggregated
  compatibility passed.
- KVCR: local persistence, Guard recovery, G3 storage, eviction stress and broader
  context/TP coverage. The passing peer-only test used matched tiering write/read
  counters; unused local cascade failures were not counted as remote delivery.
- Shadow Engine: resolve Nemotron NVFP4 GMS import/warm-up, bake the signature
  fix into a common image and requalify. Current recovery proof uses small-model
  controls with an explicit overlay, not preferred-model or hardware-failure recovery.
- R610 retests completed for the current feature matrix. Preferred-model Shadow
  remains blocked as described above; the other current-model rows and native
  Snapshot have fresh October 22 receipts. The October 13 device-plugin-based
  results remain historical evidence.
- Capacity: simultaneous attendee deployments, cold-start headroom and sustained
  throughput. No functionality result establishes workshop concurrency limits.

## Durable evidence and cleanup

| Qualification | Private receipts |
| --- | --- |
| R610 driver upgrade, eight-GPU node checks, EFA/DRA and Snapshot launch gate | `results/20261021-driver-upgrade/`; initial inventory `results/20261021-driver-upgrade-before/` |
| Public 1.5.1 serving/routing/disaggregation/ModelExpress | `results/20261013t051300z-runtime-151/`; frozen `evidence-1791870130662115000/` |
| Operator retests, sidecar, KVCR and Grove | `results/20261013t050900z-upgrade-retests/`; frozen `evidence-1791870129072422000/` |
| Snapshot capture/restore, inference and cleanup | `results/20261013-snapshot-next/`; frozen `evidence-1791876594388298000/` (1,446 files with SHA-256 manifest) |
| Snapshot approved infrastructure install | `results/20261013-snapshot-install-review/`; frozen `evidence-1791876435446665000/` |
| Shadow preflight/runtime inspection | `results/20261013-shadow-preflight/`; no fault injection |
| Live GPU DRA and preferred-model Shadow startup | `results/20261014-shadow-enabled-check/`; shared CUDA passed on three nodes, Nemotron runtime blocked |
| Live Shadow recovery control | `results/20261014-shadow-qwen-control/`; Qwen3-0.6B + overlay, full process failover/replenishment passed |
| October 14 clean inventory | `results/20261014-shadow-clean-inventory/`; three Ready nodes, zero active test Pods and zero GPU claims |
| Final cluster inventory | `results/20261013-common-runtime-clean-inventory/`, completed 19:34:27 UTC; three Ready nodes, zero active test GPU Pods |
| Common-runtime source audit | `results/20261013-runtime-consolidation-audit/audit.json`; no common image built |
| Access restored / current inventory | `results/20261013-vpn-restored-inventory/`; completed 17:49:18 UTC, all three nodes Ready and no active GPU workloads |
| Common-image build and full matrix | `results/20261013-common-runtime-c/`, `results/20261013-common-runtime-features/`; full bounded matrix passed, qualified lock in `configs/common-runtime-qualified.json` |
| Frozen common-image qualification | Test `evidence-1791920849018506000/` (1,465 files); build `evidence-1791920856504215000/` (25 files), each with SHA-256 manifest |

Final cleanup confirmed **zero active test GPU Pods**, all three nodes Ready,
and Dynamo/Snapshot controllers Ready. Owned test DGDs/Pods were removed;
model cache, namespaces, static Retain PV/PVCs, the approved Snapshot installation
and checkpoint artifacts remain. The common-image lock was recorded after all
required feature checks passed; retained baseline locks were not overwritten. Scripts retain failed attempts and exact source/image
identities; syntax, admission checks and Git whitespace checks passed for the
qualified changes.
