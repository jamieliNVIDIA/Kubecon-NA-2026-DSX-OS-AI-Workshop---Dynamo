# Dynamo feature functionality qualification

Current requested model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`,
**TP=2**. See [the model-specific retest](reports/2026-10-15-super-vl-tp2-retest.md)
and `configs/super-vl-tp2-lock.json`. The table below retains the earlier Lightning
TP1 qualification; its passes do not qualify the new model. The original default
was `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`. Do not substitute the
current model without a recorded architecture/feature incompatibility.

## Scope and evidence

Use existing cluster infrastructure. Create only owned test resources; do not change
node drivers/kernel settings, drain nodes, or modify shared queues. The user explicitly
approved the reviewed Dynamo operator/platform 1.4.2 → 1.5.1 upgrade and focused
retests, then separately approved the reviewed Snapshot 0.1.0 installation on
cp-0124, checkpoint enablement and TP1 capture/restore test. No other
infrastructure upgrades are authorized. See `reports/dynamo-upgrade.md` and
`reports/snapshot-install-review.md`.
Save commands, generated manifests, image digests, model revisions, logs and terminal
outcomes under `results/`. Never treat installed CRDs, Running pods, or an inference
response alone as proof of the relevant feature.

| Check | Required proof | State |
| --- | --- | --- |
| Inventory | Three Ready H100 nodes, resources, component versions | Collected |
| Runtime/EFA | GPU arithmetic, provider and NIXL plugin available in allocated pods | Passed; all three node pairs transferred correct VRAM payloads |
| Storage | Concurrent access from different nodes; record throughput separately | Passed for cross-node correctness |
| Aggregated serving | Correct model listed and nonempty inference response | Passed |
| KV routing | Actual events, multiple workers, cache reuse and routing evidence | Passed; two independent prefixes, six repeats |
| Disaggregation | Cross-node prefill/decode and completed KV payload transfers | Passed; 72,155,136 KV bytes, zero failed transfers |
| ModelExpress | Loaded weights via P2P; correct inference after loading | Passed; 761 tensors, 18.87 GB, no disk fallback |
| KVCR | Matched source/destination blocks and bytes, correct output | Passed; five blocks, 33,423,360 bytes, 2176 reused tokens |
| Engine sidecar | Native gRPC engine + sidecar, registration and inference | Passed for stock vLLM 0.28.0 and CPU sidecar 1.5.1 |
| Snapshot | Checkpoint ready, restored worker serves correct model | Passed: native TP1 same-node capture, distinct restored Pod, correct Nemotron inference; 37.36 GB artifact |
| Shadow Engine failover | Same-Pod standby promotion, unchanged GMS/weights, expected inference and restarted former active parked | Added; GPU DRA infrastructure gap |
| Grove/KAI | Owned graph/gang admitted and a reversible scale step | Passed; scale 1→2→1 |

## DGD workflow task list

Snapshot DGD task list:

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Adapt the pinned official Nemotron aggregated H100 DGD with native checkpoint fields.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
  - Client and server admission passed after approved checkpoint enablement.
- [x] Hand off to `deploy_dynamo` or `kubectl apply`
  - Approved single-node infrastructure installed; native TP1 test deployed.

Shadow Engine DGD task list (completed preparation):

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Pin the official Dynamo 1.5.1 `agg_failover.yaml` example.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
  - Client and server admission dry-runs passed; recovery remains unqualified.
- [ ] Hand off to `deploy_dynamo` or `kubectl apply`
  - Deployment is gated on GPU DRA inventory and one allocator per test node.

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - This workspace has no templates. Use the official Nemotron H100 recipes and preserve source provenance.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` and server admission validation
- [x] Deploy owned test resources with `kubectl apply`

The installed CRD and current upstream templates take precedence over obsolete example
flags/schema in the DGD skill. These are functionality tests, not performance benchmarks.

See `reports/2026-10-12-feature-status.md` for versions, evidence paths, limitations
and provisioning implications. All serving tests retained the preferred Nemotron
model; no alternate model was needed. The privileged single-node Snapshot
installation was separately reviewed and approved.


## Common runtime candidate DGD task list

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
  - Same pinned Nemotron model, TP1 H100, Kubernetes, preview runtime built from
    the already qualified KVCR compatibility set; current platform unchanged.
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Reuse the qualified per-feature DGDs and pinned official templates.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
  - Seven feature DGDs are saved under `configs/dgd/common-runtime/`.
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
  - Client/server admission checks and uniform image/version/env validation passed.
- [x] Hand off to `deploy_dynamo` or `kubectl apply`
  - Full bounded matrix passed; all owned GPU workloads were removed afterward.

Common-image promotion requires packaging/GPU/EFA, Nemotron serving/routing,
NIXL disaggregation, ModelExpress P2P, native engine/sidecar, KVCR peer reuse and
fresh native Snapshot capture/restore. Preserve current passing image locks
until the matrix passes. Shared allocator and platform changes remain outside
this candidate test. Jump-host SSH and Kubernetes access were restored after
the VPN endpoint change on October 13; all three nodes are Ready with no active
GPU workloads in the fresh read-only inventory. The common-image build uses
task-owned BuildKit storage on the builder's `/tmp` disk because its normal
Docker data filesystem is full. Qualification completed, including fresh native
TP1 Snapshot restore; see `configs/common-runtime-qualified.json`. Shadow/GMS
entrypoints are present, while live failover remains blocked by GPU DRA.
