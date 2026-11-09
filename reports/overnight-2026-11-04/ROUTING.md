# Routing presenter: overnight decisions and review notes

**November 5 morning update:** the default presenter now uses all three
independently accepted C16 cells. Its separate bundle/profile and new capture
preserve every historical C4/C1 bundle, run and capture below. The same-load
C16 comparison supports the cache/locality discussion but does not establish
a capacity knee. C32 failed before profiling. See
[C16 implementation, validation and remaining questions](ROUTING-C16.md) and
the [updated demo guide](../../demos/routing/README.md).

The dated overnight notes below describe the earlier fallback preparation.

Updated November 4, 2026, 10:43 p.m. Pacific. No cluster changes or new GPU
benchmarks were performed by this workstream.

## Delivered

- `demos/06-routing/run.sh` and `scripts/workshop_routing_demo.py`: keypress-led
  recorded investigation with tmux, focused YAML, compact metrics, real event
  connection evidence and a routing→KVCR transition.
- Eleven hash-pinned evidence files: original C4 scale-out / C1 policy analyses,
  four original AIPerf exports, actual policy manifests, actual KV discovery
  receipt and original local-pullback verification receipts. The private source
  arm inventories were rechecked before copying. No source benchmark replay.
- Full normal-mode presenter capture:
  `demos/transcripts/recorded/06-routing/overnight-20261105-a1/recorded-main.txt`,
  status **recorded_evidence_passed**. Raw ANSI, source snapshots and evidence
  copies remain privately under
  `results/demo-recordings/06-routing-overnight-20261105-a1/`.
- Eight focused checks pass: metric/export consistency, file integrity/path
  boundaries, paired controls, positive overlap, focused configuration,
  read-only observations, no-cluster execution and actual CLI playback.
- Actual three-pane tmux rehearsal passed nine silent keypress gates, including
  five command submission gates; four investigation screens and both side
  panes completed. Validation receipt:
  `results/demo-06-routing-tmux-20261104-a2/ui-validation.json`.

## Decisions

**Use recorded measurements for this 12-minute slot.** The qualified AgentX
profiles require 15-minute admissions, initialization and primers per arm.
Preparing those offstage preserves the constant coding-agent workload while
leaving presentation time for interpreting the experiment. This runner has no
live deployment option, so it cannot disturb another workstream accidentally.

**Keep the two studies separate.** C4 changed capacity from one to two TP2
workers, retaining the original worker/cache and including a network-recovery
pause. C1 compared two fresh RR workers against two fresh KV workers with the
same canonical primer and default tuning. Different concurrency and serving
profiles prevent combining the tables into one before/after performance claim.

**Make no capacity-speedup claim from these pilots.** The C4 observation is
useful because adding a replica did not improve every metric; it does not
isolate routing. The C1 observation shows lower TTFT and higher reported cache
reuse, with almost unchanged active decode speed. Its canonical throughput
denominators are 900 versus 1,200 seconds. Their ratio is not a capacity result.
Partial replay trees and realized trace-mix differences remain explicit.

**Show minimum configuration and actual feedback evidence.** The excerpt is
derived from actual measured DGD schema paths. Full executable manifests remain
available, while the projection shows router mode, matching cache block size,
prefix caching and KV-event publication. Actual frontend event connections are
separate from positive predicted overlap and performance evidence. This does
not establish CPU-tier event visibility for an arbitrary offload configuration.

**End on the tradeoff.** Three parallel branches sharing an exact prefix make
the warm-but-busy / cold-but-idle choice tangible. The corpus's named-branch
example supplies structural evidence, rather than a runtime cache-hit claim.
KVCR can then mitigate the cost of choosing the colder worker. Request
migration is explicitly a separate mechanism.

## Fresh-sweep status and ownership

The cluster coordinator inspected the original higher-load controller and
reported that it exited at one-RR C32 on the no-restart qualification guard.
Its cleanup receipt showed no remaining owned GPU Pods/claims and no remote
lease. A lone potentially usable C16 one-RR observation cannot replace the
matched comparisons here. The parent was asked to assign a separate immutable
sweep repair; this presenter did not reuse, modify or restart that failed run.

The coordinator offered the original four routing GPUs, but this workstream
declined to claim or mutate them while the parent assigns the fresh experiment.
No local or remote reservation was acquired by the presenter workstream.
For current retry status, consult the parent review index and fresh sweep
report rather than treating this dated coordination note as live cluster state.

## Open questions for review

1. Replace either historical pilot table with a newly qualified higher-load
   pair when available. That needs a new recording profile/importer validating
   the 128-sequence engine cap, same-load controls, cache history, drain clocks,
   errors and censored stress outcomes. Never splice in only one arm.
2. Decide whether to show any short live routing placement probe alongside the
   offstage AgentX curves. That could make the feedback loop more tangible,
   but it would be a separate functional observation rather than the AgentX
   performance experiment. No such probe has been qualified here.
3. Decide how much of the denominator caveat should be spoken versus retained
   on the evidence screen. The current table shows both canonical values and
   denominator rows; the explanation does not manufacture a better ratio.
4. Validate the chosen CPU-offload integration's tier/residency events before
   demonstrating offload-aware router placement. The current recording only
   establishes connectivity for published KV events in its actual profile.
5. The automatic capture completed in **0.194627 s**. This proves software
   playback, not a 10-minute narrated rehearsal. Suggested speaking allocation
   is 2/3/3/2 minutes plus two minutes for discussion/transition.

## Potential upstream improvements

No new upstream bug was proven by this read-only presenter work. These are
specific candidates for investigation/documentation, not submitted fixes:

- **AIPerf metric provenance:** expose admission and actual drain duration next
  to canonical throughput, and make the rate denominator queryable in exports
  or comparison views. These pilot pairs demonstrate how different drain
  windows can mislead a seemingly simple capacity comparison.
- **Discovery qualification examples:** check `kv-events` connections against
  current worker identities/IPs by topic. A frontend also connects to metrics
  and sequence streams; counting all ZMQ connections as KV-event sources caused
  the earlier workshop harness to reject a valid configuration. The fresh
  campaign already contains the topic-aware local fix; assess whether upstream
  examples/tests need the same clarification rather than filing a router bug.
- **Placement observability:** provide a compact per-request diagnostic that
  associates worker selection, estimated reusable prefix and considered load
  with the client trace. That would make the tradeoff demonstrable without
  presenting internal router scoring options. This is a product improvement
  proposal; the existing experiments do not show a correctness failure.

## Review commands

```bash
./demos/06-routing/run.sh --rehearsal
./demos/06-routing/run.sh --preview
.local/venv/bin/python -B -m unittest discover -s tests -p test_workshop_routing_demo.py -v
```
