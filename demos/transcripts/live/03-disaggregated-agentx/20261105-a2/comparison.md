# Matched four-H100 AgentX comparison

C16 live session trees; 900-second admission plus 300-second bounded drain.

| Metric | Two aggregated TP2 workers | TP2 prefill + TP2 decode |
| --- | ---: | ---: |
| Successful requests | 313.00 | 312.00 |
| Output tokens/s, all four GPUs | 174.75 | 174.36 |
| Output tokens/s/GPU | 43.69 | 43.59 |
| Mean generation tokens/s/user | 143.70 | 129.63 |
| TTFT p50 (ms) | 255.48 | 317.17 |
| TTFT p99 (ms) | 5,056.73 | 3,070.61 |
| ITL p50 (ms) | 6.48 | 7.85 |
| ITL p99 (ms) | 20.34 | 10.71 |
| Mean input tokens | 107,601.21 | 107,648.64 |
| Mean output tokens | 669.97 | 670.63 |
| Server-reported cache-read percent | 91.09 | 94.03 |
| Exported throughput denominator (s) | 1,200.00 | 1,200.00 |

Fixed-order, N=1 exploratory measurements. The exact spec, source hashes,
realized trace mix, cancellations and full precision are retained in comparison.json.

- Aggregate uses two general TP2 workers with KV-aware routing; P/D uses one TP2 pool of each role.
- P/D requires its NIXL/EFA connector settings and explicitly sets VLLM_SSM_CONV_STATE_LAYOUT=DS; aggregate leaves that variable unset.

- N=1 and fixed aggregate-then-P/D order; no significance or maximum-capacity conclusion.
- Other workshop jobs share CPU, storage, PCIe and network; GPU identities are disjoint.
- C16 counts live AgentX trees, not HTTP request concurrency.
- Trace-turn mix and completion/cancellation can differ under duration-bound replay.
- Canonical throughput uses its exported denominator; admission is 900 seconds plus bounded drain.
- Worker/phase request counters do not increase the logical user-request count.
- Structural prefix reuse is not observed backend cache reuse.
- JSONL preserves streaming metrics/metadata, not literal SSE bodies or generated answers; smoke uses nonstreaming responses.
- The original local controller receipt remains blocked after observer transport loss; separate recovery receipts qualify the original unreplayed P/D profile.
- A balanced P/D split is one configuration, not optimized independent pool sizing.
