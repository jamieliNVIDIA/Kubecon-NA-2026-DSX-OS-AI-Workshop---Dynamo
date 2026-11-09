# Request continuity under concurrent coding-stream load

Status: **both live C4 cases and independent paired verification passed**.
Migration disabled: **4/4 → 2/4** complete after the process fault. Migration
enabled: **4/4 → 4/4**, with separate correlated retry proof for both affected
streams. **Both owned cases are cleaned up**, with zero namespace Pods/GPU
claims and the scoped GPU lease released.
Eight focused offline/local-HTTP checks passed. This is a bounded integration qualification,
not an AgentX replay, throughput comparison, or SLO result.

## Review result

| Mode | Baseline complete | Fault batch complete | Affected streams |
| --- | ---: | ---: | --- |
| Migration disabled | 4/4 | 2/4 | Two streams emit SSE errors and have no valid finish |
| Migration enabled | 4/4 | 4/4 | Two streams each retry once on the prequalified peer, retaining 32 output tokens |

The paired verifier independently parsed **all 16 raw SSE captures**, compared
them with the event journals and cached summaries, verified the worker metadata
and frontend/peer identities, and checked identical engine/request/GPU controls.
There were **two process faults total**, one in each case, and **zero client
retries**. The immutable result is
`results/overnight-migration-paired-20261105-a1.json`.

The enabled affected streams' largest adjacent client content gaps were
**0.588 s and 0.587 s** across their whole responses. These are not isolated
worker handoff times. Their SSE worker attribution remains sticky; the two
response-correlated frontend traces identify the actual peer and retained
tokens. No latency SLO was selected or qualified.

The fault target was chosen from foreground SSE, rather than pinned in advance:
disabled faulted the worker on cp-0942; enabled faulted the worker on cp-0124.
Both cases used the same four physical GPUs and fixed workload/profile. This
supports the functional comparison, not a node-isolated timing comparison.

The [enabled ready-to-outcome console](../../demos/transcripts/live/05-request-continuity-load/20261105-enabled-a1/main-ready.txt)
is an exact suffix of the actual full console, beginning after offstage model
loading. The [disabled console](../../demos/transcripts/live/05-request-continuity-load/20261105-disabled-a1/main.txt)
has its separately verified recovery provenance. No recorded output is simulated.

The [shareable paired receipt](../receipts/2026-11-05-migration-load.json) freezes
the model/runtime/request identity, results, traces, 92 scientific file hashes,
cleanup verification and limits. The [capture index](../../demos/transcripts/live/05-request-continuity-load/README.md)
links both actual consoles. The enabled cleanup completed at **10:16 a.m.
Pacific**, after root confirmed the qualification process exited zero. Local
reverification accepted its final zero-Pod/zero-claim API receipts, found the
scoped lease absent, and rehashed all **92** paired scientific files unchanged
after cleanup. No network calls or additional inference/faults were performed
for this verification/export. No further live work is queued for this probe.

## Decisions

- Keep the existing demo 05 and its real recording unchanged. Use a separate
  `scripts/workshop_migration_load.py` harness for this follow-up.
- Run migration disabled and enabled **sequentially on the same four assigned
  H100s**, with fresh namespaces and engine instances for each. Eight-GPU
  simultaneous preparation would prevent other overnight work from running.
- Within each mode, send four concurrent copies of demo 05's deterministic
  coding request without a fault, then four identical concurrent requests with
  one foreground stream triggering a PID/start-time-checked EngineCore SIGKILL
  after 16 nonempty chunks. The workload and output budget remain unchanged.
- Select the fault target from the foreground stream's actual worker metadata;
  keep reading all streams while fault injection executes on another thread.
  No client retries, request pinning, or generated-code correctness claim.
- Require four outstanding HTTP clients when the fault is submitted. That is
  a client concurrency observation, not proof of four running engine requests,
  saturation, or four AgentX sessions.
- Report per-client TTFT, terminal outcome, and maximum adjacent content gap.
  Keep the exact worker handoff gap unavailable while SSE attribution remains
  first-write-wins; use the existing correlated frontend trace to prove retry.
- Use fixed-order, N=1 baseline/fault samples for diagnostic value. Shared EFS,
  CPU and network traffic from other assigned demos can overlap. Do not turn
  these numbers into a hardware-isolated performance comparison.

## Frozen configuration

The immutable per-run `load-spec.json` records request and model-lock hashes,
the four physical GPU UUIDs, mode, concurrency, fault gate and limitations.
`configs/dgd/workshop-request-continuity/overnight-gpu-assignment.json` pins
GPU6/7 on `kubecon-nke-site-cp-0124` and `kubecon-nke-site-cp-0942`.
The claim accepts only those four UUIDs; worker anti-affinity puts one TP2
worker on each node. Ready-time verification additionally checks the live DRA
allocation and `nvidia-smi` UUIDs against the exact node-specific pair.

The wrapper selects `.local/overnight-migration.gpu-lease`, preserving the
shared measurement lease and other workstreams. Cleanup deletes only the
mode's owned DGD/Pods/claims and retains cache, namespace and execution evidence.

## Current execution

First run: `results/overnight-migration-disabled-20261104-a1`.
The entire console is retained as `qualification-console.log`; actual SSE,
timestamps and fault receipts are saved per request, before/after Pod/claim/log
snapshots are saved per case, and the successful case will write
`load-qualification.json`. Frozen source copies and SHA-256 inventory are under
`source-snapshot/`.

The exact-cache CPU probe and client/server admission passed. Both workers
began loading the expected checkpoint. The observer then failed after about
259 seconds with repeated TLS handshake timeouts through the local API tunnel.
The coordinator independently observed a direct SSH timeout to the jump host,
identifying a shared external transport/VPN problem rather than a model
failure. The original console and failed command receipts are preserved.
The DGD/claims and scoped lease remain owned; resume readiness observation on
the same run after connectivity and physical assignments are re-audited.
Do not redeploy, change the frozen spec, or inject a fault during the outage.

At **7:34 a.m. Pacific on November 5**, the root's recovered-cluster audit
(`results/overnight-20261105-recovered-0733/audit.json`) confirmed the original
worker Pod UIDs `e8df5f55-ad09-4304-8a97-cd8c3fb5c97c` and
`f2a4a17a-768a-482b-b501-b849637c2aec`, Ready with zero restarts and their exact
node-specific GPU pairs. All 377 frozen observer files and original source pins
were reverified locally. A fresh canonical enabled preview is frozen at
`results/overnight-migration-enabled-20261105-a1`; its `matched-controls.json`
proves identical request bytes, model lock, hardware/load controls, normalized
engine deployment and claim, apart from migration limit and fresh resource
identities. The old overnight cutoff no longer applies: the user resumed the
original work interactively. The coordinator subsequently cleared GPU/kernel
health for all four assigned migration GPUs, with zero new Xids, in
`results/overnight-2026-11-04-coordinator/recovered-0739-health-clearance.json`
(SHA-256 `6dd9c69e898de8acb83e982bf029a4e564e13c04060e1041c21b5ec4843966b0`).
The separate Shadow GPU pair remains outside this clearance. Root was given the
exact frozen-run command because the child network-escalation hook rejected
its payload before executing anything.

### Recovered disabled result

Root executed the exact frozen disabled case successfully. All four baseline
requests completed normally. During the fault batch, foreground request 0 and
request 2 were served by worker `3830489717752731`; after its verified EngineCore
SIGKILL, both streams emitted an SSE 503 error, had no valid finish reason, and
ended. Requests 1 and 3 completed on the unchanged peer `2436651673063934`.
All four clients were outstanding at fault submission, **2.780 s** into the
batch. There was exactly one fault intent and no client retry.

All four fault-batch HTTP statuses were **200**, including the two failed
streams. Their failure appeared as an SSE error frame with code 503 and no
valid finish reason. This is a concrete observability point for the workshop:
HTTP status alone does not establish successful completion of a streaming
inference request; inspect the terminal stream outcome.

The eight raw SSE/event captures were independently parsed again, the foreground
fault proof was rederived, frontend/peer container identities were checked,
and the physical UUID receipt was matched. That verification passed and hashes
61 evidence files in `independent-local-verification.json`. This establishes
failure behavior with four concurrent clients, not capacity or an SLO.

**Recording incident:** before receiving root's execution-complete notice, the
child attempted a duplicate launch after a direct `kubectl /readyz` succeeded.
The Python-launched subprocess remained sandbox-blocked and failed at the first
readiness GET, before endpoint setup, client requests or fault injection.
Its shell redirection nevertheless overwrote the successful main console.
The traceback is preserved as `qualification-console-local-sandbox-attempt.log`
and the incident as `local-sandbox-attempt.json`; the successful raw SSE, fault,
Pod/claim/log, spec and qualification evidence remains intact and verified.
Root recovered the successful **1,137-byte console verbatim** from an earlier
retained same-chat tool output, rather than reconstructing it. The recovered
file is `qualification-console-recovered-from-tool.log`, SHA-256
`948607fb96ce1c8415e0b28d9e30635f3e1ee79646c2ed136967a2da8a79223b`.
An independent parser extracted that exact console from the frozen source
call/chunk JSON and byte-compared the result; all 61 prior scientific evidence
files were also rehashed unchanged. The supplementary
`console-recovery-supplemental-verification.json` references the prior receipt's
hash and frozen source record without altering either the original verification
or failed-attempt log. The recovered actual console is suitable for export with
that provenance; no text was invented and no fault/request was replayed.
The [shareable actual console](../../demos/transcripts/live/05-request-continuity-load/20261105-disabled-a1/main.txt)
and adjacent qualification receipt retain this recovery provenance and verified
cleanup. The enabled comparison is separate.
Root now exclusively owns further execution, cleanup and the fresh enabled case;
the child analyzes local evidence. Use exclusive/noclobber output creation for
future manually launched attempts, as the general capture utility already does.

Disabled cleanup completed at **7:49 a.m. Pacific**. The final successful API
receipts independently show zero Pods and zero ResourceClaims in its namespace;
`cleanup-verification.json` records their exact hashes. The fresh enabled run
then passed exact-cache validation and client/server admission and began
loading. Its console is created with shell noclobber. Root owns that live
execution; no child process should launch another copy.

Historical initial commands are shown below for provenance. The disabled run
has since been cleaned up; do not launch another sample into it. New experiments
need fresh run directories and the assigned cluster resources.

```bash
PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python \
  scripts/workshop_migration_load.py run \
  --run results/overnight-migration-disabled-20261104-a1 --mode disabled \
  --assignment configs/dgd/workshop-request-continuity/overnight-gpu-assignment.json

PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python \
  scripts/workshop_migration_load.py cleanup \
  --run results/overnight-migration-disabled-20261104-a1 --mode disabled \
  --assignment configs/dgd/workshop-request-continuity/overnight-gpu-assignment.json
```

Use a fresh run and `--mode enabled` for the other case, after scoped cleanup.
Existing result directories cannot be reused for another sample.

### Exact-source observer for the retained disabled case

The canonical intro UI needs additional immutable-claim and physical-allocation
guards. The disabled run already froze its earlier UI bytes, so it must not
rewrite those saved hashes to accept a newer implementation.

A private read-only tree was prepared at
`.local/frozen-observers/migration-disabled-20261104-a1/`. Its 377 static
scripts/configs/demo files include the exact previously captured UI, support,
load runner, migration probe/evidence, model lock and assignment. The template
and eight supporting modules also match the original execution-attempt hashes.
Only `.local` and `results` are symlinks to the existing workspace; no credentials
were copied or hashed. The original inherited `check_inputs()` passed against
the frozen copies. The existing demo and state files stayed byte-for-byte
unchanged, and validation made zero cluster calls.

Receipts are retained in the original run as `frozen-observer-tree.json` and
`frozen-observer-validation.json`; the full copied-file inventory is
`observer-provenance.json` inside the private tree.

The following is the historical exact-source resume command used for the old
interruption. Both cases have now completed and been cleaned up; **do not run
another sample in these directories**. The command is retained for provenance:

```bash
workshop_repo=/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop
observer_tree="$workshop_repo/.local/frozen-observers/migration-disabled-20261104-a1"
migration_run="$workshop_repo/results/overnight-migration-disabled-20261104-a1"

env -u WORKSHOP_ALLOCATION \
  PYTHONPYCACHEPREFIX="$workshop_repo/.local/pycache" \
  "$workshop_repo/.local/venv/bin/python" \
  "$observer_tree/scripts/workshop_migration_load.py" run \
  --run "$migration_run" --mode disabled \
  --assignment "$observer_tree/configs/dgd/workshop-request-continuity/overnight-gpu-assignment.json" \
  > "$migration_run/qualification-console-resume1.log" 2>&1
```

This resumes observation of the already applied DGD; it does not redeploy or
change the model/runtime/spec. Preserve the original failed console. If any
worker restarted during the outage, the existing readiness guard must fail;
retain that failure and clean up rather than treating it as a process-fault
result. Use the **same frozen runner** with `cleanup` replacing `run` for
ownership-checked cleanup of this old case.

Use the updated canonical runner for a **fresh enabled case** after cleanup.
Before sampling, check that its request SHA, model lock, engine arguments,
four physical GPU UUIDs and load-spec controls match disabled, apart from the
intended migration limit and fresh resource identities. Added hash/allocation
guards are observer improvements, not a new inference runtime. If actual
workload/runtime settings changed, stop the comparison and create a fresh
matched pair instead of silently combining configurations.

## Validation

Five focused checks pass: node/GPU rendering, malformed/duplicate assignment
rejection, HTTP 200/DONE alone insufficient, client-gap semantics, and an actual
local SSE server receiving exactly four overlapping POSTs with one fault
callback. A second capture in the same directory is rejected.

Three additional offline verifier tests pass: multiline SSE parsing,
unterminated-event rejection, and comparison normalization that still detects a
changed engine argument. The stronger verifier passes both actual cases and
requires a separate response-correlated retry trace for **each** affected
enabled stream. It derives worker identities from frozen metadata and Pod
snapshots and excludes mutable `demo.json`/state from its evidence inventory, so
subsequent cleanup does not invalidate the scientific hashes.

```bash
PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python -m unittest \
  discover -s tests -p test_workshop_migration_load.py -v

PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python -m unittest \
  discover -s tests -p test_verify_workshop_migration_load.py -v

PYTHONPYCACHEPREFIX=.local/pycache .local/venv/bin/python \
  scripts/verify_workshop_migration_load.py \
  --disabled results/overnight-migration-disabled-20261104-a1 \
  --enabled results/overnight-migration-enabled-20261105-a1 \
  --output results/NEW-migration-paired-verification.json
```

The sandbox blocks loopback sockets, so the local-HTTP test and real-cluster
run use the authorized network-capable execution mode. This is an execution
environment constraint, not a model/runtime failure.

## Open questions and upstream candidates

- **SSE attribution:** the pinned frontend retains the initial worker ID through
  migration. Add per-attempt or continuation-worker attribution so clients can
  measure actual last-old/first-peer content gaps. This is already a known
  upstream improvement candidate; the trace-based proof remains required here.
- **Detection telemetry:** emit timestamps for engine failure detection, retry
  scheduling, worker selection, first resumed token and first emitted client
  chunk. A single maximum content gap cannot attribute those phases.
- **Streaming success visibility:** document and surface terminal stream
  completion/error metrics alongside HTTP status. This diagnostic observed HTTP
  200 on both broken streams; an HTTP-only success dashboard would miss them.
- **Load/SLO follow-up:** select a production-relevant AgentX trace, offered
  concurrency and explicit SLO thresholds before an SLO/capacity experiment.
  These four short coding streams do not substitute for that work.
- **Arrivals versus in-flight survival:** all four diagnostic clients start
  before the process fault. This does not qualify new arrivals during stale
  discovery, queue admission, or overload/rejection. Keep that distinction when
  combining this result with the Guard experiment's observed discovery-lag 503.
- **Capacity recovery:** the surviving worker can finish streams while one
  worker remains unavailable. This probe does not establish when full capacity
  returns; that belongs to the separate Shadow/Snapshot timing and load work.
- **Tool/parser behavior:** this plain-text generation probe does not qualify
  tool-call streaming, partial structured arguments, grammar constraints,
  client/frontend disconnects or agent-side tool retries.
- **Local runner hardening, separate from Dynamo:** acquire the presenter lock
  before constructing a persistent demo object. The current main functions
  construct first; `Run` appends an attempt and the load wrapper saves view
  metadata before taking the exclusive presenter lock. Source inspection shows
  a possible state-write race for overlapping launches, although no concurrent
  state corruption or duplicate request/fault occurred in this incident. Keep
  console creation exclusive as well. This is a local demo-tool improvement,
  not an upstream inference correctness finding.
