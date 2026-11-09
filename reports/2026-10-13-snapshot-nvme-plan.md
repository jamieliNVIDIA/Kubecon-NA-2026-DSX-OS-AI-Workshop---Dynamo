# Snapshot local NVMe comparison proposal

Historical TP1 proposal. The [current Super VL TP2 NVMe setup and estimate](2026-10-22-snapshot-nvme-demo-plan.md) uses the October 22 CuInterpose build and 98.90 GB artifact. The earlier formatting refusal below remains in force.

**Not applied.** The user declined disk formatting and approved a RAM-backed
storage control instead. The device remains untouched. The active test uses
`scripts/snapshot_storage_compare.py prepare-ram|compare|cleanup`, a disposable
48 GiB tmpfs volume and the original Snapshot 0.1.0 agent. This does not measure
NVMe performance.

Prepared 2026-10-14T00:28:03.006650+00:00. No device writes performed.

On **kubecon-nke-site-cp-0124**, **/dev/nvme0n1** is `Amazon EC2 NVMe Instance Storage`, serial **AWS135BFFA82D334433D**, 3,800,000,000,000 bytes. Read-only blkid/wipefs checks found no filesystem or partition signature. None of the eight instance devices is mounted. The EBS root filesystem has only about 33 GiB free.

The proposal initializes only this device with ext4. It must be explicitly approved: absence of recognizable signatures does not prove absence of raw data. The filesystem metadata persists after test cleanup.

Use a temporary mount in the existing agent's private mount namespace. Copy and verify the existing 35,871,594,315-byte checkpoint, then temporarily bind the local copy read-only over that artifact path for a single restore. EFS artifact contents, host mounts, fstab, the Helm release, agent specification and PVC configuration stay unchanged. Only the selected artifact's view inside this agent changes during the local test.

Run EFS / NVMe / EFS restores with the same image, model, TP1 GPU allocation and resource requests. Record CRIU/CUDA/total restore timing, Pod readiness and a fresh inference result. Retain direct image I/O and avoid system-wide cache flushing. Include copy time separately from restore time: pre-staging costs are not startup acceleration.

Cleanup deletes only owned test resources and unmounts the artifact overlay and local filesystem. The original checkpoint remains on EFS.

Reusable inspection: `scripts/snapshot_storage_compare.py inspect|disks|plan --run results/20261013-snapshot-storage-compare`.
