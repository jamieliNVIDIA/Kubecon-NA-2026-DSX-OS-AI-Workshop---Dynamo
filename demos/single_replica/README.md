# First deployment: one Nemotron/vLLM replica

Presenter demo for section 1.4. It reuses the pinned Super VL model, runtime,
H100 TP2 settings, DRA allocation, model-cache checks and namespace preparation
from the feature tests. One replica uses **two GPUs**. The frontend uses CPUs.
ModelExpress is enabled before launch so this server can later supply the
second replica's weights. Its first startup loads the staged checkpoint from
storage; leave it running for the ModelExpress presentation. The walkthrough ends
with two short AIPerf runs of the AgentX trace against it, at concurrency 1 and 8.

## Try the presentation without a cluster

```bash
uv run python -m demos single-replica --rehearsal
```

This creates a three-pane tmux view. The left pane presents the steps; the upper
right shows Kubernetes resources and elapsed time; the lower right shows engine
logs. Rehearsal output is explicitly simulated and makes no cluster calls.

At a step boundary, press **Enter** or **Space** to advance, **q** to stop.
Presenter commands appear first; another keypress submits the displayed command.
The request body and curl command remain on screen while you explain them, then
the response appears below them after submission.
These controls are deliberately hidden from the projected screen. Use
**Ctrl-b z** to zoom the focused pane, **Ctrl-b [** to scroll, and **Ctrl-b d**
to detach. The presenter pane clears when you advance; each step's output stays
visible until then. Resource and log panes keep running. When started inside
tmux, the script creates one new window and leaves
existing windows alone. Outside tmux it uses its own `dynamo-workshop` server.

Install tmux with your package manager if needed. The launcher also recognizes
a repository-local `.local/bin/tmux`, or `WORKSHOP_TMUX=/path/to/tmux`.
For one terminal without tmux:

```bash
uv run python -m demos single-replica --rehearsal --plain
```

`--preview` prints the projected YAML excerpt and step list without running cluster
commands. `--full-manifest` previews the full executable DGD, also without cluster
calls. `--rehearsal --plain --auto` exercises every step without keypresses.
`uv sync --locked` creates the project's `.venv` from `uv.lock`.

## Live run

For the prepared jump-host workspace, connect from your laptop:

```bash
ssh -t ubuntu@3.238.63.5
cd /home/ubuntu/dynamo-kubecon-workshop
uv sync --locked
source scripts/kubecon-jump-env.sh
python -m demos single-replica prepare
python -m demos single-replica prepare-aiperf
python -m demos single-replica
```

`prepare-aiperf` is once per host, not per run; see [AIPerf steps](#aiperf-steps-agentx).
This uses the host's existing direct cluster kubeconfig and kubectl through
workspace-local symlinks. It does not use the Mac's loopback API tunnel or
`kubecon-env.sh`. Preparation reuses the existing cluster pull secret named by
`WORKSHOP_PULL_SECRET_SOURCE=namespace/name` or saved in
`.local/pull-secret-source`; its contents are never written to command receipts.
The environment script activates the project's uv-managed `.venv`, selects its
Python interpreter, and adds the user-installed `uv` to the shell path. The
lockfile pins PyYAML 6.0.3 on both Linux and macOS.
The workspace also needs the original qualified cache receipt at
`results/20261015-super-vl-tp2/state.json`; this is a preparation input, not a new
qualification result. Preparation creates a fresh run on the host.

The demo's tmux server runs on the jump host and survives an SSH disconnect.
To reconnect, run `ssh -t ubuntu@3.238.63.5`, then
`tmux -L dynamo-workshop list-sessions` and
`tmux -L dynamo-workshop attach -t SESSION` with the printed session name.
Use **Ctrl-b d** to detach. An HTTP port forward runs on the jump host too;
the presenter's curl requests execute there.

For a Mac-local runner instead:

```bash
source scripts/kubecon-env.sh
uv run python -m demos single-replica prepare
uv run python -m demos single-replica
```

Run `prepare` offstage before opening the projected demo. Live runs refuse to
open the walkthrough until that run is prepared. Preparation output is absent
from the walkthrough, which opens directly at the deployment excerpt.
Preparation creates a fresh owned namespace, private EFS PV/PVC binding and
registry pull secret, verifies the existing exact-revision model cache, prepares
the GPU claim template and MX source-discovery Service, and validates the DGD.
Model downloading is offstage.
This first profile uses the existing workshop cluster; it assumes the operator,
GPU DRA, shared checkpoint and registry access from feature qualification.

The guided steps are:

1. Read a short DGD excerpt: one CPU frontend with its command and round-robin
   routing arguments, one vLLM worker, the model and TP2
   setting, and the worker's reference to a two-GPU DRA claim.
2. Apply it and follow the complete startup automatically. The operator's
   resources and phase timings update beside the worker logs. On readiness,
   validate the image/GPU allocation and show the startup timing summary.
3. Port-forward the frontend and check `/v1/models`.
4. Send a small coding request through the HTTP endpoint.
5. AIPerf, one agent: a 20-second slice of the AgentX trace at concurrency 1.
6. AIPerf, eight agents: the same slice at concurrency 8.

After submitting the deployment command there is no presenter pause between
Pod creation and engine readiness, or between readiness and its timing summary.
Resource monitoring and the automatic post-startup resource inspection continue
without individual submission keypresses.

The opening uses `deployment-excerpt.yaml`, derived from the executable files
with storage, image pins, MX setup and preparation details omitted. It is a teaching
excerpt, not an apply target. `deployment.yaml` and `gpu-claim-template.yaml`
remain complete and are the files used for deployment. Inspect them with `cat`
in the printed run directory, or use:

```bash
uv run python -m demos single-replica --full-manifest --run results/PRINTED-RUN
```

Projected commands use paths relative to the run directory and show `kubectl`
with the workshop configuration supplied by the runner. For manual use, first
source the environment script for your host as above, then change into the run directory.
Command receipts retain the exact executable paths and kubeconfig arguments.
The resource pane and post-startup summary show the DGD, Grove PodCliqueSet,
frontend/worker Pods, Services and GPU claim. This cluster uses Grove
PodCliqueSets and PodCliques rather than Kubernetes Deployments. The HTTP
Service exposes port 8000; the worker system Service exposes port 9090; the
headless Service provides DNS discovery. The worker's ResourceClaim shows its
two allocated GPUs. Deployments are also queried and shown if present.
Full observed objects are saved in `resources.json` for inspection.

The worker uses native model context rather than the feature smoke's 8k cap, so
the context limit remains suitable for the later AgentX workload. This intro
profile uses `--enforce-eager` to skip torch.compile and CUDA-graph capture.
It also uses `--language-model-only` for the agreed coding-agent workload.
Kernel JIT and other engine initialization can still take time. This is a
startup-oriented profile, separate from the compiled performance benchmarks.
The exact pinned vLLM implementation is documented in
[its eager-mode configuration](https://github.com/vllm-project/vllm/blob/43b4aaea3/vllm/config/vllm.py#L1746).

The explicit batching-token, prefix-caching, block-size, Mamba backend/cache-dtype,
cache-mode and compiler-cache-directory settings are omitted. vLLM supplies their
defaults. Model/revision, TP2 and the reasoning parser remain, alongside the
bounded H100 memory profile: four sequences and 85% GPU memory. Those bounds
avoid implicitly reserving a large concurrency footprint. The retained image/
video limit is inactive because `--language-model-only` disables multimodal
input. These settings are not a throughput tuning lesson.
Frontend shared memory and redundant image/working-directory settings are also
removed. Routing starts with round robin. MX loader, discovery and EFA settings
are already present in the executable manifest so the server can remain running
as the next demo's source. Explain them in that demo; KV events, offloading and
disaggregation come later.

The script remembers the last successfully prepared live run in
`.local/demo-01-current.json`. Preparation failures, previews and rehearsals do
not change that selection. To prepare before taking the stage:

```bash
uv run python -m demos single-replica prepare
uv run python -m demos single-replica
```

Use `--run results/NAME` to explicitly prepare or select a particular run.
`uv run python -m demos single-replica` resumes the selected run;
add `cleanup` to clean it up and clear the selection. After cleanup, run
`prepare` again for a fresh deployment.

The first server holds the workshop GPU reservation. The ModelExpress target
can join as a dependent of this exact source; unrelated live runs still refuse
a competing reservation. Rehearsal and preview remain available.

## AIPerf steps (AgentX)

Steps 5 and 6 show the AIPerf command and its report against the endpoint from step 3:
the same short slice of the AgentX trace at concurrency 1, then 8. The numbers are
not the point. Each run takes about 30 seconds: 20 s of load, up to 10 s for answers
still streaming, then AIPerf's console tables (Effective, Active, Usage, then LLM
Metrics with TTFT, inter-token latency, request latency, throughput and errors).
In the 58% presenter pane the metric names wrap; **Ctrl-b z** zooms the pane.

The slice uses AgentX's own recipe, `--scenario inferencex-agentx-mvp`, on the
pinned corpus (`--public-dataset semianalysis_cc_traces_weka_062126`) with four
changes that make it quick: the first 8 sessions that fit in 128K tokens, each from
its first request (`--trajectory-start-*-ratio 0`, so no warmup primers), answers
capped at 128 tokens, and 20 s instead of the scenario's 900 s minimum. That last one
needs `--unsafe-override`; AIPerf prints a "Scenario violation (override active)"
warning about the duration and stamps the result `submission_valid: false`. It is a demonstration,
not an AgentX result. The grace period is 10 s because a session waiting on its
subagents holds the phase open until the grace period ends; answers still streaming
then are left out of the report, not counted as errors.

AIPerf runs on the presenter host through the step 3 port-forward, from the pinned
AgentX source the workshop measurements used (AIPerf 0.13.0 at `e2c149ee`, dataset
revision `23f152f6`, [details](../../reports/workshop-measurements-20261030/agentx-workload/README.md)).
Stage it offstage once per host:

```bash
python -m demos single-replica prepare-aiperf
```

It needs the archive at
`results/20261030-agentx-workload-prep-000329/aiperf-agentx-pinned-source.tar.gz`
(copy it from the laptop checkout; its sha256 is checked), `uv`, and Hugging Face
access. It unpacks the source into `.local/aiperf/`, builds its locked environment,
downloads the 1.8 GB corpus and the model's tokenizer at the pinned revision, then
runs both commands against AIPerf's own mock server with networking off. That smoke
builds AIPerf's dataset cache (about 10 GB of memory for a minute) and checks that
the second run reuses it. On stage both runs then start in about 2 s with Hugging
Face offline. `.local/aiperf/staged.json` records the result; staging again after
changing the slice is required and quick once the corpus is downloaded.

If AIPerf is not staged, or the slice changed since staging, steps 5 and 6 show the
command and say they are skipped; `prepare` reminds you as well. A run that fails or
takes more than 240 s is stopped and reported, and the walkthrough continues. Each
run leaves `aiperf-c1/` and `aiperf-c8/` (AIPerf's exports and log) and a receipt
`aiperf-c1.json`/`aiperf-c8.json` with the exact command and environment in the run
directory; a resumed walkthrough uses `aiperf-c1-2/` and so on. The load lands on
the intro worker, which is also the ModelExpress source; the runs end before
ModelExpress starts.

## Timing and lifecycle

Each step prints its command/output. Only the startup step displays wall times;
the deployment excerpt, model discovery and inference steps have no timing footer.
The resource pane shows
Pod startup, runtime setup, worker/TP setup, model construction, weight loading,
weight finalization, engine initialization and readiness with running phase timers.
The main pane refreshes the same table on every observation, including when no
new log lines or phase transitions arrive. It updates in place in a terminal;
captured output retains snapshots. A transport outage freezes the last observed
timers and explicitly marks them stale.
Pod startup uses the worker container's Kubernetes start timestamp. Runtime
setup ends at the vLLM engine configuration marker; worker/TP setup ends when
the model loader starts. Model setup then covers construction and kernel
selection up to checkpoint prefetch or the safetensors shard progress marker.
Weight loading uses the logged weight-load duration when present, followed by
the interval to the last model-load completion. Background checkpoint prefetch
overlaps weight loading. With ModelExpress, the total model-loading row uses
the slowest rank's logged duration. The detailed rows recognize InstantTensor
storage loading and peer-receive completion. Peer loading spans the first
receive through the last rank's completion; the nested peer-copy duration is
the slowest rank's reported copy time. These intervals overlap and must not be
added together. Missing separate timings display as `not timed`, rather than
implying that model construction or loading was skipped.
Engine phases use timestamped log markers and completed logged durations.
The indented warmup window spans the first explicit Mamba/router/FlashInfer
warmup marker through engine-init completion. It overlaps engine profiling and
KV-cache setup; it is a log-marker window, not a standalone logged duration.
The summary shows that window when vLLM omits a standalone warmup duration.
Running durations are elapsed time from the displayed phase's marker; completed
engine durations use the slowest logged rank. Unlogged boundaries stay unmeasured.
Total startup freezes at the Pods' Ready transition instead of counting time
spent presenting afterwards. `timing.json` is written immediately after startup,
before model discovery or the user request. Those later timestamps remain in
`demo.json` and are not part of the displayed startup summary.
TP-rank timings overlap: report the slowest rank and never sum nested phases.
Missing phase logs are reported as `not timed`. No throughput claim follows from
the small inference request.

Run files include the effective DGD, request/response, command receipts, Ready
Pods and image/GPU evidence, worker logs, and timings. The model/image pins and
source template remain intact. Credentials and raw evidence stay ignored.

The service **stays running** for the baseline load demo and as the
[ModelExpress demo's](../modelexpress/README.md) weight source. Its recorded
storage startup supplies that demo's first-server comparison; no extra storage
baseline is launched. The port forward stops when the presenter runner exits.
The GPU reservation remains until explicit cleanup. When both presentations are
finished, remove the dependent target first:

```bash
uv run python -m demos modelexpress cleanup
uv run python -m demos single-replica cleanup
```

Single-replica cleanup refuses while a dependent ModelExpress target remains.
It deletes only this run's graph, verifies its Pods and GPU claims are gone,
then releases its lease. It retains the namespace and checkpoint storage. Closing
tmux or stopping the presenter does not delete the service. To remove a demo's
tmux view, inspect its `tmux.json` and kill that session/window only.

## Live recording

The earlier native-loader text-only eager runner passed real-cluster execution on November 4
UTC. The [preferred main-panel recording](../transcripts/live/01-single-replica/20261104-a2/main.txt)
includes the corrected live phase timers, model discovery and expected coding
response. Its worker reached Ready about 461s after submission; this is one
staged-EFS startup, not a latency distribution. Raw terminal bytes and immutable
source/evidence copies are retained privately alongside the shareable text.
That earlier recording predates the compact YAML, command display and resource
tables. The [compact projection recording](../transcripts/live/01-single-replica/20261105-overnight-a2/main.txt)
now passes actual model discovery and coding inference after resuming the
original worker on November 5 Pacific. Its independent qualification verifies
the original Pod/claim UIDs, exact GPU pair and returned `add` function. The
presenter did not reapply the graph. That run reached Kubernetes Ready about
1,459s after its original submission while other startup tests shared EFS; the
morning observed-readiness clock includes the overnight transport outage.
It is a resumed functionality/projection recording, not a new uninterrupted
startup measurement. Both recordings and the failed transport attempt remain
available as historical evidence. They predate the MX-enabled intro profile;
the revised first-server-to-peer transition passed its live qualification on
November 7 UTC (see the [ModelExpress guide](../modelexpress/README.md#live-qualification)).

If interrupted, rerun the launcher to inspect and continue the selected
deployment (or use `--run` to select another prepared run); its original startup timestamp is retained. After cleanup use a new
run directory for a new startup. A changed demo profile also requires a fresh
run; old runs can still be cleaned up. Change `--port` if loopback port 18000 is busy.

## Next iteration

Use this presenter flow to choose which deployment details belong in the
attendee-facing manifest and which remain cluster preparation. The take-home
version can follow the same steps with a public runtime and a portable storage/GPU
profile once those configurations are qualified.

## Validation

- November 9 UTC, AIPerf steps: 12 offline checks cover the shared slice, offline
  execution, receipts, skips, timeouts, interrupts, staging refusals, archive
  unpacking and capture evidence. On the laptop, `prepare-aiperf` and both live
  steps ran against AIPerf's mock server, with the local corpus copy standing in for
  the Hugging Face download: about 3 min to stage and ~10 GB peak while building the
  cache, then 26 s (C1, 3 requests) and 32 s (C8, 22 requests) in a terminal sized
  like the presenter pane. On the jumpbox, `prepare-aiperf` took 3 min with the real
  Hugging Face corpus (smoke: C1 3 requests in 70 s while building the cache, C8 51
  requests in 35 s). Step 5 then ran on a copy of the prepared intro run
  `demo-01-20261109T010551293587Z` against the mock server: exit 0, 3 requests, no
  errors, the run itself unchanged. Neither step has run against the real intro
  worker yet.
- November 4 projection update: the YAML excerpt is 35 lines; the complete
  opening screen is 45 lines with a maximum width of 66 characters in the
  recorded rehearsal. Full manifests remain executable and separate. Shortened
  display commands preserve the actual execution arguments in receipts.
- The update passed 57 checks across the intro, MX, P/D/Snapshot, request-continuity
  and capture suites, plus a full offline rehearsal/capture. Resource rendering
  was also checked against retained real Kubernetes objects. The new presentation
  now has the resumed live recording above; the earlier uninterrupted recording
  remains intact.
- Automated checks cover hidden keypress gates, duplicate presenters, foreign
  GPU leases, readiness, simplified model/runtime settings, live phase timing,
  summary-before-request ordering, offline execution, and read-only observers.
- Actual tmux rehearsals passed both standalone and inside an existing session.
  The standalone layout was driven through its steps with Space; the
  nested case preserved the original window/process and session settings.
- The simplified DGD and GPU claim template passed a server-side dry-run in an existing
  feature-test namespace. This created no resources or GPU allocations.
- The November 4 recording validates the earlier native-loader deployment.
  The MX-enabled intro requires a fresh run; an existing native-loader server
  is never restarted or converted automatically.
