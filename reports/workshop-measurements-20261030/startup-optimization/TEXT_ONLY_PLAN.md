# Text-only ModelExpress startup pilot

Frozen pilot: `results/workshop-mx-startup-20261103-textonly01`.
Namespace: `dynamo-ft-mxstartup-4f3085aaed`.
Helper: `text_only_startup.py` in this directory.

This is one fresh text-only seed followed by one text-only MX receiver with
compiler-artifact transfer. It starts after the existing queue completes and
the parent verifies resource cleanup and lease absence. No cluster operations
have run for this pilot. The historical full-MM artifact04 result, 249.70 s,
is an **unpaired reference**, not a contemporaneous control.

## Locked controls

- Same Super VL model/revision, runtime image digest, native 1,048,576 context,
  TP2 H100, four sequences, 8192 batched tokens and GPU memory fraction 0.85.
- Same source/receiver nodes, EFS checkpoint, LIBFABRIC/EFA configuration,
  frontend, health canary settings and effective startup/readiness/liveness probes.
- Only serving capability change: append `--language-model-only` on **both**
  seed and receiver. Keep existing explicit image/video limit arguments; the
  installed language-only setting overrides modality acceptance.
- Separate text-only compile-config digest and fresh per-Pod caches; private
  new namespace/coordinator excludes the historical multimodal sources.
- Seed stays idle apart from normal health/canary and the tiny READY probe;
  no AgentX load or additional replicas.
- No Snapshot, new patches, GC settings, registration or probe tuning.

The actual effect on encoder construction/profiling must be checked in the
executed engine logs; a submitted flag alone is not proof of a speedup.

## Workflow task lists

DGD workflow:

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
- [ ] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
- [ ] Hand off to `deploy_dynamo` or `kubectl apply`

The user authorized a new immutable result directory: generated JSON DGDs
under this run derive from the already qualified source/target templates.
Old configuration files and frozen helpers were not edited. Local structural,
manifest-delta and serialization checks passed; Kubernetes dry-runs remain
part of `prepare` on the delegated controller.

Benchmark workflow:

- [x] Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
- [x] Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
- [ ] Verify endpoint healthy (curl `/v1/models` on the frontend)
- [ ] Run the benchmark (`run_profile`)
- [ ] Fetch and analyze results (`get_results`)
- [ ] Compare to previous runs if relevant (`compare_runs`)

This is the existing startup-timing workflow rather than an AIPerf load test.
The frozen local spec implements the locking contract; the user authorized the
text-only capability change. ISL/OSL/concurrency/rate are unchanged because the
only request is the same small readiness/correctness probe.

## Exact commands

All commands execute from the same logical workspace path inside the stable
controller container. `freeze` and `verify` are local-only and have passed.

```sh
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_startup.py verify --run results/workshop-mx-startup-20261103-textonly01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_startup.py prepare --run results/workshop-mx-startup-20261103-textonly01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_startup.py batch --run results/workshop-mx-startup-20261103-textonly01
.local/venv/bin/python -B reports/workshop-measurements-20261030/startup-optimization/text_only_startup.py cleanup --run results/workshop-mx-startup-20261103-textonly01
```

The parent queue adds its independently reviewed analysis/final-seal stage
after cleanup. Recommended outer ceilings: preparation 1800 s, batch 7200 s,
cleanup 900 s, analysis/final seal 300 s. The scientific startup bound remains
2400 s per arm, publication wait 180 s and artifact-effectiveness wait 60 s.
There is no automatic replay of a started pilot.

`prepare` performs owned CPU setup and server/client dry-runs. It reads the
existing owned RR `common-runtime-pull` Secret through subprocess memory and
applies it to the owned new namespace through stdin. Namespace ownership,
Secret owner label/type and existing target ownership are checked. Secret
bodies are neither saved nor sent to the laptop/controller bundle.

`batch` takes the atomic GPU lease. It reports source Ready, artifact-publication
wait, receiver Ready and cache verification to the new run's `LIVE_STATUS.json`.
It validates native context, exact worker arguments, image, two H100 GPUs,
zero restarts, unchanged effective probes and retained source UID. Acceptance
requires two peer transfers and actual rank-0/rank-1 compiled-cache loads,
with installed artifact IDs linked to seed publication and no unused/recompile
warning. It collects failure evidence and cleans only owned resources.

Cleanup independently records zero owned GPU Pods, ResourceClaims, DGDs and
coordinator Pods before releasing its matching lease. Unverifiable cleanup or
transport failures retain a failed state; another owner's lease is not removed.

## Offline evidence

- Spec SHA256: `4dc5db5ad4bb02d91ed43c6905f12fa020a4c3f5832db1df1fce50e012c3c307`.
- Helper SHA256: `fdc396f64fdd6e941ee8f6dc95d49f34198d9a2b45fd2b1eb5456c5f82225f5e`.
- `inputs-sha256.json` covers 105 exact files, including the imported shared
  helpers/scripts, templates, model lock, generated manifests and portable
  `baseline-reference.json`. Stage the complete fixed list; do not overwrite
  an existing remote file whose bytes differ.
- Source and receiver manifests match accepted artifact04 manifests after
  normalizing only namespace labels, compile identity and the added language-only
  flag. Generated-manifest byte serialization remains stable through the reused
  preparation writer.
- Offline parser checks accept the historical two-rank cache proof and reject
  duplicate Worker 1 messages without TP0, an unlinked source artifact ID and
  explicit recompilation-on-load-failure. These are parser fixtures, not
  text-only serving or timing evidence.

Parser receipt:
`results/workshop-mx-textonly-offline-checks-20261103/receipt.json`.
