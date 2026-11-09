# KVCR workshop demo: overnight development

Latest status, November 5: fresh bound child **a6 passed actual cross-node peer
reuse and its main-panel recording** after one supported B/frontend refresh.
A stayed intact; both workers now advertise the same native metadata checksum
and the frontend admits both. A computed a cold source prompt; B reused 4,224
tokens through a matched six-block, 103,809,024-byte EFA transfer. Both actual
responses were READY. Independent audit verified 48 captured source files and
417 evidence files. The original a5 HTTP 400 and all earlier failures remain
preserved. Root's scoped cleanup and independent follow-up audit both passed:
zero namespace Pods/claims/DGDs and the owning lease released. No new startup,
automatic routing, under-load speedup or production claim follows. The compact
[qualification and cleanup receipt](../receipts/2026-11-05-kvcr-peer-reuse.json)
links the terminal evidence.

## Task list (DGD workflow)

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
   - Done: Super VL text-only, vLLM, two TP2 workers, four H100 GPUs, Kubernetes/EFA.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
   - Done: reuse the qualified a4 Guard renderer/runtime and exact experimental source bundle.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
   - Done: fresh complete executable manifests are frozen in each demo run directory.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
   - Done: fresh live preparation and the supported retained-DGD refresh passed their admission/identity gates.
5. Hand off to `deploy_dynamo` or `kubectl apply`
   - Done: root executed the fresh a6 investigation/capture and scoped cleanup; both independent audits passed.

## Decisions

- Demonstrate ordinary peer reuse in scaling. Leave Guard process failure and
  request migration to the resiliency workstreams.
- Reuse the pinned preview stack that passed ordinary reuse in a4. Do not quietly
  imply released-runtime or production qualification.
- Explicitly pin a source and receiver to isolate the data path. This is a
  mechanism demonstration, not proof that the router automatically chooses an
  optimal worker under load.
- Use shared repository context and different appended coding questions. Keep
  the distinction between a bounded request proof and the full AgentX benchmark.
- Require matched transfer receipts, external-cache tokens, clean delivery
  metrics and unchanged worker/Guard identities. Correct output is insufficient.
- Keep source preparation and engine startup offstage. Onstage exposes the
  focused KV-transfer configuration, seeds A, requests B and inspects proof.

## Open questions

- Cross-node peer reuse is qualified. Remaining presentation work is reducing guard/log overhead and investigating the first-request token pauses.
- Should Guard remain installed in scaling for a future return in resiliency?
- The source bundle can now be recreated exactly from pinned public inputs.
  The portable take-home still needs a public base-image recipe and cluster setup.
- For the next presentation iteration, consider replacing the READY canary with
  a short answer that depends on the shared repository context. The current
  request is a bounded transfer/completion proof, not a coding-quality or
  comprehensive cache-content integrity evaluation. Keep the same independent
  byte/token/identity gates when making that workload change.

## Upstream candidates

- Dynamo #15535 is already merged and required for hybrid/recurrent events; the
  common runtime lacks it. The a4 matching nightly wheels supply it experimentally.
- Evaluate namespace/prefix handling and matching telemetry APIs when producing
  the eventual public runtime. Preserve exact pins until requalified.

## Validation and execution notes

- Implemented `demos/07-kvcr/run.sh`, focused settings, immutable full manifest,
  actual-node/GPU-UUID placement, offstage prime and onstage A/B requests,
  tmux/read-only panes, explicit cleanup and capture integration.
- Ten focused tests pass. Full offline rehearsal completes without cluster
  calls and retains null simulated timing/cache metrics.
- Transfer parser reproduced the prior a4 ordinary-reuse evidence: six blocks,
  103,809,024 bytes and 4,224 external-cache tokens. This is parser validation
  against historical evidence, not a fresh GPU result.
- `prepare_kvcr_demo_sources.py` recreated the source bundle from public pinned
  GitHub/PyPI inputs and matched SHA-256
  `592cda9d1831d1ece346b1185eca54d67488a9eb02bc6d8b8cdc62e79a88bc4d`.
  Receipt: `results/overnight-kvcr-public-sources-a2/preparation.json`.
  The first source recreation omitted upstream tests and failed final hash;
  its immutable failed attempt remains in `...public-sources-a1/`.
- Coordinator assigned cross-node GPU pairs: cp-0198 GPUs 4/5, cp-0942 GPUs 4/5;
  exact UUIDs are in `demos/07-kvcr/placement.json`. EFA allocation is explicitly
  reduced to main4 + service1 per worker to coexist with other experiments.
  Shared EFS/network activity may overlap. No isolated timing claim is intended.
- First fresh live preparation a1 passed exact cached model and nightly CPU APIs,
  then its completed native probe's DRA claim had already been garbage collected
  before the harness tried to fetch it. No inference experiment or engine
  deployment happened. Fixed the native gate to log CUDA's actual UUIDs inside
  the probe; the served engines still verify live DRA allocations. This was a
  test-harness race, not an upstream inference failure. a1 cleanup verified zero
  owned Pods/claims and released its own lease.
- Fresh a2 prime is running with the corrected native UUID gate. Its run is
  `results/overnight-kvcr-demo-20261104-a2`; no new peer-reuse pass yet.

### External transport interruption

Fresh a2 stopped during CPU-only namespace/storage preparation after repeated
TLS handshake/OpenAPI timeouts at 06:49–06:51 UTC (10:49–10:51 p.m. Pacific).
The central coordinator independently found a new SSH connection to the jump
host timed out as well. This is a transport/VPN blocker, not a KVCR inference
failure. No a2 GPU probe, engine startup, source request or peer request ran.
The a2 namespace and receipts are retained; its own lease remains while the
coordinator re-audits transport and allocations before a new attempt. No global
tunnel restart or cleanup was attempted by this workstream.

### Review artifacts

- Main-panel offline capture:
  `results/overnight-kvcr-capture-rehearsal-a1/rehearsal-main.txt`
  (`capture.json` reports `rehearsal_passed`, zero redactions).
- Real three-pane tmux rehearsal:
  `results/overnight-kvcr-tmux-rehearsal-a1/tmux-validation.json`.
  All three panes were inspected; only this workstream's detached rehearsal
  session was closed. Other chats' tmux sessions were preserved.
- Frozen executable manifest for the interrupted live attempt:
  `results/overnight-kvcr-demo-20261104-a2/deployment.yaml`.
- Exact public-source recreation receipt:
  `results/overnight-kvcr-public-sources-a2/preparation.json`.

### Next live steps after coordinator re-audit

1. Verify a2 namespace has no GPU Pods/claims and release only its own lease via
   the demo cleanup command. Preserve its failed transport receipts.
2. Prime a fresh a3 run on the assigned cross-node pairs (or a newly approved
   placement file if the coordinator reallocates them). Startup may overlap other
   workloads; no isolated timing claim.
3. Capture the actual onstage flow with `capture_workshop_demo.py --demo 07-kvcr`.
   Require positive matching transfer blocks/bytes, external-cache tokens,
   response cached-token usage, clean deliveries and unchanged engine/Guard
   identities. Preserve any failing HTTP/transfer attempt; do not replay it under
   the same request evidence name.
4. Freeze a successful shareable main-panel transcript, then perform scoped
   cleanup and independently audit the exact allocated pairs and namespace.

### Packaging improvement worth upstreaming

A tested immutable public preview image/recipe should align the Dynamo Python
package and Rust runtime, vLLM adapter (including telemetry APIs), KVCR and NIXL.
The current qualification composes matching private per-container overlays and
fetches the SHA-pinned nightly wheels at startup. The reproducible public source
bundle now closes the source-discovery gap, but it does not eliminate the private
base image or per-Pod network dependency. Baking the tested composition would
make the take-home simpler and make startup failures easier to attribute. This
is an integration/packaging improvement, not a newly confirmed library defect.

Completed stages now support presenter resumption without sending replacement
HTTP requests: they explicitly label saved same-run output. Partial/failed HTTP
attempts remain immutable and require a fresh run. A fresh capture and resumed
capture both passed in rehearsal:
`results/overnight-kvcr-capture-rehearsal-a2/` and
`results/overnight-kvcr-resume-capture-rehearsal-a2/`.
The offstage readiness gate also requires both current generate endpoints to be
registered before freezing the ready worker identities.

Independent review identified that preparation's immutable ConfigMap creation
cannot be replayed after an interrupted gate (the inherited baseline preparer
also refuses an existing model lock). This is now explicit: incomplete
preparation fails early with cleanup-and-fresh-run instructions before another
cluster command; only completed preparation/startup and completed onstage stages
are resumable. This preserves gate logs instead of silently overwriting them.
A regression checks this refusal. Eleven focused tests now pass. More granular
phase-level preparation resumption is a future harness improvement, not an
upstream Dynamo bug.

## November 5 recovery continuation

The user restored VPN access and explicitly resumed the original task. The
cluster coordinator re-audited the assigned cp-0198/cp-0942 pairs as unallocated
and separately confirmed clean current GPU/kernel health on those nodes. The
Shadow pair on cp-0124 is under a separate hold; this KVCR run does not use it.
No global cluster-health pass is inferred from KVCR's scoped clearance.

Root-launch controller:
`results/overnight-kvcr-recovered-20261105-a3-controller/controller.py`.
It first checks a2's exact local lease, owned namespace, zero GPU objects and
optional PVC/secret metadata, then runs only a2's canonical cleanup. The planned
fresh run is `results/overnight-kvcr-demo-20261105-a3`; the actual main-panel
capture target is `demos/transcripts/live/07-kvcr/20261105-a3`.

The new run uses the source bundle independently recreated from public pinned
inputs. Prime is gated on the coordinator's own-workstream health status and
exact four GPU UUIDs; it also rechecks no active claim occupies those pairs.
The controller preserves all earlier failures, never retries a request or
changes another namespace, and stops for diagnosis on any failure. On successful
capture it checks positive matching peer/cache evidence, performs the demo's
scoped cleanup and independently verifies zero owned Pods/claims/DGDs and release
of only its local lease. Shared EFS/network timing remains nonisolated.

A2 recovery cleanup has now completed successfully. The root-launched controller
saved namespace/PVC/secret metadata checks, verified zero Pods/claims/DGDs,
released only a2's lease and retained all transport-failure receipts. Audit:
`results/overnight-kvcr-recovered-20261105-a3-controller/a2-cleanup-proof.json`.
The coordinator receipt used for fresh a3 is
`results/overnight-2026-11-04-coordinator/recovered-0739-health-clearance.json`
(SHA-256 `6dd9c69e898de8acb83e982bf029a4e564e13c04060e1041c21b5ec4843966b0`).
All twelve referenced health artifacts independently match their hashes.

### Startup observability improvement candidate

During the fresh a3 cold start, `tower_http::trace::on_failure` emits an ERROR
for HTTP 503 roughly every 30 seconds while the engine is still loading weights.
No inference request has been submitted at this point; these correlate with the
normal health/readiness polling period. The worker log pane can consequently
show mostly red 503s despite steady safetensors/prefetch progress and no restart.
An upstream review could make expected not-yet-ready health responses quieter,
or include the route/method so they are distinguishable from inference failures.
This is a logging/presentation improvement candidate, not a confirmed inference
or KVCR defect. Evidence is the timestamped `a-main.log`/`b-main.log` in fresh a3;
no logger/probe policy was changed during the qualification.

## Fresh a3 result: priming passed; context fixture too short

Run: `results/overnight-kvcr-demo-20261105-a3`.

- Exact cached model/revision, matching nightly CPU APIs, both native CUDA UUID
  probes and host EFA registration passed. Both independent TP2 workers became
  Ready and registered on the exact assigned cp-0198/cp-0942 GPU pairs.
- Apply to observed Ready: **1,440.223630 seconds** (24 minutes). Model-loading
  logs report about 1,204.95 seconds for the slowest rank. Shared EFS/network
  activity overlapped other workstreams; this is not an isolated KVCR/startup
  comparison and says nothing about peer-transfer performance.
- The source request completed once: HTTP 200, valid complete SSE, READY, **3,247
  prompt tokens**, three completion tokens, zero cached prompt tokens, source
  worker `2080597504219142`.
- vLLM raised its effective attention block size to **4,224 tokens** to match the
  hybrid Mamba page. The 60-function coding fixture was therefore shorter than
  one complete cache page. Saved before/after source metrics show no committed
  local-fill block/host write; the canonical source gate stopped the flow.
- **No receiver request was sent.** There is no cross-node cache-transfer result,
  no failed remote delivery result and no peer-cache speedup measurement from a3.
- This is a **presenter-fixture sizing error**, not evidence of a KVCR library or
  cross-node transport defect. The tiny READY output checks bounded completion,
  not coding quality or comprehensive cache-content integrity.

The live engine's block-size log made the issue visible while warm-up was
finishing. Root's attempted hold/count arrived after automatic capture had sent
its source request; those attempted controls made no changes or additional
requests. Parent subsequently directed no further fixture/GPU experiments for
this run. There was no retry or hidden replacement prefix.

### Preserved output and provenance

- Actual unsuccessful main-panel recording:
  `demos/transcripts/live/07-kvcr/20261105-a3/failed-main.txt`.
- Its `capture.json` reports `failed`; no live-passed `main.txt` was created.
- Full failed-capture read-only source/evidence snapshots are referenced by that
  capture manifest. They precede any later cleanup and retain original hashes.
- Source response and HTTP/SSE receipts:
  `results/overnight-kvcr-demo-20261105-a3/source/`.
- Source-only metrics/log interval: `before-seed/` and `before-peer/` in the same
  run. Original 60-function `shared-context.txt`, model/runtime/placement locks,
  native probe receipts and `ready-pods.json` remain unchanged.
- Root controller terminal failure:
  `results/overnight-kvcr-recovered-20261105-a3-controller/failure-run-a3.json`;
  `a3-prime-exit.json` is exit 0 and `a3-capture-exit.json` is exit 1.

### Exact next fixture requirements (not executed)

1. Before generation, tokenize both fully templated A/B requests using the exact
   served tokenizer/revision. Measure their actual shared token prefix.
2. Require at least one complete **effective** hybrid page in that common prefix
   (currently 4,224 tokens), while both full prompts plus the 16-token output
   budget fit the 8,192-token engine limit. Requested `--block-size 64` alone does
   not establish the effective reusable page size for this model.
3. A 100–120-function variant is a candidate; its token counts have **not** been
   measured. The prepared CPU-only `inspect_prompt_tokens.py` can count 60/80/100/
   120 variants without generation, but it was not executed successfully here.
4. Keep the initial failed source attempt immutable. A new unique prefix needs
   a fresh, explicitly separated investigation/capture attempt. Reusing the
   already-qualified loaded workers could avoid another cold load, but a safe
   case-directory mechanism must preserve original fixture/response/metric
   paths and distinguish new evidence; it is not implemented or authorized for
   execution in this attempt.
5. Require the existing source commit gate, receiver bytes/blocks and matching
   wire handles, positive external-cache tokens, response cached-token usage,
   clean delivery increments and unchanged worker/Guard identities. Do not
   weaken those gates to make the shorter fixture pass.

The improvement belongs in demo preflight/fixture sizing, and potentially in an
upstream example's introspection guidance. No new upstream KVCR defect is
confirmed. More realistic context-dependent output remains an iteration option
after the mechanism proof passes.

### Scoped cleanup command

Root is the sole live executor:

```bash
.local/venv/bin/python -B scripts/workshop_kvcr_demo.py cleanup --auto \
  --run results/overnight-kvcr-demo-20261105-a3
```

This targets only `demo-kvcr` in namespace
`dynamo-ft-r610-f079f468-kvcrdemo`, waits for its Pods and GPU claims to disappear
and releases only its run-owned local reservation. Namespace/cache/source
artifacts and all failed recordings remain. Cleanup is now **verified for this
owned attempt** by the receipts and independent local audit below; this is not
a cluster-wide idle or current GPU-health assertion.

## Final scoped cleanup audit — November 5, 10:17 a.m. Pacific

Root's cleanup exited 0. Independently inspecting the retained evidence confirms:

- Owned DGD `demo-kvcr` deletion returned exit 0 with `--wait=true`; all three
  owned Pod deletion waits completed successfully.
- Final namespace Pod and ResourceClaim queries returned empty lists, exit 0.
- `cleanup-proof.json` reports passed for
  `dynamo-ft-r610-f079f468-kvcrdemo`; `demo.json` records cleanup at
  `2026-11-05T18:17:23.154416+00:00`.
- The exact run-owned local lease directory is absent.
- All **549 frozen capture-evidence files** and **36 captured source files**
  still match the immutable capture manifest hashes. The failed main-panel text
  hash, original input hashes and source SSE hash are unchanged.
- The capture remains failed, no receiver response exists and no peer proof
  exists. Cleanup does not turn the undersized fixture into a qualified demo.

Independent offline audit:
`results/overnight-kvcr-demo-20261105-a3/post-cleanup-local-audit.json`.
It references the exact live cleanup command receipts and hashes. No network
query was issued by this audit. Other workstreams and the final cluster-wide
inventory are outside its scope.

## User-resumed work: canonical fixture/preflight correction and fresh a4

The user explicitly resumed unfinished work after the earlier cleanup. This is
new authorized work; the a3 failure and its final cleanup evidence stay immutable.

### Changes

- New presenter profile: `super-vl-kvcr-host-peer-nightly-v2`.
- Increased the generated fixture from 60 to 120 repository helper functions.
  The exact context and both complete source/receiver request bodies are frozen
  together. Character/function counts are not treated as measured token counts.
- Added a cheap CPU-only sizing probe using the exact cached model/tokenizer and
  pinned base image **before native GPU probes or engine loading**. It compares
  measured counts with retained a3's 4,224/8,192 reference limits and explicitly
  marks `live_geometry_qualified: false`. This avoids loading weights for an
  obviously unsuitable fixture; it cannot substitute for the final live gate.
- After both new workers are Ready and registered, parse each current worker's
  effective page/context limits from its actual startup log. Requested
  `--block-size 64` is never used as the effective geometry.
- A CPU-only process on the current source worker applies the cached exact
  tokenizer/revision to the two frozen message bodies with their real template
  arguments. Require a measured common token prefix covering at least one full
  effective page and room for each full prompt plus 16 output tokens.
- Bind `prompt-preflight.json` to both current Pod UIDs, input/request hashes and
  retained geometry/tokenizer evidence. Check it again before generation. A
  failed, missing, changed or stale preflight stops before either request.
- Record a preflight-completion timestamp and explicit source/receiver request
  start timestamps. The submitted body hashes and actual server prompt-token
  usage must match preflight exactly.
- Existing source host-commit, matched transfer handles/bytes/blocks, positive
  external-cache tokens, response cached tokens, clean deliveries and stable
  worker/Guard identity gates are unchanged.
- Completed stages remain resumable without repeating HTTP requests. Older v1
  attempts can still invoke cleanup, but cannot silently run with the new profile.

### Validation before live execution

Eighteen focused tests pass. They include the observed a3-sized 3,247-token
regression refusing all source HTTP, context overflow, mismatched geometry or
request hashes, stale Pod bindings, exact compatibility with the actual
`guard.response` request producer, and independent CPU-versus-live gate scope.
The full offline walkthrough still measures no tokens/bytes/timings. New capture:
`results/workshop-kvcr-v2-capture-a2/capture.json` reports `rehearsal_passed`.
Root separately strengthened the shared recorder's live acceptance checks and
added negative capture cases for the same geometry/hash/timestamp/usage rules.

### Fresh immutable attempt

- Planned run: `results/workshop-kvcr-demo-20261105-a4`.
- Planned actual transcript: `demos/transcripts/live/07-kvcr/20261105-a4`.
- Root-launch controller:
  `results/workshop-kvcr-demo-20261105-a4-controller/controller.py`.
- Same original disjoint pairs: cp-0198 GPUs 4/5, cp-0942 GPUs 4/5; exact UUIDs
  remain in `demos/07-kvcr/placement.json`.
- Fresh per-workstream health receipt:
  `results/workshop-resumed-20261105-health-clearance-a1.json`, SHA-256
  `da8888641423c82a7fb9bf65bdb80c46386982c176b3e7e720a2f96c8419eed1`.
  Its KVCR status is passed. The separate Shadow probe/inference gate is outside
  this experiment; no global inference-health pass is asserted.
- The controller freezes the relevant source dependencies and health/allocation
  receipts, rechecks assigned GPUs unoccupied, primes with the publicly recreated
  exact source bundle, requires the pre-source live prompt gate, records the
  actual canonical walkthrough and verifies the peer result. It cleans up only
  after a successful capture and independently checks the owned namespace/lease.
  Any failure retains its files/resources and stops without hidden retry.
- Root is the sole live/network executor. No shared platform changes, old
  credential copying, external messages, commits or pushes are part of this work.

The 120-function token counts and the corrected peer-transfer path remain
**unmeasured until the fresh live execution**. No a3 field or recording was edited
into a passing result. Shared EFS/network timing still prevents an isolated
startup or peer-performance claim.

Fresh a4 candidate is frozen locally after the recorder change: plan SHA-256
`40efd8563567862a5b4f6a2aeec42faff8b7cafcda1fc88c126fe9237bdbc37c`,
with 19 relevant source dependencies. Root's exact launch command is:

```bash
.local/venv/bin/python -B \
  results/workshop-kvcr-demo-20261105-a4-controller/controller.py run
```

This freeze itself made no network/GPU actions. The actual run and preflight
measurements remain pending until root executes that command.

### A4 early CPU gate stopped before GPU allocation

Fresh a4 completed cache/package preparation, then its CPU tokenizer program
failed an overly strict assertion that chat-template tokenization must directly
return a Python list of Python `int`s. It failed before producing token counts;
this was not a short-prefix result or KVCR failure. No native GPU probe, model
engine deployment, source/receiver generation or peer-cache transfer ran.

Evidence remains under `results/workshop-kvcr-demo-20261105-a4`, including the
original `kvcr-prompt-size-cpu.log`, frozen tokenizer program/input and controller
failure receipt. Root's scoped cleanup exited 0. Local inspection confirms
`cleaned_at=2026-11-05T19:27:15.547479+00:00`, `apply_started_at` absent, passed
cleanup proof and absence of its own lease. The failed CPU Pod was deleted by
its probe's finally block; namespace/cache/source evidence remain.

### Tokenizer representation fix and fresh a5

The canonical CPU/live program now explicitly requests `return_dict=True`,
extracts `input_ids` from Hugging Face's Mapping/BatchEncoding result, normalizes
one unbatched integral token-ID sequence and rejects invalid IDs. It also
records actual output/container types for diagnosis. This changes token-ID
representation handling, not the prompt/page/window acceptance criteria.

A regression executes that same program against a mocked BatchEncoding using
the real UserDict/Mapping protocol, verifies exact chat-template arguments and
preservation of source/receiver token sequences/common-prefix length. Nineteen
focused tests now pass. Actual a4 output types were not printed by the original
failing assertion; a5's typed record will establish the runtime representation.

Fresh a5 was frozen after a4 cleanup, with 19 source dependencies and the same
scoped health/physical GPU assignments. Plan SHA-256:
`d2aade7812d0bd50df47e5e4daa7d73c93095bab5a328a9697d4f0acc34c34b3`.
No a4 input, log, failure or cleanup receipt was rewritten into a pass.

Root's exact launch command:

```bash
.local/venv/bin/python -B \
  results/workshop-kvcr-demo-20261105-a5-controller/controller.py run
```

The new run is `results/workshop-kvcr-demo-20261105-a5`, with actual transcript
planned at `demos/transcripts/live/07-kvcr/20261105-a5`. CPU sizing must pass
before any GPU initialization; actual live-worker geometry/token preflight must
still pass before source HTTP. All source commit/transfer/cache/identity gates
remain unchanged. Fresh token counts and peer reuse are still pending.

### A5 early CPU sizing and native gates passed

The root-launched a5 run has now produced actual CPU tokenizer measurements:

| Quantity | Measured value |
| --- | ---: |
| Fully templated source prompt | 6,426 tokens |
| Fully templated receiver prompt | 6,427 tokens |
| Common token prefix | 6,406 tokens |
| Planned output budget | 16 tokens |

Tokenizer class is
`transformers.tokenization_utils_tokenizers.TokenizersBackend`. Actual chat-template
output is `transformers.tokenization_utils_base.BatchEncoding`; `input_ids` is a
Python list. This confirms the representation mismatch that the normalization
fix addresses. Both prompt/window and common-prefix reference checks passed
before any GPU allocation. Receipt:
`results/workshop-kvcr-demo-20261105-a5/prompt-size-cpu.json`; it still explicitly
marks `live_geometry_qualified: false`.

Both native CUDA probes then verified the exact assigned pairs and EFA host
registration. The DGD has been submitted and its engines are starting. No
source/receiver generation or peer transfer has happened at this checkpoint.
Final acceptance still requires both current worker logs' geometry and the
same tokenizer check on the actual worker before source HTTP.

### A5 live preflight passed; first source request rejected

Both cross-node TP2 workers became Ready on the assigned cp-0198/cp-0942 GPU
pairs. Final CPU-only tokenization on the current worker reproduced the early
counts and bound them to both live Pod UIDs, current log hashes and the frozen
source/receiver bodies. Both logs report a 4,224-token effective attention page
and an 8,192-token model window. The shared 6,406-token prefix therefore contains
at least one reusable page, and both prompts plus the 16-token output cap fit.
The final gate completed at `2026-11-05T19:45:55.194225+00:00`, before the source
request started at `2026-11-05T19:46:14.852625+00:00`.

The first source generation returned HTTP 400 with `Invalid request`, no SSE
completion, no usage and no observed worker response. B was never requested,
and no new transfer or peer-reuse qualification is claimed. Actual failed main
panel output is retained at
`demos/transcripts/live/07-kvcr/20261105-a5/failed-main.txt`. Root preserved both
running workers and their original lease rather than reloading the model.

Root's read-only diagnostic verified all three original Pod UIDs and captured
their logs under `...a5/http400-diagnosis-20261105-a1/`. The frontend warned that
a pinned request without `token_data` would be tokenized, then reported a
sanitized validation error within about 10 ms. No specific cause is visible at
the default log level. The exact runtime source, commit
`e37f0b91f841e12715e412b375a40842ec6010b6`, disproves an initial hypothesis that
`max_completion_tokens` is ignored: chat completions explicitly select it before
`max_tokens`. Both live model cards also publish the expected 8,192 combined
budget. No prompt reduction or protocol-field workaround has been applied.

The exact HTTP adapter already logs the private semantic diagnostic at DEBUG,
target `dynamo_llm::http::service::openai`. Root authorized a bounded diagnostic
using a new CPU-only frontend Pod/Service, identical image/bootstrap/runtime and
discovery settings, and one separately recorded copy of the failed source
request. The controller is frozen locally at
`results/workshop-kvcr-demo-20261105-a5-http400-debug-a1/controller.py`; root alone
executes live commands. It independently checks the original files/capture,
lease, Pods/containers, actual GPU claims, current endpoints and live geometry.
If the request unexpectedly succeeds it is only a diagnostic cache seed; B is
still forbidden and no reuse pass is inferred. A successful final demo will
require a fresh immutable investigation bound to these retained resources.

This diagnostic preparation passed local selector, CPU-resource, unchanged
image/command and geometry checks. The failed original run and recording remain
immutable, and any diagnostic cleanup is limited to the new CPU Pod and Service.

### Debug diagnostic confirmed worker-membership rejection

Root executed the separately frozen CPU frontend diagnostic. Its one exact
source request also returned HTTP 400. DEBUG preserved the actual reason:
`nvext.decode_worker_id=8147780429315143 does not identify a known worker`.
This is the router's explicit-worker admission check, not a prompt-size or
generation-budget rejection. Both original workers, their containers, DGD,
physical GPU claims, endpoints and lease stayed unchanged. The controller's
terminal receipt independently confirms that every original a5 file and failed
capture hash also stayed unchanged. No B request or new reuse proof occurred.
Evidence: `...a5-http400-debug-a1/frontend.log` and `terminal.json`.

Source analysis found a precise compatibility difference: after normalizing
the workers' metadata-server IPs, their advertised model cards are identical
except for `extra_files`. A advertises six extra documentation/image assets
absent from B: `accuracy_plot.png`, `harness_comparisons.png`, `bias.md`,
`explainability.md`, `privacy.md` and `safety.md`. Shared extra assets have
identical checksums. Exact-runtime `ModelDeploymentCard::mdcsum()` includes
every extra file's basename/checksum, and discovery admits only the incumbent
checksum cohort within one WorkerSet. This makes the metadata difference a
strong explanation for rejecting A despite both Pods being Ready; direct
discovery-cohort logging is still needed to confirm that connection.

Saved normalized diff, assertions and exact source snapshots:
`results/workshop-kvcr-demo-20261105-a5-http400-analysis-a1/`.
Current discovery guidance explicitly preserves strict MDC checksums; do not
fix this by weakening compatibility identity or bypassing explicit-worker
validation. A possible upstream improvement is deterministic metadata-file
harvesting/registration so irrelevant document assets cannot split otherwise
identical replicas. Any workaround needs its own recorded mutation and fresh
child investigation before source/B qualification.

Separately, safe validation/admission reasons at normal log levels would make
this much easier to diagnose. The original INFO log reports zero input tokens
even though this failure occurs after preprocessing; that metric alone is not
a reliable boundary for locating this failure.

### Current checkpoint: read-only assets/admission check frozen; VPN unavailable

The next controller is prepared at
`results/workshop-kvcr-demo-20261105-a5-current-assets-a1/controller.py`.
It makes only GET/exec-read operations: current exact-revision A/B file
inventories and SHA-256 hashes, exact native card checksums via
`ModelDeploymentCard.local_dir()` (a pure path computation), and the original
frontend's model-readiness admitted worker count. It checks the original
namespace/DGD/Pod/container/physical UUID allocations and lease before and
afterward. Local payload syntax and read-only contracts passed. Root will run
it after VPN recovery; no replacement or source/B request is authorized by this
controller.

The retained timeline further supports concurrent ancillary asset additions:
B registered at `19:44:56.087975Z`; the take-home preparation Job traversed the
complete 114-file pinned snapshot at approximately `19:44:57.785–19:44:58.6Z`
and exited at `19:44:59Z`; A registered at `19:45:13.790428Z`. Both frozen PV
manifests refer to EFS `fs-07acea4e27fbda414`, and the take-home Pod's cache
subPath matches KVCR's `feature-tests/20261015-super-vl-tp2` directory. The
take-home preparation receipt's four referenced artifact hashes were verified.
The evidence lacks a directory inventory just before those registrations, so
the exact file-addition causality remains strongly supported rather than fully
proven. Timeline and source hashes are saved as
`...a5-http400-analysis-a1/asset-registration-timeline.json`.

Root conditionally authorized one supported offstage B/frontend replacement
after current assets are proven settled and matching. A remains intact; the
DGD ownership, replica counts, image/runtime and exact UUID policies remain
unchanged. There will be no manual CRD card editing, document filtering,
checksum bypass or blind reset loop. The proposed fresh child binding, live
two-worker admission gate, capture and cleanup design is in
`reports/overnight-2026-11-04/KVCR-PREPARED-CHILD.md`. It has not executed.

### Retained-parent implementation and current-asset confirmation

Implemented the isolated prepared entrypoint at
`scripts/workshop_kvcr_prepared.py` and `demos/07-kvcr/run-prepared.sh` without
editing the frozen v2 presenter, Guard harness, runtime, bootstrap or capture
mapping. Eighteen focused adapter tests pass; the combined v2/Guard/prepared set
passes **51 tests**. They exercise actual snapshot/admission gates, physical
claim mismatch, stale Pod/endpoint metadata, one-worker rejection, native MDC
mismatch, original evidence/lease immutability, fresh request fixtures, repair
tampering, nested evidence-path refusal, source/B request prevention, supported
reset ordering and UID-precondition conflict with no retry. A failed B
registration prevents frontend deletion and preserves a durable failure receipt.
Bound children refuse deployment, GPU preparation and direct cleanup.

After VPN recovery, actual read-only attempt a1 stopped on a Python API import:
the native ModelDeploymentCard class is exposed by `dynamo._core`, not the public
`dynamo.llm` re-exports. Fresh a2 corrected that exact export and completed every
live read successfully. Its final assertion incorrectly assumed the frontend
must also have a DynamoWorkerMetadata object. That object is correctly absent
for a frontend with no registered endpoint. Both failed controller receipts
remain intact; these are harness issues rather than additional KVCR failures.

A fresh independent offline audit at
`results/workshop-kvcr-demo-20261105-a5-current-assets-a3-audit/terminal.json`
verifies every a2 command exit/output, original before/after Pod/container/DGD/
GPU allocations, stable worker metadata, native-runtime identity and complete
file inventories. It preserves a2's failed finalization and records hashes for
all source evidence. The actual read interval ended at `20:42:48.503338Z`:

- Both workers currently see the same **25 non-weight files**, with equal sizes
  and SHA-256 hashes.
- A's actual native advertised mdcsum is
  `3119ea8b9e60ca2ba355c161b3ac0cc80be990259f744f6a6081f2f4e8888d6f`.
- B's actual native advertised mdcsum is
  `55f56fe8f956067da4930398a3be9c6e0c99fded27e4f9b53358596f2670e5c4`.
- The original frontend admits **one** aggregated worker and is otherwise Ready.

This establishes a concrete incompatibility between otherwise matching cached
replicas; it is consistent with the confirmed explicit-source admission error.
The snapshot download/registration timeline remains the evidence for how the
ancillary-asset difference arose, with its stated causality limit.

An actual conditional replacement plan is now frozen locally at
`results/workshop-kvcr-demo-20261105-a5-supported-refresh-a1/plan.json`.
It repeats settled-file verification before any delete and requires unchanged
source A, native matching cards and two admitted workers after the one declared
B/frontend refresh. No replacement, source/B generation or new reuse proof has
been executed by this workstream. Full reviewable launch/bind commands are in
`KVCR-PREPARED-CHILD.md`; root alone performs live actions.

## Fresh a6 qualification and actual recording passed

Root executed the declared supported refresh once: only B and the frontend were
replaced; source A, the DGD, UUID policies and exact physical GPU allocations
were retained. B's fresh registration now matches A's native checksum
`3119ea8b9e60ca2ba355c161b3ac0cc80be990259f744f6a6081f2f4e8888d6f`, and the
frontend reports two admitted aggregated workers. This independently closes the
one-worker admission gap without editing advertised cards or bypassing metadata
compatibility. Repair proof: `...a5-supported-refresh-a1/repair.json`.

Root then bound a fresh child, `results/workshop-kvcr-demo-20261105-a6`, with a
new repository-context tag and its own tokenization, request, metrics and proof
artifacts. Its final preflight measured 6,426 source / 6,427 receiver / 6,406
shared tokens against the actual 4,224-token page and 8,192-token context. Source
A remained UID `931655ed-3ff1-4bc0-a920-18923c664e00`; new B is
`117d568f-3b30-4570-ad78-262605ba23b4`; the refreshed frontend is
`e38b9db0-c6a6-454a-b401-2fd00ed61e02`.

Source and receiver each issued one actual HTTP request and returned READY with
HTTP 200 and a complete error-free stream. Source usage reports zero cached
tokens. Receiver usage and worker counters independently report 4,224 reused
tokens. Positive transfer receipts at both ends match wire operation
`2525103854758807`, six blocks and 103,809,024 bytes; both engine logs confirm the
EFA provider. Failed/partial delivery counters stayed clean. Source-only host
commit passed before B ran, and current repaired identities plus two-worker
admission were verified before both requests.

Shareable actual main-panel text:
`demos/transcripts/live/07-kvcr/20261105-a6/main.txt`.
The capture labels these workers as prepared offstage and does not assign them
a fresh startup time. Its private evidence includes exact independent repair
bytes and every admission snapshot, so capture verification survives resource
cleanup. Twenty capture tests pass (four new prepared cases and sixteen
existing cases); the frozen presenter/Guard/prepared suite previously passed 51.

Independent audit:
`results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json`.
It verified every captured source/evidence hash (48 / 417), all 4,500 raw terminal
timeline bytes, exact sanitization/main-text and SSE hashes, preflight/body/usage
agreement, repair provenance, actual transfer/commit metrics and unchanged
original failed source/preflight/capture bytes. Main text SHA-256:
`aec31b8b91eaaa887d9725be0498b16da26c5eb268993fa27c207f6cb7d342a0`.

### Presentation polish and latency follow-ups

The actual recording is complete and should not be rerun merely to improve
cosmetics. It exposes substantial harness overhead worth removing before the
workshop:

| Projected step | Actual step wall time | Actual HTTP stream to DONE |
| --- | ---: | ---: |
| Verify prepared workers | 51.8 s | No generation |
| Seed A | 224.8 s | 19.549 s |
| Continue on B | 216.0 s | 19.426 s |
| Inspect evidence | 29.3 s | No generation |

The two request steps therefore contain about 402 seconds outside their HTTP
streams, including 30 seconds of explicit commit waits. A's post-HTTP interval
alone contains roughly 44.53 seconds of Kubernetes command work plus its
15-second wait: log collection 18.09 s, identity GETs 12.60 s, metric reads 7.58 s,
admission GET 5.15 s and native checksum calculation 1.10 s. Command durations
are estimated from receipt filename timestamps written immediately after
subprocess collection, not instrumented cluster/engine intervals. The separate
`source-command-timing.json` preserves that calculation.

Proposed harness refinement: do the comprehensive offstage qualification once,
retain immutable checksum/UID/claim bindings, batch related API reads and make
each request's onstage gate inexpensive while preserving fresh admission and
identity checks. Collect bulky logs after the visible request or show an already
verified summary. Keep the actual generation and transfer evidence fresh;
do not substitute historical HTTP output. This is future polish, not a change
made during this qualification.

The HTTP streams also each contain a real first-request/inter-token pause and
must not be dismissed as harness latency. A's first content arrived at 0.811 s
and B's at 1.830 s, but both streams finished near 19.5 s. A specifically has an
18.56-second gap between READ and Y. Backend timing reports A/B prefill about
381/200 ms and total about 19.06/18.85 s. Investigate this separately before any
latency claim; this run does not isolate its cause or establish a speedup.
Another metrics question: frontend `nvext.timing.kv_hit_rate` reports 0.0 even
while B's response usage and external-cache worker counters show 4,224 reused
tokens. Clarify that field's scope before using it to explain KVCR behavior.

### Scoped cleanup prepared

Root's cleanup controller is frozen at
`results/workshop-kvcr-demo-20261105-a6-cleanup-controller/controller.py`.
It independently checks the post-refresh identities, DGD spec, claims, matching
native cards and two admitted workers; removes only the separate debug CPU
Pod/Service first; repeats the workload gate; then invokes canonical cleanup
through the owning a5 lease. It permits the parent's cleanup lifecycle fields,
locks and new receipts to change while retaining every original failed source,
preflight, input and capture hash, plus every fresh child/capture byte. It then
requires zero namespace Pods, GPU claims and DGDs and the owning lease absent.
Three offline control tests passed, including use after a failed capture,
stopping if debug resources remain and recording a failed command without a
retry. No live cleanup has been executed by this subagent.

### Final closeout: qualified, recorded and cleaned

Root executed the frozen cleanup controller successfully. Its
[terminal receipt](../../results/workshop-kvcr-demo-20261105-a6-cleanup-controller/terminal.json)
completed at `2026-11-05T21:19:03.836175+00:00`: exact post-refresh identities and
two-worker admission passed; the debug CPU Pod/Service were removed first;
canonical cleanup through the owning parent then left zero namespace Pods,
GPU claims and DGDs and removed its own lease. Parent lifecycle bookkeeping
changed as declared; no failed source, preflight, input or capture was rewritten.

The [independent cleanup audit](../../results/workshop-kvcr-demo-20261105-a6-independent-audit/cleanup-audit.json)
checked both cleanup exit/log hashes, actual saved zero-resource API responses,
lease absence, every protected original hash and every fresh child/capture hash.
The archived actual capture still passes its full completion validator **after**
the owning lease and workloads are gone. This is scoped KVCR cleanup evidence;
overall cluster clearance belongs to the coordinator's separate audit.

Review artifacts:

- [Actual main-panel text](../../demos/transcripts/live/07-kvcr/20261105-a6/main.txt)
- [Capture metadata and immutable evidence hashes](../../demos/transcripts/live/07-kvcr/20261105-a6/capture.json)
- [Independent qualification audit](../../results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json)
- [Compact qualified-and-cleaned receipt](../receipts/2026-11-05-kvcr-peer-reuse.json)

Remaining work is presentation polish, latency/metric-semantics investigation
and public-runtime packaging. The bounded experimental cross-node transfer demo
and shareable recording are complete; its original failures remain available
for upstream/debugging review.
