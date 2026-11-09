# Proposed matched router comparison extension

Requested by the outline workstream on October 30, 2026. This extension follows
the original RR scale-out plan and MX GPU handoffs. No extra GPU execution has
started; endpoint-resolved per-arm specs must be sealed separately.

Use the same model/image/tokenizer/dataset pins, native 1M context, TP2 H100,
four sequences per worker, and AgentX source patch as [PLAN.md](PLAN.md).
Keep the entire eligible 393-trajectory corpus, C1 and C4 session-tree limits,
seed 20261030, 900s profiles, 300s drain, canonical snapshot-primer warmup, fresh
benchmark-specific prefix namespaces, serial client preprocessing, and all other
generation/pacing settings unchanged. Do not select concurrency after observing
the RR results or tune routing weights.

For each preselected concurrency, run one dedicated paired repetition:

1. Start two fresh worker processes, qualify both GPUs per worker, use explicit
   round-robin routing, retain pre/post cache counters and mandatory primer, and
   run the frozen AgentX profile.
2. Stop both owned workers and confirm zero owned GPU claims. Start two fresh
   worker processes with identical configuration and placement constraints,
   change only the frontend's `--router-mode` from `round-robin` to `kv`, qualify
   KV-event consumption and worker visibility, retain the same primer/counters,
   and run the corresponding frozen AgentX profile.

Both arms keep the existing worker KV-event publisher configuration and block
size 64. Affinity headers remain disabled. Capture live routing choices and cache
events/counters where supported; worker distribution need not be even with KV
routing. Do not require two worker IDs from four sequential smoke requests for
the KV arm: affinity may intentionally select one worker. Instead verify both
workers are registered and eligible independently of the routing choices.

This adds four 900s profiles plus startup and drain. Fresh worker processes give
both arms initially empty GPU prefix caches before the same scenario warmup.
The original RR scale-out measurements remain operational scale-out results:
their first worker survives, so they are not the matched-cache RR baseline for
this router-policy comparison. Report fixed ordering, one repetition, realized
trace/request mix, actual concurrency, and uncertainty. A beneficial result is
not assumed.

The exclusive atomic GPU lease applies to every startup and profile. Offer MX
its agreed turns; release while lengthy CPU-only preparation is pending. A
failure preserves its spec and evidence without a router/model/workload swap.
