# Demo 3: disaggregated serving

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

Start with the different resource demands of prefill and decode. Give each a
worker pool, then follow a coding request through prefill, KV handoff, and decode.
This presentation demonstrates the mechanism. The recorded startup belongs to
this compiled P/D profile; it is not a matched comparison with the earlier
aggregated eager server.

```bash
uv run python -m demos disaggregated --rehearsal
```

Enter or Space submits the displayed command or advances to the next screen;
`q` stops. The main screen clears on advance. Tmux opens the walkthrough on the
left, resources and per-worker startup phases upper right, and prefill/decode
logs lower right. Add `--plain` for one terminal. No control cue is printed.

```bash
uv run python -m demos disaggregated --preview
uv run python -m demos disaggregated --rehearsal --plain --auto
```

Rehearsal makes no cluster calls and reports no measured timings or KV bytes.
Preview writes manifests and shows the focused settings without deploying.

## Live flow

The cluster/runtime, cached checkpoint, credentials, operator, GPU DRA and EFA
setup are the same as the feature tests. This needs **four H100s**: prefill TP2 on
cp-0124, decode TP2 on cp-0198, plus a CPU HTTP frontend. Clean up any previous
demo first. The measurement lease must be released by its owning controller
after verified cleanup; these runners never take over another run's lease.

```bash
# Offstage: prepare the namespace, checkpoint checks, EFA and claim templates.
uv run python -m demos disaggregated prepare --auto

# Recommended before presenting: start and verify both pools (several minutes).
uv run python -m demos disaggregated prime --auto

# Onstage: same run, with presenter controls.
uv run python -m demos disaggregated

# When finished:
uv run python -m demos disaggregated cleanup --auto
```

`prepare` creates/checks prerequisites. `prime` additionally starts and verifies
the workers, retaining their original startup timestamps and per-worker phase
records. The live walkthrough requires successful preparation and never runs
checkpoint/credential preparation onstage. When primed, it checks the same Ready
worker identities and explicitly presents retained startup timing. To show an
actual fresh startup onstage, omit `prime` and allow the full loading time.

The walkthrough has four screens:

1. Focused roles and NixlConnector configuration, derived from the executable
   frontend arguments, worker placement, tensor parallelism and GPU claims.
   Full `deployment.yaml` and effective `deployment.json` remain available.
2. Inspect the primed workers' recorded startup, or submit the DGD and follow
   both pools continuously until Ready. The summary appears before the request.
   The compiled engine phases can overlap.
3. Forward the frontend, discover the model, and submit a coding request. The
   stream requests worker identity and timing metadata.
4. Inspect distinct prefill/decode worker IDs, positive completed NIXL byte and
   transfer-count deltas on decode, and zero new transfer/notification failures.

The renderer preserves the qualified **8k, compiled** P/D profile, including the
hybrid model's state layout, block size, and cache settings. This differs from
demo 1's simpler eager configuration. Do not compare their startup times as a
controlled experiment. Both pools have model weights; NIXL transfers request
state, not the model weights shown in the ModelExpress demo.

Both pools add `--language-model-only` for the agreed coding-agent workload.
The new text-only candidate is qualified by its fresh live attempt, separately
from the older multimodal feature-test result.

`timing.json`, `ready-pods.json`, per-role logs, `response.sse`, `response.json`,
metric snapshots and `transfer-proof.json` retain the evidence. Pod replacement,
restart, missing counters or failed transfers stop the demonstration. The
service stays up until explicit cleanup; port-forward ends with the walkthrough.

## Validation status

Offline flow, real tmux/key gates, safety checks, and parsers against retained
feature-test evidence are validated. The underlying cross-node Super VL P/D
path passed the [October 22 feature recheck](../../reports/2026-10-22-r610-feature-retest.md).
The text-only presenter runner passed a fresh live qualification on November 4
UTC: both pools became Ready, the coding request identified distinct workers,
and decode recorded 103,645,184 transferred bytes / two completed samples with
zero new transfer or notification failures. See the
[actual main-panel recording](../transcripts/live/03-disaggregated/20261104-a1/main.txt).
Starting both workers from EFS took about 12.7 minutes through readiness in this
attempt; use `prime --auto` offstage when presentation time is limited. The
presentation changes above have offline coverage and do not replace this
retained live qualification.
