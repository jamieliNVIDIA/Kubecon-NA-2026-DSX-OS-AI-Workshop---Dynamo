# NVMe timing estimate and single-node Snapshot demo setup

Storage/Helm proposal remains unapplied. The one-disk filesystem prerequisite
was subsequently explicitly authorized and completed on cp-0124; see the
[disk preparation result](2026-10-22-snapshot-nvme-disk-preparation.md).
It is a runtime-only host mount; persistent boot setup and a missing-mount guard
remain outstanding. The active Snapshot store remains EFS. The candidate values,
rollback values and review metadata below preserve their original review state.

## Measured restore update

The [same-artifact NVMe control](2026-10-22-snapshot-tp2-nvme-comparison.md)
subsequently passed EFS/NVMe/NVMe/EFS restores and fresh inference. NVMe took
**37.814s / 36.915s** (mean **37.365s**, Pods Ready **40-41s**) versus EFS mean
**336.237s**, a **9.00x** speedup. The SSD recorded **196.816 GB** reads across
the two NVMe trials. One-time copy/flush **188s** plus hash verification **68.84s**
are excluded. The NVMe copy remains, while the agent is back on EFS and shared
configuration remains unchanged. This supersedes the restore estimate below
for this artifact/node; NVMe capture/publication timing is still unmeasured.

## Original timing estimate

For the exact 98,903,175,597-byte Super VL TP2 artifact, the
[measured control](2026-10-22-snapshot-tp2-storage-comparison.md) gives EFS mean
restore **336.43s**, RAM restore **42.05s**, and CRIU **316.32s / 25.63s**.
The same image, model revision, physical GPU pair and direct CRIU image I/O
must be retained when qualifying NVMe.

A deliberately conservative planning calculation is:

`NVMe restore seconds ~= 42.05 + 98.90 / effective read GB-per-second`

It adds the full NVMe read cost to the RAM path; CPU reconstruction and I/O may
overlap, so this is a sizing estimate, not a fitted performance model. The
bandwidth values below are assumptions about the actual restore path, not
measured device performance or advertised specifications.

| Effective NVMe read bandwidth | Estimated agent restore |
| --- | ---: |
| 1 GB/s | 141s |
| 2 GB/s | 92s |
| 3 GB/s | 75s |
| 5 GB/s | 62s |

Budget **roughly 1-2 minutes for an already-local artifact** if the actual read
path sustains 2-4 GB/s; allow a few more seconds for Pod scheduling/readiness.
At 1 GB/s, plan nearer 2m20s. A single disk's real throughput is unmeasured;
RAM's 42s result is not a promise for NVMe. No raw uninitialized-device read
benchmark was used as a proxy for populated-checkpoint performance.

The successful capture took 1151.52s, including 1015.08s publication, leaving
**136.44s** of other capture work. Replacing EFS publication with a local write
at an assumed 1-3 GB/s gives about **170-235s**, before additional filesystem
flush/metadata effects: approximately **3-4 minutes** is a planning target,
with extra margin until tested. This excludes cold model loading, compilation
and warmup. It is an extrapolation; NVMe capture/publication has not been run.
Switching only the restore cache leaves EFS capture publication unchanged.

Preloading from EFS still pays the network read cost once. Our RAM copy took
334s plus 139s hash verification. Pre-stage the local artifact before the
workshop and reuse it across restores; do not copy it per worker startup.

## Current disk state

Before preparation, inspection on cp-0124 found eight **3.8 TB Amazon EC2 NVMe instance-store
SSDs** with no reported filesystems or mounts. The candidate `/dev/nvme0n1`
retained serial **AWS135BFFA82D334433D**, size 3,800,000,000,000 bytes, no partition
children, no blkid/wipefs signature and no holders. It is now initialized as
ext4 and mounted at `/mnt/dynamo-snapshot` after explicit authorization; the
other seven instance SSDs were not changed. This is not proof of absence
of unidentified raw data. The OS is on the separate EBS device `/dev/nvme1n1`.
Use the verified disk identity and filesystem UUID for provisioning; NVMe device
numbers alone are not stable identifiers.

One SSD is ample for the demo. Allow **500 GiB to 1 TiB** for the current
~99 GB artifact, retained versions and partial publication/copy space. The
prepared PV advertises 1 TiB; that is a scheduler capacity declaration, not a
filesystem quota or a requirement to partition a whole 3.8 TB device.

## Initial demo setup: one Snapshot node

1. DSX provisions an ext4 or XFS filesystem on one explicitly approved instance
   SSD and mounts it at **`/mnt/dynamo-snapshot`** on cp-0124. The directory must
   be an actual NVMe mount, not a directory silently falling back to EBS when
   a mount is absent. Configure the mount through node bootstrap/systemd using
   stable device identity, with a mount/kubelet startup dependency or equivalent
   guard that prevents Snapshot from starting when the NVMe mount is absent.
   The candidate Kubernetes YAML does not establish that host dependency.
   This does not require rebuilding the GPU driver or
   common runtime image. No formatting command is included in this proposal.
2. Apply the prepared static local StorageClass/PV/PVC. The PV has cp-0124 node
   affinity, `Retain`, filesystem mode and **ReadWriteOnce**. Use an existing
   claim (`storage.pvc.create=false`) so the chart does not create its default
   shared RWX claim. RWO permits several Pods on the same node; it does not
   provide cross-node storage. See [Kubernetes local volumes](https://kubernetes.io/docs/concepts/storage/volumes/#local)
   and [access modes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes).
3. Before changing Snapshot's store, use an owned staging Job on cp-0124 with
   the EFS source mounted read-only and the new local claim writable. Copy the
   preferred Ready artifact and verify every file hash, preserving the layout
   **`artifacts/<content-UID>/containers/main/...`**. Retain the EFS copy and
   original values. The currently qualified content uses the legacy filesystem
   mode, without a bound store reference; validate its identity and restore from
   the copied path. This is not a general migration recipe for bound artifacts.
4. Upgrade the existing release using the prepared **complete values**. Both
   agent and PageBroker mount the NVMe claim at **`/checkpoints`**. The Snapshot
   operator also mounts it and must move from cp-0198 to **cp-0124**. Keep the
   agent's existing cp-0124 restriction, `pageBroker.restoreMode: direct`, RAM
   staging cap and memory limits, seccomp, R610 driver and all image digests.
   Local NVMe changes the persistent artifact mount; RAM staging remains needed.
5. Run EFS / NVMe / EFS same-artifact restore controls, checking actual NVMe
   backing and direct I/O, exact image, two DRA GPUs, distinct restored Pod UID,
   `Restored=True` and fresh READY inference. Then capture a **fresh** Snapshot
   onto the local store and measure publication, restoring and inferring from
   it. Retain the CPU companion workaround until publication is demonstrated
   within the controller's five-minute source-terminal grace. Do not infer that
   the timeout is fixed merely because storage should be faster.
6. Keep EFS as an explicit backup/export destination. Local-primary captures do
   **not** automatically replicate back to EFS with this values change. Copy
   and verify new Ready artifacts separately; account for backup time outside
   the fast demonstration path. EC2 instance-store data can be lost on
   stop/termination or disk failure: [AWS persistence documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-store-lifetime.html).

This is an **experimental single-node topology** based on inspection of the
installed chart; local-store runtime behavior is not qualified yet. Upstream's
[storage contract](https://github.com/ai-dynamo/snapshot/blob/d752d982738883e3575de7bbce0689e2443fa2c2/docs/operations/storage.md)
assumes a shared RWX PVC for agents across nodes. This one-node variant uses
RWO with every consumer colocated, and needs the runtime tests above. It does
not add Dynamo DGD integration or qualify cross-node restore.

## Complete candidate files and validation

- [`configs/snapshot-nvme-demo-20261022/storage.yaml`](../configs/snapshot-nvme-demo-20261022/storage.yaml):
  static StorageClass, local PV and PVC.
- [`configs/snapshot-nvme-demo-20261022/values.yaml`](../configs/snapshot-nvme-demo-20261022/values.yaml):
  full release values, preserving the pinned build and unrelated configuration.
- [`rollback-values.yaml`](../configs/snapshot-nvme-demo-20261022/rollback-values.yaml):
  current EFS release values.
- [`review.json`](../configs/snapshot-nvme-demo-20261022/review.json):
  current device identity, file/chart hashes, prerequisites and `applied: false`.

The same packaged platform 1.5.1 / pinned Snapshot chart is reused from
`configs/snapshot-upgrade-20261022/dynamo-platform-1.5.1-snapshot-dev.tgz`.
Local chart rendering changes only Snapshot's ConfigMap, agent DaemonSet and
operator Deployment. The StorageClass/PV/PVC server dry-run passed. That
validates schemas, not the missing host filesystem or end-to-end behavior.
The new claim and operator placement changes are fully expressed in the values;
there is no fragment to merge into the old file.

Read-only preparation:

```sh
.local/venv/bin/python scripts/prepare_snapshot_nvme_demo.py \
  --run results/20261022-snapshot-nvme-review
```

The prepared bundle is immutable for this review; regenerating requires a fresh
output directory/review. No apply or format action exists in the script.
Inspection/dry-run evidence: `results/20261022-snapshot-nvme-proposal/` and
`results/20261022-snapshot-nvme-review/`.

## Expanding to all three nodes

One local PVC is tied to one node; adding NVMe to all hosts does not make it
RWX. The current chart uses one fixed PVC name for the operator and all agents,
so the prepared one-node RWO claim must not be used with a three-node DaemonSet.
For multi-node Snapshot demos, add explicit per-node stores or a supported
node-local cache layer, distribute hash-verified compatible artifacts ahead
of time, gate placement on cache readiness, and install/qualify the Snapshot
agent/seccomp setup on each selected node. The chart/store identity and cleanup
paths need to understand that topology; three conflicting operators watching
the same resources are not a substitute. Validate actual cross-node restore.
For the immediate workshop, keeping Snapshot on cp-0124 is the smaller change.
