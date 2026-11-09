# Shadow Engine: restore serving capacity

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

New runs show Shadow promotion on **Qwen/Qwen3-0.6B at TP1, on one H100**. This is
the model of the October 14 and 22 controls, which both passed live promotion
(2.95 s and 2.62 s to the first verified response, one failed request each). The
workshop model, Super VL TP2, is still blocked by GMS startup failures; see the
[overnight qualification notes](../../reports/overnight-2026-11-04/SHADOW.md).
The presenter itself has not yet run Qwen live: qualify it before the workshop.

```bash
uv run python -m demos shadow --preview
uv run python -m demos shadow --rehearsal
```

The four screens explain shared weights and active/standby roles, inspect the
prepared engines, fail one verified active EngineCore, then inspect promotion
and replenishment. Commands wait silently for the presenter's keypress before
execution. Advancing clears the main screen. The full executable DGD remains
under the run directory; the projected excerpt is `shadow-settings.yaml`.
The excerpt shows the model and reads the actual GMS DeviceClass binding,
TP/load-format/sleep-mode arguments and frontend migration setting from that DGD.
Preparation and runtime adaptation details remain offstage.

Prepare before the workshop using a fresh run directory:

```bash
uv run python -m demos shadow prepare
uv run python -m demos shadow prime --run <run>
uv run python -m demos shadow --run <run>
uv run python -m demos shadow cleanup --run <run>
```

## Qwen3-0.6B (default)

- **Placement.** GMS and both engines share cp-0942 gpu-1
  (`GPU-7b0cff01-e024-1e7f-5c2e-53c85b3835e4`), pinned in a test-owned
  DeviceClass. `QWEN_NODE` and `QWEN_UUIDS` in [demo.py](demo.py) hold the
  assignment, so a new placement is a one-line edit before a fresh run.
  Coordinate the GPU before live preparation, and never edit a frozen run.
- **Model and configuration.** [The frozen lock](../../configs/qwen3-0.6b-shadow-lock.json)
  is copied into each run. The worker's image, arguments, environment and
  resources match the [qualified control manifest](../../configs/dgd/super-vl-r610-d906a5f1/shadow-control/qwen-shadow-control.yaml).
  The graph around it is the presenter's own: the intro template with
  `gpuMemoryService.deviceClassName`, failover and frontend migration disabled.
- **`prepare`.** Creates the namespace, cache volume and pull secret. Rechecks the
  cached revision (one 1,503,300,328-byte weight file; no download). Runs the
  infrastructure preflight, which needs cp-0942 eligible, and inspects the
  installed GMS sources. It then applies only the source-hashed `patches.py`
  overlay (the vLLM 0.31 `request_memory` signature) and admits the manifest.
- **`prime`.** Starts the graph and waits for one active and one parked standby
  engine. The Pods carry no deadline, so a primed pair stays up until its demo.
- **Recovery request.** The verifier sends the workshop coding request
  (`add(a, b)`). If Qwen's answer fails that check during qualification, set
  `QWEN_RECOVERY_REQUEST = 'ready'` in [demo.py](demo.py). That switches to the
  controls' `Reply with exactly READY.` request; existing runs pick it up
  without a re-prime.
- **Helm.** The preflight calls Homebrew's Helm path. On a host without it,
  such as the Linux jump host, the presenter uses the Helm on `PATH`.

## Super VL TP2 (opt-in)

Set `WORKSHOP_SHADOW_MODEL=super-vl` when creating a run. The choice is recorded
in the run; later commands refuse a different setting. GMS and both engines
share cp-0124 GPU4/GPU5. `prepare` revalidates the pinned checkpoint, reads the
installed GMS sources and applies two recorded test-local adaptations. They
keep the vLLM 0.31 memory-budget signature bridge, and they let only a
meta-device one-element scale materialize as the writer's committed scalar
shape. That addresses a recorded Super VL `lm_head.input_scale` mismatch; it
does not fix the later reader layout and writer faults in the qualification
notes.

## What the verifier checks

The fault verifier refuses ambiguous processes, changed Pod/container identity,
unparked standby, mismatched GPUs, missing failover lock, or a previous fault
attempt. It requires actual inference on a new worker, exactly one promotion,
unchanged Pod/GMS/standby container identities, unchanged committed weight
layout, reclaimed failed-engine KV backing and a replenished standby.

Timing is fault-command-to-first-verified-response, including request polling
and `kubectl exec`. Requests are fresh and frontend migration is disabled. This
does not preserve in-flight generation, GPU-only KV state, failed GPUs/nodes,
or establish latency SLOs under the coding-agent workload.
