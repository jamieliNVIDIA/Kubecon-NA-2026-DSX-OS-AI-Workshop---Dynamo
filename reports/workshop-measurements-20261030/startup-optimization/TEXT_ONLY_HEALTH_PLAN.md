# Paired text-only health-timing experiment

Frozen run: `results/workshop-mx-startup-20261103-textonly-health01`.
Namespace: `dynamo-ft-mxstartup-012e66a639`.
Helper: `text_only_health_startup.py`.

This candidate is prepared **offline only**. Parent execution is conditional
on textonly02 qualifying and completing verified cleanup. No namespace,
coordinator, GPU job, remote staging or cluster dry-run was created here.

## Sequence and isolated change

1. Start one fresh default-health text-only seed and publish compatible MX
   compiler artifacts through a new private coordinator.
2. Start a fresh receiver with default health settings; verify correctness,
   text-only execution, exact settings and both TP compilation-cache loads.
3. Delete that receiver and verify its Pods/ResourceClaims are gone while
   retaining the same healthy source UID.
4. Start a fresh receiver with the fast health settings and the same compiler
   artifact identity; repeat validation and compare the paired startup times.
5. Clean all owned GPU/coordinator resources, verify zero Pods/claims/graphs
   before releasing the matching lease, then analyze and seal evidence.

| Worker setting | Default receiver | Fast receiver |
| --- | ---: | ---: |
| Startup `/live` probe period | 30 s | 2 s |
| Startup failure threshold | 120 | 1,800 |
| Nominal startup failure budget, period × threshold | 3,600 s | 3,600 s |
| Startup probe timeout | 20 s | 20 s |
| Readiness `/health` probe period | 10 s | 2 s |
| Readiness failure threshold / timeout | 3 / 4 s | 3 / 4 s |
| Canary wait, `DYN_CANARY_WAIT_TIME` | Default 10 s | Explicit 1 s |

Frontend probes and worker liveness are unchanged. The source uses default
health settings throughout. Runtime logs must confirm 10/1-second canary
configuration as appropriate; a requested environment value alone is not
accepted as proof.

The model/revision/image, text-only flag, native 1,048,576 context, TP2 H100,
four sequences, 8,192 batched tokens, memory fraction 0.85, nodes, EFS checkpoint,
LIBFABRIC/EFA transport and source-idle policy remain unchanged. Both receiver
Pods start with private fresh caches and use the same new text-only compile
identity. Their installed torch artifact IDs must match each other and the
seed's publication, with actual AOT cache loads on TP0 and TP1.

Primary comparison: **one fixed-order paired default-versus-fast receiver
trial**. The older full-MM result is retained for identity/probe provenance;
it is not the primary timing control. No throughput, SLO, failure-detection or
production suitability claim follows from this startup measurement.

## Operational tradeoffs

The fast arm makes startup probes up to 15× as frequent, readiness probes 5×
as frequent and idle canaries more frequent. Readiness failure detection also
changes: its nominal period × threshold falls from 30 s to 6 s. The experiment
preserves the nominal startup failure budget; it does not claim identical
steady-state health-policy behavior. Probe execution time and scheduling can
make actual detection intervals differ from those simple products.

The scientific startup timeout is still 2,400 s per arm. Source Pod deadline
remains 10,800 s. Suggested parent subprocess bounds: preparation 1,800 s,
batch 9,600 s, cleanup 900 s and finalization 300 s. There is no automatic replay
of a started paired trial.

## Exact commands

```sh
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_health_startup.py verify --run results/workshop-mx-startup-20261103-textonly-health01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_health_startup.py prepare --run results/workshop-mx-startup-20261103-textonly-health01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_health_startup.py batch --run results/workshop-mx-startup-20261103-textonly-health01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_health_startup.py cleanup --run results/workshop-mx-startup-20261103-textonly-health01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_health_startup.py finalize --run results/workshop-mx-startup-20261103-textonly-health01
```

`freeze` and `verify` passed locally. `prepare` reuses control02's CPU-only
qualification and in-memory image-pull credential copy. It starts Redis and
waits for Redis Ready before applying the coordinator Pod, avoiding the
observed untimed CPU dependency race in textonly02. Both receiver manifests
receive client/server dry-runs before the GPU batch.

The helper reuses the **unchanged, SHA-pinned control02 helper** and accepted
MX helpers, with only process-local configuration hooks. No frozen original
file was edited. Status is recorded under the new run's `LIVE_STATUS.json`.
Per-arm identity/health and cache-reuse proofs are saved in each arm directory;
the final comparison requires distinct receiver UIDs and one retained source.

## Frozen evidence and offline checks

- Helper SHA256: `ec8951317d7cd0072b82f0a2f148fb9d60d499944017f786fd79fed1eb931b9a`.
- Spec SHA256: `9886a61acf20d5910cb5a7f6e89c4f153c415a2cd49a68a052b7226cb9a0e464`.
- `inputs-sha256.json` covers **28 fixed inputs**, excluding mutable state,
  status and unrelated scripts. All 28 hashes match.
- Source and default receiver exactly match textonly02 after normalizing
  namespace and fresh compile identity. The fast manifest differs from the
  default only in the declared worker health settings.
- The 3,600-second nominal startup failure budget and unchanged timeouts were
  checked. Runtime-validation fixtures accept both correct policies and reject
  a shortened startup budget or an unexpected default canary in the fast arm.
- Serialization is stable through the reused prepare writer. Kubernetes
  dry-runs and actual serving remain unexecuted for this candidate.

Offline receipt:
`results/workshop-mx-health01-offline-checks-20261103/receipt.json`, also copied
to the new run's `offline-validation.json`.

Pinned Dynamo configuration maps `DYN_CANARY_WAIT_TIME` to
`canary_wait_time_secs`; the default is 10 seconds. Both pinned source files
are part of the 28-file inventory.

## Detached-controller packaging

`queue_health_pair.py` and `build_health_controller.py` are prepared locally.
The builder refuses to create its output until root's verified pullback exists
at `results/workshop-textonly-pullback-20261103-a1/`. It requires the collector's
`verification.json` to have positive `files_verified` and empty `mismatches`,
plus the complete pilot02 run and controller-a5 `exit.json` under `verified/`.
Pilot02 must qualify, clean its resources and exit zero.

Run only after those collected prerequisites exist:

```sh
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/build_health_controller.py
```

Output: `results/workshop-health-controller-prep-20261103-a1/`, containing the
fixed plan, credential-free payload, file/hash manifest and predecessor handoff.
Only new health state is staged. Existing pilot02 state/qualification/cleanup
and a5 exit receipts are checked through required-existing hashes and are
never overwritten. The queue's persistent source freeze excludes mutable
`state.json` and `LIVE_STATUS.json`.

Parent launcher must verify the exact prior Docker container
`a25a5e257b7ffb73467d73c4733dffca70e82b91cc7934698c0d15974f4b45ee`
has stopped successfully before launching the detached health controller.
The queue then independently checks terminal success, qualification, recorded
and live namespace cleanup, lease absence, ready GPU nodes and no other GPU
Pods on the benchmark nodes before invoking `prepare`. It does not signal,
delete or modify predecessor resources or ownership.

Packaging source checks are recorded in
`results/workshop-mx-health01-offline-checks-20261103/packaging-receipt.json`.
No payload has been built, uploaded or executed during this offline preparation.
