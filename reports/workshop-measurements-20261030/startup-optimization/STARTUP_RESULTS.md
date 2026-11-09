# Startup candidates measured before Snapshot

Two configuration candidates were tested with Super VL, TP2 H100, native
1,048,576 context, four engine sequences, 8,192 batched tokens, GPU-memory
fraction 0.85 and the same pinned inference image. These are idle-source
startup experiments with a preexisting EFS checkpoint, not AgentX throughput
or fault-recovery benchmarks.

## Text-only mode: the main configuration gain

The MX weights-plus-artifacts receiver reached observed Ready in **188.82 s
(3m09s)**, versus **249.70 s (4m10s)** in the earlier multimodal run. This is
an unpaired, single-trial comparison with the deliberately reduced input
capability requested for this workshop.

Logged engine initialization fell **74.44 → 41.21 s**. Both ranks loaded the
transferred AOT compilation cache, and both source and receiver explicitly ran
in text-only mode. Backbone profiling/warmup remained **27.72 → 28.78 s**.
About **22.88 s** of the observed **60.88 s** total reduction was a shorter
health/probe tail under unchanged settings; the entire wall-clock difference
cannot be attributed to removing multimodal work.

Use `--language-model-only` on matching seed and receiver, with fresh compatible
artifacts. The detailed [text-only report](TEXT_ONLY_RESULT.md) includes the
exclusive timeline, raw-input hashes, KV capacity and exact GPU identities.

## Health timing: a smaller, matched gain

One idle source served both receiver arms. Receiver processes and caches were
fresh, and both loaded the same published torch artifact IDs on both ranks.
Receiver GPU UUIDs matched: **True**.

| Measurement | Default health | Faster health |
| --- | ---: | ---: |
| Deployment → observed Ready | 188.86 s | 178.79 s |
| Deployment → first checked correct response | 191.07 s | 180.98 s |
| Model loading, slower rank | 52.91 s | 52.77 s |
| Engine initialization | 40.63 s | 40.58 s |
| Backbone profiling/warmup, nested in engine initialization | 28.88 s | 28.75 s |
| Engine end → observed Ready | 23.56 s | 9.04 s |

Total observed startup fell **10.06 s (5.33%)**.
The tail shortened **14.52 s**; approximately unchanged model and
engine timers plus bootstrap/scheduling variation explain why the total gain
differs from the tail gain. This is one fixed-order pair with five-second
Ready polling, not a latency distribution.

The fast arm changes worker canary wait **10 → 1 s**, startup-probe period
**30 → 2 s** and readiness-probe period **10 → 2 s**. Startup failure threshold
changes **120 → 1,800**, preserving a **nominal** 3,600 s period-times-threshold
budget. Probe timeouts and liveness are unchanged. Because the retained startup
timeout is 20 s, slow/hung probes can change the actual failure window; this is
not production-equivalent failure-detection qualification. Idle canary and
probe frequency also increases. The [frozen plan](TEXT_ONLY_HEALTH_PLAN.md)
contains exact controls and acceptance conditions.

## Remaining targets

The qualified text-only pilot still spends about **63 s before model loading**,
**35 s in MX hidden-tensor discovery**, and **29 s in backbone profiling/warmup**.
The last two are nested in their respective model/engine timers. Actual peer
copies are around three seconds and cached compilation around 0.2 s.

MX tensor discovery has no safe supported bypass: it transfers derived NVFP4
scales needed for correct inference. Profile and optimize repeated object
traversal while retaining the complete tensor manifest. Bootstrap and backbone
warmup need more detailed profiling before assigning a further saving.

vLLM already enables Triton persistent autotuning; adding its enable flag is
not a new optimization. The [warmup investigation](../round-robin/DECODER_WARMUP_NEXT_OPTIONS.md)
distinguishes confirmed cache behavior from unmeasured CUDA/JIT possibilities.

For workshop comparisons, remeasure storage, peer weights and peer-plus-artifacts
with the final text-only configuration before combining their numbers into a
matched loading-path chart. The original multimodal matrix remains a separate
matched experiment. No Snapshot or initialized-process restore was used here.

## Evidence

- Text-only pullback: `results/workshop-textonly-pullback-20261103-a1/verification.json`:
  443 files, zero mismatches, terminal controller success and zero remaining GPU
  resources in its namespace.
- Health pullback: `results/workshop-health-pullback-20261103-a1/verification.json`:
  488 files, zero mismatches, terminal controller success and zero
  remaining Pods, ResourceClaims and DGDs in its namespace.
- Derived health data and input hashes: `results/workshop-health-analysis-20261103-a1/`.
- Both experiments verified correct responses, image/context/TP identity,
  zero restarts and real rank-0/rank-1 compiler-cache loads before acceptance.
