# Super VL TP2 same-artifact EFS / RAM storage control

The same-artifact control passed **EFS / RAM / EFS restores and fresh inference**
with the new CuInterpose build. RAM reduced mean agent restore time from
**336.432s to 42.048s**, an **8.00x speedup** / **87.50% reduction**. The
recovered **294.384s** establishes the EFS read path as the dominant overhead
for this checkpoint. Cleanup and final inventory are recorded below.

The source is the exact Ready artifact from
`results/20261022-snapshot-cuinterpose-tp2-keepalive/`: content UID
`b0b67cbb-51b4-45da-9792-05cf6175014f`, 2,021 files and 98,903,175,597 logical
bytes. Model `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, revision
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`, TP=2 and common image digest
`e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d` stay fixed.
Snapshot operator/agent/PageBroker retain build `v0.0.0-gd752d982`.

The test copies the artifact into a disposable Kubernetes tmpfs volume and
checks every file SHA256 against EFS. It then runs EFS / RAM / EFS sequential
restores, each into a distinct Pod with two DRA GPUs and a new HTTP-triggered
READY response. The harness rejects timings if the physical GPU pair differs
from the qualified baseline. Copy and checksum time are excluded from restore
measurements and recorded separately. Direct CRIU image I/O stays enabled;
no host cache flush is performed. This is a bounded storage control, not a
cold-cache, concurrency, local-NVMe or production startup benchmark.

Only the selected artifact is overlaid read-only inside the existing agent's
private mount namespace. A compiled mount helper permits exactly this artifact
UID and the owned staging Pod's tmpfs subtree. It attaches no host-namespace
mount. PageBroker retains its EFS view; this captured artifact uses the legacy
filesystem/direct-restore path, so the agent's artifact mount is the path read
by CRIU. Shared agent specification, Helm release, PVCs and EFS contents are
preserved. No disk is formatted.

The CPU-only helper requests 4 CPU / 160 GiB RAM, limits CPU to 8 and memory to
256 GiB, and uses a 128 GiB tmpfs. Its deadline is two hours. Owned restore Pods
retain the passing source's resource requests/limits. Cleanup removes the
owned Pods and helper binary, restores the EFS view, checks the retained
Snapshot identity/readiness and requires zero GPU claims/active feature Pods.

```sh
RUN=results/REPLACE-WITH-A-FRESH-CONTROL
.local/venv/bin/python scripts/snapshot_tp2_storage_compare.py inspect --run "$RUN"
.local/venv/bin/python scripts/snapshot_tp2_storage_compare.py prepare-ram --run "$RUN"
.local/venv/bin/python scripts/snapshot_tp2_storage_compare.py compare --run "$RUN"
# compare cleans up automatically; cleanup is available after interruption.
.local/venv/bin/python scripts/snapshot_tp2_storage_compare.py cleanup --run "$RUN"
```

Evidence: `results/20261022-snapshot-tp2-ram-control/`.
The source capture's 16m55s EFS publication phase is recorded in the
[CuInterpose qualification report](2026-10-22-snapshot-cuinterpose.md). This
control measures restore overhead; it does not recapture or measure publication
to a RAM store.


## Measured results

| Restore | CRIU seconds | CUDA seconds | Agent total seconds | Pod to Ready seconds | Fresh inference |
| --- | ---: | ---: | ---: | ---: | --- |
| EFS 1 | 316.305 | 15.629 | 337.009 | 340 | Passed |
| RAM 1 | 25.626 | 14.583 | 42.048 | 47 | Passed |
| EFS 2 | 316.327 | 16.310 | 335.854 | 339 | Passed |

All three trials restored the exact content UID above on cp-0124, using
`gpu-1` and `gpu-3`, with the unchanged image/model/revision and separate Pod
UIDs. Each passed `nvidia.com/Restored=True`, exact image verification, an
actual two-GPU DRA allocation and a newly generated HTTP `READY` response.

The EFS repeats bracketed the RAM restore and differed by only 1.155s in total.
Mean CRIU time was **316.316s on EFS versus 25.626s in RAM**. CUDA restoration
remained **14.58-16.31s** across all three trials. The storage switch recovered
about **4m54s** of agent restore time. This identifies the EFS read path penalty
in this setup; it does not identify a service throughput quota, exhausted
credits, TLS/proxy limit, or a specific network bottleneck.

Staging cost **334s to copy** and **139s to verify every file SHA256**; both are
excluded from the restore measurements. The manifest hash is
`58ebf8c04fc310c3d9a2c924943f7a6f0079ac4fbe4469d8e6177338e314bbea`.
The helper's observed peak was 198,065,926,144 bytes (184.46 GiB), including RAM
artifact data and buffered EFS reads, with zero OOM events. This is an observed
allocation, not a minimum memory requirement.

For fast startup, the artifact must be **pre-staged and reused**: copying it
from EFS per restore would cost about **334 + 42 = 376s**, before checksum
verification, and would repay the storage delay. The 42s result is the observed
pre-staged RAM restore, not end-to-end cold staging or a promise for local NVMe.
A supported node cache integration remains separate implementation work.

The RAM copy held all 2,021 files / 98,903,175,597 bytes. No new capture was
performed, and RAM publication speed is unmeasured. The earlier capture's
16m55s EFS publication phase remains a separate measured result.


## Cleanup and final checks

Cleanup passed at **18:46:07 UTC October 22**. The private artifact view is back
on EFS, the helper Pod and temporary binary are removed, all restore Pods are
deleted, and the retained source Snapshot/content identity and Ready state are
unchanged. The agent Pod specification exactly matches its before-test copy.
The RAM artifact copy is gone; no permanent cache was installed.

The final inventory finished at **18:46:56 UTC** in
`results/20261022-snapshot-tp2-ram-final/`: all three nodes Ready, unchanged boot
IDs and condition statuses, 32 EFA resources per node, no active feature-test
Pods and zero ResourceClaims cluster-wide. Platform Helm revision 4 remains
deployed. Snapshot operator, agent and PageBroker are Ready with zero restarts.
Post-test kernel inspection found **no new Xids**; the older contained Xid 94
condition remains recorded. No driver reset, reboot or disk formatting occurred.

The four CuInterpose allocation/lifecycle guard tests passed, including the
new independent-restore claim/companion guard; Python compilation and
`git diff --check` passed. Live trial manifests, claims, after-restore Pod
conditions, individual model replies, phase logs, SHA manifest and analysis JSON
are retained under the evidence directory above. These results qualify this
bounded native Snapshot/direct-vLLM path, not Dynamo DGD integration, cross-node
restore, other models or RAM capture/publication.
