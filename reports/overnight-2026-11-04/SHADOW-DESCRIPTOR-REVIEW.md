# Shadow v2 runtime descriptor review

Read-only review of `scripts/workshop_shadow_descriptors_v2.py` and
`scripts/workshop_shadow_descriptor_writer.py`, the frozen
`results/overnight-shadow-super-vl-20261105-descriptor-writer-a1` candidate,
and installed sources retained with writer a5. No critical source edit, network
operation, GPU action, test run, commit or upstream submission was performed.

## Disposition

No new direct write to read-only weights or relaxation of the stock materializer
shape/dtype guard was found. The composition remains an experimental
**writer-only** candidate. The actual-image v2-a2 CPU probe is a separate pending
gate; neither the existing codec result nor this source review qualifies a GPU
reader, numerical equivalence, standby promotion or recovery.

One concrete capture-evidence defect should be corrected before accepting a
descriptor packet. A separate runtime-configuration assumption must be retained
when a reader is eventually enabled. Do not edit the already-frozen candidate
in place to incorporate either change.

## P2 — Capture does not rebind the packet to the current writer/GMS incarnation

`workshop_shadow_descriptor_writer.capture()` at lines 187–222 checks an earlier
`shadow-writer-serving` pass, the current Pod UID, descriptor version/identity
and a 64-character layout-hash field. It does not recheck the serving proof's
container IDs/restart counts/GPU allocation, nor compare the two captured rank
hashes with the current exact-GPU GMS state.

The descriptors live in an `emptyDir`, which survives a main-container restart
inside the same Pod. Therefore a same-Pod engine/GMS restart after serving
verification can leave old rank files that the capture action still accepts
as `shadow-writer-descriptors=passed`. Pod UID equality alone does not establish
that these files came from the currently qualified writer incarnation. The
reader's separate live `read_committed_manifest()` layout check remains intact;
this finding concerns capture provenance and qualification.

Suggested correction in a fresh reviewed implementation:

- Call the existing `writer.verify_worker()` and compare its container/GPU
  identities with the saved serving proof before and after reading the files.
- Obtain current committed state through `writer.gms_state()` on the exact two
  GPU sockets. Bind captured layout hashes to those live layouts, retaining the
  TP-rank-to-GPU mapping used by the writer.
- Preserve failed/interrupted capture receipts. Reject changed incarnations or
  layout mismatches instead of exporting a passed packet from a stale file.

The relevant existing verifier is `workshop_shadow_writer.py:270–305`; its
serving check already records the required identities at lines 393–395.

## Reader configuration assumption

The descriptor identity binds candidate, image, model revision/config, installed
source manifest, TP size and TP rank. The linear record also exports its compute
configuration. The MoE record exports schemas, Humming layer configs and expert
class, but `restore_reader_runtime()` at lines 570–591 reconstructs its kernel
using the reader's current `qm.moe` and process environment.

The installed Humming expert constructor derives compute/tuning settings from
`VLLM_BATCH_INVARIANT`, `VLLM_HUMMING_USE_F16_ACCUM` and the current MoE config
(`fused_humming_moe.py:128–178`). Those settings are not independently bound in
the current descriptor identity/row. This is a controlled assumption for an
identically configured writer/reader pair; it is not support for importing the
packet under changed DP/EP, routing, batching, device or compute settings.

Before a general reader-ready claim, bind and verify the effective serving/MoE
configuration or explicitly reject changes to it. This is not a reason to
change the fixed writer-only profile or claim a current numerical failure.

## Source checks supporting the intended design

- **Publication order:** the loader prepares the JSON descriptor after writer
  postprocessing and private rebinding. The patched publication call invokes
  `publish_writer_manifest()` only after the stock `publish_gms_write()` returns.
  It then records the committed layout hash, rereads independent GMS contracts
  and atomically creates a fresh rank file. A descriptor write failure propagates
  instead of allowing the loader to report a normal published writer.
- **Independent parameter contract:** every described parameter must match
  `GMSTensorSpec` shape, stride, dtype, allocation ID and byte offset. The extent
  check also requires the parameter to fit within one GMS mapping. Reader meta
  plans are created before rebinding and must match the live contract.
- **Stock guard retained:** the candidate mounts the loader/helper modules,
  not `gpu_memory_service/client/torch/module.py`. The installed materializer's
  exact shape/dtype comparison at lines 203–208 remains active. The manifest
  supplies reviewed final meta layouts; it does not suppress an import mismatch.
- **No reader weight transform:** the patch removes the partially failing meta
  postprocessing call and never runs a weight-processing callback after RO
  materialization. MoE reconstruction uses `get_fused_moe_quant_config()` and
  `make_humming_moe_kernel()`; it checks that scale/input descriptors reference
  the imported layer tensors. The installed Humming experts inherit the no-op
  `process_weights_after_loading()` from the modular base, so omitting that hook
  does not skip a Humming expert transform in the reviewed source.
- **Private workspaces:** linear locks are newly allocated outside the pool;
  MoE expert construction allocates fresh locks. The final helper checks that
  the reviewed linear/MoE lock owners are already outside every GMS pool.
  Parameters retain their independently checked GMS allocation/offset aliases.
- **Fail-closed reader gate:** unknown ModelOpt methods, an unsupported root
  model post-load hook, changed recognized module inventory, changed quant
  scheme/backend, remaining meta parameters/buffers or invalid private state
  prevent successful reader reconstruction. `reader_ready` is a manifest gate,
  not evidence that a GPU reader has run successfully.

## Attention questions resolved by the actual installed sources

There is no contradiction between requiring private writer scale buffers and
also requiring their GMS metadata. The a5 loader calls `prepare_gms_write()`
before `rebind_nonparameter_tensors()` (a5 `model_loader.py:335–341`). The former
registers original GMS-resident buffers; the latter privately clones them while
retaining originals for publication.

On import, stock `module.py:187–196` clones every buffer/tensor attribute into
private memory. Consequently `prepare_reader_skeleton()` does not need to
replace `_buffers` itself. The later attention restore validates the imported
private buffer layout/value and recreates host scale copies. It checks the
fixed FlashInfer/no-sink contract and does not call a transform on RO weights.
The actual no-sink FlashInfer post-load hook returns without mutation.

The absent `--kv-cache-dtype` CLI flag does **not** establish effective `auto`
in a5. Its saved worker log records `kv_cache_dtype=fp8_e4m3` at line 50 and
`torch.float8_e4m3fn` in the FlashInfer selection at line 670. Installed
`ModelOptMixedPrecisionConfig.get_quant_method()` at lines 1755–1763 returns
`ModelOptKVCacheMethod` when checkpoint KV quantization is configured. The v2
FP8 restriction is consistent with this actual writer observation; no speculative
auto-mode expansion is warranted from the CLI default alone.

The installed ModelOpt source was additionally reviewed from
`results/overnight-shadow-super-vl-20261104-a1/recovered-runtime-20261105-a1/sources/vllm/model_executor/layers/quantization/modelopt.py`.
Its `get_fused_moe_quant_config()` delegates to the source-reviewed Humming
builder using the current layer tensors. The candidate image/model pins must
remain unchanged when carrying this source review forward.

## Evidence boundary

The frozen candidate records `reader_enabled=false`, `intentional_fault=false`,
TP2 and 130 installed-source contracts. Its descriptor helper SHA256 at review
was `5aeee2eedd2a07be5be1fcc8df38920f75355ed8fb0c681b3fed1b177f0df970`.
The first v2 CPU failure was in the probe's `_o_scale_float` initialization:
the installed default-scale helper omits that field, while the enclosing
attention initializer sets it to `None`. That probe failure does not establish
a serving/descriptor failure. The corrected actual-image CPU attempt must
remain a fresh receipt; no GPU or reader success is inferred here.
