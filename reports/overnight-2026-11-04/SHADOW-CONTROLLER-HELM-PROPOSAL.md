# Proposal: provide Helm to the detached Full controller

**Recommend a Full-only read-only compatibility bind.** Mount the verified
Linux host executable `/usr/local/bin/helm` at `/opt/homebrew/bin/helm` inside
the Full controller and its CPU preflight container. Keep the real driver
values preflight unchanged. This needs no model/runtime changes, writer-basis
requalification, generic command rewriting or controller-image rebuild.

This is a read-only source proposal written while sources remain held. No code,
frozen candidate, central review document or cluster state was changed.

## Evidence and cause

- The actual a4 capture fails in `shadow_failover_tests.preflight`, before the
  guarded fault, attempting `/opt/homebrew/bin/helm`. The saved traceback is
  `results/shadow-full-a4-remote-collected-20261105-a1/recording/failed-main.txt`
  (SHA-256 `1247049fb3e040c018bdd54437f2bdd7012d294ee9ab058743907ba82241a26c`).
- `scripts/shadow_failover_tests.py:33` invokes the absolute macOS path.
  `scripts/testlib.py:71` passes command arguments directly to subprocess:
  **there is no existing Helm environment override** in the held source.
- Full bootstrap inherits Snapshot's kubectl, kubeconfig and Python-dependency
  binds (`scripts/workshop_snapshot_remote.py:313`); it supplies no Helm bind.
  The owned image recipe installs curl (`scripts/workshop_snapshot_controller_image.py:21`).
- Full's external CPU preflight delegates to the common preflight. The passing
  actual receipt at 01:32:56Z establishes image/PyYAML/curl/API readiness, not
  Helm availability. The launch-time source import probe also never runs Helm.

Before root's new check, retained evidence did not establish host Helm's path
or usability. Successful local Helm inventories were not evidence for the
jump host. Root has now retained a fresh read-only check in
`results/workshop-shadow-full-a4-root-closeout-20261105-a1/host-helm-readonly.json`:

| Binding | Verified value |
| --- | --- |
| Host path and resolved path | `/usr/local/bin/helm` |
| Version command exit | `0` |
| Version | `v3.22.0+g144ca65` |
| SHA-256 | `7a319dee5ea7a1f7d7a0d92d5c223586f3b65abc33163c9de2a85f083aa3df2b` |

This establishes a usable host executable. Its usability as container UID
1000 with the controller's mounts and credentials is the next CPU check.

## Smallest robust implementation

Confine the adapter to `scripts/workshop_shadow_full_remote.py` and focused
transport tests. Leave common Snapshot/writer transport, the owned image,
`testlib.py`, `shadow_failover_tests.py` and the v6/backend/CPU sources unchanged.

1. Freeze an explicit Helm dependency binding in the Full package/plan:
   fixed host path, resolved regular executable, exact SHA-256, expected version
   and fixed container destination `/opt/homebrew/bin/helm`. Validate this
   binding and current host bytes before preflight and launch; reject missing,
   nonexecutable or changed files without launching the controller.
2. Add exactly one read-only file bind to the Full detached Docker command:
   `type=bind,src=/usr/local/bin/helm,dst=/opt/homebrew/bin/helm,readonly`.
   Use the same binding for the Full CPU probe. Keep kubectl/kubeconfig/Python
   mounts and the existing image/user/capability restrictions.
3. Extend the **Full-specific** external preflight and the unconditional
   launch-time bootstrap probe to execute Helm in the exact pinned controller
   image, as UID/GID 1000:1000, with that same bind and read-only kubeconfig.
   Verify the mounted file's digest and `version --short`, then execute:

   ```text
   /opt/homebrew/bin/helm --kubeconfig <logical-root>/.local/kubeconfig get values nvidia-dra-driver-gpu -n nvidia-dra-driver -a -o json
   ```

   Require exit zero, parseable JSON and the existing preflight's true
   `resources.gpus.enabled` and `gpuResourcesEnabledOverride` conditions. This
   must be an actual live read, not a cached value or replacement report.
4. Run the launch-time check **before** detached controller launch and therefore
   before `full-gpu-intent.json` or DGD deployment. Use a bounded CPU-only
   container with no GPU/device mounts, `NVIDIA_VISIBLE_DEVICES=void` and host
   networking only for the read-only API call. Retain the tool/hash/version,
   command outcome and relevant driver values in the private control receipts,
   outside the frozen candidate. Share the Full probe construction between
   `preflight` and `bootstrap` so their mount/command behavior cannot diverge.

The existing late preflight should still run immediately before the guarded
fault. The early check prevents wasting GPU startup on a missing/incompatible
controller dependency; it does not replace fresh driver-state validation.

## Why this over an environment override

A caller-level `WORKSHOP_HELM_BIN` resolver would be cleaner for general Linux
portability. It would require changing the actual `shadow_failover_tests.py`
call site because `testlib` has no override. That file belongs to the accepted
writer-basis critical set, widening this repair's requalification scope. The
Full-only compatibility bind preserves that source and executes the same real
command. The unusual destination path is contained in this environment adapter;
it is not evidence of a Dynamo/GMS defect. General executable portability can
be a separate follow-up.

If the verified host executable becomes unavailable or fails the exact-image
CPU check, stop before GPU deployment. A fresh owned image with a pinned,
hash-verified Linux Helm binary is the fallback; it needs new image provenance
and validation rather than reuse of the current image receipt.

## Necessary verification before a fresh candidate

Focused transport tests should prove both CPU and detached commands receive the
same read-only bind, path/hash/version drift fails before detached launch, and
missing executable, failed version, RBAC/API errors, invalid JSON or disabled
DRA values prevent GPU actions. A passing CPU check must preserve the real Helm
get-values command and leave cluster state unchanged. Verify common Snapshot
bootstrap and native/writer/reader/CPU sources remain byte-identical. Root must
run the actual same-image CPU probe before any fresh Full candidate deployment;
no such new probe or deployment was performed for this proposal.

## Implemented after root's a4 closeout

Root subsequently closed the a4 reservation and released the Full transport
hold. The implementation changes only `scripts/workshop_shadow_full_remote.py`
plus the new focused `tests/test_workshop_shadow_full_remote_helm.py`. Shared
Snapshot/writer transports, the owned image, native preflight, testlib,
composed harness, writer basis, v6 adapter and CPU program remain unchanged.

The Full plan and payload manifest now contain the exact reviewed `helm`
binding. The same serialized helper functions implement external preflight and
the unconditional bootstrap check. The CPU container verifies mounted bytes,
permissions/version and the actual read-only driver query in the pinned image
as UID/GID 1000:1000. The detached controller receives the same compatibility
bind and kubeconfig destination. Bootstrap writes `helm-preflight.json` in the
private control directory before testing success, rechecks host bytes and only
then starts the detached controller. Failed/malformed native output, dependency
drift, Docker failure and a bounded CPU timeout block that launch. Existing
late native preflight remains unchanged.

The CLI requires no new flags. Root's next fresh package follows the existing
`build`, `preflight` and `launch` commands; `preflight --run <fresh-full-run>`
now includes Helm automatically, and bootstrap repeats the check immediately
before detached launch. The external SSH preflight budget is 150 seconds to
cover the existing checks plus the bounded 60-second CPU Helm probe. Historical
packages remain readable for status/collection, but cannot be newly launched
without the explicit binding. An actual read-only load of a4's 393-file package
passed with its original run/spec/demo bytes unchanged.

Root's separately retained `host-helm-same-image-cpu-probe.json` passed before
this implementation: it validates the chosen bind/image/UID/query approach.
It is not execution of the newly generated preflight/bootstrap. This reviewer
has performed only local source checks and test doubles; root must validate
the new generated CPU preflight before any fresh detached deployment. Existing
assigned-pair CUDA prerequisite checks are unchanged; the new CPU gate is
before the detached controller's Full GPU intent/deployment.

Final local validation: **34 focused tests pass** across the existing transport
and review suites (9 + 8), the new implementation tests (10), and the separate
independent Helm review tests (7). The independent reviewer found no blocker
and confirmed all 32 a4 core sources, native/common sources and the accepted
writer basis remain unchanged. Source comparisons against a4's full payload
find only the intended Full transport script changed.

| Reviewed file | SHA-256 |
| --- | --- |
| Full transport | `ed1252ec5c281cac4dabbbea49569fdf349dce3f3703b0f39c75203d40184185` |
| Implementation Helm tests | `8ca528dea32e077ef1a0cbdc7d2dc040cc062292c263c9b50d1fb7def97fcd15` |
| Independent Helm tests | `111e4aa26596fea54869e796fad8a9fcb27fa776e0b387515e42929c66670a74` |

The transport source is held at this reviewed hash for root's next generated
CPU preflight and fresh package execution. No freeze, live query, GPU action,
commit or push was performed by the implementation workstream.
