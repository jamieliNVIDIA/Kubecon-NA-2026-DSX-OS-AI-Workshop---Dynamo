# AgentX C32 one-worker cell: results

The one-worker arm that failed on November 5 now has a clean score. On
November 8 it ran with health canaries off: **602 measured requests, zero
errors, context overflows or cancellations, and no worker restart.** The
mandatory primer completed all 32 of its requests in 331 s. The original
attempt was restarted by liveness during that phase.

| AgentX C32 | One TP2 worker, RR | Two TP2 workers, RR | Two TP2 workers, KV |
| --- | ---: | ---: | ---: |
| Run | November 8, canaries off | November 5 | November 5 |
| H100 GPUs | 2 | 4 | 4 |
| Successful measured requests | 602 | 650 | 688 |
| Aggregate output tokens/s | 464.25 | 500.12 | 525.23 |
| Output tokens/s/GPU | 232.12 | 125.03 | 131.31 |
| Mean decode tokens/s/user | 61.87 | 91.19 | 87.52 |
| TTFT p50 | 297 ms | 354 ms | 340 ms |
| TTFT p90 / p95 / p99 | 1.15 / 2.04 / 9.51 s | 2.67 / 11.50 / 30.68 s | 1.83 / 2.75 / 7.12 s |
| Turn latency p50 / p90 / p99 | 5.2 / 43.7 / 193.5 s | 3.8 / 35.2 / 132.9 s | 4.1 / 29.3 / 128.8 s |
| Running requests, mean per worker | 8.0 | 3.93 / 2.91 | 2.90 / 3.82 |
| Waiting requests, max per worker | 7 | 7 / 52 | 2 / 3 |
| Server-reported prompt cache read | 93.4% | 85.0% | 88.9% |

The two-worker columns are the accepted [C32 pair](../../overnight-2026-11-04/routing-c32/C32-RESULTS.md).
Turn latency runs from request to last token over all measured requests. Every
cell's exported rate uses a 1,200-second denominator (900 s admission, 300 s
drain).

## What it shows

- **A second worker raised decode speed and throughput with either router.**
  Mean decode speed per user rose 47% with round-robin and 41% with KV routing;
  aggregate output rose 8% and 13%. One worker was not saturated at C32: it
  averaged 8 running requests and never queued more than 7.
- **Round-robin made the first-token tail worse than one worker.** At p95,
  first tokens took 11.5 s against 2.0 s on one worker; at p99, 30.7 s against
  9.5 s. One round-robin worker queued up to 52 requests while the other never
  held more than 7: round-robin splits requests evenly, not work.
- **KV routing kept the tail near one worker's.** Its queues never exceeded 3.
  TTFT p95 was 2.75 s against one worker's 2.04 s, and p99 was 7.1 s against
  9.5 s. Splitting sessions across two caches cost some reuse (88.9% against
  93.4%), which shows at p90 and p95.
- **Turn latency improved with both, more with KV.** p90 fell from 43.7 s to
  35.2 s with round-robin and to 29.3 s with KV routing. AgentX answer lengths
  vary, so turn latency mixes answer length with service time; the first token
  is where routing shows.

The C16 cells showed the same order (TTFT p99 3.8 s on one worker, 15.4 s with
round-robin, 5.2 s with KV routing), as does the synthetic campaign's
128-agent tail ([RESULTS](../synthetic-scaleout/RESULTS.md)).

## Controls and limits

- Same model and revision, runtime image, TP2, native context, engine cap 128,
  batching and cache flags, and the byte-identical C32 profile (corpus, seed,
  pacing, primer, admission, drain) as the November 5 pair. `freeze()` diffed
  the manifest against the C32 one-worker manifest. It differs only in node,
  GPU selector and health environment ([reference differences](../../../results/workshop-agentx-c32-one-worker-20261108-a1/reference-differences.json)).
- **Two differences from the pair.** This cell ran without the 1 s health
  canary (the user's November 7 decision) and on cp-0942 GPU0/2, which was the
  pair's second-worker GPUs. The original pair, cp-0198 GPU0/2, was held by the
  presenter MX target. It also ran three days later, with fresh workers, so
  realized trace mixes differ.
- N=1 per cell. Each p99 is about six requests, and p95 about thirty.
  Completed requests are not completed coding tasks.

## Evidence

- Collection: `results/workshop-agentx-c32-one-worker-collection-final`
  (362 files; archive SHA256 `4e0ba722a19555a8e872eca9d005fff441b01e2e71a5ee18e674b96e984bb458`).
- Comparison: `results/workshop-agentx-c32-one-worker-collection-final/comparison.json`, from
  [`compare.py`](compare.py), which applies the C32 report's own cell analysis.
- Controller exit 0 at 09:43:58 UTC, "Completed, accepted and cleaned". The
  cleanup receipt shows no worker Pods, ResourceClaims or graphs, and the
  namespace was confirmed empty afterwards. The local reservation marker is
  released.

```bash
.local/venv/bin/python -B reports/workshop-measurements-20261030/agentx-c32-one-worker/compare.py \
  --one results/workshop-agentx-c32-one-worker-collection-final/verified/results/workshop-agentx-c32-one-worker-20261108-a1/one-rr-c32-a1 \
  --output results/workshop-agentx-c32-one-worker-collection-final/comparison.json
```
