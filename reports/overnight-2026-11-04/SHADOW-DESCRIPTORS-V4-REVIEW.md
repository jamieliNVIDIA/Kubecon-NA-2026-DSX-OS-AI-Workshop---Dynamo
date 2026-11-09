# Independent Shadow descriptor v4 review

Reviewed locally on 2026-11-05 by the KVCR/review workstream. No network,
cluster, GPU, deployment or frozen-attempt mutation was performed.

**Disposition:** the reviewed v4 helper is suitable to freeze for actual-image
CPU preflight and a fresh, bounded GPU candidate. This is a code/metadata
review, not proof of a successful GMS reader, recovery or live failover.

## Reviewed scope

- `scripts/workshop_shadow_descriptors_v4.py`
- `tests/test_workshop_shadow_descriptors_v4.py`
- `scripts/workshop_shadow_descriptor_cpu_v4.py` (source inspection only;
  root executes the actual-image payload separately)
- Independent tests added as
  `tests/test_workshop_shadow_descriptors_v4_review.py`.

The review traced writer export, independent committed-GMS metadata checks,
reader meta planning, stock-materializer integration, and post-materialization
runtime reconstruction. The v3-to-v4 source diff preserves the original dtype
allowlist, layout attribute allowlist, strict ordinary-parameter exporter,
allocation-extent guard, restricted JSON decoder, attention restrictions and
loader composition. Only the exact forty observed routing correction roles
receive the narrowly checked `requires_grad=True` admission.

The loader still calls the stock `materialize_module_from_gms`; v4 neither
rewrites that function nor relaxes its shape/dtype checks. The new reader does
not invoke weight postprocessing on imported read-only tensors.

## Concrete finding fixed before freeze

The initial role validator compared Python lists by equality. A manifest with
`shape=[512.0]`, `stride=[True]` and `offset_bytes=False` could compare equal to
canonical integer metadata. The ordinary exporter already rejects non-int
shape/stride values, so the new role should preserve that strictness.

The implementation author fixed this during review. Role shape and stride
now require exact lists of exact integers; attributes require an exact empty
dict; dtype requires an exact string. The role manifest and independent routed
and gate byte offsets require exact nonnegative integers. Separate regression
tests reject float/bool values in all three offset sources, float shape and
float/bool stride. No actual GPU failure or corruption was inferred from the
original validation gap.

## Independent behavioral coverage

The nine added tests exercise a complete 80 Humming linear / 40 Humming MoE /
2 Cutlass FP8 metadata inventory. They reuse the prior backend fixture but
install the forty role owners, plain Parameters, gate aliases and independent
fake-GMS metadata separately. Tensor rendering is a tripwire; tensor contents
are never read or copied.

- Complete writer export preserves exactly forty `True` flags, with every
  other exported parameter flag `False`.
- General gradient, unsupported dtype, Fraction/None layout attribute,
  noncanonical ordinary shape, negative stride, nonplain role Parameter,
  broken writer object alias, CPU/meta writer and missing role all fail.
- Full parameter extent must fit a single unambiguous allocation.
- Missing gate metadata, a buffer masquerading as a gate parameter, or wrong
  gate allocation/offset/shape/stride/dtype fails.
- A late non-meta skeleton, nonfinite/Fraction attrs or forged role fails
  before any layer parameter dictionary is rebound.
- After materialization, separate routed/gate Parameter objects are accepted
  only when their physical allocation and byte offset match. This models the
  stock materializer's construction of separate Parameters over shared data.
- Changed routed CUDA/meta status, shape, stride, dtype, gradient, attrs,
  pointer offset or allocation fails. Changed gate offset, gradient, dtype,
  Parameter class or attrs fails. Ordinary gradients, dtype, pointer and layout
  remain guarded. Unexpected optional parameters fail.
- Foreign MoE quantization aliases and workspaces allocated in a GMS pool
  still fail; no weight transformation hook runs during the positive rebuild.

## Validation and immutable references

Command:

```text
python3 -m unittest discover -s tests -p 'test_workshop_shadow_descriptors_v4*.py' -v
Ran 15 tests in 0.393s
OK
```

Reviewed helper SHA-256:

```text
ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e
```

Independent review test SHA-256:

```text
6a1439eaf16730d3b0d05dd9d7cdc8b137078a5a59b59e52ea2b4819347619c2
```

## Limits and next gates

PyTorch is not installed in this local workspace; these passing tests use
metadata doubles. The separate actual-image CPU payload must verify real
PyTorch meta construction, source-bound Nemotron/RoutedExperts alias
construction, stock materializer flag/alias behavior, the unchanged stock
shape/dtype rejection and inference-mode source evidence without initializing
CUDA. A fresh GPU candidate must then qualify writer publication, exact
committed-layout attachment, both TP ranks, private workspaces, reader warmup,
request correctness and any actual failure/recovery behavior. Existing a5,
v2/v3 and all failed attempts remain preserved.
