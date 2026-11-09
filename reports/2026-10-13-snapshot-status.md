# Native Dynamo Snapshot qualification — October 13, 2026

The user approved the [reviewed installation](snapshot-install-review.md).
Snapshot **0.1.0** is installed with Dynamo **1.5.1**, Helm revision **3**.
The Snapshot operator, single-node agent and Dynamo operator are Ready.
**Passed:** native TP1 CRIU capture, new-Pod restore and correct Nemotron
inference on one H100. The kernel/driver/runtime combination worked for this
configuration. Multi-GPU and cross-node restoration remain unqualified.

The [qualified common workload image](2026-10-13-common-runtime-progress.md)
also passed a fresh TP1 capture/new-Pod restore later the same day, using
Dynamo 1.6.0/vLLM 0.31.1 preview code with the same installed Snapshot 0.1.0
and Dynamo operator 1.5.1. Its artifact was 33.41 GiB, capture 16m29s and agent
restore 2m05s. The evidence below preserves the original public 1.5.1 run.

## Installed scope

- Agent restricted to `kubecon-nke-site-cp-0124`; privileged runtime/process
  access and the reviewed kubelet `profiles/block-iouring.json` seccomp file.
- `dynamo-operator.checkpoint.enabled=true`, bundled Snapshot chart enabled.
  PodSnapshot, PodSnapshotContent and SnapshotJob APIs registered at `v1alpha1`.
- Static RWX Retain PV `dynamo-workshop-snapshot-artifacts`, claim
  `dynamo-system/snapshot-artifacts`, over EFS export
  `fs-07acea4e27fbda414:/feature-tests/20261013-snapshot-install-review/snapshot-artifacts`.
  The 256 GiB PV request is advisory, not an EFS quota.
- Snapshot operator and agent pinned to the reviewed image digests in
  `configs/snapshot-0.1.0-images.json`. Existing Dynamo, Grove, KAI, GPU/EFA
  driver and allocator versions preserved. No GPU DRA enablement.

The Dynamo operator restarted once during installation because its checkpoint
gate became active before both Snapshot APIs were registered. It then recovered;
both Snapshot containers and their CRD/seccomp installers started successfully.
Private installation receipt: `results/20261013-snapshot-install-review/state.json`,
check `snapshot-infrastructure`, completed **06:54:09 UTC**.

## Exact workload and evidence

Run `results/20261013-snapshot-next`, namespace `dynamo-ft-20261013t061231z`,
native DGD `ft-snapshot`. The preferred Nemotron model and revision
`bee7596271d1495f6992ae224aefde4410e816b8` are unchanged. Runtime
`nvcr.io/nvidia/ai-dynamo/vllm-runtime@sha256:2b224a823d52a198ec0eeb0e3e4f5cf26cd8a7fc2e9812ee16204b6b1e974870`
contains Dynamo 1.5.1 and vLLM 0.28.0.

One H100, TP1, context 4096, maximum eight sequences, GPU utilization 0.65,
no speculative draft, native `python3 -m dynamo.vllm` entrypoint.
Worker requests 4 CPU / 64 GiB RAM and allows 128 GiB; shared memory 16 GiB.
Agent requests 2 CPU / 1 GiB RAM, limits 4 CPU / 16 GiB. These are configured
bounds, not measured minimums. Hardware: H100 80GB, driver 580.173.02,
containerd 2.3.5, Ubuntu 24.04.4, kernel `7.0.0-1012-aws`.

The DGD uses native Deployment components, `WaitForCheckpoint` and Retain.
Model cache is a separate workload PVC. No EFA resources, disaggregation or
ModelExpress are involved in this same-node attempt.

The first DGD attempt exposed a harness error: `activeDeadlineSeconds` is
forbidden in Deployment/ReplicaSet Pod templates. The script now removes that
field and relies on bounded verification plus explicit cleanup. The owned DGD
and its source jobs were stopped before retry; failed Snapshot metadata was
retained. This does not establish a model or Snapshot incompatibility.

Corrected attempt:

- Checkpoint `checkpoint-9c4905e7249ba9c2b2624e72dd880e23`.
- Source Pod UID `a825c243-09f6-4730-a21c-77ebecf77d85`.
- PodSnapshotContent UID `313bbaaf-35e8-4479-8844-3cdeb365ccb6`.
- Native preparation reached the sentinel at **07:03:45 UTC**.
- Agent started checkpoint operation at **07:03:46 UTC**.
- Capture completed at **07:20:03 UTC**; PodSnapshot `Ready=True`,
  SnapshotJob `Captured=True` and `Completed=True`, `Failed=False`.
- Finalized artifact: **37,356,007,511 logical bytes** (34.79 GiB), 1,055 files;
  allocated size 37,358,899,200 bytes. Capture agent total **976.704 seconds**:
  CRIU dump 972.439s, CUDA checkpoint 3.235s, overlay capture 0.884s.
  These are one observed EFS run's timings, not a throughput benchmark.
- New serving Pod `ft-snapshot-vllmsnapshotworker-b71eb504-5fb499d8bb-spljr`,
  UID `dc3536e9-503d-421a-888e-1606eb948f90`, was created after capture.
  Agent began external restore at **07:20:06 UTC**, including Pod IP remapping.
  `nvidia.com/Restored=True` at **07:22:17 UTC**, Pod Ready at **07:22:30 UTC**.
  Container restart count remained zero.
- Agent restore total **130.181 seconds**: CRIU restore 120.982s, CUDA restore
  8.961s. Pod creation to Restored condition **133 seconds**, to Pod Ready
  **146 seconds**. First verified inference completed **07:22:35 UTC**.
  Snapshot API creation to Ready **1,249 seconds**, including model initialization.
  These durations have different boundaries; the CUDA phase is not the whole
  worker startup time.
- Through the frontend, the restored model returned exactly `READY` with
  worker ID **1599404283913842**. Verification also required the artifact
  annotation, distinct source/restored Pod UIDs and Ready DGD. The strengthened
  verifier passed again at **07:24:11 UTC**, recording API-level timings.
- During capture, worker Pod cgroup `memory.peak` reached 59,283,009,536 bytes
  (55.21 GiB), with zero `oom`/`oom_kill` events. The agent Pod peak at that
  sample was 88,330,240 bytes (84.24 MiB). These are high-water observations,
  not minimum resource requests. Restored worker Pod peak observed by 07:23 UTC
  was 37,451,317,248 bytes (34.88 GiB); agent Pod peak 391,778,304 bytes
  (373.63 MiB), with zero OOM events. Kubernetes
  metrics API is absent; the diagnostic script reads only the owned Pod and
  selected agent cgroups for these measurements.

## Provisioning implications

The approved setup is sufficient for this native **single-GPU** Snapshot test:
Dynamo 1.5.1 plus its pinned Snapshot 0.1.0 dependency, checkpoint gate, privileged
node agent, containerd access, kubelet seccomp profile, and dedicated artifact
storage supporting the agent's direct I/O. Ordinary GPU device-plugin allocation
worked; GPU DRA and EFA were not needed for this test. Keep the model cache and
artifact export separate, and allow Retain artifacts plus temporary capture
staging when budgeting storage.

For the tested context/KV allocation, one artifact is about **34.8 GiB** and the
capture worker reached about **55.2 GiB** of host RAM. Keep the tested 64 GiB
worker request / 128 GiB limit until additional sizing runs establish a lower
bound. Keep the approved agent resource bounds rather than interpreting the
small observed agent peak as a universal minimum.

**EFS passed correctness but this run did not restore in seconds:** full restore
was about 130 seconds, dominated by the 121-second CRIU phase. The 16-minute
capture is a one-time artifact creation cost; the 9-second CUDA restore phase
cannot be used as the overall startup claim. Faster artifact storage and smaller
captured state are potential optimization work, requiring separate measurements.
No peak-throughput or repeated cold-start qualification was performed.

## Repeatable commands

```bash
set -e
source scripts/kubecon-env.sh
.local/venv/bin/python scripts/snapshot_tests.py dry-run --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_tests.py deploy --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_tests.py verify --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_diagnostics.py --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_measurements.py --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_tests.py cleanup --run results/20261013-snapshot-next
```

Verification requires a Ready artifact, a distinct serving worker with the
matching restore annotation and `nvidia.com/Restored=True`, and correct Nemotron
inference through the frontend. `reset` stops only this run's DGD and owned
capture jobs, retaining Snapshot artifacts for inspection.

Multi-GPU, cross-node restore, disaggregated Snapshot and performance sizing
remain separate qualifications. Shadow Engine failover remains blocked on its
independent GPU DRA requirement.

## Cleanup and frozen receipts

Owned DGD and workload Pods were removed; cleanup passed **07:28:07 UTC**.
The capture Job had already finished and been removed by Snapshot. The approved
operator, restricted agent, CRDs, host profile, storage and Retain artifact stay
installed. Final inventory `results/20261013-snapshot-clean-inventory` completed
**07:28:30 UTC**: all three nodes Ready, all three relevant controllers Ready,
zero active feature-test GPU Pods. The earlier inventory sampled asynchronous
Pod deletion; the cleanup helper now explicitly waits for workload Pod removal.

Saved `snapshot-resource-summary.json` reports the maximum observed cgroup
high-water values and the supporting sample filenames. Preparation, capture,
restore, inference, API objects, agent logs and command receipts are kept in
private `results/` runs; frozen evidence archives include SHA-256 manifests.
No model substitution, driver upgrade or allocator change was needed.

Frozen qualification/cleanup archive:
`results/20261013-snapshot-next/evidence-1791876594388298000/manifest.json`
(1,446 files). Frozen installation archive:
`results/20261013-snapshot-install-review/evidence-1791876435446665000/manifest.json`
(156 files). Private archives are intentionally excluded from Git.
