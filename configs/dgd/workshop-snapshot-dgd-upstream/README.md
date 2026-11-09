# Upstream KV-only Snapshot controller trial

Passed live capture, initial frontend coding inference, automatic replacement
and replacement inference on November 4, with independent cleanup/health audit.
Replacement: 342s Pod-to-Ready / 360.98s deletion intent to observed success on
EFS. No matched speedup or DGD NVMe result is claimed.

Fresh counterpart to the passing v3 candidate in `../workshop-snapshot-dgd/`.
This keeps its image/model/engine/storage/GPU configuration while replacing the
custom pause controller with the exact merged Dynamo PR #15887 implementation.
The installed native controller's communicator checkpoint hooks are preserved.
The only additional module changes are the qualified restore-proxy identity
and destination offline-policy bridge.

`upstream-snapshot.py` is the original module at upstream commit
`521225369330f2120f1676748057a692a24c2303`, with its original license header.
`scripts/snapshot_dgd_upstream_patch.py` checks both the installed-module and
upstream-module hashes before creating the runtime overlay.

The manifests target a fresh owned namespace and the workshop's exact H100
UUID pair. They are qualification evidence, not portable deployment defaults.
No full image upgrade or shared platform modification is included.

See [the live trial report](../../../reports/workshop-snapshot-upstream-controller.md).
