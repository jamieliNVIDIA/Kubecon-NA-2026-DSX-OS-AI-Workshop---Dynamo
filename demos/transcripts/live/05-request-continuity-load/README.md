# Request continuity with four concurrent clients

| Mode | Baseline completed | After one process fault |
| --- | ---: | ---: |
| Disabled | 4/4 | 2/4 |
| Enabled | 4/4 | 4/4 |

- [Disabled actual console](20261105-disabled-a1/main.txt)
- [Enabled actual ready-to-outcome console](20261105-enabled-a1/main-ready.txt)
- [Enabled full startup and console](20261105-enabled-a1/main.txt)
- [Paired qualification receipt](../../../../reports/receipts/2026-11-05-migration-load.json)
- [Decisions, limits, verification and upstream candidates](../../../../reports/overnight-2026-11-04/MIGRATION.md)

The disabled console was recovered verbatim from a retained actual tool record
after a local redirection mistake; recovery is independently byte-verified and
explicit in its receipt. No output was invented or request/fault replayed.

All 16 actual SSE captures were independently parsed and matched to their event
journals and summaries. Both affected enabled streams have separate correlated
peer-retry proof, preserving 32 output tokens each. HTTP 200 alone did not reveal
the two failed disabled streams: their terminal SSE errors did.

Both owned cases were cleaned up, with zero Pods/GPU claims and a released
scoped lease. These fixed-order N=1 coding-stream tests establish functional
continuity; they do not qualify AgentX replay, capacity recovery or an SLO.
