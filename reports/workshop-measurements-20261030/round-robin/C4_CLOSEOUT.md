# C4 scale-out closeout

**Complete, November 4, 2026.** The original one-worker/two-worker C4 evidence
is collected and rechecked locally. No benchmark was rerun. The recomputed
analysis exactly matches the accepted remote analysis, apart from the export's
new local file location. Both raw archives and all their extracted files match.

| Observation | One TP2 worker / 2 H100s | Two TP2 workers / 4 H100s |
| --- | ---: | ---: |
| Successful measured requests | 122.0 | 114.0 |
| Output tokens | 97,394.0 | 90,369.0 |
| Canonical aggregate output tokens/s | 81.16 | 75.31 |
| Mean active-generation tokens/s/user | 139.79 | 151.52 |
| TTFT p50 | 306.19 ms | 477.59 ms |
| TTFT p99 | 2150.72 ms | 5238.63 ms |
| Server-reported cache-read share | 95.79% | 90.72% |
| Canonical throughput denominator | 1,200 s | 1,200 s |
| Profiling main / subagent / flat requests | 61 / 60 / 1 | 56 / 57 / 1 |
| Source trace IDs sampled | 5 | 4 |
| Dynamo worker request counts | 122 | 57 / 57 |
| GPU utilization during 900 s admission | 65.42–65.46% | 35.47–37.22% |
| Samples per GPU during admission | 180 | 180 |
| Children spawned / completed / truncated | 6 / 2 / 1 | 3 / 2 / 0 |
| Agent graphs completed to end | 0 | 0 |

Adding the replica increased mean active-generation speed **8.4%**, while the
canonical aggregate output rate fell **7.2%**, TTFT increased and cache-read
share fell **5.08 percentage points**. The same configured load produced a
different realized turn mix. This is an operational illustration of why replica
count alone does not determine user experience; it does not isolate cache
locality's causal effect, establish maximum capacity or measure RR/KV benefit.

## Acceptance and provenance

- **142 files** transferred and verified, **zero mismatches**. The final arm
  inventories contain **33 and 35 files**; every named file, including each
  original `raw-artifacts.tar.gz`, is present. Original intermediate inventories
  and the first-arm recovery / successful second-arm stage inventories also pass.
- Both embedded raw archives contain **14 regular files**, each byte-identical
  to its collected extracted counterpart. Nothing was selectively omitted.
- Both AIPerf exports report complete, uncancelled, valid submissions, positive
  request counts and no request errors, context overflows or cancelled profiling
  records. Both arms passed the unchanged original analyzer's acceptance checks.
- Normalized workload profiles match. Model/revision/image, corpus revision/hash,
  AIPerf commit/patch, native 1,048,576 context, four sequences per worker,
  preprocessing and C4 session-tree semantics match the frozen specifications.
  Worker UIDs, image digests and zero restarts match captured Pod evidence.
- Original worker `66649d97-fd14-4054-be3f-7aa55d7f2215` survived scale-out.
  New worker `9ca3405c-f058-49d7-8372-9008aba80745` served half of the measured
  two-worker requests. Exact worker IDs/endpoints, trace IDs/offsets, branch
  counters and per-GPU statistics are retained in the recomputed analysis.
- C4's stage exited **zero** and verified zero owned GPU Pods, ResourceClaims,
  DGDs and no stage GPU lease. The closeout's fresh read-only namespace audit
  also found no GPU resources. The expired, failed non-GPU client Pod is retained.
- The enclosing controller and later continuation exited **one** at the C1 KV
  guard. Those failure receipts are preserved. C4 success does not relabel that
  queue or either routing-policy pair as successful.

## Interpretation limits

This is one fixed-order pair: 900 s request admission plus a 300 s grace bound.
The first profile continued cluster-side through a laptop tunnel outage; it was
recovered unchanged, not replayed. The second arm followed a network-recovery /
initialization pause and a change to the stable controller. The original worker
and cluster-side client were retained. Initial worker cache occupancy can differ.

The full pinned corpus was available; only the source requests counted above
were measured. C4 denotes configured live session-tree concurrency, not four
HTTP requests at every instant. Branch counters and completed replay sessions
do not prove completed coding tasks. No complete agent graph finished here.

The serving profile predates the newer `--language-model-only` startup baseline.
It serves text requests but retains multimodal capability; do not relabel this
closeout as a new text-only benchmark or combine it with the MX startup matrix
as one matched experiment. GPU samples cover admission rather than the entire
grace period. Canonical throughput and derived request-span throughput remain
separately named metrics; per-user active-generation speed excludes TTFT.

## Artifacts

- Complete verified tree: `results/workshop-c4-closeout-20261104-a1/verified/`.
- Transfer and nested-inventory receipt: `results/workshop-c4-closeout-20261104-a1/verification.json`.
- Recomputed analysis and workload/GPU CSVs: `results/workshop-c4-closeout-20261104-a1/analysis/`.
- Exact original analysis: `verified/results/workshop-rr-20261103-resume02/scaleout-c4-a1-analysis.json` under the closeout.
- Pullback archive SHA256: `e5c12c71ae17aec4d3cc8f1791be30b91d3d8f35aba983d843e6fcc933f9bad6`.
- [Collection plan](C4_CLOSEOUT_PLAN.md), [main measurement report](REPORT.md),
  [separate routing failure diagnosis](KV_DISCOVERY_DIAGNOSIS_20261104.md).

Older partial local mirrors and all original inventories remain unchanged.
The new verified tree is the authoritative complete local C4 copy. This task
performed remote reads and local analysis only; it changed no leases or cluster
resources and did not schedule the still-outstanding routing comparison.
