# Original matched AgentX benchmark consoles

These are the actual November 5 benchmark outputs, copied byte-for-byte after
both original profiles passed independent qualification. They are not a
presenter PTY capture or a reconstructed demo.

- [P/D console](main.txt): 312 successful requests, zero errors/cancellations.
- [Aggregate console](aggregate-main.txt): 313 successful requests, zero errors/cancellations.
- [Comparison](comparison.md) and [full precision](comparison.json).
- [Independent acceptance](acceptance.json), [provenance](provenance.json) and
  [file hashes](sha256.json).
- [Canary source review](canary-source-review.json) and [scoped cleanup receipt](cleanup.json).
- Profiles: [aggregate](profile-aggregate.yaml), [P/D](profile-disaggregated.yaml).
- [Interpretation, controls and open questions](../../../../../reports/overnight-2026-11-04/disagg/RESULTS.md).

Same four H100s, Super VL, C16 **live session trees**, 900-second admission and
300-second bounded drain. Official throughput uses the full 1,200-second window.
The aggregate arm is KV-routed; default tuning remains fixed. P/D additionally
uses its role-specific NIXL/EFA settings and explicit DS SSM layout; aggregate's
layout variable is unset. Fixed order, N=1 and low realized concurrency limit
performance conclusions. No capacity or universal P/D speedup is established.

The original detached P/D runner finished while the laptop observer was
disconnected; it was collected without replay. The failed observer/controller
receipt remains preserved. The separate prefill KV-expiry counter is nonzero
and strongly consistent with unused canary leases; failed-transfer and
failed-notification deltas are zero. The matching upstream fix is already in
local fetched history as [Dynamo #15594](https://github.com/ai-dynamo/dynamo/pull/15594);
the pinned runtime remains unchanged. See the interpretation link above.

The benchmark export preserves streaming metrics/metadata, not raw SSE bodies
or generated answer text. The earlier [live P/D mechanism recording](../../03-disaggregated/20261104-a1/main.txt)
remains the separate coding-answer and state-handoff demonstration.
