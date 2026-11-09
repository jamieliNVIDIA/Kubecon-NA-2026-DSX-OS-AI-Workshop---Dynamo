# Higher-load sweep: incomplete after C32 warmup restart

Verified November 6, 2026. The November 4 controller stopped after one completed
cell; eleven of the twelve requested measurements are unavailable. The model,
full corpus, C16/32/64/128 range and engine cap were not silently changed.

## Completed observation

One TP2 H100 worker, round-robin, C16 live AgentX trees, native 1M context,
compiled text-only and max-num-seqs 128. The original pinned runtime and corpus
were preserved. This is one workload observation, without a matched two-worker
or KV-routing arm.

| Observation | Value |
| --- | ---: |
| Valid successful requests | 307 |
| Request errors / context overflows / cancelled profile records | 0 / 0 / 0 |
| Mean active decode tokens/s/user | 112.43 |
| TTFT p50 / p99 | 251.93 ms / 3,807.45 ms |
| Server-reported prompt cache-read | 93.88% |
| Canonical aggregate output tokens/s | 173.78 |
| Canonical rate denominator | 1,200 s |
| GPU utilization, 900 s admission window | 89.46% / 88.52% |
| GPU samples | 180 per GPU |

The export is complete, uncancelled, scenario-valid and covers the required
profiling interval. The canonical rate includes the full drain window; it is
not a separately measured 900-second server-counter throughput. Health-check
behavior still needs qualification before treating this as an unperturbed
production capacity baseline. Higher utilization establishes activity at this
load, not saturation or the shape of a scaling curve.

## Failure chronology (November 4, PST)

- 17:59:43: detached controller starts.
- 18:10:25: CPU qualification and all four higher-load profile/cache checks pass.
- Approximately 18:19: higher-cap worker admission and bounded inference pass.
- 18:22:41–18:42:41: C16 profiling and drain; 307 valid requests.
- 18:43:50: C16 cell sealed as clean.
- Approximately 18:44:09: C32 snapshot-primer warmup begins, 32 primers sent.
- 18:47:07: 26/32 primers returned, six remain in flight.
- 18:47:08 onward: repeated `Health check timeout for generate` messages and
  HTTP 503 health responses. The engine logs 1 running / 172 waiting requests;
  waiting reaches 189 by shutdown. Queue entries cannot be assumed to correspond
  one-for-one to agent trees; the engine also receives health traffic.
- 18:47:28: worker receives a shutdown signal and unregisters its endpoints.
- 18:47:34: EngineCore termination and shutdown exceptions appear, followed by
  a native segfault stack. Kubernetes records exit 139 and restartCount 1.
- 18:47:55: the post-run worker qualification rejects the restart. No C32
  profiling result is accepted.
- 18:48:59: GPU cleanup passes; 18:49:04 the controller exits with failure.

The worker used canary wait 1 s / health-request timeout 180 s, liveness
`/live` every 5 s with failure threshold 3, and readiness `/health` every 2 s.
The sequence is consistent with a health/liveness interaction during long
prefill; it does not prove which component initiated shutdown. The later
segfault alone does not prove a GPU kernel crash or OOM caused the incident.
Resolve this distinction before selecting a fix or classifying C32 as a
hardware-capacity limit.

## Evidence and cleanup

`results/workshop-load-sweep-failure-pullback-20261106-a1/verification.json`
records **451 verified files**, zero transfer mismatches, all 37 C16 final-
inventory entries, successful local C16 analysis and no remote frozen-source
hash drift. `c16-analysis.json` contains the reconstructed metrics. The
`verified/` subtree contains controller/worker logs, current and previous
container logs, Pod termination state, complete C16 exports, profiles and specs.

`results/workshop-load-sweep-observations-20261104/status-20261106-01/` contains
the live audit and extracted failure chronology. The current namespace audit
finds zero worker Pods, ResourceClaims and DGDs. The remote GPU lease is absent;
the matching local controller reservation was released after evidence and
cleanup verification. The expired CPU client remains Failed; it cannot be used
to resume the campaign. No other workstream's resources or leases were changed.

The failed C32 path stopped at worker verification before raw AIPerf pullback,
and the client has since expired. Saved progress logs establish warmup activity;
they do not provide a valid C32 export or a completed performance point.

## Remaining work

Reproduce the C32 warmup/health behavior with the pinned model, full corpus,
128-sequence cap and saved probe configuration. Check canary scheduling and
load-sensitive liveness separately from engine execution failure. Any qualified
configuration change belongs in a new immutable run, consistently across all
three configurations. Keep the user-selected C16/32/64/128 matrix, retain this
failed attempt, and make no RR/KV or scale-out claim until matched arms exist.
