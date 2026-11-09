# Synthetic scale-out and routing: results

All eight planned cells completed cleanly: **zero request errors, zero worker
restarts, and every output exactly 650 tokens**. One-worker cells at 32 and 128
agents come from a2. a3 reran 1W-64 as a bridge (953 versus 948 output tok/s,
22.5 versus 22.7 TPS/user) and ran every two-worker cell, scaling the same first
worker's deployment from one replica to two.

The load is synthetic AIPerf user-centric traffic shaped like coding agents,
never AgentX. Each agent sends one turn of a 12-turn session every 45 s, about
80K prompt tokens per request including a 32K shared system prompt, and exactly
650 output tokens. Workers are Nemotron 3.5 Super VL 120B-A12B NVFP4 at TP2 on
H100s, engine cap 128, health canaries off, router defaults.

Values cover the 180–540 s window of each 540 s profile. Throughput counts
requests that completed in the window. TPS/user (AIPerf
`output_token_throughput_per_user`, mean), TTFT and cache reads cover requests
that started in it.

| Cell | GPUs | Agents | Output tok/s | TPS/GPU | TPS/user | TTFT p50 | TTFT p90 | Cache read | Achieved / offered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1W-32 (a2) | 2 | 32 | 460 | 230 | 76.3 | 0.37 s | 0.65 s | 88.7% | 1.00 |
| 1W-64 (a3) | 2 | 64 | 953 | 477 | 22.5 | 0.53 s | 1.48 s | 89.0% | 1.03 |
| 1W-128 (a2) | 2 | 128 | 1,038 | 519 | 9.3 | 0.96 s | 49.2 s | 78.9% | 0.56 |
| 2KV-32 | 4 | 32 | 460 | 115 | 123.0 | 0.46 s | 1.61 s | 80.6% | 1.00 |
| 2KV-64 | 4 | 64 | 923 | 231 | 54.3 | 0.55 s | 1.60 s | 81.7% | 1.00 |
| 2RR-64 | 4 | 64 | 923 | 231 | 73.8 | 0.39 s | 1.28 s | 87.4% | 1.00 |
| 2KV-128 | 4 | 128 | 1,766 | 442 | 16.0 | 1.35 s | 4.44 s | 84.3% | 0.96 |
| 2RR-128 | 4 | 128 | 1,313 | 328 | 19.7 | 1.38 s | 7.85 s | 77.4% | 0.71 |

Offered output is 462, 924 and 1,849 tok/s at 32, 64 and 128 agents.

## Same agents, one worker versus two

- **Below one worker's limit, throughput follows demand.** At 32 and 64 agents
  one worker already delivered everything offered, so a second left output
  tok/s unchanged (460 → 460; 953 → 923) and halved TPS/GPU. The added GPUs
  went into per-user speed: **76 → 123 TPS/user at 32 agents (+61%)** and
  **22.5 → 54.3 at 64 agents (2.4×)**. One worker at 64 agents kept pace but
  was past its knee by latency: TTFT p90 2.3× its 32-agent value, about 44
  running and up to 28 waiting requests.
- **The second worker cost cache locality.** With KV routing at 32 agents, 37%
  of later turns ran on a worker missing some or all of the session's previous
  context (below). Cache reads fell from 88.7% to 80.6%, uncached prompt tokens
  per request rose from 9.1K to 15.6K, and TTFT p90 rose from 0.65 to 1.61 s.
  This matches AgentX C4: cache reads 95.8% → 90.7%, TTFT p50 306 → 478 ms,
  mean decode speed +8.4%.
- **Past one worker's limit, the second worker adds throughput.** At 128 agents
  one worker served 56% of offered load at 1,038 tok/s with TTFT p90 49 s. Two
  KV workers served 96% at **1,766 tok/s (1.70×)**, TTFT p90 4.4 s and TPS/user
  9.3 → 16.0. Two round-robin workers served 71% at 1,313 tok/s (1.26×).

## Twice the agents on twice the GPUs

| KV routing | 1W-32 → 2KV-64 | 1W-64 → 2KV-128 |
| --- | ---: | ---: |
| Output tok/s | 460 → 923 (2.00×) | 953 → 1,766 (1.85×) |
| TPS/GPU | 230 → 231 | 477 → 442 (−7%) |
| TPS/user | 76.3 → 54.3 (−29%) | 22.5 → 16.0 (−29%) |
| TTFT p90 | 0.65 → 1.60 s | 1.48 → 4.44 s |

Throughput doubled with the GPUs; per-user speed did not hold under the default
KV router. 2RR-64, which kept sessions in place (below), held 73.8 TPS/user, 3%
below 1W-32.

## Routing and where sessions ran

AIPerf does not record the serving worker, so [`analyze.py`](analyze.py)
classifies each later turn from cache reuse: the session's previous-turn prompt
minus this turn's cache hit. In one-worker cells at 32 and 64 agents that never
exceeded 4,222 tokens. Under 5,000 is **current**; 5,000–20,000 is **stale**, an
older copy missing recent turns (one turn adds about 4,650); over 20,000 is
**cold**, little beyond the shared prompt.

| Later turns in window | Current | Stale | Cold | Uncached prompt tokens / request |
| --- | ---: | ---: | ---: | ---: |
| 1W-64 | 100% | 0% | 0% | 8,765 |
| 2KV-32 | 63.5% | 21.0% | 15.5% | 15,635 |
| 2KV-64 | 63.1% | 24.7% | 12.2% | 14,639 |
| 2RR-64 | 92.7% | 4.7% | 2.6% | 10,086 |
| 2KV-128 | 86.7% | 5.1% | 8.2% | 12,360 |
| 2RR-128 | 54.0% | 28.1% | 17.9% | 17,147 |
| 1W-128 | 83.7% | 0.2% | 16.1% | 15,018 |

1W-128's cold turns are sessions evicted from one worker's cache under load; it
recorded no preemptions.

**Round-robin at 64 agents was accidental session affinity.** Every agent sends
its next turn exactly 45 s after the last, so at 64 agents the arrival order
repeats each cycle. With 64 requests per cycle, strict alternation returns each
agent to the same worker. The parity of the request count between an agent's
consecutive turns predicted placement: all 424 turns it predicted to stay were
current. At 128 agents responses overran the gap (turn gaps median 54 s, p95
117 s), parity predicted the same worker for 50.5% of turns, and round-robin
behaved as round-robin. 2RR-64 is therefore not a cache-oblivious baseline. It
also fails the plan's expectation that round-robin reuse fewer prompt tokens
than KV (87.4% versus 81.7%). Do not present it as round-robin beating KV. It is
a reference for sessions held in place with even load (384/384 requests).

**At light load the default KV router moved sessions often.** At 32 and 64
agents, 36–37% of later turns ran away from their latest context, with 75% mean
predicted overlap across routing decisions. Recomputing those contexts raised
whole-profile prefill time from 422 s (2RR-64) to 569 s (2KV-64) and ITL p50
from 13.8 to 18.9 ms, so TPS/user fell to 54.3 against 73.8. A hypothesis,
untested here: one running ~80K-token request adds about as many active KV
blocks as a session's cached prefix saves, so small load differences outweigh
locality under the default cost function. A 2KV-64 cell with a higher overlap
weight would test it.

**Near the limit, KV routing kept sessions in place and won.** At 128 agents
KV kept 86.7% of later turns current against round-robin's 54.0%. It served 96%
of offered load against 71% and delivered **1,766 against 1,313 tok/s (+35%;
442 against 328 TPS/GPU)**, with TTFT p90 4.4 against 7.9 s and p99 7.9 against
22.6 s. Round-robin's per-user mean was higher (19.7 against 16.0) because it
admitted fewer requests: 725 against 978 started in the window.

## End-to-end latency at 128 agents

Turn latency from request to last token, over requests started in the window;
none were canceled.

| 128 agents | One worker | Two, round-robin | Two, KV |
| --- | ---: | ---: | ---: |
| Turns started in window | 575 | 725 | 978 |
| E2E p50 | 68.0 s | 45.1 s | 45.9 s |
| E2E p90 | 140.2 s | 113.0 s | 53.8 s |
| E2E p99 | 169.1 s | 127.6 s | 58.0 s |
| TPS/user p10 | 5.1 | 6.8 | 12.5 |
| TPS/user mean | 9.3 | 19.7 | 16.0 |

Either router cut the median turn by a third. The slowest tenth differed:
round-robin cut E2E p90 by 19% and KV routing by 62%, while KV also completed
35% more turns. Round-robin splits requests evenly, not work: its two workers
averaged 61.5 and 41.4 running requests over the profile, with 3,043 and 1,543 s
of summed engine queue time; KV's averaged 55.2 and 55.4. Mean TPS/user favors
round-robin because it excludes queueing and first-token time: round-robin
admitted fewer turns, so fewer shared each decode batch. At a fixed agent count,
compare routers on end-to-end latency or completed turns, not decode speed
alone. This is one run, and which worker falls behind is not predictable.

## AgentX calibration

2KV-32 against the accepted [AgentX two-worker KV C32](../../overnight-2026-11-04/routing-c32/C32-RESULTS.md):
460 against 525 output tok/s (115 against 131 per GPU), TPS/user 123 against 88,
TTFT p50 463 against 340 ms, cache reads 80.6% against 88.9%. Synthetic 32
agents ran about two requests per worker against AgentX C32's three to four, so
synthetic agent counts are not AgentX concurrency levels. Use the synthetic
cells for the shape of the scale-out answer and AgentX for real-workload values.

## Controls and limits

- N=1 per cell, fixed order, persistent workers: a3 deployed once and scaled
  one replica to two, and worker 1 kept its UID. All cells ran on cp-0942.
  KVCR requalification loaded models on other nodes during 2KV-64, 2RR-64 and
  2RR-128 ([STATUS](STATUS.md)).
- a2 and a3 are separate deployments with identical manifests apart from the
  removed anti-affinity rule; the 1W-64 bridge agrees within 0.6% on
  throughput and 1% on TPS/user.
- Whole-run AIPerf summaries include the cold first turns and differ from the
  window; 1W-128, for example, is 750 tok/s whole-run against 1,038 in the
  window. Compare window values.
- Arrivals are smooth and periodic, with no bursts or subagent trees. Placement
  is inferred from cache reuse, not router logs. GPU utilization was 98–100% in
  every cell, so it does not indicate load here.

## Use in the talk

- **Why didn't more capacity help?** At 64 agents one worker already served all
  demand, so two KV workers gave 953 → 923 tok/s and TPS/GPU 477 → 231, but
  TPS/user 22.5 → 54.3. The capacity went into speed, not throughput. The
  32-agent pair repeats AgentX C4: TTFT p90 0.65 → 1.61 s, with 37% of turns
  away from their context.
- **When does it raise throughput?** At 128 agents: 1,038 → 1,766 tok/s, 56% →
  96% of demand served, TTFT p90 49 → 4.4 s.
- **Routing:** the 128-agent trio. Slowest tenth of turns: 140 s on one
  worker, 113 s with round-robin, 54 s with KV routing; the median is about
  45 s for either router. Do not use 2RR-64 as a round-robin result.
- **In the deck:** the Router section opens with "Why didn't more capacity
  help?" (`Kubecon Slides/build/extras.py`, `r1_capacity`), which shows these
  four bars and then the [AgentX C32 one-worker result](../agentx-c32-one-worker/RESULTS.md).

## Evidence

[`STATUS.md`](STATUS.md) records the attempts. The collections are
`results/workshop-synthetic-scaleout-collection-a2-final` and
`results/workshop-synthetic-scaleout-collection-a3-final`; the latter's
`analysis.json` covers both:

```bash
.local/venv/bin/python -B reports/workshop-measurements-20261030/synthetic-scaleout/analyze.py \
  --run results/workshop-synthetic-scaleout-collection-a2-final/verified/results/workshop-synthetic-scaleout-20261107-a2 \
  --run results/workshop-synthetic-scaleout-collection-a3-final/verified/results/workshop-synthetic-scaleout-20261107-a3 \
  --output results/workshop-synthetic-scaleout-collection-a3-final/analysis.json
```
