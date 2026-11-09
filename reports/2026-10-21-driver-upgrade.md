# Operator-managed R610 driver upgrade — October 21, 2026

The demo cluster was upgraded from **580.173.02** to **610.57.04** through the
existing GPU Operator **26.7.0**, one node at a time. All three nodes passed the
allocated retests and final audit. No node image was changed or node rebooted.

## Reviewed scope

Fresh live values and rollback values are saved in
[`configs/driver-upgrade-20261021/`](../configs/driver-upgrade-20261021/).
The rendered ClusterPolicy changes only `spec.driver.version`; the existing
one-node upgrade policy, disabled GPU device plugin and other settings remain.
The separate NVIDIA DRA 0.5.0 Helm release gains
`kubeletPlugin.nodeSelector.nvidia.com/gpu.deploy.client: "true"` so the
installed driver manager can evict the plugin before unloading the driver.
Both existing DRA containers remain enabled.

During maintenance, all nodes initially receive the driver-upgrade skip label;
the scripts release one explicit node at a time. NVSentinel management is
temporarily disabled with its documented maintenance label, with original label
values saved for restoration. A node must pass driver, NVSwitch Fabric, GDRCopy,
DRA inventory and an eight-GPU CUDA/NCCL check before advancing. There is no
node-image rebuild, NVMe formatting, EFA driver upgrade or DRA allocation-mode
migration in this change.

## Preparation evidence

- SSH and Kubernetes access work through the existing jump host.
- Three idle H100 nodes, no ResourceClaims or model DGDs; all run Ubuntu 24.04
  and kernel `7.0.0-1012-aws` with matching headers.
- The public target image resolves to
  `nvcr.io/nvidia/driver@sha256:f466fd4f13f5c8832e124d762919290e25be02ecffafee9449774d65c616bcd2`.
- A CPU-only disposable Pod compiled all five R610 open kernel modules against
  the running kernel. Host headers/modules were mounted read-only; no modules
  were installed or loaded. An initial missing `libdw.so.1` was resolved inside
  that Pod using the normal kernel-header dependency `libdw1t64`; matching header
  and image packages remain downloadable. The actual driver initializer installs
  those kernel-header dependencies itself.
- Both complete Helm values files passed server dry-run. Six local guard tests
  passed, covering scope preservation, allocator safety, integrity and incomplete
  rollout rejection. The complete local suite passed **40 tests**.

Raw immutable receipts, before inventory, image resolution, build logs and the
maintenance journal live under `results/20261021-driver-upgrade/` (Git-ignored).
The full initial inventory is `results/20261021-driver-upgrade-before/`.
That inventory already records `GpuNvlinkWatch=True` on all three nodes, while
they were Ready and schedulable. The final health audit compares against these
preexisting NVSentinel conditions as well as checking actual Fabric registration
and NCCL payload correctness.

## Execution

All nodes completed reload, are Ready and schedulable, and advertise eight GPUs
through DRA. Each passed a real eight-GPU allocation, CUDA arithmetic, an
eight-rank NCCL all-reduce with correct payloads, completed Fabric registration
and a loaded GDRCopy module. The collective's startup logs
identify loaded **NCCL 2.30.7+cuda13.3**; Torch reports CUDA 13.0. The receipts
also retain `torch.cuda.nccl.version()`'s separate 2.29.7 return value.

| Node | Driver | Eight-GPU CUDA / NCCL | DRA GPUs | EFA resources | Reboot |
| --- | --- | --- | --- | --- | --- |
| cp-0124 | 610.57.04 | Passed | 8 | 32 | No |
| cp-0198 | 610.57.04 | Passed | 8 | 32 | No |
| cp-0942 | 610.57.04 | Passed | 8 | 32 | No |

The canary first passed EFA/NIXL transfers to an R580 node before further
rollout. After all upgrades, all three node pairs passed **1 / 16 / 64 MiB VRAM
READs over LIBFABRIC/EFA**, nine correct transfers total. Each endpoint requested
one GPU and four EFA resources; the test enforces the EFA provider, device RDMA
and CUDA DMA-BUF. It does not measure all-rail or peak NCCL bandwidth.

The shared-claim prerequisite also passed on every node: two containers held one
DRA H100 claim, reported the same GPU UUID and returned correct CUDA arithmetic.
This verifies allocation/sharing for the Shadow deployment pattern; no engine
startup or recovery fault was attempted in this upgrade run.

Snapshot's launch-job gate **passed** after recreating its idle agent Pod.
Before recreation, its runtime-injected checkpoint executable still reported
R580 despite the newly loaded R610 module. The recreated agent reports CLI
610.57.04 and creates a nonempty CUDA job file. This removes the driver/tool
prerequisite blocker; a fresh Super VL TP2 capture/restore with source launch
wrapping is still required for native Snapshot qualification.

The original skip/management and GPU-client deployment labels are restored.
The final audit at **00:57:31 UTC October 22** (October 21 local) passed:
identical node UIDs/boot IDs, unchanged running kernel, matching validated driver
image digests, eight DRA GPUs and 32 EFA resources per node, no newly unhealthy
NVSentinel conditions, no unready infrastructure Pods, no active test Pods and
zero ResourceClaims. The preexisting `GpuNvlinkWatch` conditions remain recorded.
The CPU build Pod was removed; model caches and historical artifacts remain.
GPU Operator Helm revision is **4** and DRA revision **3**; Dynamo, Snapshot,
Grove/KAI and EFA versions are unchanged.

Authoritative raw audit: `results/20261021-driver-upgrade/driver-upgrade-audit.json`.
The final full inventory is `results/20261021-driver-upgrade-final/`, completed
at **00:59:07 UTC October 22** with all reads collected, all three nodes Ready
and schedulable, zero active test Pods across test namespaces and zero claims.
`results/20261021-driver-upgrade-after/` is an intermediate snapshot that caught
the CPU build Pod during cleanup. GPU scalar allocatable remains zero by design:
the eight GPUs per node are allocated through DRA.

The first operator Helm transaction was deliberately canceled while all nodes
were still skipped: Helm 4's `--wait` also waits for ClusterPolicy readiness,
which requires completing the driver rollout. The canary gate prevented that
completion. The script now lets Helm apply without the global readiness wait
and owns per-node verification itself; it resumed identical reviewed values.
The canceled transaction remains in Helm history as failed; the follow-up
transaction supersedes it. The successful CRD hook used the same installed
operator version. Every node still ran R580 when that transaction was canceled.

## Reusable commands

These phases describe the completed execution; the script rejects advancing an
already completed node. Use a fresh reviewed bundle for another driver change.

```bash
PY=.local/venv/bin/python
RUN=results/20261021-driver-upgrade
BUNDLE=configs/driver-upgrade-20261021
# Read-only progress; safe while an upgrade phase is running:
$PY scripts/apply_driver_upgrade.py --run "$RUN" --bundle "$BUNDLE" --phase status
# Run after a node has completed driver rollout:
$PY scripts/driver_cuda_probe.py --run "$RUN" --node kubecon-nke-site-cp-0124
# Advance only after the prior node's allocated CUDA/NCCL check passes:
$PY scripts/apply_driver_upgrade.py --run "$RUN" --bundle "$BUNDLE" \
  --phase advance --node kubecon-nke-site-cp-0198
# Final read-only audit (all retests and maintenance restoration must pass):
$PY scripts/driver_upgrade_audit.py --run "$RUN" --bundle "$BUNDLE"
```

Allocated GPU, EFA and shared-claim probes used the immutable common workload
image `e98d074e…` and exercised CUDA/transport without loading a model.
The full Super VL TP2 model matrix has not been rerun on R610.
Native Snapshot still needs source launch wrapping and a fresh capture/restore;
the prior GMS/model startup failures also need separate qualification. The
driver/claim checks do not establish either complete feature.

The before-values files preserve rollback inputs. Do not use an uncoordinated
Helm rollback while GPU clients are active; hold node upgrades and use the same
maintenance/eviction sequence to reload the prior driver. A failed canary leaves
the other nodes skipped and records its state for recovery.

References: [GPU Operator driver upgrades](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-driver-upgrades.html),
[supported components](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html),
[installed driver manager client-eviction implementation](https://github.com/NVIDIA/k8s-driver-manager/blob/v0.12.0/cmd/driver-manager/main.go),
[installed NVSentinel maintenance runbook](https://github.com/NVIDIA/NVSentinel/blob/v1.20.0/docs/runbooks/driver-upgrades.md).
