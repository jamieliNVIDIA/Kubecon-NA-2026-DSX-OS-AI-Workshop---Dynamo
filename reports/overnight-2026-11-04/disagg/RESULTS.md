# Matched AgentX aggregate versus disaggregated serving

Both original profiles passed independent qualification. This C16, four-H100
point shows almost unchanged total output throughput and a latency tradeoff:
P/D has better observed tails, slower median latency and slower mean generation
per user. It does **not** establish a capacity or universal P/D speedup.

| Metric | Two aggregated TP2 workers | TP2 prefill + TP2 decode |
| --- | ---: | ---: |
| Successful requests | 313 | 312 |
| Request errors / cancellations / context skips | 0 / 0 / 0 | 0 / 0 / 0 |
| Output tokens/s, all four GPUs | 174.75 | 174.36 |
| Output tokens/s/GPU | 43.69 | 43.59 |
| Mean generation tokens/s/user | 143.70 | 129.63 |
| TTFT p50 / p99, ms | 255.48 / 5,056.73 | 317.17 / 3,070.61 |
| ITL p50 / p99, ms | 6.484 / 20.344 | 7.853 / 10.708 |
| Mean input / output tokens | 107,601 / 669.97 | 107,649 / 670.63 |
| Server-reported prompt cache-read percentage | 91.09% | 94.03% |
| Official throughput denominator, seconds | 1,200.000866 | 1,200.001093 |
| Request-record span, seconds | 900.569403 | 901.165127 |

The denominator is the exported phase window: 900 seconds of admission plus
300 seconds of bounded drain. Both phases consumed the full drain and reported
zero final cancellations. Do not divide the output tokens by admission time or
the shorter request span and present that as the official throughput. The two
runs share **312 identical source-turn identities**; aggregate has one additional
main-agent turn. Each realized ten source traces from the full pinned 393-trace
corpus. Duration-bound replay does not promise identical completed turn counts
or complete agent trees.

## Controls and limits

The campaign uses Super VL
`nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, model revision
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`, the same pinned Dynamo 1.6/vLLM
runtime digest, text-only compiled serving, native 1,048,576-token context,
TP2, 128 sequences per worker, 8,192 batched tokens and memory fraction 0.85.
AIPerf is pinned at `e2c149ee29d3b64798d8ba2176e9f42e0aa89280`.
The source corpus, canonical primers, C16 live-tree semantics, seed 20261030,
recorded pacing/output lengths and ten-second true-idle cap are unchanged.
The manifest, profile and all **52 frozen inputs** still match their hashes.

The baseline uses **KV-aware routing**, with default tuning retained from the
selected routing controls. This is not another RR-versus-KV experiment. P/D
necessarily adds role-specific NIXL/EFA connector settings and explicitly sets
`VLLM_SSM_CONV_STATE_LAYOUT=DS`; aggregate leaves that variable unset. Captured
same-image `envs.py` returns `None` when unset and documents SD as the default,
but the effective resolver was not captured. Keep this serving-path/layout
difference explicit rather than calling the comparison a single-variable
topology toggle.

Both arms use the **same exact four H100 UUIDs**, cp0198 indices 1/3 and cp0942
indices 1/3, sequentially in aggregate-then-P/D order. Current and independently
saved startup evidence agrees on Pod UIDs, image digests, nodes, GPU UUIDs and
zero restarts. Original raw archives match their extracted files. Every
profiling request has ordered timestamps, received chunks, positive completion
usage, matching token sums and a unique request ID. All metrics endpoints
exported data.

This is fixed-order **N=1**, with shared CPU/storage/network activity from other
workstreams. Neither topology was saturated: aggregate's mean running requests
were 0.80 / 0.55 per worker; P/D's were 0.12 prefill / 1.39 decode. Maxima were
6 / 4 and 2 / 7, respectively, and preemptions were zero. The equal one-prefill /
one-decode split is a qualified configuration, not optimized pool sizing.

## Actual transfer proof and an older-image canary gap

P/D's decode endpoint reports **37,752,668,160 transferred bytes** and **624
TP-rank transfer observations** during profiling. The distinct prefill/decode
worker IDs agree with the smoke response and endpoint labels. Failed-transfer,
failed-notification and notification-after-expiry deltas are zero on both
workers. Count these as transfer observations, not 624 additional user requests.

The separate prefill KV-expiry counter increased by **2,406**. Saved logs show
one new expired request per second, counted on both TP ranks, starting thirty
seconds after the prefill health task starts and continuing after AIPerf exits.
None of the logged expired IDs matches a retained benchmark request/correlation
ID. Same-image source capture shows that the health payload carries
`_HEALTH_CHECK`, but the installed prefill handler unconditionally configures
the normal prefill-to-decode transfer protocol and does not inspect that marker.
The NIXL worker reaps unconsumed leases and increments this separate counter.

These facts strongly support **local prefill canaries creating unused transfer
leases**; exact per-canary tracing was not added to this fixed campaign. An
existing upstream fix matches the missing branch:
[Dynamo #15594](https://github.com/ai-dynamo/dynamo/pull/15594), commit
`5b4ad1db8946117cb50a12af4901c96c12580d66`, “do not request KV handoff for
prefill health probes,” October 14 UTC. The clean local checkout and its fetched
`origin/main` contain that code and regression tests. This was verified from
local Git history; live GitHub status and release-branch/backport inclusion were
not refreshed. Treat it as an **image/release-selection gap**, rather than filing
a duplicate fix, and qualify a future runtime containing it in a fresh campaign.
The pinned runtime was not changed. Preserve this counter and warning rather
than calling all NIXL counters zero. No failed user request or late transfer
notification is established by these expirations.

## Recordings and operational disposition

[Actual console package](../../../demos/transcripts/live/03-disaggregated-agentx/20261105-a2/README.md)
contains byte-for-byte copies of the original aggregate and P/D AIPerf consoles,
profiles, full-precision comparison, independent acceptance and hashes. These
are actual benchmark logs, not a staged presenter PTY recording. The benchmark
retains streaming metrics/metadata, **not literal SSE bodies or generated answer
text**. Its four startup smoke responses are nonstreaming, two-token checks.
Use the earlier live demo 03 recording for the separate coding-answer and SSE
mechanism proof; do not imply this comparison revalidated answer correctness.

The local observer failed at 12:14:57 Pacific; the detached original P/D runner
finished with exit 0 at **12:26:55**. Recovery collected that original run and
kept the failed controller receipt unchanged. No profile was replayed. The
independent audit accepted the pair and cleared root to clean only the owned
GPU graph/claims, retaining the handed-off CPU/PVC/namespace/cache. Root's final
scoped cleanup passed at **12:50:32 Pacific**, with the GPU lease absent and
borrowed CPU retained; its receipt is included in the console package.

Evidence roots are `results/workshop-disagg-agentx-20261105-a2/`, especially
`independent-pair-acceptance.json`, `comparison.json`, `installed-source-inspection-r2/`,
`canary-expiry-source-review.json`, `cleanup-final.json`,
both `independent-*-startup/` directories and `profile-recovery-r2/acceptance.json`.
The offline verifier is `scripts/verify_workshop_disagg_results.py`.

For the workshop, keep the live P/D demo focused on specialization and the
measured state handoff. This result can support a brief sizing/tradeoff
discussion; it should not be introduced as a throughput-win slide.
