# Independent review: startup probe gating and early coding evidence

**Source review accepted; no blocker found.** This follows root's exact full-a3
lease/source-hold closeout at 2026-11-06 01:18:15Z. This reviewer edited only a
separate review test and review output, with no network, RPC, GPU, cluster or
candidate-freeze actions.

Reviewed `scripts/workshop_shadow_composed.py` SHA-256:
`14580c35ed0520a2b1546df21d4ab734f057d4244a63e9618aa15f3a7de0658c`.
The machine-readable receipt is
`results/shadow-startup-readiness-independent-review-20261105-a1/verification.json`.

The actual retained full-a3 observations are hash-pinned in the independent
tests. The earlier observation correctly fails the new probe-health predicate,
while its stable generation comparison to the later healthy observation passes.
The later observation passes both health and initial-coding validation. Harmless
nonidentity container status additions no longer cause identity rejection.

The startup loop waits for **engine-0, engine-1 and gms-server** to each be
Ready, Started and running before coding. Nonempty string container IDs and
exact integer zero restart counts are required. Thirty independent malformed
probe cases cover every container, false/numeric readiness, missing containers,
blank IDs, restarts, boolean restart counts and terminated/null running states.

Pod/container generation, restart count, active/standby roles, the assigned
GPU pair and the **whole GMS maps** remain guarded. Independent negatives cover
Pod and all container replacements, changed roles, weight layout/events,
nonweight KV state changes and added/missing GMS endpoints. The full-map check
uses canonical JSON, preserving type distinctions. The initial and final
GPU-pair guards remain in the actual wait control flow.

The baseline observation is saved before the first coding request. Each
validated returned payload is immediately saved to `full-ready-coding-N.json`
and the aggregate list. A failed second request preserves the first payload
and baseline without claiming complete readiness. Failure to collect the final
observation preserves all three completed responses. The final observation is
saved before graph, pair and startup-generation/GMS guards, so failures in each
of those guards retain both observations and all completed payloads.

**34 focused tests pass across three suites:** eight independent review tests,
six author startup/evidence tests and 20 existing composed tests. All eight
independent cases executed with the actual retained snapshots; they explicitly
skip when that historical evidence is unavailable. Request/cluster methods in
the host control-flow cases are test doubles and establish no new live coding
or GPU outcome.

An independent comparison against the accepted a3 critical-source inventory
finds only the composed host harness changed; the other **29 critical sources**
are byte-identical. After removing the two new helpers and restoring the prior
`wait_verified` AST, the entire module AST equals a3. Default freeze/render,
failover boundary logic, v6 backend/descriptor adapter and actual CPU program
are unchanged. Old candidate sources and evidence remain preserved.

Root may proceed with a fresh reviewed candidate after its current producer
identity and remaining RAM/cluster admission gates. This source-only acceptance
does not qualify optional cache staging on GPUs, initial serving, parked reader
in the new candidate, fault/recovery behavior, performance or SLO outcomes.
