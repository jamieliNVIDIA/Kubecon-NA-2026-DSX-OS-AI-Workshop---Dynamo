# AgentX scaling and routing investigation

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

The default walkthrough uses the **three independently accepted C16 cells**:
one worker with round-robin, two workers with round-robin, and two workers with
KV-aware routing. All use the same pinned AgentX corpus, text-only Super VL,
TP2 workers and 128-sequence engine cap. Workers were fresh for each cell.

```bash
uv run python -m demos routing --rehearsal
uv run python -m demos routing --preview
```

Before presenting in normal mode, verify and select the recording offstage:

```bash
uv run python -m demos routing prepare
uv run python -m demos routing
```

Preparation freezes and validates the evidence without contacting a cluster.
The walkthrough rechecks its frozen inputs silently and starts at the first
investigation. It does not repeat preparation on the projected screen.

This is a **recorded-evidence presenter**. Playback never deploys workers,
changes routing, invokes AIPerf, or reserves GPUs. Normal mode and rehearsal
both display genuine historical measurements. Enter or Space advances and
submits the displayed command; `q` stops. Controls stay off the projected screen
and each investigation clears it. The tmux side panes show study boundaries,
measured request pressure and actual C16 worker cache-event connections.

Use `--plain` for one terminal or `--full-manifest` to print the recorded KV
deployment. Full one-worker/RR/KV manifests remain in every run directory.

## Four investigations

1. **One RR worker → two RR workers at C16.** Aggregate output rate changed
   170.92 → 175.55 tokens/s, while mean per-request decode speed rose 18.6%.
   Cache-read share declined and p99 TTFT worsened from 3.81 to 15.40 seconds.
   This changes capacity and placement opportunities together. Fresh workers
   mean this is a controlled topology comparison, rather than in-place scale-up
   retaining the first worker's cache.
2. **How the router learns about cache.** Inspect the actual measured KV
   manifest's frontend mode, prefix caching and cache-event publisher. Show
   both actual C16 `kv-events` connections against current Pod/worker identities.
   These messages describe residency; they do not carry tensors. CPU-tier
   visibility still needs the appropriate integration events.
3. **Two RR workers → two KV workers at the same C16 load.** Cache-read share
   rose 87.15% → 91.03%, p99 TTFT fell 15.40 → 5.17 seconds and aggregate rate
   stayed roughly flat. There were 311 selections and positive total predicted
   prefix overlap. Each p99 represents about three requests per cell; these
   are observations, not stable production percentiles or SLO guarantees.
4. **A warm worker can also be busy.** Illustrate parallel coding-agent branches
   sharing a prefix. Router tuning balances locality against load. Transition
   to KVCR: can the colder worker retrieve state rather than recompute? Copying
   cached state and migrating a request are separate mechanisms.

Allow roughly 2 / 3 / 3 / 2 minutes plus two minutes for questions and transition
in the 12-minute routing slot. Automatic playback took 0.436 seconds, excluding
explanation and human keypresses; a narrated rehearsal remains open.

## Controls and limits

All C16 cells had zero request errors, context overflows and canceled profile
records. Canonical rate windows were approximately 1,200 seconds, including
drain after 900-second admissions. Session completion reached the bounded
grace deadline despite all measured requests completing. These partial replay
trees do not establish completed coding tasks.

The results support the cache/locality discussion. They **do not establish a
capacity knee or universal speedup**. C16 counts paced live trees, not active
inference requests. One worker averaged 1.61 running requests and had zero
waiting requests at median/p99; roughly 89% GPU utilization alone does not
establish saturation. This was N=1 in fixed order with fresh workers, the same
primers and engine controls. Realized trace/turn mixes differ. Other tests used
disjoint GPUs while sharing node CPU, storage and network.

C32 in this original source campaign failed at frontend model discovery
**before profiling**. That failed attempt remains preserved. A later fresh
campaign with an exact-model startup gate now has an independently accepted
[C32 two-worker RR/KV pair](../../reports/overnight-2026-11-04/routing-c32/C32-RESULTS.md):
aggregate output rate 500.12 → 525.23 tokens/s, cache-read 85.04% → 88.88%,
p99 TTFT 30.68 → 7.12 seconds, and mean decode speed/user 91.19 → 87.52 tokens/s.
The lower mean decode speed is part of the observed tradeoff. Its one-worker
primer failed through a proven liveness restart; there is no accepted C32
scale-out ratio. This newer pair has not been imported into the current C16
presenter/capture; keep the campaigns and changed order separate.
See [accepted results and limits](../../reports/overnight-2026-11-04/routing-sweep/C16-RESULTS.md).

## Evidence and reproduction

The [C16 main-panel capture](../transcripts/recorded/06-routing/c16-20261105-a1/recorded-main.txt)
is actual presenter output with
[provenance and hashes](../transcripts/recorded/06-routing/c16-20261105-a1/capture.json).
Its status is `recorded_evidence_passed`, never `live_passed`.

`recording-c16/recording.json` pins 35 files: accepted analysis, transport and
independent acceptance, launch plan/payload inventory, campaign, actual
manifests, and each cell's specification, profile, summary, qualifications,
AIPerf export and identity excerpt. Import rechecked **1,040 transported files**
and **47 frozen payload members**. Identity excerpts retain original source
hashes while omitting Pod environment values.

Validation checks source/export metrics, clean cells, matched controls, fresh
worker UIDs, physical GPU pairs, current event sources and positive predicted
overlap. Workload profiles differ only in endpoint/artifact/metric locations;
RR/KV manifests differ only by frontend routing mode. One-/two-worker manifests
differ only in replicas and permitted worker nodes. Each run freezes full
manifests, `comparison.json`, `realized-mix.json`, `pressure-proof.json`, original
cache connection log lines and command receipts.

To reproduce the freeze from already-collected private evidence:

```bash
uv run python -m demos.routing.freeze_c16_recording \
  --output results/NEW-C16-RECORDING-BUNDLE
```

This verifies/copies evidence without network access or inference and rejects
existing destinations. Capture a fresh walkthrough with:

```bash
uv run python -m demos routing prepare --run results/NEW-C16-PRESENTER-RUN
uv run python -m demos.common.capture \
  --demo 06-routing --run results/NEW-C16-PRESENTER-RUN \
  --output demos/transcripts/recorded/06-routing/NEW-ATTEMPT
```

## Historical pilots remain available

The original C4 scale-out/C1 policy bundle in `recording/`, its
[original capture](../transcripts/recorded/06-routing/overnight-20261105-a1/recorded-main.txt),
and existing presenter runs are preserved. Select it for a fresh run with:

```bash
uv run python -m demos routing --recording-profile historical --rehearsal
```

Existing runs infer their choice from frozen metadata, so old resume commands
remain valid. Changing a saved run's profile is rejected. Historical C4/C1
tables remain separate with their original serving profiles and C1 denominator
caveat. The historical `freeze_recording.py` still reproduces that evidence.
[Demo 09](../metrics/README.md) continues using its original C4 export
and pinned metric definitions.

See [C16 presenter notes](../../reports/overnight-2026-11-04/ROUTING-C16.md),
[earlier decisions](../../reports/overnight-2026-11-04/ROUTING.md), and
[parallel-prefix evidence](../../reports/workshop-measurements-20261030/agentx-workload/BRANCH_PREFIX_FINDINGS.md).
