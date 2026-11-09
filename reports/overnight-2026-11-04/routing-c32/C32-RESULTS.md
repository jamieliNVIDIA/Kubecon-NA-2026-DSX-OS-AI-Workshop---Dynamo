# C32 AgentX routing: accepted pair and separate one-worker failure

**Update, November 8:** the one-worker arm was rerun with health canaries off
and completed cleanly; see the [one-worker results](../../workshop-measurements-20261030/agentx-c32-one-worker/RESULTS.md).
This report is unchanged below.

Two-worker RR and KV cells passed independent acceptance: **650 and 688 measured
requests, zero errors, overflows or canceled profile records**. KV routing
improved cache reuse and first-token tails; mean per-request decode speed was
slightly lower. The one-worker case failed during its mandatory primer and
cannot supply a throughput/latency scale-out comparison.

| Observation | Two TP2 workers, RR | Two TP2 workers, KV |
| --- | ---: | ---: |
| H100 GPUs | 4 | 4 |
| Successful measured requests | 650 | 688 |
| Aggregate output tokens/s | 500.12 | 525.23 |
| Output tokens/s/GPU | 125.03 | 131.31 |
| Mean decode tokens/s/user | 91.19 | 87.52 |
| TTFT p50, ms | 353.57 | 339.74 |
| TTFT p99, ms | 30,680.24 | 7,115.13 |
| ITL p50, ms | 10.97 | 11.20 |
| ITL p99, ms | 136.04 | 90.02 |
| Server-reported prompt cache-read, % | 85.04 | 88.88 |
| Canonical throughput denominator, seconds | 1,200.001 | 1,200.001 |

In this observation, KV routing increased aggregate output rate **5.0%** and
cache-read share **3.84 percentage points**. TTFT p99 fell from 30.68 to 7.12
seconds; mean decode speed per request fell **4.0%**, and median ITL was slightly
higher. This is useful evidence for the locality/load tradeoff, not a claim that
every latency measure improves. There were 688 routing selections and positive
total predicted prefix overlap, with current-worker event/discovery proof.

RR's two workers averaged 3.93 / 2.91 running requests. Their waiting-request
p99 values were 4 / 41, with maxima 7 / 52. KV averaged 2.90 / 3.82 running;
waiting p99 was 1 / 2, with maxima 2 / 3. KV occupancy remained low: means
approximately 3.7–5.0%, maxima approximately 10–14%. GPU utilization during the
900-second admission window averaged 96.8–98.9%. These observations show compute
and queue pressure; they do not establish a KV-capacity limit or maximum goodput.

## Controls and limits

The full pinned 393-trace AgentX corpus, seed, pacing and mandatory snapshot
primer were retained. Both profiles used the exact prior Super VL revision and
runtime, TP2, native 1,048,576 context, engine cap 128 and unchanged cache/kernel
settings. The new owned CPU client reconstructed and qualified its own cache;
the retained client handed to P/D was untouched. The exact-model frontend gate
passed before every cell; no startup model-list failure occurred in this run.

Root approved fixed order **two RR → two KV → one RR**, with fresh workers and
private compiler caches each time. This is N=1. Other tests used disjoint GPUs
but shared node CPU, EFS and network. Realized trace/turn mixes differ: mean
input/output lengths were approximately 109.6k/923 versus 111.7k/916 tokens.
Each p99 represents roughly six or seven requests. The 900-second admission
and 300-second drain gave approximately equal 1,200-second exported-rate
denominators. No measured request was canceled, although session replay reached
its bounded grace deadline. Completed requests are not completed coding tasks.

Do not splice this changed-order campaign with the separate C16 campaign into a
controlled capacity curve. There is no accepted one-worker C32 profile and no
eligible C32 scale-out ratio. Show the two-worker pair alongside its actual
tradeoffs, rather than presenting only the favorable p99 ratio.

## One-worker failure: liveness restarted a progressing engine

The exact model gate and four bounded smoke requests passed. During the
canonical C32 primer, the worker continued processing long prefills while
reporting one running request and a queue growing toward 187 requests. At
20:51:07 UTC, `generate` canaries began exceeding the configured 180-second
deadline. The engine still logged approximately 24–33k prompt tokens/s in nearby
samples, with KV usage around 1–3%.

The evidence now directly identifies the restart mechanism:

1. The exact Pod was `ft-agg-0-agg-lfjbf`, UID
   `4ce1e139-563d-4bf1-8d05-caa95e19f36b`.
2. Kubernetes recorded a readiness 503 at **20:51:08 UTC**.
3. At **20:51:20 UTC**, its `Killing` event explicitly states:
   `Container main failed liveness probe, will be restarted`.
4. The worker logged the shutdown signal at **20:51:20.456895 UTC**. Pod status
   records one restart and termination with `reason=Error`, `exitCode=1` at
   **20:51:27 UTC**. This is not evidence of an OOM kill.
5. Active primer streams returned service-unavailable errors, and AIPerf aborted
   with `warmup_failure`. Profiling never began for the one-worker cell.

The post-run zero-restart gate correctly rejected that arm. Its failed exports,
events and logs were preserved before rejection. The controller stopped at
**12:53:02 Pacific**, with scoped GPU cleanup verified. No retries or parameter
changes were made.

This strengthens the existing canary/liveness investigation linked in
[LOAD-SWEEP](../LOAD-SWEEP.md). The source mechanism for unbounded asynchronous
canaries remains a candidate explanation for queue amplification; not every
queued request was individually attributed to a canary. Existing upstream
work on busy-aware health and separating liveness/readiness should be reviewed
before proposing duplicates.

A secondary AIPerf cleanup issue is also retained: after aborting during warmup,
the JSONL writer logged `file handle is not open` and failed to flush an unopened
profiling export. It did not initiate the runtime failure. A regression test for
warmup-abort cleanup would be useful before proposing a patch.

## Evidence, text output and cleanup

- [Machine-readable metrics, source hashes and exact failure lines](C32-results.json).
- Full local snapshot: `results/workshop-routing-c32-collection-terminal-20261105-a2/`.
- All **883 transported files** and **48 frozen payload sources** independently verified.
- Archive SHA256: `627bb755504b60f085b21bd11998eff1bb3add6f2bf79ebfb32330b1fb42f3ee`.
- Analysis SHA256: `6eea304516aca77dea3a866996364ada9bf21fc0f153566965b9af991d0e1cf2`.

The original raw AIPerf console text is retained under each collected cell's
`raw/<arm>/console.log`; both successful cells have complete JSON/JSONL and
server-metric exports. These are benchmark logs, not a new presenter main-panel
recording. The existing C16 demo-06 capture remains independently valid. A C32
presenter import must freeze this new pair and label the failed one-worker case
separately, retaining the lower mean decode-speed observation.

Final remote cleanup and root's recovered live inventory agree: zero routing
GPU claims/DGDs/workers. The CPU client remains retained as UID
`dcad92cf-6dd9-4d1b-a760-8147191f8c0e`. The independent acceptance/cleanup receipt
recommends releasing only this controller's local reservation after parent
acknowledgement; this offline verifier changed no reservation or cluster resource.
