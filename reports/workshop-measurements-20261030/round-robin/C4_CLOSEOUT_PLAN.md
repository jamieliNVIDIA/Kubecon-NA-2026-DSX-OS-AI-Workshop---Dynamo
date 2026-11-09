# C4 scale-out evidence closeout

Requested November 4, 2026. Collect and independently recheck the completed C4
one-worker/two-worker observation. No benchmark replay, deployment, cleanup,
GPU allocation or lease mutation is part of this task.

- [x] Inspect local partial evidence and original pullback plan.
- [x] Verify the original controller is terminal and the C4 stage exited zero.
- [x] Collect both complete final arm inventories into fresh local staging.
- [x] Verify every inventory entry, including the original raw archives, and
  the recovery/stage receipts against their recorded hashes.
- [x] Recompute acceptance, matched-profile checks, workload mix, worker
  distribution and GPU samples from the collected exports.
- [x] Compare recomputed results with the accepted remote analysis, seal the
  local closeout, and update the report, tracker and outline.

The original `PULLBACK_PLAN.json` expected a successful six-arm queue, including
both RR/KV policy pairs. That queue later failed at the C1 KV discovery guard.
This narrower closeout uses the two C4 `integrity-final.json` inventories and
the successful `resume-c4-r2-stable-a1` stage. It preserves the original global
controller/continuation exit-one receipts; it does not claim routing success.

Source: `ubuntu@3.238.63.5`, physical workspace
`/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace`,
run `results/workshop-rr-20261103-resume02`. Original controller ID:
`5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411`.
The source tree is read-only. Existing local partials are retained; the new
verified tree is authoritative for this closeout and is not merged over them.

Select the exact final inventories and every regular file they name, both
original raw archives, C4 recovery/stage evidence, fixed spec/model/template and
analysis files, and the consumed analysis helper. Retain later controller failure
receipts for chronology. Exclude credentials, arbitrary root command receipts,
model weights, source trace corpus, mmap caches and unrelated runs.

The model, corpus, native context, AIPerf revision, replay settings, original
worker and benchmark identities remain unchanged. Keep the network-recovery
pause, changed realized turn mix, rate denominators, source branch mix and
fixed-load/N=1 limits explicit. A successful closeout is evidence collection
and reanalysis of the original observations, not a new measured repetition.
