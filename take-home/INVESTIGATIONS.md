# Continue the investigation

Keep the coding-agent workload and model identity fixed. Each change should
answer one operational question; keep configuration, offered load, cache history
and measurement boundaries alongside the result. The presenter launchers use
private workshop preparation and are references, not portable attendee commands.

| Question | Experiment and evidence | Workshop reference |
| --- | --- | --- |
| What changes as more agents arrive? | Use the same pinned AgentX trace and vary offered session-tree concurrency. Record actual engine running/waiting requests, aggregate tokens/s/GPU, per-user generation speed and TTFT. Session trees are not equivalent to simultaneous HTTP requests. | [Workload semantics](../reports/workshop-measurements-20261030/agentx-workload/README.md) and [load-sweep status](../reports/workshop-measurements-20261030/load-sweep/STATUS.md) |
| Why is a second replica slow to appear? | Measure matched storage loading versus ModelExpress peer loading. Keep image, model, engine flags and target hardware fixed. Separate tensor-copy, model-loading and Ready clocks. | [ModelExpress demo](../demos/modelexpress/README.md) |
| Does another replica help this workload? | Compare one worker and two workers, then compare RR and cache-aware routing with matching load and cache policy. Routing needs worker cache events and capacity information. Do not derive a speedup from dissimilar request mixes. | [Scaling outline](../WORKSHOP_OUTLINE.md#23-two-replicas-cache-aware-routing) |
| Can useful cached context move to idle compute? | Seed a prefix on A, confirm B lacks it, request on B, then require matching transfer blocks/bytes and external-cache tokens. Successful output alone could be recomputation. | [KVCR qualification](../reports/workshop-kvcr-guard-qualification.md) |
| Why specialize workers? | Split prefill/decode and establish the NIXL handoff using worker IDs and transfer counters. A performance claim additionally needs matched total GPU resources and workload. | [Disaggregation demo](../demos/disaggregated/README.md) |
| What happens to the response when a worker dies? | First establish two healthy workers. Inject one identified EngineCore failure during a streaming response and compare migration disabled/enabled. Preserve the original frontend/client stream and trace each backend attempt. | [Request-continuity demo](../demos/request_continuity/README.md) |
| How quickly does serving capacity return? | Measure GMS/Shadow promotion and standby replenishment separately from request survival. Prove shared weight identity and unchanged GMS/Pod, then inject one controlled process failure. Super VL startup/promotion remains a separate qualification gate. | [Shadow findings](../reports/2026-10-15-super-vl-tp2-retest.md#shadow-startup-retry) |
| What must be rebuilt when the Pod disappears? | Prime an automatic Snapshot while preserving its creating DGD, delete only its worker Pod, and establish a distinct restored Pod plus fresh inference through the same frontend. Local storage covers compatible same-node placement. | [DGD Snapshot qualification](../reports/workshop-snapshot-dgd-nvme.md) |

These are separate qualifications. Request migration can rebuild cache from
retained tokens; Snapshot restores initialized engine state; GMS/Shadow restores
process capacity; KVCR-Guard can preserve committed host-cache data. A working
component does not establish that the combined path works, preserves every
request, or meets an SLO.

The current portable bundle implements only the first deployment. Portable
ModelExpress/routing/KVCR/disaggregation/recovery overlays need selected public
runtime/artifact pins and independent validation before becoming attendee
copy-and-run exercises. Avoid expanding into Planner, autoscaling, KAI or
multitenancy: manual scale changes are sufficient to investigate this workshop's
questions.
