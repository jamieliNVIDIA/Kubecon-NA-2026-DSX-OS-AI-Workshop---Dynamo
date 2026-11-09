# Synthetic scale-out and routing comparison

**Complete: see [RESULTS.md](RESULTS.md).** a3 ran November 8, 2026,
06:22–08:02 UTC (November 7, 22:22 – November 8, 00:02 Pacific). Controller
`kubecon-workshop-synthetic-scaleout-20261107-a3` ran detached on the jumphost
from a fresh workspace; run `results/workshop-synthetic-scaleout-20261107-a3`,
namespace `dynamo-ft-synthetic-scaleout-20261107-a3`. The harness is
[`campaign.py`](campaign.py), [`controller.py`](controller.py),
[`analyze.py`](analyze.py) and [`collect.py`](collect.py). See
[STATUS.md](STATUS.md) for every attempt.

a2 (03:20–04:55 UTC) completed one worker at 32, 64 and 128 agents cleanly.
Worker 2 then stayed Unschedulable: the two-worker template spreads workers
across hosts with `podAntiAffinity`, and both workers here share cp-0942. a3
removes that rule and is otherwise identical, with byte-identical profiles and
seeds. It reruns 1W-64 as a bridge to a2's phase A, then runs the two-worker cells.

a1 (02:35–03:13 UTC) is a pilot, stopped on purpose after 1W-64. With variable
session lengths, the pinned AIPerf user-centric scheduler gave virtually aged
users the dataset's average remaining turns. Users holding shorter conversations
raised `ValueError` every turn: 4 of 32 users idle for up to about 330 s in 1W-32.
a2 fixes sessions at 12 turns and replaces the adaptive rule with a fixed matrix.
a1's cleanup receipt verified no workers, claims or graph. Its evidence is in
`results/workshop-synthetic-scaleout-a1-pilot-collection-20261108`, and its failed
first launch receipt sits beside its prep directory.

## Question

The accepted AgentX cells answer only half of "why didn't more capacity help?"
in tokens per second. At [C16](../../overnight-2026-11-04/routing-sweep/C16-RESULTS.md)
one worker averaged 1.6 running requests with nothing waiting: a second worker
raised mean decode speed per user 18.6% but not throughput, so TPS/GPU halved.
The saturated one-worker baseline failed in [C32](../../overnight-2026-11-04/routing-c32/C32-RESULTS.md)
warmup when a queued health canary failed liveness. This campaign measures:

1. One versus two workers at the same number of agents, with one worker past
   its knee.
2. One worker with N agents versus two with 2N: does a second worker double the
   agents served at the same per-user speed?
3. Round-robin versus KV routing on two workers, in TPS/GPU and TPS/user as
   well as TTFT, at a load where throughput is capacity-bound.

This replaces the planned three-cell AgentX C32 rerun (about 2.5 h for three
points) with a cheaper synthetic campaign. AgentX C16/C32 results stand as
they are.

## Workload: synthetic, not AgentX

AIPerf synthetic multi-turn sessions in user-centric mode. Label every result
"synthetic coding-agent-shaped load" and never present it as AgentX. Prefix
layers follow AIPerf's agentic-code generator defaults; size and output length
follow the realized AgentX statistics:

| Setting | Value | Basis |
| --- | --- | --- |
| Shared system prompt, all users | 32,000 tokens | agentic-code global L1 prefix |
| Per-user context, cold on a user's first turn | 24,000 tokens | session repository context |
| New input per turn | mean 4,000, sd 1,500 tokens | tool output plus instruction |
| Output per turn | 650 tokens, forced | AgentX realized mean about 670 |
| Turns per session | exactly 12 | context about 60K at turn 0 to 111K at turn 11, mean about 86K; fixed because variable lengths break the pinned user-centric scheduler (see a1) |
| Per-user turn gap | 45 s, so offered QPS = N / 45 | AgentX demand of about 11–16 output tok/s per tree |

Expected single-worker prompt reuse is about 90–95% (AgentX C16 one worker:
93.9%). Record the realized shape; do not retune it after the first measured
cell.

User-centric mode keeps at most one request in flight per user. Overload
lengthens turns and lowers the achieved rate instead of growing an unbounded
engine queue. AIPerf sends a stable session ID in `X-Correlation-ID` and
`X-Session-Affinity`; no router session-affinity flag is set, and the RR
acceptance check below confirms round-robin stays non-sticky.

AIPerf is pinned at `e2c149ee29d3`, the AgentX client build, without the AgentX
corpus or dataset patch. Per cell, in CLI form (the harness seals it as AIPerf
YAML, as the AgentX cells did):

```bash
aiperf profile \
  --model nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4 \
  --tokenizer nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4 \
  --tokenizer-revision 8a115b9d966adce8c059a7bcf47f49a1e57957d8 \
  --url http://FRONTEND:8000 --endpoint-type chat --streaming \
  --use-server-token-count \
  --user-centric-rate QPS --num-users N --concurrency N \
  --shared-system-prompt-length 32000 --user-context-prompt-length 24000 \
  --synthetic-input-tokens-mean 4000 --synthetic-input-tokens-stddev 1500 \
  --osl 650 --prompt-corpus coding \
  --extra-inputs '{"ignore_eos": true, "chat_template_kwargs": {"enable_thinking": false}}' \
  --session-turns-mean 12 --session-turns-stddev 4 \
  --num-dataset-entries 1000 --random-seed SEED \
  --benchmark-duration 540 --benchmark-grace-period 300 --slice-duration 30 \
  --export-level records --server-metrics WORKER_METRICS_URLS \
  --output-artifact-dir CELL/artifacts
```

[`profiles.py`](profiles.py) renders these flags into each cell's YAML with the
pinned AIPerf archive itself and plans every profile offline. `SEED` is
20261107 plus the cell's position in the profile list, so user contexts never
repeat across cells. The coding corpus generates code, shell output, JSON,
tracebacks and diffs instead of prose. The pinned runtime reads root-level
`ignore_eos` (`CommonExt`), and the startup smoke test checks it. Thinking is
off so history accumulates plain content. AIPerf's 6 h request timeout stays,
and the 300 s grace lets overload cells drain in-flight turns rather than cancel
them; the analysis window still ends at 540 s. Offline, the pinned AIPerf
generated the 1,000-session dataset in about 10 s.

## Serving configuration

Identical to the accepted C16/C32 routing cells except the health policy:

- Super VL revision `8a115b9d`, the C32 runtime digest, TP2 per worker on H100,
  compiled text-only (`--language-model-only`), native 1,048,576 context,
  `--max-num-seqs 128`, 8,192 batched tokens, memory fraction 0.85, prefix
  caching, and KV-event publication on every worker in every cell.
- **Health, all cells:** drop `DYN_CANARY_WAIT_TIME=1` (the MX fast-startup
  setting in [`generated()`](../rr-kv/campaign.py)) and the template's
  `DYN_HEALTH_CHECK_REQUEST_TIMEOUT=180`; set `DYN_HEALTH_CHECK_ENABLED=false`.
  The pinned runtime defaults canaries off, but the operator appears to inject
  `true`: no DGD here sets it, yet [`upgrade_retests.py`](../../../scripts/upgrade_retests.py)
  asserts it on live worker Pods. Verify the rendered Pod env and the worker's startup config
  line (`health_check_enabled=false`). An env value in the DGD alone is not
  proof. Keep the startup and readiness probes and the operator's liveness probe.
  User decision, November 7: the 1 s canary was a startup optimization and does
  not belong in a load test.
- **Placement:** GPU0/2/4/6 on cp-0942, with frontends and the CPU client on the
  same node. The live presenter demos hold cp-0124 gpu-1/3 and cp-0198 gpu-0/2,
  including the earlier routing pair, so both workers share cp-0942. Each
  worker's claim takes any two of the four UUIDs; worker 1 keeps its pair
  through the scale-up.
- **Two frontends, one worker pool:** `Frontend` with `--router-mode round-robin`
  and `FrontendKV` with `--router-mode kv`, in the same DGD with default router
  weights. Each cell drives exactly one, which removes per-cell redeployments.
  If the operator rejects a second frontend, patch one frontend's router mode
  between cells instead (about one minute per switch).

## Cells and order

N is the number of simulated agents. While a topology keeps up, its total
throughput equals the offered demand whatever the worker count or routing,
which is why the C16 cells showed no throughput change. In the a1 pilot one
worker still kept pace at 64 agents, but per-user speed fell from 85 to 29 tok/s
(ITL 11 to 37 ms). A request-rate rule would therefore have skipped the
64-agent two-worker cell, the clearest TPS/user comparison. a2 runs a fixed
doubling matrix instead, with 128 agents to take one worker past its limit.

| Phase | Cell | Workers / GPUs | Frontend | N | Offered output tok/s | Role |
| --- | --- | ---: | --- | ---: | ---: | --- |
| A | 1W-32 | 1 / 2 | RR | 32 | 462 | One worker, comfortable |
| A | 1W-64 | 1 / 2 | RR | 64 | 924 | One worker keeping pace at low per-user speed |
| A | 1W-128 | 1 / 2 | RR | 128 | 1,849 | One worker past its limit |
| | Scale `replicas: 1 → 2`; record second-worker startup | | | | | |
| B | 2KV-64 | 2 / 4 | KV | 64 | 924 | Same agents as 1W-64; twice those of 1W-32 |
| B | 2RR-64 | 2 / 4 | RR | 64 | 924 | Routing at a load two workers keep up with |
| B | 2RR-128 | 2 / 4 | RR | 128 | 1,849 | Routing cost near two workers' limit |
| B | 2KV-128 | 2 / 4 | KV | 128 | 1,849 | Same agents as 1W-128; twice those of 1W-64 |
| B | 2KV-32 | 2 / 4 | KV | 32 | 462 | Calibration against AgentX two-worker KV C32 |

The comparisons:

- **Same agents, twice the GPUs:** 1W-64 versus 2KV-64 for per-user speed
  where one worker still keeps pace; 1W-128 versus 2KV-128 for throughput once
  it cannot.
- **Twice the agents on twice the GPUs:** 1W-32 versus 2KV-64, and 1W-64
  versus 2KV-128. KV routing should keep TPS/GPU and TPS/user close to one
  worker serving half the agents.
- **Routing:** 2RR versus 2KV at 64 and 128 agents, in TPS/GPU and TPS/user as
  well as TTFT.

A fresh seed per cell controls cache history. RR and KV alternate (KV, RR, RR,
KV) to spread drift. 2KV-32 runs last; it is sized roughly like AgentX
two-worker KV C32, which delivered 525 output tok/s. Say so on any slide where
synthetic and AgentX numbers disagree.

## Analysis

Each profile runs 540 s. Analyze the 180–540 s slices (360 s): at 64 agents one
worker needs a minute or more to prefill every user's first turn, and those
cold turns must fall outside the window. Report AIPerf's whole-run summary
separately. Per cell:

- Output tok/s over the window, per GPU; `output_token_throughput_per_user`
  mean, p50 and p10; achieved versus offered request rate (N / 45).
- TTFT p50/p90/p99 and ITL p50/p90. p90 is the main tail statistic.
- vLLM prefix-cache reuse, recomputed prompt tokens, summed engine queue time,
  running and waiting requests per worker, KV usage, preemptions and GPU
  utilization, as in the C16/C32 pressure series.

A cell is past its knee when its achieved request rate is below 90% of offered,
or its TTFT p90 is more than twice the same topology's lowest-N value. Use the
same window and denominators for every cell.

## Acceptance

- Zero worker restarts, no readiness transitions and zero request errors.
- Realized output mean within 5% of 650 tokens.
- RR cells: per-worker request split within 50 ± 10%, and lower prompt reuse
  than the matching KV cell.
- KV cells: positive predicted prefix overlap in router metrics.
- Integrity manifest over each cell's artifacts, as in C16/C32.

Overload is the point of 1W-64 and the 128-agent cells: high TTFT and blocked
users are results, not failures. As in C32, request errors, cancellations or an
unforced output length mark a cell as a stress observation instead of stopping
the campaign. A worker restart, a failed AIPerf process, an incomplete export
or an infrastructure failure stops it, and the graph is deleted either way.

## Cost

About 13 minutes per cell (2 for client and dataset preparation, 9 profiling,
1 to drain, 1 collection), plus about 25 minutes for the first deployment, the
scale-up and the smoke test. Overload cells can drain for up to 5 minutes. The
eight cells take about 2 h on four H100s (two during phase A). a2 should end
around 05:20 UTC (21:20 Pacific).

## Before launch

Preparation:

1. Derive `campaign.py` from [`routing-c32/campaign.py`](../../overnight-2026-11-04/routing-c32/campaign.py):
   health env, second frontend, deploy once then scale, synthetic profile
   sealing and windowed analysis.
2. Validate a sealed profile with the pinned AIPerf (`aiperf config validate`
   and `aiperf profile --dry-run`), in a scratch environment or the client Pod,
   and time dataset generation.
3. Render the manifests and diff them against the accepted C32 KV deployment.
   Expected differences: health env, second frontend and replica count.
4. Freeze inputs and write `spec.json` with hashes.

At the jumphost:

5. Read-only inventory: nodes, live DRA allocations for the four UUIDs, other
   workstreams' leases, and absence of the campaign namespace.
6. Server-side dry-run of the DGD. Deploy one worker and smoke-test it: model
   listed on both frontends, four bounded requests, realized output length, and
   canaries off in the rendered Pod and the startup log.
7. Phase A, scale-up, phase B; collect; scoped cleanup; release the lease.
