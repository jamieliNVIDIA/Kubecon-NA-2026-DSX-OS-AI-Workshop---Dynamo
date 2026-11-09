# KVCR-Guard upstream readiness

Reviewed November 4, 2026. **Recommendation: proceed to an isolated experimental
qualification.** There is a working implementation and a specific recovery test
to adapt. This source review does not establish production readiness, a passed
GPU recovery run, or compatibility with our exact Super VL/EFA image.

No tests were executed and no cluster resources were changed for this review.
Retrieved source snapshots and blob identifiers are retained privately under
`results/upstream-kvcr-guard-review-20261104/source-manifest.json`.

## Revisions inspected

| Source | Revision / status |
| --- | --- |
| KVCR main | [`dd5df02c076dfee4bb2cdc39bef11164f9dcaec5`](https://github.com/ai-dynamo/kvcr/tree/dd5df02c076dfee4bb2cdc39bef11164f9dcaec5), package source version 0.2.0, NIXL 1.5.0 |
| Dynamo main | [`c3df5f98e624370f142ada1a99106a9e09ad6984`](https://github.com/ai-dynamo/dynamo/tree/c3df5f98e624370f142ada1a99106a9e09ad6984) |
| Dynamo Guard example | [PR #14695](https://github.com/ai-dynamo/dynamo/pull/14695) merged September 17; current files have further updates |
| Current Dynamo example's stack pins | KVCR `7ce17c358b867bd89f40a4a42bee9c76839506d0`, vLLM adapter `fed7de909f894fbee0c45130376aed2e2c9bf0d3` |
| Current KVCR quick-start pins | vLLM adapter `a5db4c9ff58a0ec4dc20594ba5cea9f776dcd693`, base image `nightly-40941f2c4ba96fba0a7e282a5355e89cd74d9ac5` by digest, Dynamo `318ab0390d8e3e1fa7517ea6a1ebf46a7854c236` |

These are separate pinned stack combinations. The quick-start still calls
#14695 a proposed deployment; the merged PR and current Dynamo tree supersede
that wording. The quick-start remains explicitly a public preview.

## What is implemented

The service creates host-memory pool groups, one exclusive claimant per group,
and a passive Guard. The engine maps the service-owned pages through file
descriptors passed over a Unix socket. A shared journal mirrors committed
block metadata. The service also owns the peer-control listener and passes a
duplicate to the engine.

On confirmed engine-process death, the Guard drains the journal, adopts the
recoverable G2/host-memory records, starts its own NIXL core and serves peers
at the same control endpoint. A replacement primary can reclaim the pool and
its records through a handback. The code logs `KVCR_EVENT guard_promoted` with
recovered block count and promotion-stage timings. These paths are implemented,
not only described in the design document.

Sources: [service guide](https://github.com/ai-dynamo/kvcr/blob/dd5df02c076dfee4bb2cdc39bef11164f9dcaec5/docs/dev-guide.md#kvcr-guard-service),
[`_observe_holder`, `_promote`, `_serve`, `_hand_back`](https://github.com/ai-dynamo/kvcr/blob/dd5df02c076dfee4bb2cdc39bef11164f9dcaec5/src/kvcr/service/guard.py).

The workshop claim should be: **the inference process can die while previously
committed, offloaded cache remains available to another engine.**
Request migration separately continues generation by replaying retained token
IDs; Guard can reduce the cached-prefix recomputation needed by a new request
or retry. Their composition still needs its own qualification.

## Evidence available upstream

- [`test_guard_integration.py`](https://github.com/ai-dynamo/kvcr/blob/dd5df02c076dfee4bb2cdc39bef11164f9dcaec5/tests/unit/test_guard_integration.py)
  includes real subprocess death, a real NIXL/UCX read from the promoted Guard,
  exact payload verification and replacement-primary handback. The real native
  transport case skips if a runnable NIXL agent is unavailable. Other cases
  cover multiple pools and retry after a timeout during promotion.
- The current [Dynamo deployment guide](https://github.com/ai-dynamo/dynamo/blob/c3df5f98e624370f142ada1a99106a9e09ad6984/examples/backends/vllm/deploy/kvcr/README.md)
  supplies a two-node memory-service DGD and lifecycle guidance.
- Its [live Guard test](https://github.com/ai-dynamo/dynamo/blob/c3df5f98e624370f142ada1a99106a9e09ad6984/tests/deploy/test_kvcr_guard.py)
  seeds one source, confirms the target was not seeded, kills EngineCore and
  holds it down. It requires an unchanged sidecar, Guard promotion, matching
  response content, positive target `remote_deliver` blocks, KVCR tier-read
  bytes and `external_kv_transfer` prompt tokens. It also checks payload-sized
  HCA traffic, then engine readiness and recovered record count after handback.

This is a substantive test specification, but it is explicitly manual/opt-in
until a dedicated two-host RDMA lane exists. The separate KVCR GPU E2E workflow
tests ordinary peer reuse, not Guard recovery. The inspected source therefore
does not establish a continuously passing Super VL/TP2/EFA recovery gate.

## Boundaries that affect our experiment

| Boundary | Consequence |
| --- | --- |
| Only committed KVCR-owned G2 records are served after failure | GPU cache, vLLM-owned host cache, partial writes and in-flight operations are not recovered. Confirm positive writes into the Guard-owned pool before faulting. |
| Service/pool lifetime | The reference sidecar survives a main-container restart. Pod deletion, node loss and service loss are outside this guarantee. Its memory-backed emptyDir is not durable storage. |
| Sidecar/state-agent failure | Current example calls sidecar restart deployment-fatal and requires an external controller to replace the affected Pod or worker group. Losing worker 0's state agent requires group recreation because live agent reselection is not supported. Automatic coupled recovery is not supplied by this example. |
| Fencing | Default pidfd-only promotion waits for confirmed process exit. Optional missed-heartbeat promotion sends SIGKILL and promotes without waiting for confirmed exit; code and developer docs explicitly call that fence weaker/best-effort. Use the default for the first experiment. |
| Recovery capacity | Journal is fixed at 100 MiB per Guard. Overflow disables warm recovery while the service can continue. A promotion event or healthy probe alone does not prove any usable cache survived. |
| Guard failure | One Guard failure stops the service; there is no per-group failure containment yet. Do not configure independent liveness restarts beneath engines still mapping its pools. |
| Storage tier | Guard currently does not serve G3. Inherited G3 file contents are not verified; exclude disk/G3 from this first trial. |
| Registration/startup | Large pool registration may take tens of seconds. Guard preparation is asynchronous; promotion can wait for it. Takeover/handback scale with recovered block count. The pinned engine adapter has a separate default 60-second initialization budget. |

The older design prose describes strictly fenced takeover; the current code
and developer guide qualify the optional heartbeat path more narrowly. The
recommendation here follows the pidfd-only implementation.

## Compatibility work before a GPU run

1. **Freeze a matched stack.** Both current source combinations use the 0.2.0
   version label, but their key-adapter APIs differ. KVCR main expects
   `decode_from_framework` / `encode_to_router`; the Dynamo example's older
   adapter implements `encode` / `decode`. Do not combine those pins unchanged.
   Use the current KVCR quick-start's matched adapter as the initial API
   reference, or retain the Dynamo example's complete older pair.
2. **Keep the existing runtime intact.** Our checked-in runtime probe and dated
   feature report identify KVCR 0.1.1 and NIXL 1.5.0. The existing vLLM adapter
   already has Guard configuration symbols, but our qualified serving config
   exercises peer transfer through vLLM's host tier, without a service-owned
   secondary pool. That result does not qualify Guard. A new candidate needs
   CPU import/API checks before GPU use; a KVCR wheel alone need not upgrade
   the adapter or native dependencies.
3. **Adapt the transport proof.** The upstream DGD/test use UCX, InfiniBand
   resource names, `mlx5` devices and HCA counters. Our established KVCR path
   uses NIXL LIBFABRIC/EFA. Both main and Guard need that backend and device
   access, and the test needs equivalent EFA transport evidence. The IB-specific
   test cannot simply run unchanged here.
4. **Retain the workshop model requirement.** The reference live test is
   Qwen3-0.6B, TP1. Super VL TP2/hybrid cache layout remains an explicit
   qualification gate. Preserve stable logical cache-owner IDs and compatible
   pool geometry across restart; the example gets IDs from Grove's replica index.

## Suggested first qualification

Use two aggregated Super VL TP2 workers on different nodes: **four H100s**,
plus CPU Guard service sidecars and a small, explicitly budgeted host-memory
pool per worker. Use pidfd-only detection and G2 only. First establish ordinary
cross-worker reuse with the exact candidate image.

Then seed A and wait for committed secondary-pool writes. Confirm B lacks that
prefix. Kill A's guarded EngineCore and hold its replacement engine down,
keeping A's Pod, Guard and state-agent identities unchanged. Require a nonempty
Guard recovery, successful B generation, positive matching cache-transfer
blocks/bytes and external-KV tokens, zero failed/partial delivery, and EFA
transport evidence. Finally release the hold and verify handback plus a fresh
generation on A, beyond merely observing readiness or a record count.

Only after that passes, combine Guard with the already-qualified frontend
request-migration demonstration. That second experiment must establish actual
reuse during continuation; successful request completion alone could still
come from recomputation.

## Follow-up: same-GPU GMS / Shadow composition

Guard's preserved host pool can conceptually serve a promoted shadow on the
same GPU, through pool reclaim or peer retrieval. GMS makes engine/weight
recovery fast; Guard supplies previously committed cached context, which is
loaded into the promoted engine's GPU cache. This composition has not been
qualified by the separate tests above. GPU-only and uncommitted state remain
outside Guard's protection, and request continuation still requires frontend
migration/retry.

One concrete integration gate is pool ownership: `guard.py:_reserve_claim`
rejects a second claimant while the original engine is alive. A preinitialized
shadow cannot simultaneously claim that same group. The integration must
coordinate attachment at promotion or give the shadow a separate group and
retrieve from the preserved source. Compatible cache geometry and logical
owner identity are also required.

Current Dynamo GMS code contains a separate, default-off GPU persistence path:
[`DYN_GMS_PERSIST_KV`](https://github.com/ai-dynamo/dynamo/blob/c3df5f98e624370f142ada1a99106a9e09ad6984/lib/gpu_memory_service/integrations/vllm/worker.py#L85).
At wake-up it requests `RW_DATA_OR_RW`; an existing committed layout is adopted
and remapped instead of freshly allocated. Otherwise it allocates and commits
the layout. It requires identical geometry; adoption failure is not repaired
in place. Keeping those pages also changes sleep's memory-release behavior.

That worker path establishes allocation/byte retention, not by itself recovery
of the dead engine's prefix index, block ownership or active request metadata.
Its integration should be evaluated separately from CPU-cache preservation.
The GMS README still describes the usual fresh-KV wake path; the optional
branch is visible in `worker.py:wake_up`. The existing Shadow failover test
does not establish a combined GMS + Guard warm-prefix recovery result.

## Follow-up: two-engine workshop qualification

The same-node Super VL TP2 attempt reached serving and committed host offload,
but failed its ordinary peer-reuse prerequisite. The pinned runtime's state
agent rejected recurrent events with `NonMainAttentionKind` and quarantined
CacheOwner residency. The receiver recomputed; no engine fault was injected.
Merged [Dynamo #15535](https://github.com/ai-dynamo/dynamo/pull/15535) addresses
that exact rejection and is absent from the tested runtime source. This is a
runtime-version gate, not evidence that current upstream universally lacks
hybrid support or that Guard recovery failed after promotion. Full attempts,
compatibility fixes, evidence and verified cleanup are recorded in the
[qualification report](workshop-kvcr-guard-qualification.md).

### Nightly follow-up

No checked release tag contains Dynamo #15535, including v1.6.1. The November 3
nightly contains the fix. The unmodified nightly image bundles NIXL 1.4.1;
this KVCR candidate requires 1.5.0. The qualification therefore used SHA-pinned
official Dynamo **1.7.0.dev20261103** wheels in a private overlay on the existing
Super VL/NIXL 1.5 base, with matched packages in the frontend and both workers.

Same-node a4 passed ordinary peer reuse, controlled Guard-only retrieval by B
after A's engine died, and warm local-pool handback to replacement A. Each
recovery request reused 4,224 input tokens through six preserved blocks (99 MiB).
Both Guards and B stayed unchanged; source main had one liveness restart.
The first unpinned post-fault request returned 503 before discovery removed A;
the passing diagnostic explicitly pinned B and request migration was disabled.
This is experimental component evidence, not automatic failover, stream
continuation, cross-node or GMS qualification. Full pins, failures, handback
proof and cleanup are in the qualification report and its
[nightly receipt](receipts/2026-11-04-kvcr-guard-nightly.json).
