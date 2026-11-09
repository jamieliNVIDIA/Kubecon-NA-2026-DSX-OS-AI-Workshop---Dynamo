# Frozen topology-first AgentX retry

Fresh namespace/run: `dynamo-ft-routing-overnight-20261105-a1` /
`results/workshop-routing-overnight-20261105-a1`.

Run C16 one-RR, two-RR, two-KV, then the same three C32 cells. Each cell uses
fresh workers/private compiler caches, bounded model/discovery smoke and the
mandatory canonical AgentX primer. Do not change attempted input files.

The prior C32 failure is retained separately. Preserve max-num-seqs 128,
native 1,048,576 context, 8,192 batched tokens, prefix caching, memory fraction
0.85, text-only compiled Super VL TP2, the exact runtime/model/AgentX corpus
and replay settings. The model/image/data source pins are in campaign.json.
Admission is 900 seconds plus up to 300 seconds drain; C is live session-tree
concurrency, not HTTP concurrency. No health or restart acceptance relaxation.

Use only the original routing GPU0+2 UUID pairs on cp-0198 and cp-0942. The
fresh scoped lease is `.local/overnight-routing-sweep.gpu-lease`; no global
cluster-idle prerequisite or cleanup. Other assigned GPU tests share node
CPU/EFS/network and must be disclosed in the comparison.

Require endpoint health and exact worker identity/configuration/allocation,
zero restarts, actual current-Pod discovery and event sources, full raw exports,
realized workload/phase/drain records, queue/cache/GPU/client telemetry. Do not
present failed/censored cells as clean latency speedups or SLO evidence.
Stop the controller on an infrastructure/engine/collection failure. Completed
C16 cells remain useful even if a later C32 cell fails. A controller's success
means execution and scoped cleanup; every comparison retains per-cell gates.

No peak-capacity claim, no universal routing gain, N=1 fixed topology-first
order. New cache histories and concurrent background activity preclude
combining these points with earlier low-load pilots as one controlled curve.
