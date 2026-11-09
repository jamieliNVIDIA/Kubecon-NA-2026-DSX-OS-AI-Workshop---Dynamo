# Compiled text-only startup baseline

This versioned profile applies the qualified workshop startup settings to both
the storage baseline and ModelExpress deployments:

- Super VL at the revision and runtime image in `configs/super-vl-tp2-lock.json`.
- Text-only serving with `--language-model-only` on source and receivers.
- TP2 H100, native 1,048,576-token context, four sequences, 8,192 batched tokens,
  GPU-memory fraction 0.85, compiled execution.
- Worker canary wait 1 second, startup probe period 2 seconds / failure threshold
  1,800, readiness period 2 seconds. Other probe fields remain unchanged.

`target-storage.yaml` uses the native loader and has no MX environment settings.
`target-weights.yaml` enables peer weights with artifact transfer disabled.
`target-artifacts.yaml` also enables compatible compiler-cache transfer.
Their other receiver settings are identical. `source.yaml` publishes compatible
weights/artifacts through the services in `coordinator.yaml`.

The files use JSON syntax, which is valid YAML and preserves string-valued
environment settings. They are exact, namespace-bound inputs for the fresh
comparison; use the controller below to prepare storage, credentials and EFA
plumbing before deployment. Do not apply them into an unrelated namespace.

The faster health policy was qualified for startup and correct inference. Its
more frequent probes/canaries and changed failure-detection timing are not a
production SLO qualification. The eager presenter demos retain their own profile.

The completed matched trial measured **492.79 s** for native EFS loading,
**280.10 s** for MX peer weights and **173.61 s** for peer weights plus artifacts.
Both TP ranks reused the published compiled graphs. See the
[results and limitations](../../../reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_RESULTS.md).

Plan and commands:
[matched baseline plan](../../../reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_PLAN.md).
`current.json` selects the current measurement. Its run directory contains the
frozen manifests with a fresh namespace and compiler-artifact identity;
`profile.json` retains the original template-generation provenance. The initial
attempt served correctly but stopped at an overly strict validator that compared
raw manifests with API-defaulted probes. Its evidence is preserved separately.
The corrected validator checks the previously qualified effective health policy,
including the operator-provided liveness probe, and Downward API defaults.
