# Higher-load sweep status

Checked November 6, 2026. **Stopped with a worker restart: 1 of 12 points
completed.** The controller exited November 4 at **18:49:04 PST**; it is no
longer running. This supersedes the earlier launch-only status.

- CPU/model/image checks and admission at the 128-sequence cap passed.
- **One-worker RR, C16:** completed with 307 valid requests, zero request errors,
  overflows or cancelled profiling records. Mean decode 112.43 tokens/s/user,
  TTFT p50 251.93 ms / p99 3.81 s, canonical aggregate 173.78 tokens/s over a
  1,200 s exported phase window. Both GPUs averaged approximately 89% utilization
  during the 900 s admission window (180 samples each).
- **One-worker RR, C32:** failed during snapshot-primer warmup. Health checks
  timed out repeatedly, the worker received a shutdown signal, and Kubernetes
  recorded one restart with exit code 139. A segfault appears during shutdown.
  The log also shows a growing queue (172→189 waiting requests). This ordering
  suggests a health/liveness interaction under long prefill, but the initiating
  cause is not proved by the saved evidence.
- C64/C128 and **both two-worker configurations never ran**. No scale-out or
  RR-versus-KV performance result exists from this sweep.

The controller's no-restart qualification correctly stopped the campaign.
GPU cleanup is independently verified: zero owned worker Pods, claims or DGDs;
remote and local scoped reservations are released. One expired non-GPU client
Pod remains in Failed state. Other workstreams were untouched.

Collected and verified **451 files**, including all 37 C16 final-inventory
entries, with zero mismatches. The collected original analyzer successfully
reconstructed C16 locally. All frozen source hashes still matched remotely.
Evidence: `results/workshop-load-sweep-failure-pullback-20261106-a1/`.
See the [failure report](FAILURE_REPORT.md) for the restart chronology and limits.

Next work is to reproduce and resolve the C32 warmup/health interaction, then
start a fresh immutable run of the selected matrix. Do not silently resume a
partial curve or lower concurrency/context to obtain a passing result.

User-selected matrix: **C16, C32, C64, C128** live AgentX trees, each for:

- One TP2 worker with round-robin.
- Two TP2 workers with round-robin.
- Two TP2 workers with cache-aware routing.

Both comparisons use a common `--max-num-seqs 128`, with actual running/queued
request counts and cache pressure recorded. All other serving/workload controls
remain fixed. Workers are fresh per configuration and retained across ascending
load points; each profile has its normal fresh cache namespace and snapshot
primer. See the [frozen plan](PLAN.md).

This is twelve 15-minute profiles: **at least three hours of profiling**, plus
dataset qualification, model startup, snapshot primers, drain and collection.
These were the original execution estimates; the failed attempt stopped after
approximately 49 minutes and did not complete the matrix.

Evidence: `results/workshop-load-sweep-20261104-a1/`.
Controller: `kubecon-workshop-load-sweep-20261104-a1`, ID
`d4fcfdde299004ada02158e0997a02d4a6db7fd93614ff665feb27bf1694e3ae`.
Frozen plan SHA256:
`42eea491fc6251b9c9f7ae38ac3ef898c1fd46ccb94c49992a4930593f10a75d`.
49 source/payload files were verified at remote staging.

Scope: cp-0198/cp-0942 only, the same four explicit H100 UUIDs, a fresh namespace
`dynamo-ft-load-sweep-20261104-a1`, and separate reservation
`.local/workshop-load-sweep-20261104.gpu-lease/`. cp-0124 and the global lease
belong to other workstreams and are preserved. The live allocation check found
all four selected routing GPUs free before this launch.

The preceding C1/C4 routing campaign was stopped at the user's direction before
C4 profiling. Its GPU cleanup passed and **680 evidence files** were pulled back
and verified. Retain its C1 observation as a low-load diagnostic, not evidence
of serving capacity or scale-out benefit. Its obsolete CPU client was deleted
at 18:02 PST after verifying the exact Pod UID; this sweep uses a separate
fresh client.
