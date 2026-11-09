# Driver upgrade ownership and feasibility — October 15, 2026

The current cluster can use an NVIDIA GPU Operator driver upgrade; a rebuilt
node image is not inherently required. Live read-only inspection confirms the
operator owns and runs the containerized driver on all three nodes.

| Setting | Observed value |
| --- | --- |
| Authoritative resource | `ClusterPolicy/cluster-policy` |
| Driver management | `spec.driver.enabled: true`; `useNvidiaDriverCRD: false` |
| Current version/image | `580.173.02`; `nvcr.io/nvidia/driver:580.173.02-ubuntu24.04` |
| Driver DaemonSet | `nvidia-driver-daemonset`, owned by the ClusterPolicy, 3/3 Ready |
| Precompiled driver | Disabled; `usePrecompiled: false` |
| Upgrade controller | `autoUpgrade: true`, `maxParallelUpgrades: 1` |
| Automatic node drain | Disabled |

The persistent change belongs in the Helm values for release `gpu-operator`,
namespace `gpu-operator`: `driver.version`. That reconciles to
`ClusterPolicy/cluster-policy.spec.driver.version`. Export fresh live Helm values
for a new review bundle; do not overwrite the previous hash-locked DRA transition
bundle or use it as an unreviewed driver-upgrade apply script.

NVIDIA's [GPU Operator component matrix](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
lists **610.57.04** with the installed **26.7.0** Operator. The
[Ubuntu 24.04 driver container](https://catalog.ngc.nvidia.com/orgs/nvidia/-/containers/driver/610.57.04-ubuntu24.04/layers)
is published. This establishes a concrete candidate, not successful installation
on this cluster's `7.0.0-1012-aws` kernel. Before applying, verify matching headers,
module build/load requirements and the GDRCopy/NVSwitch dependencies, then prepare
a complete reviewed Helm upgrade and rollback plan. Upgrade kernel modules with
GPU clients stopped, and requalify DRA, CUDA, NCCL and EFA/GPUDirect afterward.

The operator installs and reloads the host GPU kernel modules; putting the driver
in a container does not make this a workload-only change. A reboot is not an
inherent requirement of the documented upgrade sequence, but module-unload/build
failures could require node maintenance. The current automatic-upgrade policy
means changing the desired version can immediately start reconciliation.

If drivers had been baked into the host image instead, GPU Operator would not
manage their lifecycle. That is not the deployment observed here. See NVIDIA's
[driver upgrade procedure](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-driver-upgrades.html).

Evidence: `results/20261015-driver-upgrade-feasibility/driver-management.json` and
immutable command receipts, collected with `scripts/inspect_driver_management.py`.
No upgrade, node drain, reboot or shared-resource mutation was applied.
