# Complete GPU DRA Helm upgrade for the demo cluster

Prepared October 14, 2026. **Not applied.** Both Helm server dry-runs passed;
the subsequent read-only readiness check passed with no workload blockers.

Later October 14 live check: GPU DRA is now enabled on all three nodes and the
competing GPU device plugin is absent. Shared-claim CUDA passed on every node.
The agent did not apply this saved bundle; its original Helm baseline is now
historical, so do not rerun it to enable an already-working allocator. The
current installation retains ComputeDomain support alongside GPU allocation.
See [live Shadow qualification](2026-10-14-shadow-engine-retest.md).

The proposal's fragment configures the Helm release
`nvidia-dra-driver-gpu` in namespace `nvidia-dra-driver`. In this repository,
use **`configs/cluster-upgrade/gpu-dra-values.yaml`**. It contains the complete
computed values exported from the live release, with the proposed GPU settings
already incorporated. A second complete file,
**`configs/cluster-upgrade/gpu-operator-values.yaml`**, disables the competing
NVIDIA GPU device plugin in release `gpu-operator`, namespace `gpu-operator`.

| Release | Pinned chart | Target changes |
| --- | --- | --- |
| `gpu-operator` | `gpu-operator-v26.7.0` | `devicePlugin.enabled: false` |
| `nvidia-dra-driver-gpu` | `dra-driver-nvidia-gpu-0.5.0` | Enable GPU resources and override; disable ComputeDomains; driver root `/run/nvidia/driver`; unrestricted GPU-node selector |

These change allocation configuration at the existing software versions.
The full values retain the installed custom affinity, tolerations, names,
driver/toolkit/CDI settings, images and monitoring configuration. The rendered
ClusterPolicy disables the device plugin; the DRA chart renders the
`gpu.nvidia.com` DeviceClass and a GPU-only kubelet plugin. The [0.5.0 chart
installation reference](https://github.com/kubernetes-sigs/dra-driver-nvidia-gpu/blob/v0.5.0/site/content/docs/install.md)
documents the standalone configuration keys. This proposal uses the existing
standalone layout for the experimental demo; it is not the newer managed
`GPUCluster` installation workflow.

The cluster uses Helm releases as the immediate configuration interface. The
path to DSX's separate provisioning repository/IaC values file has not been
identified here. DSX should incorporate the resulting settings into that source
of truth when applying; do not assume our local file is automatically reconciled
by their provisioning system.

## Apply from this workspace after approval

First run the read-only checks:

```sh
.local/venv/bin/python scripts/apply_gpu_dra_upgrade.py \
  --run results/20261014-gpu-dra-upgrade-check
```

After approval of the cluster-wide allocator change, apply the reviewed bundle:

```sh
.local/venv/bin/python scripts/apply_gpu_dra_upgrade.py \
  --run results/20261014-gpu-dra-upgrade-apply --apply
```

The script starts the existing jump-host tunnel and selects the workshop
kubeconfig explicitly. It checks chart/value SHA-256, installed Helm revisions
and computed values, and the three reviewed node identities. It repeats Helm
server dry-runs, then refuses mutation if GPU Pods/controllers, DGDs, claims or
ComputeDomains remain. It does not stop workloads automatically.

Application order:

1. Upgrade `gpu-operator` using its complete values and the pinned chart with
   `--reset-values --wait --timeout 10m`.
2. Wait for every NVIDIA GPU device-plugin Pod to stop and confirm the
   ClusterPolicy has GPU device-plugin allocation disabled.
3. Recheck workload absence and upgrade `nvidia-dra-driver-gpu` with its complete
   values and pinned chart using the same wait/reset settings.
4. Wait for Ready GPU DRA plugins on all three nodes, eight devices per node in
   GPU ResourceSlices, and `gpu.nvidia.com` registration. Recheck that the old
   allocator has not returned.

This replaces the illustrative fragment with two full values files and a guarded
execution path. `--reset-values` is intentional: the full exported values are
the input, so stale release overrides are not merged back into the target.
No Kubernetes, driver, Dynamo, EFA, Grove or Snapshot version change is part of
this allocator upgrade. Demo manifest/harness migration and the feature retests
remain in the [cluster proposal](2026-10-13-cluster-setup-next-steps.md).

## Evidence and recovery

- Review: `results/20261014-gpu-dra-upgrade-review/`; full original user/computed
  values, matching chart archives, rendered manifests and both server dry-runs.
- Readiness: `results/20261014-gpu-dra-upgrade-check/`; passed, no blockers.
- Lock: `configs/cluster-upgrade/gpu-dra-upgrade-lock.json`; original release
  revisions, values/chart hashes and source locations.
- Eight offline guard tests passed, covering pending GPU Pods, controller
  recreation, outstanding claims, GPU labels, EFA and configuration preservation.

Keep the ignored `results/` review directory: the apply script uses its pinned
chart archives and baseline node snapshot. If Helm values/revisions or node
identities change, prepare a fresh review rather than bypassing the guard.
The preparation script can verify the saved bundle offline:

```sh
.local/venv/bin/python scripts/prepare_gpu_dra_upgrade.py \
  --check-only --run results/20261014-gpu-dra-upgrade-review
```

There is no automatic rollback across the two releases. If an application step
fails, inspect its saved receipts before proceeding. To return to the old
allocator, stop GPU DRA consumers and their controllers, remove their claims,
disable GPU allocation in DRA and verify its GPU plugins have stopped, then
restore the original GPU Operator values/revision. Never roll back the GPU
Operator alone while GPU DRA still owns GPUs.

Server dry-run and inventory validation do not prove CUDA/CDI injection or
Shadow failover. After applying, qualify one-claim CUDA on each node, shared GPU
UUID/CUDA access from two containers, then the preferred-model recovery test and
the remaining demo matrix.
