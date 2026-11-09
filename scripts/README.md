# Cluster and development tools

This folder contains the cluster qualification harness and supporting tools.
Presenter entry points and their required helpers live in [demos/](../demos/README.md).
The automated regression suite lives in [tests/](../tests/README.md).

| Task | Entry points |
| --- | --- |
| Cluster access and inventory | [kubecon-env.sh](kubecon-env.sh), [kubecon-jump-env.sh](kubecon-jump-env.sh), [kubecon-tunnel.sh](kubecon-tunnel.sh), [cluster_inventory.py](cluster_inventory.py) |
| Platform and driver upgrades | `prepare_driver_upgrade.py` / `apply_driver_upgrade.py`, `prepare_dynamo_upgrade.py` / `apply_dynamo_upgrade.py`, `prepare_gpu_dra_upgrade.py` / `apply_gpu_dra_upgrade.py`, `prepare_snapshot_install.py` / `apply_snapshot_install.py` |
| Runtime and image qualification | [common_runtime_build.py](common_runtime_build.py), [common_runtime_tests.py](common_runtime_tests.py), [super_vl_tests.py](super_vl_tests.py), [qualify_common_runtime.sh](qualify_common_runtime.sh), [retest_super_vl.sh](retest_super_vl.sh) |
| Live feature qualification | `storage_tests.py`, `serving_tests.py`, `request_tests.py`, `modelexpress_tests.py`, `kvcr_tests.py`, `nixl_tests.py`, `grove_tests.py`, `snapshot_*`, `shadow_*` |
| Source preparation and runtime inspection | `prepare_sources.py`, `prepare_snapshot*.py`, `prepare_shadow_sources.py`, `runtime*_probe.py`, `inspect_*.py` |
| Evidence, recovery and scoped cleanup | [archive_evidence.py](archive_evidence.py), [check_receipt_storage.py](check_receipt_storage.py), [recover_feature_logs.py](recover_feature_logs.py), [restore_feature_receipts.py](restore_feature_receipts.py), [cleanup_tests.py](cleanup_tests.py) |
| Development experiments and acceleration | [development/](development/README.md): MX RAM-cache tools and standalone disaggregation measurement/recovery tools |

The `*_tests.py` scripts here are live qualification programs: they can create
cluster resources, make inference requests or inject a declared fault. Run the
offline automated tests with:

```bash
uv run python -m tests
```

The root [README](../README.md#test-sequence) and [test plan](../TEST_PLAN.md)
describe the live feature sequence. Preparation and apply actions remain
separate for platform changes. Keep each run's pinned inputs, ownership checks,
receipts and cleanup boundaries when reusing these tools.

Some files are payloads copied into a container by another tool rather than
host entry points. Examples include `model_download.py`, `storage_probe.py`,
`runtime_capabilities.py`, `kvcr_prepare_runtime.py`, `snapshot_cuinterpose_app.py`
and the `*-entrypoint.sh` scripts. Their launching tool supplies the container
paths, environment and resource limits.

[testlib.py](testlib.py) owns the shared run, command-receipt and Kubernetes
operations. [gpu_claims.py](gpu_claims.py) handles GPU claim conversion. The
standalone qualification tools retain their sibling imports; packaged
development tools run from the repository root with `python -m scripts.development...`.
[source_paths.py](source_paths.py) provides the shared source inventory and
resolves historical receipt identities to their current files with hash checks
retained at each caller.

The Snapshot source-preparation variants capture different upstream contracts:
the initial Snapshot source, the installed Dynamo release, and newer
release/current sources. Their names identify those inputs; they are not
interchangeable retries.
