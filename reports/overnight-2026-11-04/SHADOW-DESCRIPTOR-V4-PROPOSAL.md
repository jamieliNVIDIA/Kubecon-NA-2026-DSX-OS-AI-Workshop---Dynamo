# Preserve Nemotron inference routing-correction metadata

The actual v3 diagnostic identified an overly strict assumption in our
experimental exporter: forty `RoutedExperts.e_score_correction_bias` parameters
per TP rank legitimately have `requires_grad=True`. The qualified original
writer runs these parameters successfully. This is not an upstream GMS runtime
defect, and it does not establish a cause for a3's unobserved failure.

The closed attempt is
`results/overnight-shadow-super-vl-20261105-descriptor-writer-a5`.
The immutable independent reconstruction, complete raw-log snapshots and every
exact parameter name are in
`results/overnight-shadow-super-vl-20261105-descriptor-inventory-a1/analysis.json`.
Both inventories are complete and agree with their flushed summaries and fresh
generation pair: 2,078 slots, 1,621 CUDA parameters, 457 None slots, 360 aliases.
All forty candidate-exporter issues are the same correction role: plain
`torch.nn.Parameter`, fp32, shape `[512]`, stride `[1]`, true gradient flag and
empty layout attributes. All forty owner names have actual Humming MoE
lock-rebinding proof on each rank. There is no unsupported dtype, shape/stride,
empty extent, None or Fraction layout field in any row. The other 289 grad-true
slots per rank are outside the exporter's selected quantization owners.

## Source basis and meaning of the flag

| Actual pinned source | Evidence |
| --- | --- |
| `vllm/model_executor/models/nemotron_h.py:168` | Creates `nn.Parameter(torch.empty(config.n_routed_experts, dtype=torch.float32))`, retaining the constructor's default true flag. |
| Same source, line 244 | Passes the gate's correction parameter into `FusedMoEFactory`. |
| `vllm/model_executor/layers/fused_moe/routed_experts.py:150` | Assigns that same parameter to the actual RoutedExperts owner. |
| `gpu_memory_service/client/torch/module.py:211` | The unchanged stock materializer recreates a parameter with `requires_grad=param.requires_grad`; its shape/dtype guard remains unchanged. |
| `vllm/v1/worker/gpu_model_runner.py:4136`, `:5788` | Actual `execute_model` and `_dummy_run` use `@torch.inference_mode()`. |
| `vllm/v1/worker/gpu_worker.py:1264` | Actual `execute_model` also uses `@torch.inference_mode()`. |

The gradient flag alone does not imply that inference builds an autograd graph.
The source-backed fix preserves legitimate parameter metadata instead of
changing the writer model. These sources come from the exact pinned runtime
image; the additional worker source receipt is
`results/workshop-shadow-inference-sources-20261105-a1/manifest.json`.
Its CPU-only source read initialized no CUDA context. New freeze binds its
hashes, the actual RoutedExperts source, complete inventory/log hashes,
diagnostic cleanup and no-new-Xid audit. Existing model and GMS source hashes
must agree with the qualified original writer's source contracts.

## Narrow v4 implementation

Separate `scripts/workshop_shadow_descriptors_v4.py` preserves the true bit
only for the exact forty observed model owners, the exact correction attribute,
actual RoutedExperts/GateLinear/plain Parameter classes, approved Humming MoE
backend, 512 experts, fp32 `[512]` with stride `[1]` and no layout attributes.
The writer and initial reader skeleton must have the source's gate object
alias. The descriptor explicitly names that gate parameter. Independent GMS
contracts must confirm identical shape, stride, dtype, allocation and offset.
After stock materialization, gate and routed Parameters may be distinct Python
objects but must address the same GMS allocation and byte offset, with the same
true bit and exact role signature.

All other gradient, dtype, shape and layout contracts remain strict; there is
no E8M0 allowance. The meta reader Parameter receives the recorded boolean, and
the stock materializer preserves it. The exact forty-role inventory is required
before publication or reader mutation. All meta plans are checked before any
layer is rebound. The a5/v3 sources and all prior frozen attempts remain intact.

Independent review found and resolved Python's permissive numeric equality at
the new role boundary: `[512.0]`, `[True]` and byte offset `False` must not pass
as integer metadata. Role shape/stride and byte offsets now require exact
integer types, with finite/nonnegative contracts preserved.

Six implementation tests plus nine independently written review tests pass.
They cover complete writer export, the exact forty-role inventory, unrelated
gradient rejection, source-role/backend/class/signature checks, independent GMS
alias metadata, reader all-or-nothing preparation, full post-import runtime
reconstruction, distinct Python aliases sharing the same GMS allocation,
foreign pointers/gradients/types/attrs and noncanonical numeric metadata.

The separate `workshop_shadow_descriptor_cpu_v4.py` payload additionally compiles
the exact actual-source Nemotron creation and RoutedExperts assignment, then
uses real Torch meta Parameters for all forty roles. It runs the unchanged
actual-source GMS materializer against CPU fixture tensors, verifies both
true flags and shared storage, demonstrates inference-mode autograd suppression
and challenges the stock shape/dtype guard with a wrong shape. The existing
real Humming/Attention/meta/JSONL/rendezvous/no-CUDA checks are retained. This
CPU probe is still pending; its fixture class identities and fake GMS specs do
not constitute an actual GPU reader or recovery result.

The fresh frozen candidate is
`results/overnight-shadow-super-vl-20261105-descriptor-writer-a6`, namespace
`dynamo-ft-r610-031fb156-demo`, graph `ft-shadow-writer`.
Specification SHA256:
`237dc410c4283caf9405717745214a8b33dfdc7777bdebf5b78c993480e528f6`.
Overlay SHA256:
`82ed5fbe40821a377dd6c8a5769c17b488cbc44bf8ada6fd4312345248e80247`.
Reviewed v4 helper SHA256:
`ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e`.
Actual-image CPU payload SHA256:
`fc6e920d15d867b50abe8507b32ed26a7b419953677aabd5cbbf949dd04fff61`.
The inventory helper remains unchanged at
`2d6ef1664d7746edd922c9281dcb6d8a30fa2f91d7d0abfeeaf5114e950623ef`.
Offline load revalidated all inputs, source snapshots and 134 installed-source
contracts. All 162 focused Shadow tests and compilation passed. No live action
has run for a6 at this checkpoint. The independent v4 review is recorded in
[SHADOW-DESCRIPTORS-V4-REVIEW.md](SHADOW-DESCRIPTORS-V4-REVIEW.md).

## DGD task list before the fresh candidate

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete: same pinned Super VL revision/image, eager/text-only vLLM TP2, fixed 2 GiB KV cache, scoped Kubernetes GMS on cp-0124 GPU4/5.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete: reuse qualified original writer-a5 DGD/DeviceClass/overlays, themselves derived from the intro and upstream operator examples.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete after independent review: `configs/dgd/workshop-shadow-descriptor-writer/overnight-shadow-super-vl-20261105-descriptor-writer-a6/deployment.yaml`; v3 is closed and will not be resumed.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — pending root's source/cache/admission preparation and explicit actual-image descriptor CPU probe. 134 pinned installed-source contracts are expected.
5. Hand off to `deploy_dynamo` or `kubectl apply` — pending CPU/source checks, exact-pair CUDA arithmetic and fresh health. No reader/fault is enabled by this writer composition.

## Root sequence after fresh freeze

Use only the new candidate; do not apply these commands to closed a1-a5:

```bash
SHADOW_DESCRIPTOR_RUN=results/overnight-shadow-super-vl-20261105-descriptor-writer-a6
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py prepare --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py inspect-descriptors --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py inspect-wrappers --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py probe --run "$SHADOW_DESCRIPTOR_RUN"
```

The explicit CPU action handles frozen helper/inventory bytes and source hashes;
its one-attempt intent cannot be cleared/retried. Both `probe` and `deploy`
require that exact passed CPU result. Review all CPU/source evidence, capture
fresh node health after the GPU smoke, then use the actual health pathname:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py deploy --run "$SHADOW_DESCRIPTOR_RUN" --health-before "$SHADOW_DESCRIPTOR_HEALTH_BEFORE"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py verify --run "$SHADOW_DESCRIPTOR_RUN" --timeout 1500
```

Successful coding, actual stable two-rank manifest capture and fresh final
health are all required before writer qualification. The rank manifests may
still reveal unsupported runtime state; no reader basis is assumed. On a
passing writer, capture final health and then:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py finalize --run "$SHADOW_DESCRIPTOR_RUN" --health-after "$SHADOW_DESCRIPTOR_HEALTH_AFTER"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py cleanup --run "$SHADOW_DESCRIPTOR_RUN"
```

On failure, preserve actual unlimited/previous logs, final health and canonical
scoped cleanup. The full-reader controller remains unfrozen with its old v2
interface until an actual supported writer basis passes and that composition
is rebound/reviewed. This v4 writer experiment does not qualify promotion,
capacity recovery or request continuity.

## Actual a6 writer result and pacing finding

The durable writer supervisor completed all phases with exit 0 at
**22:45:04 UTC**. The immutable, transport-verified collection contains 626 files
at `results/shadow-writer-a6-remote-collected-a1/run`; the original local a6
state remains CPU-prepared and has not adopted remote state. Independent
read-only verification is recorded in
`results/shadow-writer-a6-independent-audit-a1/verification.json`.
It rechecks all collection bytes and 134 source contracts, three complete
correct coding streams, stable capture provenance, 240 actual Humming lock
rebounds, all forty true correction flags and gate aliases per rank, no new
Xids/same boot and driver, canonical cleanup and the source namespace's empty
live resource inventory. Both actual manifests report `reader_ready=true`, no
unhandled state and counts of 97 Cutlass FP8, 80 Humming linear, 40 Humming MoE
and 8 ModelOpt Attention modules. This is writer qualification only. Full
reader freeze remains gated on root's separate exact-byte acceptance and local
reservation closeout; no full reader candidate has been frozen.

An observed pacing issue is separate from model loading and descriptor
metadata: the backend registered at **22:43:46 UTC**, then the first actual
request observed at **22:43:56 UTC** triggered a late FlashInfer XQA JIT build
at **22:43:58 UTC**. The runtime explicitly warns that this can take several
minutes on first use.
The coding streams subsequently passed. Backend discovery/readiness therefore
does not establish a warm first-response path. Rehearsal should warm the actual
request shape before presenting latency/SLO comparisons, and should show this
first-request compilation as a separate startup/warmup phase. The actual
collected log spells the XQA module
`xqa_input_bf16_kv_cache_e4m3_output_bf16_page_size_64_head_dim_128_head_group_ratio_16_use_sliding_window_False_use_spec_dec_False_spec_q_seq_len_1`.
It also records a separate first-use
`selective_state_update_s_f16_i_bf16_w_bf16_a_f32_si_i32_d_64_ds_128_nt_1_cs_i32_na_i64_sm90`
JIT build at **22:44:18 UTC**, during the first stored qualifying coding stream.
That stream ran from 22:44:17.469 to 22:44:37.888 (20.4 seconds); the next two
complete streams took about 1.65 and 1.70 seconds. These are bounded smoke
request completion durations, not steady-load or SLO measurements. The
qualification profile and compilation cache were not changed while this
experiment ran.
