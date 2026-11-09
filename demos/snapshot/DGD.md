# Demo 4 candidate: Dynamo-managed Snapshot recovery

This presenter uses the qualified same-node DGD checkpoint path, keeping the
original Dynamo frontend and DGD alive while the operator replaces the worker.
It serves a fresh streaming coding response through the frontend after recovery.
The existing [native presenter](README.md) remains available through
`uv run python -m demos snapshot`.

The November 5 [actual main-panel recording](../transcripts/live/04-snapshot-dgd/demo-04-dgd-live-20261105-a3/main.txt)
passed fresh priming, automatic worker replacement and two completed frontend
coding responses. Replacement measured 33.895 s agent restore, 59 s
Pod-to-Ready and 64.288 s deletion-to-observed-Ready; these are separate clocks,
not a matched speedup comparison. The full offstage prime took 45 minutes.
Independent owned-resource/agent/storage audit and local reservation release
also passed. Retained checkpoints remain.

The canonical presenter now projects a compact storage/recovery summary and
saves verbose successful checks in private `storage-validation.log`. Every
validation and full command/check receipt is retained; failures stay visible.
Its [new layout preview](../../reports/overnight-2026-11-04/snapshot-projection-a1/rehearsal-main.txt)
is an offline rehearsal with simulated identities and unmeasured timing. The
passed live recording above retains the original verbose output unchanged.

```bash
uv run python -m demos snapshot-dgd --preview
uv run python -m demos snapshot-dgd --rehearsal
```

The offline rehearsal marks all identities as simulated and does not invent
durations. It uses the usual three-pane tmux layout, screen clearing and silent
submission gates. `--plain` uses one terminal; `--auto` removes the key gates.

## Offstage prime

Use a fresh run and the workshop's existing cluster/runtime/storage setup.
Priming creates a new DGD, automatically captures its initialized engine,
publishes the artifact, stages and verifies an exact node-local copy, then
restores the first worker and checks coding inference through its frontend.
Capture and hashing can take many minutes. Do this before the workshop.

```bash
uv run python -m demos snapshot-dgd prepare
uv run python -m demos snapshot-dgd prime --auto --timeout 5400

# Preserve this exact run and its creating DGD for the onstage walkthrough.
uv run python -m demos snapshot-dgd

uv run python -m demos snapshot-dgd cleanup --auto
```

A retained automatic checkpoint belongs to its creating DGD UID. A newly
created DGD cannot simply adopt a prior qualification artifact. Priming keeps
that DGD, frontend and Service alive, and the onstage action deletes only the
worker Pod with a UID precondition. The operator creates the replacement.

`dgd-profile.json` pins the already-qualified node, exact physical H100 pair,
cache baseline, image and runtime bridge. The executable per-run manifest
retains TP2, compiled text-only 8k context, memory fraction 0.65 and the other
qualified engine settings. It is deliberately different from demo 1's eager
configuration. Hardware, runtime or placement changes require requalification.

The default `nvme` storage mode uses the prepared filesystem and an
artifact-specific read-only view in the agent's private mount namespace. The
runner never formats a disk, mounts a host filesystem, edits agent/Helm specs
or overwrites a prior checkpoint. Staging holds the capture helper's GPU claim
until every hash and inventory check passes. `--storage efs` on the first
invocation selects the slower shared-storage path; that choice is frozen.

The installed automatic capture Job has a 3,600-second lifetime. A November 5
attempt to extend its owned Jobs to 7,200 seconds stopped safely at server
dry-run: the SnapshotJob spec is immutable. No extension was applied. The failed
`capture-deadline-policy.json` and exact admission receipts remain retained.
An explicit, separately recorded continuation can accept the stock lifetime
after checking the same active source identities and remaining time; it resumes
that existing capture rather than redeploying it. Its immutable disposition
records that the optional extension was rejected, and bounds priming by the
remaining source Job lifetime. Shared operator defaults and source Pod deadlines
are never changed. A configurable lifetime at automatic Job creation is an
upstream improvement candidate.

## Onstage flow

1. Show a focused DGD excerpt: the frontend's command/routing arguments, worker
   and checkpoint settings.
   Full `deployment.yaml` and `runtime-patch.yaml` remain in the run directory.
2. Show the worker-deletion command, wait for submission, then continuously
   observe automatic replacement. Print agent restore phases, Pod-to-Ready and
   deletion-to-observed-Ready as soon as startup completes.
3. Verify the changed worker Pod UID and unchanged DGD, frontend, Service,
   checkpoint, node and GPU identities in a short table. Exact identities remain
   in `recovery-proof.json`.
4. Show and submit port-forward and coding-request commands. Validate the
   completed stream, `add(a, b)` output and changed decode-worker identity.

The readiness waiter sends no presenter inference request. The final coding
request is separately gated after the timing summary. Any time the presenter
waits at a key gate is therefore outside the reported restoration clocks.
The later coding request has its own start and completion timestamps.

## Scope and lifecycle

This is same-node initialized-engine capacity recovery. The checkpoint released
KV cache before capture. Node loss, in-flight streams, retained prefix cache and
combined GMS/ModelExpress recovery are separate topics. There is no matched
cold-start or storage speedup claim.

The pinned runtime still uses the merged upstream Snapshot module plus the
destination identity/offline bridge. That temporary workload-local overlay is
explicit in the preview and full manifests. The
[upstream workstream](../../reports/2026-11-04-snapshot-upstream-status.md)
tracks its replacement. Local NVMe overlay handling is workshop-specific storage
plumbing, separate from those runtime fixes.

Stopping preserves the DGD and private storage view for resumption. A durable
replacement intent prevents a second fault from being silently injected after
an interrupted delete. Cleanup verifies owned workload ancestry, removes only
those workloads and claims, restores the private EFS view, then releases the
Snapshot reservation. Identity or storage uncertainty retains the lease.
Snapshot resources and both checkpoint copies remain for inspection.

## Durable qualification from the jump host

For a full unattended qualification, run offstage coordination on the existing
jump host so VPN/chat interruptions cannot strand a captured source helper:

```bash
uv run python -m demos snapshot-dgd prepare --auto --run results/my-snapshot-dgd-demo
uv run python -m demos.snapshot.controller_image build --run results/my-snapshot-dgd-demo
uv run python -m demos.snapshot.remote preflight --run results/my-snapshot-dgd-demo
uv run python -m demos.snapshot.remote build --mode full --run results/my-snapshot-dgd-demo
uv run python -m demos.snapshot.remote launch --run results/my-snapshot-dgd-demo
uv run python -m demos.snapshot.remote status --run results/my-snapshot-dgd-demo
```

The frozen Docker controller performs fresh prime, actual main-panel capture and
scoped cleanup. The pinned slim Python base lacks curl, which the actual
presenter uses. The image-build step creates an owned local derivative with curl,
retaining the base/recipe/package versions and exact image ID in
`controller-image.json`. It does not overwrite the base, push an image or install
host packages. Preflight and launch validate that receipt and use the exact
built image ID. Existing dependencies and jump-host kubectl/kubeconfig mount
read-only; no credentials are exported, no shared
operator defaults change and no new RBAC resources are installed. A named
controller and launch-intent receipt prevent blind replay after an uncertain
SSH response. Failed phases do not automatically retune or repeat a fault.

After the controller exits, collect into a new local directory:

```bash
uv run python -m demos.snapshot.remote collect \
  --run results/my-snapshot-dgd-demo --output results/my-snapshot-remote-collection
```

The collection verifies hashes/paths and includes the sanitized actual recording,
private raw evidence and run/controller receipts. It does not import remote
state over the local run or release the local reservation. Independently audit
the owned namespace, agent/storage view and GPU claims before releasing that
reservation. Full mode cleans the service after recording; the ordinary primed
interactive walkthrough above keeps its creating DGD alive for presenting.

See [overnight notes](../../reports/overnight-2026-11-04/SNAPSHOT.md) for the
latest presenter validation, live status, decisions and open questions. Older
native and qualification recordings remain separate immutable attempts.
