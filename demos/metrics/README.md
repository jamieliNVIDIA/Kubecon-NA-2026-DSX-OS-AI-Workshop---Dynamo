# AgentX workload and metrics primer

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

A short **recorded-evidence** walkthrough for section 1.5, reusable at the
scaling opener. It uses the actual one-worker C4 AgentX export already pinned
by [demo 06](../routing/README.md). No benchmark, download, GPU reservation
or cluster request occurs during playback.

Verify and select the recording offstage, then present it:

```bash
uv run python -m demos metrics prepare
uv run python -m demos metrics
```

Playback requires a successfully prepared run and keeps the verification output
off the projected screen. Preparation performs only local evidence checks.
Rehearsal and preview remain self-contained:

```bash
uv run python -m demos metrics --rehearsal
uv run python -m demos metrics --preview
```

The three screens cover the workload, user experience, and service efficiency.
Allow roughly 45 / 90 / 90 seconds plus a 15-second transition. Enter or Space
advances and submits the displayed command; `q` stops. Controls stay off the
projected screen. Each screen clears, and the tmux side panes retain topology,
study boundaries and metric definitions. `--plain` uses one terminal.
The actual three-pane layout passed six silent gates with main exit zero;
its review receipts are `results/demo-09-root-tmux-20261105-a1/tmux-validation.json`
and `tmux-screens.json` beside it.

Normal mode is also recorded evidence. `--rehearsal` rehearses the controls;
the displayed numbers are genuine historical measurements in both modes.
The [main-panel capture](../transcripts/recorded/09-agentx-metrics/overnight-20261105-a1/recorded-main.txt)
has status `recorded_evidence_passed`, never `live_passed`. Automatic capture
took 0.155 seconds; that excludes presenter explanation and human keypresses.

## What the numbers mean

- **Concurrency:** C4 counts live AgentX session trees. A tree contains many
  HTTP requests, tool waits and potentially parallel branches. It does not mean
  four simultaneously running engine requests.
- **Requests and errors:** 122 accepted measured requests, zero reported errors.
  These were partial replay trees, not 122 successful coding tasks.
- **TTFT:** request start to first content chunk. The recorded p50/p99 were
  306.19 / 2,150.72 ms.
- **ITL:** one average token interval per request; the displayed p50/p99 are
  percentiles of those request-level values. They are not percentiles of all
  individual token gaps pooled together.
- **Generation rate per request:** the inverse of that request's ITL, averaged
  over measured requests. It excludes TTFT and tool waits. The recorded mean
  was 139.79 tokens/s/request, rather than an end-to-end agent progress rate.
- **Service rate:** the canonical export reports 81.16 output tokens/s.
  Dividing by two assigned H100s yields an observed 40.58 tokens/s/H100 using
  the same denominator. This low-load, drain-inclusive rate is not peak
  serving capacity or evidence of a saturation curve.
- **Prefix reuse:** server usage reports 20,068,224 cache-read prompt tokens
  from 20,949,158 prompt tokens summed across requests: 95.79%. Repeated
  context counts repeatedly in those totals. Reuse saves prompt processing;
  it does not inherently speed generation of each new output token.

The canonical throughput denominator is **1,200.001472204 s**, including this
analysis window's drain, while the recorded request span is **902.686032896 s**.
The presentation shows both. Do not silently replace the canonical denominator
or divide aggregate throughput by four trees to infer user generation speed.

## Exact source definitions

The implementation was checked in AIPerf commit
`e2c149ee29d3b64798d8ba2176e9f42e0aa89280` from the SHA-verified pinned archive.
[metric-definitions.json](metric-definitions.json) freezes eight source-file
hashes, the archive identity, exact formulas and an independent reproduction
receipt for all 122 recorded requests. There were zero formula mismatches.

For this run, per-chunk usage was disabled. AIPerf therefore assumes one token
in the first content chunk:

```text
TTFT = first_content_time - request_start_time
request_latency = last_content_time - request_start_time
ITL = (request_latency - TTFT) / (output_sequence_length - 1)
rate_per_request = 1 / ITL_seconds
reported_mean_rate = mean(rate_per_request)
```

The last content timestamp excludes a trailing usage-only chunk. This pinned
parser uses server token counts with separately reported reasoning tokens
subtracted from completion tokens for its output-token count.

With opt-in per-chunk usage, the general ITL formula subtracts the valid
reported first-content-chunk token count instead of one. Inconsistent counts
fall back with a warning. The simplified formula above is scoped to this
recorded configuration. Inverting the **mean** ITL would produce about 136.17
tokens/s, which differs from the actual mean of per-request rates, 139.79.

Canonical aggregate throughput uses the explicit analysis-window duration
when set; otherwise it falls back to `BenchmarkDurationMetric`. The latter
measures maximum response timestamp minus minimum request timestamp. That is
why an exported request-span duration need not be the canonical rate's divisor.

The run directory retains the complete original recording bundle, its full
effective AIPerf configuration, rendered screens and a derived `metrics-proof.json`.
This demo adds no duplicate large source exports to the repository; it copies
the existing demo 06 bundle privately into each run.

To reproduce the offline formula receipt from the existing private source
archive and original per-request export:

```bash
uv run python -m demos.metrics.freeze_metric_definitions \
  --output results/NEW-METRIC-DEFINITIONS.json
```

Existing destinations are rejected. This is an evidence verification operation,
not an AIPerf invocation.

To capture a fresh walkthrough:

```bash
uv run python -m demos metrics prepare --run results/NEW-METRICS-RECORDING
uv run python -m demos.common.capture \
  --demo 09-agentx-metrics --run results/NEW-METRICS-RECORDING \
  --output demos/transcripts/recorded/09-agentx-metrics/NEW-ATTEMPT
```

See [decisions and remaining questions](../../reports/overnight-2026-11-04/METRICS.md).
