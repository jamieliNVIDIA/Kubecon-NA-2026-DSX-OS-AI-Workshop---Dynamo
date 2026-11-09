# Request-continuity presenter demo

**Passed live on November 4, 2026.** With migration disabled, an EngineCore
SIGKILL interrupted the streaming response. With migration enabled, the same
client response continued through a retry to its already-qualified peer,
preserving 31 output tokens, then ended with `stop` and no stream error.
Both cases used one generation POST and identical coding-request JSON.

[Actual main-panel recording](../demos/transcripts/live/05-request-continuity/20261104-a2/main.txt)
and [qualification receipt](receipts/2026-11-04-request-continuity.json) retain
the outcomes, source/evidence hashes and cleanup proof.

Implementation: [demo guide](../demos/request_continuity/README.md),
[runner](../demos/request_continuity/demo.py), and
[PID-guarded probe](../demos/request_continuity/probe.py).

## DGD task list

Required workflow from the DGD skill; the existing qualified single-replica
template is the starting point, through `workshop_demo.render`.

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
- [x] Hand off to `deploy_dynamo` or `kubectl apply`

Requirements: locked Super VL, vLLM/Dynamo image by digest, Kubernetes/DRA,
two independent aggregated two-worker deployments, each worker TP2 H100.
Eight H100s total while prepared. No engine, model, or cluster upgrades.

## Evidence contract

Make one streaming HTTP request in each case, with identical request JSON and
zero client retries. Wait for 16 nonempty visible content chunks. Use SSE worker
identity joined to the current Pod UID through DynamoWorkerMetadata; kill only
the inspected EngineCore PID with unchanged Linux process start time.

The disabled case must expose a failed/incomplete response. The enabled case
must preserve the response ID, produce content on the already-qualified peer,
then end with a successful finish and DONE without an error frame or read
failure. The unfaulted frontend and peer must retain Pod/container identities
and readiness. Signal acknowledgement, raw SSE, timestamped events and before/
after logs are retained. Ambiguous fault acknowledgement stops qualification;
there is no automatic repeat fault.

SSE worker attribution is first-write-wins in the pinned runtime. The enabled
case therefore requires a response-correlated HTTP trace linking the failed
worker to exactly one retry, a positive retained-output-token count and a
decode-worker selection of the qualified peer. The trace parser rejects logs
from another request, unknown peers, additional retries and zero retained
tokens. Source:
[`RequestTracker::record_once_u64`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/protocols/common/timing.rs).

The exact last-old/first-peer client gap is unavailable with that stale SSE
field. Maximum adjacent client content gap across the whole response is
reported separately and does not isolate the handoff or establish an SLO. The
failed worker may start cold recovery in the background during the next case.
The cases are a functional demonstration, not a controlled performance test.

## Validation

Thirteen scoped offline tests passed: renderer invariants, PID reuse and multiple
EngineCore rejection, stale metadata ownership, survivor lifecycle, real local
HTTP streaming while fault injection executes, truncated/error responses,
rehearsal resume, frozen-input/interrupted-case rejection, container isolation
and foreign-lease/cleanup refusal, plus response-correlated retry evidence with
negative cases. Eleven capture tests and ten existing intro
demo tests also passed. The real three-pane tmux layout, quiet Space gates and
`q` exit before the first case were exercised locally. Both live manifests
passed client/server admission.

The first live attempt, `results/workshop-continuity-live-20261104-a1`, exposed
an error frame plus DONE without a finish in the disabled case. The enabled
request completed with `stop`, the same response ID and no stream error. Its
frontend trace links failed worker `1636253979746942` to survivor
`2117973916849040`, preserving 31 output tokens. Both unfaulted Pod/container
identities and readiness survived. Maximum adjacent client content gap was
1.182 seconds across the enabled response; this is not an exact handoff gap.

The original main-panel recording remains explicitly failed: its validator
required SSE worker identity to change. A separate `qualified-review-v2/`
contains the revised proofs from the unchanged raw evidence; the original
capture and evidence snapshot were not rewritten.

The fresh v2 run, `results/workshop-continuity-live-20261104-a2`, passed the full
corrected presenter flow and recording. Its 12-test coding request uses a
1024-token cap; both arms use identical JSON. Disabled worker
`4446967580483451` was killed after visible output, producing a service-unavailable
error, DONE and no successful finish. Enabled worker `7594699037439315` was
killed at the same content-chunk gate. The correlated retry selected the
already-qualified `7809818136875612`, retaining 31 output tokens. Response
`chatcmpl-94659c9d-eb97-4a46-8666-f8c30d746c2b` continued to `stop` plus DONE,
without a stream/read error or replacement of the frontend or surviving
worker. Maximum adjacent client content gap was 0.511 seconds across the whole
enabled response; the exact handoff gap is unavailable.

With both pairs loading concurrently, logged weight-loading durations were
roughly seventeen minutes, then engine initialization/readiness followed.
Allow at least 25 minutes offstage on this EFS setup. These observations are
not a controlled startup benchmark or general duration bound.

The first attempt's resources were verified cleaned before a same-owner lease
transfer to a2. Final a2 cleanup completed at **22:45:09 UTC**: zero continuity
Pods and GPU claims, both DGDs removed, and the lease released. An independent
namespace-scoped audit also found zero Pods/claims/DGDs. The waiting Snapshot
workstream acquired the reservation immediately afterwards and its ownership
was preserved. No global-idle claim is made after that handoff.

The successful capture's immutable evidence and source hashes were rechecked
after cleanup. No credentials were found in its shareable transcript. Load/SLO
qualification, exact per-attempt gap telemetry and richer tool/parser request
shapes remain outside this standalone demonstration.
