# KVCR: retained-resource child investigation

The retained-parent entrypoint and conditional-refresh controller are implemented
in `scripts/workshop_kvcr_prepared.py`, with an executable wrapper at
`demos/07-kvcr/run-prepared.sh`. Eighteen adapter tests and the original v2/Guard
tests pass (51 combined). Root executed the supported refresh and fresh a6
capture successfully, then cleaned its scoped resources and lease. The
[qualified-and-cleaned receipt](../receipts/2026-11-05-kvcr-peer-reuse.json)
links the actual recording and independent audits. Root is the sole live
executor; the procedure below records the completed sequence.

## Evidence required before replacement

The actual a2 read-only interval completed its live commands. A fresh independent
offline audit at `...a5-current-assets-a3-audit/terminal.json` verifies 25 matching
current non-weight assets, different actual native advertised MDC checksums, and
one admitted aggregated worker despite two current generate endpoints. Original
lease, DGD, Pod/container and physical GPU claims stayed unchanged. A2's final
controller assertion incorrectly required a frontend metadata registration;
frontends without endpoints need no DynamoWorkerMetadata. Its failed receipt and
all bytes are preserved. The independent audit records this distinction and all
source hashes; it does not rewrite a2 into a passing run.

The frozen conditional-refresh plan independently rechecks the current cached
asset hashes immediately before deletion. Any mismatch or transport failure
stops the sequence without a mutation.

The existing debug diagnostic confirms a typed explicit-worker rejection for A.
Exact source and retained cards show the only advertised compatibility difference
is six ancillary documentation/image files. Strict MDC compatibility remains
enabled. No registry editing, CRD model-card patch, file filtering or alternate
checksum is part of this proposal.

## One supported offstage refresh

Root has authorized this conditional refresh after the evidence above passes:

1. Capture current DGD and its Grove PodClique/PodCliqueSet ownership chain,
   the three original owned Pods, both GPU claims and source A's container
   identities. Confirm the B and frontend selectors each identify exactly their
   own single Pod. The DGD spec, replica counts, UUID selectors and source A
   remain unchanged.
2. Gracefully delete only B using a Kubernetes DELETE with a UID precondition
   for `6e3681d0-a403-464e-b2ba-e6c805fee70b`. Record the intent and API response in
   a new reset directory. Do not force delete, change the worker command or
   change a cluster/operator setting. Grove recreates its worker from the
   existing DGD. Wait for the old B Pod/claim to finish before accepting the
   replacement.
3. Require the replacement B to have a fresh Pod UID, current owner chain,
   exact original cp-0942 GPU UUID pair, original base image/overlay pins and
   current 4,224/8,192 page/context geometry. A's Pod, containers, claims and
   generate endpoint ID must still match the original a5 identities.
4. Capture fresh model cards and compute exact native mdcsums. Require new B's
   advertised metadata to match A's compatibility identity. If it differs,
   stop rather than repeating replacement or weakening admission.
5. Gracefully replace only the original frontend, also using its current UID
   precondition. Require a fresh frontend UID and original image/runtime.
   Keep the same owned DGD/Service/discovery namespace. Read its full startup
   log with discovery diagnostics enabled if possible without changing the
   executable DGD. Verify the frontend's model readiness reports **two admitted
   aggregated workers**, not merely a model listing or two Ready Pods.

The CPU-only `kvcr-a5-http400-debug-a1` Pod/Service use their own selector and
must not be selected by either replacement. Their cleanup is separately scoped.
No other workstream's Grove Pods or GPU reservations are in scope.

## Fresh immutable child binding

Create a new run and capture directory; never reuse a5's request names or failed
recording. The child records:

- Parent a5's frozen deployment, source bundle, model/revision, runtime/package
  pins, physical UUID policy and original failed-capture hashes.
- The owning parent lease's exact path, owner and hash. The child borrows that
  reservation explicitly; it does not acquire a second reservation or pretend
  that the parent's owner file names the child.
- The unchanged DGD UID/spec and source A identities, plus the deliberately
  replaced B/frontend Pod UIDs, container IDs, claims and current worker IDs.
- The reset receipt, current equal advertised MDC checksums, and the frontend's
  observed two-worker admission proof.
- A new unique repository snapshot tag near the beginning of the shared prompt
  so every cache page is distinct from any original/diagnostic request. Freeze
  fresh source/target bodies and their tokenizer inputs and hashes.

Preparation, native probes and model loading are inherited from the parent and
reset receipts. They are not rerun or counted as fresh startup timings. The
child's presenter output must say that these workers were prepared offstage.

The new prepared presenter uses an explicit `bind` action that copies
the parent's executable/configuration files and readiness evidence into the new
run, stores `prepared_parent`/`binding.json`, and creates fresh request fixtures.
All future writes, command receipts and metrics live in the child directory.
The bound path's lease check validates the recorded parent owner; it must never
rewrite the lease's owner to the child. The child cannot silently deploy or
re-prepare inherited resources if an identity check fails.

The implementation uses native `dynamo._core.ModelDeploymentCard` directly;
the type is intentionally not re-exported by `dynamo.llm`. A local regression
executes the exact CPU probe with a core-only export and fails when that export
is unavailable, rather than inventing a checksum fallback.

Before source HTTP, repeat the actual-worker CPU tokenization and geometry gates
for the new bodies, and recheck current A/B metadata compatibility plus two-worker
frontend admission. Check these again before B. Preserve the existing source
commit gate, response-usage agreement, source cold-cache requirement, matching
transfer operation/blocks/bytes, external-cache-token counters, clean delivery
results and unchanged post-reset worker identities. A correct READY response
alone is insufficient.

## Capture and cleanup

Only after the source/B proof passes may the fresh main-panel transcript be
marked successful. Associate it with the child binding and reset receipt; do not
claim that the original a5 run passed or that a cache-aware router selected the
workers automatically.

Perform final scoped cleanup from a controller that checks the post-reset live
identities and the unchanged owning lease. Delete the owned DGD/workloads and
diagnostic CPU resources, verify zero owned GPU claims, then release only that
lease. Save cleanup and independent audit receipts outside the original failed
request/capture. Preserve original a5 input, request, failure, preflight and
diagnostic evidence. No timing or performance comparison follows from this
functional cache-transfer proof.

## Concrete root launch sequence

The actual conditional plan is frozen at
`results/workshop-kvcr-demo-20261105-a5-supported-refresh-a1/plan.json`. Source
dependencies were frozen for that plan. Root executed:

```bash
.local/venv/bin/python -B scripts/workshop_kvcr_prepared.py refresh \
  --plan results/workshop-kvcr-demo-20261105-a5-supported-refresh-a1/plan.json \
  --timeout 2700
```

This creates an owned loopback-only `kubectl proxy` for Kubernetes DELETE requests
with exact UID preconditions; ordinary unguarded `kubectl delete pod` is not used.
The controller records each intent/response, never repeats a delete, saves a
durable failure on any stop and closes only its proxy. After a passing repair:

```bash
demos/07-kvcr/run-prepared.sh bind \
  --repair results/workshop-kvcr-demo-20261105-a5-supported-refresh-a1/repair.json \
  --run results/workshop-kvcr-demo-20261105-a6
demos/07-kvcr/run-prepared.sh prime --run results/workshop-kvcr-demo-20261105-a6 --auto
demos/07-kvcr/run-prepared.sh run --run results/workshop-kvcr-demo-20261105-a6 --plain
```

`bind` is local preparation only. `prime` performs fresh current-worker
tokenization/admission checks without loading engines or sending generation.
`run` preserves the existing v2 presenter steps and cache-transfer proof gates.
The capture recorder now selects this prepared entrypoint explicitly through a
separate mapping, preserving the canonical v2 mapping and existing recordings:

```bash
.local/venv/bin/python -B scripts/capture_workshop_demo.py \
  --demo 07-kvcr-prepared \
  --run results/workshop-kvcr-demo-20261105-a6 \
  --output demos/transcripts/live/07-kvcr/20261105-a6 \
  --quiet --capture-timeout 1800
```

The recording labels startup as prepared offstage in the owning parent even
though the child has no `apply_started_at`. Its provenance records the retained
A UID, replaced B/frontend UIDs and exact repair hashes. Completion retains the
v2 token/page and transfer gates and also verifies a repaired two-worker
admission observation before each HTTP request. The private evidence snapshot
includes all admission observations and independent exact-byte copies of the
repair, plan and qualified snapshot, so final verification survives cleanup of
the original deployment. Four focused tests plus all 16 existing capture tests
pass. Prepared capture requires a bound live child; use `07-kvcr` for rehearsal.
The bound child refuses direct cleanup and reports its owning parent path.

This historical a6 run is now cleaned. Reusing its evidence does not redeploy
its workers. Root's cleanup controller and terminal audit are in
`results/workshop-kvcr-demo-20261105-a6-cleanup-controller/`; original a5 failures
and all a6 scientific/capture bytes remain unchanged. A future live run needs
its own authorized parent resources and fresh evidence directory.

## Upstream and harness follow-ups

- Make model-asset preparation complete and quiescent before registration;
  ancillary assets added to a shared pinned snapshot can change advertised
  metadata identity without changing weights/tokenizer/revision.
- Review whether the current broad extra-file harvest is the desired metadata
  contract. Any upstream change belongs at asset discovery/registration with
  explicit compatibility tests; preserve strict `mdcsum()` identity semantics.
- Expose safe admission/rejection reasons without needing a new DEBUG frontend.
- Require intended admitted frontend capacity in readiness gates. Pod readiness
  and model listing do not prove that both replicas joined one serving cohort.
- Keep early CPU sizing and final live page/window checks; the discovered
  membership failure does not reduce their value or justify bypassing them.
