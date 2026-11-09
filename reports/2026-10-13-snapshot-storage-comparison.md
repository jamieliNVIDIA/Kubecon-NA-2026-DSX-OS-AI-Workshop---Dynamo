# Snapshot same-artifact EFS / RAM comparison

Updated 2026-10-14T01:12:05.480768+00:00. Cleanup: **passed**.

The user declined NVMe formatting and approved a RAM-backed control. No disk was formatted. The test reused Snapshot 0.1.0, the same pinned common workload image, the Nemotron model/revision, cp-0124 and TP1 worker resource requests/limits. The original 33.41 GiB artifact was copied into a disposable tmpfs volume; every file SHA256 was checked against EFS. This is not an NVMe performance result.

| Restore | CRIU seconds | CUDA seconds | Agent total seconds | Pod → Ready seconds | Fresh inference |
| --- | ---: | ---: | ---: | ---: | --- |
| EFS 1 | 115.348 | 8.504 | 124.421 | 139 | passed |
| RAM 1 | 5.382 | 8.277 | 14.200 | 30 | passed |
| EFS 2 | 115.239 | 8.147 | 123.967 | 139 | passed |

Copy seconds: **127** (excluded from restore measurements).

Verification seconds: **63** (excluded from restore measurements).

Mean observed EFS agent restore: **124.194s**; RAM control: **14.200s**, **8.75×** faster. This is a bounded storage control, not a concurrency/cold-cache benchmark or a guaranteed production startup time. Pre-staging costs and memory reservation remain separate.

CRIU fell from **115.294s** on EFS to **5.382s** in RAM. The EFS process samples show NFS RPC waits while reading memory pages. This control establishes the EFS read path as the dominant delay for this artifact; it does not identify an EFS service throughput cap, exhausted credits or a specific NFS/TLS bottleneck. Copying the checkpoint again for every Pod would repay the EFS read cost. Startup acceleration therefore needs pre-staging and a reusable node cache, or faster artifact storage, rather than per-Pod copying.

During the RAM restore, only the selected artifact path was bound read-only to tmpfs inside the existing agent's private mount namespace. The EFS contents, Helm release, agent specification, PVC and persistent host storage configuration were preserved. A narrow checked-in C helper uses the same detached-mount APIs as Snapshot 0.1.0. It enters the source namespace only to clone the tmpfs subtree, then returns to the agent namespace before attaching it read-only. No mount is attached in the host namespace. Only the disposable helper's ordinary Kubernetes tmpfs volume adds a temporary host mount. Direct CRIU image I/O was retained and no system-wide cache flush was used.

The sequential worker restores use one GPU at a time. The CPU-only staging helper requests 2 CPU / 48 GiB RAM, limits RAM to 64 GiB and uses a 48 GiB tmpfs volume.

Reusable commands:

```sh
RUN=results/<fresh-storage-comparison>
.local/venv/bin/python scripts/snapshot_storage_compare.py inspect --run "$RUN"
.local/venv/bin/python scripts/snapshot_storage_compare.py prepare-ram --run "$RUN"
.local/venv/bin/python scripts/snapshot_storage_compare.py compare --run "$RUN"
# compare cleans up automatically; cleanup is also available after interruption.
.local/venv/bin/python scripts/snapshot_storage_compare.py cleanup --run "$RUN"
.local/venv/bin/python scripts/snapshot_storage_compare.py report --run "$RUN"
```

Evidence: `results/20261013-snapshot-storage-compare/`, including `artifact-files.sha256`, the source API objects, per-Pod manifests, phase summaries and fresh inference responses.

An initial harness attempt completed EFS restore but had no worker discovery Service for EndpointSlices, so fresh inference failed. Its evidence is retained and excluded from the passed comparison. A subsequent EFS baseline passed inference; a legacy cross-namespace bind then failed before the RAM restore started. One-byte probes validated the detached-mount method before the final control. The passed EFS baseline was reused, and the final EFS repeat follows the RAM result.
