# Real-cluster main-panel recordings

These are actual executions of the presenter programs on the workshop cluster.
Each `main.txt` contains commands and responses from the main panel, with all
screens retained in order and terminal-control escapes removed. The capture
advanced automatically; presenter pauses are not included.

| Demo | Recording | Scope |
| --- | --- | --- |
| Single replica | [main.txt](01-single-replica/20261104-a2/main.txt) | Text-only eager Super VL TP2; deploy, corrected startup timing, model discovery, coding request |
| ModelExpress | [main.txt](02-modelexpress/20261108-a1/main.txt) | Revised flow with the intro server as the source: discovery through its `mx-source` Service, new replica Ready in 247.6 s against 493.0 s from storage, both-rank EFA copy summary, coding request |
| Earlier ModelExpress | [main.txt](02-modelexpress/20261104-a1/main.txt) | Earlier isolated workflow with a separate source: peer weights, both-rank EFA transfer evidence, one same-run storage/peer pair, coding request |
| Disaggregated serving | [main.txt](03-disaggregated/20261104-a1/main.txt) | Separate TP2 prefill/decode workers, coding request, worker IDs and clean KV-transfer counters |
| Operator-managed Snapshot | [main.txt](04-snapshot-dgd/demo-04-dgd-live-20261105-a3/main.txt) | Full DGD/NVMe presenter: live creating DGD, staged checkpoint, initial coding request, automatic Pod replacement and fresh final coding request; independently audited and cleaned |
| Earlier native Snapshot | [main.txt](04-snapshot/20261104-a1/main.txt) | Native vLLM same-node Pod replacement from a prepared NVMe artifact, new UID, exact GPUs, fresh READY inference |
| Request continuity | [main.txt](05-request-continuity/20261104-a2/main.txt) | Identical coding request with migration disabled/enabled; guarded EngineCore SIGKILL; interrupted stream versus successful response-correlated peer retry preserving 31 output tokens |
| KVCR | [main.txt](07-kvcr/20261105-a6/main.txt) | Experimental cross-node peer host-cache reuse: cold A, cached B, six matched blocks / 103,809,024 bytes / 4,224 reused tokens over EFA; qualified and cleaned; no automatic-routing or speedup claim |
| Shadow Engine | [main.txt](08-shadow-engine/20261108-a2/main.txt) | Qwen3-0.6B at TP1 on one H100 (cp-0942 gpu-1); active EngineCore killed, standby promoted, first verified response 1.7 s after the kill, new standby confirmed; two requests failed during the switch. Super VL TP2 remains blocked on GMS |

Additional November 5 evidence:

- [Resumed introduction](01-single-replica/20261105-overnight-a2/main.txt): actual
  main panel; original Kubernetes Ready clock excludes overnight observer delay.
- [Four-client migration comparison](05-request-continuity-load/README.md):
  disabled 2/4 versus enabled 4/4 completed after fault, both baselines 4/4.
- [Equal-four-GPU AgentX aggregate/P-D console package](03-disaggregated-agentx/20261105-a2/README.md):
  accepted original benchmark logs and transfer proof; throughput was similar,
  P/D improved observed tails and slowed medians. These are benchmark logs,
  separate from the presenter recording above.
- [C16 routing walkthrough](../recorded/06-routing/c16-20261105-a1/recorded-main.txt):
  accepted historical measurements, explicitly a recorded-evidence presenter.
- [KVCR qualification and cleanup receipt](../../../reports/receipts/2026-11-05-kvcr-peer-reuse.json):
  the fresh bound-child recording preserves its failed parent and explicitly
  records one B/frontend refresh; startup was prepared offstage.

The [current November 5 review](../../../reports/overnight-2026-11-04/REVIEW.md)
tracks new incomplete/failed attempts separately from the existing recordings.

The earlier [Snapshot DGD qualification transcript](04-snapshot-dgd/20261104-a3/qualification.txt)
contains actual deploy/verify/replace/cleanup CLI output: automatic same-node
replacement and fresh coding chat through the unchanged frontend, using EFS
and an experimental pinned-runtime adapter. Its
[manifest](04-snapshot-dgd/20261104-a3/qualification.json) records provenance and
timing. This is CLI qualification output. The full DGD/NVMe main-panel recording in
the table now passes its separate presenter and independent audit gates; the
earlier native NVMe recording remains unchanged.

The later [upstream-controller qualification](04-snapshot-dgd-upstream/20261104-a1/qualification.txt)
also passed the full DGD flow, retaining only the custom identity/offline bridge.
Its [manifest](04-snapshot-dgd-upstream/20261104-a1/qualification.json) includes
timing, frozen evidence hashes and the corrected observer's source-exit-137
false positive. The November 5 DGD/NVMe presenter now builds on this controller path;
the earlier v3 qualification and native presenter recording remain retained.

The [upstream-controller NVMe qualification](04-snapshot-dgd-upstream-nvme/20261104-a1/qualification.txt)
passes initial and automatic-replacement frontend coding inference from the same
pre-staged local artifact. Its
[manifest](04-snapshot-dgd-upstream-nvme/20261104-a1/qualification.json) records
**34.05/36.86 s agent restore**, **48/59 s Pod-to-Ready**, and **99.11 s deletion
intent to observed successful response**. Capture/copy/hash work is offstage.
This remains qualification output, separate from the existing presenter recording.

These Snapshot paths released KV cache before capture and demonstrate fresh
requests, without in-flight request recovery. The P/D recording
establishes functionality and does not compare throughput against aggregation.

Each attempt has a `capture.json` with the live outcome, timestamps, command,
hashes and timing scope. Raw PTY bytes, output timing offsets, and immutable
source/evidence copies remain in ignored private `results/workshop-demo-recordings/`
directories. Copy `main.txt` for booth content; use the timeline if playback
should later retain or shorten actual waits. No credentials were found in the
completed shareable captures.

The earlier single-replica attempt remains under `01-single-replica/20261104-a1/`
for history. Use the table's retake for the booth: it includes the corrected
nanosecond timestamp display and immutable evidence copies.

The [capture guide](../README.md) documents new recordings. The
[execution report](../../../reports/workshop-demo-recordings/STATUS.md) records
qualification, fixes, timing limits and cleanup separately from the transcripts.

Request continuity's initial `05-request-continuity/20261104-a1/` attempt is
retained as failed: the request continued, but its validator expected SSE
worker identity to change. The pinned runtime keeps the original identity.
Use the table's retake, whose response-correlated frontend trace proves the
peer selection. The exact client handoff gap remains unavailable; the maximum
adjacent content gap is a separate whole-response observation.
