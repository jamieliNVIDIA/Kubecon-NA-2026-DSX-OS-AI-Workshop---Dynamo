# Proposed cluster changes for fast Snapshot and Shadow Engine recovery

Original proposal: October 13, 2026, for a dedicated demo cluster. Later
approved changes and measurements are recorded in the dated updates below.
The original read-only Shadow preflight is retained in
`results/20261013-shadow-setup-refresh/`.

October 22 Snapshot update: the approved GPU Operator upgrade installed
**610.57.04 on all three nodes**. The approved Snapshot-only development upgrade
now runs matching digest-pinned operator/agent/PageBroker build
**`v0.0.0-gd752d982`**, still on cp-0124. CuInterpose with the unchanged Super VL
TP2 model/common image passes both GPU checkpoints and CRIU. The earlier
launch-job/CUDA-stall prerequisites below are historical. The first new artifact
is **98.89 GB**; **19m54s** of its **22m10s** capture was EFS publication. A
hardcoded five-minute terminal-source grace failed the parent Snapshot before
content publication completed. A fresh CPU-keepalive retry has passed that
boundary and **passed native capture, distinct-Pod restore and fresh inference**.
The passing run captured in **19m12s** (16m55s publication), restored in
**5m40s** (5m17s CRIU), and produced a **98.90 GB** artifact. Same node/GPU pair,
unchanged workload image; caches were not cleared. Dynamo DGD lifecycle
integration and cross-node/vision Snapshot remain unqualified. Fast storage
and a supported publication lifecycle remain necessary for the intended fast
restore demonstration. The old 64 GiB artifact budget and 16 GiB agent limit below
do not size this implementation/model. See the
[CuInterpose report](2026-10-22-snapshot-cuinterpose.md) for complete installed
values, measured memory and current qualification. No disk was formatted.

October 22 same-artifact storage control: EFS / RAM / EFS restores passed in
**337.01 / 42.05 / 335.85s**, with fresh inference and the same GPU pair.
Mean CRIU time dropped from **316.32s to 25.63s**. Pre-staged RAM gives an
**8.00x** agent restore speedup for the 98.90 GB TP2 checkpoint. Copying it from
EFS took **334s**, plus 139s verification, so a reusable node cache populated
before restore is required to preserve the benefit. The tested tmpfs was
128 GiB; the staging helper peaked at 184.46 GiB including buffered EFS reads.
These observations supersede the old TP1 64 GiB cache budget and do not define
a production memory minimum. The temporary mount was cleaned up; supported
cache integration remains to be implemented. This control did not recapture
to RAM or measure RAM publication. See the
[TP2 storage comparison](2026-10-22-snapshot-tp2-storage-comparison.md).

October 22 NVMe proposal: a read-only refresh confirmed eight unmounted
3.8 TB instance SSDs on cp-0124. Complete single-node local-PV/PVC and full
Snapshot values are prepared and storage-schema dry-run validated, **not
applied**. Conditional planning estimates are 1-2 minutes restore and roughly
3-4 minutes capture after model initialization; NVMe performance is unmeasured.
The proposal uses local RWO storage with the operator, agent and PageBroker all
on cp-0124. Multi-node NVMe still requires per-node store/cache integration.
Disk initialization remains unapproved. See the
[NVMe setup and estimate](2026-10-22-snapshot-nvme-demo-plan.md).

October 14 update: GPU DRA is enabled on all three nodes and shared-claim CUDA
passes on each. The old device plugin is absent. The allocator proposal below
records the earlier target; Snapshot cache integration is still pending. Live
preferred-model and control outcomes are in the
[Shadow retest report](2026-10-14-shadow-engine-retest.md).

October 15 update for **Super VL TP=2**: routing, disaggregation, ModelExpress,
KVCR, engine sidecar and image input passed with two H100s per worker. Grove
scaled two-GPU claims. Snapshot runtime pause/resume passed, but native capture
requires a CUDA launch-job file and the installed R580 driver/CLI rejects that
operation. Plan a reviewed **R610+ driver/tool target and source launch wrapper**,
then recapture and requalify DRA/EFA. This is an additional prerequisite to the
storage optimization below. The old TP1 artifact size and 64 GiB cache budget do
not size the new model. Shadow's TP2 startup also exposed a GMS scalar-shape
reconstruction error and a writer CUDA warm-up failure. DRA is already enabled;
a driver upgrade for Snapshot does not establish a fix for those GMS errors.
See the [exact failure and next changes](2026-10-15-super-vl-tp2-retest.md#tp2-snapshot-blocker-and-next-changes).

Driver ownership check: the existing GPU Operator manages containerized R580
on all three nodes. An operator-level `driver.version` change is the expected
R610 upgrade path; rebuilding node images is not inherently required. NVIDIA
lists 610.57.04 with GPU Operator 26.7.0 and publishes its Ubuntu 24.04 container.
The current AWS kernel/module build still needs validation before any apply.
See [driver upgrade feasibility](2026-10-15-driver-upgrade-feasibility.md).

The demo is the cluster's only required workload. Opportunistic workloads may
be stopped for the transition; preserving their allocation or software
compatibility is not a design requirement. Shared operators, schedulers and
experimental software may be upgraded or replaced when feature tests need it.
Applying major changes still requires approval; disk formatting was explicitly
declined and is excluded from this proposal.

The changes are independent: Super VL TP2 Snapshot first needs the CUDA job-file
driver/launch path, then a qualified fast artifact read path. Shadow Engine needs
GPU allocation through DRA and working GMS/model integration. Neither requires
EFA DRA or multinode NVLink. Retain the working EFA device plugin for existing
transfer demos.

## Target cluster configuration

| Node | Initial assignment | GPU allocation |
| --- | --- | --- |
| cp-0124 | First fast Snapshot restore and Shadow Engine tests | NVIDIA GPU DRA, eight H100s |
| cp-0198 | Routing/disaggregation/P2P/KVCR; second Snapshot node when qualifying placement | NVIDIA GPU DRA, eight H100s |
| cp-0942 | Additional feature workers and Grove scaling | NVIDIA GPU DRA, eight H100s |

Use GPU DRA for **all 24 GPUs**, with the legacy NVIDIA GPU device plugin
disabled cluster-wide. Assignments above are an initial test sequence; nodes
remain interchangeable once their required agents/cache and claims are ready.
No node is reserved to preserve the old allocator. EFA continues using its
working device plugin and `vpc.amazonaws.com/efa` requests.

Use the already-qualified common runtime image as the starting point for every
feature, including Shadow Engine, from `configs/common-runtime-qualified.json`.
GMS/model qualification is still pending. Upgrade the common runtime, Dynamo
operator, Grove or KAI together when necessary, with explicit version/image
pins and fresh results. Previous passing results remain evidence for the old
configuration; they do not establish success after this transition.

## Fast Snapshot restore

Snapshot already works for the earlier Lightning TP1 configuration. The [storage control](2026-10-13-snapshot-storage-comparison.md)
measured EFS agent restores of 124.42s / 123.97s versus 14.20s from a pre-staged
RAM copy, with correct inference in every reported restore. Copy time was 127s.

RWX is already functional: `default/dynamo-shared-pvc` and
`dynamo-system/snapshot-artifacts` are Bound EFS CSI RWX claims. These are
static PV/PVC bindings; no EFS StorageClass exists for dynamic provisioning.
The change needed for fast restore is the artifact read path. Adding an EFS
StorageClass would simplify new claims but would not itself speed up restore.

For the RAM approach, keep EFS as the retained/shared backing store and add a
long-lived, node-local cache. Reserve approximately **64 GiB RAM per node for
one current artifact/cache service**, separately from serving-worker RAM. The
artifact is 33.41 GiB; the test used a 48 GiB tmpfs with a helper requesting
48 GiB and limiting memory to 64 GiB. Source filesystem cache also consumes
memory. This budget is an initial planning allowance, not a measured universal
minimum; multiple retained artifacts/concurrent staging need more capacity.

Required integration:

1. A dedicated cache service/DaemonSet preloads the Ready artifact once, before
   the demo or worker scheduling, and survives individual inference Pod restarts.
2. Key entries by immutable artifact identity; validate contents before atomically
   marking an entry usable. Budget retention/eviction and refresh after node or
   cache-service restart.
3. Make the Snapshot restore path read the local cached artifact while preserving
   EFS publication/retention. This needs supported agent/cache integration or
   a reviewed implementation change; the private bind mount used in the
   performance control was test instrumentation, not an installed cache feature.
4. Label/gate scheduling so a worker lands on a node with the compatible artifact
   already cached. Install the privileged Snapshot agent and seccomp profile on
   every additional node selected for Snapshot; only cp-0124 is enabled today.
5. Size memory limits on the container that owns the tmpfs pages. The current
   Snapshot agent's 16 GiB limit cannot hold this whole artifact if staging is
   charged to that container; the control charged the separate helper.

The installed [Snapshot v0.1.0 storage configuration](https://github.com/ai-dynamo/snapshot/blob/v0.1.0/docs/operations/storage.md)
has a shared PVC path and does not document a reusable local cache switch.
Current development [PageBroker storage documentation](https://github.com/ai-dynamo/snapshot/blob/main/docs/operations/storage.md)
adds `pageBroker.restoreMode: staged`, which copies the artifact before CRIU.
Do not treat that setting alone as a warm-cache guarantee: per-restore copying
would repay the EFS read cost. Select a pinned experimental Snapshot
agent/PageBroker/chart combination with the required cache integration, or
implement that integration. Update our demo configuration and recapture the
checkpoint if required by the new stack. Keeping Snapshot 0.1.0 is not a
requirement; the cache must demonstrate a warm restore without another full
EFS copy on the worker's startup path.

Start with the RAM cache on cp-0124, then expand the agent/seccomp/cache setup
to every node used for Snapshot. Three nodes with one cache each need an initial
**192 GiB total cache memory allowance**, in addition to worker memory. Verify
artifact portability with an actual cross-node restore before allowing placement
on another node; a shared or copied artifact alone does not establish portability.
GPU DRA also changes device injection: recapture and rerun Snapshot under the
target allocator, checking restored GPU identity and working CUDA/inference.

Faster RWX artifact storage is an alternative if DSX can provision it; benchmark
the checkpoint on that store. Local NVMe provisioning requires separate approval
and qualification. No NVMe device was formatted, and RAM performance is not an
NVMe result. Keep EFS artifacts and evidence during the transition.

## Shadow Engine / GPU DRA

Fresh preflight still finds GPU allocation disabled, no `gpu.nvidia.com`
DeviceClass or GPU ResourceSlices, and the GPU device plugin on all three nodes.
The installed DRA 0.5.0 currently enables only ComputeDomains. Those are the
MNNVL path, not the GPU allocation capability required on H100.

The cluster already meets relevant version floors: Kubernetes API 1.34.2,
driver 580.173.02, containerd 2.3.5. Recent inventory shows toolkit image 1.20.0;
actual DRA/CDI device injection still needs a claim-sharing smoke test. The
[DRA 0.5.0 prerequisites](https://github.com/NVIDIA/k8s-dra-driver-gpu/blob/v0.5.0/site/content/docs/prerequisites.md)
require toolkit 1.18+ and CDI; no Kubernetes or GPU driver upgrade is expected
solely to enable this test.

Proposed cluster-wide transition:

1. Record current Helm values, manifests, image pins and ownership for rollback.
   Stop existing GPU demos and opportunistic GPU workloads across all three
   nodes. Update DSX's source of truth for the dedicated demo configuration.
2. Disable GPU Operator's NVIDIA GPU device plugin cluster-wide using the
   reviewed chart/ClusterPolicy `devicePlugin.enabled: false` configuration;
   retain the driver, toolkit and monitoring. Verify the plugin has actually
   stopped on every node and no device-plugin allocations remain before enabling GPU DRA.
   Do not let both allocators manage the same physical GPUs.
3. Enable GPU allocation in the standalone DRA release on all three GPU nodes,
   using `nvidiaDriverRoot: /run/nvidia/driver` and reviewed image/chart pins.
   Disable unused ComputeDomain support for this H100 cluster. The installed
   0.5.0 chart can express this target; use a newer pinned release if qualification
   exposes a driver issue. Inspect rendered GPU Operator validators/operands
   after disabling the plugin and adjust their configuration for DRA as needed.
4. Verify driver registration, `gpu.nvidia.com` DeviceClass, ResourceSlices
   advertising all **24 distinct H100s across three nodes**, and CDI allocation.
   First run a one-claim CUDA smoke on each node. A two-container
   Pod referencing **one ResourceClaim** must report the same physical GPU UUID
   in both containers. Independent claims/consumable sharing/MPS are unnecessary
   for this single-Pod arrangement.
5. Convert demo manifests and harnesses to GPU claims as described below, then
   deploy the Dynamo GMS/failover pattern and run the saved active
   + parked-standby verifier, bounded engine-process fault and recovery test.
   Nemotron NVFP4/Mamba/MoE GMS compatibility and actual HBM headroom remain
   unqualified despite GMS entrypoints being present in the common image.

The complete values and guarded apply script are now prepared in the
[October 14 upgrade bundle](2026-10-14-gpu-dra-upgrade.md), with both server
dry-runs and a read-only readiness check passed. Use that bundle for applying.
The following remains a concise summary of its DRA settings:

```yaml
gpuResourcesEnabledOverride: true
nvidiaDriverRoot: /run/nvidia/driver
resources:
  gpus:
    enabled: true
  computeDomains:
    enabled: false
kubeletPlugin:
  nodeSelector: {}
```

This removes any single-test-node restriction; the chart's GPU-node affinity
and reviewed tolerations must cover all three nodes. It assumes the competing
GPU device plugin has been disabled everywhere. The fragment must be merged
with the release's complete reviewed values before applying.
The [installed-version Helm values](https://github.com/NVIDIA/k8s-dra-driver-gpu/blob/v0.5.0/deployments/helm/dra-driver-nvidia-gpu/values.yaml)
and [installation validation](https://github.com/NVIDIA/k8s-dra-driver-gpu/blob/v0.5.0/site/content/docs/install.md)
define this configuration surface.

The workload needs `experimental.gpuMemoryService: {}`,
`experimental.failover: {}`, container discovery and vLLM `--load-format gms`.
The operator arranges active/standby/GMS GPU sharing through DRA; all consume
the shared allocation. Budget shared weights plus private contexts/graphs and
active KV cache, not twice the entire GPU memory budget. Start TP1 with the
preferred model and adjust KV/HBM headroom based on the actual GMS test.
See the [release example](https://github.com/ai-dynamo/dynamo/blob/v1.5.1/examples/backends/vllm/deploy/agg_failover.yaml)
and [saved fault-injection contract](shadow-engine-failover.md).

Do not add the latest GPU Operator `GPUCluster` workflow to the existing
`ClusterPolicy` installation as a shortcut. [Current GPU Operator documentation](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/dra-intro-install.html)
requires choosing one and does not support in-place migration from this
standalone Helm layout. The recommended first implementation uses standalone
DRA with the existing driver/toolkit management and its GPU device plugin
disabled. A clean rebuild into the managed `GPUCluster` workflow is also an
acceptable demo-cluster option if it simplifies operations, with a separately
prepared reinstall/driver plan. Preserving the current layout is not a requirement.

## Demo manifest and harness migration

On Kubernetes 1.34.2, explicitly use `resource.k8s.io/v1` ResourceClaims and
ResourceClaimTemplates. Do not assume an ordinary Pod requesting
`nvidia.com/gpu` will automatically become a DRA allocation. Avoid making an
extended-resource compatibility layer a prerequisite for this demo.

- Plain worker/probe Pods: request one or two GPUs through `gpu.nvidia.com`,
  attach the Pod claim and reference it from each container needing CUDA.
  Remove legacy scalar GPU requests from those rendered Pods. Give ordinary
  independent workers separate claims so they receive separate allocations.
- Dynamo GMS/failover: retain the operator's supported component GPU-count
  input where it uses that count to generate a claim. Verify the rendered Pod
  has no competing scalar GPU allocation and active/standby/GMS share exactly
  one claim. Do not add a second manual allocation around operator-generated DRA.
- Engine sidecar: the stock engine gets the GPU claim; the external CPU router
  sidecar keeps its existing CPU-only resource budget.
- EFA: keep device-plugin requests and tested userspace configuration alongside
  GPU claims for NIXL, disaggregation and P2P tests.
- Inventory and capacity checks: count DRA ResourceSlice devices and claim
  allocations. Replace harness assumptions that node capacity must expose
  `nvidia.com/gpu: 8`; verify claims release correctly on cleanup.
- Grove/KAI: qualify GPU-claim scheduling, gang admission, GPU counting and scale
  down/reallocation together. Upgrade or patch these demo components if needed.
  Do not report the previous device-plugin-based gang test as DRA qualification.

## Application sequence and feature retests

Prepare pinned values, rendered manifests and reusable migration/retest scripts
before applying the cluster changes. Then:

1. Stop GPU workloads, switch allocator ownership, and pass per-node CUDA plus
   shared-claim smoke tests. Confirm all 24 devices and no overlapping allocator.
2. Run preferred-model ordinary TP1 inference on the common image, then qualify
   Shadow Engine active/parked standby, the bounded process fault, inference
   recovery and standby replenishment using the saved verifier.
3. Capture a fresh Snapshot under DRA and verify restore/inference on cp-0124.
   Integrate the reusable RAM cache and compare cold preparation versus warm
   restore, recording staging separately. Then qualify cross-node/TP2 as needed.
4. Rerun GPU/EFA transfer probes, KV-aware routing, disaggregation, Model Express
   P2P, KVCR, and stock-engine sidecar inference with claims on the common image.
5. Rerun Grove/KAI gang placement and scaling under DRA, verifying correct GPU
   allocation, cancellation/cleanup, and reallocation after scale-down.

Save new receipts and immutable image/version/model identity for every result,
then update the feature-status page. The target is a fully functioning demo
matrix on the new configuration; workload continuity during conversion is not
required. The pending approvals are the concrete cluster-wide allocator change
and final Snapshot deployment/cache configuration.

Shadow Engine acceptance: exclusive allocator ownership; shared-claim CUDA smoke; active and
parked standby; inference after one bounded engine-process failure; standby
replenishment; original Pod and GMS survive. This validates process recovery,
not failed-GPU/node recovery or continuity of in-flight requests/KV state.
