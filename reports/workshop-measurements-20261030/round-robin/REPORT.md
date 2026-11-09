# AgentX replica and routing measurements

**C1 and C4 scale-out evidence is closed out locally, November 4, 2026.**
C4's complete pullback verified **142 files with zero mismatches**, including
both final arm inventories and original raw archives. Local recomputation
exactly reproduces the accepted remote analysis apart from relocated export
paths. [C4 closeout and provenance](C4_CLOSEOUT.md).

The original controller later exited one at the C1 KV qualification guard.
Its routing-policy comparisons are not running; they require a fresh harness/run.
C4's own accepted stage exited zero and verified cleanup. Keep these separate
outcomes explicit; see the [routing failure diagnosis](KV_DISCOVERY_DIAGNOSIS_20261104.md).

## Completed C1 scale-out pair

The November 2 resumed run completed one paired observation at **one live
session tree**, with manual scale-out from one TP2 worker to two. Both arms
passed explicit completion/submission validation, preserved the full pinned
AgentX corpus and had zero request errors or context overflows. The first
worker's UID survived scale-out; worker request counters split **41 / 41** in
the two-worker arm.

| Observation | One worker, 2 H100 GPUs | Two workers, 4 H100 GPUs |
| --- | ---: | ---: |
| Successful measured requests | 84 | 82 |
| Completed output tokens | 64,547 | 60,400 |
| Mean active-generation tokens/s/user | 154.05 | 152.14 |
| TTFT p50 | 322.22 ms | 423.78 ms |
| TTFT p99 | 2,617.90 ms | 5,332.15 ms |
| Server-reported cache-read tokens / prompt tokens | 97.62% | 94.75% |
| Canonical AIPerf aggregate output tokens/s | 53.79 | 66.70 |
| Canonical rate denominator | 1,200.00 s | 905.61 s |
| Observed-request-span output tokens/s, derived | 70.83 | 66.70 |
| Observed request-span duration | 911.26 s | 905.60 s |

**The canonical rate's apparent 24% increase is affected by different phase
tail accounting and must not be presented as a capacity speedup.** Both runs
used a 900 s admission window and at most 300 s grace. The first phase waited
through all grace despite all 84 requests completing; the second closed after
about 5.6 s of grace. The separately labeled derived rate divides completed
output tokens by AIPerf's observed request-span duration. Neither is a maximum
GPU throughput measurement.

At this low load the second replica did not improve the measured active-user
generation speed; cache reuse was lower and first-token latency higher. The
one-worker GPUs averaged about 49% utilization during the 900 s admission
window; the four two-worker GPUs averaged about 21–25%. The C4 observation below
and the pending matched routing-policy pairs provide the next evidence about
busier service and cache-aware routing.

The first three source traces were sampled in both arms. The first two had the
same measured turns; the final trace contributed five requests in the first arm
and three in the second. All measured records in these C1 arms were main-agent
requests. The corpus's parallel-sibling example is supported separately; it was
not exercised by these measured C1 records. Logged completed replay sessions
and unfinished child streams are not complete coding-task successes.

## Completed C4 scale-out pair — locally verified

One fixed-order paired observation at **four live session trees** completed on
the same pinned model, native context, corpus, replay settings and TP2 H100
workers. Both arms have zero request errors and zero cancelled profile records.
The original first worker survived scale-out. Owned GPU Pods, ResourceClaims,
graphs and the remote lease were verified absent before the MX handoff at
`2026-11-04T00:06:07Z`.

| Observation | One worker, 2 H100 GPUs | Two workers, 4 H100 GPUs |
| --- | ---: | ---: |
| Successful measured requests | 122 | 114 |
| Completed output tokens | 97,394 | 90,369 |
| Mean active-generation tokens/s/user | 139.79 | 151.52 |
| TTFT p50 | 306.19 ms | 477.59 ms |
| TTFT p99 | 2,150.72 ms | 5,238.63 ms |
| Server-reported cache-read tokens / prompt tokens | 95.79% | 90.72% |
| Canonical AIPerf aggregate output tokens/s | 81.16 | 75.31 |
| Canonical rate denominator | 1,200.00 s | 1,200.00 s |
| Observed-request-span output tokens/s, derived | 107.89 | 100.44 |
| Observed request-span duration | 902.69 s | 899.74 s |

At this fixed offered load, mean active-generation speed increased about 8.4%,
while completed output tokens and aggregate rate declined and first-token
latency increased. Cache-read share was about 5.08 percentage points lower.
This is one operational scale-out pair, with different measured turn counts
inside the same admission duration. It does not measure a capacity limit or
isolate a routing-policy effect. A fresh matched RR/KV experiment is still
needed to establish any routing benefit; the original queue stopped before
the C1 KV AgentX workload and never ran the C4 policy pair.

C4's first arm included 61 main-agent, 60 subagent and one flat request across
five source trace IDs; the subagent requests came from two source roots. The
second arm included 56 main-agent, 57 subagent and one flat request across four
source trace IDs. Measured Dynamo worker request counters split **57 / 57**
after scale-out, versus 122 on the original single worker.

Both arms have 180 GPU samples per GPU during the 900 s admission window.
Mean utilization was **65.42–65.46%** on the single worker's GPUs and
**35.47–37.22%** across the two-worker arm's GPUs. Branch exports recorded
six/three children spawned, two/two completed and one/zero truncated. Neither
arm completed a full agent graph; these are partial replay trees, not complete
coding-task successes. Exact trace IDs/offsets, worker IDs and per-GPU values
are in the locally recomputed analysis.

The first arm continued in the cluster while the laptop API tunnel failed. Its
original execution completed normally and was recovered without replay; the
second arm began after a network-recovery pause under the stable bastion
controller. The same cluster-side AIPerf client, sealed scientific settings and
first worker were retained. Disclose this inter-arm pause and change of
controller observer with the pair.

Complete local evidence is now in
`results/workshop-c4-closeout-20261104-a1/verified/`, with its hash-verification
receipt and `analysis/` CSV/JSON outputs alongside. Both raw archives' 14 regular
files were checked against the collected extracted files. The earlier local
partial mirror remains unchanged; use the closeout tree for the complete C4
evidence. The original remote status snapshot and all acceptance/failure
inventories are preserved. MX has separate measurements and provenance.

This C4 campaign used the earlier multimodal-capable serving configuration
with text requests, not the subsequent `--language-model-only` MX startup
baseline. No benchmark was rerun or configuration changed during closeout.

## Identity, conditions and evidence

- Model: `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, revision
  `8a115b9d966adce8c059a7bcf47f49a1e57957d8`.
- Runtime: immutable image `e98d074e…`; vLLM
  `0.31.1rc1.dev23+g43b4aaea3`, Dynamo 1.6.0, TP2 H100.
- AIPerf: `e2c149ee29d3b64798d8ba2176e9f42e0aa89280` plus the recorded
  dataset-revision-only patch; canonical `inferencex-agentx-mvp` replay.
- Dataset: all 393 eligible source traces, pinned revision
  `23f152f6f0f9399a85901b89a6458def0ef16729`; no truncation or trace substitution.
- Native 1,048,576 context, four engine sequences per worker, seed 20261030;
  canonical primer, pacing, fresh per-invocation benchmark prefix namespace.
- Workers ran on cp-0124 / cp-0198; the dedicated CPU client ran on cp-0942.
  No competing GPU measurement workstream ran during the pair.
- The operational scale-out arm retained the first worker and its cache
  occupancy. This is not the fresh-worker matched RR/KV-policy experiment.

Raw run: `results/workshop-rr-20261102-resume01/`.

- `c1-r1-a1/` and `c1-r2-a1/`: frozen profiles/specs, actual Pod/claim identity,
  worker/frontend logs, endpoint smokes, GPU telemetry, AIPerf JSON/JSONL and
  server metrics, positive acceptance summaries and integrity manifests.
- `scaleout-c1-a1-analysis.json` and `scaleout-c1-a1-REPORT.md`: timing boundaries,
  complete metric values, exact source trace IDs/offsets and worker distribution.
- `cpu-transport-recovery-a1/`: full reconstruction receipts copied in compressed
  form with both compressed/original hashes, C4 cache-hit check, full 393-root /
  9,450-child / 98,827-turn proof and measured 32.01 GB peak with no OOMs.

A temporary server-metrics completion relay timeout in the first arm resolved
without changing parameters; accepted server exports include both frontend and
worker endpoints. Native vLLM engine request counters include additional internal
requests and are kept separate from Dynamo's `generate` request counters and
AIPerf's client request count.

After the C1 pair, zero owned GPU Pods and ResourceClaims were verified and the
lease was explicitly handed to the MX artifact workstream. C4 and matched
RR/KV comparisons were then pending that workstream's verified cleanup/handoff.
The API tunnel failed again during MX's turn; MX retained its lease until
cleanup could be verified. No C4 or policy profile had started at that point.
See [RESUME.md](RESUME.md) for current ownership and recovery gates.

## Historical execution and recovery — November 3

The dated checkpoints below describe the original recovery sequence. Current
completion and routing status are given above; do not resume these old helpers.

Access was restored again. MX's interrupted resources were collected and cleaned;
zero GPU Pods, ResourceClaims and graphs were verified before releasing its lease.
The previous RR client had actually reached `Failed / DeadlineExceeded`, so a
fresh immutable run and client were prepared:

`results/workshop-rr-20261103-resume02/`, namespace `dynamo-ft-r610-1ec4908b-rr`.

Full CPU qualification passed in 488.05 s with about 32.01 GB peak memory and no
OOMs. All corpus/mmap hashes match the accepted C1 preparation. Full graph-bearing
receipts were transferred compressed with both original/compressed hashes. The
existing C1 pair was not rerun: `upstream-c1-prerequisite.json` verifies its 67
sealed files, accepted exports and unchanged scientific/deployment settings.

The fixed continuation controller started at `2026-11-03T22:41Z`. Its planned
sequence was C4 scale-out, the separately owned MX artifact04 matrix, then fresh
two-worker RR/KV policy pairs at C1 and C4. Each GPU stage is serialized and
requires a positive owned-resource cleanup proof before the next stage.

Original laptop-controller receipts:
`results/workshop-rr-20261103-resume02/continuation-a1/`. The recovery and stable
handoff below explain how the accepted C4 observation was subsequently obtained.

At `23:01Z`, the API tunnel failed during the first C4 profile poll. The controller
stopped and retained the GPU lease because cleanup could not be verified. The
remote profile was detached and may still run; no completed C4 export has been
collected. The second arm, MX artifact04 and routing pairs have not started.
See [RECOVERY_20261103.md](RECOVERY_20261103.md) for exact ownership and recovery
gates. The accepted C1 results and all scientific pins remain unchanged.

Access was restored and the detached original C4 first arm completed normally.
At `23:20Z`, the reviewed collect-only recovery accepted its 122 requests with
zero errors or cancelled profile records, unchanged client/worker identities,
and matching sealed profile/spec and source/mmap hashes. No first-arm replay
occurred. Its original worker and lease remain retained for the second arm;
a stable-controller handoff is under review. This is an accepted first arm,
not a completed C4 comparison.

At `23:34:29Z`, root launched the reviewed continuation on the stable bastion
`ip-172-31-10-102`, container `kubecon-workshop-controller-20261103`. It resumed
only the second arm, preserving the original first worker and cluster-side
AIPerf client. The first worker was Ready and the new second worker was starting
at `23:34:43Z`. Subsequent control no longer depends on the laptop's API tunnel.
The local lease is fenced against old helpers while the remote controller owns
r2, MX artifact04, the routing pairs and cleanup. Local result files remain an
earlier snapshot until pulled back. C4 must disclose the network interruption,
inter-arm pause and controller-observer change; scientific model/workload
settings and first-arm execution were preserved.
