# Single-node NVMe disk preparation

Status: **prepared and verified**, October 22, 2026 at 19:59:40 UTC.
The user explicitly authorized formatting after the initial automatic approval
review rejection. Exactly one SSD on cp-0124 was initialized and mounted; the
other disks and Snapshot's active EFS storage were not changed.

- Filesystem: ext4, label `dyn-snap-demo`.
- UUID: `68d48707-ddd0-4094-b46b-a70255b4d25b`.
- Mount: `/mnt/dynamo-snapshot`, host namespace, `rw,noatime`.
- Available capacity: 3,797,617,467,392 bytes (about 3.80 TB / 3.45 TiB).
- A 4 MiB fsynced write and checksum-verified direct read passed; probe removed.
- Node remained Ready with the same boot ID; Snapshot agent UID and Pod spec
  remained unchanged. Agent `/checkpoints` still resolves to `nfs4`.
- No Helm upgrade, StorageClass/PV/PVC creation, fstab or service changes.

The mount is **runtime-only**. This verifies filesystem readiness, not NVMe
Snapshot capture/restore performance. Preloading/checksumming the artifact and
running the same-artifact storage comparison remain the next steps.

## Fresh verified identity

Read-only host-namespace inspection passed on October 22, 2026:

- Node: `kubecon-nke-site-cp-0124`, host machine ID matched the Kubernetes Node.
- Disk: `/dev/nvme0n1`, selected dynamically by serial `AWS135BFFA82D334433D`.
- Model: Amazon EC2 NVMe Instance Storage; size: 3,800,000,000,000 bytes.
- No partitions, device holders, swap, mounts or recognized wipefs signatures.
- OS backing disk is separate EBS `/dev/nvme1n1`.
- No existing `/mnt/dynamo-snapshot` mount or related fstab entry found.

These checks do not establish absence of unidentified raw data. Initializing
ext4 writes persistent disk metadata and could destroy such data. It was the
only irreversible operation authorized here; no other disk was initialized.

## Executed operation

The reusable script `scripts/prepare_snapshot_nvme_disk.py`:

1. Revalidates host identity, exact serial, model, size, no partitions/holders,
   root-device separation, swap absence and writable device state.
2. Before formatting, additionally rejects every recognized signature and mount.
3. Initializes only the verified serial as whole-device ext4, label
   `dyn-snap-demo`, with a fresh recorded UUID. No force or discard option is used.
   Reserved blocks are zero; largefile inode allocation and eager metadata/journal
   initialization avoid background initialization affecting subsequent tests.
4. Mounts by UUID at `/mnt/dynamo-snapshot` in the host mount namespace with
   `noatime`, refusing an occupied target or mismatched existing mount.
5. Checks filesystem identity, available capacity, a 4 MiB fsynced write and
   checksum-verified direct read; removes its probe file afterward.
6. Verifies the node remains Ready without reboot and the Snapshot agent UID
   remains unchanged.

This creates a **runtime-only host mount**. It does not alter fstab, node services,
Kubernetes storage objects, Helm values or the active EFS Snapshot store. A node
reboot will require remounting and verification. Automatic mount persistence
and a missing-mount guard remain prerequisites before adopting NVMe as workshop
primary storage; they are not part of this disk-only test preparation.

Commands executed under the explicit authorization (do not rerun initialization;
it will refuse the existing filesystem):

```sh
.local/venv/bin/python scripts/prepare_snapshot_nvme_disk.py initialize \
  --run results/20261022-snapshot-nvme-prepare \
  --approved-serial AWS135BFFA82D334433D
.local/venv/bin/python scripts/prepare_snapshot_nvme_disk.py mount \
  --run results/20261022-snapshot-nvme-prepare
.local/venv/bin/python scripts/prepare_snapshot_nvme_disk.py verify \
  --run results/20261022-snapshot-nvme-prepare
```

Inspection evidence: `results/20261022-snapshot-nvme-prepare/`, including
`nvme-inspect-*.log`, signature inspection and command receipts. Script syntax
compilation and formatting/mount/direct-I/O execution passed. The run contains
the recorded UUID, explicit authorization, initialization/mount/verification
logs, active-EFS evidence, node/agent snapshots and a passed result receipt.
The future storage/Helm configuration is separate:
[full NVMe plan](2026-10-22-snapshot-nvme-demo-plan.md).
