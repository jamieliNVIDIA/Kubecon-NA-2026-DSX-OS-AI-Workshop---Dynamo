# AgentX workload for the workshop measurements

Prepared October 30, 2026. CPU-only preparation is complete; this page contains
no GPU benchmark results. The round-robin and MX agents execute the hardware
workstreams under the campaign's exclusive GPU lease.

The [CPU resource addendum](RESOURCE_REQUIREMENTS.md) documents eager full-corpus
preparation, serial-worker settings, shared memory and disk limits, and a helper
that qualifies the real mmap/cache pipeline before reserving GPUs.
The [parallel-branch check](BRANCH_PREFIX_FINDINGS.md) records exact shared-prefix
and scheduling evidence, including named subagents with a 72k-token common
prefix, plus the limits of interpreting that as full parent-context inheritance.

## Exact source and corpus

- AIPerf package version: `0.13.0`.
- Source commit: `e2c149ee29d3b64798d8ba2176e9f42e0aa89280`.
- Built-in scenario: `--scenario inferencex-agentx-mvp`.
- Dataset alias: `semianalysis_cc_traces_weka_062126`.
- Hugging Face repository: `semianalysisai/cc-traces-weka-062126`.
- Dataset revision: `23f152f6f0f9399a85901b89a6458def0ef16729`.
- Raw corpus: `traces.jsonl`, 1,847,151,435 bytes.
- Verified LFS/content SHA256:
  `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
- The CDN ETag `3d0b21d711dff6436460ee48d0236ad13d9e836413fc09aa269b332c2aa0cff8`
  is the Xet hash, not the content SHA256. The repository tree metadata and
  downloaded file agree on the content hash above.

The original AIPerf checkout contains unrelated staged DAG changes. Preparation
therefore used `git archive` of committed HEAD, with one transparent additional
line setting the Weka public loader's existing `hf_revision` attribute. This pins
the public dataset download without changing reconstruction or scheduling rules.
The patch is [aiperf-dataset-revision.patch](aiperf-dataset-revision.patch).

The portable archive and exact paths/hashes are in
[source-location.json](source-location.json). The dataset-pinned archive is:

```text
results/20261030-agentx-workload-prep-000329/aiperf-agentx-pinned-source.tar.gz
SHA256: 4e7f3a2ed15276a5252200e4d4772bf4d10e182edf2cbff4a9606794822d4699
```

Raw corpus bytes and the full source snapshot stay in ignored `results/`.
`prepare_corpus.py` downloads the exact dataset revision, validates its size and
content hash, and produces the recorded-length summary. It never truncates or
rewrites the trace.

## What is replayed

The source traces were recorded from real Claude Code sessions. They contain
request timing, input/output lengths, prefix-cache hash identities, and parent
and subagent structure. AIPerf reconstructs coding-text request payloads with the
recorded cache structure and lengths; it does not execute the original tools or
measure coding-task quality. This is a trace-driven serving workload, not a
generic single-turn synthetic workload and not a live coding-agent evaluation.

Corpus scanning verified:

| Quantity | Value |
| --- | ---: |
| Root traces | 393 |
| Main requests | 56,798 |
| Subagent groups | 1,697 |
| Child requests | 42,029 |
| Total model requests | 98,827 |
| Maximum recorded input length | 989,824 |
| Maximum recorded output length | 59,903 |
| Maximum recorded input + output | 996,579 |

Lengths are the corpus's recorded proxy-tokenizer counts. The served model's
tokenizer reconstructs the actual payload; preserve headroom and inspect actual
server token counts. Full machine-readable statistics are in
[corpus-summary.json](corpus-summary.json).

| Context limit | Eligible whole root trajectories |
| --- | ---: |
| 8,192 | 0 |
| 32,768 | 0 |
| 131,072 | 82 |
| 262,144 | 220 |
| 1,048,576 | 393 |

The saved feature-test server's `--max-model-len 8192` is unsuitable. The execution
agent is preparing a separate native-context configuration on the unchanged
Super VL model/revision, runtime, H100 hardware, and TP2 topology. Do not truncate
prompts, cap output lengths, or silently select a smaller trace pool to fit. A
constrained-context investigation, if necessary, needs an explicit new spec and
clear labeling independent of the scenario's software-validity stamp.

## Fixed initial comparison

The primary pilot compares one versus two TP2 workers at each of C=1 and C=4.
Only replica count changes within a pair. Each arm has one 900-second profiling
phase; repetitions or additional load points are separately frozen extensions.
This initial matrix is a paired pilot, not a confidence-interval study.

- `--concurrency` counts live session trees, including descendant lifetimes.
  Fan-out can create more simultaneous HTTP requests than the configured C.
- Equal C is equal offered agent concurrency and replay rules, not fixed RPS.
  Faster serving can recycle more trajectories within the fixed duration.
- Seed `20261030` fixes reconstruction and sampling/start-position choices.
- Retain all eligible traces, sequential sampling, recorded delays, and recorded
  output lengths. No request-count stop, output cap, burst-start, fixed-rate,
  per-turn delay cap, or ignore-delay override is included.
- Trajectory start ratios are explicitly `0.0` and `1.0`.
- The scenario preserves per-turn dependencies and idle gaps, with its global
  10-second system-idle guard.

### Cache isolation across arms

`first_turn_prefix` cache busting uses a tree-wide marker derived from
`benchmark_id`, recycle pass, lane, and base trace ID. Root and children share it,
and a continuing tree retains it through warmup into profiling.

The normal CLI creates a fresh UUID-derived benchmark ID independently of the
random seed. Separate CLI invocations therefore have different full-prefix
namespaces even with the same seed. Do not manually force the same benchmark ID
across arms. The marker prevents full conversation-prefix reuse from an earlier
arm; equivalent cache occupancy/eviction preconditions still need consideration.

For the requested round-robin baseline, disable session-affinity injection:

```bash
export AIPERF_HTTP_X_DYNAMO_SESSION_ID_FROM_CORRELATION_ID=0
export AIPERF_HTTP_X_SMG_ROUTING_KEY_FROM_CORRELATION_ID=0
export AIPERF_HTTP_X_SESSION_ID_FROM_CORRELATION_ID=0
```

Server-side routing must independently be explicit round-robin, without sticky
affinity. The AIPerf model-selection flag is not a server-worker routing policy.

## Profiles, bounds, and installation

[profile-c1.yaml](profile-c1.yaml) and [profile-c4.yaml](profile-c4.yaml) are
validated templates. The execution agent must replace endpoint/artifact paths
and freeze per-arm copies before execution. They have passed the frozen source's
YAML validation and DatasetResolver -> ScenarioResolver -> TimingResolver with no
scenario violations; this is configuration validation, not a serving result.

| Setting | Frozen template value |
| --- | --- |
| Endpoint | OpenAI chat, streaming |
| Model/tokenizer | Super VL; tokenizer revision matches the serving-model pin |
| Corpus | Full date-pinned 062126 corpus at the exact HF revision above |
| Context filter | 1,048,576; all 393 recorded trajectories eligible |
| Profiling | 900 seconds, the scenario's minimum valid duration |
| Request timeout | 1,800 seconds |
| Snapshot-primer warmup grace | 1,800 seconds |
| Profiling drain | 300 seconds |
| Extra generation input | `ignore_eos: true` |
| Token counts | Server usage counts |
| Local GPU telemetry | Disabled because the load generator is CPU-only |

The native CLI defaults are a six-hour per-request timeout, an unbounded
snapshot-primer warmup wait, and a 30-second profiling drain. The explicit bounds
above make this initial pilot finite; preserve incomplete/failed records and
check validity/metric coverage rather than hiding cancellation. Optional
cache-pressure warmup is unset; mandatory per-stream snapshot primers still run,
with one output token each.

Unpack the source archive into an owned CPU load-generator directory, then use
its lockfile in an isolated environment:

```bash
uv sync --project "$AGENTX_SOURCE" --frozen --no-dev --no-editable --python python3
"$AGENTX_SOURCE/.venv/bin/python" -m aiperf config validate "$AGENTX_PROFILE"
"$AGENTX_SOURCE/.venv/bin/python" -m aiperf profile --config "$AGENTX_PROFILE"
```

Record Python version and `uv pip freeze --python "$AGENTX_SOURCE/.venv/bin/python"`
after installation. Set Hugging Face, AIPerf, and temporary cache locations to
owned storage appropriate for the load generator. Keep the profile and data
semantics identical across a replica-count pair.

The templates use the current chat endpoint's default `max_completion_tokens`.
During endpoint preflight, verify a small bounded response actually honors that
field and returns token usage. If the pinned Dynamo frontend requires legacy
`max_tokens`, resolve that once, consistently for both arms, before locking the
measurement specs. Do not change the field halfway through a comparison.

The equivalent explicit CLI for C=1 is:

```bash
aiperf profile \
  --scenario inferencex-agentx-mvp \
  --url "$AGENTX_ENDPOINT" \
  --model nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4 \
  --tokenizer nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4 \
  --tokenizer-revision 8a115b9d966adce8c059a7bcf47f49a1e57957d8 \
  --endpoint-type chat --streaming --use-server-token-count \
  --public-dataset semianalysis_cc_traces_weka_062126 \
  --max-context-length 1048576 --concurrency 1 \
  --extra-inputs ignore_eos:true --cache-bust first_turn_prefix \
  --system-idle-gap-cap-seconds 10 \
  --trajectory-start-min-ratio 0.0 --trajectory-start-max-ratio 1.0 \
  --benchmark-duration 900 --benchmark-grace-period 300 \
  --request-timeout-seconds 1800 --agentic-warmup-grace-period 1800 \
  --random-seed 20261030 --no-gpu-telemetry --ui none \
  --artifact-dir "$AGENTX_ARTIFACT_DIR"
```

A 60-second diagnostic run needs a separate spec and `--unsafe-override`; it is
an AgentX-style smoke and must not be reported as a valid full AgentX result.

## Metrics and acceptance evidence

- Check scenario validity, context overflows, errors, cancellations, and partial
  or completed session trees. The scenario enforces at least 95% profiling metric
  coverage; a valid configuration does not guarantee a valid completed run.
- Report TTFT, ITL, request latency distributions, aggregate output throughput,
  request counts, and session/branch outcomes.
- `output_token_throughput_per_user` is `1 / ITL`: decode-only speed.
- `e2e_normalized_interactivity_p90` and `_p75` invert the corresponding
  percentile of request latency per output token, including first-token wait.
  They are the named AgentX interactivity convention, not fast-tail percentiles
  of token rates.
- Preserve per-request ISL/OSL and trajectory metadata: closed-loop arms may
  complete different request mixes over the same wall-clock interval.
- Gather actual worker selection and cache reuse from response metadata and/or
  server metrics. An absent client `cached_tokens` field is not a zero cache-hit
  observation; vLLM gates token-detail reporting behind its own configuration.
- CPU source preparation has used no GPU execution lease and changed no cluster
  resources. No benchmark outcome is claimed here.

## Primary source pointers

All paths below are relative to the frozen AIPerf source tree:

- `docs/tutorials/agentx-mvp.md`: scenario CLI, locks, warmup, and tree concurrency.
- `docs/tutorials/weka-trace.md`: trace reconstruction and cache semantics.
- `src/aiperf/common/scenario/inferencex_agentx_mvp.py`: invariant specification.
- `src/aiperf/dataset/loader/semianalysis_cc_traces_weka.py`: public loader and
  filter-then-cap selection.
- `src/aiperf/dataset/loader/base_hf_dataset.py`: explicit revision support.
- `src/aiperf/timing/strategies/cache_bust.py`: marker identity and tree ledger.
- `src/aiperf/cli_runner/__init__.py`: fresh benchmark-ID construction.
- `src/aiperf/endpoints/openai_chat.py`: token-budget field selection.
- `docs/metrics-reference.md`: interactivity and cache metric definitions.
