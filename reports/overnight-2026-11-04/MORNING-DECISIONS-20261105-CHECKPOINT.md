> Historical morning checkpoint, preserved before the November 5 afternoon reconciliation.
> Its pending/failed statuses describe that earlier checkpoint, not current readiness.
> See [current review questions](MORNING-DECISIONS.md) and [current results](REVIEW.md).
> The original document body follows verbatim. Original SHA-256: `867b499507df66ed8e489502eb5bd8ca2d13fff6a59cbb559b605ca578767ab5`.

# Decisions for the morning review

These are review prompts, not a replacement agenda. They describe the current
demo drafts and the evidence needed before choosing what to present live.

## Start with the audience-facing flow

Try the existing single-replica rehearsal, then the new metrics walkthrough
(`demos/09-agentx-metrics/run.sh --rehearsal`). Review ModelExpress, routing,
KVCR and disaggregation in the agreed teaching order; the directory numbers
reflect implementation order. Return to aggregated serving for request
continuity, Shadow and Snapshot.

All launchers support preview or rehearsal. Live preparation, fault injection
and cleanup must use the documented ownership and qualification gates.

## Questions worth settling

| Question | Current evidence / recommendation | What remains |
| --- | --- | --- |
| Which comparisons deserve projector time? | Routing 06 and metrics 09 have actual replay captures with source-verified values. Use them to explain behavior and metrics, without a capacity-speedup claim. | C16 is accepted and is the default recorded profile. C32 never profiled because model discovery raced readiness; no capacity knee is established. |
| What should the KVCR demo promise? | The new script isolates a shared coding prefix on A, then retrieval by B, with matched operations and external-cache tokens. This explains moving state to spare compute. | The live prompt was too short (3,247 tokens versus a 4,224-token hybrid page); B was never sent. Token-verify a longer common prefix before a fresh attempt. Pinning would isolate the mechanism, not automatic routing or load benefit. |
| Is Super VL Shadow ready for a live slot? | The candidate, safety gates and rehearsal exist. Related upstream drafts are identified, and their different validation stacks are explicit. | Real read-only write faults remain. The CPU-only writer prototype omits MoE helper locks; complete workspace coverage before another GPU test, then qualify reader/promotion separately. |
| Which Snapshot path should the presenter use? | Prefer the DGD-managed NVMe presenter once its own capture passes. It keeps the checkpoint's creating DGD alive and sends the coding request after readiness timing. The prior native demo remains available. | The artifact reached Ready but the held source Job expired before staging/restore. Fix durable offstage coordination and creation-time lifetime handling, then qualify the full presenter. The identity/offline bridge remains experimental. |
| How much continuity performance should we claim? | The paired C4 experiment passed: baseline 4/4 in both modes; after fault, enabled 4/4 versus disabled 2/4. Both affected enabled streams have their own peer-retry proof. | Functional continuity is qualified. Maximum inter-content gap is not an exact worker-handoff clock; no latency SLO or capacity recovery is qualified. |
| Does disaggregation need a live performance comparison? | Existing demo 03 already proves the actual P/D KV handoff. The new locked experiment compares equal four-GPU budgets. | Fresh CPU/cache/admission preparation passed; neither GPU arm started. Run both matched AgentX arms in a fresh bounded window. Use a neutral result honestly; specialization is a resource-management motivation, not a guaranteed speedup for this mix. |
| What can an attendee actually deploy afterwards? | The take-home renderer removes private placement, requests an explicit image/version/PVC, stages the exact checkpoint and checks a fresh HTTP response. | All 14 dry-runs passed. Select a publicly obtainable compatible runtime, document supported dependencies and qualify actual serving in the attendee profile. |
| When should the first deployment start? | The measured eager startup exceeds the six-minute deployment explanation slot. Rehearsals preserve startup timing before the first request. | Rehearse overlap with explanation or use prepared resources/recording. Do not shorten an observed startup clock by hiding preparation inside it. |

## A useful cloud-native finding from the failed sweep

The old C32 failure gives the overload slide a concrete Kubernetes connection:
an engine can continue processing long prefills while an inference canary waits
behind queued work. Liveness can then report failure even though the engine is
making progress, risking further capacity loss. The saved run shows that
sequence; it does not yet prove who initiated shutdown or that any proposed
health-check change fixes this exact configuration.

This could be a short operational example alongside rejection/admission policy.
It should remain an observed limitation with related upstream work, rather than
a claim that the current workshop runtime solves overload health checking.
Keep it within the agreed closing slide unless the user wants to expand it.

## Compare readiness of the deliverables

- **Reviewable locally:** new routing, metrics, KVCR, Shadow and DGD Snapshot
  presenters; controlled migration-load and equal-GPU P/D harnesses; portable
  take-home draft; independent review and upstream ledger.
- **Ready as recorded historical evidence:** routing 06 and metrics 09. Their
  normal-mode captures are intentionally labeled `recorded_evidence_passed`.
- **Still needs fresh cluster acceptance:** KVCR, Super VL Shadow, the integrated
  Snapshot presenter, P/D performance and attendee-profile serving. All owned
  GPU cleanup is verified; the paired C4 load experiment passed.
- **Separately owned:** general Snapshot destination context/offline fixes,
  which Neal is pursuing upstream. The NVMe mount harness remains local plumbing.

The external SSH/API outage is recorded separately from model/runtime defects.
Re-audit retained resources before resuming; do not turn an observation timeout
into a claim of a serving failure or silently rerun an immutable attempt.

The final status table and actual capture links are in [MORNING-REVIEW.md](MORNING-REVIEW.md).
