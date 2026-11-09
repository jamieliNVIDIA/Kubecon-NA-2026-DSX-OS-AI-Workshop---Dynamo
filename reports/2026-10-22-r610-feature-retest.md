# Super VL TP2 feature reverification on R610

**Completed October 22, 2026; preferred-model Shadow remains blocked.** Serving/KV routing,
image inference, native engine sidecar, KVCR, disaggregation, ModelExpress and
Grove/KAI passed on driver **610.57.04**, with the same frozen Super VL TP=2
model and common runtime. Preferred-model Shadow startup remains blocked.
A separate Qwen TP1 control passed actual Shadow process failover in **2.62s**,
with one failed request and a replenished standby. Snapshot's separately passing
R610 capture/restore and NVMe controls were not repeated.

These are bounded functionality checks, not throughput, attendee capacity,
hardware-failure recovery or startup-performance benchmarks. All times are UTC.

## Results

| Feature | October 22 outcome | Fresh evidence and limits |
| --- | --- | --- |
| Aggregated serving / KV routing | Passed, 21:01 | Two cross-node TP2 workers, READY; two independent prefixes, six unforced repeats with 4,224 reused tokens each; two frontend stored events. |
| Image inference | Passed, 20:58 | Separate TP2 multimodal worker correctly identified a synthetic red PNG. No video or image-aware routing qualification. |
| Engine sidecar | Passed, 21:08 | Native vLLM gRPC engine plus CPU Dynamo sidecar, identical common image and two-GPU DRA allocation; READY. Replacement worker had zero restarts with a 1,800s startup allowance. No SGLang/parity qualification. |
| KVCR | Passed, 21:59, after discovery-test correction | Cross-node EFA peer transfer: six matched blocks / 103,809,024 reported bytes, 4,224 cached tokens and READY; no failed/partial deliveries. Three idle-health samples per worker, zero restarts. Initial attempt retained separately. |
| Disaggregation | Passed, 21:38 | Four completed rank-level transfers / 224,591,872 reported bytes; 6,237 externally imported prompt tokens, correct responses, no failed transfers/notifications. NIXL multiprocess telemetry retained. |
| ModelExpress P2P | Passed, 21:41 | cp-0124 → cp-0198; each TP rank received 1,869 tensors / 40.27 reported GB over LIBFABRIC/EFA. Receiver returned READY; disk fallback explicitly rejected. Maximum per-rank transfer log duration 4.41s, not a benchmark. |
| Grove/KAI | Passed, 20:39 | Real two-GPU DRA claims, gang creation and arithmetic on each allocated GPU; four → eight → four GPUs. No model inference or scheduling-policy qualification. |
| Super VL Shadow, TP2 | Blocked before fault injection, 21:57 | Reader rejects `language_model.lm_head.input_scale`: parameter `(1,)/float32`, GMS `()/float32`. Writer also reports CUDA illegal access. Same integration failures as the earlier model attempt; DRA preflight passed. |
| Separate Shadow control, Qwen TP1 | Passed, 22:04 | Same common runtime and source-hashed GMS signature overlay. Active EngineCore killed; standby returned correct output in 2.619s, same Pod/GMS, changed worker identity and new standby confirmed. One failed request. Does not qualify Super VL or TP2 recovery. |

## Frozen inputs

- Driver **610.57.04** on all three H100 nodes; no additional rollout.
- Model `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`.
- Revision `8a115b9d966adce8c059a7bcf47f49a1e57957d8`, **TP=2**.
- Common image:
  `nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d`.
- Installed workload versions: Dynamo 1.6.0 preview; vLLM
  `0.31.1rc1.dev23+g43b4aaea3`; PyTorch 2.13.0+cu130; KVCR 0.1.1;
  NIXL 1.5.0; ModelExpress 0.6.0; NCCL 2.30.7; GMS 0.9.0.
- Reused October 15 model cache; each feature freshly checks the exact revision,
  88 weight files / **75,010,188,240 actual file bytes**, and metadata hashes.
  No download or preferred-model/runtime substitution in the TP2 matrix.
- Only after this fresh GMS incompatibility was recorded, the guarded control
  used `Qwen/Qwen3-0.6B`, revision
  `c1899de289a04d12100db370d81485cdf75e47ca`, TP1, same common image.
  Its original cached 1,503,300,328-byte weight file was revalidated; no download.

GPU/EFA probes precede each TP2 feature. Verification requires actual inference,
routing, matched transfer counters or fault recovery; deployment readiness alone
cannot count as a pass. Shadow uses the existing image/source-hashed test-local
GMS signature overlay, not a shared image modification. No model-specific GMS
fix is implied by these tests.

## Startup and test-harness findings

Concurrent EFS reads made large-model startup slow. Four initial engines took
roughly 16 minutes to read weights; five concurrent source engines took about
23 minutes, before initialization/warmup. These observations do not establish
storage throughput or attendee concurrency. Prewarming and startup headroom need
separate workshop sizing.

The initial native sidecar engine restarted with the exact error
`startup handshake timed out while waiting for READY after 600s`. Installed help
confirms `--engine-ready-timeout-secs` and `VLLM_ENGINE_READY_TIMEOUT_S`. Only the
owned test DGD was changed to **1,800s**, matching its existing startup probe;
the same image/model/TP then passed with zero restarts. Future common-image TP2
sidecar renders carry this allowance. Both initial and applied complete YAML
remain under the generated sidecar manifest directory.

The initial KVCR serving check passed, but twelve unforced discovery queries
selected the same worker despite both workers being registered and Ready.
KV routing is not required to visit every peer. The verifier now reads the two
live Pod-owned generate endpoints from DynamoWorkerMetadata and explicitly
checks frontend selection for each. Actual cross-peer block/byte matching,
cached-token reuse, correct output and zero failed/partial delivery requirements
are unchanged. A fresh namespace proved the corrected complete test; the initial
failed attempt remains intact.

The new wrapper initially hit a Python `feature` keyword collision after Grove
finished. It now uses `tested_feature`; guarded recovery only accepts terminal
receipts from this same campaign, checks frozen input/namespace identity and
rechecks cleanup, without repeating completed workloads. The initial sidecar
and transfer supervisors also had 30-minute deadlines that included long model
loads and superseded startup attempts. Only exact owned local supervisors were
stopped; independent feature verifiers completed within fresh bounded waits.
PID/intent receipts are `sidecar-watchdog-handoff.json` and
`transfer-watchdog-handoff.json`. Future outer bounds are 60 minutes per ordinary
feature, 90 minutes for two-stage MX and 25 minutes for preferred Shadow.

A follow-up CUDA probe selects **the exact failed Shadow pair** using UUID-based
DRA selectors. Both GPUs passed fresh arithmetic at 22:01:50 without reset.
Its first attempt completed arithmetic but failed only a UUID string comparison
because PyTorch omits the `GPU-` prefix; normalization was corrected and the
complete probe repeated successfully. Original command/diagnostic receipts are
preserved. This does not erase the recorded GPU faults or qualify GMS recovery.

Validation: **32 targeted unit tests passed** across TP2 claims, Shadow fault
guards, same-campaign recovery, KVCR peer ownership/readiness and transfer receipt
verification. Python compilation passed. Two additional local audit guards verify
that microsecond shifts in `dmesg` ISO timestamps do not create false new errors,
while repeated Xid occurrences are still counted.

## Cleanup and health

Final inventory at **22:05:52 UTC**, and three GPU/kernel checks completed by
**22:05:58 UTC**, found all three nodes Ready, driver 610.57.04 and eight visible
H100s / 32 EFA resources each. Boot IDs, node UIDs and condition statuses are
unchanged; zero GPU ResourceClaims, no active feature-test Pods, no unready
infrastructure, no increased infrastructure restart counts, and unchanged Helm
revisions/versions (Dynamo platform 1.5.1 revision 4). Scalar GPU allocatable is
zero because allocation uses DRA.

The audit intentionally returns **blocked** for the two new Shadow-related Xids
below; it does not label this run as having no new GPU errors. No new Xids were
recorded on cp-0198 or cp-0942. Preferred Shadow cleaned up at 21:58:40 UTC,
the exact-GPU arithmetic follow-up at 22:01:57 UTC, and the separate Qwen
recovery control at **22:04:24 UTC**. The failed Super VL Shadow writer logged two
new **Xid 31** MMU write faults at 21:56:23 on cp-0124 GPUs 4 and 5 (PCI 97:00
and a8:00). The exact pair subsequently passed CUDA arithmetic. Existing contained
Xid 94 history remains recorded. No GPU reset or node restart was performed.

Each test removes its own workload and checks that its active Pods and GPU
ResourceClaims are gone. Existing shared controllers, driver, EFA/Grove/KAI,
EFS data and Snapshot/NVMe configuration are preserved. Static Retain cache
PV/PVCs and namespaced configuration remain for evidence/reproduction.

## Reproduction and receipts

```sh
.local/venv/bin/python scripts/r610_feature_retests.py matrix \
  --run results/REPLACE-WITH-FRESH-R610-RETEST
.local/venv/bin/python scripts/r610_feature_retests.py progress --brief \
  --run results/REPLACE-WITH-FRESH-R610-RETEST
.local/venv/bin/python scripts/r610_feature_retests.py one --feature kvcr \
  --run results/REPLACE-WITH-FRESH-SINGLE-FEATURE-RETEST
.local/venv/bin/python scripts/r610_feature_retests.py summarize \
  --run results/20261022-r610-feature-retest \
  --kvcr-retry results/20261022-r610-kvcr-retry
```

- Input lock: `configs/super-vl-tp2-lock.json`.
- Primary run: `results/20261022-r610-feature-retest/`.
- Corrected KVCR run: `results/20261022-r610-kvcr-retry/kvcr/`.
- Separate Shadow control: primary run's `shadow-control/`.
- Generated YAML: `configs/dgd/super-vl-r610-d906a5f1/` and corrected KVCR
  `configs/dgd/super-vl-r610-040e184f/`.
- Baseline inventory: `results/20261022-r610-feature-before/`.
- Baseline GPU/kernel health: `results/20261022-r610-feature-health/`.
- Immediate post-Shadow health: `results/20261022-r610-post-shadow-startup-health/`.
- Final inventory: `results/20261022-r610-feature-final/`.
- Final GPU/kernel health: `results/20261022-r610-feature-final-health/`.
- Validated feature receipts: primary run's `feature-qualification-summary.json`.
- Node/cleanup audit: primary run's `cluster-audit.json` (blocked for the two new Xids).
- Committed compact receipt: `receipts/2026-10-22-r610-feature-retest.json`.

The final summary validates frozen inputs, underlying pass receipts, terminal
outcomes and cleanup. It records the selected fresh KVCR state plus the original
failed attempt's path/hash/error; the preferred-model Shadow block and small-model
control remain separate. The partial supervisor summary is preserved before the
validated final summary replaces it. Prior October 15 results are not promoted.

Read-only final comparison can be reproduced from saved receipts:

```sh
.local/venv/bin/python scripts/r610_retest_audit.py \
  --before results/20261022-r610-feature-before \
  --after results/20261022-r610-feature-final \
  --health-before results/20261022-r610-feature-health \
  --health-after results/20261022-r610-feature-final-health \
  --output results/20261022-r610-feature-retest/cluster-audit.json
```

Exit 1 records the known new Xid events; the JSON separately records successful
cleanup, unchanged infrastructure and node state. `post_shadow_cuda_probe.py`
reproduces the exact-GPU follow-up with inspect-first UUID selection and scoped
claim/Pod cleanup. No shared infrastructure or storage configuration changed.
