# Dynamo-managed Snapshot recovery from node-local NVMe

**Passed November 5, 2026 UTC (November 4 Pacific):** both the initial restored
worker and its automatic replacement served correct streaming coding responses
through the same Dynamo frontend using a pre-staged node-local NVMe checkpoint.
The creating DGD, frontend, Service, artifact, node and physical GPU pair stayed
the same. Worker Pod and decode-worker identities changed on replacement.

This closes the local-storage qualification gap from the
[upstream-controller EFS trial](workshop-snapshot-upstream-controller.md).
It uses that exact Super VL revision, runtime image, upstream module backport,
identity/offline bridge, TP2 compiled text-only 8k profile and 0.65 GPU memory
fraction. It does not add a custom pause controller or change the shared platform.
The pinned image still requires the workload-local module overlay; this is not
qualification of an unmodified published runtime image.

## Timings

| Boundary | Initial NVMe restore | Automatic NVMe replacement |
| --- | ---: | ---: |
| Agent restore | 34.05 s | 36.86 s |
| CRIU phase | 19.36 s | 19.31 s |
| CUDA phase | 13.05 s | 16.06 s |
| Pod creation to Ready | 48 s | 59 s |
| Deletion intent to observed successful frontend response | — | 99.11 s |

Both serving Pods were created after NVMe staging and activation. Neither Pod creation-to-Ready clock includes preparation. The agent clocks and replacement Pod clock exclude
capture, publication, copying and hash verification. Activation to initial Ready
was 78.42 s. The final response boundary
includes observer polling, API/port-forward setup and a fresh request; it is not
a continuously sampled availability or SLO measurement.

The previous EFS replacement was **342 s Pod-to-Ready** and **360.98 s deletion
intent to observed response**. Those are useful prior observations, but the two
runs captured different artifacts. No matched storage or cold-start speedup is
claimed. A separately authorized routing campaign ran on other nodes during this
qualification and could share EFS/network services.

## What actually ran

Run `workshop-snapshot-dgd-upstream-nvme-20261104-a1`, namespace `dynamo-ft-20261104t234901z`,
on `kubecon-nke-site-cp-0124`, used a fresh operator-managed automatic checkpoint.
Both Snapshot resources had to be Ready before staging. The capture-only helper
held the exact source GPU claim while the checkpoint was inventoried, hashed,
copied to a fresh `.partial` directory and verified before atomic promotion.

The artifact contains **1,818 files / 94,229,153,009 logical bytes**.
Source hashing took **330.83 s**, copying
**47.15 s**, and local hash verification
**73.14 s**. These are offstage preparation costs.
Manifest SHA256: `30dd43cf3384935d075c55d52356e22740e100105863cf7e8a64a2e4d323893f`.

An artifact-specific read-only ext4 clone was attached inside the existing
Snapshot agent's private mount namespace. Only then was the source helper
released. The analysis checks both agent restore-start timestamps occur after
NVMe activation and records the exact direct artifact mount for each restore.
Device counters observed **187,783,430,144 bytes read**
from `/dev/nvme0n1` after staging/verification and through the two restores.
No global page-cache flush was used. Disk UUID/serial and agent identity/spec
were pinned; no disk formatting, host mount, shared Helm/PVC or agent-spec
change was performed.

Both requests checked the expected model, successful stream stop/DONE, no stream
error, Dynamo worker identity and a Python `add(a, b)` function returning `a + b`.
Snapshot content UID: `5eb7993d-64b0-4969-990d-5f2556012e0a`.
Replacement Pod UID: `b3fc88aa-63ae-464e-8724-b7abb4b8190b`.

## Evidence and cleanup

- [Actual qualification CLI output](../demos/transcripts/live/04-snapshot-dgd-upstream-nvme/20261104-a1/qualification.txt)
- [Shareable provenance and timing manifest](../demos/transcripts/live/04-snapshot-dgd-upstream-nvme/20261104-a1/qualification.json)
- Full local receipts, source snapshots, file manifest and analysis remain under
  `results/workshop-snapshot-dgd-upstream-nvme-20261104-a1/`.

The first attempt stopped before deployment because an agent-namespace `df`
could not resolve the host filesystem. The probe was corrected to enter its host
mount namespace. The original failure, corrected source snapshot and actual
resume output are retained. No DGD, engine initialization or capture was replayed.
A separate optional directory-size progress probe timed out during publication;
controller readiness remained authoritative and qualification continued.

Owned workloads were removed before restoring the agent's EFS view and removing
its temporary mount helper. Both matching Snapshot reservations were released.
Independent audit at **2026-11-05T00:39:17.552649+00:00** passed: all nodes Ready, no owned
GPU Pods/claims/DGDs, no active GPU Pod on the Snapshot node, unchanged agent
UID/spec, original and new snapshots retained Ready, and no new GPU Xids.
The unrelated routing namespace/resources and its separate reservation were
preserved. Both original EFS and verified local checkpoint copies remain.

The live executable source was frozen before deployment. The initial test receipt
records 96 passing Snapshot tests, including the new storage gate and 16 focused
NVMe lifecycle/safety checks. After live cleanup, saved helper/staging path
validation was moved ahead of any copy/unmount for corrupt-state rejection;
18 focused NVMe checks pass on that hardened helper. The measured executable
sources remain separately frozen; see `post-run-safety-hardening.json`.

## Workshop implications

Use this as the functional local-storage candidate for DGD presenter wiring.
Capture, publication and staging happen offstage. Keep the **creating DGD alive**
from priming through the onstage replacement: retained automatic checkpoints are
bound to that DGD UID and cannot simply be adopted by a newly created graph.
This test cleaned its DGD after qualification, so its retained artifacts are
evidence, not a primed live workshop service.

Presenter/tmux wiring and retaining or upstreaming the identity/offline bridge
remain. This qualification covers same-node fresh-request capacity recovery;
it does not cover node loss, preserved KV state, in-flight request migration,
or a combined ModelExpress/Shadow/Snapshot deployment.
