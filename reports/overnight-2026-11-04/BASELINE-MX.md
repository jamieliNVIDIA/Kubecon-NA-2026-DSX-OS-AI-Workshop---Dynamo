# Baseline and ModelExpress overnight recapture

Status: **closed: intro live capture/cleanup passed; fresh MX prime incomplete; all own GPU resources cleaned**. Source-only startup completed, but the native observer lost API access before terminal readiness. No fresh peer arm, comparison or coding inference was executed. Historical successful MX recordings remain separate and unchanged.

## Scope and decisions

- Re-record the actual demo 1 presenter after the compact YAML/resource-table update, then the current eager peer-weights ModelExpress presenter. Preserve all earlier live recordings and failed attempts.
- Keep the exact Super VL model/revision, pinned runtime and eager text-only configuration from the executable demos. These recaptures are not the compiled startup-optimization matrix.
- ModelExpress remains a cross-node EFA experiment: source and native/peer targets must be on different nodes. A proposed same-node target was rejected during allocation because it would change the transport demonstration.
- Main-panel output will be captured from the actual program through `scripts/capture_workshop_demo.py`, with immutable private source/evidence copies and a fresh shareable attempt directory. No resource/log pane scraping.
- Live phase timings under the overnight shared-cluster schedule are functional observations. Shared EFS/network activity is uncontrolled; do not treat the result as a performance-isolated comparison or a repeated distribution.

## Assigned resources

Allocation granted by the cluster coordinator November 4, Pacific:

| Role | Node | Device | GPU UUID |
| --- | --- | --- | --- |
| Intro / MX source | cp-0124 | gpu0 | GPU-c220c1d0-843c-ce3c-b1f9-3ad67af277d7 |
| Intro / MX source | cp-0124 | gpu2 | GPU-ea836524-584e-0719-d7bb-0de129f5e7d3 |
| MX native / peer target | cp-0198 | gpu6 | GPU-3790a112-5f2d-70e8-e65f-30dfa66869e0 |
| MX native / peer target | cp-0198 | gpu7 | GPU-c78f34dc-e790-cfc7-1745-be1cb2e98409 |

Scoped lease: `.local/overnight-baseline-mx.gpu-lease`. Shared allocation support is implemented in `scripts/workshop_demo_allocation.py`; `WORKSHOP_ALLOCATION` loads a frozen plan and binds exact GPU UUID selectors and node placement. Offline checks proved all four role assignments, matching native/peer engine signatures and frozen allocation. Other agents have disjoint exact GPU assignments. No global idle requirement or global cleanup is used.

## Acceptance

1. Demo 1: actual compact opening excerpt, successful deployment/readiness, unchanged pinned image and exact allocated GPU pair, startup summary before endpoint/request, correct coding response, immutable main-panel text and source/evidence hashes.
2. ModelExpress: matched native/peer engine signature and target placement; same source UID throughout; positive receiving/completion receipts on both TP ranks; NIXL LIBFABRIC/EFA and no storage fallback; successful fresh coding response.
3. Save request-command start and observed-response end separately from startup. Do not count presenter pauses or preparation as engine startup.
4. Scoped cleanup proves this run's Pods and claims are gone while preserving concurrent work, model storage and namespaces.

## Open questions and possible improvements

- Shared run-scoped allocation support now resolves the parallel-capture gap. Its exact UUID/node constraints and frozen plan are retained with each capture; no lease-only bypass was used.
- Intro request acceptance currently checks nonempty content/model identity. Independently inspect the actual `add(a, b)` response; a correctness check should not be inferred solely from HTTP success.
- Current request receipt records command start and the presenter records observed response time, but there is no separately named request timing artifact. Retain a derived receipt with clear boundaries rather than relabeling startup timing.
- Publicly obtainable runtime artifacts remain a separate take-home qualification question. These captures use the existing private workshop runtime.

## Validation and output

Offline checks completed before live execution:

- `python -B -m unittest discover -s tests -p test_workshop_demo.py`: **15 passed**.
- `python -B -m unittest discover -s tests -p test_modelexpress_demo.py`: **6 passed**.
- Fresh immutable rehearsal capture for each runner: **both `rehearsal_passed`**, zero redactions, explicitly simulated, timing summary before the request body.
- Intro opening teaching screen maximum width: **66 characters**. Including the transition and step timing it occupies 48 text lines in this capture.
- MX initially had a **297-character** maximum line from absolute command paths. A coordinated opt-in `compact_output=True` after base initialization reduces this to **175** in the assigned rehearsal; its six existing regression checks pass. Execution arguments/receipts remain unchanged.

Local rehearsal outputs:

- `results/overnight-intro-rehearsal-20261104-a1-capture/rehearsal-main.txt`
- `results/overnight-mx-rehearsal-20261104-a1-capture/rehearsal-main.txt`

Live attempt, preserved as failed:

- Run: `results/overnight-intro-live-20261104-a1`.
- Namespace: `dynamo-ft-r610-49088d2e-demo`.
- Capture: `demos/transcripts/live/01-single-replica/20261105-overnight-a1/`.
- Model cache and client/server dry-runs passed; actual compact YAML was printed and the worker is loading on the assigned pair.
- A sandboxed read-only preflight could not access the loopback API tunnel (`operation not permitted`). The authorized network-enabled retry passed; no workload was submitted during that failed preflight.
- At approximately 22:49–22:51 Pacific, log access first timed out, followed by a TLS-handshake timeout on Pod inventory. The presenter exited 1. The capture remains `failed`, with `failed-main.txt` and frozen source/evidence.
- The cluster coordinator independently found both API `/readyz` and a fresh SSH connection to the jump host unavailable while the local SSH master was alive. This points to the external VPN/transport path; it is not proof of an engine/GPU failure.
- Preserve the original DGD, apply timestamp and scoped lease. No blind retry, replacement deployment, global cleanup or independent tunnel restart was performed.
- Central transport recovery and a fresh ownership audit are required before any resume. A same-run recording will explicitly identify its pre-existing startup and the API outage; a later fresh run is needed for an uninterrupted startup recording.
- Final inference, immutable-evidence checks and scoped cleanup are pending.


## Frozen intro observer and exact recovery commands

Canonical UI guard fixes can require metadata absent from this pre-guard run.
The original observer tree is therefore frozen read-only at:

`results/overnight-baseline-mx-control/intro-a1-observer/`

Its `observer-manifest.json` records **25/25** capture-source hashes and
**114/114** original run script hashes. Configs are copied locally; the actual
model lock and DGD template match the original demo hashes. A pure offline render
reproduced the exact DGD and GPU claim. Only `.local` and `results` are symlinked
to the original workspace; no credentials were copied. The physical scoped
lease resolves to the original lease.

**Gate:** do not execute the following until the coordinator confirms transport
recovery and re-audits the existing namespace, claims, GPU identities and workload
health. This resumes the original run; it does not repeat deployment/startup.
The output attempt must still be absent.

```bash
WORKSHOP_ALLOCATION=/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-baseline-mx-control/allocation.json \
  /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/.local/venv/bin/python -B \
  /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-baseline-mx-control/intro-a1-observer/scripts/capture_workshop_demo.py \
  --demo 01-single-replica \
  --run /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-intro-live-20261104-a1 \
  --output /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/demos/transcripts/live/01-single-replica/20261105-overnight-a2 \
  --quiet --startup-timeout 1800 --capture-timeout 3600 --port 18100
```

If cleanup is appropriate after the same ownership gate, use the original
observer as well:

```bash
WORKSHOP_ALLOCATION=/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-baseline-mx-control/allocation.json \
  /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/.local/venv/bin/python -B \
  /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-baseline-mx-control/intro-a1-observer/scripts/workshop_demo.py \
  cleanup --auto \
  --run /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop/results/overnight-intro-live-20261104-a1
```

The upcoming fresh MX run uses the canonical guarded source, rather than
adopting this old intro run or its startup evidence.

## Canonical post-guard check and deferred MX commands

After the parent landed the new claim hash and observed-allocation guards,
fresh assigned rehearsals of both canonical runners passed. The intro capture
froze nine evidence files; the MX rehearsal froze 20, including the complete
source/native/peer/DGD, both claims and source Service. Both claim hashes match
the executable files. These are offline checks, not new live qualification.

After transport recovery, ownership audit, successful intro finish/inspection,
and verified intro cleanup, the assigned source/target pairs can be used for
the fresh MX investigation below. Do not start it while the intro still owns
its source pair or lease.

```bash
cd /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop
export WORKSHOP_ALLOCATION="$PWD/results/overnight-baseline-mx-control/allocation.json"
./demos/02-modelexpress/run.sh prime --plain --auto \
  --run results/overnight-mx-live-20261104-a1 --timeout 1800 --port 18101
.local/venv/bin/python -B scripts/capture_workshop_demo.py \
  --demo 02-modelexpress \
  --run results/overnight-mx-live-20261104-a1 \
  --output demos/transcripts/live/02-modelexpress/20261105-overnight-a1 \
  --quiet --startup-timeout 1800 --capture-timeout 3600 --port 18101
```

The private independent checker is
`results/overnight-baseline-mx-control/validate_capture.py`. It verifies every
frozen evidence hash, the actual returned `add` function via AST without code
execution, and request command-start to observed-response boundaries. Run it
only after a `live_passed` capture; it creates a fresh adjacent qualification
receipt. It does not infer transfer proof or public-runtime portability.

A concrete observer improvement from the failure is to preserve the last valid
phase observations with a stale/disconnected marker and bounded transport
retries. The current observer replaced a failed log fetch with empty text,
causing model loading to appear pending again before the next API error ended
the presenter. This is a workshop-tooling issue, not a demonstrated Dynamo
engine bug. Readiness must remain unknown until observed after reconnection.


## Implemented observer recovery guard (offline follow-up)

The canonical intro/MX startup observer now uses `bounded-reads-v1`:

- Startup API/log reads have a 10-second per-read cap and a 60-second consecutive
  transport-failure budget, always bounded by the original startup deadline.
  Only read operations retry. Deployment, fault injection, HTTP generation and
  cleanup are never replayed by this change.
- A failed read preserves the last valid phase values and log snapshot, with an
  explicit stale/disconnected label and **current readiness unknown**. Readiness
  is accepted only after fresh Pod/log/allocation reads and the existing image,
  GPU count and physical UUID checks.
- Every successful log observation is saved under its worker UID, with the last
  observed log timestamp, content hash and apply/arm context. Replacement UID or
  changed MX arm invalidates the current cache; history stays available. A
  previously qualified Ready worker cannot silently give its clock to a
  replacement. UID changes during a log read fail closed.
- Pending workers without container status do not trigger premature log calls.
  Image/config errors, failed/restarted/terminated containers, authorization,
  malformed API responses and identity failures refuse immediately.
- Read-only side panes can display a hash-verified stale log before `worker.log`
  exists. They do not write run state and invalidate in-memory logs when the
  startup/arm context changes. The recorder freezes the UID-bound log files.

This is a workshop observer fix, not an upstream inference-engine bugfix or a
new live qualification. Other demos with their own startup loops retain their
own retry behavior. The frozen intro a1 observer and failed recording are
unchanged; resuming that historical attempt still uses its exact original code.
The canonical version is for fresh runs after transport recovery/audit.

Source transition:

- a1 frozen `workshop_demo.py`: `fc92abf28a65d452f7f98f50bbf2aa4e840d7545a71ad9bc0be18c5e6a5e354a`.
- canonical `workshop_demo.py`: `fba4eb29802c1018c6d8fe6cfb4bbc74c810003e2d01927ff9aa0136be35bac5`.

Focused regression tests cover intermittent read failure and recovery, budget
exhaustion, the original timeout bound, UID replacement/races, a Pending worker,
fatal API/container errors, retained physical-GPU checks, read-only stale log
rendering, corrupted-cache rejection and MX arm/context changes. They use mocked
read responses and a controlled clock; no cluster actions were performed.

Final related validation: **47 tests passed** across the new observer suite,
intro UI, MX and main-panel capture. Python AST parsing and scoped
`git diff --check` passed. Exact command:

```bash
PYTHONPATH=tests:scripts .local/venv/bin/python -B -m unittest \
  test_workshop_observer test_workshop_demo test_modelexpress_demo test_workshop_capture
```

Local log: `results/overnight-baseline-mx-control/observer-related-tests-20261104-a1.log`.
Source-transition receipt:
`results/overnight-baseline-mx-control/observer-source-transition.json`.


## November 5 morning resumption

The user resumed work after restoring VPN connectivity; the old overnight cutoff
is no longer a stop/cleanup instruction. The 07:34 Pacific recovery audit at
`results/overnight-20261105-recovered-0733/` found the original intro worker
`demo-inference-0-agg-p6sk6`, UID
`eb1a7465-455f-45c9-bbe4-9698f3f9c604`, Ready with zero restarts on the exact
assigned cp-0124 gpu0/gpu2 pair. The scoped lease still names the original run;
the MX destination pair is free. Coordinator clearance permits continuing the
original intro without redeployment; a separate health audit gates fresh MX.

All 290 files in the frozen original observer tree still match its manifest.
The subagent's network command did not start because the tool hook rejected the
permission payload. This is an execution-tool plumbing error, not a new cluster
failure or denial of the user's authorization. The parent has the exact command
above and can run the network process while this agent checks its local output.
No a2 capture or workload mutation was created by that rejected call.

A successful same-run recording will retain the original apply timestamp and
explicitly mark startup as pre-existing. Its morning observed-readiness time
includes the overnight observation gap; report the Kubernetes Ready transition
separately and do not claim a fresh uninterrupted startup measurement.

At 07:39 Pacific the coordinator also cleared the exact four intro/MX GPUs:
`results/overnight-2026-11-04-coordinator/recovered-0739-health-clearance.json`,
SHA256 `6dd9c69e898de8acb83e982bf029a4e564e13c04060e1041c21b5ec4843966b0`,
with `workstreams.baseline_mx.status=passed`. XML/kernel checks succeeded,
node conditions did not change, and no new Xids affected cp-0124 gpu0/gpu2 or
cp-0198 gpu6/gpu7. Separate Shadow Xid31 findings concern its different pair.
Fresh MX can follow successful intro inspection and scoped cleanup on the
already assigned cross-node pairs.

The subagent execution hook also rejected a read-only Bash MCP probe, so no
alternate process was launched. Root execution of the supplied command remains
the immediate dependency; local artifact validation is ready. The independent
intro checker now accepts `--placement-audit` pointing at the 07:34 audit and
requires captured worker/claim UIDs and exact GPU UUID resolution to match it.


## Intro a2 resumed result — passed

Actual main panel:
`demos/transcripts/live/01-single-replica/20261105-overnight-a2/main.txt`.
The adjacent `capture.json` reports `live_passed` and explicitly records
pre-existing startup. `qualification.json` independently verifies all 12 frozen
evidence files, original worker/claim UIDs, exact assigned GPU UUIDs and a
correct `add(a, b)` function by AST inspection without executing generated code.

| Boundary | Observation |
| --- | ---: |
| Original apply → Kubernetes worker Ready | 1,459.397 s |
| Logged model loading, slowest TP rank | 1,246.701 s |
| Logged engine initialization | 83.34 s |
| Original apply → morning observed readiness | 32,251.752 s |
| Coding request command start → observed response | 2.358812 s |

The worker's Ready transition is `2026-11-05T07:09:07Z`, before client
connectivity recovered. The morning observation clock includes the overnight
transport outage and is not startup time. Model loading overlapped independent
EFS-heavy tests, so these startup values are functional observations rather
than an isolated performance comparison. Logged phases may overlap.

The original Pod UID is unchanged with zero restarts, and the presenter retained
the original apply timestamp rather than reapplying the DGD. Startup summary
still precedes the endpoint/request. The returned text is exactly:

```python
def add(a, b):
    return a + b
```

The compact projection now has actual-cluster evidence. The recording is useful
for reviewing the UI and service flow; a fresh uninterrupted canonical capture
would make a cleaner booth startup example. That optional retake does not
replace or rewrite this resumed attempt or the failed a1 evidence.

The parent has the exact frozen-source scoped-cleanup command and fresh MX
priming command. The subagent execution hook still prevents direct network
execution, so root runs those processes while this agent reviews local evidence.


## Intro cleanup and fresh MX preparation

The parent's frozen-source cleanup completed successfully. Subsequent API
receipts show zero intro Pods and zero GPU claims; independent `cleanup.json`
is adjacent to the a2 recording, with three command receipts frozen privately.
Cleanup timestamp: `2026-11-05T15:49:16.875416Z`. Namespace/model storage remain.

The fresh live-mode MX manifests were rendered and independently checked without
cluster calls in `results/overnight-mx-live-20261104-a1`, namespace
`dynamo-ft-r610-e969b3c7-demo`. All seven inputs, target-claim hash, source/target
node and UUID selectors, and source/native/peer engine signatures match.
The parent then launched actual offstage priming; its log is
`prime-morning-20261105-a1.log` in that run. Model-cache verification passed and
the source startup is active on the assigned pair with the canonical observer.

Root is the sole network executor to avoid duplicate launches while subagent
execution hooks fail. This agent monitors and validates local artifacts.
Actual peer capture remains gated on the prime process succeeding and the
source/native identities, actual allocation, matching configuration and
source-only remaining claims passing independent review.
The private review checker is
`results/overnight-baseline-mx-control/validate_mx_prime.py`.

Presentation decision still open: the observed 24-minute intro startup exceeds
section 1.4's six-minute deployment slot, and the fresh MX source is loading
storage weights at roughly 60–70 MB/s during concurrent cluster tests. Eager
execution alone does not guarantee a fast storage-backed intro. Choose a
prepared/recorded intro, or separately qualify faster checkpoint staging (for
example existing node-local storage) and isolated startup behavior. Such a
change needs its own frozen profile/run and must not alter the running matched
MX baseline. This is an environment and pacing improvement, not a demonstrated
Dynamo engine bug.

Interpretation limit: the InstantTensor progress rate is application-level
weight-loading throughput, not an independent EFS/device bandwidth measurement.
The vLLM model-loading phase can include tensor preparation/processing as well
as I/O. Separate those costs before attributing the entire delay to storage or
putting a bandwidth-based causal claim on a slide.


## Current closeout: fresh MX prime interrupted

Root's prime process exited 1. The source arm completed real startup and exact
physical allocation checks. The native arm began on its assigned node, but its
last successful observation was `2026-11-05T16:23:30.736015Z` (08:23 Pacific),
with model loading still in progress. Subsequent reads timed out and then
reported `127.0.0.1:16443` connection refused. That establishes an unavailable
local API-tunnel endpoint; it does not establish an inference-engine failure or
a particular VPN cause. No fatal engine exception was present in the last saved
native log. Later server state is unknown from this observer.

| Item | Result |
| --- | --- |
| Intro a2 actual compact main panel and fresh coding response | Passed; original Pod/claim/UUID independently verified |
| Intro scoped cleanup | Passed; zero own Pods/claims, namespace/cache retained |
| Current canonical UI/MX/capture checks | Passed offline; 47 related checks and parent full suite separately recorded |
| Fresh MX source startup | Passed: 1,420.993 s Ready; 1,241.134 s model loading; 84.19 s engine init |
| Fresh MX native baseline | Observer interrupted before a terminal Ready record |
| Fresh MX peer loading / matched comparison / coding inference | Not executed; no new qualification |
| Historical MX peer-weight demo | Earlier successful recording remains valid in its documented scope |
| Fresh MX cleanup | Passed; both owned graphs deleted, zero Pods/claims and exact scoped lease released |

The fresh attempt never reached `primed=true`; its only completed arm is
`source`, and `peer` is absent from `arm_intents`. Do not use the source's
InstantTensor/storage preparation time as a native baseline, manufacture a
peer result, or silently relabel the historical MX recording as this attempt.

Immutable private evidence before cleanup:

- `results/overnight-baseline-mx-control/mx-interrupted-evidence-20261105-a1/`
- 771 files / 55,071,777 bytes, including actual source hashes, source Ready and
  allocation proof, last native UID-bound log, API failures and the prime log.
- Manifest SHA256:
  `6cde5e463f6c184da499ce0c90710cbee72723662b3474391fa47717c9cc0262`.
- Shareable summary receipt:
  `reports/receipts/2026-11-05-workshop-mx-prime-interruption.json`.

The canonical observer correctly kept the last successful phase/log evidence
explicitly stale, did not infer Ready, and retained the owned lease/resources.
The live failure also exposes a remaining clock limit: saved retry attempts span
6,227 wall-clock seconds between last success and exit despite the configured
60-second monotonic budget. Suspension/scheduling is a candidate explanation;
the receipts do not establish its cause. Do not claim a strict 60-second wall
exit. A follow-up should bound both elapsed wall time and active monotonic time,
record both clocks, and test a wall-clock jump or host-suspend/re-entry case.
No such timing change was made during this failed attempt.

For long offstage preparation, a cluster-side controller with durable receipts
would avoid tying observation to a sleeping laptop/VPN tunnel; that is an
operational improvement to evaluate separately, not a Dynamo engine bug.

Root is the sole network executor. After preserving evidence, root launched
canonical scoped cleanup (`cleanup-20261105-a1.log`) on the owned namespace. No
fresh peer or benchmark runs will be started in this closeout window.


## Final cleanup — independently passed

Root's actual cleanup completed at `2026-11-05T18:18:58.068554Z`
(10:18:58 Pacific). Independent review verified the ownership labels on both
`demo-inference` and `demo-mx-source`, successful deletion of both, subsequent
empty Pod and ResourceClaim API responses, and absence of the exact scoped
lease. Namespace and model-cache storage remain.

Final receipt:
`reports/receipts/2026-11-05-workshop-mx-cleanup.json`.
Six immutable command receipts are retained under
`results/overnight-baseline-mx-control/mx-cleanup-evidence-20261105-a1/`.
The interruption receipt's pending-cleanup field describes its pre-cleanup
checkpoint; this separate final receipt supersedes that lifecycle status.
The failed prime evidence and historical successful recordings are unchanged.

No further collection, peer startup or benchmark run was launched during
closeout. Any later full MX retake requires a fresh run after a new ownership
and health audit; do not resume the cleaned attempt or invent its missing peer
arm. The current take-away is an actual resumed intro recording and a complete
source-only/failed-observer MX record, with scoped cleanup proved for both.
