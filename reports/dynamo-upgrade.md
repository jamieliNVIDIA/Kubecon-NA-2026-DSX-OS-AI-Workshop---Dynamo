# Dynamo 1.5.1 upgrade review and retest plan

Prepared October 12, 2026, UTC evidence October 13. User explicitly approved
application and focused retests. **Upgrade applied successfully at
2026-10-13 05:08:13 UTC.** The operator is Ready, DGD/DCD stored/storage versions
are `v1beta1`, and all three GPU nodes are Ready. **All focused feature retests
passed**, including the adjusted KVCR retry and public-runtime qualification.

## Proposed platform change

Upgrade the existing `dynamo-platform` release in `dynamo-system` from 1.4.2
to **1.5.1**, the current stable release. Preserve the user-supplied settings
using `--reset-then-reuse-values`: Kubernetes discovery, Prometheus endpoint,
controller tolerations, and integration with the separately installed Grove
and KAI releases. Explicitly leave Snapshot installation and checkpoint support
disabled. This does not upgrade Grove, KAI, GPU Operator, EFA, storage drivers,
or any inference image. Snapshot installation is a separate proposal.

The server dry-run passed. The release currently has revision 1 and there are
**no active DGDs and no legacy DynamoCheckpoint objects**. The rendered changes:

- Operator and CRD-init image: `kubernetes-operator:1.4.2` → `:1.5.1`.
- Adds the `dynamo-epp` PodMonitor.
- Removes the old operator's PodSnapshotContent ClusterRole and binding.
- Changes operator configuration/RBAC/webhooks to the new release contract.
- Its CRD init/migrator promotes DGD/DCD storage to `v1beta1`. Helm dry-run
  does not execute that migration and is not proof of successful rollout.

The target chart SHA256 is
`b220d4ccc6b8c1dd25df80b471469380721432a32413ee58920d7fb0c0d38e41`.
Private backups, source chart, exact upgrade arguments, old CRDs/custom objects,
rendered manifests and command receipts are in
`results/20261013t050322z-features/`. Do not commit the raw Helm backup: it may
contain chart-managed credentials/certificates. The entire results tree is ignored.

The user explicitly authorized this concrete shared operator/webhook/CRD upgrade
after reviewing its scope. Helm rollback alone does not undo CRD migration. Backups exist;
any rollback must review the CRD schema/storage state as well as the Helm revision.

## Runtime change is a separate decision

The previous integrated serving tests used the model-specific development image,
with Dynamo 1.4.0 and vLLM 0.26.1rc1 despite its 1.5.0 image tag. A Helm upgrade
does not replace those images. Keep those previous receipts immutable.

The candidate public `vllm-runtime:1.5.1` is pinned in
`configs/dynamo-1.5.1-runtime.json`, index digest
`sha256:2b224a823d52a198ec0eeb0e3e4f5cf26cd8a7fc2e9812ee16204b6b1e974870`.
The release pins vLLM 0.28.0, NIXL 1.3.2 and ModelExpress 0.6.0. Driver 580+
and Hopper are documented baseline support; the exact preferred Nemotron model
still needs a serving qualification in this runtime.

A disposable one-GPU candidate packaging/GPU/EFA probe passed in
`results/20261013t050357z-features/`: actual packages match the release,
GPU arithmetic passed and all four assigned EFA providers were visible.
It does not load a model or prove inference. Fresh feature retests use
`results/20261013t050900z-upgrade-retests/`; model/cache reuse is freshly verified,
including hashes of the previously built KVCR wheels. Grove/KAI scaling passed.

The public 1.5.1 runtime has now passed preferred Nemotron inference and
two-worker KV routing in `results/20261013t051300z-runtime-151/`, with the expected
READY output, six unforced cache-affinity repeats and 2176 cached tokens each.
Its cross-node disaggregation and ModelExpress 0.6.0 P2P qualification also passed.
Installed ModelExpress source confirms both `modelexpress` and `mx` loader aliases;
the existing loader flag remains valid.

## Regression discovered and scoped retry

The initial KVCR retry passed inference but failed discovery of its second
worker. Pod events and previous-container logs show a **liveness restart during
first-use FlashInfer JIT**, not a measured failed peer-cache transfer. The newer
operator enabled synthetic canary inference. One worker began compiling
`selective_state_update_..._nt_1_..._sm90`; the three-second canary requests timed
out and Kubernetes restarted it before compilation completed. The initial failed
request, Pod/event/health evidence and logs are frozen in
`results/20261013t050900z-upgrade-retests/evidence-1791869442868792000/`.

The owned KVCR DGD was recreated with
`DYN_HEALTH_CHECK_REQUEST_TIMEOUT=180` **only on its workers**, using
`kvcr_tests.py reset --canary-timeout 180`. Canary checks remain enabled, as do
the Kubernetes liveness/readiness probes. The retry must still prove correct
cross-node cache delivery and expected inference. This is an experimental
workshop cold-start allowance, not a change to the shared operator defaults or
a production timeout recommendation. The adjusted retry passed: five matched
source/destination blocks, 33,423,360 bytes, 2176 cached tokens, expected output,
and zero failed/partial remote deliveries. Both workers then remained Ready
with zero restarts across three idle-health samples each, 15 seconds apart.

## Completed results

| Check | Previous runtime under operator 1.5.1 | Public runtime 1.5.1 |
| --- | --- | --- |
| Nemotron inference | Passed, READY | Passed, READY |
| KV routing | Passed, six repeats / 2176 cached tokens each | Passed, six repeats / 2176 cached tokens each |
| Cross-node disaggregation | Passed, 72,155,136 KV bytes, zero transfer/notification failures | Passed, 72,155,136 KV bytes, zero transfer/notification failures |
| ModelExpress P2P | Passed, 761 tensors / 18.87 GB, no receiver disk fallback | Passed with ModelExpress 0.6.0, 761 tensors / 18.87 GB, no receiver disk fallback |
| Engine sidecar | Passed with stock vLLM 0.28.0 and CPU sidecar 1.5.1 | Separate pinned sidecar stack; integrated image is not substituted |
| KVCR | Passed with the existing pinned 1.6.0 preview/adapter stack and scoped 180s canary timeout | Separate preview stack; not included in stable 1.5.1 |
| Grove/KAI | Passed GPU gang admission and scale 1→2→1; real DGDs reconciled through Grove | Same external Grove/KAI versions |

The public runtime became the **local serving default** after these checks,
using `scripts/promote_dynamo_runtime.py`. `configs/model-lock-original.json`
preserves the original development-image lock; existing runs keep their frozen
`model_lock`, and new runs use the new digest plus `runtimeVersionOverride: 1.5.1`.
The model identity and exact weight revision are unchanged. Basic diagnostic
image pins and the separate sidecar/KVCR runtime pins remain explicit.

The before/after Helm comparison showed **only** `dynamo-platform` changed,
from revision 1 / 1.4.2 to revision 2 / 1.5.1. No other Helm chart was upgraded.
No driver, node, security-group, storage backend or shared queue changes were made.

These are bounded functionality checks (TP1, 4096 context, small request counts),
not throughput or startup benchmarks. Several cold loads ran concurrently from
EFS, and EFA userspace was installed inside disposable containers. Their startup
times are not a controlled comparison. Preserve/prebuild the workload compiler
caches and qualify readiness timeouts before workshop cold-start demos.

Passing evidence archives:
`results/20261013t050900z-upgrade-retests/evidence-1791870129072422000/` and
`results/20261013t051300z-runtime-151/evidence-1791870130662115000/`.
Owned test-workload cleanup passed at 2026-10-13 05:43:03 UTC, with zero remaining
test Pods. Namespaces, Retain PV/PVCs and cached data were preserved.
Final inventory `results/20261013T054424Z-inventory/` reconfirmed three Ready
H100/EFA nodes, the unchanged drivers/kernel/resources and Dynamo Helm revision
2 / 1.5.1. The final Snapshot preflight at 05:44:28 UTC remained blocked by
the missing Snapshot operator, agent, SnapshotJob CRD and checkpoint enablement.

## Retests after a platform-only upgrade

| Priority | Retest | Pass evidence |
| --- | --- | --- |
| 1 | Controller rollout, webhook admission and CRD migration | Operator Ready; expected image; DGD/DCD storage `v1beta1`; no init/migrator errors; all nodes Ready. |
| 1 | Aggregated Nemotron deployment and inference | Owned DGD creates workers/frontend, model registered, correct READY response using the previous pinned runtime. Exercises probes, identity/env injection and RBAC. |
| 1 | KV-aware routing | Two workers on different nodes; six unforced prefix-affinity repeats; nonzero cached tokens and applied KV store events. |
| 1 | Grove/KAI | Existing dummy GPU gang scales 1→2→1; verify queue/scheduler injection plus a real DGD reconciles through Grove. Existing external versions stay pinned. |
| 2 | Engine sidecar | Stock vLLM plus CPU-only Dynamo sidecar registers and answers after operator namespace/probe injection. This already uses Dynamo sidecar 1.5.1; upgrading Helm alone does not make it a new runtime test. |
| 2 | Cross-node disaggregation | Correct short/long outputs, distinct P/D nodes, positive completed KV transfer bytes and zero transfer/notification failures. |
| 2 | ModelExpress P2P | Source and receiver register across separate DGDs; positive completed tensor transfer over LIBFABRIC/EFA; receiver inference; no disk fallback. |
| 2 | KVCR | Recheck sidecar/readiness/runtime-version override injection with the existing custom 1.6.0 runtime; positive matched cross-node write/read bytes, cached prefix reuse, zero failed/partial reads. |
| Separate | Snapshot | Upgrade/preflight alone is not a capture/restore test. Still needs its operator, privileged agent, artifact claim and a compatible runtime; see `snapshot-enablement.md`. |

## Retests if the integrated runtime also moves to 1.5.1

Repeat model load and exact output first, then KV routing, NIXL disaggregation,
and ModelExpress P2P with both endpoints on the same newly pinned runtime.
ModelExpress moves from 0.5.0 to 0.6.0, so this deserves a full weight-transfer
test, not just Pod readiness. Preserve model revision, prompts, TP1 and context
settings for comparison. The CPU sidecar and custom KVCR stack should keep their
own exact pins; do not overwrite their backends with the integrated 1.5.1 image.

Do not repeat the full NCCL bandwidth sweep, EFA device-plugin test or EFS
correctness test solely for this operator/runtime change. Repeat those only if
GPU/network/storage infrastructure changes or new evidence suggests a regression.
The bounded disaggregation/P2P/KVCR tests exercise the relevant data path again.

## Known limits

- Stable 1.5.1 does not close the dev Snapshot recipe mismatch. The guide's
  TRT-LLM recipes exist on main but are absent at the v1.5.1 paths; multi-GPU
  H100/Nemotron capture still needs qualification with a matched build.
- SGLang sidecar 1.5.1 has a documented inference protocol failure with bundled
  SGLang 0.5.18; the fix is targeted for 1.6.0. Our passing vLLM sidecar result
  does not qualify the SGLang sidecar.
- Snapshot's standalone vLLM example explicitly excludes vLLM 0.28; a generic
  integrated runtime upgrade is not evidence that that example now works.

Sources: [1.5.1 release notes](https://github.com/ai-dynamo/dynamo/releases/tag/v1.5.1),
[1.5.0 breaking changes](https://github.com/ai-dynamo/dynamo/releases/tag/v1.5.0),
[compatibility](https://docs.nvidia.com/dynamo/latest/reference/compatibility).
