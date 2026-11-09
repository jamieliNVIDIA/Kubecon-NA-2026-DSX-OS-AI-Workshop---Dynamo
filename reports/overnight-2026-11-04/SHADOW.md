# Shadow Engine overnight work

Started November 4, 2026, Pacific. **Presenter and rehearsal complete; morning
recovery of cluster access exposed two real Super VL/GMS startup failures. No
intentional fault or promotion qualification has occurred.**

## Decisions and scope

- Keep Super VL TP2; the earlier Qwen control is not a substitute.
- Build a separate presenter candidate (`demos/08-shadow-engine`) so existing
  qualified demos and prior Shadow evidence remain unchanged.
- Use text-only eager execution and the prior 0.65 engine-memory fraction.
  Limit warm-up batching to 1,024 tokens and enable synchronous CUDA diagnostics
  for the first attempt. This is a new qualification profile, not a timing
  comparison to another demo or a production performance configuration.
- Restore capacity through active/standby promotion, with fresh requests and
  frontend migration disabled. Under-load SLOs, in-flight continuation and KV
  preservation are independent experiments.
- Use the coordinator-assigned cp-0124 GPU4/GPU5 pair, explicit UUID selectors,
  and an owned DeviceClass. Snapshot concurrently uses disjoint GPUs. No global
  idle checks, driver resets, operator upgrades or unrelated cleanup.

## Prior blocker and candidate adaptations

October 22's preferred-model attempt failed before fault injection. The GMS
reader rejected `language_model.lm_head.input_scale`: meta parameter `(1,)`,
committed tensor `()`, both float32. The writer also raised illegal memory
access during FlashInfer warm-up; the saved GPU audit records Xid 31. The
asynchronous traceback alone does not prove the offending write's origin.

Current upstream `lib/gpu_memory_service/client/torch/module.py` still has the
strict shape check (blob `6d2c7455c10612a55f77637bd1dfb2045340a970`, read during
this work). [Dynamo #11201](https://github.com/ai-dynamo/dynamo/pull/11201)
already addresses private rebinding of non-parameter tensors; do not propose it
again as a new finding. A separate meta/postprocessed-parameter compatibility
gap may remain.

Related proposed fixes were found after a1 began, and their full metadata/diffs
are frozen as `upstream-pr-12168.json` and `upstream-pr-9854.json` in that run:

- [#12168](https://github.com/ai-dynamo/dynamo/pull/12168), **open draft**, head
  `2b2d1d9eae467b21de5b5a624fcf8542d0ea626f`: adopts committed quant scale
  shapes and rebuilds NVFP4 read-mode MoE kernels, with backend guards. The
  reported validation is Kimi/vLLM 0.25.1/TP8; Humming compatibility is not
  established. Our actual image selects Humming for Super VL, so this is not
  a drop-in qualified fix.
- [#9854](https://github.com/ai-dynamo/dynamo/pull/9854), **closed, unmerged
  draft**, head `a4bf9d538b76d43ebd22cf7b6be48c2da4a8fc56`: structural handling
  of auxiliary mutable tensors, aliases, final parameter manifests and meta
  model reconstruction. Older text in #12168 calls #9854 merged; current PR
  metadata contradicts that description. Treat it as proposed source work.

The candidate uses only two explicit module overlays in its own containers:

1. Existing source-hashed `request_memory` signature compatibility for the
   pinned image's vLLM 0.31 third argument.
2. A narrow meta singleton-scale adaptation: accept the writer's scalar shape
   only for an unmaterialized one-element scale of identical dtype. Non-meta,
   non-scale, non-singleton and dtype mismatches still fail.

This second change is a candidate workaround, not an upstream-quality general
solution or proof that the writer-side fault is fixed. The run records the
actual installed source and transformed source hashes before deployment.

## Validation and evidence

The DGD workflow used the existing qualified intro template and the pinned
operator failover example; it did not construct a serving topology from scratch.

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s) — complete.
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch) — complete using the repository's qualified DGD and upstream failover example.
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`) — complete as an immutable per-run `deployment.yaml`, preserving prior qualified manifests.
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars) — client and server admission passed.
5. Hand off to `deploy_dynamo` or `kubectl apply` — applied; exact shared GPU4/GPU5 allocation observed, startup still unqualified.

- Preview and all four offline presenter screens pass; rehearsal explicitly
  marks simulated outcomes and has no numeric recovery timing.
- A fresh PTY capture through the shared utility passed as `rehearsal_passed`:
  `results/overnight-shadow-capture-rehearsal-b1-transcript/rehearsal-main.txt`.
- Eight focused tests pass: UUID allocation and fault-boundary refusal,
  foreign reservation refusal, missing-proof refusal, verifier callback
  restoration and the narrow source transformation. Python/shell syntax pass.
- Live run: `results/overnight-shadow-super-vl-20261104-a1`.
- Console: `results/overnight-shadow-super-vl-20261104-a1-console.log`.
- Terminal live outcome will be appended below; until then no live success is
  claimed. Original October 22 evidence remains intact.
- The startup implementation and seven dependencies were frozen separately in
  `execution-sources/`. Subsequent changes improve the rehearsal label, use
  the workshop coding prompt for verification and harden partial cleanup;
  those did not change a1's already-running serving profile. Freeze a second
  source set before the later verification phase.
- At 10:48 p.m. Pacific, the coordinator captured node/GPU/kernel baseline
  evidence under `results/overnight-2026-11-04-coordinator/shadow-gpu-health-before/`.
  Only historical October 22 Xid entries were present. At 10:50 p.m., kubectl
  began reporting TLS handshake timeouts; the waiter retained the workload,
  and the coordinator was notified before any tunnel or workload mutation.

## Resume after transport recovery

### November 5 morning diagnosis supersedes the transport-only observation

Read-only inventory after VPN recovery found a replacement worker Pod
`ft-shadow-0-agg-pfljc`, UID `c16ef64b-4473-499a-8f4d-e1bf74118710`, rather than
the originally observed `ft-shadow-0-agg-9hcsg`. Both frontend and worker had
been recreated under new PodCliques. The DGD retained its original UID
`45876da3-cc1b-470a-a87f-a07ac297d2fb`, generation 1 and identical full spec hash.
No inference or failover result can be attributed to the original Pod.

The recovered current/previous logs and cluster health reveal two separate
compatibility failures:

1. **Reader reconstruction:** the singleton-scale workaround passed the prior
   scalar mismatch, then failed on `language_model.lm_head.weight`: meta
   `(65536,4096)` versus committed `(4096,65536)`, both `float8_e4m3fn`.
   This is a post-load transposition/layout mismatch. A generic reshape or
   trusting every committed shape would bypass necessary layout/kernel checks;
   the meta reconstruction and quantization runtime must agree.
2. **Writer warm-up:** after the GMS log confirms read-only remapping,
   FlashInfer autotune executes `up_proj` through ModelOpt's Humming NVFP4 linear
   kernel. The trace reaches `humming_gemm` / `cuLaunchKernelEx` and reports
   `CUDA_ERROR_ILLEGAL_ADDRESS`. Kernel audit shows six new **Xid 31
   `FAULT_RO_VIOLATION ACCESS_TYPE_VIRT_WRITE`**, only on assigned GPUs 4/5,
   in pairs at 06:58:58, 11:07:22 and 15:14:37 UTC. All reference fault virtual
   address `0x5d_3dbfe000`. The exact mutable tensor or helper alias causing the
   write has not yet been established.

The driver Pod and node boot identity are unchanged. Runtime ConfigMap module
and patches hashes exactly match a1's frozen overlay; this is not drift in
the tested source. The original `blocked_transport` observer receipt remains
unchanged as a historical observation. New findings are appended in
`results/overnight-shadow-super-vl-20261104-a1/recovered-qualification-findings.json`.
Full new Pod, event, DGD, claim, ConfigMap, and current/previous logs are in
`recovered-diagnosis-20261105-a1/` under that run.

Installed-source review now identifies a specific missed mutable allocation:
`HummingNvFp4LinearKernel.process_weights_after_loading` creates
`self.locks = torch.zeros(1024, dtype=torch.int32, device=layer.weight.device)`.
It belongs to a non-module helper, so the current GMS module tensor walk and
non-parameter rebinding never visit it. Humming passes that lock tensor into
GEMM after RO remapping. This is a concrete four KiB workspace candidate, still
requiring pointer-range evidence and a successful GPU experiment to establish
the fix. The [writer-only candidate](SHADOW-WRITER-CANDIDATE.md) keeps reader
shape guards intact and records the source, proposed hook, bounded KV-cache
test control, eleven passing CPU tests and exact root-executor commands.

The coordinator held this slot for diagnosis. Root preserved read-only GMS state
and installed Humming/ModelOpt sources, then stopped only this owned graph to
prevent further automatic attempts. A fresh, reviewed candidate is required
before another GPU startup.

### Morning closeout: preserved failure, prepared writer recipe only

Root completed canonical cleanup of a1 with exit 0. The post-cleanup inventory
`results/overnight-20261105-post-cleanup-0803/audit.json` confirms no Shadow
GPU Pods or claims; other workstreams were preserved. Original startup logs,
new Pod identities, GMS state and installed source are retained under a1.

The separately reviewed writer recipe is
`results/overnight-shadow-super-vl-20261105-writer-a4`, namespace
`dynamo-ft-r610-04d348cd-demo`. Root executed CPU/cache/runtime-source preflight
and client/server admission successfully. The actual image supports the fixed
KV-memory flag and matches the expected original source hashes. **No a4 GPU
probe, model DGD, coding request or writer qualification was executed** before
root directed closeout. Canonical writer cleanup then passed, removing its
DeviceClass and verifying zero Pods/claims. The extra CPU source extraction
also found an uncovered MoE-expert lock at
`quant_method.moe_kernel.fused_experts.locks`; a4 handles only linear-kernel
locks. It is a known incomplete prototype, preserved for review, and should
not be GPU-launched as-is. The proposed fix remains CPU-tested only; no claim
of resolved Super VL Shadow recovery is justified.

### Resumed writer isolation: a5 covers both verified lock owners

The fresh a5 candidate extends only the two source-verified ownership paths:
linear NVFP4 kernel locks and MoE fused-expert locks. Exact helper/wrapper classes,
the MoE property-to-implementation identity and both required owner kinds are
checked. Full tensor extents, all registered GMS pools, alias preservation and
pending-publication lifetime are validated before binding the private copies.
There is no generic helper traversal or reader shape relaxation.

Eighteen hook and six controller CPU tests pass. The candidate records both
owner kinds and TP ranks in pointer evidence, and the verifier requires actual
rebinding of both kinds on both ranks. The source-locked recipe and exact
root-executor commands are in the [current candidate packet](SHADOW-WRITER-CANDIDATE.md).
Run: `results/overnight-shadow-super-vl-20261105-writer-a5`; namespace
`dynamo-ft-r610-5fb30ea0-demo`; overlay SHA-256
`79bbcefd977c069e3d942a1f3294fff46696387371ce3c756841d573fcd1377d`.
At preparation, no a5 GPU work had been executed. Root controls cluster CPU
preflight, fresh exact-pair arithmetic/health clearance and any bounded writer
startup. Writer inference/no-new-Xid proof, reader reconstruction and Shadow
promotion remain separate gates; a5 is not a recovery result.

### Historical transport-only handoff, superseded by morning diagnosis

At **11:05 p.m. Pacific**, the bounded a1 startup observer exited 1 after the
cluster connection remained unavailable. The terminal local receipt is
`results/overnight-shadow-super-vl-20261104-a1/qualification-exit.json`:
`blocked_transport`, no fault intent, no injected fault, no recovery proof.
At that point the owned graph, GPU reservation and DeviceClass were retained
for a live audit. The observation alone did not establish engine startup's
outcome. The subsequent audit documented the failures above; a1 is now cleaned.

The closed attempt used namespace `dynamo-ft-r610-caa592eb-demo`, graph `ft-shadow`,
DeviceClass `dynamo-ft-r610-caa592eb-demo-shadow`. The scoped reservation is
`.local/dynamo-ft-r610-caa592eb-demo-shadow.gpu-lease/owner.json`.
No fault intent had been written. Initial same-run re-observation was considered
while its live identity was unknown. Replacement Pods and fresh RO-write Xids
ruled that out. Do not prime or redeploy this closed attempt; future changes
need a fresh candidate and actual active/parked-standby qualification.

## Questions for review and upstream candidates

- Does GMS need a supported postprocessed parameter-shape contract for
  quantized meta models, rather than per-model shape exceptions? A proper
  regression should compare the writer's final model and reader materialization.
- The installed `_create_meta_model` catches a failure from the whole vLLM
  `process_weights_after_loading` pass, logs only at DEBUG and returns the
  partially processed model. Improve that diagnostic or fail closed with the
  first failed layer/backend context. A later shape mismatch conceals the
  earlier reconstruction failure; continuing with arbitrary shape adoption
  would not rebuild missing runtime helper state.
- If text-only startup still faults, obtain the synchronous failing kernel and
  GPU fault log before deciding whether the issue is scratch KV, mutable shared
  tensors, or a backend-specific assumption.
- Is the measured standby headroom acceptable for the workshop's intended
  coding-agent capacity? A successful small request alone cannot answer it.
- Select a representative constant offered load and compare response latency,
  surviving capacity and replenishment under a fault; no SLO promise yet.
- Qualification deadlines should also exist on the cluster. The local observer
  ended while VPN access was lost, but the owned DGD kept reconciling failed
  engines, producing repeated startup faults. A Pod deadline alone may permit
  its controller to create another Pod. Consider a scoped DGD-level expiry or
  an independently reviewed server-side cleanup guard for unattended trials.
  No such shared/operator change was made in this work.
- Parent must register demo 08 with the shared capture utility after the
  candidate's terminal validation; preserve failed attempts as failures.
