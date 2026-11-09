# Reader reconstruction candidate

Prepared offline November 5, 2026. **The lm_head layout helper passes ten CPU
guard tests; no reader GPU run, parked standby, promotion or replenishment is
qualified.** This packet adds new files only. It does not modify the active a5
writer, presenter, Humming hook or their dependencies. Their recorded source
hashes were checked unchanged after preparation.

## What the a1 failure establishes

The preserved reader fails at `language_model.lm_head.weight`: its meta shape
is `(65536,4096)` while the committed writer shape is `(4096,65536)`, both
`float8_e4m3fn`. Before that, the older reader failed on scalar-vs-singleton
`input_scale`; a1's narrow scale adaptation passed that earlier check.

The installed `modelopt.py` explains both effects. `KFp8StaticTensor.process`
transposes the weight, restores `input_dim=0`/`output_dim=1`, reduces the weight
scale and input scale to scalars, and relies on value-dependent operations that
cannot finish on meta tensors. `_create_meta_model` catches a failure from the
entire postprocess pass and returns the partially processed model. Therefore
later layers need runtime reconstruction as well as parameter shape handling.

The expected transpose of the original contiguous `[out,in]` weight is a
non-contiguous `[in,out]` view with stride `(1,4096)`. This exact stride is a
source-derived expectation, **not yet a live reader metadata observation**.
If the actual committed stride differs, this candidate refuses adaptation;
inspect that evidence before preparing a new layout contract.

## Narrow helper ready for review

`scripts/workshop_shadow_reader.py` supplies `prepare_known_meta_parameter`
and a source transformation for the original materializer. The original GMS
shape/dtype conditional remains unchanged. The helper adjusts only the
unmaterialized skeleton of the pinned TP2 `language_model.lm_head`, when all
of these source-derived contracts match:

- Exact `ParallelLMHead` and `ModelOptLinearMethod` classes.
- Exact `KFp8StaticTensor` weight and activation schemes and their shared
  `kFp8StaticTensorSym` keys.
- The pinned per-partition input/output dimensions.
- FP8 weight dtype, raw contiguous layout, final transposed shape/stride,
  and the raw input/output dimension attributes.
- Only the two known FP32 scale names, with `(1,)` to `()` and exactly one
  element, can receive scalar skeletons.

It never transposes, reshapes, copies or writes the imported GPU tensor.
Unknown parameters, methods, shapes, strides, dtypes and non-meta parameters
fall through to the original guard. This replaces the need for a general
singleton-scale exception at this one layer. It does not relax the rest of
the model.

The ten guard tests cover valid meta reconstruction, both scale names,
unchanged imported tensor, non-meta refusal, unknown method/key/layer/name,
dtype/shape/stride/device refusal and the unchanged original guard.

```bash
.local/venv/bin/python -m unittest discover -s tests -p 'test_workshop_shadow_reader.py' -v
```

These tests use tensor doubles because local PyTorch is absent. Real-image
CPU/meta validation and GPU materialization are separate pending gates.

The frozen offline packet is
`results/overnight-shadow-super-vl-20261105-reader-plan-a1/reader-plan.json`.
It records the original materializer hash, transformed module/helper hashes,
pending gates and `launchable=false`. It deliberately contains no executable
DGD while runtime reconstruction remains incomplete.

## Why a full Shadow recipe is not yet ready to launch

Humming's kernel objects are Python runtime state, not just named tensors.
The installed sources show these additional dependencies:

| Component | Runtime state needed after materialization |
| --- | --- |
| Humming NVFP4 linear | `kernel.layer_config`, `kernel.compute_config`, private `kernel.locks`; layer `weight_schema` and final parameter names/layout |
| Humming NVFP4 MoE | Layer `weight_schemas`, `input_schemas`, `humming_configs`; rebuilt `moe_quant_config`, modular `moe_kernel`, fused-expert configuration and private locks |
| FP8 lm_head | The actual selected FP8 kernel and any non-tensor initialization it requires; final dimension attributes must be correct |

The reader's global meta failure can leave all of those absent. Calling the
ordinary postprocess pass on materialized shared weights would re-run
transforms against read-only, already-final weights. That is unsafe and is
not proposed here. Likewise, simply adopting every committed shape cannot
establish that a kernel interprets those bytes correctly.

Upstream draft #12168 rebuilds a narrower set of NVFP4 MoE backends and
explicitly does not validate Humming. Removing its backend guard or merely
adding `HUMMING` to the allowlist is not a supported solution.

Two options for a new experimental integration are worth reviewing:

1. Preserve a versioned writer-generated manifest for final parameter
   layouts and the restricted, serializable Humming runtime descriptors.
   Rebuild reader runtime objects from those descriptors, then check their
   tensor references against the actual imported parameters. This requires
   a reviewed serialization contract; do not pickle the whole model.
2. Reproduce each layer's transformation on disposable private synthetic
   weights, derive the final tensor contract and descriptors, and compare
   all names/shapes/dtypes/strides against writer metadata before binding
   real shared tensors. This must explicitly refresh tensor-holding aliases
   in the rebuilt MoE quant configuration and bound temporary memory.
   It is a larger experiment, not an implementation or qualified result.

## Next full-candidate composition and qualification

After writer a5 passes actual coding and no-new-Xid checks, prepare a fresh
profile and namespace. Copy the frozen writer overlay bytes (including both
linear and MoE lock isolation) into that candidate; do not edit a5 inputs.
Retain the pinned request-memory shim and bounded fixed KV setting for this
experiment. Add the reviewed reader materializer/runtime reconstruction,
freeze every source and input hash, and identify this as a composition test.

The order of evidence gates should be:

1. Actual-image source/CPU/meta validation and client/server admission.
2. Exact-pair CUDA arithmetic and fresh node/GPU-health baseline.
3. One writer plus one reader imports unchanged committed layouts; all
   reader runtime descriptors and writable workspaces are complete and private.
4. Correct active coding responses and a genuinely parked standby on the
   same shared GPU pair, with stable Pod/container identities and no new Xids.
5. One guarded, UID/PID-verified active EngineCore fault; observe promoted
   identity, unchanged GMS commitment, correct fresh coding responses and
   standby replenishment. Do not conflate this with in-flight continuation.
6. Final GPU-health comparison, scoped cleanup and actual main-panel capture.

The existing presenter/fault guards remain the basis for that last stage, but
its original `prepare` path creates a different two-file overlay and must not
silently replace the new composed profile. A separate entrypoint or explicitly
frozen subclass is required. A successful writer-only experiment is not proof
that these reader, promotion or presenter gates passed.

## Potential upstream work

- GMS needs a contract for final transformed layouts plus the non-tensor
  runtime descriptors required to interpret them; shape compatibility alone
  cannot supply it.
- Meta postprocess failures should identify the precise module/backend and
  expose incomplete reconstruction clearly, rather than only DEBUG-logging
  a global failure and returning a partial model.
- A regression should compare writer/reader parameter layout, runtime tensor
  aliases and numerical outputs under the actual ModelOpt/Humming backend.
  Greedy success on one high-confidence prompt is insufficient evidence of
  numerical equivalence.

All of this remains experimental workshop/runtime integration. None of the
offline work establishes production readiness for Super VL Shadow recovery.

## Subsequent concrete descriptor prototype

The writer-only a5 experiment has now passed. An independent offline audit
verified and preserved its three correct coding streams, 240 actual workspace
rebinding rows (80 linear and 40 MoE per TP rank), unchanged committed GMS
states/events and the final no-new-Xid/boot/driver/time-ordering checks.
All frozen a5 inputs and critical sources still matched their recorded hashes.
The immutable audit copy is
`results/overnight-shadow-super-vl-20261105-reader-evidence-a1/verification.json`.
It includes 98 source files from the actual pinned image. Three additional
GMS tensor/manager and NVFP4 oracle files are independently hashed in
`extra-verification.json`. Root performed canonical writer cleanup separately.

`scripts/workshop_shadow_descriptors.py` now implements the descriptor approach
as a new, isolated prototype. Twenty-one offline tests pass, using tensor and
runtime doubles; no real-image codec, imported-weight, reader or promotion
qualification is claimed.

The code includes:

- A JSON-only codec for the exact installed `LayerConfig`,
  `HummingWeightSchema`, `HummingInputSchema`, Humming dtype and enum classes.
  It rejects tensors, arbitrary objects/classes, extra/missing dataclass fields
  and non-finite values. No pickle is used.
- Writer export of the complete supported ModelOpt inventory: 80 Humming
  NVFP4 linear helpers, 40 Humming NVFP4 MoE layers and all selected unpadded
  Cutlass FP8 layers. Actual a5 logs show FP8 projections beyond lm_head;
  therefore the earlier lm_head-only helper is insufficient for the model.
- Final parameter names, shapes, strides, dtypes, optional `None` parameters,
  dimensional attributes, allocation IDs and byte offsets. Complete tensor
  extents must fit inside one actual GMS allocation.
- Independent `GMSTensorSpec` metadata validation. The reader cannot derive
  its expected contract by simply trusting the descriptor itself.
- A manifest identity containing the fresh candidate, image digest, model
  revision, model-config hash, source-manifest hash, actual TP rank and TP size.
  Publication occurs atomically **after** GMS commit/reconnect/remap and records
  `get_memory_layout_hash()`. Readers require that same committed hash and
  parameter allocation identities. Stale files are never overwritten.
- Exact final meta skeleton construction before the unchanged stock GMS
  shape/dtype guard. The reader does not re-run ordinary weight postprocessing.
- Humming linear runtime reconstruction and private lock allocation. MoE
  quant configs are rebuilt from actual imported parameters and checked for
  correct tensor aliases before creating a new Humming expert object; no
  postprocess/repack hook runs against the shared weights. The source-reviewed
  lock checker verifies that reconstructed workspaces are outside GMS pools.
- Unpadded Cutlass FP8 runtime restoration, including its
  `logical_output_size`. Any remaining meta parameter/buffer is a hard failure.
- A source-anchored loader transformation that composes onto a **copy** of
  a5's frozen loader and compiles successfully. No a5 file was edited.

The tests exercise complete synthetic writer export, final meta preparation,
optional-parameter preservation, runtime reconstruction, rejection of foreign
MoE tensor aliases, class/field restrictions, metadata mismatches, stale
identity/layout rejection and bounded missing-file waits. They deliberately
provide no GPU numerical evidence.

### Exact minimal next candidate changes

A fresh **writer-only instrumented candidate** can reuse a5's frozen writer,
Humming lock helper, pinned shim and bounded two-GiB KV control. The changes
are confined to:

1. Add `workshop_descriptors.py` to its own immutable overlay and transform a
   new copy of a5 `model_loader.py` with `patch_descriptor_loader`.
2. Add a dedicated Pod-shared `emptyDir` and mount it in the worker template
   so operator-generated engines share the rank manifest files. Set
   `DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR` to that absolute mount path and
   `DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY` to the pinned JSON identity; the actual
   rank is obtained from vLLM, rather than supplied in the environment.
3. Keep the ordinary writer-only GMS topology first. Capture the actual final
   manifest, verify its image/model/config/source/TP/GMS contracts and repeat
   the a5 coding/no-new-Xid checks as a new composition experiment.

The code records currently unsupported ModelOpt runtime classes in
`unhandled_modules` and sets `reader_ready=false`; the reader refuses such a
manifest. A known additional source review is `ModelOptKVCacheMethod` and
attention's post-load initialization: it removes raw q/k/v/prob-scale
parameters and may initialize host float copies and attention implementation
state. Those effects must be reproduced explicitly or shown unnecessary in
the actual pinned runtime. The requested installed-source inspection is still
pending. Merely skipping the global meta postprocess is not sufficient.

Only after those contracts and actual-image CPU checks pass should the new
candidate enable operator Shadow mode, import the genuine parked reader and
proceed through the guarded fault/promotion/replenishment gates above. The
prototype's presence or passing doubles does not authorize claiming a complete
Super VL reader implementation.
