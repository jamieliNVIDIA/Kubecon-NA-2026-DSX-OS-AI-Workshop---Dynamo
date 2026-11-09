# Dynamo cluster feature tests

Reusable, bounded functionality tests for the KubeCon H100/EFA cluster. Scripts
create only labeled test resources. Feature scripts do not alter drivers,
change shared queues, or install privileged node agents. The separately reviewed
and explicitly authorized platform and GPU driver upgrades use dedicated review/apply scripts.

The local Git repository tracks scripts, manifests, pinned upstream sources and
summaries. Credentials, downloaded tools and raw execution evidence are ignored.
Do not push kubeconfig or raw pod environment values.

## Presenter demos

All presenters use one Python CLI. Run these commands from the repository root:

```bash
uv sync --locked
uv run python -m demos list
uv run python -m demos single-replica --rehearsal --plain --auto
```

`uv` manages the project environment in `.venv` using the dependency versions
and hashes in `uv.lock`. Run `source .venv/bin/activate` to use plain `python`
instead of `uv run python`. `requirements.txt` remains available for older
build tooling; host setup uses `uv sync --locked`.

Use `uv run python -m demos <demo> --help` for demo-specific actions.
The [demo structure guide](demos/README.md) maps the demos, shared runtime and
capture tools to their source folders.

The [scripts catalog](scripts/README.md) covers live qualification and cluster
maintenance. [Development tools](scripts/development/README.md), including the
dec-only MX RAM cache and standalone disaggregation experiments, live outside
the presentation folders. The [automated test guide](tests/README.md) describes
the feature-based regression suite:

```bash
uv run python -m tests
```

### Prepared run selection

Every demo variant remembers its own last successfully prepared normal-mode run:

```bash
uv run python -m demos single-replica prepare
uv run python -m demos single-replica
# Keep it running for the next demo:
uv run python -m demos modelexpress prepare
uv run python -m demos modelexpress
# When finished with both demos, remove the dependent target first:
uv run python -m demos modelexpress cleanup
uv run python -m demos single-replica cleanup
```

Use the corresponding demo's CLI name for the same workflow. If that demo needs
offstage priming, run `prime` between `prepare` and the walkthrough; it uses the
selected run too. A successful cleanup clears that demo's selection.
Preparation failures, previews and rehearsals do not replace a selection.
An explicit `--run` overrides the default. Cleanup refuses nonexistent runs.
The native/DGD Snapshot, ordinary/prepared KVCR and ordinary/composed Shadow variants keep
separate selections. Recorded routing/metrics preparation remains offline;
the live demos retain their existing lease and resource-identity checks.

The composed Shadow workflow still needs `freeze --source-writer ...` and its
existing source/reader proof arguments before `prepare`; the frozen output is
remembered for that preparation. The retained-parent KVCR variant accepts
`uv run python -m demos kvcr-prepared prepare --repair VERIFIED-REPAIR.json`, then
`uv run python -m demos kvcr-prepared`. Binding still validates the repair and parent ownership, and
its evidence child still cannot clean up the parent's workers.

Prepared runs bind source hashes. After changing source bytes, prepare a fresh
run; moving the code does not bypass source or resource identity checks.

The [November 4 overnight review packet](reports/overnight-2026-11-04/REVIEW.md)
tracks the remaining demos, actual validation and captures, decisions, open
questions and possible upstream changes. Its workstream notes distinguish
live qualification from offline rehearsal and recorded historical measurements.

The first workshop demo is a keypress-controlled single-replica Nemotron/vLLM
deployment, with tmux panes for the guided steps, Kubernetes resources, and engine
logs. Start with an offline rehearsal:

```bash
uv run python -m demos single-replica --rehearsal
```

Use `--plain` for one terminal, or `--preview` to inspect the rendered DGD without
cluster access. See [the demo guide](demos/single_replica/README.md) for the
live flow, preparation, timing boundaries, and scoped cleanup.

The first server starts with ModelExpress enabled and loads its weights from
storage. The next demo keeps it running as the source and adds a second server
using peer weights. It compares the two recorded startups and checks transfer
evidence on both TP ranks:

```bash
uv run python -m demos modelexpress --rehearsal
```

See [the ModelExpress demo guide](demos/modelexpress/README.md) for source binding,
the live flow, and cleanup. No separate storage baseline is launched.
Compilation-cache reuse is deferred.

Two more walkthroughs cover separate prefill/decode pools and replacement-Pod
recovery from a prepared Snapshot:

```bash
uv run python -m demos disaggregated --rehearsal
uv run python -m demos snapshot --rehearsal
```

See the [disaggregation guide](demos/disaggregated/README.md) and
[Snapshot guide](demos/snapshot/README.md). Both support the same terminal
controls and offline modes. Snapshot's presenter uses the qualified native vLLM
path. A separate [DGD NVMe qualification](reports/workshop-snapshot-dgd-nvme.md)
now passes automatic replacement and frontend coding chat: **59 s Pod-to-Ready**,
**99.11 s deletion intent to observed successful response**, with an upstream
module backport and identity/offline bridge.

An [integrated DGD Snapshot presenter](demos/snapshot/DGD.md) is now implemented
and rehearsed. Its fresh live qualification is pending; the original native
Snapshot variant and its recordings remain available.

Earlier versions of all four passed real-cluster execution. Their
[main-panel text recordings](demos/transcripts/live/README.md) are available for
the future demo booth. The [capture utility](demos/README.md#capture) records
new attempts without the other tmux panes and retains private raw output plus
immutable evidence. The revised intro-to-ModelExpress flow passed live on
November 7 UTC and is qualified: the intro server fed the new replica over EFA,
493 s to 247 s to Ready ([receipt](reports/receipts/2026-11-07-modelexpress-intro-source.json)).
A November 8 [main-panel recording](demos/transcripts/live/02-modelexpress/20261108-a1/main.txt)
of the same flow is the fallback. The earlier isolated ModelExpress recording is
historical evidence.

The [request-continuity demo](demos/request_continuity/README.md) compares a
broken coding-response stream with frontend migration enabled. It prepares two
two-worker cases offstage, identifies the serving worker from the stream, then
kills only its EngineCore and checks whether the same response continues on
the surviving peer. The fresh live recording passed: disabled interrupted;
enabled completed through a trace-proven peer retry. SSE worker attribution is
first-write-wins in this runtime, so the correlated frontend trace identifies
the handoff. See the guide for the eight-GPU offstage setup and limits.

```bash
uv run python -m demos request-continuity --rehearsal
```

Additional presenter drafts cover [routing](demos/routing/README.md),
[KVCR](demos/kvcr/README.md), [Shadow Engine](demos/shadow/README.md),
and the [AgentX workload and metrics](demos/metrics/README.md).
Routing and metrics present verified historical measurements and make no new
live-performance claim. KVCR has a [qualified cross-node peer-reuse recording](demos/transcripts/live/07-kvcr/20261105-a6/main.txt)
on its pinned experimental stack; scoped cleanup passed. Shadow Engine's current
qualification status is in the overnight review packet.

The [take-home draft](take-home/README.md) renders an attendee-owned Dynamo
service without private workshop placement. Runtime availability and target
cluster qualification remain explicit release gates.

## Latest verified results

The [compiled text-only startup baseline](configs/dgd/super-vl-textonly-fast-startup/)
applies the qualified text-only and faster health settings to a fresh matched
storage/MX-weight/MX-artifact comparison: **8m13s → 4m40s → 2m54s** to observed
Ready. See the [matched results](reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_RESULTS.md)
for controls and limits. This is separate from the eager presenter demos above.

Start with the [feature status and provisioning requirements](reports/2026-10-12-feature-status.md).
The filename is retained for existing links; the page was updated October 22.
The latest full feature recheck uses driver 610.57.04, Super VL TP=2 and the
pinned common runtime. See the [R610 feature report](reports/2026-10-22-r610-feature-retest.md)
and [committed result receipts](reports/receipts/2026-10-22-r610-feature-retest.json).
Native TP2 Snapshot and its EFS/RAM/NVMe comparisons have separate reports linked
from the status page. Preferred-model Shadow remains blocked; the Qwen TP1
recovery control is reported separately.

Raw `results/` evidence, local tools, registry credentials and cluster kubeconfig
stay local. A clone includes the scripts, manifests, pinned sources, reports and
the committed result summary; cluster access must be configured separately.

## Access

For a persistent presenter session on the jump host, use the
[jump-host demo instructions](demos/single_replica/README.md#live-run).
Run `source scripts/kubecon-jump-env.sh` there to use its direct cluster API
connection. The following setup is for running clients on your Mac.

```bash
source scripts/kubecon-env.sh
scripts/kubecon-tunnel.sh status
kubectl get nodes
```

This selects `.local/kubeconfig` and a loopback SSH tunnel through
`ubuntu@3.238.63.5`. TLS is still verified against the cluster API identity.
`kubecon_leave` restores the previous shell environment. No global kubeconfig
changes are required.

## Super VL TP=2 retests

The current model-specific run uses
`nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, two H100s per worker,
GPU DRA, and the common image pinned in `configs/super-vl-tp2-lock.json`.
See [the retest report](reports/2026-10-15-super-vl-tp2-retest.md) for outcomes
and [the generated manifests](configs/dgd/super-vl-tp2/).

```bash
source scripts/kubecon-env.sh
# Fresh owned namespace/cache and immutable model/image inputs:
bash scripts/retest_super_vl.sh results/NEW-SUPER-VL-RUN
# One feature with scoped cleanup and durable receipts:
uv run python scripts/super_vl_tests.py feature \
  --run results/20261015-super-vl-tp2 --feature disagg
```

Shadow verification permits at most one fault attempt per run; use a fresh run
after a recorded fault intent. Prior Lightning qualifications stay separate.

## Test sequence

Synchronize the locked project environment first:

```bash
uv sync --locked
uv run python scripts/cluster_inventory.py
uv run python scripts/feature_tests.py probe --node-count 3
uv run python scripts/nixl_tests.py --pairs 3
uv run python scripts/grove_tests.py
uv run python scripts/snapshot_preflight.py
```

For serving tests, run storage first, then substitute the printed results path
for `RUN`. All serving variants share that run's owned cache and namespace.

```bash
uv run python scripts/storage_tests.py
RUN=results/<printed-run-directory>
uv run python scripts/serving_tests.py download --run "$RUN"
uv run python scripts/serving_tests.py agg --run "$RUN"
uv run python scripts/serving_tests.py smoke --run "$RUN"
uv run python scripts/request_tests.py routing --run "$RUN"
uv run python scripts/serving_tests.py disagg --run "$RUN"
uv run python scripts/request_tests.py disagg --run "$RUN"
uv run python scripts/sidecar_tests.py deploy --run "$RUN"
uv run python scripts/sidecar_tests.py smoke --run "$RUN"
uv run python scripts/sidecar_tests.py verify --run "$RUN"
uv run python scripts/modelexpress_tests.py source --run "$RUN"
uv run python scripts/modelexpress_tests.py target --run "$RUN"
uv run python scripts/modelexpress_tests.py verify --run "$RUN"
uv run python scripts/kvcr_tests.py build --run "$RUN"
uv run python scripts/kvcr_tests.py status --run "$RUN"
uv run python scripts/kvcr_tests.py deploy --run "$RUN"
uv run python scripts/kvcr_tests.py verify --run "$RUN"
uv run python scripts/serving_tests.py status --run "$RUN"
```

The ModelExpress script currently assumes the EFA ConfigMap created by the
disaggregation step. Source readiness must precede target launch. A disk fallback
is expected for the first source and cannot qualify target P2P loading.
Wait for KVCR's build to report Passed before deploying its matched runtime.
The build is preparation; `verify` checks actual peer reuse. A successful run
requires matched source/destination blocks and bytes, positive cache reuse,
expected inference and no failed or partial remote delivery.

## Evidence and cleanup

Each run records command outcomes, generated manifests, runtime image IDs, model
revision, logs, metrics and scoped pass/failure receipts in `results/<run>/`.
Successful inference alone does not establish routing, transfer, restore or P2P
loading. These bounded runs do not measure peak throughput.

```bash
uv run python scripts/serving_tests.py cleanup --run "$RUN"
uv run python scripts/kvcr_tests.py cleanup --run "$RUN"
# Or stop workloads for every test run recorded in this workspace:
uv run python scripts/cleanup_tests.py --run "$RUN"
scripts/kubecon-tunnel.sh stop
```

Disposable storage/NIXL/Grove probe pods are removed by their scripts. Serving
cleanup deletes owned DGDs and their children. The owned namespace, static Retain
PV/PVC and model cache remain for repeat tests; no shared EFS data is deleted.
A DGD may recreate a worker after its pod deadline, so use graph cleanup to stop
resource use. Review [TEST_PLAN.md](TEST_PLAN.md) for qualification scope.

Final cluster findings and requirements are in
[feature status](reports/2026-10-12-feature-status.md). Verify receipt storage
without cluster access with `scripts/check_receipt_storage.py`. Use
`scripts/archive_evidence.py` to freeze response/metric/log files with hashes
before rerunning a feature.

The [qualified common runtime](reports/2026-10-13-common-runtime-progress.md)
passed the bounded vLLM/Nemotron matrix, including native TP1 Snapshot.
Its image/version/model lock is `configs/common-runtime-qualified.json`.
Builds use a frozen context and an isolated AMD64 BuildKit worker on `gemini`.
`scripts/qualify_common_runtime.sh BUILD_RUN TEST_RUN` runs a published candidate
through the feature matrix in a fresh owned namespace, including a fresh
Snapshot and read-only Shadow/GMS inspection. The original passing runtime
locks remain available as baselines; no shared platform upgrade was needed.

[Snapshot enablement](reports/snapshot-enablement.md) follows the current dev
guide, including its release/recipe mismatch, required controllers, privileged
agent, artifact storage, and runtime qualification. The saved preflight remains
read-only; `--implementation legacy` checks the historical 1.4.2 integration.

The [CuInterpose TP2 retest](reports/2026-10-22-snapshot-cuinterpose.md) records
the pinned Snapshot development upgrade and its complete chart/values bundle.
`scripts/snapshot_cuinterpose_tests.py` runs the gated direct-vLLM capture,
restore, inference verification, resource observation and owned cleanup.
Use a fresh run with `prepare --keepalive` for the EFS publication workaround;
the report distinguishes this path from Dynamo DGD lifecycle qualification.

The [TP2 EFS/RAM storage control](reports/2026-10-22-snapshot-tp2-storage-comparison.md)
uses `scripts/snapshot_tp2_storage_compare.py` to restore the same hash-verified
artifact from EFS, disposable tmpfs, then EFS again. Copy time is measured
separately; shared storage configuration and disks are preserved.

## Dynamo upgrade and regression tests

[Upgrade review and results](reports/dynamo-upgrade.md) records the authorized
1.4.2 → 1.5.1 platform upgrade, exact chart hash and rollback limitations.
`prepare_dynamo_upgrade.py` backs up the current release and performs a server
dry-run. `apply_dynamo_upgrade.py --review <review-run> --apply` applies that
reviewed chart only after explicit authorization and checks rollout/CRD migration.

`upgrade_retests.py prepare --run <fresh-run>` rechecks the previous model cache
and KVCR wheel hashes in a fresh namespace. Its `agg`, `disagg`, `mx`, `sidecar`,
`kvcr`, and `grove` actions rerun the existing evidence checks. Run `disagg`
before `mx`/`kvcr` to create their EFA ConfigMap. Add `--runtime 1.5.1` to
`prepare` for a separate run with an immutable per-run public-runtime lock;
this preserves the original model/runtime configuration. Use
`serving_tests.py status --brief --run <run>` for compact progress with saved logs.

The serving default is now the qualified public Dynamo 1.5.1 image. Previous
runs keep their frozen locks; `configs/model-lock-original.json` retains the
original development-image profile. The experimental KVCR workers require the
recorded cold-JIT canary timeout; use `kvcr_tests.py deploy --canary-timeout 180`
for that configuration. No shared canary defaults were changed.

## GPU driver upgrade

The [R610 execution report](reports/2026-10-21-driver-upgrade.md) records the
authorized 580.173.02 → 610.57.04 upgrade, complete values, canary gates and
post-upgrade checks. The existing GPU Operator stays at 26.7.0. A fresh bundle
exports live values and pins chart/value hashes; the old DRA transition bundle
is preserved. `driver_build_probe.py` compiles modules in a CPU-only Pod with
read-only host headers. `apply_driver_upgrade.py` coordinates skip labels,
NVSentinel maintenance, DRA client eviction and one-node rollout verification.
Use the report's exact run and bundle paths to inspect this execution:

```bash
PY=.venv/bin/python
RUN=results/20261021-driver-upgrade
BUNDLE=configs/driver-upgrade-20261021
$PY scripts/apply_driver_upgrade.py --run "$RUN" --bundle "$BUNDLE" --phase status
$PY scripts/apply_driver_upgrade.py --run "$RUN" --bundle "$BUNDLE" \
  --phase diagnose --node kubecon-nke-site-cp-0124
```

Each upgraded node must pass `driver_cuda_probe.py --node NODE --run RUN`
(eight GPUs and NCCL) before `--phase advance --node NEXT` releases the next
node. `nixl_tests.py --pairs 3 --run RUN` tests cross-node VRAM transfers over
EFA using that run's immutable common runtime and DRA lock. After all nodes
pass, `--phase restore` restores the saved maintenance labels;
`driver_upgrade_audit.py --run RUN --bundle BUNDLE --cleanup-build-probe`
checks driver digests, boot IDs, DRA, infrastructure and cleanup. A passing
`snapshot_launch_probe.py --refresh-agent --run RUN` verifies the new checkpoint
utility and job-file creation, separately from native model capture/restore.

## Shadow Engine failover

[Requirements and test contract](reports/shadow-engine-failover.md) cover
`scripts/shadow_failover_tests.py`: `preflight`, `runtime`, `dry-run`, `deploy`,
`status`, `verify`, `cleanup`. The pinned Nemotron TP1 DGD uses two engines plus
GMS sharing one H100. Verification kills only the active EngineCore in the
owned Pod and requires actual standby promotion, shared-weight reuse,
expected inference and background standby replenishment.

Dry-runs and runtime-entrypoint inspection passed. Live failover is blocked:
NVIDIA DRA is ComputeDomain-only and all nodes use the GPU device plugin.
GPU DRA allocation with exclusive ownership on a test node is required. No
shared allocator change or failure injection was performed. Snapshot and EFA
DRA are not prerequisites for this test.

## Snapshot qualification

The reviewed Snapshot 0.1.0 installation was approved and applied alongside
Dynamo 1.5.1, with the agent restricted to cp-0124. Native Nemotron TP1
capture and new-Pod restored inference passed: 37.36 GB artifact, 16m17s
capture, 2m10s restore on EFS. TP2 and cross-node restore are unqualified. See
[the qualification result](reports/2026-10-13-snapshot-status.md) and
[the installation review](reports/snapshot-install-review.md).
The qualified common image also passed a fresh TP1 capture/restore: 35.87 GB
artifact, 16m29s capture and 2m05s agent restore. See the
[common-image result](reports/2026-10-13-common-runtime-progress.md).
`snapshot_runtime_tests.py` checks native preparation/resume;
`snapshot_tests.py` renders, deploys and verifies actual new-worker restoration.
`snapshot_diagnostics.py` saves API, controller, agent, CRIU and artifact evidence.
`snapshot_measurements.py` records artifact bytes and phase timings;
`snapshot_resource_summary.py` summarizes saved cgroup RAM high-water marks.

The [same-checkpoint EFS/RAM comparison](reports/2026-10-13-snapshot-storage-comparison.md)
isolated artifact storage as the dominant restore delay: EFS **124.4 / 124.0s**,
pre-staged RAM **14.2s**, with correct inference and identical workload settings.
`snapshot_storage_compare.py inspect|prepare-ram|compare|cleanup|report` makes
the control repeatable. Preparation checks a one-byte private mount before
copying and hashing the checkpoint; `snapshot_ram_bind.c` supplies the narrow
detached-mount helper. Use a fresh results directory for each completed comparison.
No disk formatting or shared Snapshot configuration change is needed. The
temporary helper and artifact view are removed automatically. Copy time is
reported separately; this does not install a reusable production cache.
The `reset` action stops only this run's DGD and capture jobs, retaining artifacts.

## Common runtime version

[Runtime consolidation assessment](reports/runtime-consolidation.md) records
why the original KVCR stack differed. The common preview image is now qualified
across the bounded feature matrix, including fresh TP1 Snapshot restore; its
lock is `configs/common-runtime-qualified.json`. Retained baseline locks are
unchanged. Live Shadow failover still needs the independent GPU DRA fix.
`scripts/audit_runtime_consolidation.py --output results/<fresh-audit>` saves
pinned dependency and Snapshot-hook source evidence without cluster changes.
