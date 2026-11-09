# Snapshot CuInterpose upgrade and Nemotron TP2 retest

The approved Snapshot-only upgrade completed at **17:05:39 UTC October 22**.
**Native Super VL TP=2 capture, restore and fresh inference passed** with the
unchanged common image. The passing run uses CuInterpose, upstream direct-vLLM
preparation and a test-local CPU companion to avoid the controller's five-minute
terminal-source grace during slow EFS publication. This qualifies the native
SnapshotJob path on one node; Dynamo DGD lifecycle integration remains untested
with CuInterpose.

Pinned upstream references: [multi-GPU architecture](https://github.com/ai-dynamo/snapshot/blob/d752d982738883e3575de7bbce0689e2443fa2c2/docs/reference/architecture/multi-gpu.md),
[vLLM preparation app](https://github.com/ai-dynamo/snapshot/blob/d752d982738883e3575de7bbce0689e2443fa2c2/docs/guides/vllm/app.py),
and [terminal-source grace](https://github.com/ai-dynamo/snapshot/blob/d752d982738883e3575de7bbce0689e2443fa2c2/operator/internal/controller/podsnapshot_reconciler.go#L204).

## Installed change

- Snapshot source: `d752d982738883e3575de7bbce0689e2443fa2c2`, published build
  `v0.0.0-gd752d982`. The chart's static appVersion remains `v0.1.0`; use the
  source SHA and image digests to identify this development build.
- Matching operator, agent and PageBroker images are pinned in
  [`images.json`](../configs/snapshot-upgrade-20261022/images.json).
- The existing `dynamo-platform` Helm release was upgraded in place. Its
  platform chart is still 1.5.1; only the bundled Snapshot subchart changes.
  Server dry-run comparison found changes only to Snapshot's ConfigMap,
  DaemonSet and operator Deployment. The Snapshot CRD installer updated
  PodSnapshotContent and SnapshotJob schemas; storage remains `v1alpha1`.
- The agent remains restricted to `kubecon-nke-site-cp-0124`. Operator and both
  agent/privileged PageBroker containers report ready, zero restarts. NRI
  registered successfully with containerd 2.3.5 / runtime NRI 0.12.0.
- Fresh RWX EFS claim: `dynamo-system/snapshot-artifacts-cuinterpose`, static
  Retain PV `dynamo-workshop-snapshot-cuinterpose`. Export subdirectory:
  `/feature-tests/20261022-snapshot-cuinterpose-upgrade/snapshot-artifacts`.
  Both root-directory and actual subdirectory-PVC aligned 4 KiB direct-I/O
  correctness checks passed. This is not a bandwidth benchmark.
- The earlier artifact PVC/export and Snapshot API objects are retained.
  Dynamo operator, Grove, KAI, GPU/EFA drivers and model cache are unchanged.

The complete values and packaged chart are in
[`configs/snapshot-upgrade-20261022/`](../configs/snapshot-upgrade-20261022/).
One recorded local chart-template adjustment gives PageBroker its own immutable
image digest, while retaining the same source build as the agent. Upstream's
default template derives PageBroker's tag from the agent tag, which cannot use
two different image digests. No Snapshot runtime source was patched.

Agent and PageBroker memory limits are each 384 GiB; RAM staging is capped at
320 GiB. Requests are 16 GiB and 40 GiB respectively, including the default
32 GiB GPU transfer ring. The TP2 source requests 256 GiB and is limited to
512 GiB to allow shared-memory carriers. These are conservative test bounds,
not measured minimum requirements. cp-0124 has about 1,976 GiB allocatable RAM.
Saved cgroup observations during the keepalive retry measured source Pod peak
**174,338,658,304 bytes (162.37 GiB)**, restored Pod peak
**98,849,914,880 bytes (92.06 GiB)** and agent/PageBroker Pod peak
**297,490,583,552 bytes (277.06 GiB)**, with zero OOM/OOM-kill events. The latter
includes both captures in the same agent Pod and includes cache/staging; it is
not a per-container or per-capture minimum.

Upgrade receipts, pre-upgrade Helm values/manifests/CRDs/objects and rendered
server dry-run are under `results/20261022-snapshot-cuinterpose-upgrade/`.
The pre-upgrade cluster inventory is
`results/20261022-snapshot-cuinterpose-before/`.

## Test scope and method

Run: `results/20261022-snapshot-cuinterpose-tp2/`; namespace
`dynamo-ft-20261022t170500z`.

- Same model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`.
- Same revision: `8a115b9d966adce8c059a7bcf47f49a1e57957d8`; TP=2.
- Same common runtime image:
  `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- All 88 cached weight files, 75,010,188,240 actual bytes, and metadata hashes
  reverified before deployment. No model download or substitution.
- The source adapts the pinned upstream SnapshotJob recipe; GPU scalar requests
  are converted to an actual two-GPU NVIDIA DRA claim.
- `nvidia.com/snapshot-multi-gpu: enabled` opts in. Snapshot injects its matching
  launcher and both interposer libraries before CUDA initialization.
- The model uses compiled execution (`enforce_eager=false`) and default NCCL
  allocation settings; neither the eager nor legacy-allocation workaround is
  needed for this pass.
- The mounted test application explicitly uses `spawn`. It follows upstream's
  direct vLLM `pause_generation` / `release_kv_cache_memory` preparation. It
  does not call Dynamo's previous per-library communicator checkpoint hooks.
- The application gates capture after correct `READY` generation and model
  preparation. The harness checks DRA allocation, injected launcher, libraries
  and control sockets, then runs coordinator `--inspect` through the owned
  source's namespaces. Any new kernel Xid since source creation keeps the gate
  closed. The preexisting cp-0124 Xid 94 condition is retained as baseline.
- Capture success requires a ready PodSnapshot. Restore qualification requires
  a distinct Pod UID, `nvidia.com/Restored=True`, the exact workload image,
  two allocated GPUs and a new HTTP-triggered `READY` response after restore.

This isolates native Snapshot with the upstream preparation sequence. It does
not by itself qualify the existing Dynamo DGD's older lifecycle integration,
cross-node restore, vision/video restoration or workshop performance targets.
The restore uses the same node immediately after publication; host caches are
not dropped. Any restore timing is an observed warm-path measurement, not a
cold-storage or local-NVMe benchmark.

```bash
UPGRADE=results/20261022-snapshot-cuinterpose-upgrade
RUN=results/REPLACE-WITH-A-FRESH-RUN
# The approved prepare, storage probes and apply steps have already completed:
# .local/venv/bin/python scripts/snapshot_multigpu_upgrade.py prepare --run "$UPGRADE"
# .local/venv/bin/python scripts/prepare_snapshot_artifact_dir.py --review "$UPGRADE"
# .local/venv/bin/python scripts/prepare_snapshot_artifact_dir.py --review "$UPGRADE" --subpath
# .local/venv/bin/python scripts/snapshot_multigpu_upgrade.py apply --run "$UPGRADE"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py prepare --keepalive --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py deploy --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py wait-prepared --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py inspect --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py capture --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py wait-capture --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py finish-source --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py restore --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py verify --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py resources --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py measure --run "$RUN"
.local/venv/bin/python scripts/snapshot_cuinterpose_tests.py cleanup --run "$RUN"
```

For a new attempt, choose a fresh `--run` directory. The app ConfigMap and model
lock are immutable within a run. `prepare --eager` creates a separate eager
variant. `progress` and `snapshot_multigpu_upgrade.py status` save bounded logs.
Cleanup deletes only the owned source/restore workloads and capture Job,
retaining Snapshot diagnostics and artifacts.

## First CuInterpose attempt

Source Pod UID `7834f358-3222-4cc5-8be2-54c069cdc008` used the **same physical
`gpu-1` / `gpu-3` pair** as the earlier failed native captures.

- At `17:14:59Z`, pre-capture inference returned `READY`; direct vLLM pause and
  KV-cache release completed in **0.04545s**. This excludes the agent's subsequent
  CuInterpose preparation, CUDA checkpointing and CRIU work.
- At `17:17:22Z`, read-only coordinator inspection passed for live namespace
  PIDs `1`, `1271`, `1627`, `2012`. Both libraries matched across the source,
  DRA allocated two GPUs, and no kernel Xids occurred after source creation.
  The harness was corrected to exclude the Pod's pause container and 81 stale
  sockets left by exited startup helpers; every live core participant still had
  to expose a responsive socket.
- Both actual TP worker CUDA checkpoints **completed**, in **38.143s** and
  **38.537s**. The main/engine-core CUDA checkpoints also succeeded. This is the
  first full-model attempt to pass the former CUDA stall.
- CRIU **completed successfully in 56.763s** at `17:19:56Z`, terminating the
  source as expected. Roughly 99 GB of files were staged in PageBroker RAM.
- At `17:24:56Z`, the operator marked PodSnapshot/SnapshotJob failed because
  the source had been terminal for five minutes while publication was pending.
  Source code pins this backstop as `sourcePodTerminalGrace = 5 * time.Minute`
  in `operator/internal/controller/podsnapshot_reconciler.go`; it is not a Helm
  setting. This is separate from the prior CUDA failure.
- PageBroker continued copying the staged checkpoint. Its observed write count
  advanced from about 48 GB to 96 GB. A captured kernel stack identifies
  `nfs4_file_flush` / `nfs_wb_all` / `folio_wait_writeback` during `close`, rather
  than a CUDA call. The EFS partial publication remained under the content-owned
  artifact root. At **17:39:50Z** the content reported `Ready=True`, but the
  parent PodSnapshot remained sticky `Failed=True` / `Ready=False`; this does
  not count as a successful SnapshotJob lifecycle or restore test. The artifact
  contains **2,021 files / 98,891,793,962 logical bytes**. Agent timing: total
  **22m10.26s**, CUDA **77.40s**, CRIU **56.76s**, publication/switch
  **19m53.93s**. The new measurement script records parent and content
  readiness separately.
- At `17:31:53Z`, the owned failed source Job/Pod were removed and zero active
  Pods/claims verified. Snapshot objects and publication diagnostics were kept.

### CPU keepalive retry

Fresh run: `results/20261022-snapshot-cuinterpose-tp2-keepalive/`, namespace
`dynamo-ft-20261022t173026z`. This retains the frozen model, image, TP size,
CuInterpose and EFS store. The source gains one tiny CPU-only companion
container with `NVIDIA_VISIBLE_DEVICES=void`. Only `main` is captured. After
CRIU terminates `main`, the companion keeps the Pod nonterminal while publication
finishes. After the harness verifies the Ready artifact, `finish-source` sends
TERM to the owned companion shell, whose trap exits 0. SnapshotJob then verifies
helper completion and deletes the owned source Job normally.
The restore Pod has only the captured main container.

This is a test-local workaround for the terminal-Pod grace, not a controller
fix or production recommendation. The source Job deadline is two hours to bound
the whole run. Use `prepare --keepalive --run <fresh-directory>` to reproduce.
The retry's cache verification, `READY` generation, 0.04559s pause/KV release
and four-participant inspection passed. Source UID
`8e37e151-5892-4d7a-99ed-f8be5e027057`; capture gate opened at
**17:44:08Z**. Both CUDA worker checkpoints completed again (37.627s /
38.748s), followed by CRIU in **57.218s** at **17:46:25Z**. At **17:51:46Z**,
more than five minutes after main exited, the source Pod was still `Running`
with only `capture-keepalive` running and `Failed=False` on SnapshotJob. This
verifies the grace workaround. PodSnapshot became **Ready at 18:03:21Z**.
The companion then exited cleanly after the explicit readiness-gated signal,
and SnapshotJob reported **Captured=True / Completed=True / Failed=False at
18:05:06Z**. A separate restore Pod was created at **18:05:18Z**.

At **18:11:00Z**, `nvidia.com/Restored=True`; the app woke its KV cache,
resumed generation and returned `READY` at **18:11:01Z**. A separate HTTP request
at **18:11:08Z** generated `READY` again, with the exact frozen model/revision,
TP=2 and unchanged image digest. Restored Pod UID:
`a78c43d4-e63c-4347-8d1d-453d34bbbc7f`; actual DRA allocation retained the same
physical GPU pair. No new kernel Xids or changed node conditions through the
post-inference audit at **18:12:08Z**; preexisting Xid 94 is not cleared.

| Passing run measurement | Observed value |
| --- | --- |
| Artifact | 2,021 files / **98,903,175,597 logical bytes** (98.90 GB) |
| Agent capture total | **19m11.52s** |
| CUDA checkpoint aggregate | 77.08s |
| CRIU dump | 57.22s |
| Publication/switch | **16m55.08s** |
| Agent restore total | **5m40.45s** |
| CRIU restore | **5m16.53s** |
| CUDA restore aggregate | 17.49s |
| Restored application first inference | About 0.23s after agent completion |

These timings exclude cold model startup and manual time between capture and
restore. The restored Pod was Ready at 18:11:02Z, about 5m44s after Pod creation.
The first metadata measurement during restore hit its 45s scan limit; repeating
it after successful inference completed and produced the values above. Raw
receipts, phases, claims and inference response are retained in the run directory.

Publication consumed 88% of capture; CRIU consumed 93% of agent restore time.
Artifact storage is the next performance investigation. CRIU includes process
memory reconstruction as well as I/O; this test does not isolate how much of
its restore time is EFS versus reconstruction. During this qualification run, no local NVMe, RAM-store switch, disk formatting
or host-cache flush was performed. The subsequent RAM artifact control below
measures the restore storage penalty separately.
A supported controller fix or an explicit helper lifecycle is also needed for
slow publication; the unmodified single-container EFS path failed this test.


## Cleanup and final inventory

The passing run's owned SnapshotJob and restore Pod were deleted; idle checks
passed at **18:13:12Z**, with zero active run Pods and zero remaining claims.
Its Ready PodSnapshot, content and artifact are retained. The first failed
run's source was already removed; its sticky Failed parent and late Ready
content are retained as diagnostic evidence.

Final read-only inventory finished at **18:14:06Z**:
`results/20261022-snapshot-cuinterpose-final/`. All three nodes are Ready,
all boot IDs and condition statuses match the pre-upgrade inventory, and each
still advertises 32 EFA resources. There are **no active feature-test Pods and
zero ResourceClaims cluster-wide**. Platform Helm revision 4 is deployed;
Snapshot agent, PageBroker and operator are Ready with zero restarts.
Driver remains 610.57.04. No GPU reset, reboot or disk formatting was performed.

Local validation passed: seven existing Snapshot launch/bootstrap guard tests,
three CuInterpose allocation/lifecycle guard tests, Python compilation and
`git diff --check`. These checks complement the live model capture/restore
proof; they do not qualify Dynamo DGD integration or other model features on
this new Snapshot build.


## Subsequent same-artifact RAM control

The [controlled EFS/RAM/EFS comparison](2026-10-22-snapshot-tp2-storage-comparison.md)
now isolates the restore storage cost: **337.01 / 42.05 / 335.85s**, all with
fresh `READY` inference and the same physical GPU pair, exact artifact and
unchanged model/image/build. Mean CRIU time fell from **316.32s to 25.63s**;
CUDA restoration remained around 15-16s. Pre-staged RAM recovered **294.38s**
(**87.5%**) of agent restore time, an **8.00x** speedup.

Copying the artifact to RAM cost **334s**, plus **139s** verification; those
costs are separate from restore. The cache must be populated before the startup
critical path and reused; per-restore copying would repay the EFS delay. This
was a temporary read-only artifact view in the agent's private namespace; it
was removed after testing. No shared store change or RAM publication test was
performed. The capture publication timing remains the original EFS result.
