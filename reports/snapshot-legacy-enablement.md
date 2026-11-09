# Legacy Dynamo 1.4.2 Snapshot enablement (superseded recommendation)

Retained for release-specific reference. Use `snapshot-enablement.md` for the
current recommendation following the dev guide supplied by the user.

Inspected October 12, 2026 (UTC receipts October 13). This is an enablement
proposal; no Snapshot agent, host profile or platform upgrade has been applied.

## Recommended first path

Use the Snapshot integration from the **installed Dynamo 1.4.2 release**, with
one aggregated vLLM worker, TP1, and the preferred Nemotron model. Pin the agent,
placeholder tooling and chart to that release. Keep model revision and backend
settings consistent between capture and restore.

A correction to the initial preflight wording: this integration uses the existing
Dynamo operator for orchestration, once checkpoint support is enabled. It does
not require an additional standalone Snapshot operator. The newer
`ai-dynamo/snapshot` chart and PodSnapshot API are a different implementation;
do not mix their image/workload contracts with the 1.4.2 DynamoCheckpoint flow.

## Already available

- x86_64 H100 nodes, driver 580.173.02, GPU Operator 26.7.0 and containerd 2.3.5.
- Existing Dynamo operator 1.4.2 and DynamoCheckpoint CRD.
- Working cross-node EFS CSI storage and the exact cached Nemotron model revision.
- A one-H100 serving configuration that generated the expected output.

The fresh read-only preflight found **no checkpoint block** in the existing
Dynamo operator's configuration, and **no snapshot-agent DaemonSet**. Installed
PodSnapshot CRDs do not make either checkpoint/restore flow operational.

## Changes needed

1. **Enable checkpoint orchestration in the existing platform release.** Set
   `dynamo-operator.checkpoint.enabled=true`, retaining existing Helm settings and
   the installed chart version. This changes the operator configuration and may
   roll its controller deployment. Confirm checkpoint storage names and mounts
   match the agent chart. No driver change is required for the first TP1 test.
2. **Create a dedicated artifact PVC against the existing EFS filesystem.** The
   cluster's default EBS class is RWO, and there is no RWX StorageClass. Use an
   owned static EFS Retain PV/PVC, as in the serving tests, with a distinct artifact
   directory. Configure Snapshot to reuse that claim rather than provision a
   default PVC. The claim must be in the workload/agent namespace for agentMount.
3. **Install the matching Snapshot 1.4.2 chart and privileged agent.** For the
   first test, scope RBAC to a dedicated test namespace and select one H100 node
   using `daemonset.nodeSelector`. The chart requires privileged hostPID,
   hostIPC and hostNetwork access, the container-runtime/host mounts, and deploys
   a kubelet seccomp profile that blocks io_uring for checkpointed workloads.
   These are infrastructure/host security changes and require explicit approval.
   The legacy chart has no separate Snapshot operator deployment.
4. **Build a placeholder image around the working H100 Nemotron runtime digest.**
   The release Dockerfile's `placeholder` target preserves the application's
   launch contract and adds CRIU, cuda-checkpoint, cuda-checkpoint-helper,
   nsrestore and related restore support. Use the release's CRIU pin
   `b47c692bb3a73ae45ee1c4ab215a8f6869d40efd`, rather than arbitrarily installing
   a distro CRIU package. The image needs to be available from a registry that
   these nodes can pull; no image has been built or published for this proposal.
5. **Run a capture/restore qualification.** Use a DynamoCheckpoint and the
   placeholder image, wait for Ready and a checkpoint ID, then create a new
   worker using checkpointRef. Require agent-confirmed restore, correct model
   registration and successful expected inference. Start on the same node, then
   try another compatible H100 node with the same driver and runtime image.
   A Running Pod or a completed capture Job is not sufficient evidence.

The matching legacy chart defaults to 2 CPU / 1 GiB requests and 4 CPU / 4 GiB
limits for the agent. Its default artifact claim is 1 TiB. Those are chart defaults,
not measured requirements for Nemotron. Start with a reduced KV allocation and
ample artifact capacity (e.g. 128–256 GiB initial budget, an estimate to validate),
then measure capture size, peak host RAM and EFS write/read time. EFS PV capacity
is not an enforced filesystem quota. CUDA checkpointing copies GPU allocations
to host memory, so leave host-memory headroom beyond the serving process's RSS.

Snapshot itself does not require EFA or multinode NVLink for this TP1 test.
Initial validation should avoid disaggregation, P2P loaders and extra live network
connections. The 1.4.2 guide identifies established TCP socket state as a restore
sensitivity. The AWS 7.0 kernel / containerd 2.3.5 combination still needs an actual
CRIU capture/restore test; the prerequisite check is not a compatibility proof.

## Multi-GPU boundary

The Dynamo 1.4.2 guide calls for driver **590 or newer** for multi-GPU snapshots;
our nodes use 580.173.02. It labels single-node vLLM multi-GPU support highly
experimental, and multinode support work in progress. Consequently a TP2 test
would need a separately approved driver change and additional validation.
The standalone Snapshot repository pinned in `configs/snapshot-source.json`
currently lists single-GPU only. Do not infer TP2 support across implementations.

## Sources and review artifacts

- [Dynamo 1.4.2 Snapshot guide](https://docs.nvidia.com/dynamo/v1.4.2/kubernetes/operations/cold-start-optimizations/dynamo-snapshot)
- Matching release source commit: `2ecbdfdf192c69c02c6d21e931d20d3b4a0bb64a`;
  SHA256 file receipts in `configs/snapshot-legacy-source.json`.
- Checked-in chart values, README and Dockerfile:
  `configs/upstream/dynamo-1.4.2/deploy/`.
- [CUDA checkpoint host-memory behavior](https://github.com/NVIDIA/cuda-checkpoint)
- The separate standalone vLLM example is validated on 0.27.1 and explicitly
  excludes 0.28; it is not a drop-in for the tested engine sidecar or the Nemotron
  H100 development image:
  [standalone vLLM guide](https://github.com/ai-dynamo/snapshot/blob/main/docs/guides/vllm.md).
