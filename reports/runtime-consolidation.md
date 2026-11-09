# One workload runtime for the workshop — October 13, 2026

**The custom common image is now qualified for the bounded vLLM/Nemotron matrix.**
See [the completed qualification](2026-10-13-common-runtime-progress.md) and
`configs/common-runtime-qualified.json`. Serving, routing, disaggregation,
ModelExpress, native sidecar, KVCR, Grove and fresh TP1 Snapshot all passed.
Shadow/GMS packaging is present; live failover retains its GPU DRA blocker.

The original passing main runtime and sidecar shared Dynamo 1.5.1 and vLLM
0.28.0. KVCR was the exception: its validated preview used Dynamo 1.6.0 sources,
vLLM 0.31.1 development code, KVCR 0.1.1 and NIXL 1.5.0.
No runtime lock or cluster deployment was changed during this assessment.
The authorized [candidate build and qualification work](2026-10-13-common-runtime-progress.md)
has completed; the existing passing locks remain available as baselines.

## Original passing sets

| Set | Dynamo | vLLM | NIXL | Other packages / scope |
| --- | --- | --- | --- | --- |
| Integrated runtime | 1.5.1 | 0.28.0 | 1.3.2 | ModelExpress 0.6.0; inference, KV routing, disaggregation, weight P2P and TP1 Snapshot passed |
| Sidecar pattern | CPU sidecar 1.5.1; stock engine contains no ai-dynamo | 0.28.0 | 1.3.2 in engine | Separate engine and CPU sidecar containers; aggregated inference passed |
| KVCR preview | 1.6.0 built at `ea23e5130c1bfbadec477b99449d0cee5598caa0` | `0.31.1rc1.dev23+g43b4aaea3` plus pinned six-file adapter overlay | 1.5.0 | KVCR 0.1.1, NCCL 2.30.7; matched cross-node cache transfers passed |

Exact baseline image digests are in `configs/model-lock.json`,
`configs/sidecar-images.json` and `configs/kvcr-lock.json`. The original KVCR test installed
the cached Dynamo wheels, pinned KVCR package, NCCL and vLLM adapter into disposable
containers at startup. Its base image alone did not identify the complete
runtime; wheel/source hashes were also part of that tested set. The qualified
common image now contains those components at build time.

## Why stable 1.5.1 is not a drop-in common image

The [Dynamo 1.5.1 package metadata](https://github.com/ai-dynamo/dynamo/blob/2093662a4d4e5fd318732935213dde08dc7be818/pyproject.toml)
pins vLLM 0.28.0 and NIXL 1.3.2. The
[pinned KVCR package](https://github.com/ai-dynamo/kvcr/blob/f6b9387b9e838ee9196a5d22b107e4c95f6f1dfb/pyproject.toml)
requires NIXL 1.5.0. Its
[validated quick-start build](https://github.com/ai-dynamo/kvcr/blob/f6b9387b9e838ee9196a5d22b107e4c95f6f1dfb/Dockerfile.quick-start)
also selects newer vLLM adapter and Dynamo router-hint contracts together.

Our pinned source audit found the stable constants use
`ROUTER_HINT_RUNTIME_CAPABILITY_KEY`, while the tested preview integration imports
`KV_HINT_TRANSFER_CAPABILITY_KEY`. Matching string values do not establish matching
request/protocol behavior. Merely installing KVCR into the 1.5.1 image would
replace dependencies without qualifying the associated integration.

## Common candidate

Consolidate upward around the already passing **KVCR preview compatibility set**:

1. Keep the exact nightly vLLM base digest, six adapter source files, KVCR source,
   Dynamo Python/Rust wheels and NCCL/NIXL pins from `configs/kvcr-lock.json`.
   Bake these into the image instead of installing them at each Pod startup.
2. Add checksum-pinned AWS EFA userspace 1.49.0 and ModelExpress 0.6.0 plus its
   required dependencies. Reconcile imports/native libraries after installation;
   do not let a backend extra silently replace the selected vLLM/NIXL stack.
3. Build `dynamo-vllm-sidecar` from the **same Dynamo source SHA** as the frontend
   and integrated workers. The
   [sidecar crate at that revision](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/sidecar/vllm/Cargo.toml)
   is present. Do not keep the 1.5.1 sidecar binary merely because both builds
   carry a similar release label.
4. Preserve the engine-sidecar deployment pattern: two processes in separate
   containers, engine launched through native `vllm-rs`, sidecar through its
   Rust binary. A literal one-image deployment can place both entrypoints in
   the common image and select the command per container. CPU roles receive
   no GPU allocation. A smaller sidecar image built from the same source SHA
   gives one version set with two image artifacts and lower image-pull cost.

Using the common image for the sidecar engine would change the current assertion
that the stock engine has **no installed ai-dynamo package**. That assertion
would need to become “native engine entrypoint, external Dynamo sidecar, no
in-process Dynamo worker.” A successful integrated-worker test would not prove
that sidecar pattern.

The candidate is promising for Snapshot: the exact selected
[vLLM source](https://github.com/vllm-project/vllm/blob/43b4aaea3e40e20ef53ce2bfecfa1b72060bf2b5/vllm/v1/engine/async_llm.py)
contains `checkpoint_prepare` and `checkpoint_restore`; the matching
[Dynamo revision retains the native Snapshot path](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/components/src/dynamo/vllm/snapshot.py).
This is source-level evidence, not proof that the new image captures/restores
the model or that all its libraries are compatible.

## Required qualification before promotion

| Test | Required evidence on the common candidate |
| --- | --- |
| Packaging | Exact installed versions, import paths, native extensions, gRPC and sidecar entrypoints; image digest and all source/wheel hashes |
| Nemotron serving and KV routing | Correct output, two workers, six unforced prefix repeats, events and nonzero cache reuse |
| Disaggregation | Cross-node EFA/NIXL KV transfer, expected output, zero failed transfers/notifications |
| ModelExpress | All expected weight tensors via peer loading, no disk fallback, correct inference |
| Sidecar | Native gRPC engine plus external CPU sidecar, registration and correct inference |
| KVCR | Matched source/destination blocks and bytes, cache reuse, correct inference and cold-JIT health stability |
| Snapshot | Native preparation, **fresh image-specific checkpoint**, distinct restored Pod, `Restored=True`, correct inference; record artifact bytes and phase times |
| Shadow Engine | Runtime/GMS checks first; live recovery still needs the independent GPU DRA infrastructure fix |

Do not reuse the 1.5.1 Snapshot artifact after changing the runtime image. Keep
the current passing locks until this matrix passes. The shared operator may
remain 1.5.1 while candidate DGDs set their actual `runtimeVersionOverride`,
as the passing KVCR DGD already does. Grove/KAI and Snapshot infrastructure
images remain separate platform components.

## Audit receipt

`scripts/audit_runtime_consolidation.py` fetched 13 files by immutable Git SHA,
saved content hashes, extracted dependency lines and parsed checkpoint method
definitions. Receipt: `results/20261013-runtime-consolidation-audit/audit.json`.
The audit made no cluster changes and did not build or qualify a common image.
