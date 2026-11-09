# Demo 5: request continuity through an inference-process crash

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

Begin with a broken streaming coding response. Then repeat with frontend
request migration enabled: the same client stream pauses, moves to the surviving
worker, and continues. This uses two aggregated workers, returning from the
preceding disaggregation example for simplicity.

```bash
uv run python -m demos request-continuity --rehearsal
uv run python -m demos request-continuity --preview
uv run python -m demos request-continuity --rehearsal --plain --auto
```

Enter or Space advances or submits the displayed command; `q` stops. Tmux
opens the walkthrough, resources and logs. `--plain` uses one terminal.
Rehearsal is explicitly simulated, makes no cluster calls, and provides no
measured fault/recovery timing. Preview writes local inputs without deploying.

## Prepare offstage

The same pinned Super VL checkpoint/image and eager text-only engine profile
as demo 1 are used. Two independent cases are prepared: migration limit zero,
and migration limit three. Each has a CPU frontend and two TP2 H100 workers,
placed on different nodes within that case. **Eight H100s total.** Preparing
both cases avoids waiting for a killed engine to reload between onstage faults.
The frontend migration limit is the only behavioral setting changed between
cases. Distinct graph/claim names and discovery identities isolate the cases
within one owned namespace.

```bash
uv run python -m demos request-continuity prepare --auto
uv run python -m demos request-continuity prime --auto

# Onstage, reuse the exact same run:
uv run python -m demos request-continuity

# Afterwards:
uv run python -m demos request-continuity cleanup --auto
```

Both cases share the workshop's exclusive GPU lease. A foreign lease is never
taken over. Preparation reuses the existing exact-revision cached checkpoint
and performs client/server admission. Priming loads both pairs offstage,
waits for Ready Pods and records
actual image digests, DRA allocations, live worker registrations and EngineCore
process identities. A completed case is shown again without injecting another
fault. An interrupted case is retained for inspection; use a fresh run after
scoped cleanup. Inputs and runner/probe/shared-source hashes are frozen.

`run` requires the primed cases. It checks the reservation and the unfinished
cases' existing Pod identities, then opens the presentation without preparing
storage, applying manifests or reloading workers. If priming is missing, it
stops with the offstage `prime` command. Resuming a completed case shows its
saved outcome and never injects another fault.

## Onstage sequence

1. Show `DYN_MIGRATION_LIMIT=0` versus `3`, two workers per case, and no client
   retries. Three means up to three retries after the original attempt.
2. Send a streaming coding request to the disabled case. After 16 nonempty
   visible content chunks, identify its worker from SSE metadata and kill that
   worker's EngineCore. Inspect the actual stream error or incomplete ending.
3. Send the identical request to the enabled case. Repeat the same fault and
   show the frontend retry targeting the peer while the client response ID
   stays unchanged. In this pinned runtime the SSE worker field stays stale;
   use the correlated frontend trace to show the worker transition.
4. Inspect both outcomes, the retained token count and client chunk gaps.

The teaching YAML is projected from the frozen executable manifests, so the
displayed frontend flags, worker replica counts and TP sizes track the actual
cases. The resource pane includes the DGD, Grove PodCliqueSet, Services and GPU
claims alongside the Pods.

One HTTP POST is made per case. The request has no worker pin, guided decoding
or multiple output choices. A separate fault thread lets the client keep
reading/timestamping while `kubectl exec` runs. Worker IDs are matched to live
Pods through DynamoWorkerMetadata and exact Pod UID owner references. The
probe checks PID and process start time before SIGKILL, excludes PID 1, and
refuses shared/host process namespaces. It never kills the frontend, GMS,
the host, or any unowned workload.

Migration retains the original prompt plus accepted output token IDs in the
frontend and retries with the remaining output budget. The peer recomputes or
reuses working state; this demo does not transfer KV tensors from the dead
worker. See [technical notes](../../reports/2026-11-04-request-migration-technical-notes.md).
The continuation can differ from an uninterrupted sampled answer. Frontend or
client connection loss is outside this demonstration's scope.

## Evidence and interpretation

Each case retains `response.sse`, `events.jsonl`, `http.json`, `stream.json`,
`fault-intent.json`, `fault-result.json`, `proof.json`, and Pod/claim/log
snapshots. The run also retains frozen manifests, `request.json`, live worker
metadata, `comparison.json` and a hash inventory. HTTP 200 or DONE alone never
qualifies success. The enabled stream must continue on the peer, then produce a valid
finish and DONE, with no error; its frontend and surviving worker must stay
healthy with the same Pod/container identities. A `length` finish means the
output budget was reached, not that the entire requested Python module exists.
This does not test generated code quality or tool execution correctness.
The compact outcome view shows the stable client response, observed worker
transition, accepted output retained, terminal finish and distinct client-gap
fields. Full generated content and raw frontend trace lines remain in the
evidence files. Retained output is the frontend's accepted token count; this
demo does not independently establish zero duplicate or missing token IDs
against a reference generation.

The pinned RequestTracker stores worker IDs in `OnceLock`, so its SSE worker ID
continues to name the original worker. The demo correlates the failed router
attempt's response ID with its HTTP request span, then requires exactly one
retry retaining output tokens and a decode-worker selection of the qualified
peer. The frontend's conflicting-tracker-write log supplies that actual peer
selection. A global migration counter cannot satisfy this proof. Raw logs are
retained; the main panel prints a compact trace summary.

Because SSE attribution is stale, the exact last-old/first-peer content gap is
reported as unavailable. The maximum adjacent client content gap across the
whole response is shown separately. It does not isolate detection/retry time
or establish an SLO. A runtime with accurate per-attempt SSE worker attribution
can use the direct handoff-gap path. Background cold recovery may overlap the
next case. The frontend's 30-second backend inactivity timer is an explicit
fallback, not a promise of a particular failure-detection time.

Record the actual main panel with `uv run python -m demos.common.capture
--demo 05-request-continuity`, using the primed run and a fresh output directory.
The capture utility retains each case's nested evidence privately.

The corrected walkthrough passed a fresh live qualification on November 4:
disabled interrupted with an error; enabled preserved 31 output tokens,
continued on its qualified peer and completed with `stop` and no stream error.
See the [actual main-panel recording](../transcripts/live/05-request-continuity/20261104-a2/main.txt)
and [implementation report](../../reports/workshop-request-continuity-demo.md).
Concurrent four-worker weight loading took roughly seventeen minutes on this
EFS setup, followed by engine initialization/readiness; allow at least 25 minutes
offstage. This observation does not establish a general startup-time bound.
