# Independent reader-only v5 review

Reviewed locally on 2026-11-05. No network, GPU, cluster or frozen-attempt
actions were performed. The capture helper remains unchanged at SHA-256
`c0c9bcd83afcbcf7c9c8b33a8248f2be305ddacecbd272c4a76fe206ab228750`.

**Disposition:** no remaining source-review blocker to actual-image CPU
preflight followed by a fresh GPU reader candidate. This review does not
qualify a parked reader, request recovery, replenishment or an SLO result.

## Why this callback is appropriate

The pinned actual-image `ModelOptNvFp4FusedMoE.get_fused_moe_quant_config`
evaluates `layer.w13_input_scale` and `layer.w2_input_scale` while constructing
arguments for the generic NVFP4 oracle. These are checkpoint-stage attributes;
the actual final Humming layers contain seven parameters and neither input
scale attribute. The generic wrapper therefore fails before reaching the
Humming-specific branch.

The same pinned oracle's Humming branch directly calls
`get_humming_moe_quant_config(layer, gemm1_alpha=..., gemm1_beta=...,
gemm1_clamp_limit=...)`. That native helper reads the final weight/input schemas,
Humming configs and final parameter references. It uses optional lookups for
absent input scales and creates quantization descriptors without transforming
the imported weights. v5 takes this already selected Humming path directly and
forwards the constructor's SwiGLU alpha, beta and limit values. Other backends
remain excluded by the existing `_kind` checks.

## Exact change and preserved guards

The complete v4-to-v5 source diff contains only:

1. An explicit reader adapter revision constant.
2. Replacement of the generic MoE config callback by the native Humming config
   callback and its three SwiGLU arguments.

Reversing those exact substitutions reconstructs the reviewed v4 file
byte-for-byte. All **29 other top-level function bodies** are byte-identical,
including writer export, writer preparation/publication, schema version,
codec, metadata and role validation, allocation checks, reader meta skeleton,
attention handling and stock-materializer loader composition. The reader's
remaining reconstruction body is preserved, including final parameter alias
checks, native kernel construction, private workspace checks and the deliberate
absence of weight postprocessing. Schema `VERSION` remains v4; the adapter
revision identifies the new reader implementation separately.

`validate_reader_delta` proves only that exact source relationship. Its caller
must supply the accepted writer bytes and separately bind both helper hashes
to the fresh candidate. It does not independently establish writer acceptance
or grant permission to reuse a failed candidate. This is an integration gate,
not an unresolved callback defect.

## Packet and tests

The existing packet at
`results/workshop-shadow-reader-v5-cpu-packet-20261105-a1` was checked against
its file manifest, the actual accepted a6 rank manifests, the writer spec and
the four pinned installed-source contracts. It contains exactly **80 unique
rank/owner pairs** (40 per rank), all in one identical final-layout group.
Every normalized shape, stride, dtype, gradient flag, layout attribute and
encoded schema/config matches its actual writer row. Each has the observed
seven parameters, no optional-parameter entries and no raw checkpoint scales.
The packet's helper and CPU program bytes match the reviewed local sources.

Eight independent tests were added in
`tests/test_workshop_shadow_reader_v5_review.py`. With the author's three tests,
**11 tests pass**. Independent coverage includes:

- Whole-source inversion and all 29 unchanged function bodies.
- Refusal of any additional dtype/gradient, alias, allocation, format,
  workspace, lifecycle or reader-transform edit by the delta gate.
- Native callback arguments for absent/default, explicit zero and nondefault
  SwiGLU values across all forty MoE layers; unchanged parameter identities and
  metadata; no recreation of checkpoint-only scale attributes.
- Continued rejection of ordinary/role gradient errors, unsupported dtype,
  wrong role or gate pointer, gate dtype, non-CUDA parameters, unexpected
  optional parameters, foreign scale/input aliases and GMS-backed workspaces.
- Propagation of native builder errors with no generic callback or weight
  transformation fallback.
- Actual packet/source/role equivalence and fail-closed packet preparation for
  changed source, wrong version, changed correction gradient, checkpoint-layout
  drift or a missing rank, before creating output.

The actual-evidence tests skip when the local a6 packet is absent; they ran and
passed during this review. Local tests use metadata doubles because PyTorch is
not installed in the workspace environment. The separately prepared CPU
program must run inside the pinned actual image to verify real decoded
Humming config types, real Torch meta parameters, exact aliases and traps for
weight transforms/kernel creation, with CUDA remaining uninitialized. Its
source correctly limits its claim to that CPU builder preflight.

Validation:

```text
PYTHONDONTWRITEBYTECODE=1 .local/venv/bin/python -m unittest discover -s tests -p 'test_workshop_shadow_*v5*.py' -v
Ran 11 tests in 2.306s
OK
```

## Reviewed hashes

| File | SHA-256 |
| --- | --- |
| Accepted v4 helper | `ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e` |
| Reader v5 helper | `2f144fd5971aa07bc6008dfe7c6fd5c5b85c7d4d33d17c7fae9bb277280c9403` |
| Reader delta validator | `3faddc235e31377edebf905c028e3042f9ea75f349f49898a1e0bdb55d9a61bc` |
| CPU packet/program module | `d9a0ef5868a0a6e61ce15a5c1f34622361d6bdfa226dee076fcfc62b86a0d14e` |
| Embedded actual-image CPU PROGRAM | `daf61d6852053c481fc4539a6c10348ae836ad1d6327dd2f364ea8790aaf94ec` |
| Independent review tests | `80988c2ae40fb99aa5a4db00e341cad57ceffcb36ae5ef72b8bfafd4a4319a7c` |

The next GPU gate must use a fresh candidate and preserve failed full-a1. Full
ready/parked and correct coding proof must precede any fault. The first actual
fault capture and subsequent post-fault health/final qualification remain
separate gates; v5 source equivalence does not satisfy any of them.
