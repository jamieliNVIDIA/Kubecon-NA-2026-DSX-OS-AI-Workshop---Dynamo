# Fresh writer instrumentation for reader descriptors

This is a new composition experiment after the independently verified a5
writer-only result. a5 and the v1 descriptor packet remain unchanged. Root is
the sole live executor; no Shadow reader or fault is enabled by this recipe.

## Current diagnostic status (after a4 cleanup)

The original `...-writer-a5` remains the qualified writer baseline. The separate
`...-descriptor-writer-a4` experiment failed at **21:33:46.064216971 UTC** in our
experimental descriptor exporter's strict `tensor_layout` dtype/gradient guard:
`ValueError: Unexpected inference parameter dtype/gradient contract.` Both TP
rank logs show this path after Humming lock rebinding and GMS preparation,
before descriptor publication. The exact offending parameter/field is still
unknown. This is an **experimental exporter contract gap**, separate from an
upstream GMS runtime defect. It is not a CUDA, reader or promotion result.
The full traceback is preserved in a4's
`main-follow-unlimited-20261105-a1.log`. No reader-ready rank manifests were
published. a3's unobserved original cause remains unknown.

a4's canonical scoped cleanup passed at **21:37:16 UTC**. The post-failure
health check found no new Xids or changed node conditions, with unchanged
boot/driver identity. All a4 frozen inputs and source snapshots remain intact.

The next **offline diagnostic** uses a separate v3 helper; it does not expand
the v2 dtype/gradient/layout allowlists. Before any exporter guard it inventories
all module-owned final parameter slots, including aliases, None, CPU and meta
entries. Every non-None row includes its exact owner/name, module/quant/kernel
classes, parameter class, dtype, requires_grad, shape/stride, device and typed
layout attributes. `Fraction` preserves numerator/denominator; `None` preserves
its type and value. The inventory never reads/copies tensor contents, calls
`data_ptr`/`item`, or creates CUDA/NCCL operations. It flushes JSONL to the actual
engine log and atomically saves one fresh rank file. A bounded CPU/filesystem
rendezvous requires both ranks to acknowledge the same fresh per-process token
pair before either reaches the strict exporter. Old same-candidate files
cannot satisfy a fresh partial restart. Inventory or acknowledgement files are
never overwritten. The strict error now names the exact rejected parameter,
dtype/gradient or layout-attribute types.

The inherited `kubectl --request-timeout=30s` had terminated a4's original log
followers after 30 seconds. Root preserved a4 by attaching separate unlimited
read-only streams without modifying its frozen sources. The fresh candidate's
canonical diagnostic follower now removes inherited timeout flags and sets
`--request-timeout=0` for streams; Pod-observer GETs remain bounded to 8 seconds.
Regression coverage checks the actual subprocess commands, retained previous
logs and collector restoration. The original qualified writer is unchanged.

The fresh v3 candidate is now frozen as
`results/overnight-shadow-super-vl-20261105-descriptor-writer-a5`, namespace
`dynamo-ft-r610-88b4b246-demo`. Independent metadata-inventory review passed 14
tests; all 141 focused Shadow tests passed. Offline load revalidated its
frozen inputs and 131 source contracts. No live action has run for that fresh
candidate at this checkpoint. Its exact root sequence and frozen-source
identifiers are in [the v3 runbook](SHADOW-DESCRIPTOR-V3-RUNBOOK.md); the
separate [inventory review](SHADOW-PARAMETER-INVENTORY-REVIEW.md) records four
resolved diagnostic-harness issues. The following a4 preparation details and
command sequence are historical; a4 is closed and must not be resumed or
overwritten.

The DGD skill's required task list is recorded before writing the YAML:

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete: pinned Super VL revision/image, vLLM, TP2 on the assigned cp-0124 GPU4/5 pair, Kubernetes/operator GMS.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete: reuse the actually qualified a5 writer DGD and its scoped DeviceClass/overlay, themselves derived from the qualified intro and upstream operator examples.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete: `configs/dgd/workshop-shadow-descriptor-writer/overnight-shadow-super-vl-20261105-descriptor-writer-a4/deployment.yaml`, with a fresh namespace and dedicated descriptor `emptyDir`.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — a4 actual-image CPU/source/cache and client/server admission preparation passed at 21:21:58 UTC. Its 25-file top-level wrapper inspection passed without CUDA initialization; nested MoERunner delegation review needs the separate runner-source read described below.
5. Hand off to `deploy_dynamo` or `kubectl apply` — a4 model GPU startup is gated on wrapper review, fresh exact-pair CUDA/health clearance and root's explicit bounded execution. a3 failed and is cleaned; it is not a current deployment candidate.

The v2 helper explicitly handles the actual source's ModelOpt KV-cache scale
finalization for scalar FP8 FlashInfer attention without sinks. It preserves
the writer's four final private scale buffers, host float values and two host
tensor copies, removes consumed checkpoint placeholders from the reader meta
skeleton, and verifies GMS buffer metadata plus imported values. The installed
FlashInfer no-sink post-load hook returns immediately; v2 does not call a
backend callback or weight postprocessing on the reader.

Unsupported attention variants and model-level post-load hooks remain explicit
reader gates. The instrumented writer can capture an incomplete descriptor
manifest while reporting `reader_ready=false`; that does not qualify a reader.

## Frozen candidate and evidence

- Run: `results/overnight-shadow-super-vl-20261105-descriptor-writer-a4`.
- Namespace: `dynamo-ft-r610-218a80e1-demo`.
- Graph: `ft-shadow-writer`.
- Overlay SHA-256:
  `9cc88eaad0348bbc7319978694645e1e00b2901a188a04f039deed2f80773d7c`.
- v2 helper SHA-256:
  `5aeee2eedd2a07be5be1fcc8df38920f75355ed8fb0c681b3fed1b177f0df970`.
- 131 actual installed-source contracts, including the original unchanged GMS
  materializer, Humming/FP8/attention runtime and model-loader sources.
- 26 v2 helper tests, ten composition/provenance tests and three log-preservation tests pass. The frozen controller
  reload checks all candidate inputs, critical implementation sources,
  installed-source copies, the pinned model lock and executable config YAML.
- The actual-image v1 CPU probe passed all three real Humming dataclass
  roundtrips and a real FP8 meta tensor layout with `cuda_initialized=false`.
  Its exact result and 24 additional attention/model/backend source files were
  independently verified and copied into the reader evidence packet. v2's
  corrected attention-specific actual-image CPU probe also passed with the
  exact unchanged helper SHA above, real meta constructors, the actual no-sink
  FlashInfer source and `cuda_initialized=false`; its result is independently
  copied as `descriptor-cpu-v2-a2-result.json` in that packet.

Candidate a1 was prepared offline and never GPU-started. Review found that its
manifest capture checked only Pod UID and hash length. a2 revalidates the exact
serving container generations, restart/image checks, physical GPU pair and
ResourceClaim UID/allocation, plus current committed GMS state, before **and**
after the rank-file read. Captured manifest hashes must match that live state.
Separate observation folders preserve the original serving claim proof.
Negative tests cover main/GMS restart before reading, main restart during
reading, claim replacement, GMS layout change and stale manifest hashes.
Failed capture records a failed receipt; it cannot retain a current passed
descriptor claim. The original a1 spec and controller bytes remain preserved
under a1's `source-snapshot/`; a2 contains the corrected capture guard.

a2 passed cluster CPU/source/cache and admission preparation, then the exact-pair
probe encountered a local sandbox network denial before a GPU Pod was applied.
Its one-attempt probe intent remains preserved; it was not cleared or retried.
a3 was a fresh freeze of the same reviewed serving/controller sources and used
a new namespace. Its probe/model startup subsequently ran; its outcome is
recorded below. The earlier a2 failure is not a CUDA or runtime failure.

a3 exited the writer restart gate at **21:11:50 UTC**. The last retained
nonempty command output ends near weight shard 86/88 at 21:11:37; the canonical
latest main log was overwritten by an empty restarted-container read. The
exact original exception remains **unknown**. No writer descriptor manifest,
reader-ready basis or reader/promotion result was produced. Read-only health
after the failure found no new Xids or condition changes, with the same node
boot and driver identity. Canonical scoped a3 cleanup passed at 21:16:08 UTC.
Its failed evidence and source snapshots remain unchanged.

**a4 is the current diagnostic candidate.** It keeps exactly the same runtime
helper, pinned serving profile and overlay bytes. No hypothetical runtime fix
was applied. It adds previous-generation log capture before destructive stop
and independent continuous `kubectl logs --follow` streams per Pod/container
generation. The observer uses its own read-only subprocesses and files, avoiding
concurrent mutations of the verifier's Run state. The original qualified
`workshop_shadow_writer.py` remains unchanged; a scoped collector override is
installed only during the instrumented verifier and restored in `finally`.

a4 also requires a bounded CPU inspection of the actual pinned image's fused
MoE wrapper sources before model deployment. It records `vllm.__file__`, version,
source hashes and `quant_method` property definitions. This can establish
whether wrapper/delegate aliases need explicit exporter ownership handling;
that is a source-audit hypothesis, not the established cause of a3's failure.

The initial actual-image wrapper read preserved 25 top-level files and found no
top-level `quant_method` property definitions. This does not rule out delegation:
the captured `layer.py` imports and returns `runner/moe_runner.py`, outside that
glob. The separate read-only helper
`scripts/workshop_shadow_runner_inspect.py:inspect_runner(run)` captures that
actual nested package into `runtime-runner-sources/` without modifying a4's
frozen runtime or controller. That read has now passed and preserved four
matching-image runner files. Independent hash/AST inspection found only the
private `_quant_method` forwarding property (`moe_runner.py:356`), with no public
`quant_method` forwarding/assignment or custom `__getattr__`/`__getattribute__`.
The factory's real quantization owner remains `RoutedExperts`. The wrapper
alias/count hypothesis is ruled out for this pinned source path; it did not
justify a runtime change. a3's original cause remains unknown. Unchanged a4 can
proceed as the bounded diagnostic experiment with improved log retention.

The additional ModelOpt source contract was verified through its original
source-read receipt and the source Pod's exact matching image digest. The
actual a5 engine log already resolves the model's default cache dtype to
`fp8_e4m3`; no serving flag or cache dtype was changed for this prototype.

The current `workshop_shadow_descriptors.py` v1 file and its immutable packet
remain unchanged. v2 lives in `workshop_shadow_descriptors_v2.py`; only its
frozen bytes are mounted under the candidate's installed
`workshop_descriptors.py` path.

The source-reviewed MoE reconstruction also deliberately skips the expert
post-load hook: none of the three installed Humming expert classes overrides
it, and their pinned `FusedMoEExperts` implementation is a no-op (`pass`).
The Humming-specific builder matches the installed NVFP4 oracle's constructor
path for this backend. These are source contracts, not GPU reader results.

## Root-executor sequence

The current actual-image v2 CPU payload is
`scripts/workshop_shadow_descriptor_cpu_v2_a2.py:PROGRAM`. Pass the frozen
candidate's `workshop_descriptors.py` bytes as `DESCRIPTOR_SOURCE_B64` and its
SHA-256 as `DESCRIPTOR_SOURCE_SHA256` to the existing bounded `cpu_probe`.
Besides real Humming roundtrips, it compiles the actual scale-buffer helper and
`KVCacheScaleParameter` source with real PyTorch/meta tensors, and verifies that
the installed FlashInfer hook returns without mutation when sinks are absent.

The first v2 CPU attempt failed before any GPU use: the probe constructed a
bare module with `set_default_quant_scales` and incorrectly expected it to own
`_o_scale_float`. The actual source initializes that field separately in
`_init_kv_cache_quant`. The a2 probe compiles that exact installed-source
assignment separately; the runtime helper already operates on actual Attention
instances and did not require a change. The failed a1 program/source/logs remain
preserved in the a5 evidence directory. No frozen serving source was edited.

After that source/CPU check:

Current a4 has completed preparation and both source inspections. Its remaining
live sequence resumes at `probe`; the first two commands below document the
fresh-candidate setup already completed for a4.

```bash
SHADOW_DESCRIPTOR_RUN=results/overnight-shadow-super-vl-20261105-descriptor-writer-a4
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py prepare --run "$SHADOW_DESCRIPTOR_RUN"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py inspect-wrappers --run "$SHADOW_DESCRIPTOR_RUN"
```

Review the actual wrapper inspection before proceeding. Deployment refuses a
missing inspection receipt. Once there is no known source-level blocker:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py probe --run "$SHADOW_DESCRIPTOR_RUN"
```

Capture fresh exact-node health **after** the CUDA probe, then use its actual
pathname as `SHADOW_DESCRIPTOR_HEALTH_BEFORE`:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py deploy \
  --run "$SHADOW_DESCRIPTOR_RUN" --health-before "$SHADOW_DESCRIPTOR_HEALTH_BEFORE"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py verify \
  --run "$SHADOW_DESCRIPTOR_RUN" --timeout 1500
```

`verify` retains the existing three-response, worker/container/GPU identity,
workspace pointer and unchanged-GMS checks. It additionally copies both actual
rank manifests out of the Pod into `rank-manifests/` and records their hashes,
module counts, committed layout hashes and any unsupported reader state in
`descriptor-capture.json`. Capture occurs before cleanup destroys the shared
`emptyDir`; cleanup refuses to delete a passing writer until this evidence is
saved.

Capture fresh final health after coding, then use the actual pathname:

```bash
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py finalize \
  --run "$SHADOW_DESCRIPTOR_RUN" --health-after "$SHADOW_DESCRIPTOR_HEALTH_AFTER"
.local/venv/bin/python scripts/workshop_shadow_descriptor_writer.py cleanup --run "$SHADOW_DESCRIPTOR_RUN"
```

This proves only the instrumented writer composition. Review the real manifests
and require all reader gates before freezing the subsequent active/standby
candidate. No intentional fault belongs in this writer experiment.
