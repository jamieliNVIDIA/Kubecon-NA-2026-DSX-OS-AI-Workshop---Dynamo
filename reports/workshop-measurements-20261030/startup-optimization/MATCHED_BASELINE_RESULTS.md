# Matched startup comparison on the updated baseline

Measured November 4, 2026. The storage and MX arms all use text-only Super VL
and the qualified faster worker-health policy. This is the compiled benchmark
profile; the eager presenter demonstrations have a separate profile.

| Measurement | MX off: EFS storage | MX peer weights | MX peer weights + artifacts |
| --- | ---: | ---: | ---: |
| Deployment → observed Ready | 492.79 s | 280.10 s | 173.61 s |
| Deployment → first checked correct response | 494.96 s | 282.30 s | 176.10 s |
| Model loading, slower rank | 267.39 s | 52.57 s | 48.66 s |
| Engine initialization | 143.90 s | 149.12 s | 40.53 s |
| torch.compile, nested in engine initialization | 26.38 s | 30.76 s | 0.20 s |
| Backbone profiling/warmup, nested in engine initialization | 80.72 s | 82.17 s | 28.51 s |
| Peer copy, slower rank, nested in model loading | — | 3.23 s | 3.22 s |
| Engine end → observed Ready | 9.17 s | 7.40 s | 8.09 s |

MX peer weights reached observed Ready **1.76×**
faster than native storage. With compiler-cache transfer, startup was
**2.84×** faster than storage and
**1.61×** faster than peer weights
alone: a **319.18 s
(64.8%)** total reduction
relative to the matched storage arm.

## Controls and limits

The model is `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4` at
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`. Every arm uses the same runtime image
`nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`; TP2 H100, native 1,048,576 context,
four sequences, 8,192 batched tokens and GPU-memory fraction 0.85.

All seed/receiver workers use `--language-model-only`, canary wait 1 second,
startup period 2 seconds / failure threshold 1,800, and readiness period
2 seconds. Other probe settings are held fixed. This adopts the measured
startup policy without making a production fault-detection or SLO claim.

One fresh idle source was retained throughout the receiver trial. Its initial
storage bootstrap took **512.42 s**;
the receiver saving requires an existing compatible source. Receivers ran in
fixed storage → weights → artifacts order on the same physical two H100 GPU
UUIDs, with distinct Pod UIDs and fresh private caches. Native storage has no
MX environment settings. Artifact transfer is disabled in the weight-only arm.
NIXL peer transfer uses LIBFABRIC/EFA. Host page cache is uncontrolled and never
flushed, so storage is an existing-checkpoint result, not a cold-download test.

This is one trial per arm with five-second Ready observation, not a distribution.
The first checked response follows evidence collection and is an upper bound on
first-possible inference. Phase timers overlap across ranks and within model /
engine initialization; do not sum the rows. No AgentX throughput load, Snapshot,
initialized-process restore or autoscaling was used.

## Acceptance and provenance

All arms passed the correct READY response, model/context/image/TP and effective
health checks with no restarts. Both MX arms transferred weights on both ranks
without storage fallback. The artifact arm loaded the published AOT cache on
TP0 and TP1; merely copying files was not sufficient for acceptance. Receiver
Pods and GPU claims were verified absent between arms. Final owned Pods,
ResourceClaims and DGDs are absent and the remote GPU lease is released.

- [Versioned baseline](../../../configs/dgd/super-vl-textonly-fast-startup/).
- [Frozen plan](MATCHED_BASELINE_PLAN.md).
- Spec SHA256: `e0efc532518c7cc3e9e8ad3907ed81f966ae114ca8f166cbdb141f040eb3f3e7`.
- Verified pullback: `results/workshop-baseline-pullback-20261104-a3/verification.json`:
  **633 files, zero mismatches**, controller exit zero.
- Derived CSV/JSON and raw-input hashes: `results/workshop-baseline-analysis-20261104-a3/`.
- Earlier multimodal and text-only health comparisons remain separate historical
  experiments; their timings are not mixed into this matched table.
