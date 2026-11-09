# Narrow Humming lock experiment

Current candidate: **a5, prepared offline November 5, 2026.** Eighteen hook
unit tests and six controller tests pass. Cluster CPU preflight, exact-pair
CUDA arithmetic, writer inference and final GPU-health checks are separate
gates. No writer or Shadow recovery qualification is claimed here.

Root is the sole live/network executor. The closed a1 and a4 evidence remains
unchanged. a4 covered linear locks only; CPU inspection found its missing MoE
owner path before any a4 GPU experiment ran.

## Concrete ownership contracts

The installed sources identify two mutable four KiB lock workspaces allocated
during the GMS weights-pool scope:

| Kind | Reviewed owner path | Exact owner class |
| --- | --- | --- |
| Linear | `layer.quant_method.kernel.locks` | `HummingNvFp4LinearKernel` |
| MoE | `layer.quant_method.moe_kernel.fused_experts.locks` | `HummingIndexedExperts`, `HummingGroupedExperts` or `BatchedHummingGroupedExperts` |

The MoE wrapper must be the pinned `FusedMoEKernel` with a
`FusedMoEKernelModularImpl`; its public `fused_experts` property must resolve
to that implementation's actual owner. Unknown Humming variants fail closed.
Both kinds must be found for this Super VL experiment. The hook does not walk
arbitrary Python helper objects or modify parameters.

The hook runs after leaving the weights pool and before registration, pruning
and commit. It validates every workspace before changing any binding, requires
a contiguous 1,024-element int32 CUDA tensor, and checks its complete extent
against the allocation. Clones must lie outside every registered GMS pool.
A misplaced active GMS-pool context, partial alias, ambiguous mapping or
overlapping private clone causes refusal.

Distinct owners sharing the same workspace receive the same private copy.
The helper retains strong owner references and preserves the old backing
through GMS's existing pending-publication list. Logs identify owner kind/path,
TP rank, old/new pointer, allocation ID, mapping base/size/offset and bytes.
The verifier requires actual linear and MoE rebinding on **both TP ranks**.

## Scope controls

This is an ordinary writer-only GMS deployment: **no reader, standby, failover,
scratch mode or intentional fault**. The reader's strict shape guard remains
unchanged; no `module.py` overlay is mounted. Its transposed FP8 reconstruction
and backend initialization need separate fixes and qualification.

The known source-hashed vLLM 0.31 `request_memory` signature/budget shim is
retained. A fixed **2 GiB KV allocation** isolates the workspace experiment from
the separate ordinary-GMS cache-sizing accounting concern. The profile still
executes warm-up. This does not qualify normal automatic KV sizing or capacity.

The CPU preflight checks the actual image's fixed-KV flag and hashes of the
original GMS loader/patch module plus the installed linear, MoE expert, modular
wrapper and allocator sources. Candidate inputs and critical implementation
sources are frozen; changes require a fresh candidate.

## a5 identity and root-executor commands

- Run: `results/overnight-shadow-super-vl-20261105-writer-a5`.
- Namespace: `dynamo-ft-r610-5fb30ea0-demo`.
- DGD: `ft-shadow-writer`.
- Overlay SHA-256:
  `79bbcefd977c069e3d942a1f3294fff46696387371ce3c756841d573fcd1377d`.
- Same pinned Super VL revision/image/TP2, text-only eager kernels.
- Assigned cp-0124 GPU4/GPU5 pair, verified through CUDA and actual DRA UUIDs.

After fresh cluster health and ownership clearance, root performs:

```bash
SHADOW_WRITER_RUN=results/overnight-shadow-super-vl-20261105-writer-a5
.local/venv/bin/python scripts/workshop_shadow_writer.py prepare --run "$SHADOW_WRITER_RUN"
.local/venv/bin/python scripts/workshop_shadow_writer.py probe --run "$SHADOW_WRITER_RUN"
```

Capture a fresh cp-0124 health JSON **after** that exact-pair CUDA smoke, then
use its actual pathname as `SHADOW_WRITER_HEALTH_BEFORE`:

```bash
.local/venv/bin/python scripts/workshop_shadow_writer.py deploy \
  --run "$SHADOW_WRITER_RUN" --health-before "$SHADOW_WRITER_HEALTH_BEFORE"
.local/venv/bin/python scripts/workshop_shadow_writer.py verify \
  --run "$SHADOW_WRITER_RUN" --timeout 1500
```

Verification checks physical UUIDs, image/container identities, both workspace
kinds and TP ranks, unchanged committed GMS weights and three correct coding
responses through the frontend. Fatal startup errors or timeout stop only the
UID-matched DGD while retaining evidence.

Capture health again after coding, then pass its actual pathname:

```bash
.local/venv/bin/python scripts/workshop_shadow_writer.py finalize \
  --run "$SHADOW_WRITER_RUN" --health-after "$SHADOW_WRITER_HEALTH_AFTER"
.local/venv/bin/python scripts/workshop_shadow_writer.py cleanup --run "$SHADOW_WRITER_RUN"
```

Finalization requires no new Xid occurrences and unchanged boot/driver-Pod
identity with correct time ordering. It compares message occurrence counts,
avoiding microsecond shifts in dmesg's reconstructed timestamps. Even a pass
qualifies only this writer configuration; reader and promotion gates follow.

## Preserved earlier evidence and upstream direction

a1 exposed the reader transpose mismatch and six new writer RO-write Xids.
Its source, identities, logs and GMS state remain preserved; cleanup passed.
a4 passed CPU/cache/source/admission checks and extra source extraction, then
cleanup passed without a CUDA probe or model deployment. Its incomplete
linear-only prototype and earlier offline drafts were not overwritten.

An upstream fix should address runtime tensor ownership. Humming could expose
mutable locks as non-persistent buffers on the owning layer and read those
buffers through the layer during execution. Registering a buffer while keeping
an old helper alias would still bypass GMS's rebound private copy. Dynamo
#9854's proposed structural helper/alias traversal is another relevant approach.
Both linear and MoE owners need regression coverage.
