# Super VL TP=2 feature retest — October 15, 2026

Retests completed with two blockers. Super VL TP=2 passed aggregated inference,
KV routing, engine sidecar, image input, KVCR, disaggregation, ModelExpress and
Grove. Snapshot's runtime pause/resume passed; native capture requires the CUDA
launch-job driver path. Shadow failed model/GMS startup on both tested attention
configurations, so no recovery fault was injected. These are bounded feature
checks, separate from the earlier Lightning TP1 qualification.

## Frozen inputs

- Model revision: `8a115b9d966adce8c059a7bcf47f49a1e57957d8`.
- Architecture: `NemotronH_Omni_Reasoning_V3`; 88 safetensors shards;
  weight index reports 75,010,189,968 bytes; staged shard files total
  75,010,188,240 bytes. Both values are retained rather than assumed equal.
- Common runtime:
  `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Dynamo source: `ea23e5130c1bfbadec477b99449d0cee5598caa0`;
  vLLM `0.31.1rc1.dev23+g43b4aaea3`; KVCR 0.1.1; ModelExpress 0.6.0;
  GMS 0.9.0. Same image for each engine/frontend/sidecar.
- Actual H100 runtime logs select the HUMMING NVFP4 MoE backend and FP8 KV.
- TP=2 within a node; 8192 context; four sequences; serving HBM utilization 0.85
  (0.65 for Snapshot and Shadow to bound the KV pool and leave warm-up headroom);
  FlashInfer Mamba, FP16 SSM cache; speculative decoding disabled. Image input
  limited to one per prompt; video disabled for these bounded tests.
- Run: `results/20261015-super-vl-tp2`; namespace `dynamo-ft-20261015t220520z`.
  New cache: `/efs/feature-tests/20261015-super-vl-tp2/hf/hub`.
- [Committed lock](../configs/super-vl-tp2-lock.json) includes metadata hashes and
  the original recipe template provenance. Serving manifests adapt the pinned
  Lightning templates; they are not verbatim upstream Super VL recipes.

## Results

| Check | Outcome | Scope |
| --- | --- | --- |
| Current inventory | Passed | All three nodes Ready; driver 580.173.02; API 1.34.2; 32 EFA resources per node; GPU allocation uses DRA, so scalar GPU allocatable is zero. |
| Model metadata | Passed | Immutable revision and architecture pinned; metadata inspection only. |
| Actual common-image architecture inspection | Passed | Exact runtime digest verified; vLLM registry includes the Omni architecture and native engine binary. CPU inspection only. |
| Two-GPU runtime probe | Passed | One two-H100 claim, arithmetic on both CUDA devices, EFA provider, package and entrypoint contracts. No model loading or TP collective qualification. |
| Grove/KAI | Passed | Four initial Pods, six scaled Pods, restored to four. Two GPU cliques request two GPUs each: four → eight → four GPUs. Correct arithmetic on each GPU, PodGang creation and cleanup. No model inference. |
| Shadow runtime and allocator preflight | Passed | Runtime entrypoints present; all three nodes eligible with GPU DRA and no competing NVIDIA GPU device plugin. Entrypoint and allocator check only; startup/recovery outcomes are separate below. |
| Checkpoint staging | Passed | All 88 shards present at the exact revision; 75,010,188,240 file bytes; completed 22:30:03 UTC. No substitution. |
| Aggregated serving / KV routing | Passed | Two TP2 workers on cp-0124 and cp-0198 returned READY. Two independent prefixes, six unforced repeats, each reused 4,224 tokens; frontend applied two stored events. Completed 22:44:26 UTC. |
| Image request | Passed | Dedicated one-worker TP2 deployment with Dynamo `--enable-multimodal` identified a synthetic red PNG; completed 22:58:20 UTC. Initial HTTP 400 came from the text worker configuration without that flag. No video or image-aware routing qualification. |
| Engine sidecar | Passed | Native vLLM gRPC TP2 engine and separate CPU Dynamo sidecar on cp-0942; both exact common digest; expected READY output and two-GPU allocation verified, 22:53:35 UTC. |
| KVCR | Passed | Initial transfer independently verified from saved receipts; bounded-log retry also passed peer reuse and all three idle-health samples with zero restarts, 23:34:14 UTC. Six blocks, 103,809,024 matching reported source/target bytes, 4,224 cached tokens, expected READY, EFA, zero failed/partial deliveries. One control port per DP1 worker, not per TP rank. |
| Disaggregation | Passed after telemetry fix | cp-0124 prefill → cp-0198 decode; four completed rank-level transfer samples / 224,591,872 reported bytes, 6,240 imported prompt tokens, zero failed transfers/notifications, expected outputs. Completed 23:54:25 UTC. Both TP ranks need prometheus_mp with a shared per-Pod metrics directory; single-process exporter caused the first HTTP 500. |
| ModelExpress | Passed | cp-0124 → cp-0198; 1,869 tensors / 40.27 GB logged per TP rank, both LIBFABRIC/EFA transfers completed, no receiver disk fallback, expected READY. Completed 23:49:25 UTC; graph cleanup completed 23:50:03. Transfer log durations 4.36s / 3.32s are observations, not a benchmark. |
| Snapshot runtime pause/resume | Passed | Exact model TP2, two GPU UUIDs, READY before and after. Communicator preparation 54.13s; restore/wake 3.21s. Distinct from CRIU restore; completed 00:00:21 UTC October 16 (October 15 local). |
| Native Snapshot restore | Blocked | Capture reached model pause, then agent rejected the missing CUDA launch-job file at 00:09:54 UTC October 16. The installed 580.173.02 CUDA checkpoint CLI rejects --launch-job. No usable artifact or restored Pod qualified. Runtime preparation passed separately. |
| Shadow recovery | Blocked | Both default FlashAttention/graphs and eager FlashInfer startup failed after GMS weight remap. Reader ranks reject input_scale shape (1,) versus scalar (); writer reported illegal CUDA access. Shared two-GPU claim and identical runtime used, but no active/standby pair or recovery fault qualified. |

## Resource requests

| Feature | Simultaneous GPUs | Layout |
| --- | ---: | --- |
| Aggregated KV routing, disagg, ModelExpress, KVCR | 4 | Two workers, two GPUs each, across two nodes |
| Engine sidecar, Snapshot, Shadow | 2 | One worker allocation on one node; Shadow shares weights across its engines |
| Grove | 4 → 8 → 4 | Two GPU cliques, one → two → one replicas, two GPUs per Pod |

A TP2 serving worker requests 8 CPUs and 128 GiB host memory, with a 256 GiB
memory limit. These are bounded test requests, not measured minimum capacity.
Transport tests request eight EFA resources per TP2 worker; successful provider
initialization alone is not evidence of a completed feature transfer.

The first aggregated worker reported 37.59 GiB of model memory per GPU.
Checkpoint loading from EFS took about 489 seconds before compilation/warm-up.
The runtime selected FP8 KV and a 4,224-token aligned Mamba page; cache/transfer
requests use a 6,000-word prefix to cross that page boundary. These are
startup observations, not a performance or minimum-memory qualification.

The first KVCR peer-transfer proof is frozen under
`results/20261015-super-vl-tp2/evidence-1792105900541846000/`, with
`kvcr-transfer-receipts.json` and a SHA-256 manifest. Its successful transfer
qualification is separate from the interrupted first action. The retry also
passed the idle health check. The successful full retry and latest proof are frozen under
`evidence-1792107374346035000/`. The original timeout receipt is retained.

The first disaggregation failure is frozen under
`evidence-1792107539120272000/`, including recovered successful log captures
from immutable command receipts. Shutdown 401 errors occurred after cleanup
started and are separate from the earlier telemetry failure. The MP exporter
uses `NIXL_TELEMETRY_EXPORTER=prometheus_mp` and
`NIXL_TELEMETRY_MULTIPROC_DIR=/tmp/nixl-metrics`; all ranks in one container
share that directory. See [NIXL MP exporter documentation](https://github.com/ai-dynamo/nixl/blob/main/src/plugins/telemetry/prometheus_mp/README.md).

## Shadow startup retry

The first GMS writer loaded both ranks, projected 12.24 GiB available KV per
GPU and remapped 396 allocations / 37.82 GiB per GPU. It then failed in
`hopper/flash_fwd_launch_template.h:200` with an illegal CUDA memory access
before the active/standby state. No recovery fault was injected. Startup was
interrupted locally after preserving previous-container logs; scoped cleanup
released the graph and GPU claim. Initial evidence:
`evidence-1792110076195783000/`.

After the writer restart, both TP ranks also rejected the committed reader
metadata for `language_model.lm_head.input_scale`: fresh parameter shape `(1,)`
versus GMS shape `()`, both float32. This is distinct from the earlier Lightning
packed `lm_head.weight` mismatch. It is a GMS/model reconstruction error, not
an absent GPU DRA allocator. Those logs are frozen in
`evidence-1792110398707559000/`.

The same model/revision, TP2 allocation, image and source-hashed GMS signature
overlay were retried with `--attention-backend FLASHINFER --enforce-eager`.
Both ranks selected FlashInfer and eager execution. The writer again reported
an illegal CUDA access during startup at 00:32:06 UTC; the reader repeated the
scalar-shape mismatch on both ranks at 00:32:10. The stack reported the CUDA
error through FlashInfer prefill; asynchronous reporting does not identify the
first invalid access. Switching attention backends and disabling CUDA graphs
did not resolve the failure. The waiter saved the permanent reader error and
stopped before fault injection. No alternate model was substituted.

The remaining work is GMS/Nemotron integration: reconstruct the post-quantization
parameter metadata, including scalar scales, and debug the remap/warm-up CUDA
failure. A corrected source/image needs fresh active/standby inference first,
then the single verified EngineCore fault and recovery/replenishment checks.
GPU DRA is already enabled; those startup failures are not a missing allocator.

## TP2 Snapshot blocker and next changes

The actual SnapshotJob error was:

```text
multi-GPU CUDA source is missing /snapshot-control/cuda-checkpoint-job;
source must be launched under cuda-checkpoint --launch-job
```

The no-model diagnostic `scripts/snapshot_launch_probe.py` ran the installed
agent's CUDA checkpoint utility. Its help identifies driver **580.173.02**;
`--launch-job` exits 1 with `unrecognized option` / `option(s) not supported by
this CUDA Driver`. It creates no job file. The retry harness now runs this
capability gate before creating a TP2 capture workload; an unchanged-cluster
retry stopped at the gate with no GPU Pod created. This was not a storage failure, OOM,
or evidence that TP2 pause/resume is unsupported. The sampled capture-worker
cgroup peak was approximately **128.7 GiB** with zero OOM events; this failed
attempt does not establish the RAM requirement for a complete capture.

Next qualification target, requiring a separately reviewed node change:

1. Upgrade the Snapshot test node to a supported **R610 or newer driver/tool
   combination**, then require the launch probe to produce a nonempty job file.
   NVIDIA lists CUDA IPC checkpoint support under R610; merely adding a command
   flag to the current 580 deployment cannot satisfy the installed agent.
2. Make `cuda-checkpoint` available in the source workload and start its process
   tree under `--launch-job`. Persist the driver-created file to
   `/snapshot-control/cuda-checkpoint-job` and export `CUDA_CHECKPOINT_JOB_FILE`
   to that path before launching Python. The installed Dynamo-generated capture
   job did not do this automatically. Verify matching restore-side job-file
   support and binary availability; source wrapping alone is not a restore pass.
3. Create a fresh capture after the driver/launch change, require a distinct
   restored Pod UID and correct inference, then measure artifact bytes and RAM.
   Existing Lightning/R580 artifacts and the old 64 GiB cache allowance do not
   qualify the Super VL TP2 path. Keep capture and restore driver versions matched.
4. Requalify GPU DRA and EFA/NIXL on any upgraded node before using it for the
   other demos. No driver/agent/operator upgrade or disk formatting was applied.

Sources: [NVIDIA CUDA checkpoint R610 features](https://github.com/NVIDIA/cuda-checkpoint),
[Snapshot launch wrapper](https://github.com/ai-dynamo/snapshot/blob/v0.1.0/operator/internal/protocol/source_job.go),
[Snapshot CUDA job-file contract](https://github.com/ai-dynamo/snapshot/blob/v0.1.0/agent/internal/cuda/job.go).
The upstream wrapper is the implementation reference; a prepared command is
not proof that our installed Dynamo operator injects it.

## Final state and evidence

Fresh inventory finished **00:35:20 UTC October 16 (October 15 local)** under
`results/20261016-super-vl-tp2-final-inventory/`: all three nodes Ready, driver
580.173.02 unchanged, 32 EFA resources per node, no Pods in the test namespace
and no ResourceClaims anywhere in this observed cluster. The final idle receipt
also records zero active test Pods and zero remaining claims.

After the Shadow CUDA failures, a fresh two-GPU DRA probe on cp-0124 passed CUDA
arithmetic on both H100s and EFA provider/runtime checks at 00:34:51 UTC.
This verifies post-test runtime health, not a Shadow recovery pass. The model
cache and retained failed Snapshot API objects remain; shared cluster software
and storage formatting were unchanged.

`super-vl-summary.json` records all eleven feature actions, nine passed and two
blocked. Final evidence is frozen with SHA-256 hashes under
`results/20261015-super-vl-tp2/evidence-1792110984672380000/` (118 files).
Earlier failed attempts and their archives remain available. The original
Lightning common-runtime lock has not been promoted to this model.

Validation: 34 offline tests passed; Python sources compiled; Bash syntax and
outside-directory runner invocation passed. The runner executes a hashed copy
of itself so edits cannot change Bash's file-read offset during a long run.

## Reproduce and resume

```bash
# Fresh run: metadata pin, staging, actual image inspection, then the full matrix.
bash scripts/retest_super_vl.sh results/NEW-RUN

# Resume this run. Successful feature actions are retained; blocked actions retry.
bash scripts/retest_super_vl.sh results/20261015-super-vl-tp2 agg

# One feature, with failure cleanup and durable receipts:
.local/venv/bin/python scripts/super_vl_tests.py feature \
  --feature agg --run results/20261015-super-vl-tp2

# Read-only progress:
.local/venv/bin/python scripts/super_vl_tests.py status \
  --run results/20261015-super-vl-tp2
```

The runner never injects a second Shadow fault in a run. It stops if a failed
feature leaves live Pods/claims, rather than launching another graph over them.
Manifests saved by the updated harness include DRA claim templates; the Shadow
DGD retains scalar GPU count as input to the operator's shared-claim generation.
All live writes are confined to owned test resources and EFS cache/artifacts.
No shared operator, agent, driver or storage formatting change is included.

Current upstream references, checked October 15:
[Super VL model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4),
[H100 recipes](https://docs.nvidia.com/dynamo/dev/recipes/nemotron-3-5-super-vl),
[Snapshot walkthrough](https://docs.nvidia.com/dynamo/dev/kubernetes/model-deployment/model-loading/dynamo-snapshot-experimental),
[compatibility matrix](https://docs.nvidia.com/dynamo/reference/compatibility).
The current Snapshot walkthrough now includes an eight-GPU TRT-LLM example;
that is separate evidence from our vLLM/Nemotron TP2 runtime and installed agent.
