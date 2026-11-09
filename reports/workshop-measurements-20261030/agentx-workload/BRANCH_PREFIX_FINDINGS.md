# AgentX parallel branches and exact prefix sharing

**Yes: AgentX contains concurrently scheduled child streams with large,
identical leading prefixes.** The most defensible workshop wording is
“parallel branches can share a large exact prefix,” rather than claiming all
named subagents automatically inherit the parent's entire conversation.

This was a CPU-only check of the existing complete corpus, the pinned source,
and the RR agent's completed preparation cache. No inference, new downloads,
GPU operations, workload edits, or benchmark tuning were performed.

## A concrete named-subagent example

Trace `208d6e28928b0b3d3b33db3c690173d15be3` is line 58 of the canonical
`traces.jsonl`. Consider the first requests of these recorded subagents:

| Field | Subagent 006 | Subagent 007 |
| --- | ---: | ---: |
| Agent ID | `subagent_006_80c02286` | `subagent_007_069d8a89` |
| Source outer request index, zero based | 110 | 111 |
| Source inner request index | 0 | 0 |
| Recorded input tokens | 77,248 | 77,248 |
| Canonical request start, milliseconds | 11,555,543 | 11,557,696 |
| Recorded request duration, milliseconds | 7,238 | 5,939 |

Their ordered `hash_ids` share **1,130 identical leading blocks**, each 64
tokens: **72,320 recorded token units**, about 94% of each input. The first
recorded request windows overlap by **5.085 seconds**. This compares the prefix
from position zero, not a set of common blocks or similar repository text.

The actual reconstructed cache strengthens that structural result: each first
turn contains one `user` message, and their content strings share **247,751
identical UTF-8 prefix bytes** out of 265,614 / 264,845 total bytes. Their full
arrays differ, as expected for branches that diverge after a common prefix.
The shared content prefix SHA256 is
`63dddb99cd8196f91263f6811e2eb262d60008163a27cff785b6e3304a86cae4`.

Both child IDs are in the same `SPAWN` branch attached to parent replay turn
96, with a `SPAWN_JOIN` prerequisite on turn 97. Its recorded branch start is
11,546,869 ms; these two children start at offsets 8.674 s and 10.827 s. The
group also contains other recorded subagent heads and inferred auxiliary
streams; this example is an explanation of two members, not a reduced workload.

## A full-context fork example, with a different provenance

Trace `085aacf44ac5428ad3c6b4f6cd431e083832`, line 16, contains replay children
`::fa:005` and `::fa:006`, mapped to source outer requests 377 and 378.
Their first inputs each have **10,087 identical leading blocks = 645,568
recorded token units**, and the first recorded requests overlap by **95.936 s**.

The prepared first-turn arrays are byte-for-byte equal: one user message each,
2,318,143 bytes as canonical JSON, including **2,210,134 identical UTF-8 content
bytes**. The identical content SHA256 is
`f5fcc314b6cc2fd22e58afc88a6f8232a7da69740e3b02ccfd5a7a50940285d7`.

These are **inferred parallel context chains from flattened recorded requests**,
not explicitly named Task/subagent markers. AIPerf models them as sibling SPAWN
streams. The trace proves concurrent same-prefix requests; it does not identify
whether the original application called them subagents, retries, or something
else. Use the named-subagent example above when that distinction matters.

## Scope of the finding

The scan used the actual prepared graph's spawning-parent turns and child
first-request source coordinates, preserving trace-local hash namespaces:

| Comparison | Pairs | At least 32,768 matching leading token units | Also overlapping first recorded requests |
| --- | ---: | ---: | ---: |
| Named subagent main vs its spawning parent request | 1,697 | 0 | 0 |
| Inferred context chain vs its spawning parent request | 7,753 | 390 | 139 |
| Two named subagent mains attached to the same parent turn | 17,018 | 2,421 | 226 |
| Siblings including at least one inferred chain | 503,397 | 2,435 | 49 |

The named-parent/child maximum in this scan is only **2,304** matching leading
token units; none reaches 8k. Named siblings can share a large prefix with each
other while their parent's prefix differs. Thus “fork the full parent context”
is a valid motivating application design, but is not a general fact established
by these named-subagent captures. Pair counts are neither independent samples
nor fractions of all runtime requests; large branch groups contribute many
pairs. They show existence, not a prevalence or performance estimate.

The original source text is not included. Recorded tool/system token
annotations are zero in these examples; that is missing original role evidence,
not proof that the original application had no system prompt. We cannot identify
the original common bytes as repository code rather than a long system prompt.
We **can** establish a large exact prefix in the reconstructed user messages;
this goes beyond semantic similarity or the mere presence of a shared model.

## What “concurrent” means here

The loader emits SPAWN branches with independent child sessions and recorded
offsets; the branch orchestrator schedules delayed starts independently and
gathers immediate dispatches concurrently. Joins gate a subsequent parent turn,
not each child's dispatch on its preceding sibling's completion. It can also
start captured overlapping SPAWN branches before the parent request completes.

These are source/graph scheduling facts and recorded-time overlaps. Actual
Super VL request overlap, worker placement, cache hits, and speedup require the
live benchmark evidence. Live latency, queueing, backend sequence limits, and
the 10-second global idle guard can change realized timing. A bounded profile
may not visit these particular source requests. No desired outcome is assumed.

SPAWN is a replay scheduling relationship: it starts its own recorded context,
whereas AIPerf's FORK mode clones an existing client message history. Exact
shared child payloads do not require FORK mode. The configured tree-wide
cache-bust marker is shared across descendants, preserving within-tree prefix
sharing; different sampled/recycled trees use distinct namespaces.

This supports the locality-versus-capacity teaching example: several parallel
requests can want the same cached prefix while spare compute is elsewhere.
It motivates asking whether another worker can obtain that prefix state.
It does not establish a KVCR transfer result, routing outcome, or integration
readiness claim.

## Reproduction and evidence

- [inspect_branch_prefixes.py](inspect_branch_prefixes.py) performs the complete
  read-only comparison; [branch-prefix-evidence.json](branch-prefix-evidence.json)
  records counts, representative coordinates, corpus and receipt hashes.
- The corpus remains pinned to revision
  `23f152f6f0f9399a85901b89a6458def0ef16729`, SHA256
  `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
- Existing RR preparation receipt:
  `results/workshop-rr-20261030-prep-1705/cpu-qualification-a3/receipt-c1.json`.
  Its embedded metadata preserves all 98,827 turns in 393 root and 9,450 child
  conversations. The explanatory scan does not alter that graph.
- Existing cache byte inspections and their exact scripts are alongside that
  receipt: `named-subagent-prefix-inspection.json` and
  `shared-prefix-inspection.json`. They read only selected existing mmap
  conversations, with page-prefault disabled in the inspection subprocess.
  [branch-prefix-byte-evidence.json](branch-prefix-byte-evidence.json) records
  their hashes and the complete text-free inspection results in this report.
- Pinned source references: `dataset/loader/weka_trace.py` lines 584, 1519,
  1941, 2084, 2158, and 2261; `dataset/loader/weka_synth_buf.py` lines 45 and
  130; `timing/branch_orchestrator.py` lines 460, 984, 1098, and 1312;
  `timing/conversation_source.py` lines 45–65.

Counts are in the recording's 64-token block units, not measured server-side
token usage. Cache byte checks validate reconstructed payloads, not original
captured application text or observed server cache residency.
