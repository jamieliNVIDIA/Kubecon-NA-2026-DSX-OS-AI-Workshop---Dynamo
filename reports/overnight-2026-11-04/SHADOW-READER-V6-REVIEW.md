# Independent reader-only v6 review

Reviewed locally on 2026-11-06 UTC. **Source review and the separately audited
actual-image CPU preflight passed.** No new GPU candidate or live operation was
performed by this reviewer. Existing v4/v5 helpers and held capture code were
preserved.

## Source-backed state repair

Full-a2's preserved first fatal is in native DeepGEMM warmup inspection. That
inspection re-enters the generic ModelOpt metadata callback, which eagerly
reads `w13_input_scale` and `w2_input_scale`. The final reader has seven
registered parameters and neither raw scale attribute, so the generic call
fails before its native Humming dtype filter.

The pinned ModelOpt import identifies its `replace_parameter` as
`vllm.model_executor.utils.replace_parameter`. Its actual `new_tensor is None`
branch is `setattr(layer, param_name, None); return`, before any Torch tensor
allocation, copying or parameter construction. After Humming removes the raw
parameters, ModelOpt's two postprocessing calls therefore create ordinary
`None` attributes. This is distinct from registering extra parameters whose
values are `None`.

V6 restores only that ordinary state. It requires the exact final seven
parameter names and an empty optional-parameter manifest. For both sublayers,
it requires the exact HummingInputSchema class, `quant_method='humming'`, null
activation dtype/quantization/scale dtype/static scale name, and an exact
integer zero scale group size. It rejects registered input-scale parameters
(including registered `None`), buffers (including `None`), non-None ordinary
values and inherited attributes. Both sublayers are validated before mutation;
the result must appear directly in `layer.__dict__` as ordinary `None`.

The initial helper accepted unrelated schemas with coincident null fields and
a different `quant_method`. The author added exact schema-class and Humming
method guards during this review; the independent negative cases now pass.

## Preserved implementation

The exact v4-to-v6 delta consists of the separately reviewed v5 native Humming
builder callback, the explicit v6 revision, the new restricted optional-state
helper and its single reader call. All **29 other original top-level functions**
are byte-identical to the accepted v4 helper. Writer export, schema `VERSION`,
codec, dtype/gradient/layout/allocation guards, reader skeleton and the stock
materializer integration are preserved. The remaining reader reconstruction
body and alias/private-workspace checks are unchanged.

Full metadata reconstruction tests exercise 80 Humming linear, 40 Humming MoE
and two Cutlass layers. Every MoE retains the same seven registered Parameter
objects and aliases; the two ordinary None attributes are added without
re-running a weight transformation or replacing parameters. Idempotent helper
calls retain the same result.

## Native CPU preflight review

The packet at `results/workshop-shadow-reader-v6-cpu-packet-20261105-a1` was
rehashed and rebuilt exactly from the accepted a6 writer and exact-image source
receipts. It binds **80 unique rank/owner pairs**, one identical final-layout
group and **seven** installed-source contracts. The three added contracts cover
the imported native replacement helper and native DeepGEMM/kernel warmup source.
Wrong source bytes, missing source records or an image mismatch fail before
packet output is created.

The actual-image PROGRAM:

- Verifies every source/helper/packet hash and the ModelOpt import identity.
- Reproduces the original generic native warmup-count missing-attribute failure
  before repair.
- Executes the actual imported native None helper as a reference and compares
  its ordinary state to the candidate repair.
- Uses real Torch meta Parameters, RoutedExperts/MoERunner and ModelOpt/Humming
  classes, the real native generic oracle and decoded final schemas/configs.
- Calls the unmodified installed native predicate/count bodies with both
  DeepGEMM flags explicitly true; the repaired metadata reaches the dtype
  filter, returns predicate `False` and count zero.
- Uses explicit tripwires for hardware helpers and weight transformations;
  preserves the seven parameter identities/metadata and gate alias; requires
  CUDA to remain uninitialized.

Those CPU checks concern the normalized MoE fixture, not dense/full-model
warmup or GPU execution. The PROGRAM explicitly reports its metadata doubles
(environment flags, ineligible provider/expert classes, empty caches and
unreachable hardware helpers). It does not set a warmup skip flag or modify the
native predicate/count bodies. The code review does not substitute for root's
actual-image CPU result.

## Actual-image CPU receipt audit

Root's `reader-v6-source-cpu` completed successfully at
`2026-11-06T00:17:46.908690+00:00`. The independent audit is recorded in
`results/workshop-shadow-reader-v6-independent-audit-20261105-a1/verification.json`.
The result, canonical check/state, intent, actual Pod manifest/environment,
retained stdout and reviewed packet/program/helper all agree byte-for-byte.
The Pod ran the exact pinned runtime image with `NVIDIA_VISIBLE_DEVICES=void`,
CPU/memory resources only and no GPU claims; its successful completion and
scoped deletion were confirmed in captured command receipts.

All three actual-image cases (absent/default SwiGLU, explicit zeros, and
nondefault values) reproduced the original missing-attribute failure, matched
the native ordinary-None behavior, returned actual Humming configs through the
generic callback, preserved seven parameters and the gate alias, and produced
native predicate `False` / count zero with both flags true. CUDA remained
uninitialized. All seven installed-source hashes matched the packet.

Actual CPU result SHA-256:
`d8bd2f45332624df3bbdbdc51039c133b3898e93d675b798015b0e41335c915c`.
Canonical check SHA-256:
`e5007c491dab6d2301cd62cda1872d01bc319665f70b531bb1f977d85f51a88c`.
Packet SHA-256:
`6a716a93b3ccba69ba027054b24f6065e8c7995327f692f8dd9afbf2b5d586aa`.

## Validation and hashes

**13 focused tests passed**, including ten independent tests. Local source-body
tests reproduce the original generic/predicate/count failure and then `False/0`
with metadata doubles and both flags true. A Torch-access tripwire remains
untouched when executing the actual imported native None branch. No local
PyTorch, network or GPU execution was used by this reviewer.

```text
PYTHONDONTWRITEBYTECODE=1 .local/venv/bin/python -m unittest discover -s tests -p 'test_workshop_shadow_*v6*.py' -v
Ran 13 tests in 8.915s
OK
```

| File | SHA-256 |
| --- | --- |
| V6 helper | `5a59b4c6e24574e3017bff5197b4603961f396da8504fb2594033b44ca410528` |
| V6 delta validator | `9ee875cd272ff5f05f41bfb9379cd96bec38c8c0ae005fc3bac3eeb00e6a8f3a` |
| V6 CPU packet/program module | `fe092536453e5c817dcf2a35425d3db1407ad748bada4ede0f7d005815328733` |
| Embedded actual-image PROGRAM | `8b7fd10730c2bb80a01d8a5e1975d50c9b53b2244bd0c5b8de93c85150b19288` |
| Independent tests | `bd7296910bbc480ea8e06f49a70a1051d50f4480d4f4b76ac465a27286632a58` |

The delta validator still requires its caller to bind the original helper to
the accepted writer. Source equivalence and CPU metadata success do not qualify
GPU materialization, a parked reader, fresh coding, recovery or an SLO. A future
GPU attempt requires a fresh separately reviewed candidate after the other
integration gates; this review created none.
