# Offline diagnosis of the C1 KV qualification failure

**The qualification failed because it counted ZMQ sockets for all topics.**
Both worker registrations and both `kv-events` connections were present. The
guard collected six endpoints—two per topic—and required that total to equal
two. This is a harness false failure, not evidence of missing worker discovery.
It does not establish that KV events were processed or that routing improved.

No frozen helper, serving configuration or current text-only pilot was changed.
No network call or GPU run was made for this diagnosis.

## Reproduced evidence

Input: `results/workshop-textonly-predecessor-audit-20261103-a1/frontend-logs.json`,
SHA256 `5021cfcb56008d459bd932750e5b44957ffafb09175c8c257b3cad1a8de41331`.
Both embedded log-text hashes match their recorded hashes. The previous-container
log contains no discovery matches and does not affect the count.

The inspected `execute_router_pair.py` SHA256 is
`d946ab5138ddbcf9a119e49a2855088a8fbc2a2804a455a0e5a9d386f82eb191`, matching
the original controller's frozen input. Replaying its exact regexes offline gives:

| Original guard input | Observed |
| --- | --- |
| Registered worker IDs | `2514545568877449`, `8087467107042084` — count **2** |
| All matched ZMQ endpoints | **6** |
| `kv-events` endpoints only | **2** |
| `kv_metrics` endpoints | **2** |
| `active_sequences_events` endpoints | **2** |
| Original condition `len(ids) != 2 or len(endpoints) != 2` | **Rejects** because endpoints = 6 |

Proof locations below refer to ANSI-stripped lines in
`ft-agg-0-frontend-qjrck.log` from the saved bundle:

- Lines 300–301, `01:20:29.493Z`: two `kv_metrics` connections.
- Lines 322–323, `01:20:29.506860Z` / `.506948Z`: `kv-events` connected at
  `tcp://192.168.100.48:33445` and `tcp://192.168.92.226:43699`.
- Lines 327–328, `01:20:29.507849Z` / `.507870Z`: both worker IDs added at DP rank 0.
- Lines 333–334, `01:20:29.508Z`: two `active_sequences_events` connections.
- Line 344, `01:20:30.461592Z`: committed discovered model group with `members=2`.
- Lines 350, 355, 360 and 365, `01:20:37–38Z`: KV selector alternated between
  both workers for the four bounded qualification requests. Their HTTP responses
  were successful, with two output tokens each (lines 353, 358, 363 and 368).

The worker regex itself succeeds. The socket regex in
`qualify_discovery()` (lines 17–25 of the frozen helper) matches the common
`ZMQ single-consumer stream connected` prefix and endpoint, without checking the
`topic` field. The failure was therefore deterministic for these logs, rather
than a race waiting for a missing second worker/socket. Earlier zero-instance
discovery polls precede the worker registrations and do not override the later
positive evidence.

Machine-readable replay, source hashes, endpoint groups and proof lines:
`results/workshop-rr-offline-discovery-diagnosis-20261104-a1/diagnosis.json`.

## Minimal future harness fix

In a new immutable harness/run, parse connection records by topic and count
only `topic="kv-events"`. Retain the other topic counts as diagnostics. Prefer
the current frontend process and match the two expected worker Pod IPs, so old
reconnection logs cannot inflate a count. Save the qualification evidence before
raising an error, including the worker IDs and endpoint sets by topic; the old
function raises before writing its diagnostic JSON.

For example, collect endpoint/topic fields from each connection line, filter
to `kv-events`, then require the two expected registrations and two corresponding
event endpoints. Do not merely relax the check to "at least two arbitrary
sockets." A small offline regression fixture should include all three topics,
a genuinely missing KV endpoint and duplicate/reconnection lines.

Keep the later semantic acceptance gate: actual positive predicted cache overlap
and valid completed AgentX exports are still required. Connected sockets and
successful tiny smoke requests do not prove event delivery, cache-index contents
or performance. These smokes recorded `overlap_blocks=0`; the KV AgentX arm never
started. Preserve the failed attempt as failed, and run a fresh matched RR/KV
comparison after the independently authorized text-only startup pilot and any
needed fresh CPU-client qualification. The retained old client object reached
its deadline; do not reuse its old qualification marker.
