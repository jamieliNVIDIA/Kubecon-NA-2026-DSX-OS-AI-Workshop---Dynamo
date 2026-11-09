# Reader-only Humming config repair

The first actual full-a1 reader acquired committed GMS read-only weights on
both TP ranks at 23:12:56 UTC, returned from the reader skeleton and unchanged
stock materializer, then failed at 23:13:06 UTC in our runtime reconstruction
callback. The generic `ModelOptNvFp4FusedMoE.get_fused_moe_quant_config` eagerly
reads `layer.w13_input_scale` before entering its Humming branch. That attribute
does not exist in the final seven-parameter Humming layout, producing the same
`AttributeError` on both ranks. This is an experimental reader callback gap;
it is not an upstream GMS runtime defect or a promotion/recovery result.

The independent first-failure packet preserves the original trace, observer
failure and all 24 unchanged critical hashes at
`results/overnight-shadow-super-vl-20261105-full-reader-failure-a1/verification.json`.
The earlier full wait failure at 23:12:49 UTC was a separate local kubectl TLS
tunnel error. Root restored the owned tunnel and `/readyz` immediately; there
is no VPN diagnosis. The later actual reader exception remains independent.
Root's fresh health audit and canonical cleanup passed with no new Xids or
condition changes and unchanged boot/driver. No fault was injected.

## Narrow source-backed change

Pinned `vllm/model_executor/layers/fused_moe/oracle/nvfp4.py:541-551` dispatches
the Humming branch directly to `get_humming_moe_quant_config`, passing the
layer's `swiglu_alpha`, `swiglu_beta` and `swiglu_limit`. That builder uses the
final Humming schemas/configs and optional `getattr(..., None)` scale fields.
The new reader callback follows that exact branch, retains all existing tensor
alias/role/allocation/workspace guards and does not invoke weight conversion,
post-load hooks or the generic checkpoint wrapper.

Separate `scripts/workshop_shadow_descriptors_v5.py` retains **exact v4
VERSION/data schema** and adds a distinct reader adapter revision:
`workshop-humming-reader-v5-native-config-builder`. Only the MoE config callback
inside `restore_reader_runtime` changes. `workshop_shadow_reader_delta.py`
requires the exact reviewed whole-source substitution and byte-identical
source for every other function, including writer export, codecs, tensor and
gradient guards, manifest validation, publication and reader skeleton. Local
tests also compare complete writer export dictionaries for exact equality.
The already accepted a6 writer/data basis can therefore be retained for a new
full candidate, with an explicit reader delta and new overlay hash. A separate
passing writer reload is unnecessary. Full-a1 and all old source snapshots
remain immutable.

## Actual-source CPU gate (passed)

Offline packet:
`results/workshop-shadow-reader-v5-cpu-packet-20261105-a1`.
It binds both accepted a6 rank-manifest hashes and all eighty actual rank/owner
roles. Their schemas, configurations and seven-parameter signatures reduce to
one identical runtime group. The packet's fixture and helper bytes are frozen
with an exact file manifest; no GPU/model work ran while creating it.

The CPU payload executes the exact v5 callback into the actual installed
Humming builder using decoded real schemas/configs and real Torch **meta**
parameters. It verifies `HummingMoEQuantConfig`, each weight/scale/config alias,
absent input-scale attributes, unchanged parameter identities/layouts/gradients
and default plus nondefault SwiGLU arguments. Weight transforms, postprocessing,
the generic wrapper and kernel construction are traps. It checks actual source
hashes and the oracle's exact dispatch arguments, with CUDA uninitialized before
and after. Root's exact pinned-image CPU run passed at **23:27:55 UTC**:
`results/workshop-shadow-reader-v5-cpu-live-20261105-a1/result.json`.
It produced actual `HummingMoEQuantConfig` objects for the one structural group
covering all eighty observed roles, preserved all aliases and parameter
metadata, retained absent raw input-scale attrs, and passed both SwiGLU cases
with CUDA uninitialized. The result, one-attempt intent and passed execution
receipt bind the helper, program, fixture packet, actual four source hashes and
runtime image. This does not establish GPU materialization, reader parking,
numerical behavior or promotion.

Root alone schedules the existing bounded `cpu_probe` with `cpu-program.py` and
four environment values: `DESCRIPTOR_SOURCE_B64`, `DESCRIPTOR_SOURCE_SHA256`
from packet `workshop_descriptors.py`, and `MOE_PACKET_B64`, `MOE_PACKET_SHA256`
from packet `fixtures.json`. The result must bind the exact helper, packet,
source hashes and image. Preserve a failed CPU attempt; do not overwrite it.

- Reader helper SHA256: `2f144fd5971aa07bc6008dfe7c6fd5c5b85c7d4d33d17c7fae9bb277280c9403`.
- CPU program SHA256: `daf61d6852053c481fc4539a6c10348ae836ad1d6327dd2f364ea8790aaf94ec`.
- Accepted writer helper SHA256 remains `ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e`.

Three new local tests pass: exact source/schema equivalence, identical complete
writer data, and forty reader callbacks using the Humming builder with exact
oracle arguments and no generic wrapper/input-scale placeholders. Eight
independent review tests also pass; the review is in
[SHADOW-READER-V5-REVIEW.md](SHADOW-READER-V5-REVIEW.md). Five full-freeze CPU
admission tests reject changed helper/packet/program/intent, wrong image/CUDA,
noncanonical coverage, missing/mutating/duplicate builder cases and incomplete
CPU proof before creating a candidate. Full composed tests remain passing.

## Fresh full-a2 task list before YAML

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete: unchanged pinned Super VL/image, eager/text-only vLLM TP2, operator GMS active/parked pair on cp-0124 GPU4/5, fixed 2 GiB KV cache.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete: accepted a6 writer DGD and reviewed operator failover composition; preserve all serving/model/GPU arguments and replace only the reviewed reader helper bytes.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete after actual-source CPU, independent reader-delta review, accepted a6 writer/root closeout and failed full-a1 cleanup: `configs/dgd/workshop-shadow-composed/overnight-shadow-super-vl-20261105-full-a2/deployment.yaml`.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — pending root's fresh full-a2 CPU/cache/source/admission preparation. No GPU work is part of this offline freeze.
5. Hand off to `deploy_dynamo` or `kubectl apply` — pending root's exact-pair CUDA smoke/fresh health/deploy/wait. No fault until one active plus parked reader, three correct complete coding streams and fresh pre-fault health pass.

The new full freeze requires exact root acceptance of the collected a6 writer
and absence of its local lease, then independently recomputes the CPU fixture
packet from those accepted rank manifests. It binds the source-reviewed reader
delta, actual CPU result/intent/check/program/packet and a new overlay hash.
The descriptor VERSION remains v4; the full profile stays
`super-vl-shadow-humming-runtime-descriptors-v4-routing-bias` with an explicit
`reader_adapter_revision` and `writer_overlay_sha256` for provenance. A new
namespace and full GPU intent keep it separate from closed full-a1.

## Frozen full-a2 and root handoff

- Run: `results/overnight-shadow-super-vl-20261105-full-a2`.
- Namespace: `dynamo-ft-r610-b06a9a1f-demo`; graph: `ft-shadow`.
- Full spec SHA256: `4bb21f9a4425e7edfd669375ff6a5b2c6f86b62378e0da6d5ce416d4e6fbbb60`.
- Composed controller SHA256: `2728d99a2ae947c17167cb1f1f6d6ba26003d23d4c9d1f20e84d192fbd1de90c`.
- New reader overlay SHA256: `3df2f3d0179ccaeaa48d24071559733cc5ae1f997251d7e2ef64125f14878cc8`.
- Accepted writer overlay remains `82ed5fbe40821a377dd6c8a5769c17b488cbc44bf8ada6fd4312345248e80247`, recorded separately as `writer_overlay_sha256`.

The freeze validated the complete accepted writer collection/root audit and
its exact cleanup/lease closeout, then the reviewed reader-only source
equivalence and actual CPU result. Offline `load` passed for all seventeen
inputs, sixteen accepted writer receipts, 134 source contracts and 27 critical
source snapshots. The six extra inputs are `reader-delta.json`,
`reader-cpu-result.json`, `reader-cpu-packet.json`, `reader-cpu-program.py`,
`reader-cpu-intent.json` and `reader-cpu-check.json`. All 27 critical sources
are held unchanged through canonical full-a2 cleanup. Old full-a1 is closed;
its source snapshots and failed evidence remain unchanged.

Root next performs `run-composed.sh prepare --run FULL` (CPU/cache/source plus
client/server admission), then `probe` on the assigned cp-0124 GPU4/5 pair.
Fresh health after that exact-pair CUDA smoke precedes `deploy --health-before
PATH`, followed by `wait --timeout 1500`. `prime` is only an alternative that
combines deploy and wait. No fault belongs in those preparation/readiness
phases. The durable adapter may run the later live phases using the same
frozen inputs; its own phase/health/control artifacts stay outside the Full run.

After actual active/parked readiness plus three correct complete streams,
root captures fresh pre-fault health. The existing two-stage capture interface
passes it as `--pre-fault-health` (child `--health-after`) and seals one actual
fault transcript as `pending_qualification`. Fresh post-fault health and full
`finalize --health-after PATH` precede capture `--finalize-pending`; no second
presenter launch or fault is allowed. The guided presenter and all fault guards
remain unchanged. No GPU reader, promotion or recovery result exists for a2 at
the freeze checkpoint.

## Full-a2 result: later native warmup failure, closed

The v5 restoration callback itself succeeded. Both reader ranks imported
36.79 GiB and validated 120 already-private Humming workspaces per rank with
zero extra copies; their model-loading lines report 7.419943 / 7.550250 seconds.
The reader then failed in a later **native** warmup metadata query at
`2026-11-05T23:51:04.556182239Z`: `_count_warmup_iterations` calls
`_fused_moe_grouped_gemm_may_use_deep_gemm`, which invokes ModelOpt's generic
`get_fused_moe_quant_config` before checking whether this is a DeepGEMM config.
The generic wrapper requires `layer.w13_input_scale`, still absent from the
reader's final parameter skeleton. This trace does not enter v5's direct
Humming builder callback. It establishes successful import/reconstruction up
to that point, not a parked reader, promotion, recovery or SLO result.

The 1,221-file immutable collection and first-fatal audit are in
`results/shadow-full-a2-remote-collected-a1` and
`results/shadow-full-a2-reader-failure-audit-a1/verification.json`. Root verified
canonical remote cleanup and both lease releases at 23:58:44 UTC; the local
CPU-prepared run state was never adopted. Closeout is
`results/workshop-shadow-full-a2-root-closeout-20261105-a1/complete.json`.
No intentional fault or presenter capture ran. All a2 artifacts and snapshots
remain preserved. A separate v6 reader-only optional-state repair is described
in [SHADOW-READER-V6.md](SHADOW-READER-V6.md); v4/v5 helpers remain unchanged.
