# GPU DRA and live Shadow Engine recovery — October 14, 2026

**GPU DRA is enabled and works. Shadow recovery passed with the small Qwen
control and a test-local compatibility overlay. Preferred Nemotron NVFP4
startup remains blocked by runtime/model integration errors.**

## What passed

- Both GPU allocation flags are enabled in DRA 0.5.0. `gpu.nvidia.com` exists,
  all three GPU plugins are Ready, and each node advertises eight H100 devices.
  No NVIDIA GPU device-plugin Pod competes for those devices. ComputeDomain
  support remains enabled alongside GPU allocation; it is not used by this test.
- A real `resource.k8s.io/v1` GPU claim was allocated on each of the three nodes.
  Two containers referencing that claim both saw exactly one identical GPU UUID
  and computed the correct CUDA arithmetic result. This tested one GPU per node;
  it was not a simultaneous 24-GPU allocation test.
- Dynamo operator 1.5.1, Grove and KAI scheduled the Shadow worker with the
  operator-generated shared claim. Active/standby engines and the GMS native
  sidecar consumed that same allocation.
- `Qwen/Qwen3-0.6B`, revision `c1899de289a04d12100db370d81485cdf75e47ca`,
  reached active + parked standby and returned `READY.` through the frontend.
  This is the model used in the [release Shadow example](https://github.com/ai-dynamo/dynamo/blob/v1.5.1/examples/backends/vllm/deploy/agg_failover.yaml).
- The verifier killed exactly the owned active `VLLM::EngineCore` PID 1000 in
  `engine-0`. `engine-1` promoted and returned `READY.` with a different worker
  identity. Fault-command-to-first-verified-response was **2.953 seconds**,
  including `kubectl exec` overhead. One request failed during the transition.
- The original Pod UID `c8bc9d86-0dba-445e-af99-b778161c5b20`, GMS and promoted
  engine survived. Exactly one successful promotion was recorded. The failed
  container restarted and became the new parked standby. GMS retained the same
  committed weight-layout hash and publication history; failed-engine KV
  allocations were reclaimed.

This is one TP1 process-failure control on cp-0124. It does not qualify failed
GPU/node recovery, in-flight request or KV continuity, throughput, repeated
swaps, TP2, or Nemotron recovery.

## What failed with preferred Nemotron

Both attempts retained model
`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
`bee7596271d1495f6992ae224aefde4410e816b8`.

1. The unmodified common image failed before loading weights: GMS's
   `patched_request_memory(init_snapshot, cache_config)` wrapper accepts two
   arguments, while vLLM 0.31 calls it with a third `external_weight_memory`
   argument. The exact error was `takes 2 positional arguments but 3 were given`.
2. A narrowly scoped overlay accepted that argument and let the writer load
   and publish 19.19 GiB of shared weights. The standby then failed with:

   ```text
   Shape/dtype mismatch for lm_head.weight:
   param=(131072, 1344)/torch.uint8,
   gms=(168, 262144)/torch.int32
   ```

   The writer also exited with a CUDA illegal-memory-access error during
   FlashInfer/autotune warm-up after scratch KV initialization. No recovery
   fault was injected into either Nemotron attempt.

The layout mismatch is consistent with raw NVFP4 parameter metadata versus
the writer's processed Marlin layout on H100. That is an interpretation of the
logged shapes, not a claim that every quantized model or future GMS version is
unsupported. It needs an actual GMS quantization-layout fix/qualification;
increasing GPU count or re-enabling a cluster allocator does not resolve the
recorded metadata mismatch.

## Exact software and overlay

All serving containers used the same pinned common image:

```text
nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d
```

It contains Dynamo 1.6.0 development code and
vLLM `0.31.1rc1.dev23+g43b4aaea3`. The image itself was not rebuilt or modified.
An immutable owned ConfigMap mounted the patched GMS module read-only into the
engine containers. The successful control therefore qualifies **image plus
overlay**, not the unmodified common image.

- Original module SHA-256: `a1bce1a996b85ff25d9541aeae80adb2735642748d6fd24c8510e85a5f96846b`.
- Overlay SHA-256: `8f75223bc5856a4cca206d416607d2807d985857b3d181938d9c1529c3d8f422`.
- Source and rationale: [compatibility overlay](../configs/patches/shadow-gms-vllm031/README.md).
- Twelve offline tests passed: eight fault/allocator guards and four direct
  compatibility-function tests.

The Qwen control used TP1, context 1024, four maximum sequences, batch budget
1024 and GPU memory utilization 0.25. Both cloned engines requested 4 CPU /
64 GiB host RAM with a 128 GiB limit; these conservative inherited requests are
not measured minimum requirements. The model's single weight file is
1,503,300,328 bytes. Its substitution was permitted by the concrete preferred-model
failure and recorded in a separate per-run model lock and namespace.

## Scripts, receipts and next steps

`scripts/shadow_live_tests.py` provides preparation, three-node claim smoke,
source capture, immutable overlay preparation, metrics-only startup wait,
diagnostics and cleanup. `scripts/shadow_failover_tests.py` provides DGD
admission/deploy and guarded recovery verification. Generated control/preferred
DGDs are under `configs/dgd/common-runtime/`. The generic model downloader now
also supports an unsharded safetensors model.

To rerun the justified control in a fresh run:

```sh
set -e
RUN=results/<fresh-shadow-control>
.local/venv/bin/python scripts/shadow_live_tests.py prepare-control --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py dry-run --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py deploy --run "$RUN"
.local/venv/bin/python scripts/shadow_live_tests.py wait --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py verify --run "$RUN"
.local/venv/bin/python scripts/shadow_live_tests.py cleanup --run "$RUN"
```

The control preparation requires this workspace's preserved preferred-model
failure evidence. On failure, save `inspect` output and run scoped cleanup;
the example's `set -e` intentionally leaves diagnosis available before cleanup.

Raw preferred-model evidence is in `results/20261014-shadow-enabled-check/`;
the control is in `results/20261014-shadow-qwen-control/`. Frozen evidence
manifests retain both failed startup and successful recovery receipts:

| Evidence | Frozen directory | Files |
| --- | --- | ---: |
| Preferred model, shared CUDA and final cleanup | `evidence-1792012803930416000/` | 483 |
| Qwen control, recovery and final cleanup | `evidence-1792012804412835000/` | 298 |
| `results/20261014-shadow-clean-inventory/` | `evidence-1792012804999996000/` | 30 |

Every archive includes a SHA-256 manifest. Final inventory at 21:19:17 UTC
confirmed three Ready nodes, zero active owned test Pods and zero ResourceClaims.
Both test namespaces' normal-termination/claim-GC checks passed. The earlier
`shadow-final-inventory` was captured during normal Pod termination; it is not
the clean final inventory. Model caches and static Retain PVCs were retained.

The legacy `nvidia.com/gpu` allocatable count is now zero on every node; GPU DRA
inventory comes from ResourceSlices. Ordinary demo manifests requesting only
that old scalar resource still need migration to claims before their retests.

For a near-term Shadow demo, use the pinned Qwen control with the explicit
overlay. To return to one self-contained common image, include the compatibility
fix in a new pinned build and rerun the control. Nemotron needs its separate
quantized-weight import and warm-up issues resolved before advertising support.
The other October 13 feature results predate the allocator transition and have
not all been rerun with GPU claims.
