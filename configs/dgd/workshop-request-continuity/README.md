# Request-continuity examples

`disabled.yaml` and `enabled.yaml` derive from the qualified single-replica
template via `scripts/workshop_migration_demo.py:render`. Each contains its DRA
claim template and aggregated DGD: one CPU frontend and two TP2 H100 workers.
The only behavioral difference is frontend `DYN_MIGRATION_LIMIT` zero or three.
Combined footprint: eight H100s. These examples require the workshop's existing
operator, model-cache PVC, pull secret, runtime and GPU DRA setup.

Use the [presenter launcher](../../../demos/05-request-continuity/README.md)
for namespace preparation, exact model checks, dry-runs, immutable per-run
manifests and ownership-checked fault injection/cleanup. It renders fresh
run-specific inputs; these example namespace/name values are not an instruction
to apply directly to an existing workshop run.
