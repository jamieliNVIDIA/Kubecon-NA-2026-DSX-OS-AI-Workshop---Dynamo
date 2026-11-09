# Text-only startup pilot result

The text-only MX receiver reached observed Ready in **188.82 s**, versus
**249.70 s** for the earlier full-multimodal MX weights-plus-artifacts run.
That is **60.88 s / 24.38% shorter observed startup**. Both are single trials,
run about six hours apart; this is an **unpaired historical comparison** with
a deliberate capability change. It does not show a repeatable 60.88 s saving
caused entirely by removing multimodal work.

The clearest engine-level result is **74.44 → 41.21 s initialization**.
Text-backbone profiling/warmup remains approximately unchanged, **27.72 → 28.78 s**.
Meanwhile **22.88 s of the observed reduction lies in the readiness tail**,
despite identical health settings. That part must not be attributed to removed
multimodal computation.

## Conditions and acceptance

- Same Super VL model and revision, inference image, native 1,048,576 context,
  TP2 H100, four sequences, 8,192 batched tokens and memory fraction 0.85.
- Same physical source and receiver GPU UUIDs, nodes and driver 610.57.04.
- Worker/frontend probes and the 10-second canary setting unchanged.
- Both runs use compatible peer weights and actual transferred compiler-cache
  loads on both TP ranks, private fresh per-Pod caches and an idle source.
- Text-only seed and receiver both use `--language-model-only`; source and
  receiver logs explicitly announce text-only mode. Expected multimodal
  processor-warmup and encoder-profile messages are absent in both.
- Correct READY responses, exact context and zero restarts passed. The new
  receiver's independently checked correct response arrived **191.00 s** after
  deployment; this follows evidence collection, not the first possible response.
- The new storage-loaded seed still took **552.90 s**. The 188.82 s result
  applies to a receiver with a compatible ready donor, not the first seed.

Existing EFS checkpoint and uncontrolled host page caches; no external model
download, global cache flush or AgentX/throughput load ran during these timings.

## Exclusive receiver timeline

These intervals are contiguous and non-overlapping. Timer starts are
back-calculated from logged ends and reported durations. Kubernetes transition
timestamps have second precision; engine durations are rounded to 0.01 s;
readiness is observed with five-second polling. More decimal places in JSON
are arithmetic, not that level of measurement precision.

| Phase | Full-MM historical | Text-only | Historical − text-only |
| --- | ---: | ---: | ---: |
| Deployment → worker container start | 8.26 s | 8.04 s | +0.22 s |
| Pre-model-load process/runtime boot | 62.90 s | 63.45 s | −0.56 s |
| Model loading, slower TP rank | 57.68 s | 52.59 s | +5.09 s |
| Between model and engine timers | 0.44 s | 0.43 s | +0.01 s |
| Engine initialization | 74.44 s | 41.21 s | +33.23 s |
| Engine end → observed Ready | 45.98 s | 23.10 s | +22.88 s |
| **Total** | **249.70 s** | **188.82 s** | **+60.88 s** |

Text-only boundaries, UTC November 4, 2026 (November 3 Pacific):

| Boundary | Timestamp |
| --- | --- |
| Deployment apply begins | 06:58:45.956 |
| Worker container starts | 06:58:54 |
| Model-load timer starts, inferred | 06:59:57.451 |
| Slower model-load timer ends | 07:00:50.039 |
| Engine-init timer starts, inferred | 07:00:50.468 |
| Engine-init timer ends | 07:01:31.678 |
| Generate endpoint registers | 07:01:36.577 |
| First canary-request warnings | 07:01:46.584 |
| Worker Pod Ready transition | 07:01:53 |
| Controller observes Ready | 07:01:54.774 |

The 63.45 s pre-loader boot comprises 10.26 s before the first worker log,
29.21 s from that log to the EngineCore announcement and 23.98 s from that
announcement to the inferred model-load start. These locate bootstrap and
distributed-process setup; they do not separately profile imports, CPU work,
CUDA or NCCL.

## What changed inside the engine

The interval from inferred engine-init start to the TP0 cached-AOT-load log
fell from **35.93 s to 0.85 s**. The old run logs multimodal encoder profiling
in that interval; the text-only run does not. This is consistent with removing
that initialization work. The rest of the engine still performs the text
backbone's profiling/warmup, KV-cache setup and fresh CUDA graph captures.

Both new ranks load AOT artifacts from cache key
`fb3c36168aaeb21b3828101c20ae5170024a9a30156c8617c216b6430606bf4a`:
TP0 at **07:00:51.314** (raw worker line 4623), TP1 at **07:00:51.322**
(4625). Reported compilation is **0.19/0.20 s**, versus 0.15/0.14 s previously.
The installed torch artifact links to the new seed's publication; transfer
alone was not the acceptance gate.

The historical **40.172 s main-process multimodal warmup** overlapped model
loading in other processes. Its absence is not another additive 40 s saving.
Likewise, backbone warmup, graph captures and compilation are nested inside
engine initialization and must not be summed as extra top-level phases.

## What remains inside model loading

| Nested measurement, TP0 / TP1 | Full-MM historical | Text-only |
| --- | ---: | ---: |
| Adopted hidden tensors | 120 / 120 | 120 / 120 |
| Hidden-tensor adoption | 40.792 / 40.972 s | 34.590 / 35.044 s |
| NIXL registration | 0.979 / 1.973 s | 5.797 / 0.753 s |
| Actual weight copies | 6.75 / 4.96 s | 3.21 / 3.23 s |
| Manifest tensors per rank | 1,869 | 1,413 |
| Transferred payload per rank | 40.27 GB | 39.22 GB |
| Full model loading | 57.681 / 57.243 s | 52.588 / 48.208 s |

Hidden-tensor discovery remains a roughly **35-second** step. The same MX
0.6.0 adoption logic ran; no tensors were deliberately skipped by a patch.
Its shorter duration is observed, not a diagnosis of exactly which Python
objects consumed less time. Registration also varied substantially between
trials and ranks. These parallel/nested timings do not add into an exclusive
model-loading breakdown.

## The readiness tail still varies

| Interval | Full-MM historical | Text-only |
| --- | ---: | ---: |
| Engine end → generate endpoint registered | 5.02 s | 4.90 s |
| Endpoint registered → Pod Ready | 38.53 s | 16.42 s |
| Pod Ready → observed Ready | 2.44 s | 1.77 s |

Both workers retain 30-second startup probes, 10-second readiness probes and
a 10-second canary wait. In the text-only run, the last startup-probe failure
is logged at **07:01:23**, the first canary-request warnings at **07:01:46.584**,
and Pod Ready changes at **07:01:53**. In the historical run, the first canary
appeared just after the **00:34:58** failed startup probe, with Pod Ready at
**00:35:28**.

That pattern supports probe/canary alignment as a contributor to the shorter
tail. Neither log records the exact successful canary/probe timestamp, so we
cannot partition it precisely into computation and waiting. Approximately
38% of the observed 60.88 s reduction falls in this tail; a separate paired
health-policy experiment is intended to examine it.

## KV capacity and hardware

| Engine-reported receiver capacity | Full-MM historical | Text-only |
| --- | ---: | ---: |
| Available KV budget per rank | 27.32 GiB | 28.42 GiB |
| KV token pool | 13,468,640 | 14,012,788 |
| Native-context memory-capacity estimate | 12.84× | 13.36× |

The extra reported KV capacity is about **1.10 GiB / 544,148 tokens**. The
configured **maximum number of sequences is still four**; the 13.36× log is a
memory-capacity estimate, not a measured or configured user concurrency.
Unchanged memory fraction does not imply identical KV allocation or identical
engine initialization work.

Both trials used these exact GPU pairs:

| Role/node | GPU UUIDs |
| --- | --- |
| Seed, cp-0124 | `GPU-ce4aaec3-4fd1-f047-a303-80986bc29110`; `GPU-75461e0d-6588-94c9-2517-dca859f5c68b` |
| Receiver, cp-0198 | `GPU-3aea3e1e-63c3-41cd-43be-4e379ed995b5`; `GPU-08dc0ef4-2e92-4cc2-6adc-b735980a1326` |

All are H100 80GB HBM3 with driver **610.57.04**. Matching hardware removes one
source of variation; it does not turn these unpaired single trials into a
repeatable causal estimate.

## Evidence

Root verified **443 copied files with zero mismatches**, terminal controller
exit zero and zero remaining pilot Pods/ResourceClaims/DGDs. The historical MX
pullback separately verified 560 selected files. This analysis read both raw
trees without modifying them and hashed its 17 raw inputs.

- [Verified text-only pullback receipt](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-pullback-20261103-a1/verification.json)
- [Machine-readable result and input hashes](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/text-only-result.json)
- [Metric comparison CSV](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/metric-comparison.csv)
- [Exclusive phase comparison CSV](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/exclusive-phase-comparison.csv)
- [Timestamped exclusive timelines CSV](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/exclusive-timelines.csv)
- [Text-only receiver evidence excerpts](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/text-only-mx-artifacts-excerpts.txt)
- [Read-only derivation script](/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/workshop-textonly-analysis-20261103-a1/analyze_text_only.py)
