# Single-GPU Snapshot installation review — October 12, 2026

**Approved and installed October 13, 2026.** The user approved this exact
single-node change; the guarded installer completed at 06:54:09 UTC, with
Dynamo platform Helm revision 3 and all three controllers Ready. See
[the live qualification result](2026-10-13-snapshot-status.md). The sections
below preserve the pre-installation review and its checks.

**Original review:** A new live Nemotron test passed Dynamo's actual Snapshot preparation
and resume hooks on one H100 with the public 1.5.1 runtime. The pinned Snapshot
installation passed Helm and CRD server dry-runs. Actual CRIU capture/restore
remains untested.

## What is now verified

- `results/20261013-snapshot-next/`: the exact cached Nemotron model revision was
  reverified. It generated `READY`, completed the native
  `VllmEnginePauseController` pause/sleep/`checkpoint_prepare`, ran
  `checkpoint_restore`/wake/resume, passed engine health, and generated `READY`
  again. Dynamo/runtime 1.5.1, vLLM 0.28.0, unchanged model/image lock.
  Preparation took 28.06 seconds and in-process resume 1.60 seconds. These are
  hook timings, **not Snapshot capture/restore timings**.
- `results/20261013-snapshot-install-review/`: dedicated EFS artifact directory
  prepared; aligned 4 KiB `O_DIRECT` write/read/fsync correctness passed. This
  is filesystem compatibility evidence, not a throughput result.
  The exact EFS subdirectory export was then mounted through an owned static
  PV/PVC and passed the same direct-I/O check; the system-namespace claim remains
  a proposal.
- Helm server dry-run passed for the exact previously installed 1.5.1 chart,
  SHA-256 `b220d4ccc6b8c1dd25df80b471469380721432a32413ee58920d7fb0c0d38e41`.
  Only Snapshot images are added; no existing image changes or resources removed.
- All three proposed Snapshot CRDs passed server-side dry-run. Existing
  PodSnapshot/PodSnapshotContent objects: zero. `SnapshotJob` is currently absent.
- The Nemotron Snapshot DGD passed client validation. Server admission explicitly
  rejected it because the shared operator's checkpoint feature is disabled;
  this is the remaining gate, not a schema/version error. No DGD was created.

The first runtime attempt failed before Snapshot preparation because the harness
treated Transformers' token mapping as a token list. The corrected retry passed;
failed evidence is preserved in `evidence-1791872695982072000/`. The EFS helper's
initial non-root attempt hit existing directory permissions; the root UID used
by the proposed agent passed. No model substitution or host changes were needed.

## Exact proposed change

Use the Snapshot **0.1.0** dependency already bundled in the installed Dynamo
**1.5.1** chart, with operator/agent images pinned in
`configs/snapshot-0.1.0-images.json`:

| Component | Immutable index digest |
| --- | --- |
| Snapshot operator | `sha256:67aeb508f5b396c1615d3d782d10930cd74749333d739fa44c1643eea69b1722` |
| Snapshot agent | `sha256:973e93dfd2388f3bcba6099de8c4c806262690d23077fd1042b87391bcdd80ff` |

`configs/snapshot-install-values.yaml` enables the bundled chart and
`dynamo-operator.checkpoint.enabled`, restricts the agent to
`kubecon-nke-site-cp-0124`, and reuses a dedicated artifact PVC. Agent requests
2 CPU / 1 GiB, limits 4 CPU / 16 GiB; these are proposed bounds, not measured
Snapshot minimums. The existing operator, Grove, KAI, GPU/EFA drivers and
allocators keep their current images/settings.

The render adds 14 resources, including one operator Deployment, one restricted
agent DaemonSet, RBAC, service accounts and configuration. The CRD installer
updates PodSnapshot/PodSnapshotContent schemas and adds SnapshotJob; storage
version remains `v1alpha1`. The Dynamo operator rolls out its checkpoint setting.

The agent is privileged and uses host PID, IPC, network, runtime socket, cgroup
and process access. Its init container writes
`/var/lib/kubelet/seccomp/profiles/block-iouring.json` on the selected node.
That host/shared-controller change is why approval is needed under the user's
no-major-changes instruction.

`configs/snapshot-artifact-storage.yaml` proposes a static Retain PV and
`dynamo-system/snapshot-artifacts` PVC over the existing EFS filesystem. Export
only `/feature-tests/20261013-snapshot-install-review/snapshot-artifacts`, rather
than the filesystem root: Snapshot orphan cleanup must not see model-cache or
unrelated test data. The 256 GiB PV capacity is advisory; EFS does not impose a
PV quota. The model cache remains a separate workload claim.

## Why this path

The missing dev TensorRT-LLM release recipes do not prevent trying the released
native vLLM Snapshot API. The [Dynamo 1.5.1 integration](https://github.com/ai-dynamo/dynamo/blob/v1.5.1/components/src/dynamo/vllm/snapshot.py)
uses communicator checkpoint hooks, which our runtime test exercised. The
[standalone Snapshot vLLM recipe](https://github.com/ai-dynamo/snapshot/blob/69535c52124d3c5569c4e41e8fe840e98c513ae1/docs/guides/vllm.md)
is a different path and explicitly excludes vLLM 0.28; its warning should not
be treated as a blanket rejection of the tested Dynamo preparation path.

The `v0.2.0-rc.2` Git tag exists, but its checked chart metadata/limitations
still say 0.1.0/single GPU. A tag alone does not establish a compatible multi-GPU
payload. Keep this attempt TP1 with the matching bundled dependency; TP2 remains
a separate software and hardware qualification. No GPU DRA, EFA DRA, multinode
NVLink or driver upgrade is required to start this attempt.

## Apply and qualification sequence after approval

1. Recheck Helm revision **2**, no competing Snapshot controller, no preexisting
   Snapshot objects, unchanged reviewed manifests/chart/image hashes, and the
   owned EFS artifact directory. Refuse unowned PV/PVC name collisions.
2. Apply only the reviewed artifact PV/PVC and Helm upgrade. Wait for the
   artifact claim, Snapshot operator, restricted agent, CRD installer and Dynamo
   operator to become Ready. Recheck the three Snapshot APIs and checkpoint flag.
3. Reuse the verified model cache and run
   `snapshot_tests.py deploy --run results/20261013-snapshot-next`. The DGD uses
   `WaitForCheckpoint`, Retain artifacts, one GPU, normal native entrypoint,
   no disaggregation/GMS and the selected node's seccomp profile.
4. Run `snapshot_tests.py verify`: require artifact readiness, a serving worker
   distinct from the capture Pod, the matching restore annotation,
   `nvidia.com/Restored=True`, and correct Nemotron inference with worker identity.
   Save capture/restore logs, timings, artifact bytes and peak resources.
5. Stop the owned DGD using `snapshot_tests.py cleanup`. Retain its artifact for
   inspection. A cross-node restore and TP2 test follow only after TP1 passes.

The AWS kernel's real CRIU compatibility, GPU state capture, injected-tool
compatibility and new-Pod restoration remain unknown until step 4. The successful
preparation test must not be reported as a successful Snapshot restore.

Rollback: stop owned Snapshot workloads, disable checkpoint support, and roll
the platform back to its recorded Helm revision. CRD schemas, the host seccomp
file and Retain storage/artifacts persist; do not automatically delete/revert
them. Private Helm/CRD backups and rendered manifests are in the review run.

## Reusable commands

```bash
set -e
source scripts/kubecon-env.sh
.local/venv/bin/python scripts/prepare_snapshot_install.py --run results/20261013-snapshot-install-review
.local/venv/bin/python scripts/prepare_snapshot_artifact_dir.py --review results/20261013-snapshot-install-review
.local/venv/bin/python scripts/prepare_snapshot_artifact_dir.py --review results/20261013-snapshot-install-review --subpath
.local/venv/bin/python scripts/snapshot_runtime_tests.py --run results/20261013-snapshot-next
.local/venv/bin/python scripts/snapshot_tests.py dry-run --run results/20261013-snapshot-next
```

Preparation is not installation. No install/apply command is automatically run
by these review scripts.

After explicit approval, the guarded apply script is:

```bash
.local/venv/bin/python scripts/apply_snapshot_install.py \
  --review results/20261013-snapshot-install-review \
  --runtime-run results/20261013-snapshot-next --apply
```

It checks frozen file/chart hashes, current Helm values/revision, CRD drift,
controller ownership, existing Snapshot objects, owned storage names and both
storage checks before applying. Omitting `--apply` performs no installation.
