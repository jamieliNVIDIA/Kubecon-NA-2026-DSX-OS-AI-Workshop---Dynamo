# Frozen writer-only controller on the existing jump host

The adapter runs the already-frozen v4 writer through deployment, serving and
rank-descriptor verification, fresh post-health, final health qualification and
scoped cleanup. It never runs preparation, a reader, promotion, a fault, an
automatic retry or a second deployment. It does not edit the writer/exporter
implementation or install shared infrastructure.

Entry points:

- `scripts/workshop_shadow_writer_remote.py`
- `scripts/workshop_shadow_writer_remote_controller.py`
- `tests/test_workshop_shadow_writer_remote.py`

Seven focused offline tests pass. They cover secret/CPU-receipt exclusion,
immutable payload membership, exact namespace/GPU reservation, missing/stale
gates, source/reservation drift before networking, symlink refusal, uncertain
launch replay refusal and success/failure cleanup ordering. Generated bootstrap
and collector syntax checks pass. Read-only validation of the actual a6 source,
config, runtime contracts and complete CPU/CUDA prerequisite state also passed.
No live action or actual reservation was taken by the implementation agent.

The transport/controller sources are frozen after handoff through collection.
Root alone executes all network/cluster steps below. Do not instantiate another
`Run` for a6 or modify frozen state/source after packaging.

## Exact a6 handoff

Run: `results/overnight-shadow-super-vl-20261105-descriptor-writer-a6`.
Namespace: `dynamo-ft-r610-031fb156-demo`.
Placement: `kubecon-nke-site-cp-0124`, exact GPUs
`GPU-b896cc31-be76-0f28-2e2d-d82564b624b7` and
`GPU-a63322d6-c08e-79cb-c42a-031aeb4c1488`.

Root's preparation, actual-image descriptor/wrapper checks and exact-pair CUDA
arithmetic have passed. Fresh health was captured at 22:32:12 UTC with no changed
conditions and all reads successful. The bounded remote execution starts with
that qualified state; it does not replay those gates.

```bash
.local/venv/bin/python -B scripts/workshop_shadow_writer_remote.py build \
  --run results/overnight-shadow-super-vl-20261105-descriptor-writer-a6 \
  --health-before results/overnight-shadow-super-vl-20261105-descriptor-writer-a6/snapshot-gpu-health-1793917925569467000.json \
  --health-baseline results/workshop-resumed-20261105-qualified-closeouts-a1

.local/venv/bin/python -B scripts/workshop_shadow_writer_remote.py preflight \
  --run results/overnight-shadow-super-vl-20261105-descriptor-writer-a6

.local/venv/bin/python -B scripts/workshop_shadow_writer_remote.py launch \
  --run results/overnight-shadow-super-vl-20261105-descriptor-writer-a6

.local/venv/bin/python -B scripts/workshop_shadow_writer_remote.py status \
  --run results/overnight-shadow-super-vl-20261105-descriptor-writer-a6
```

Build acquires the exact local reservation:
`.local/dynamo-ft-r610-031fb156-demo-writer-remote.gpu-lease/owner.json`.
It records the run, namespace, node and full GPU UUID pair. A previous package or
reservation is refused; failed preparation preserves evidence/reservation for
root review. The package contains safe explicit inputs, installed-source
contracts, source snapshots, model/config pins, fresh health/baseline and the
original cleaned-source `demo.json` guard. CPU command/manifests and credentials
are excluded. No prior attempt is overwritten.

The CPU image is the existing owned
`sha256:f12b417250bc7d8e150e929114e60762e86f25146ea1f9289990a0fc7b5e9872`.
Its receipt/recipe/package hashes are copied from the completed Snapshot image
build as provenance; no image build or pull occurs here. Existing jump-host
kubectl, kubeconfig and Python dependencies mount read-only. The container has
no GPU device access and no Docker socket. The same logical repo path preserves
all absolute frozen source/config/health paths.

The detached controller survives loss of external VPN/chat. Outer limits are
300 s deploy, 2,400 s verification (including its 1,500 s readiness wait),
300 s fresh health, 180 s finalize and 600 s cleanup. A failed phase does not
retry. Post-failure health is attempted before cleanup if it has not already
been attempted; final qualification runs only after successful serving and
actual rank-manifest proof. Writer manifests must be ready with exact frozen
identity/version/hashes and no unhandled modules. This is metadata readiness,
not GPU reader qualification.

If launch loses its SSH response, inspect the existing launch intent and named
Docker controller with `status`; do not rerun launch or rebuild. Status failure
does not establish remote workload failure.

## Immutable collection and closeout

After Docker exits:

```bash
.local/venv/bin/python -B scripts/workshop_shadow_writer_remote.py collect \
  --run results/overnight-shadow-super-vl-20261105-descriptor-writer-a6 \
  --output results/shadow-writer-a6-remote-collected-a1
```

The collector archives only the owned run, including controller receipts,
health, log followers, three coding responses and rank manifests. It requires
a terminal Docker state and verifies complete archive membership, safe regular
paths, sizes and every hash before extraction into a fresh directory. The
archive is retained read-only. No state is adopted over the original local a6
run, no public recording is created and no reservation is released.

If transfer succeeded but local extraction was interrupted, preserve that
archive and transport receipt. Use the existing generic offline
`workshop_snapshot_remote.extract_collection` with the recorded expected
run/controller/plan identity and a new output directory; do not download again.

Before release, root independently checks the collected controller outcome,
serving streams, manifest provenance, health and cleanup receipts; then performs
a fresh cluster audit of the exact namespace, DGD UID, Pods, GPU claims and
owned DeviceClass, plus node/driver/health continuity. Failure or uncertain
cleanup retains the reservation. Successful controller exit alone is not this
independent audit.

After the independent audit passes, root records the audit and exact saved
reservation owner/hash, then removes only the matching local owner file and
empty lease directory. The remote workspace also retains its private mirrored
owner: root may remove only that exact matching mirror after the same audit,
recording the closeout separately. Never release a foreign/replaced owner or a
parent workstream's reservation. Retain all run/spec/source/health/descriptors,
controller and archive evidence.

The original local a6 state remains CPU-prepared after collection. Further
composition must explicitly consume the accepted collected evidence or use a
separately reviewed import; collection never silently promotes local state.

## A6 executed result

Root launched controller `kubecon-shadow-writer-031fb156`, ID
`451138cddb59e9c50d5cecb4fcd4743cda6afff20fcd14988eea95e1ed30c473`, at
`2026-11-05T22:36:33.564716553Z`. All five explicit phases and scoped cleanup
passed, finishing at 22:45:04.369 UTC. This is writer-only qualification, not a
passed Shadow reader, promotion, failure demo or presentation recording.

The three coding SSE responses completed with distinct request IDs through the
same writer generation. Both rank manifests are reader-ready with no unhandled
modules, the exact frozen v4 identity/version, and a shared committed GMS layout
hash. Each rank reports 97 CUTLASS FP8, 80 Humming linear, 40 Humming MoE and
8 ModelOpt attention descriptors. The final health observation found no new Xids
and preserved driver-Pod/boot identity. The writer DGD UID was
`aa2a9f2e-c777-4d57-80a3-3e785d59989f`; worker UID was
`f1310e07-8dd8-41bb-ad42-2ebdfa2ae8e2`.

Root collected the immutable result into
`results/shadow-writer-a6-remote-collected-a1` at 22:48 UTC. Archive SHA-256:
`e04e9f117110fe4a52253d25420af78ad3cb762d119561a79ab822fa95d97f82`.
Independent read-only audit passed at 22:51:17 UTC after rehashing all 626
collected files, verifying 337 payload members, 19 critical source snapshots,
134 installed-source contracts, launch/controller/phase identity, real coding
streams, rank capture provenance, health and scoped cleanup.
Proof: `results/shadow-writer-a6-independent-audit-a1/audit.json`.

Original local a6 state remains byte-identical to the packaged CPU-prepared
state, and all 19 critical local source pins remain unchanged. The independently
evolving `workshop_shadow_composed.py` differs locally from its unused frozen
writer-payload copy; that unrelated reader work did not alter the isolated
writer execution or its critical pins.

At the independent audit, the exact local reservation still matched the frozen
plan and had SHA-256
`c668db89cf965d167f8a2e13534134cf70202e448e20bbcbc71ba1b7824fee0d`.
Frozen plan SHA-256:
`b00655594aac2eefff06396a50f2f053dcc9829fee6bb46efd1029394e034d6a`.
The controller checked its exact remote mirror before each phase, retaining it
after cleanup. Root's separate fresh namespace/DeviceClass absence audit and
source-controller-bound remote/local reservation release must precede further
GPU use; the independent audit itself performed no lease or network mutation.
Root's 22:47:45 UTC inventory separately showed zero allocated GPUs/claims/DGDs
and no scheduling issues. Final lease-release receipts are separate from that
inventory and the immutable collected result.
