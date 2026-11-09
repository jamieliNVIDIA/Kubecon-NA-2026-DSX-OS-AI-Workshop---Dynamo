# AgentX C16 scaling and routing results

Collected and independently accepted November 5, 2026, after VPN recovery.
All three C16 cells passed exact input, worker/GPU identity, discovery, raw
artifact integrity and submission checks. The controller stopped on a startup
readiness race before C32 profiling; there are no C32 measurements.

| Observation | One TP2 worker, RR | Two TP2 workers, RR | Two TP2 workers, KV |
| --- | ---: | ---: | ---: |
| H100 GPUs | 2 | 4 | 4 |
| Successful measured requests | 303 | 316 | 311 |
| Request errors / context overflows / canceled profile records | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Aggregate output tokens/s, exported score | 170.92 | 175.55 | 174.09 |
| Output tokens/s/GPU | 85.46 | 43.89 | 43.52 |
| Mean decode tokens/s/user | 112.63 | 133.60 | 137.49 |
| TTFT p50, ms | 258.98 | 295.39 | 261.28 |
| TTFT p99, ms | 3,814.82 | 15,403.99 | 5,172.53 |
| ITL p50, ms | 9.11 | 7.26 | 6.81 |
| ITL p99, ms | 17.07 | 21.41 | 16.35 |
| Server-reported prompt cache-read, % | 93.87 | 87.15 | 91.03 |
| Canonical throughput denominator, seconds | 1,200.002 | 1,200.003 | 1,200.002 |

Adding a second RR worker increased the exported aggregate rate only 2.7%,
while mean decode speed rose 18.6%. Cache reuse declined and TTFT tails worsened.
On the same two-worker topology, KV routing raised cache-read from 87.15% to
91.03%, reduced median TTFT from 295 to 261 ms, and reduced this observation's
p99 from 15.40 to 5.17 seconds. Aggregate throughput was effectively flat.
There were 311 routing observations with positive total predicted prefix
overlap, alongside current-worker discovery/event evidence.

These results support explaining the tradeoff; they do not establish a universal
speedup or a capacity knee. C counts live AgentX trees, including pacing and
parallel descendants, rather than active HTTP requests. The one-worker profile
averaged 1.61 running requests, with median 1 and maximum 7; its waiting-request
median and p99 were zero. Median running requests on the two-worker profiles
were 0–1 per worker. GPU admission-window utilization averaged about 89% on the
one-worker pair and 63–69% on the two-worker pairs; utilization alone does not
establish hardware saturation. Full pressure series remain in the JSON.

## Controls and limits

The full pinned 393-trace AgentX corpus, model/revision, runtime, TP2, native
context, engine cap 128, cache/kernel settings and canonical snapshot primers
were preserved. Each cell began with fresh worker processes and private compiler
caches. Admission was 900 seconds with a 300-second drain; the exported scores
used approximately 1,200-second windows. No measured request was canceled,
although replay session completion waited until the bounded grace deadline.
Completed inference requests do not imply completed coding tasks.

This is N=1 in fixed order with concurrent tests on disjoint GPUs sharing node
CPU, storage and network. Realized request counts and trace/turn mixes differ.
Mean input/output lengths were approximately 106.5k/677, 107.3k/667 and
107.7k/672 tokens. The p99 populations are only about three requests in each
cell; show the tail numbers as this experiment's observation, not a stable
production percentile or an SLO guarantee. Cache-read is server-reported reuse,
separate from theoretical structural prefix reuse.

## C32 failure and follow-up

The new C32 attempt did not reproduce the older overload crash: it stopped
before any profiling request at a one-shot `/v1/models` assertion. The worker
was Ready with zero restarts. The smoke command began at 08:56:37.875626 UTC;
the frontend logged its HTTP 200 at 08:56:38.039326, then committed the expected
discovered model group at 08:56:38.167468, about 128 ms later.

The harness should wait for the exact expected model ID at the frontend before
its four bounded smoke requests. A fresh retry can add this gate while keeping
the workload/engine controls. Preserve this failed attempt. There is no need
to infer a general upstream model-registration defect from an eventually
consistent startup boundary; documenting worker-ready versus model-servable
readiness would be useful.

## Evidence and cleanup

- [Machine-readable observations and source hashes](C16-results.json).
- Local full collection: `results/workshop-routing-overnight-collection-recovered-20261105-0739/`.
- 1,040 transported files and all 47 frozen payload sources independently verified.
- Archive SHA256: `d0524b4a44602a361b243bb0fdbd8031db39c178625de445383c4f3afb32c8fe`.
- Analysis SHA256: `f01d4a62c909176207eb162a6c2baf4de9b52abac74fed5dbe0175e96152bf12`.

The controller exited at 00:56:51 Pacific. Its final scoped cleanup receipt,
remote reservation absence and the recovered live namespace inventory agree:
zero routing GPU claims/DGDs/workers. Only the exact owned local reservation
was released, with owner and acceptance/release receipts preserved beside the
collection. No cluster workloads were changed during closeout. The CPU client
is retained as UID `4385c581-2c2c-446a-8f7d-123617386cf8`; it is not a GPU worker.
