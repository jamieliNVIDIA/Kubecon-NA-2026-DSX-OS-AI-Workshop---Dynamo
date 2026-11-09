# Workshop presenter runbook

Follow the talk order below. Demo numbers are stable identifiers, so their
numeric order differs from the [workshop outline](../WORKSHOP_OUTLINE.md).
Use the named CLI commands to make that order clear.

Run from the checkout on the Linux jumpbox:

```bash
cd ~/dynamo-kubecon-workshop
source scripts/kubecon-jump-env.sh
uv sync --locked
uv run python -m demos status
```

`prepare` records the run selected by subsequent commands. `prime`, where
required, starts and verifies its workers before presenting. Neither command
belongs on the projected walkthrough. Plain demo commands open tmux; detach
with **Ctrl-b d** and reattach to the printed session to continue. Laptop
disconnects do not stop the jumpbox session or the serving workloads.

## Talk order

| Stop | CLI name and mode | Audience question and visible proof | Prepare offstage | Serving GPUs |
| --- | --- | --- | --- | --- |
| 1. Fundamentals | [single-replica](single_replica/README.md) · live | What does one Dynamo deployment create? Show the focused DGD, operator resources, startup, model discovery and a coding response. | `prepare` | 2 |
| 2. Workload and metrics | [metrics](metrics/README.md) · recorded evidence | What do latency, generation rate, throughput and cache reuse mean for an agent workload? Read the pinned C4 export with its denominators. | `prepare` | 0 |
| 3. Add capacity | [modelexpress](modelexpress/README.md) · live | Can the second replica load the first replica's weights? Verify both TP-rank transfers, distinguish copy time from model loading and readiness, then query the new frontend. | `prepare`, after the first server is Ready | 2 additional; 4 with the first server |
| 4. Place traffic | [routing](routing/README.md) · recorded evidence | With two workers, where should a request go? Follow cache metadata and the matched RR/KV observations. | `prepare` | 0 |
| 5. Move reusable context | [kvcr](kvcr/README.md) · live experimental runtime | How much sooner does a subagent on B answer when it reuses the main agent's context from A? Compare B's first token for an unseen repository and for A's repository, then inspect the matched transfer. | `prepare`, then `prime` (also warms both engines) | 4 |
| 6. Specialize workers | [disaggregated](disaggregated/README.md) · live | What changes when prefill and decode have separate pools? Show both roles, distinct worker identities and a completed NIXL KV handoff. | `prepare`; use `prime` to load both pools before the talk slot | 4 |
| 7. Keep a request alive | [request-continuity](request_continuity/README.md) · live | Does one client stream survive its serving engine failing? Contrast the disabled and enabled cases and inspect the correlated retry proof. | `prepare`, then `prime` | 8 across the two independent cases |
| 8. Restore engine capacity | [shadow](shadow/README.md) · live experimental runtime | After a process exits, can a parked engine restore serving capacity while the shared weights survive? Inspect promotion, fresh inference and standby replenishment. | `prepare`, then `prime` | 1 (Qwen3-0.6B TP1), shared by active and standby |
| 9. Replace a worker Pod | [snapshot-dgd](snapshot/DGD.md) · live experimental integration | Can the operator restore a new worker while its DGD and frontend remain? Show replacement identity, restore clocks and a fresh response. | `prepare`, then `prime` | TP2 on its exact prepared GPU pair |

The GPU column describes each serving setup. It is not permission to overlap
their fixed placements or a budget for every preparation helper.

`metrics` uses an earlier one-worker **C4** measurement. The default `routing`
walkthrough uses separate **C16** measurements. Their numbers are independent
observations; use metrics to define the measurements, then state the routing
experiment's concurrency and controls. Neither playback measures the currently
running intro or MX servers.

## Keep the first two servers together

The first server has the MX loader enabled before startup. It initially loads
the staged checkpoint from storage, then remains the weight source:

```bash
uv run python -m demos single-replica prepare
uv run python -m demos single-replica

# Present the recorded metrics primer while this server stays running.
uv run python -m demos metrics prepare
uv run python -m demos metrics

uv run python -m demos modelexpress prepare
uv run python -m demos modelexpress

# The recorded routing walkthrough can retain both live servers too.
uv run python -m demos routing prepare
uv run python -m demos routing
```

MX adds only the peer target. Its first-server startup record is the storage
baseline; there is no extra source or baseline startup. The new target has a
separate frontend. The routing playback explains shared traffic placement using
its own recorded deployment; it does not turn this live pair into that recorded
router experiment.

Keep the selected source and its recorded files intact while the target depends
on it. Reattach the existing tmux session to revisit the presentation. Starting a
fresh `prepare` creates a different run, rather than restarting the selected
server in place.

## Switch to the next prepared profile explicitly

Later live demonstrations use their own qualified configurations and ownership
records. P/D and the DGD Snapshot candidate use compiled profiles; the intro/MX
pair uses eager execution. KVCR and Shadow have separate experimental runtime
requirements. An existing MX-enabled worker cannot silently become one of those
workers, and a checkpoint belongs to its recorded source identities.

The ordinary P/D, continuity and Snapshot flows require the workshop's exclusive
reservation. Other candidates also have explicit placements and scoped guards.
This runbook releases the previous live group before preparing the next one.
There is no automatic cleanup, lease takeover or conversion between profiles.
For the intro/MX group, remove the dependent target first, only when both live
servers are no longer needed:

```bash
uv run python -m demos modelexpress cleanup
uv run python -m demos single-replica cleanup
```

For each subsequent live profile, prepare and prime before its presentation,
keep the same selected run, then use that profile's scoped cleanup:

```bash
uv run python -m demos kvcr prepare --auto
uv run python -m demos kvcr prime --auto
uv run python -m demos kvcr
uv run python -m demos kvcr cleanup --auto

uv run python -m demos disaggregated prepare --auto
uv run python -m demos disaggregated prime --auto
uv run python -m demos disaggregated
uv run python -m demos disaggregated cleanup --auto
```

Apply the same prepare → prime → present → cleanup sequence to continuity,
Shadow and DGD Snapshot, using their feature guides for prerequisites and
timeouts. P/D priming loads the pools without submitting the teaching request;
the walkthrough subsequently inspects those same workers and retains their
original startup timing. To demonstrate P/D startup onstage instead, omit
its prime and budget for the actual startup.

Do not assume every later profile can stay primed simultaneously. The retained
observations include approximately 12.7 minutes for P/D startup, a 25-minute
offstage budget for continuity, and 45 minutes for one DGD Snapshot prime.
Those are planning observations from specific runs, not startup bounds. Arrange
long preparation before the slot; when placements cannot coexist, plan a
separately verified allocation schedule or use a clearly identified recording.
For the workshop day, the [day plan](WORKSHOP_DAY_PLAN.md) is that schedule: all
demos on pinned GPUs at once, with named reservations.
Metrics and routing playback remain available during these transitions.

## Choose alternate presenters deliberately

- **`snapshot`** is the separate native vLLM restore path. It uses a retained
  qualified artifact and its own serving Pod lifecycle. **`snapshot-dgd`** shows
  Dynamo's DGD and frontend surviving worker replacement. Choose the latter for
  the operator-managed narrative above; their artifacts and selected runs are
  not interchangeable. See [native Snapshot](snapshot/README.md) and
  [DGD Snapshot](snapshot/DGD.md).
- **`kvcr-prepared`** binds an explicitly repaired, retained parent after its
  ownership and admission checks. Its child cannot redeploy or clean the parent.
  It is an alternative to a fresh `kvcr` run, not an extra onstage stop. See the
  [retained-parent procedure](../reports/overnight-2026-11-04/KVCR-PREPARED-CHILD.md).
- **`shadow-composed`** needs a frozen qualified source writer, the recorded
  source-release gates and its additional health evidence. It is an alternative
  experimental composition, not a drop-in resume of `shadow`. Use the ordinary
  Shadow presenter for offline rehearsal. See the
  [composition notes](../reports/overnight-2026-11-04/SHADOW.md).

## What to keep on screen

Lead with the audience question, show the small executable settings excerpt,
perform the bounded action, then inspect the proof. Keep source preparation,
downloads, artifact hashing and admission checks in the offstage commands.
Full manifests and raw evidence remain in the selected run for inspection.

Startup and recovery metrics need their actual boundaries. Model-loading totals
and nested phases overlap; a peer-copy duration is only part of model loading.
Presenter keypresses, `cat`, model discovery and request inspection do not belong
in those clocks. Recorded evidence, rehearsal and actual live results retain
their labels. A changed worker or interrupted proof needs diagnosis rather than
an onstage rerun that silently replaces the original evidence.

The runbook describes the intended flow. Each feature guide retains its actual
qualification status; rehearsal and presentation polish do not establish a new
live performance or recovery result.
