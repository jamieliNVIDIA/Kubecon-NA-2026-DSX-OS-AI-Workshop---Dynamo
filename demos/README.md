# Workshop demos

Run presenters from the repository root through one CLI:

```bash
uv run python -m demos list
uv run python -m demos status
uv run python -m demos single-replica --help
uv run python -m demos single-replica --rehearsal --plain --auto
```

Run `uv sync --locked` from the repository root first. Add `--plain` for one
terminal; omit it for the presenter and observer panes in tmux. Rehearsals make
no cluster calls. Routing and metrics show historical evidence in normal mode
too; their playback does not create new measurements.

| Demo | CLI name | Guide and code |
| --- | --- | --- |
| 1 | `single-replica` | [Single replica](single_replica/README.md), `single_replica/` |
| 2 | `modelexpress` | [ModelExpress](modelexpress/README.md), `modelexpress/` |
| 3 | `disaggregated` | [Disaggregated serving](disaggregated/README.md), `disaggregated/` |
| 4 | `snapshot` | [Native Snapshot](snapshot/README.md), `snapshot/` |
| 4 | `snapshot-dgd` | [DGD Snapshot](snapshot/DGD.md), `snapshot/` |
| 5 | `request-continuity` | [Request continuity](request_continuity/README.md), `request_continuity/` |
| 6 | `routing` | [Routing](routing/README.md), `routing/` |
| 7 | `kvcr` | [KVCR](kvcr/README.md), `kvcr/` |
| 7 | `kvcr-prepared` | [Retained-parent investigation](../reports/overnight-2026-11-04/KVCR-PREPARED-CHILD.md), `kvcr/` |
| 8 | `shadow` | [Shadow Engine](shadow/README.md), `shadow/` |
| 8 | `shadow-composed` | [Shadow qualification notes](../reports/overnight-2026-11-04/SHADOW.md), `shadow/` |
| 9 | `metrics` | [AgentX metrics](metrics/README.md), `metrics/` |

Numbers such as `01` or `1` select the ordinary variant. Original IDs such as
`01-single-replica` also work. The named variants keep separate prepared-run
selections.

`status` shows each selected run, its recorded phase, source dependencies and
local reservations without changing files. Its output describes saved metadata;
the presenter still verifies live readiness and evidence before an action.

## Presenter order

Follow the [workshop presenter runbook](RUNBOOK.md) for talk order, offstage
preparation, live versus recorded stops, and the explicit transitions between
serving profiles. Stable demo numbers identify implementations; they do not
define the speaking order.

## Common workflow

Follow each guide's placement, preparation and qualification requirements before
a live run. For the single-replica demo:

```bash
# Offstage preparation, then presentation of that same run:
uv run python -m demos single-replica prepare
uv run python -m demos single-replica
# Leave this server running: it is the next demo's weight source.
uv run python -m demos modelexpress prepare
uv run python -m demos modelexpress
# Clean up only after both presentations:
uv run python -m demos modelexpress cleanup
uv run python -m demos single-replica cleanup
```

Use `prime` between preparation and presentation when the demo requires it.
`--run results/NAME` explicitly chooses a run; otherwise the demo remembers its
last successfully prepared normal-mode run. Previews, rehearsals and failed
preparation do not replace that selection. Cleanup checks ownership and clears
the selection only after it succeeds.

The first server has ModelExpress enabled before launch and loads from storage.
ModelExpress preparation binds to that selected running server; the presentation
adds only the peer target. Its cleanup preserves the first server. Single-replica
cleanup refuses while a dependent ModelExpress target remains. See the
[ModelExpress guide](modelexpress/README.md) for source selection and timing limits.

Composed Shadow first requires `freeze --source-writer ...` and its reader/source
proofs. Prepared KVCR uses `prepare --repair VERIFIED-REPAIR.json` to bind to an
existing owned parent. These paths retain their own lifecycle gates.

## Code structure

Each demo folder contains its `demo.py`, guide, configuration and feature-specific
helpers. Variant implementations have descriptive names such as
`snapshot/dgd_demo.py`, `kvcr/prepared.py` and `shadow/composed.py`.

Development-only acceleration and standalone measurement/recovery tools live in
[scripts/development/](../scripts/development/README.md). In particular, the
dec-only [MX RAM cache](../scripts/development/mx_cache/README.md) is optional
development infrastructure, separate from the ModelExpress presentation.

The shared code lives in `common/`:

- [runtime.py](common/runtime.py) owns the presenter base, terminal controls,
  tmux layout and common Kubernetes/startup observation helpers. The
  single-replica entry point delegates to this shared implementation.
- [startup.py](common/startup.py) contains the pure phase, timing and readiness
  calculations, independently of the host environment and Kubernetes commands.
- [support.py](common/support.py) provides shared presenter action handling,
  YAML output, health checks and observers.
- [presenter.py](common/presenter.py) and [selection.py](common/selection.py)
  select prepared runs while preserving each demo's native lifecycle gates.
- [allocation.py](common/allocation.py) handles explicit per-run GPU placement.
- [placement.py](common/placement.py) pins P/D and continuity workers to explicit GPUs
  (`WORKSHOP_PLACEMENT`), and `WORKSHOP_LEASE` gives a presenter a named reservation, so
  demos can be staged side by side. The workshop day's files are in [allocations/](allocations/).
- [weights.py](common/weights.py) supplies the common ModelExpress loader,
  discovery and transport configuration for the first and second workers.
- [dependencies.py](common/dependencies.py) protects a source server while a
  dependent ModelExpress target uses it.
- [presentation.py](common/presentation.py) wraps projected shell commands at
  argument boundaries while preserving their exact executable values.
- [status.py](common/status.py) reads saved selections and reservations without
  loading presenters or contacting Kubernetes.
- [capture.py](common/capture.py) records the main presenter panel and its
  immutable source/evidence provenance.
- [source_paths.py](../scripts/source_paths.py) resolves source identities from historical receipts
  to their current files while retaining hash verification.

[registry.py](registry.py) defines demo IDs, entry points, CLI names and stable
selection keys once. The CLI, presenter selection and capture utility use this
registry. Shell wrappers are no longer required.

Shadow's active writer and reader helpers use descriptive names such as
`writer_descriptors.py` and `reader_descriptors.py`. The `shadow/compat/` files
retain reference protocols used by reader-delta checks and regression tests;
they are named for that behavior rather than a development iteration. The MX
development package keeps one cache seed and server renderer, with regression
coverage for the earlier iterations' content-validation and resource guards.

Cluster qualification, provisioning and upgrade tools are cataloged in
[scripts/](../scripts/README.md). Historical reports and transcripts retain their original
paths and recorded commands. Active guides use the current CLI and source
layout.

Prepared runs bind source hashes. If source bytes change, use a fresh `prepare`
and follow that demo's priming or qualification requirements. Source aliases
preserve receipt identities; they do not make changed code match an old hash.

## Capture

Capture a prepared run's main panel into a fresh attempt directory:

```bash
uv run python -m demos.common.capture \
  --demo 01-single-replica --run results/PREPARED-RUN \
  --output demos/transcripts/live/01-single-replica/NEW-ATTEMPT
```

Use the original demo ID from `registry.py` for `--demo`, including variant IDs
such as `04-snapshot-dgd` or `07-kvcr-prepared`. Add `--rehearsal` for an offline
attempt and choose an output beneath `results/` for practice recordings.
Capture runs with `--plain --auto`; it preserves all main-panel screens and
retains private raw output and source/evidence snapshots. It does not clean up
resources. Follow the demo's scoped cleanup when finished.
