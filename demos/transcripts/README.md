# Main-panel transcripts

`python -m demos.common.capture` records the actual presenter program on a PTY,
using `--plain --auto` so only the main panel is included. Commands, responses,
all cleared screens, and progress updates remain in chronological order in the
text output. It does not scrape the resources/log panes or invent any output.

```bash
# Real cluster, after the usual preparation and lease checks:
uv run python -B -m demos.common.capture \
  --demo 01-single-replica \
  --run results/booth-demo-01-attempt-01 \
  --output demos/transcripts/live/01-single-replica/attempt-01
```

Choose `02-modelexpress`, `03-disaggregated`, `04-snapshot`, or
`05-request-continuity` for the other demos.
New experimental presenters use `04-snapshot-dgd`, `07-kvcr` and
`08-shadow-engine`; follow their own preparation and qualification gates.
Use `07-kvcr-prepared` for an explicitly bound retained-parent KVCR child. It
records offstage parent/repair provenance and both request-admission gates; it
requires a live binding and does not support rehearsal. The [qualified a6 recording](live/07-kvcr/20261105-a6/main.txt)
and [cleanup receipt](../../reports/receipts/2026-11-05-kvcr-peer-reuse.json) are retained.
`06-routing` and `09-agentx-metrics` present historical evidence without cluster
calls. Their successful normal-mode captures use `recorded_evidence_passed`
and `recorded-main.txt`, never a live measurement label.
Prepare/prime MX and Snapshot offstage with their normal launchers, then pass
the same `--run` directory to capture the onstage walkthrough. That startup is
marked pre-existing in provenance; recording it does not create a fresh startup
measurement. Only the demo's existing timing definitions apply.
Prime both continuity cases offstage as well; its capture includes the two
case directories with their separate proofs and raw streaming/fault evidence.

For a local check, add `--rehearsal` and choose an output under
`results/demo-recordings-rehearsal/`. Rehearsals make no cluster calls and never
produce a live `main.txt`. Existing nonempty feature-result directories without
`demo.json` are rejected; use fresh or explicitly prepared demo runs.

The output directory is one immutable capture attempt and must not exist:

- `main.txt`: successful live main-panel output, stripped of terminal controls
  and with common credential values redacted if any were printed.
- `recorded-main.txt`: successful historical-measurement walkthrough, explicitly
  separate from a new live benchmark or deployment.
- `capture.json`: exact command, timestamps, process outcome, live/rehearsal
  mode, pre-existing startup scope, source/evidence hashes and text hash.
- `rehearsal-main.txt` or `failed-main.txt`: explicitly separate simulated or
  unsuccessful recordings. These are never presented as successful live output.

The byte-for-byte `main-panel.ansi` and byte-offset/time `timeline.jsonl` remain
in ignored `results/demo-recordings/` with restrictive permissions. `--raw-output`
can select another fresh private location. The ANSI file preserves original
bytes; the timeline allows reconstruction of their recorded timing. The clean
text retains every screen rather than emulating clear-screen overwrites.
The private directory also retains read-only `sources/` copies made before
launch, including the capture script and workshop demo/support modules, and
read-only `evidence/` JSON copies made when the child exits. `capture.json`
hashes those saved copies. Subsequent demo cleanup or source fixes do not alter
the evidence associated with an earlier recording.
Inspect the clean transcript before externally publishing it; raw files are
private working evidence and may contain unfiltered terminal output.

Capture failure preserves output and its exit status. Fix the problem and use a
new attempt directory. The wrapper does not clean up GPU resources: follow each
demo's scoped cleanup instructions before moving to the next live demo.
`--quiet` suppresses local mirroring, `--startup-timeout` controls the demo's
readiness timeout, and `--capture-timeout` bounds the whole recording (default
four hours). Interrupts are forwarded to the owned demo process group so it can
close its port-forward and leave resources available for explicit cleanup.
