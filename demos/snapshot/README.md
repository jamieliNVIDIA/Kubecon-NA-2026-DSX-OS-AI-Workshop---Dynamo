# Demo 4: Snapshot Pod recovery

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

The new [Dynamo-managed presenter candidate](DGD.md) is available through
`uv run python -m demos snapshot-dgd`. It wires the qualified upstream-controller DGD/NVMe flow into the
same keypress/tmux presentation, including frontend coding inference. This page
documents the retained native fallback through `python -m demos snapshot`; its recordings and
artifact remain unchanged. See the candidate guide for current validation.

Restore an initialized Super VL engine into a new Pod after deleting this demo's
serving Pod. Capture and storage preparation happen offstage. The first version
uses the qualified **native vLLM Snapshot path**, on the same node and physical
GPU pair. A separate [DGD qualification](../../reports/workshop-snapshot-dgd.md)
now passes automatic worker replacement, frontend registration and fresh coding
chat with an experimental runtime adapter on EFS. This page's runner still
uses the native path. The integrated DGD candidate linked above now has its own
passed main-panel recording; cross-node recovery remains unqualified.

The [upstream-controller follow-up](../../reports/workshop-snapshot-upstream-controller.md)
also passed the DGD flow. It removes the custom pause/resume controller while
retaining the identity/offline bridge; use that candidate for presenter wiring.

The [DGD NVMe follow-up](../../reports/workshop-snapshot-dgd-nvme.md) now passes
initial and automatic-replacement coding inference too: **48/59 s Pod-to-Ready**,
with **99.11 s deletion intent to observed successful replacement response**.
The artifact is copied and fully verified offstage; the creating DGD must stay
alive through the onstage replacement. This is a separate qualification CLI
transcript; the presenter below still uses its original native path.

The restore claim explicitly selects the verified GPU UUIDs for the original
pair; a generic count of two would depend on allocator ordering. That CEL
selector passed a server dry-run on the workshop cluster.

```bash
uv run python -m demos snapshot --rehearsal
```

Controls and tmux layout match the other demos: Enter/Space submits the shown
command or advances, `q` stops, the main screen clears on advance, and there is
no printed control cue. Add `--plain` for one terminal.

```bash
uv run python -m demos snapshot --preview
uv run python -m demos snapshot --rehearsal --plain --auto
```

Rehearsal is entirely offline. Illustrative Pod UIDs are labeled simulated;
restore durations and speedups are not invented.

## Offstage preparation and live flow

Use the existing pinned cluster/runtime and retained capture namespace. This
needs two H100s on cp-0124, the compatible Snapshot agent/PageBroker build, and
the exact Ready artifact described in `prepared-source.json`. That small file
and `artifact-files.sha256` are committed metadata, not the ~99 GB checkpoint.
The initialized engine settings are copied from the qualified capture template;
the runner does not replace them with demo 1's eager configuration.

The default `nvme` mode verifies the already prepared ext4 filesystem identity
and every artifact hash. It then reuses the narrow artifact-specific read-only
overlay inside the existing agent's private mount namespace. Cleanup restores
the EFS view and removes the temporary helper. The runner does not format a
disk, mount a host filesystem, copy/overwrite the checkpoint, or change shared
Helm values/agent specifications. If the node rebooted and its runtime-only SSD
mount disappeared, preparation stops; restore the reviewed storage setup
separately before running this demo.

```bash
# Offstage: verify the retained artifact and start a disposable restored Pod.
uv run python -m demos snapshot prepare
uv run python -m demos snapshot prime --auto

# Onstage: the same run retains its storage choice and primed Pod.
uv run python -m demos snapshot

# Finish: delete only this run's restore Pods and restore the private EFS view.
uv run python -m demos snapshot cleanup --auto
```

Choose `--storage efs` on the first invocation to use the existing shared-storage
path instead; the choice is frozen in the run. This still restores on the same
node. EFS was much slower in the historical control, so allow several minutes.
The offstage `prime` is itself a restore; it does not rerun the 19-minute capture.
Live playback requires that primed serving Pod and refuses to run preparation
or an initial restore onstage. An interrupted replacement resumes at screen
2 of 4 with its original restore intent; it does not prime another source Pod.
Restore Pods have a six-hour deadline to cover preparation plus the three-hour
workshop; explicit cleanup releases the GPUs when the demonstration finishes.

The walkthrough has four screens:

1. Explain initialize once → artifact → replacement process and inspect the
   prepared resource/annotation settings. Current native scope is explicit.
2. Submit deletion of the owned serving Pod, then creation of a distinct restore
   Pod. Follow continuous restore/startup through Ready. Immediately show agent
   phase durations and Pod-to-Ready time.
3. Show a compact recovery summary after verifying different before/after Pod
   UIDs, exact artifact binding, `nvidia.com/Restored=True`, runtime image, node
   and physical GPU pair. Full identities remain in `recovery-proof.json`.
4. Forward the recovered Pod and submit a fresh `/test` request. This captured
   app generates `READY` and returns the pinned model/revision/TP identity.

The artifact released KV cache before capture. This demonstrates initialized
engine recovery; it does not resume an in-flight user stream or retain the
production prefix cache. Request migration has a separate role in the outline.

`timing.json` separates agent restore, Pod creation-to-Ready, and observed
apply-to-Ready boundaries. Capture, staging and artifact hash verification are
outside these clocks. No matched cold-start baseline is included; demo 1 uses
different engine settings. The [historical control](../../reports/2026-10-22-snapshot-tp2-nvme-comparison.md)
provides storage evidence with its own carefully labeled timing boundaries.

## Safety, interruption and validation

Preparation requires the independent measurement lease to be released by its
owner, idle GPU claims, and compatible agent/artifact identities. Cleanup checks
the per-run `snapshot-storage-experiment` label and retains the capture namespace,
SnapshotJob, Snapshot/content and checkpoint files. Never use a broad namespace
cleanup against this retained capture namespace.

Stopping leaves the owned Pod and any private overlay available for resumption
or explicit cleanup. A recorded replacement/restore intent allows resumption
after deletion or during startup. Cleanup retains the lease on ownership,
agent-identity, or storage-view uncertainty.

Offline flow, real tmux/key gates, evidence parsers and lifecycle safety checks
are validated. A fresh live run passed on November 4 UTC after verifying all
artifact hashes. The onstage replacement restored a distinct Pod on the exact
GPU pair, reached Ready in 41s from Pod creation (37.3s agent restore), and
returned fresh READY inference. See the
[actual main-panel recording](../transcripts/live/04-snapshot/20261104-a1/main.txt).
These clocks exclude the preceding deletion and offstage preparation. This
qualifies the native same-node path. The later
[DGD CLI transcript](../transcripts/live/04-snapshot-dgd/20261104-a3/qualification.txt)
establishes the functional integrated path on EFS (352s replacement Pod-to-Ready,
374.72s deletion intent to observed successful response). It is a separate
qualification, not a retake of this presenter's NVMe recording. The next steps
are to wire the qualified upstream-controller NVMe flow into this runner.
