# Super VL TP2 same-artifact NVMe restore control

Status: **passed**, including all four restores, fresh inference, cleanup
and final health/inventory checks. Pre-staged NVMe reduced mean agent restore
from **336.237s to 37.365s**: **9.00x faster**, **88.89% less time**, saving
**298.872s**. NVMe Pods reached Ready in **40s / 41s**.
Evidence: `results/20261022-snapshot-tp2-nvme-control/`.

The control reuses the exact Ready content
`b0b67cbb-51b4-45da-9792-05cf6175014f`, 2,021 files / 98,903,175,597
logical bytes, from the passing CuInterpose capture. Model:
`nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, revision
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`, TP=2. Runtime digest:
`e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
Snapshot retains pinned development build `v0.0.0-gd752d982`.

## Method

1. Verify idle feature workloads/GPU claims, artifact identity/readiness,
   image pins, direct CRIU image I/O and cp-0124 NVMe mount identity.
2. Copy the checkpoint once from EFS into the approved host filesystem
   `/mnt/dynamo-snapshot/artifacts/<content-UID>`. Fsync the copy, verify all
   file SHA256 hashes against the qualified EFS/RAM manifest, then rename
   the partial copy into place. Hash-manifest SHA256:
   `58ebf8c04fc310c3d9a2c924943f7a6f0079ac4fbe4469d8e6177338e314bbea`.
3. Restore sequentially from EFS, NVMe, NVMe, EFS. Each uses a distinct Pod,
   the qualified actual GPU pair (`gpu-1` and `gpu-3`), exact runtime/model
   identity, `nvidia.com/Restored=True` and fresh HTTP READY inference.
4. Attribute timing only from the agent summary matching this Pod name and
   exact content UID; collect phase durations and Pod-to-Ready time separately.
5. Delete owned restored Pods, restore EFS view, remove the temporary mount
   helper, verify retained source identity, unchanged agent specification and
   idle claims/workloads. Leave the verified NVMe copy for reuse.

The SSD is ext4 on cp-0124, serial `AWS135BFFA82D334433D`, filesystem UUID
`68d48707-ddd0-4094-b46b-a70255b4d25b`. Only this artifact is overlaid read-only
inside the existing agent's private mount namespace using a narrowly scoped
compiled helper. No host mount is changed by this comparison; the previously
prepared runtime-only host NVMe mount remains. PageBroker retains EFS. This
legacy filesystem artifact's direct CRIU restore reads through the agent view.
No Helm values, shared specifications, PVCs or EFS artifact data are modified.

Staging and verification costs are excluded from restore timing and reported
separately. Direct CRIU I/O is retained; no global cache flush is performed.
This is a bounded same-node storage control, not a cold-cache/concurrency,
NVMe capture/publication, production cache, or Dynamo DGD qualification.

## Reusable scripts

```sh
RUN=results/REPLACE-WITH-FRESH-NVME-CONTROL
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py inspect --run "$RUN"
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py stage --run "$RUN"
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py stage-progress --run "$RUN"
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py compare --run "$RUN"
# compare cleans up automatically; explicit cleanup is available after interruption.
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py cleanup --run "$RUN"
```

The staging command refuses an existing destination. After a partial copy or
for reusing the retained NVMe artifact in a fresh campaign, inspect identity and
hashes rather than overwriting or deleting data automatically.

## Measured results

| Trial | CRIU seconds | CUDA seconds | Agent total seconds | Pod to Ready seconds | Fresh inference |
| --- | ---: | ---: | ---: | ---: | --- |
| EFS 1 | 316.184 | 18.718 | 338.318 | 342 | Passed |
| NVMe 1 | 19.947 | 14.864 | 37.814 | 40 | Passed |
| NVMe 2 | 20.039 | 15.194 | 36.915 | 41 | Passed |
| EFS 2 | 316.206 | 13.878 | 334.155 | 336 | Passed |

Both NVMe trials used the same artifact and physical GPU pair as the EFS
control, with distinct restored Pod UIDs and fresh inference. The observed
NVMe block-device read counter increased **196,816,379,904 bytes** across the
two NVMe trials. This establishes actual SSD reads, rather than a filesystem
label masking an entirely RAM-cached result. File metadata/cache was not
flushed; this remains a pre-staged same-node control, not a cold-cache benchmark.

Copying/flushing the checkpoint took **188s**; verification of all 2,021 hashes
against the locked manifest took **68.84s**. Both costs are excluded from restore
timing. The copy remains on NVMe for reuse.

Mean CRIU time fell from **316.195s on EFS to 19.993s on NVMe**. Mean CUDA
restore was **16.298s / 15.029s**, respectively; most of the gain is in the
CRIU read path. The EFS controls bracketed the two NVMe trials; their CRIU
phases differed by only 0.021s. NVMe agent totals differed by 0.899s.

The [earlier same-artifact RAM control](2026-10-22-snapshot-tp2-storage-comparison.md)
measured **42.048s** agent restore / **47s** Pod-to-Ready, with fresh inference.
It was one earlier RAM trial, not an interleaved RAM-versus-NVMe experiment;
these samples establish similar startup latency, not a general NVMe-over-RAM
performance ranking.

This result is substantially faster than the earlier 1-2 minute planning
estimate. That estimate added an assumed full-file read to the entire RAM
restore duration. Actual phase timing and device read counters now supersede
that conservative estimate for this artifact and node. Do not extrapolate the
restore result to the still-unmeasured NVMe capture/publication path.

## Cleanup and final inventory

Cleanup passed **20:24:13 UTC October 22**: all four owned workers are deleted,
the private artifact overlay and temporary helper binary are gone, and the
agent's artifact path is back on EFS. Source Snapshot/content identity and
Ready state are retained; the agent Pod specification matches its before-test
copy. The verified ~99 GB NVMe checkpoint remains for reuse. The host SSD
mount remains runtime-only and needs remounting after reboot.

Post-test GPU/kernel health inspection completed **20:24:47 UTC** with no new
Xid entries or changed node conditions. Agent and PageBroker are Ready with
zero restarts. The historical contained Xid 94 remains a prior condition.
Final inventory completed **20:25:09 UTC** in
`results/20261022-snapshot-tp2-nvme-final/`: all three nodes Ready, unchanged
boot IDs/condition statuses, 32 EFA resources per node, zero ResourceClaims and
no active feature-test Pods. Platform Helm revision **4** remains deployed.
No Helm/PVC or shared storage configuration changes were made by this test.

The four CuInterpose allocation/lifecycle guard tests, Python compilation and
`git diff --check` passed. Raw per-trial manifests, Pod conditions/UIDs, actual
DRA claims, image identity, inference responses, exact-content phase logs,
SHA256 manifest, file verification output, disk counters and computed analysis
are retained in the evidence directory. `nvme-comparison-analysis.json` can be
regenerated locally with:

```sh
.local/venv/bin/python scripts/snapshot_tp2_nvme_compare.py summarize \
  --run results/20261022-snapshot-tp2-nvme-control
```
