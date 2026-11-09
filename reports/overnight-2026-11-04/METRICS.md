# Workload and metrics primer: overnight notes

Updated November 4, 2026. This was an offline follow-up while cluster work ran
or waited for access. No existing demo 06 source, capture or frozen bundle was
changed.

## Delivery and validation

- New `demos/09-agentx-metrics/` and `scripts/workshop_metrics_demo.py` provide
  three screens: AgentX workload/concurrency, user latency/generation, and
  service throughput/cache reuse. They fit the four-minute section 1.5 slot
  as an initial speaking allocation of 45/90/90 seconds plus transition.
- The existing demo 06 bundle supplies the actual one-worker C4 export. It is
  copied privately into each run, rather than duplicated in the repository.
  Exact source model/runtime/revision/corpus identities remain attached.
- Five focused tests pass, including source-definition version guards,
  calculated values, read-only observations, tamper refusal, actual CLI
  execution and absence of cluster/lease mutations.
- Actual keypress-driven main-panel PTY validation passed **six gates**, three
  command submission gates and three screen clears, with no visible control
  cue. Receipt:
  `results/demo-09-metrics-keypress-20261105-a1/ui-validation.json`.
- Normal-mode shareable main capture passed as **recorded_evidence_passed**:
  `demos/transcripts/recorded/09-agentx-metrics/overnight-20261105-a1/recorded-main.txt`.
  It completed in 0.15522625 seconds with zero redactions. That is automatic
  playback time, not a narrated rehearsal duration.
- All three projected text files are at most 21 lines / 73 columns before
  their short step headers. Full source configuration stays inspectable.

The parent subsequently verified the actual three-pane tmux layout through its
working execution path: six silent gates, correct read-only panes, main exit
zero and no cluster calls. Only that demo's session was cleaned up. Receipts:
`results/demo-09-root-tmux-20261105-a1/tmux-validation.json` and
`results/demo-09-root-tmux-20261105-a1/tmux-screens.json`.
An earlier agent-local socket/hook restriction prevented launch and created no
session; that limitation is superseded by this successful parent check.

## Decisions and exact semantics

**Teach a single recorded baseline before comparisons.** AIPerf's metrics
become easier to interpret when one tree's tool waits and many inference calls
are distinguished first. The workload remains the coding-agent AgentX corpus.
The sample uses one TP2 worker, two H100s, C4 session trees and a four-sequence
engine cap. This is a historical fixed-load pilot, not the later 128-sequence
sweep or a modern-runtime requalification.

**Verify formulas against the actual pinned AIPerf source.** The source archive
SHA256 is
`4e7f3a2ed15276a5252200e4d4772bf4d10e182edf2cbff4a9606794822d4699`,
at commit `e2c149ee29d3b64798d8ba2176e9f42e0aa89280`.
Eight exact source-file hashes and the original per-request JSONL hash are in
`demos/09-agentx-metrics/metric-definitions.json`. All 122 profiling records
reproduce both ITL and output rate with **zero mismatches**.

For this configuration, per-chunk usage was off, so AIPerf uses
`ITL = (request_latency - TTFT) / (OSL - 1)` and
`rate_per_request = 1 / ITL_seconds`. Request latency ends at the last content
chunk, excluding usage-only trailers; TTFT ends at the first content chunk.
The general opt-in per-chunk-usage path subtracts the actual first content
chunk's token count, falling back for invalid counts. The pinned server-count
parser subtracts separately reported reasoning tokens from completion tokens
for its output-token count.

**Keep the averaging operation honest.** The exported 139.7855206040956
tokens/s/request is the mean of per-request inverse ITLs. Inverting the mean
ITL instead gives about 136.1669. ITL percentiles are across request-average
intervals; they are not percentiles of every individual token gap. Both
definitions exclude first-content delay and tool waits and cannot be called
complete agent throughput.

**Normalize the observed service rate without calling it capacity.**
81.16156709468022 output tokens/s divided by two GPUs is
40.58078354734011 output tokens/s/H100 for this recorded observation.
Both rates use the canonical **1,200.001472204 s** observation window, while
the benchmark-duration metric is **902.686032896 s**. The source implementation
uses explicit analysis-window bounds when set, otherwise the benchmark-duration
fallback. Displaying that distinction avoids silently improving a headline
rate by changing its divisor.

**Separate cache tokens from unique application text.** The server reports
20,068,224 reused prompt tokens across 20,949,158 prompt tokens, or 95.7949%.
Requests repeat context; the denominator is a sum over requests, not unique
repository text or structural corpus-prefix overlap. More reuse reduces
prefill computation but does not inherently accelerate each generated token.

## Questions for review

1. Should the 900-second recorded profile be mentioned only as provenance,
   with a shorter separately qualified live AIPerf probe for section 1.5? The
   present runner makes no live invocation and cannot manufacture a short
   benchmark with the same scientific meaning.
2. The scalar metrics explain the baseline, but the scaling opener still needs
   usable higher-load measurements to show a curve. Do not draw a saturation
   curve through the C1/C4 pilot points.
3. Choose workshop SLO thresholds and percentiles after the final workload and
   load range are qualified. This primer intentionally does not invent them.
4. Rehearse narration within four minutes. Only automated playback and actual
   command/keypress behavior have been timed so far.
5. Full tmux-layout inspection is complete; retain the parent receipts above
   when reviewing the presenter behavior.

## Potential upstream documentation improvements

No new correctness bug was found. These are documentation/UI candidates:

- Put the exact first-content-chunk convention beside ITL and output TPS/user
  in exported comparison views. The general per-chunk path differs from the
  default OSL-1 fallback, and averaging inverse ITLs differs from inverting
  their average.
- Label configured AgentX concurrency explicitly in live-tree units, beside
  independently measured active HTTP/engine-request concurrency.
- Expose canonical throughput's observation-window divisor next to exported
  benchmark duration and explain drain behavior. This is the same practical
  improvement identified in [routing notes](ROUTING.md); track it once.

See [demo guide](../../demos/metrics/README.md) and
[routing decisions](ROUTING.md).
