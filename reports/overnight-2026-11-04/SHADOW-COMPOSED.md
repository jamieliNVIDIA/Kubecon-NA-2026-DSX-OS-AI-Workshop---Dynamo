# Full reader / Shadow composition

**Full-a1 is closed; do not resume or reapply it.** Its first actual reader
failed at 23:13:06 UTC in our generic ModelOpt config callback because final
Humming state has no `w13_input_scale` attribute. The earlier 23:12:49 observer
failure was a separate local TLS tunnel error. Root restored the tunnel,
captured clean post-failure health and completed canonical cleanup at
23:18:25 UTC. No fault was injected. Old sources, manifests and actual traces
remain preserved. The separate reader-only repair is tracked in
[SHADOW-READER-V5.md](SHADOW-READER-V5.md); it retains the accepted a6 writer
format and requires independent review/actual-source CPU validation before a
fresh full candidate. The commands below describe the closed a1 experiment.

The controller and launcher are implemented in
`scripts/workshop_shadow_composed.py` and
`demos/08-shadow-engine/run-composed.sh`. Twenty offline composition/gate tests
and 177 focused Shadow tests pass. **No GPU reader is qualified yet.** Root is
the sole live executor. The actual v4 a6 writer passed, its 626-file collected
output was independently audited and root-accepted, and exact source namespace
and mirrored-reservation closeout passed at 22:56:11 UTC. The original local a6
state remains CPU-prepared; full composition reads the verified collected
`/run` as evidence without constructing `Run` or adopting remote state.
The writer result is tracked in
[SHADOW-DESCRIPTOR-V4-PROPOSAL.md](SHADOW-DESCRIPTOR-V4-PROPOSAL.md).

Independent source review of the composed identity/fault boundaries is recorded
in [SHADOW-COMPOSED-REVIEW.md](SHADOW-COMPOSED-REVIEW.md). The identified generation
gaps were addressed; that review did not establish an actual reader result.

The DGD skill's required task list is recorded before materializing this YAML:

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete: exact pinned Super VL/image/TP2, assigned cp-0124 GPU4/5 UUID pair, operator GMS plus active/parked Shadow engines, same eager FP8-cache profile.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete: compose from the instrumented writer DGD and the previously reviewed operator failover example/presenter, preserving serving arguments and overlay bytes.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete after actual a6 writer manifests/coding/health/cleanup, independent audit, root exact-byte acceptance and reservation closeout: `configs/dgd/workshop-shadow-composed/overnight-shadow-super-vl-20261105-full-a1/deployment.yaml`.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — pending fresh full-candidate CPU/source/cache preflight and client/server admission.
5. Hand off to `deploy_dynamo` or `kubectl apply` — pending exact-pair CUDA smoke, source-writer cleanup and fresh health. No full GPU deployment has run.

## Frozen full-a1 identity

- Run: `results/overnight-shadow-super-vl-20261105-full-a1`.
- Namespace: `dynamo-ft-r610-84d3182d-demo`; graph: `ft-shadow`.
- Profile: `super-vl-shadow-humming-runtime-descriptors-v4-routing-bias`.
- Full specification SHA256: `d4bb47faecd62aa4b04c9edb2ad44815c2a241f0851a878edb286f6135ddf3dd`.
- Exact accepted overlay SHA256: `82ed5fbe40821a377dd6c8a5769c17b488cbc44bf8ada6fd4312345248e80247`.
- Exact accepted v4 helper SHA256: `ae2b7f19154a0032ceb50bfc0bbf5b8f654ca8c006423205414cf2f52afb7a8e`.
- Full controller SHA256: `a5c33c7375f2ff867c682ddcea8727b11cd06c4358299b7256adaa8382412ad1`.
- Physical assignment: `kubecon-nke-site-cp-0124`, GPU4/5 (`GPU-b896cc31-be76-0f28-2e2d-d82564b624b7`, `GPU-a63322d6-c08e-79cb-c42a-031aeb4c1488`).
- Expected actual runtime inventory per rank: 97 Cutlass FP8, 80 Humming linear, 40 Humming MoE, 8 ModelOpt Attention.

Offline `load` revalidated all frozen inputs, 134 source contracts and sixteen
writer-basis receipts, including exact root acceptance at the freeze checkpoint.
Root subsequently passed CPU/admission, exact-pair CUDA and deployment before
the reader failed as recorded above. All 24 files listed under
`full-spec.json.source_snapshot` were held unchanged through canonical cleanup;
that includes the composed controller, v4 descriptor helper, original writer,
original presenter/fault verifier, CPU dependencies, diagnostics/follower and
shared support modules. Capture-tool changes are separate from this frozen
runtime and do not alter it. No full fault is authorized by readiness alone:
the ready/parked pair, three correct streams and fresh pre-fault health remain
required before the one guarded fault.

## Preconditions enforced by the controller

- Actual source-writer serving, descriptor capture and no-new-Xid qualification
  and cleanup must all be passed. Final writer health must cover descriptor capture.
- Both real rank manifests must match their recorded hashes, pinned
  image/model/config/source/TP identity and committed GMS layout. They must have
  `reader_ready=true`, no unsupported modules and the same runtime inventory.
- Capture provenance must show the same verified serving Pod/container
  generation and stable GMS state around the manifest read.
- The manifest must actually establish supported attention runtime state.
  The model's resolved FP8 cache dtype alone does not prove the mixed-precision
  config attached `ModelOptKVCacheMethod`; inspect the real manifests.
- The source writer must be canonically cleaned, with zero remaining Pods and
  GPU claims, before the full candidate's probe or GPU deployment.
- A collected source must match every collection file hash, its original local
  launch plan, immutable writer inputs, current critical implementation hashes,
  original config path/YAML and model lock. It requires the separate exact-byte
  root acceptance and absence of the original local writer lease. These gates
  are read-only; the CPU-prepared original state is never replaced.
- The new candidate reuses the exact frozen v4 runtime overlay and serving
  arguments. It keeps the stock GMS materializer and shape/dtype guard. It adds
  operator failover plus container discovery and a single shared descriptor
  `emptyDir`; inherited descriptor mounts/env entries are replaced once.

## Exact root-executor sequence

After the instrumented writer actually passes, freeze a fresh full run:

```bash
SHADOW_WRITER_RUN=results/shadow-writer-a6-remote-collected-a1/run
SHADOW_WRITER_AUDIT=results/shadow-writer-a6-root-closeout-a1/source-audit.json
SHADOW_FULL_RUN=results/overnight-shadow-super-vl-20261105-full-a1
.local/venv/bin/python scripts/workshop_shadow_composed.py freeze \
  --source-writer "$SHADOW_WRITER_RUN" --source-audit "$SHADOW_WRITER_AUDIT" \
  --run "$SHADOW_FULL_RUN"
```

This command is offline. It refuses to create output for incomplete writer
proof. It preserves an independent copy of the actual writer evidence inside
the full run and freezes all inputs, runtime sources and critical implementation
files under a distinct full profile.

Once the source writer is cleaned:

```bash
./demos/08-shadow-engine/run-composed.sh prepare --run "$SHADOW_FULL_RUN"
./demos/08-shadow-engine/run-composed.sh probe --run "$SHADOW_FULL_RUN"
```

Capture fresh node health after that exact-pair CUDA smoke, then supply its
actual pathname:

```bash
./demos/08-shadow-engine/run-composed.sh deploy --run "$SHADOW_FULL_RUN" \
  --health-before "$SHADOW_FULL_HEALTH_BEFORE"
./demos/08-shadow-engine/run-composed.sh wait --run "$SHADOW_FULL_RUN" --timeout 1500
```

`prime --health-before ...` is an alternative that combines `deploy` and `wait`;
use one startup path per candidate. It is not another preparation phase.

`wait` stops the UID-matched owned graph on a fatal startup error, any startup
container restart, unexpected Pod replacement, or bounded timeout. It requires
actual active/standby metrics on the same physical pair, three correct fresh
coding streams, unchanged container identities and unchanged GMS state. This
establishes a ready composition; it does not inject a fault.

Capture fresh health after ready/coding. Only then run the guarded failure:

```bash
./demos/08-shadow-engine/run-composed.sh verify --run "$SHADOW_FULL_RUN" \
  --health-after "$SHADOW_FULL_HEALTH_READY"
```

The existing verifier checks allocator isolation, the single active EngineCore
PID, Pod/container identities, failover lock owner and the absence of an earlier
fault intent. It requires a new serving worker, one successful promotion,
unchanged committed weights/GMS/standby identities, failed-engine KV backing
reclamation and a replenished standby. The completion check uses the workshop's
deterministic coding request. Recovery timing includes fault-command and request
polling overhead.

The composed controller additionally pins the applied DGD UID, generation and
serving-spec hash throughout startup and at the fault boundary. Immediately
before fault intent, it rechecks the complete ready/GMS observation after the
baseline coding request. Immediately before the actual kill, it performs only
lightweight DGD and all engine/GMS container ID/restart-count checks. This closes
the replacement race without introducing CUDA-context probes inside the timed
kill boundary; final lightweight identity reads remain included in the reported
command/polling duration. The original callbacks are restored in `finally`.

For a live **main-panel capture instead of the standalone `verify` command**,
run the four-step presenter after ready/health:

```bash
./demos/08-shadow-engine/run-composed.sh --run "$SHADOW_FULL_RUN" --plain --auto \
  --health-after "$SHADOW_FULL_HEALTH_READY"
```

This invokes the same one-fault verifier during step 3. Do not run both paths
on the same candidate: fault intent is a one-attempt gate. Omitting `--auto`
retains silent keypress controls; omitting `--plain` enables the existing tmux
layout. The checked health-source path is passed to tmux's presenter child
through `demo.json`.

Capture final health after promotion/replenishment, then qualify and clean:

```bash
./demos/08-shadow-engine/run-composed.sh finalize --run "$SHADOW_FULL_RUN" \
  --health-after "$SHADOW_FULL_HEALTH_AFTER"
./demos/08-shadow-engine/run-composed.sh cleanup --run "$SHADOW_FULL_RUN"
```

During `run` or `verify`, `--health-after` is the fresh **pre-fault** health
source and is copied to `health-before-fault.json`. During `finalize`, the same
flag supplies fresh **post-fault** health, copied to `health-after.json`.
The capture wrapper exposes the pre-fault source as `--pre-fault-health` to
avoid that ambiguity. Its opt-in `pending_qualification` stage seals the
original main transcript and identity. Root then captures post-fault health
and runs `finalize`; `capture --finalize-pending` validates and appends those
proofs without rerunning the presenter/fault or changing transcript bytes.
Passed/failed capture records are terminal. Presenter guided flow is unchanged.

## Validation gaps and scope

The actual writer may expose a runtime class, attention path or model-level
post-load hook that the prototype does not support. Such a manifest remains
explicitly unready; it is not bypassed. Even a complete writer manifest does
not establish GPU reader materialization, private runtime tensor aliasing,
standby sleep/wake, numerical equivalence or promotion. Those remain actual
integration gates.

The full controller deliberately does not use the original presenter's
`prepare` path, which would install its earlier two-file workaround. It loads
only this new source-frozen composition and reuses the original presenter and
fault-verifier methods after its own preparation and readiness gates.

This experiment covers fresh inference after a process failure within a
healthy Pod, GMS server and GPU pair. It does not preserve in-flight requests,
GPU-only KV state or streams, handle failed GMS/GPUs/nodes, or measure workload
SLOs. The integrated runtime remains experimental and is not production-qualified.
