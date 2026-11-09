# Strict final-parameter diagnostic: root-executor runbook

**Closed historical candidate. Do not re-execute descriptor-writer-a5 with a
newer controller.** All a5 frozen inputs, intents and source snapshots remain
preserved. Its v3 diagnostic answered the parameter-contract question but did
not qualify an instrumented writer or reader.

This fresh diagnostic follows closed descriptor-writer-a4. The original
`...-writer-a5` remains the qualified writer baseline. a4 exposed an
experimental exporter dtype/gradient contract gap; the exact field is unknown.
v3 adds diagnostics and clearer strict errors, with **no** dtype, gradient,
shape, layout, cache-dtype or serving-argument allowance changes. No reader or
intentional fault is enabled. Root is the only live executor.

## DGD task list before writing the new YAML

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete: unchanged pinned Super VL revision/image, vLLM eager/text-only TP2, fixed 2 GiB KV cache, Kubernetes GMS on cp-0124 GPU4/5.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete: qualified original writer-a5 executable DGD and scoped DeviceClass/overlay, already derived from the qualified introduction and upstream operator examples.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete: independent inventory review passed 14 tests and freeze wrote `configs/dgd/workshop-shadow-descriptor-writer/overnight-shadow-super-vl-20261105-descriptor-writer-a5/deployment.yaml`.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — complete: root's bounded CPU/cache/source/client/server admission preparation passed. No GPU deployment was part of preparation.
5. Hand off to `deploy_dynamo` or `kubectl apply` — complete: explicit descriptor CPU probe, wrapper-source check, exact-pair arithmetic and fresh health passed before startup. The strict exporter failed as detailed below; scoped cleanup passed. This attempt is closed.

## What is frozen

The fresh frozen candidate is
`results/overnight-shadow-super-vl-20261105-descriptor-writer-a5`, namespace
`dynamo-ft-r610-88b4b246-demo`, graph `ft-shadow-writer`. Overlay SHA256 is
`1601d0f2ec7cb6895f69e220b97abbd34b7eb0a317e2de52148f6f08c9c8ae66`;
v3 helper SHA256 is
`e9ddc71168965ac9e7b098c9ef9b5354879ad5cedff0ed46088895a5a26ea974`;
inventory helper SHA256 is
`2d6ef1664d7746edd922c9281dcb6d8a30fa2f91d7d0abfeeaf5114e950623ef`.
Offline load revalidated every frozen source/input/contract after freeze.
All 141 focused Shadow tests passed; compilation passed. These are local
checks only. At the offline-freeze checkpoint no live action had run.

Root subsequently completed preparation/admission, the exact frozen
actual-image descriptor/inventory CPU probe (real Torch CPU/meta, two-rank
nonce/ACK rendezvous, CUDA uninitialized), wrapper-source inspection and
reserved-pair CUDA arithmetic. All passed. Root captured fresh health and
started the model. Both rank inventories completed and acknowledged the same
fresh generation pair at 22:07:06 UTC. At **22:07:07 UTC** both ranks reached
the strict exporter guard and rejected
`language_model.model.layers.1.mixer.experts.routed_experts.e_score_correction_bias`:
`torch.float32`, `requires_grad=True`. Every one of the forty such correction
biases per rank has that same observed flag, shape `[512]`, stride `[1]`, plain
`torch.nn.Parameter` class and empty layout attrs. The source creates them with
the default `requires_grad=True` constructor and shares them between gate and
RoutedExperts. This is an incorrect assumption in our experimental exporter,
not an upstream GMS runtime defect. a3's unobserved cause remains unknown.

The complete per-rank inventory contains 2,078 owned slots, 1,621 CUDA
parameters, 457 None slots and 360 parameter aliases. Both ranks use only the
already-approved bf16/fp32/e4m3/int32 dtypes. No shape/stride/empty-extent or
typed None/Fraction layout issue appears in any row. The only exporter-candidate
issues are those forty correction flags; all forty owners also appear in the
actual Humming MoE lock-rebinding proof. Other 289 grad-true slots per rank
belong to owners not selected by the exporter and are kept separate in the
analysis. All rows and their exact names remain available in the packet.

Independent, immutable actual-log reconstruction:
`results/overnight-shadow-super-vl-20261105-descriptor-inventory-a1/analysis.json`
with exact source-log byte snapshots and hashes. It verifies both rank
summaries, no JSONL/metadata inspection errors, and the shared generation pair.
The offline parser is `scripts/workshop_shadow_inventory_analysis.py`; its six
focused tests cover duplicate/partial/conflicting/foreign/truncated records and
the separation of broad metadata from exporter candidates.

Root's separate actual-image CPU source packet is
`results/workshop-shadow-inference-sources-20261105-a1/manifest.json`.
It records `@torch.inference_mode()` on actual GPU-model-runner `execute_model`
and `_dummy_run`, and GPU-worker `execute_model`; no CUDA context or model was
created by that source read. Frozen GMS `module.py:211` explicitly preserves the
meta Parameter's `requires_grad` bit. These source contracts support a narrow
role-bound preservation proposal, not a GPU reader result.

Fresh post-failure health and normalized audit passed, with no new Xids or
changed node conditions and unchanged boot/driver identity. Canonical scoped
cleanup passed at **22:09:20 UTC**; the a5 critical-source hold is released.
No rank descriptor manifest or reader-ready basis was published. Exact CPU,
health and cleanup receipts remain in the candidate directory, including
`post-failure-health-audit-20261105-a1.json`.

The new controller freezes the entire qualified original writer's critical
source set, unchanged original loader/patch/Humming inputs, 131 installed-image
source contracts, model/image/config identity, fresh namespace/DeviceClass,
executable DGD, immutable ConfigMap and these new/updated critical sources:

- `workshop_shadow_descriptor_writer.py` (fresh diagnostic controller).
- `workshop_shadow_descriptors_v3.py` (strict v3 helper; v2 unchanged).
- `workshop_shadow_parameter_inventory.py` (metadata-only inventory and bounded filesystem rendezvous).
- `workshop_shadow_descriptor_cpu_v3.py`, its corrected v2-a2 payload dependency, original v2 payload and original CPU payload.
- `workshop_shadow_diagnostics.py` (unlimited log streams; bounded observer reads; previous-generation retention).

The installed ConfigMap files are `model_loader.py`, `workshop_humming.py`,
`patches.py`, `workshop_descriptors.py` (v3 bytes), and
`workshop_parameter_inventory.py`. The inventory shares the existing dedicated
64 MiB descriptor `emptyDir`. All serving arguments, placement and stock GMS
materializer remain unchanged. No post-load transform runs on reader weights.

The new `inspect-descriptors` action is an explicit separate CPU probe, **not**
implicitly part of `prepare`. It reads the frozen candidate's descriptor and
inventory bytes, passes their Base64 and SHA256 to the frozen CPU payload, runs
the existing 180-second actual-image CPU Pod with `NVIDIA_VISIBLE_DEVICES=void`,
and records `descriptor-cpu-intent.json` plus `descriptor-cpu-result.json`.
`probe` and `deploy` require its passed source/program hash and no-CUDA receipt.
A failed CPU attempt is preserved; its intent cannot be cleared/retried.

The actual-image CPU payload retains the real Humming codec/Attention/meta
constructors/no-sink FlashInfer checks, adds actual PyTorch CPU/meta inventory
checks, tests the two-rank nonce/ACK rendezvous using CPU threads, and verifies
the strict grad/Fraction/None/unallowlisted-E8M0 rejections remain unchanged.
It checks `torch.cuda.is_initialized()` before and after. This is not a GPU
parameter inventory or a reader result.

## Historical root sequence (completed; do not resume a5)

Set this only to the **new frozen candidate**, never a1-a4:

```bash
SHADOW_DESCRIPTOR_RUN=results/overnight-shadow-super-vl-20261105-descriptor-writer-a5
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py prepare --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py inspect-descriptors --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py inspect-wrappers --run "$SHADOW_DESCRIPTOR_RUN"
```

Review the actual CPU receipts and wrapper source before any GPU action:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py probe --run "$SHADOW_DESCRIPTOR_RUN"
```

Capture fresh cp-0124 health **after** that exact-pair CUDA smoke using the
coordinator's existing read-only health workflow. Set
`SHADOW_DESCRIPTOR_HEALTH_BEFORE` to the actual saved health JSON, then:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py deploy --run "$SHADOW_DESCRIPTOR_RUN" --health-before "$SHADOW_DESCRIPTOR_HEALTH_BEFORE"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py verify --run "$SHADOW_DESCRIPTOR_RUN" --timeout 1500
```

The strict exporter is expected to expose the same unsupported contract with
its exact name; that is a useful diagnostic outcome, not a passed writer.
`verify` starts independent unlimited log followers, preserves previous logs
before its scoped stop on failure, and restores the collector override in
`finally`. It never clears startup/probe/CPU intents. Each TP rank flushes all
parameter JSONL with prefix `WORKSHOP_PARAMETER_INVENTORY_V1` before the strict
exporter runs. The live rank files are
`parameter-inventory-rank-{0,1}.json`; per-rank acknowledgements bind both fresh
process-generation nonces. Never substitute an a5 original-writer manifest or
infer a3's cause from this new result.

After failure, save fresh health and run canonical scoped cleanup. If the
instrumented writer unexpectedly passes coding and real rank-manifest capture,
save health and use the normal qualification path first:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py finalize --run "$SHADOW_DESCRIPTOR_RUN" --health-after "$SHADOW_DESCRIPTOR_HEALTH_AFTER"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py cleanup --run "$SHADOW_DESCRIPTOR_RUN"
```

The full-reader controller remains unfrozen and bound to the old v2 interface.
Only after a genuinely supported writer passes may that controller's
version/profile/mounts be rebound and reviewed. This diagnostic does not qualify
Shadow, process promotion, capacity recovery or request continuity.
