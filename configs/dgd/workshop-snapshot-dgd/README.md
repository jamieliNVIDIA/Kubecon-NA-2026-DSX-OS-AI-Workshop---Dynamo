# DGD Snapshot qualification candidate

These are the frozen inputs for `results/workshop-snapshot-dgd-20261104-a3`.
They passed client/server admission and live DGD-managed capture, initial
frontend coding inference, automatic worker replacement, and replacement coding
inference on November 4. Same node/exact GPUs, EFS, experimental adapter required.
The presenter UI and DGD-from-NVMe timing remain to qualify. See
[the qualification report](../../../reports/workshop-snapshot-dgd.md).

`deployment.yaml` contains the exact-pair GPU claim template and checkpoint-
enabled DGD. `runtime-patch.yaml` contains the immutable, workload-local adapter
for the pinned runtime and newer Snapshot proxy protocol. `candidate.json`
records source/patch hashes and model/runtime identity. No shared image or
operator is modified.

Use `scripts/workshop_snapshot_dgd.py` with a fresh owned run for another trial.
The namespace and GPU UUIDs here are evidence inputs, not portable defaults.
Capture is offstage; the onstage investigation deletes only a serving worker
and verifies automatic recovery through its existing frontend. Keep the DGD
alive during that investigation because automatic artifacts belong to its UID.
