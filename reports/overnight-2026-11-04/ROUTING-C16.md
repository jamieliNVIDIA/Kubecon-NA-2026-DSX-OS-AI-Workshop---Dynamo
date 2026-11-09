# Routing presenter: accepted C16 evidence

Updated November 5, 2026. This workstream imported independently accepted
evidence offline; it did not launch a benchmark or make GPU/network calls.

## What changed

Demo 06 now defaults to the accepted C16 one-RR → two-RR → two-KV experiment.
It uses a separate `recording-c16/` bundle and profile
`agentx-routing-recorded-c16-fresh-workers-v1`. The historical C4/C1 bundle,
capture and saved-run semantics remain available, and demo 09 remains pinned
to its original C4 export and exact AIPerf definitions.

The importer rechecked all 1,040 transported files and all 47 frozen launch
payload members. It pins accepted analysis, experiment plan, campaign, raw
AIPerf exports, specifications, qualification/discovery receipts, actual
manifests and reduced Pod identity/runtime excerpts. Full raw Pod environment
values stay private. An earlier local draft with full Pod objects was retained
privately at `results/demo-06-c16-draft-with-full-pods-20261105/` before
producing the final 35-file bundle.

The validator checks source metric/export equality, zero errors/overflow/record
cancellations, same model/runtime/corpus/engine controls, identical normalized
workload profiles, fresh worker UIDs per cell, exact physical GPU pairs and
the actual new KV cell's current Pod IPs/worker IDs/event connections. Old C1
event connectivity is not relabeled as C16 evidence. Policy manifests differ
only by frontend routing mode; topology manifests differ only in replica count
and permitted worker nodes. Realized trace mix and running/waiting pressure are
frozen separately in `realized-mix.json` and `pressure-proof.json`.

## What to say onstage

At C16, one→two RR workers changed aggregate throughput only
170.92→175.55 output tokens/s, while mean per-request decode rate rose 18.6%.
Cache-read share fell and p99 TTFT worsened from 3.81 to 15.40 seconds.
The added hardware did not improve every part of the user experience.

On the same two-worker topology, KV routing increased cache-read share from
87.15% to 91.03% and lowered p99 TTFT from 15.40 to 5.17 seconds, with roughly
flat aggregate throughput. There were 311 KV selections and positive total
predicted prefix overlap. Do not imply every selection had a positive hit.

Each p99 corresponds to about three requests in these 303/316/311-request
populations. These are N=1 observations in fixed order with different realized
trace/turn mixes, not stable production tail estimates or SLO guarantees.
Each canonical rate uses approximately 1,200 seconds, including drain after a
900-second admission. Concurrent tests used disjoint GPUs but shared CPU,
storage and network. The source report retains exact figures and clocks.

The one-worker profile averaged 1.61 running requests, maximum seven, and
median/p99 waiting zero. C16 means paced live trees, not 16 simultaneously
running HTTP requests. GPU utilization alone does not establish saturation.
**Do not claim a capacity knee or universal routing speedup.** Fresh workers
per cell also mean this was a controlled topology comparison, rather than
in-place manual scale-up retaining the original worker/cache. The C32 startup
attempt failed before profiling; it cannot create a second load point.

## Validation

- Fifteen routing checks pass, including seven new C16 cases and eight
  historical cases. Five metrics-primer checks pass without source changes.
- Existing normal-mode C4/C1 and metrics-09 runs still pass the shared capture
  completion validator with their original frozen files.
- Actual C16 main-panel PTY passed nine silent keypress gates, five command
  gates and four screen clears. Receipt:
  `results/demo-06-c16-keypress-20261105-a1/ui-validation.json`.
- New immutable main-panel capture:
  `demos/transcripts/recorded/06-routing/c16-20261105-a1/recorded-main.txt`,
  status **recorded_evidence_passed**, zero redactions, 0.435776375 seconds
  automatic playback. No new live measurement is implied by that capture.
- Historical routing's actual three-pane tmux layout was validated overnight;
  C16 uses the same layout with profile-aware observer contents, tested
  read-only. The actual C16 main panel was separately keypress-driven as above.
- Demo 09's full three-pane layout also passed through the parent execution
  path. [Metrics notes](METRICS.md) now cite those receipts instead of retaining
  the earlier blocked-layout gate.

## Questions and follow-ups

1. Narrate the C16 result within the 12-minute routing slot, retaining the
   distinction between a controlled topology comparison and operational
   in-place scale-up. The scripted capture is not a speaking rehearsal.
2. Decide which tail figures to emphasize. Median latency and cache-read share
   are less visually dramatic than p99 but the latter is supported by only
   about three requests per cell. No SLO threshold has been chosen here.
3. A future saturation curve requires separately qualified higher-load cells.
   Do not extrapolate from C16, splice in the older failed C32 attempt, or
   treat the new C32 readiness failure as a performance observation.
4. The fresh campaign found a harness readiness race: worker Ready and an
   initial `/v1/models` HTTP 200 can precede appearance of the exact model ID.
   A bounded exact-model discovery wait belongs in a fresh retry. This is
   evidence for a harness gate and documentation of readiness boundaries,
   rather than proof of a general model-registration defect.
5. CPU-tier routing visibility and final-runtime requalification remain
   separate from this actual KV-event connection/overlap result.

No upstream changes were submitted. Metric-denominator and placement
observability improvements remain in [the earlier routing notes](ROUTING.md).
The exact C32 race, prior overload-canary questions and upstream work already
found by the measurement agent are in
[the sweep notes](LOAD-SWEEP.md) and
[accepted C16 report](routing-sweep/C16-RESULTS.md).
