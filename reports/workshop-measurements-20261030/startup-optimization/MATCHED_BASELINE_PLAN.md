# Updated compiled startup baseline and matched MX comparison

Requested November 4: promote the qualified text-only and faster worker-health
settings, then remeasure MX on versus off. This is a fresh experiment; earlier
multimodal and eager-demo measurements remain separate.

## Tasks

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Use the actually qualified health-pair manifests as the more specific template.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
- [x] Hand off to `deploy_dynamo` or `kubectl apply`
- [x] Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
- [x] Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
  - User authorized the existing settings plus the qualified changes. Startup
    uses the existing file-backed spec, rather than an AIPerf load spec.
- [x] Verify endpoint healthy (curl `/v1/models` on the frontend)
- [x] Run the benchmark (`run_profile`)
  - The startup controller measures deployment through observed Ready and a
    checked correct response; no throughput load is part of this experiment.
- [x] Fetch and analyze results (`get_results`)
- [x] Compare to previous runs if relevant (`compare_runs`)

## Common deployment controls

Super VL `8a115b9d966adce8c059a7bcf47f49a1e57957d8`, pinned image ending
`e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`,
TP2 H100, native 1,048,576 context, four engine sequences, 8,192 batched tokens,
GPU memory fraction 0.85, compiled execution. Every worker, including the seed,
uses `--language-model-only`, `DYN_CANARY_WAIT_TIME=1`, startup period 2 seconds /
failure threshold 1,800, and readiness period 2 seconds. Other probe fields and
frontend health remain unchanged.

This adopts the qualified startup health policy; it does not qualify its fault
detection or SLO behavior. Startup timeout remains 20 seconds, so the nominal
3,600-second period-times-threshold budget is not an identical hung-probe window.

## Trial

One fresh idle MX seed loads from the existing EFS checkpoint and publishes
new compatible text-only artifacts. Keep its UID alive through three receiver
arms, each on the same target node, with a new Pod and private empty caches:

1. **MX off:** native storage loader, all MX environment settings removed.
2. **MX weights:** peer loader, artifact transfer disabled.
3. **MX weights and artifacts:** peer loader and compatible compiler caches.

The first comparison exposes weight loading; the last shows the full qualified
MX path. Other receiver settings are identical. NIXL uses LIBFABRIC/EFA. The
source remains idle except health and the same tiny readiness request. Host
page cache is uncontrolled and never flushed. Retaining the same idle seed
during the storage arm holds GPU topology/occupancy constant.

Accept only correct READY responses, exact model/image/context/TP and health
settings, no restarts, identical receiver GPU UUIDs, verified two-rank peer
transfers without storage fallback, and actual two-rank AOT loads from the
published artifact in the artifact arm. The storage and weight-only arms must
not install MX compiler artifacts. Verify receiver Pod/claim cleanup between
arms and complete owned cleanup before releasing the GPU lease.

This is one fixed-order trial per arm, observed Ready at five-second polling.
Report model loading, engine initialization and nested compilation/warmup
separately; do not sum overlapping rank timers. No throughput, distribution,
autoscaling or Snapshot claim follows. Never replay a started trial.

## Access

Initial checks: SSH to `ubuntu@3.238.63.5` timed out; local Kubernetes endpoint
`127.0.0.1:16443` refused the connection. No deployment, GPU reservation or
benchmark has been started. Local preparation can proceed without access.

Access subsequently recovered after the user's VPN confirmation. Live inventory
showed no GPU Pods, no running controllers and no remote lease. The fresh
controller was launched at 19:23:15 UTC on November 4 (11:23 a.m. Pacific).
This supersedes the initial access checkpoint; the trial has been dispatched.

## Frozen run and commands

Current run: `results/workshop-mx-startup-20261104-baseline03/`.
Spec SHA256: `e0efc532518c7cc3e9e8ad3907ed81f966ae114ca8f166cbdb141f040eb3f3e7`.
The versioned deployment files are in `configs/dgd/super-vl-textonly-fast-startup/`.

`matched_baseline_startup_03.py` supports `verify`, `prepare`, `batch`, `cleanup`
and `finalize`, with `--run` pointing to the frozen run. GPU execution is
delegated to the detached controller: do not run a second local copy.
Preparation and batch each verify the immutable inputs. A `batch-started.json`
receipt prevents replay. No automatic retry changes scientific settings.

Baseline01's source served correctly, then a validator comparing raw manifests
to API-defaulted Pod probes stopped qualification. Its 271-file verified failed
pullback and cleanup are preserved. Baseline02 was only an offline guard draft.
Baseline03 checks the qualified effective probes and Downward API defaults; it
passes the captured real Pod and rejects real policy mutations. It retains the
same serving parameters in a new namespace with new caches. Controller a3
started at 19:38:19 UTC (11:38 a.m. Pacific). Both the parent launcher and the
queue verify the failed predecessor's terminal state and cleanup before new
GPU work.

## Completed result

All three receivers passed: **492.79 s storage → 280.10 s peer weights →
173.61 s peer weights and artifacts** to observed Ready. Model loading was
267.39 / 52.57 / 48.66 s; engine initialization was 143.90 / 149.12 / 40.53 s.
Both TP ranks loaded published AOT artifacts in the final arm, both peer arms
transferred weights without storage fallback, and all correct-response,
identity, probe, GPU and no-restart checks passed.

The controller exited zero at 20:05:40 UTC (12:05 p.m. Pacific). Pullback verified
633 files with zero mismatches. An independent cleanup audit found zero owned
Pods/ResourceClaims/DGDs and no remote lease, then released the exact local
fence at 20:06:14 UTC. The Snapshot handoff receipt is
`results/workshop-snapshot-dgd-20261104-a1/gpu-handoff.json`.

The [matched result report](MATCHED_BASELINE_RESULTS.md) contains the complete
table, controls and limits. No benchmark replay or continuation is queued.
