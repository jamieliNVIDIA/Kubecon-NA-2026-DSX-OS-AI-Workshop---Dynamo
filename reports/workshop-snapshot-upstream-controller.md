# Snapshot trial with the upstream KV-only controller

**Local-storage follow-up passed:** the same runtime/profile now passes initial
and automatic-replacement inference from pre-staged NVMe: **48/59 s Pod-to-Ready**,
**34.05/36.86 s agent restore**, and **99.11 s deletion intent to observed response**.
See the [NVMe qualification](workshop-snapshot-dgd-nvme.md). The EFS observations
and provenance below remain separate; these are different captured artifacts.

**Passed November 4, 2026:** the upstream KV-only implementation and native
`VllmEnginePauseController` passed capture, initial restored inference, automatic
worker replacement and replacement inference through the same Dynamo frontend.
The custom v3 pause/resume controller is unnecessary for this pinned Super VL
configuration. The remaining custom runtime code supplies destination Pod
identity and offline policy from the Snapshot restore proxy.

55 scoped offline checks pass, including seven upstream-integration checks and
a CRIU source-exit/publication regression. CPU-only pinned-image/cache checks,
admission, owned workload cleanup and independent GPU/cluster audit also passed.
The [actual qualification CLI transcript](../demos/transcripts/live/04-snapshot-dgd-upstream/20261104-a1/qualification.txt)
and [provenance manifest](../demos/transcripts/live/04-snapshot-dgd-upstream/20261104-a1/qualification.json)
retain the observation correction described below. This is a qualification CLI,
not a new recording of the existing native demo 4 presenter.

The first observer attempt stopped at 22:56 UTC because an added check treated
source exit 137 as an engine failure. Agent logs show successful CRIU dump at
the same instant; the passing v3 source also exited 137 exactly at dump completion.
That observer check was incorrect and was removed. The original observer-error
receipt/log remains retained. Verification resumed against the same DGD/source/
artifact; no deployment, model initialization, runtime module or capture was
replayed or changed. Actual SnapshotJob/PodSnapshot failure/readiness gates
remained authoritative through EFS publication.

The passing [v3 trial](workshop-snapshot-dgd.md) used a custom pause/resume
controller plus restore-proxy identity and offline-policy fixes. This trial
uses the exact module from merged Dynamo PR #15887, with only the existing
identity/offline bridge added. The original `VllmEnginePauseController` and
communicator checkpoint hooks remain enabled when supported by the engine.
This is a workload-local backport into the same pinned image, not a full
runtime upgrade. The v3 candidate, snapshots and evidence remain unchanged.

## Result and timing scope

Run `results/workshop-snapshot-dgd-upstream-20261104-a1`, namespace
`dynamo-ft-20261104t221053z`, used the
[frozen candidate](../configs/dgd/workshop-snapshot-dgd-upstream/).
The model lock and engine/storage/node/GPU configuration are identical to v3;
the effective manifests differ only by namespace and runtime ConfigMap name.
The installed image has vLLM `0.31.1rc1.dev23+g43b4aaea3` and both communicator
checkpoint methods. Source logs show KV release and checkpoint readiness,
without the missing-hook fallback warning; restored logs show KV wake and
registration. No separate per-call hook tracing was added.

| Boundary | Initial restore | Automatic replacement |
| --- | ---: | ---: |
| Pod creation to agent Restored condition | 322 s | 330 s |
| Pod creation to Ready | 334 s | 342 s |
| Deletion intent to observed successful frontend response | — | 360.98 s |

Initial response completed at **23:18:08.959720 UTC**. Deletion intent was
**23:18:23.940655**, replacement creation **23:18:24**, Restored **23:23:54**,
Ready **23:24:06**, and successful replacement response **23:24:24.923455**.
The last boundary includes observer polling, API/port-forward setup and the
request; it is not a continuous availability measurement. These are single-run
EFS observations, without a matched speedup claim or DGD-from-NVMe measurement.

Both fresh streaming requests returned correct Python `add(a, b)` code with
stop, DONE and no stream error. Pod UID changed from
`71d1410a-dfda-4e40-a164-5a2cba85ea9a` to
`6e3d0d2d-2068-473c-94ce-45fc481cfdd3`; decode-worker ID changed from
`7964319560988462` to `6784954611980798`. DGD
`4236c7c2-8d88-492d-8382-3aacf9270743`, frontend Pod/Service, artifact, node and
both physical GPU UUIDs remained unchanged.

The automatic checkpoint became Ready at **23:11:58**, 26m28s after its API
object was created. CUDA checkpoint timers were **37.65/38.17s** for the two
TP workers, and CRIU dump took **56.45s**, finishing **22:55:47.039**. The
remaining dump-to-Ready publication/verification window was about **16m11s**;
it is not a GPU restore timer. Capture/preparation remains offstage, and the
creating DGD must stay alive through the workshop's replacement demonstration.

## Cleanup and remaining work

Owned workloads were cleaned and both matching reservations released at
**23:24:48 UTC**. Independent audit at **23:25:27 UTC** passed: all three nodes
Ready, zero active GPU Pods/ResourceClaims/DGDs, absent local/remote reservations,
unchanged Snapshot agent UID/spec, retained native and new DGD snapshots Ready,
and no new kernel Xids (the same 88 historical messages). The owned log followers
were stopped. Proof: this run's `final-cleanup-proof.json`.

Use the upstream-controller candidate for the next workshop integration.
Presenter/tmux wiring and upstreaming or
retaining the identity/offline bridge remain. The pinned image still needs that
module overlay; the test does not qualify an unmodified published image.

## Tasks

- [x] Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
  - Same Super VL revision/image, TP2, compiled text-only 8k profile, exact H100
    UUID pair on cp-0124, EFS, Kubernetes, as v3.
- [x] Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
  - Reuse the renderer and v3 frozen settings; change only runtime module/ConfigMap.
- [x] Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
  - Frozen in `configs/dgd/workshop-snapshot-dgd-upstream/` and fresh run
    `results/workshop-snapshot-dgd-upstream-20261104-a1`.
- [x] Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
  - Both client/server dry runs passed; no DGD or GPU claim was created.
- [x] Hand off to `deploy_dynamo` or `kubectl apply`
  - The sequential qualification orchestrator submitted the fresh candidate
    after the prior owner released its reservation and idle checks passed.

## Qualification gates

1. Verify exact upstream module provenance and ensure the remaining changes
   only supply destination identity/offline policy.
2. Freeze a fresh run and manifests. Check controller semantics locally and
   inspect the actual image's communicator hooks with a CPU-only probe.
3. Acquire both GPU reservations after the request-continuity owner releases
   its reservation and workload/claim cleanup is independently proven.
4. Observe operator capture; require positive hook/capture evidence. A capture
   failure is not a successful qualification and must not be silently retried.
5. Require initial and automatic-replacement coding inference through the same
   frontend, with distinct Pod/worker identities and the same artifact/GPU pair.
6. Preserve logs, phase timings and an actual qualification CLI transcript.
   Clean owned workloads, audit GPU health and release only matching leases.

No shared operator/driver/allocator/storage configuration changes are part of
this trial. No NVMe speedup, cross-node restoration, KV persistence or in-flight
request continuity is inferred from it.
