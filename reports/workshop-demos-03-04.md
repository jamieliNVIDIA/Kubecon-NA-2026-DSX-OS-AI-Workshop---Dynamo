# Disaggregation and Snapshot presenter demos

Implementation status: both presenter runners passed fresh live qualification
on November 4 UTC. Their actual main-panel recordings are linked from
`reports/workshop-demo-recordings/STATUS.md`.

## DGD workflow

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
   - Complete: pinned Super VL, vLLM, TP2 H100, Kubernetes/EFA; four GPUs for P/D.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
   - Complete: use this repository's qualified `super-vl-tp2` P/D template and
     CuInterpose Snapshot restore path.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
   - Complete: runners render frozen per-run manifests from existing templates,
     retaining the qualified templates in `configs/dgd/` unchanged.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
   - Complete: offline checks and live client/server validation passed after
     restoring the API tunnel. The initial November 3 refusal is historical.
5. Hand off to `deploy_dynamo` or `kubectl apply`
   - Complete: prior controller cleanup was independently verified; new owned
     leases serialized the live demos. No competing fence was taken over.

## Scope

- Disaggregation: distinct prefill/decode workers, real SSE worker identity and
  positive NIXL KV-transfer deltas. Resource specialization motivates the demo;
  functionality alone makes no throughput or latency claim.
- Snapshot: pre-captured initialized native vLLM engine, same-node Pod
  replacement, fixed GPU pair, fresh inference. Prepared NVMe artifact or EFS.
  A separate [DGD qualification](workshop-snapshot-dgd.md) now passes automatic
  replacement and frontend coding chat on EFS with a pinned runtime adapter;
  the presenter runner remains native.
- Both: silent command submission gates, clear on advance, continuous startup,
  timing before inference, tmux, offline rehearsal, scoped explicit cleanup.

## Validation

- 28 presenter-demo tests pass, including offline flows, counter/SSE gates,
  source identity, fixed GPU pair, foreign-lease preservation, unowned-Pod
  cleanup refusal, and interrupted restore resumption without reapplying.
- 10 capture tests also pass, including actual PTY runs of all four rehearsals,
  secret redaction, attempt immutability and evidence surviving later cleanup.
- Real three-pane tmux rehearsals completed with zero exit status. P/D: ten
  silent key gates; Snapshot: twelve. Request submission was gated in both;
  Snapshot deletion was gated; clearing on advance was verified.
- UI receipts: `results/demo-03-disaggregated-tmux-v2-20261103/ui-validation.json`
  and `results/demo-04-snapshot-tmux-v2-20261103/ui-validation.json`.
- P/D transfer parser accepted the retained October 22 worker/metrics evidence;
  Snapshot timing parser reproduced its exact 37.814132624-second historical
  NVMe agent receipt. Neither was promoted to a new measurement.
- New Python and shell syntax and `git diff --check` pass.
- Fresh live P/D: correct coding output, distinct worker IDs, 103,645,184 bytes
  transferred with two completed samples and no new transfer/notification errors.
- Fresh live Snapshot: full artifact hashes verified, same-node fixed-UUID
  restores, distinct before/after Pod UIDs, Restored=True and fresh inference.
  The onstage replacement measured 37.3s agent restore / 41s Pod-to-Ready.
- Live fixes accept nanosecond log timestamps on Python 3.9, recognize vLLM's
  loading marker, explicitly select Snapshot GPU UUIDs, and allow primed Pods
  to survive preparation plus the three-hour workshop.

## Remaining workshop work

- Snapshot: wire the [qualified NVMe DGD lifecycle](workshop-snapshot-dgd-nvme.md)
  into the presenter UI. Automatic replacement, registration and
  coding chat now pass from pre-staged local storage; its experimental bridge/cache
  requirements must remain explicit. The current presenter artifact still
  serves native `/test` READY generation.
  Prefer the [qualified upstream-controller candidate](workshop-snapshot-upstream-controller.md)
  for this wiring; it retains only the custom identity/offline bridge.
- Add a matched aggregated/disaggregated workload comparison to illustrate
  resource specialization; this first P/D demo only establishes the handoff.
- Capture/staging and any matched cold-start baseline remain offstage work.
