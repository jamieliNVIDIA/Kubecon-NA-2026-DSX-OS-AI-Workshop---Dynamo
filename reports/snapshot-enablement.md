# Snapshot enablement using the current dev guide

Reviewed October 12, 2026. The guide supplied by the user is the target workflow:
[Restore Workers with Dynamo Snapshot](https://docs.nvidia.com/dynamo/dev/kubernetes/model-deployment/model-loading/dynamo-snapshot-experimental).
The earlier recommendation targeted the installed Dynamo 1.4.2 integration;
that proposal is retained in `snapshot-legacy-enablement.md` for reference.
The user subsequently approved the reviewed single-node installation. Snapshot
0.1.0 is now installed alongside Dynamo 1.5.1, checkpoint support is enabled,
and the agent is restricted to cp-0124. The dedicated EFS artifact export and
kubelet seccomp profile are installed. See [the October 13 qualification
result](2026-10-13-snapshot-status.md) for actual capture/restore evidence.

The [installation review](snapshot-install-review.md) records the exact approved
images, resources, dry-runs and rollback boundaries. The earlier dev TRT-LLM
recipe mismatch below applies to that walkthrough; it did not prevent the
native Dynamo vLLM TP1 attempt with the preferred Nemotron model.

## Requirements and cluster gaps

| Requirement | Evidence and action |
| --- | --- |
| Full GPUs on one node, MIG disabled | Existing nodes have eight H100 80GB GPUs each. Start with one GPU; multi-GPU remains a separate qualification. |
| x86_64, containerd or CRI-O, GPU Operator 26.3+, driver 580+ | Last successful inventory: x86_64 Ubuntu 24.04.4, containerd 2.3.5, GPU Operator 26.7.0, driver 580.173.02. The real native TP1 CRIU capture/restore test passed on AWS kernel 7.0.0-1012-aws; broader configurations remain unqualified. |
| Dynamo checkpoint integration plus Snapshot operator and privileged agent | Platform was upgraded from 1.4.2 to 1.5.1 under explicit authorization. Checkpoint support is now enabled; the pinned Snapshot 0.1.0 operator and one-node agent are Ready. The current path needs both controllers; the old integration's orchestration contract is different. |
| Snapshot APIs | All three Snapshot APIs are installed at v1alpha1 with the pinned 0.1.0 dependency. Actual capture/restore passed; CRD presence alone was not the qualification criterion. |
| RWX artifact storage, separate writable model cache | Working EFS and a cached, pinned Nemotron model are available. There is no RWX StorageClass; the default EBS class is RWO. The approved installation created a dedicated static EFS Retain PV/PVC in the Snapshot agent's namespace and reuses it via `snapshot.storage.pvc.create=false` and `snapshot.storage.pvc.name`. Keep model-cache claims in the workload namespace. |
| Snapshot-aware runtime and entrypoint | Keep the preferred Nemotron model. The public Dynamo 1.5.1 / vLLM 0.28.0 runtime passed native TP1 capture, new-Pod restore and correct inference on H100. The new walkthrough's runtime is TensorRT-LLM, whose Nemotron NVFP4/H100 path is not established by our vLLM tests. |

The baseline cluster facts above come from the inventory with UTC receipts on
October 13. A later refresh initially failed because SSH to the jump host timed
out. After the user's network change, SSH authentication succeeded, the API
tunnel was restored, and the current preflight completed at
**2026-10-13 04:59:07 UTC**. It reconfirmed all three nodes' GPU counts, drivers,
and kernels, plus the missing Snapshot agent, Snapshot operator, SnapshotJob CRD,
and Dynamo checkpoint enablement. The connectivity blocker is resolved.

## The new installation and workload flow

The guide enables these platform values together:

```yaml
global:
  snapshot:
    install: true
dynamo-operator:
  checkpoint:
    enabled: true
snapshot:
  storage:
    pvc:
      create: false
      name: snapshot-artifacts
```

These values were applied under explicit approval. They require a
compatible platform chart/operator/runtime tuple and a pre-created artifact
claim in the platform namespace. The current guide's normal runtime entrypoint
handles the capture/restore lifecycle; the legacy custom placeholder-image
Dockerfile is not a blanket requirement for this workflow. The Snapshot agent
injects restore tooling. Any alternative runtime still must satisfy the
[workload contract](https://github.com/ai-dynamo/snapshot/blob/77fe2f40e4f14e3b3c866e607b266bffc7a3d864/docs/reference/workload-contract.md).

The DGD sets `experimental.checkpoint.enabled: true` and
`startupPolicy: WaitForCheckpoint`. Dynamo creates a SnapshotJob to initialize
and capture a worker; serving replicas then restore from its PodSnapshot.
Require `nvidia.com/Restored=True`, the expected `nvidia.com/restore-from`
annotation, and correct inference through the frontend. Artifact readiness
alone is not a pass. First restore on the capture node, then separately test
another H100 node with compatible hardware, driver, mounts, and runtime.

Installation changes include cluster RBAC/CRDs, privileged host access to the
runtime and GPU processes, and a kubelet seccomp profile that blocks io_uring.
The user explicitly authorized the reviewed single-node installation as an
exception to the earlier no-major-changes constraint. The saved review includes
rendered manifests and upgrade/rollback details. A second namespace does not isolate cluster-wide CRDs/operators;
do not install competing controllers. Initially limit the agent to one node.

## Version boundary for the dev TensorRT-LLM recipes

The guide says to use a matching published Dynamo version for the platform,
runtime image, and downloaded examples. Our saved source checks found:

- Dynamo **v1.5.1**, commit `2093662a4d4e5fd318732935213dde08dc7be818`, has
  the bundled Snapshot **0.1.0** dependency and `global.snapshot.install` flag.
  Both `qwen3-0.6b.yaml` and `glm-5.3.yaml` at the guide's release paths return
  **404**. Enabling the flags does not establish that the new recipes work on
  the released operator/runtime.
- Dynamo **main**, commit `736f3ca97d90468f3c5b1f32c870517693d006b7`, has both
  recipes. They are adapted from Snapshot [PR #456](https://github.com/ai-dynamo/snapshot/pull/456),
  which was open at inspection. Their Pod templates opt into
  `nvidia.com/cuda-shared-memory-support: enabled`.
- Snapshot **v0.1.0**, commit `69535c52124d3c5569c4e41e8fe840e98c513ae1`, and
  **main**, commit `77fe2f40e4f14e3b3c866e607b266bffc7a3d864`, still document
  single-GPU-only limitations. The PR describes earlier same-node multi-GPU
  recipe qualification with Snapshot/agent/PageBroker **0.2.0-rc.2**; it explicitly
  limits what those results cover. This is evidence of an experimental path,
  not proof that the default 0.1.0 dependency supplies the tested payload.

For the dev TensorRT-LLM or multi-GPU paths, the next software step is selecting
a complete compatible development tuple (Dynamo chart/operator/runtime, Snapshot operator/agent/PageBroker, and
recipe), pinning image digests, and rendering its manifests. The user has allowed
experimental software; this version boundary does not require changing models.
Do not assume a development recipe is compatible with a released image merely
because the chart accepts its values.

## Multi-GPU and driver boundary

**The dev guide does document multi-GPU Snapshot:** its GLM 5.3 NVFP4 example
uses eight B200s on one node, tensor plus expert parallelism, 1 TiB workload RAM,
2 TiB RWX model cache, and 4 TiB artifact storage. This is not an H100/Nemotron
TP2 recipe and is not a capacity requirement for our smaller model.

The shared-memory path uses CuInterpose support to preserve inter-process CUDA
state. Verify that the chosen build includes the matching injected libraries,
launcher/coordinator, and GPU/driver support, then qualify actual TP2 inference
after restore. The general 580+ prerequisite does not establish that every
multi-GPU path works on driver 580.173.02. The older 1.4.2 guide's 590+ rule is
specific to that integration and should not be presented as the verified driver
requirement for this new flow. No driver upgrade is proposed before identifying
the exact requirement or a concrete failure.

Keep capture and restore within one node for initial multi-GPU testing.
Restoring an artifact on another compatible node is distinct from a worker
whose ranks span multiple nodes. Neither EFA nor multinode NVLink is a stated
prerequisite for the single-node examples. Start without disaggregation or P2P
weight loading so their connections do not add unqualified capture state.

## Host memory and storage sizing

Do not transfer the old agent's resource limits to a newer build:

| Source/build | Infrastructure defaults, excluding the model worker |
| --- | --- |
| Published Snapshot v0.1.0 chart | Agent requests 2 CPU / 1 GiB, limits 4 CPU / 4 GiB; operator requests 50m CPU / 64 MiB. No PageBroker values in this chart. |
| Inspected Snapshot main chart | Agent + PageBroker request **10 CPU / 33 GiB per selected node**. PageBroker reserves 4 GiB per visible GPU by default: 32 GiB on an eight-GPU node even for a one-GPU workload. Agent memory limit 64 GiB, PageBroker limit 256 GiB, RAM staging cap 64 GiB. These are source defaults, not measured Nemotron requirements. |

For the newer build, budget the model worker, pinned GPU transfer rings, CRIU,
and CPU staging separately. The default agent limit equals the staging cap;
leave extra headroom or lower the cap to avoid an OOM near capacity. The source
storage guide recommends resetting chart defaults while preserving intentional
overrides when moving from a build without PageBroker; blindly using
`--reuse-values` can retain obsolete memory limits. Inspect rendered values.

The dev guide's small Qwen example starts with 1 TiB of artifact space, not a
measured minimum. For Nemotron, measure artifact bytes, peak RAM, and EFS read/
write time with a reduced KV allocation before setting a firm DSX budget.
Dynamo's TRT-LLM capture retains KV; the standalone GLM recipe releases it, so
its artifact sizes and timings are not interchangeable. EFS PV capacity does
not enforce a quota. EFS correctness and native TP1 capture/restore passed. The observed 37.36 GB
artifact took 16m17s to capture and 2m10s to restore; repeated/peak throughput
remains unqualified.

## Reproducible review

- `scripts/prepare_snapshot_current.py` resolves Git refs without requiring the
  GitHub API, saves source by immutable revision, and records hashes/404s in
  `configs/snapshot-current-source.json`.
- `scripts/snapshot_preflight.py --implementation current` checks both
  controllers, the agent, the Dynamo enablement flag, and the three current
  Snapshot CRDs. `--implementation legacy` preserves the old resource check.
  Presence does not prove version compatibility or a successful restore.
- Source files are in `configs/upstream/snapshot-current/`; historical sources
  and receipts remain intact.
