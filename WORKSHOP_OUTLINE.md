# Dynamo KubeCon workshop: working outline

Last updated: November 4, 2026.

This is the working planning document for the workshop. Sections 1, 2, and 3
have working content outlines. The detailed KVCR demonstration is deferred,
and the scaling close retains slide placeholders. Resiliency now includes
source-based Shadow Engine and Snapshot narratives within the agreed timing.
The outline describes intended coverage, not qualification of the demonstrations.

## Purpose and audience

The workshop should drive adoption of Dynamo by showing production inference
problems that experienced Kubernetes operators may not have encountered yet,
then investigating how Dynamo addresses them.

- Audience: solid Kubernetes and distributed systems foundations, surface-level
  familiarity with inference engines such as vLLM.
- Morning format: presenter-led investigation. Attendees will not have individual
  clusters or access to the demonstration cluster.
- Take-home goal: deploy a Dynamo-managed service and reproduce the investigations
  in an appropriate environment.
- Motivating application: coding agents. Use controlled, repeatable traffic for
  the serving experiments.

## Working time budget

Budget for three hours, assuming the preceding NVKE material takes 30 minutes.
If it takes 25 minutes, retain the extra five minutes as breathing room.

| Block | Minutes |
| --- | ---: |
| NVKE introduction, delivered by others | 30 |
| 1. Inference fundamentals and baseline service | 20 |
| 2. Scaling | 55 |
| Short break | 5 |
| 3. Resiliency | 55 |
| Take-home walkthrough and final questions | 10 |
| Overruns and transitions | 5 |
| **Total** | **180** |

## Decisions that apply throughout

- Keep the coding-agent workload constant across the workshop. Change offered
  load, serving configuration, and injected failures; do not change the workload
  mix to manufacture a reason for disaggregation.
- Target Super VL throughout. Other workstreams are pursuing the required
  upstream fixes; the final runtime and integration cutoff may happen late.
- Use Super VL in text-only mode for this coding-agent workload; multimodal
  input support is outside the workshop. `--language-model-only` with matching
  ModelExpress source/artifacts is now qualified in the pinned benchmark image.
  Keep earlier multimodal and later text-only startup comparisons labeled with
  their actual configurations; remeasure matched loading paths for the final demo.
- Introduce metrics in section 1 and use them throughout. Observability does not
  need its own section.
- Scale manually. Include at most one overview slide on automated scaling;
  there is no Planner demonstration.
- Introduce ModelExpress in scaling. Introduce Snapshot only in resiliency.
- Introduce KVCR through scaling and revisit its recovery role if qualified.
- Present MX, Snapshot, and GMS/Shadow Engine separately. Push to demonstrate
  their integration, and present the remaining integration as vision/slides.
- Distinguish production readiness, preview/experimental features, demonstrated
  configurations, work in progress, and integration vision. A working component
  does not establish that every composition is supported or qualified.
- After introducing disaggregation, explicitly return to aggregated serving for
  the resiliency experiments to make the mechanisms easier to follow.

## 1. Inference fundamentals and baseline service — 20 minutes

Introduce only the concepts required to understand the later experiments. Begin
with vLLM as the server; introduce Dynamo after establishing prefix reuse and
its operational implications.

| Part | Minutes | Format |
| --- | ---: | --- |
| Coding-agent loop and growing context | 3 | Simplified visual explanation |
| Inside vLLM: HTTP, processing phases, and state | 4 | Progressive zoom into the server |
| Prefix reuse and the implications of retained state | 3 | Visual explanation; no separate live reuse experiment |
| Barebones DGD, operator reconciliation, resources, and startup | 6 | Manifest walkthrough and deployment demonstration |
| AIPerf baseline and metrics | 4 | Controlled load and interpretation of results |
| **Total** | **20** | |

### 1.1 Start with the coding agent

Treat the LLM server as a black box behind an HTTP endpoint.

1. A program takes code and a user request and sends them to the server.
2. The server returns a response, which may request a tool call.
3. The program executes the tool and obtains more text, such as file contents,
   test output, or an error message.
4. The program sends the accumulated context back: original code and request,
   prior responses, tool results, and any new instruction.
5. Repeat until the task is complete.

Make clear that one agent session consists of multiple inference requests.
Keep this intentionally simplified; agent frameworks and context-management
strategies are outside this introduction.

### 1.2 Zoom into the vLLM server

Introduce the HTTP endpoint, the inference engine, and the GPUs. Keep Dynamo out
of this explanation initially.

- **Model weights:** model parameters that must be available in memory for
  inference. They are shared across requests and do not depend on the particular
  request being served.
- **Request working state / KV cache:** state associated with processing the
  context and generating an answer. Prefill processes the input and builds this
  state; generation uses and updates it.
- **Initialized engine state:** briefly acknowledge startup work beyond loading
  weights, such as compilation and warm-up. Return to its operational importance
  in the startup and recovery experiments.
- **Prefill versus decode:** enough distinction to interpret prompt-processing
  time and generation speed later.

Add a simple GPU-memory illustration: model weights, engine buffers/workspace,
and the cache pool share a finite memory budget. Explain that cache occupies
real memory and that an engine can serve multiple active requests from different
users at once. Develop the concurrency/performance tradeoff in the scaling
opener rather than expanding this into a scheduling lesson.

Do not teach attention mathematics, KV tensor layouts, or differences between
attention KV caches and recurrent/Mamba state. Use the working-state abstraction
needed for the workshop.

### 1.3 Explain prefix reuse visually

Show successive requests with the repeated prefix highlighted and newly appended
content distinguished:

```text
Request 1: [code + user task]
Request 2: [code + user task] [assistant/tool-call response] [tool result] [next instruction]
           <shared prefix>   <new context>
```

Explain that the server can retain computation associated with a matching prefix
and reuse it on subsequent requests, reducing repeated prompt-processing work.
This does not inherently accelerate the generation of each new token.

Emphasize the operational consequence: inference servers retain valuable state,
so the cost of a request depends on which server receives it and what that server
already has cached. This motivates routing and cross-worker reuse later.

**Essential caveat:** cached state is derived from the context. In this simplified
model it can be recomputed if lost, but doing so is expensive. The agent still
sends the context needed for the request; its conversation history is distinct
from the server's cached computation. Cache loss therefore affects compute cost,
latency, and available capacity, even when the request can still be served.

Introduce **capacity and eviction** here: the GPU cannot retain every previously
computed prefix indefinitely. An engine may evict reusable cached state to make
room, so an agent's next request can need recomputation. Keep eviction of retained
prefixes distinct from failure of an active request. Introduce CPU offloading
early in scaling, after concurrency and before ModelExpress.

### 1.4 Introduce the Dynamo-managed deployment

Show the smallest useful DGD for the service and explain:

- The HTTP frontend is separated from the inference engine running on GPUs.
- The reasons for that separation will become clearer in the later experiments.
- The Dynamo operator reconciles the DGD into Kubernetes resources.
- Show the resources that actually appear, including frontend and worker Pods.

Show the startup timeline, distinguishing model weight loading from engine
initialization and the full time until the worker can serve a request. Include
scheduling and image availability where they materially contribute.

The timing dependency is still open: start the deployment while explaining the
manifest, and retain a completed measured startup timeline if live initialization
exceeds its slot. Long preparation must not consume the rest of the introduction.

Presenter implementation: [single-replica terminal demo](demos/single_replica/README.md).
Keypress-controlled steps show the effective DGD, deployment, operator-created
resources, readiness and its immediate timing summary, then HTTP model discovery
and an inference request. Pod/model startup run continuously within one step.
Tmux adds resource/timing and worker-log panes; a labeled offline rehearsal
supports presentation iteration. The service is retained for section 1.5.
The introductory demo uses eager execution and omits performance tuning options;
the compiled startup benchmarks have their own separately qualified profile.

### 1.5 Establish the workload and metrics with AIPerf

Use a prebuilt agentic trace to establish a baseline. Choosing the exact agent,
task, and trace is deferred. Save the increasing-demand experiment for section 2.

Explain the important measurements in terms of the agent's experience:

| Measurement | Audience interpretation |
| --- | --- |
| Time to first token | How long before the answer starts arriving? |
| Generation speed / inter-token latency | How quickly does the answer arrive once generation starts? |
| End-to-end request latency | How long does the whole inference request take? |
| Throughput | How much work does the service complete under this load? |
| Errors / unsuccessful requests | Which requests fail to complete successfully? |

Distinguish individual-request measurements from an entire agent session. Define
the metrics here; choose the concrete SLO targets and percentiles during workload
preparation. Use the same evaluation criteria throughout the later sections.

## 2. Scaling — 55 minutes

Keep the workload constant and increase offered load. Scale replicas manually.

| Investigation | Minutes | Components and teaching point |
| --- | ---: | --- |
| Traffic increases and the service deteriorates | 5 | Explain concurrency and the throughput/interactivity tradeoff; briefly introduce CPU offloading as a larger effective cache pool before adding replicas. |
| A new replica takes too long to help | 12 | ModelExpress; distinguish weight loading from the complete startup path. |
| Multiple replicas need cache-aware traffic placement | 12 | Dynamo KV router; compare routing behavior and cache locality. |
| A warm worker is busy while another worker has spare capacity | 10 | Move directly from routing to KVCR and router hints for peer reuse; NIXL moves the data. |
| Specialize workers for prefill and decode | 12 | Dynamo disaggregation and NIXL; compare with aggregated serving under the same workload and comparable GPU resources. |
| Automated scaling overview and finite-capacity behavior | 4 | One general slide on automation; finish with rejection when requests keep arriving and capacity cannot increase. |
| **Total** | **55** | |

Snapshot is not introduced in this section. Grove or other orchestration details
may be identified where necessary to explain the deployment, without becoming a
separate scheduling topic.

### 2.1 Increase concurrency and expose the need for capacity

Continue with the same coding-agent workload. Either increase concurrency with
AIPerf or show a previously measured throughput/latency curve. AIPerf changes
offered load; the presenter changes the deployment's desired replica count.

Explain the useful concurrency regime before showing its limits:

- One engine batches work from multiple active requests, including requests from
  different users. Concurrent agents, active engine requests, and requests
  waiting in a queue are different quantities; tool waits and subagents make
  the distinction particularly relevant to the coding-agent workload.
- GPU parallelism and engine batching allow work from many requests to share
  the GPU efficiently.
- As concurrency increases, aggregate throughput can increase while generation
  speed per user decreases. A service can complete more work overall while
  becoming less interactive for each user.
- This regime has limits. Scheduling and memory constraints can leave requests
  waiting; insufficient KV-cache capacity can also cause preemption and
  recomputation. Do not promise a universally smooth curve or that queuing begins
  only when KV cache fills.
- When the observed experience falls below our target, add serving capacity.

Plot concurrency against aggregate output throughput and per-user generation
speed, with first-token latency where useful. Keep agent concurrency, active
inference requests, and queued requests distinguishable. The exact curve and
load levels remain measurements to collect.

Make the two objectives explicit: output tokens/second/GPU describes resource
efficiency, while output tokens/second/user (with a clearly defined active
generation window) describes interactivity. Increasing concurrency can improve
the former while worsening the latter. Do not infer per-user speed simply by
dividing aggregate throughput by the number of agent sessions, since those
sessions may be waiting on tools, generating subrequests, or queued.

#### Briefly introduce CPU offloading before ModelExpress

Once concurrency and cache pressure are established, expand the GPU-memory
picture with CPU memory as an additional cache tier.

- GPU cache capacity is finite; the engine can retain more cached state by using
  host memory as well.
- Present native CPU KV offloading as a way to increase the effective cache pool,
  without teaching transfer implementation, configuration options, or eviction
  policies. A simple GPU/CPU memory visual is sufficient.
- Keep the distinction between cached request state and model weights explicit.
  More cache capacity does not itself add GPU compute capacity.
- Then return to the need for another serving replica and its startup delay.

This is the introduction of CPU offloading. Do not insert a new CPU-offloading
topic between routing and KVCR later.

### 2.2 Add a replica: startup cost and ModelExpress

Bring back the startup timeline from section 1. The audience now has a reason to
care about its duration: the requested capacity has not yet become useful.

The updated matched Super VL TP2 H100 measurements use text-only serving and
the qualified faster worker-health settings on every arm. Native loading from
the existing EFS checkpoint took about **493 s to observed Ready**, including
**267 s of model loading** and **144 s of engine initialization**. Model loading
is the largest individually logged phase, about 54% of full startup. Identify
the storage/cache state and distinguish phase timers from complete serving
readiness. This baseline includes no external model download and is not a
cold-Hugging-Face or local-NVMe comparison. The compiled benchmark profile is
separate from the eager presenter's first-server/second-server demonstration.

#### Hardware explanation

- Storage and external download paths have finite bandwidth.
- An existing compatible replica already holds the processed weights in GPU
  memory. GPU peer connectivity offers another source and transfer path.
- Briefly distinguish same-node GPU connectivity such as NVLink from cross-node
  fabrics such as InfiniBand, RoCE, or EFA. Identify the actual path used in our
  demonstration; the saved workshop P2P configuration uses NIXL/LIBFABRIC/EFA.
- Show source and destination GPUs and the weight-transfer arrow. Avoid a broad
  bandwidth taxonomy or assuming peer transfer always beats every storage path.

#### Explain the division between ModelExpress and NIXL

ModelExpress integrates with the inference engine's model loader and coordinates
how a compatible copy of the weights is found and loaded. NIXL supplies the
underlying data transfer.

In the P2P scenario:

1. A seed worker using the MX loader loads the model from an available storage
   path, registers the GPU-resident tensors, and publishes source metadata.
2. The new worker uses the MX loader to discover a compatible source and obtain
   the tensor/transfer metadata. Model identity, parallelism, and tensor layout
   must match the supported configuration.
3. Weights move directly between the source and target through NIXL; a central
   metadata service does not relay the model bytes. The saved workshop setup uses
   decentralized Kubernetes Service discovery.
4. The target still performs its remaining initialization before it can serve.

Both source publication and target loading need the appropriate MX integration;
this is not an arbitrary memory copy from an unmodified serving process.

Mention the broader loading capabilities briefly: ModelExpress also integrates
storage paths such as ModelStreamer for object/local storage and GPUDirect
Storage where supported. Current upstream MX additionally supports compatible
compilation-cache artifact reuse. The original functionality recipe sets
`MX_ARTIFACT_TRANSFER=0`. A separate matched native-context experiment has now
qualified compatible artifact reuse in the pinned MX 0.6.0 / vLLM image, using
central metadata discovery. Keep the original weight-only recipe and this
qualified artifact configuration distinguishable in preparation material.

Artifact reuse moves file-backed compiler/kernel/autotune caches into the fresh
worker's filesystem cache before the engine needs them. It does not restore a
running process. Keep that distinction available for the later Snapshot
introduction. Reuse depends on model, parallelism, software stack, GPU architecture,
and compilation configuration. Current upstream provides
`MX_ARTIFACT_COMPILE_CONFIG_DIGEST` to partition sources by compilation settings;
vLLM can ignore an installed cache and recompile if its own cache key differs.

This also requires a discovery decision: the saved `k8s-service` backend supports
weight manifests only. The default NIXL artifact path requires P2P metadata and a
central Redis or Kubernetes-CRD coordinator. Upstream also has a separately
configured Mooncake artifact backend. Verify these features against the pinned
workshop build before treating artifact reuse as an enabled configuration.

#### Demonstration and comparison

Presenter implementation: [ModelExpress terminal demo](demos/modelexpress/README.md).
The presenter covers peer weights only with the intro's eager profile. Enable
the MX loader before the first demo launches: that server loads from storage
and remains running as the weight source. In this section, explain the existing
loader/discovery settings, launch only the second replica, verify both TP-rank
transfers without fallback, and compare startup with the first server's recorded
storage load before sending a request through the destination frontend. No
separate source or storage-baseline worker is launched. The two observed
startups use different nodes; the matched experiments below remain separate.
The target's dedicated frontend isolates this loading investigation; shared
traffic placement follows in the router demo. Clean up the peer target before
cleaning up the first server.

- Reveal the MX loader and source-discovery/fabric setup already enabled in the
  first server, then show how the second server discovers it.
- Launch the second replica and show evidence that it received peer weights
  rather than silently falling back to storage.
- Compare the first server's storage startup with the second server's peer
  startup, showing both weight loading and complete initialization. Label these
  observed timings separately from the controlled comparison below.
- Keep external download, local/shared-storage loading, and P2P baselines labeled
  separately. Use matching model/runtime/workload settings and report cache state.
- Observe the serving source during transfer so we can assess any effect on
  existing traffic as well as the target's startup.

The final text-only loading-path matrix is complete, with the same worker
health policy on all three receivers:

| Startup path | Deployment to observed Ready |
| --- | ---: |
| Native EFS loading, MX off | 492.79 s (8m13s) |
| MX peer weights | 280.10 s (4m40s) |
| MX peer weights plus compilation artifacts | 173.61 s (2m54s) |

Actual engine cache loads were verified on both TP ranks. Peer weights reduced
the model-loading timer **267.39 → 52.57 s**. Adding compatible artifacts reduced
engine initialization **149.12 → 40.53 s**, with the compilation timer
**30.76 → 0.20 s** and backbone profiling/warmup **82.17 → 28.51 s**. These
nested timers must not be added to full startup or attributed solely to AOT
graph reuse; the transferred bundle also includes kernel/autotuning caches.

The artifact receiver still spends **48.66 s** in model loading, even though
the slowest logged NIXL weight copy takes only **3.22 s**. Process/bootstrap,
tensor setup, profiling/warmup, KV-cache allocation and graph capture remain.
Its engine-end-to-observed-Ready tail is **8.09 s** under the faster health
policy. This is a startup-qualified policy, not a production failure-detection
or SLO qualification.

The full MX path is **2.84× faster than storage** in this matched experiment,
removing **319 s (64.8%)** from startup. One fresh idle source was retained;
its own storage bootstrap took **512 s**. All receivers used the same physical
two H100 GPUs, distinct Pods and private fresh caches. This is one fixed-order
trial per arm with five-second Ready polling and uncontrolled host page cache,
not a distribution. The first checked correct response follows evidence
collection and is an upper bound on first-possible inference.

See the [updated matched results](reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_RESULTS.md)
and [versioned compiled baseline](configs/dgd/super-vl-textonly-fast-startup/).
The earlier multimodal matrix and separate text-only/health experiments remain
historical evidence in the [MX report](reports/workshop-measurements-20261030/mx-startup/REPORT.md)
and [candidate results](reports/workshop-measurements-20261030/startup-optimization/STARTUP_RESULTS.md);
do not combine their numbers into this matched table. Effects on an actively
serving source, repeatability, later-runtime qualification and how much artifact
configuration to show live remain preparation items.

### 2.3 Two replicas: cache-aware routing

Update the system diagram to show one frontend dispatching to two aggregated
workers. Compare the service under the same offered load with one and two
replicas, using an explicitly identified initial routing policy.

The first AgentX scale-out pairs now give this investigation a measured setup:
C1 showed essentially unchanged active-generation speed and worse TTFT; its
aggregate rate requires care because the two exported phase denominators differ.
In C4, adding a replica did not improve aggregate throughput. Mean
active-generation speed improved about 8.4%, while
cache-read share fell from 95.8% to 90.7% and TTFT p50 rose from 306 to 478 ms.
Use this to ask why more capacity did not improve the whole request experience.
These are one-repetition operational scale-out observations, including partial
trace mixes and the recorded C4 recovery pause; they neither measure maximum
capacity nor isolate routing as the cause. The separate fresh-worker RR/KV
pairs must establish any routing benefit. See the
[replica measurement report](reports/workshop-measurements-20261030/round-robin/REPORT.md).

Return to the retained state introduced in section 1: identical replicas can have
different cached context. Round-robin or random routing provides a baseline;
cache-aware routing can account for reuse as well as load.

#### Core explanation

1. Workers know what cached state they hold. They publish updates as cache is
   created, offloaded to CPU memory, or evicted, allowing the router to track
   where reusable state remains available.
2. The router consumes those events and maintains an index of which prefixes
   are available on which worker and, when published, in which memory tier.
   These messages describe cache state; the router does not receive the KV
   tensors themselves.
3. On a new request, the router looks for overlap with that request's input
   prefix and considers the workers' projected load.
4. It selects a worker using both the reusable work and the work already
   assigned there. Subsequent worker events update the router's view.

Use one system diagram with worker-to-router metadata arrows and a
frontend-to-worker request arrow. Avoid hashing/index data structures, event
transport choices, detailed scoring formulas, and a catalog of tuning flags.

Bring back the GPU/CPU memory picture from the concurrency opener. Illustrate
creation, offloading, and eviction as residency updates. In particular, removing
a GPU copy need not discard a retained CPU copy. The presenter can describe
these lifecycle changes without teaching their individual wire-event encodings.
Router visibility of CPU-resident cache requires the appropriate worker events;
it does not follow automatically from enabling offloading inside the engine.

#### Explain the tradeoff using parallel subagents

Introduce delegation here, after the router's event/selection feedback loop,
rather than expanding the opening fundamentals. The main coding agent has
accumulated a substantial context while investigating a change. It forks several
branches from that same context to investigate separate questions, such as
implementation, tests, and compatibility. In this illustrative application, each
branch inherits the same initial messages and appends its own instruction:

```text
Branch 1: [same accumulated context] [investigate the implementation]
Branch 2: [same accumulated context] [design the tests]
Branch 3: [same accumulated context] [check compatibility]
```

Reuse the highlighted-prefix visual from section 1. Earlier it showed reuse
over time within one agent; now it shows reuse across parallel branches. No large
swarm or new agent-framework lesson is required. A few branches can illustrate
the tradeoff; whether they create measurable pressure depends on actual capacity.

Use these requests to explain the routing choice:

- Worker A has already processed the common prefix but also has active work.
- Favoring A preserves locality but competes for its compute and can concentrate
  traffic there.
- Worker B has spare compute, but sending work there requires more prompt
  computation while its cache is cold.

Routing parameters can adjust that balance for the workload. Give interested
attendees a documentation link and leave detailed tuning to the take-home
material. Cache-aware routing is not an unconditional rule to send every request
to the worker with the longest matching prefix. It can already choose the colder
worker when its lower load outweighs the cost of recomputation; tuning alone
does not remove that computation cost.

The illustrative fork preserves a matching token prefix. Real subagent frameworks
differ in what they inherit; the same repository or semantically similar context
does not guarantee reuse, and different instructions at the start of the prompt
can reduce overlap. The AgentX trace analysis now supplies a concrete example:
two named parallel subagents share 72,320 leading recorded token units, about
94% of their inputs, with overlapping recorded requests. This supports shared
prefixes across parallel branches; those captures do not generally establish
inheritance of the parent's entire conversation. Use the
[trace evidence](reports/workshop-measurements-20261030/agentx-workload/BRANCH_PREFIX_FINDINGS.md)
to ground the visual. Cache residency, placement and performance remain separate
live measurements; the corpus example alone does not establish a routing gain.

#### Demonstration and evidence

- Show the worker KV-event configuration and the frontend's cache-aware routing
  mode at the minimum level needed to explain the feedback loop.
- Compare two-worker round-robin and two-worker cache-aware serving at the same
  preselected AgentX load points, with matching hardware, worker configuration,
  workload, and cache/primer conditions.
- Show representative measured changes in prompt reuse, first-token latency,
  per-user generation speed, and aggregate throughput where available. Identify
  which metrics actually improve and the load/workload to which the result applies.
- Keep this policy comparison distinct from the earlier one-versus-two-replica
  experiment, which changes capacity as well as placement opportunities.

### 2.4 Move directly from routing to KVCR

Keep the same parallel-subagent example and the tradeoff just established.
Worker A has the matching context but is busy; worker B has spare compute.
Introduce KVCR as a way to mitigate the recomputation downside of routing to B:
can B retrieve available cached prefix state from A and reuse it there?

Show a peer cache-transfer arrow on the existing two-worker diagram. Transfer
has its own cost, so the locality/load tradeoff remains; the missing prefix no
longer always has to be recomputed. The reusable state is copied, rather than
migrating an already-running request as discussed in section 3.

CPU offloading and the GPU/CPU cache pool are already familiar from the concurrency
opener, so they need no separate introduction here. Introduce the general idea
that KV state can move between workers, so compute can happen somewhere other
than where that state was first created. Reuse this idea in disaggregation.
Keep disk/object-storage cache tiers outside the core explanation.

**Deferred:** finish the detailed KVCR explanation, configuration walkthrough,
and peer-reuse demonstration later. The teaching transition does not depend on
settling that demonstration now.

### 2.5 Specialize workers for prefill and decode — 12 minutes

Open by returning to the prefill/decode concepts introduced in fundamentals.
We already have multiple workers and have introduced moving KV state between
them. Lead with their different resource requirements: specializing workers is
the next scaling option.

#### Why specialize?

- Prefill processes the input context and builds the working state. Decode
  repeatedly uses and updates that state while generating new tokens.
- Make their different demands on GPU compute, memory bandwidth, cache capacity,
  and batching the primary motivation. Keep the explanation at this level;
  avoid a kernel or tuning tutorial.
- Those differences motivate specialized workers with different engine settings
  and independently sized pools. Scale prefill and decode capacity separately
  as demand changes; continue scaling manually in this workshop.
- Protecting ongoing generation from new long-prefill work is a secondary
  benefit to mention where useful. It does not introduce the section. Establish
  which benefits the comparison actually demonstrates rather than assuming
  disaggregation always helps.

#### Carry forward the idea of moving KV state

The state created during prefill is what the decode worker needs to continue
generation. Move that state between compatible engines instead of requiring
both phases to run on the same worker:

```text
HTTP request -> prefill worker [GPU: build KV state]
                                    |
                          NIXL GPU-to-GPU transfer
                                    v
               decode worker [GPU: generate using that state] -> response
```

Both pools still run model engines with the weights they require. The router
and backend coordinate worker selection, transfer, and continuation; NIXL moves
the bytes. Keep that coordination to a short request walkthrough without
teaching backend-specific transfer metadata.

Connect the mechanisms by purpose as well as by memory tier:

- **KVCR peer reuse:** obtain existing cached prefix state to reduce repeated
  computation across requests. The host-memory reuse path introduced here
  contrasts with the direct GPU handoff below; NIXL supplies its data movement
  too. Scope tier descriptions to the demonstrated integration rather than
  claiming KVCR can never involve GPU memory.
- **Disaggregation:** hand working state from prefill to decode within one
  request. The demonstrated P/D path transfers directly between GPU memories
  through NIXL.

The common idea is that request state can travel to the worker that will use it.
These are related uses of state movement with different coordination and reuse
semantics; disaggregation does not require KVCR to provide its P/D transfer.

#### Demonstration to develop

Presenter implementation: [disaggregation terminal demo](demos/disaggregated/README.md).
The initial runner demonstrates the P/D handoff and verifies real KV-transfer
evidence. A matched performance comparison remains open. The text-only runner
passed fresh live qualification; its actual main-panel output is in the
[recordings index](demos/transcripts/live/README.md).

Update the existing deployment diagram to separate prefill and decode pools.
Show the smallest relevant DGD changes and one request's prefill, state-transfer,
and generation path. Keep the same coding-agent workload and compare aggregated
and disaggregated serving with comparable total GPU resources. Interpret TTFT,
per-user generation speed/ITL, and aggregate throughput together; identify the
transfer cost and any capacity tradeoff. Choose an experiment that illustrates
resource specialization and independently sized pools. The exact experiment
remains open; the lead motivation is settled.

After this block, retain the four-minute automation/rejection close. Explicitly
return to aggregated serving before resiliency, as already agreed.

### 2.6 Closing slides — 4 minutes

- **Autoscaling — placeholder:** one general overview slide. Content deferred;
  the workshop experiments continue to use manual scaling.
- **Request rejection — placeholder:** what happens when capacity cannot
  increase and requests keep arriving. Content deferred.

## 3. Resiliency — 55 minutes

Explicitly return to aggregated serving after the disaggregation demonstration.
Show that topology change and scope the demonstrated recovery behavior to it.

Use the same questions and metrics for every recovery mechanism:

1. Do the affected requests complete?
2. When does usable serving capacity return?
3. How does latency and SLO behavior change during recovery?

Latency and SLO impact apply across the entire section, not just Shadow Engine.

| Sub-block | Minutes | Coverage |
| --- | ---: | --- |
| Request continuity | 15 | Failure detection, in-flight request migration, and graceful draining. |
| Engine process recovery | 15 | GMS weight preservation, Shadow Engine promotion, and standby replenishment. |
| Pod and node recovery | 25 | Snapshot local restore, shared-storage/node-loss discussion, and the integrated recovery story; revisit KVCR-Guard if ready. |
| **Total** | **55** | |

### 3.1 Request continuity — 15 minutes

The technical basis and source links are collected in
[request migration presenter notes](reports/2026-11-04-request-migration-technical-notes.md).
Teach the main sequence here; keep the implementation details and version
differences available for preparation and questions.

Presenter implementation: [request-continuity terminal demo](demos/request_continuity/README.md).
Two two-worker cases are prepared offstage (eight H100s total), with migration
disabled/enabled. It captures one client stream per case, a PID-guarded
EngineCore fault, worker identities and client chunk gaps. The pinned runtime
keeps the initial SSE worker ID, so a response-correlated frontend trace proves
the retry target; the exact handoff gap is unavailable. The fresh corrected
walkthrough and [main-panel recording](demos/transcripts/live/05-request-continuity/20261104-a2/main.txt)
passed disabled interruption and enabled continuation to successful completion.

#### Start with a broken streaming response

Return to two aggregated workers and keep the same coding-agent workload.
Expose one representative streaming coding response so the audience can follow
it, alongside a compact request/worker timeline. Begin with frontend request
migration disabled and client retries disabled so the failure is observable.

1. Show a healthy request producing visible output, and identify its serving
   worker. Establish how a successfully completed stream normally ends.
2. Abruptly kill that worker's inference process after some output has arrived.
   Keep the frontend and the other worker alive. This is the process-failure
   scope; Pod and node failures are investigated later.
3. Inspect the partial answer and the actual client/stream outcome before
   introducing a recovery mechanism. Capture received chunks, errors, terminal
   finish information, stream termination, and timestamps. Distinguish the
   worker's failure from failure of the client-to-frontend connection.
4. Send a separate new request to show whether surviving capacity can serve it.
   Separate the fate of the interrupted request from readiness for new traffic
   and from eventual restoration of the lost capacity.

Use the investigation to make the problem concrete: there is already output at
the client, and restoring a worker does not by itself complete this in-flight
generation. Starting the original prompt again is a different operation from
continuing the partially delivered answer.

**Source-level preparation note:** in the pinned frontend, a streaming error can
be serialized as an error frame followed by `[DONE]`. Neither HTTP 200 nor that
terminator alone establishes a successful generation. Qualify the exact outcome
of the selected process fault and client against the workshop runtime; do not
script an assumed socket reset, missing terminator, or silent truncation. The
existing request helper discards `[DONE]` and is not a sufficient capture of the
complete failure sequence.

#### Then investigate request migration

Keep the frontend and its client connection alive. The failed connection is
between the frontend and one worker; a second worker already has the model
loaded and can serve the continuation.

Explain what the frontend retains: the original prompt's token IDs, generated
token IDs received in successful chunks, remaining output budget, and request
options. This is a compact replay description of the generation. It is not the
failed worker's GPU KV memory or initialized engine process.

Walk through one request with a simple prefix/budget example:

```text
Original request: input P, generate up to 10 new tokens
Worker A returns: o1 o2 o3, then fails
Retry to worker B: input P + o1 o2 o3, generate up to 7 more tokens
Client output:    o1 o2 o3 [recovery pause] o4 ...
```

The output already produced becomes part of the replacement worker's input.
B continues after that prefix; it does not need to generate it again as output.
Missing working state is rebuilt by processing the accumulated input, with any
compatible cache reuse reducing that work. No KV transfer from the failed
worker is required for this basic recovery mechanism. This returns to the
fundamentals lesson that working state can be recomputed from context, at a cost.

Trace the control flow on the existing frontend/two-worker diagram:

1. The runtime reports a typed dispatch/stream failure. An internal stream
   ending before its generation-completion marker is treated as a disconnect;
   discovery removal or an engine-reported shutdown can also expose the failure.
2. The frontend migrator checks the error, request constraints, and retry budget.
   Routing avoids the failed worker through local inhibition and, for KV
   routing, per-request exclusions while discovery converges.
3. The migrator dispatches the accumulated token prefix and adjusted budget
   through the backend path again, using the same logical request context.
4. If the replacement succeeds, the eligible error is consumed internally and
   new output continues on the original client stream. If recovery is disabled,
   disallowed, or exhausted, the error reaches the client instead.

There are two recovery cases: an initial dispatch fails before generation
starts, or an already-running generation fails and needs its output prefix.
Use the mid-stream case as the main demonstration because the audience has
already seen the partial answer.

#### Enable it and repeat the same failure

Show the frontend setting `DYN_MIGRATION_LIMIT=3` (or `--migration-limit 3`).
The default is zero; three permits up to three replacement attempts in addition
to the initial dispatch. Keep client retries disabled so it is clear that Dynamo
performs the internal continuation. Identify the serving worker from telemetry
rather than pinning the request to a particular worker.

Repeat the same representative streaming request and process fault. Show the
worker change, the partial prefix remaining at the client, the gap while B
resumes, and successful final completion. Capture backend attempt/worker traces
and timestamped client chunks. A migration counter alone does not prove that
the response resumed or completed; the code's duration metric marks replacement
stream establishment, which can precede resumed client tokens.

Interpret the pause: detection, routing/queueing, and rebuilding missing state
can take time, especially for long coding contexts. Keep completion, capacity,
and latency/SLO behavior on the same timeline. Migration can preserve progress
while the survivor is overloaded; it does not replace the lost serving capacity.
That is the transition to Shadow Engine recovery.

#### State the support boundary and planned-termination case

- The frontend must survive. Its token replay state is in memory and does not
  provide automatic recovery of a lost client connection or frontend process.
- Use a supported single-choice text request. Guided/structured decoding and
  `n > 1` disable migration in the pinned implementation. An explicit worker
  pin can prevent rerouting. Ordinary tool-call generation and constrained
  JSON output need to be distinguished when qualifying the coding-agent demo.
- `DYN_MIGRATION_MAX_SEQ_LEN` optionally caps prompt plus generated tokens used
  for replay. Exceeding it disables future migration for that request; it does
  not truncate the input. Do not copy a short illustrative cap into our
  long-context workload. Sampler/decoder state also has version-specific limits
  described in the presenter notes; avoid promising identical future samples.
- For planned rollout or scale-down, show draining as the first option: stop
  admitting new work and let existing requests finish. If a request is later
  interrupted, eligible migration can continue it elsewhere. A `SIGTERM` drain
  and an abrupt process kill are different lifecycle experiments.

Working delivery budget: 3 minutes for the broken response, 5 for the replay
mechanism, 5 for enabling migration and repeating the fault, and 2 for boundaries
and draining. The detailed source walkthrough belongs in preparation/backups.

### 3.2 Engine process recovery: GMS and Shadow Engine — 15 minutes

Base the explanation and investigation on the
[Shadow Engine blog](https://developer.nvidia.com/blog/restore-llm-inference-capacity-in-seconds-with-shadow-engine-recovery-in-nvidia-dynamo).
Use its experimental results as a published example, separately from the
workshop's Super VL qualification and measurements.

#### The request survives; how quickly does capacity return?

Continue from request migration. While requests can move to the surviving
worker, it must now absorb more traffic. Return to the startup timeline from
fundamentals/MX: how much initialization must finish before the lost capacity
becomes usable again? Keep completion, capacity, and latency/SLO observations
on the same timeline, as in every resiliency experiment.

#### Explain the two pieces with one worker diagram

- **GMS:** a separate process owns the GPU weight allocation. The active and
  shadow engines map one physical copy, and those weights survive an engine
  process exiting while GMS and the GPUs remain healthy.
- **Shadow Engine:** a second process has already initialized its own execution
  state, including communicators and graphs. It parks until promotion; it does
  not inherit the failed engine's CUDA context.
- Show a single weight allocation shared by both engines, private engine
  buffers/state, and KV cache materialized only for the active engine. Shared
  weights avoid a second weight copy; the standby still has overhead.
- Trace the lifecycle: active process exits -> standby acquires the failover
  lock -> standby wakes, materializes KV memory and registers for traffic ->
  restarted engine prepares as the next standby in the background.

Keep CUDA allocation APIs and lock implementation details in presenter notes.
The teaching point is preserving expensive weights and preparing the remaining
initialization before the failure.

#### Demonstrate Shadow promotion under load

Working sequence: about 2 minutes to establish the capacity problem, 4 for the
diagram/lifecycle, 6 for live promotion, and 3 for replenishment and scope.

1. Keep request migration enabled from the preceding investigation, retain the
   coding-agent workload and a stable offered load, and show the Shadow-enabled
   worker configuration. Label the additional standby resources.
2. Show two usable workers and the prepared standby, then kill one active
   inference process to trigger promotion. Preserve its Pod, GMS, GPU
   allocation, and the other worker.
3. Follow request outcomes, the temporary capacity drop, and the actual moment
   restored capacity serves traffic. Overlay TTFT and per-user generation speed
   or ITL, retaining the same metric definitions used earlier.
4. Show the new standby becoming ready after promotion. Fast cutover and
   restoring protection against another fault are different milestones;
   observe any effect of background initialization on serving traffic.

**Agreed:** the live demonstration in this section is Shadow promotion. Use the
earlier investigation, existing timings, or the blog's chart for cold-restart
context; do not add a separate ordinary-failure demonstration here.
The blog's two-worker GLM-5.2/B200 example reports **283 s versus
7.3 s** until the second worker serves, and **201/399 versus 1/398** requests
above its 5 s TTFT threshold. Those are its workload and thresholds, not Super VL
results or a promise of zero SLO violations. Reuse its capacity and latency
visuals as examples; do not replace the workshop workload with its synthetic one.

**Boundary:** the blog describes a preview for process failures, not GPU, Pod,
or node loss. The promoted engine starts with an empty KV cache in that version;
request continuation and cached-context recovery remain separate mechanisms.
**Decided November 8:** Super VL is still blocked by GMS integration bugs, so
the live promotion uses Qwen3-0.6B at TP1 on one H100, labeled on the slide.
Its first live qualification must pass before the session (day plan, step 4);
otherwise the slide presents the October 22 Qwen control instead.

### 3.3 Pod and node recovery: Snapshot — 25 minutes

Base the explanation on the supplied
[Snapshot blog draft](https://docs.google.com/document/d/16-vzIprjNUO9_f4G-6z8ACzmmaUS81XI3OUg_1wADTk/edit?tab=t.0#heading=h.t6npw1ugvi0g),
read November 3, and the [Snapshot project](https://github.com/ai-dynamo/snapshot).
Retain the allocation of 15 minutes for replacement Pods, 5 for node loss/storage,
and 5 for the integrated story.

#### A replacement Pod needs an initialized engine — 15 minutes

Escalate the failure boundary: the Pod containing the active engine, standby,
and GMS is gone. The in-Pod recovery arrangement cannot be assumed to survive.
Kubernetes can replace the Pod, but the new process still needs to become
serving-ready. Bring back the startup phases: loading weights, runtime
initialization, compilation/autotuning, and graph capture.

Use an ordinary aggregated worker for the standalone Snapshot demonstration;
restoring a combined GMS/Shadow deployment is a separate integration to qualify.

Introduce Snapshot as saving an initialized CPU/GPU process into an artifact
and restoring that state into a new, compatible Pod. Use a three-stage visual:
initialize once -> checkpoint artifact -> replacement Pod restores and serves.
Briefly identify CRIU for CPU/process restoration and CUDA restoration for GPU
state. This recalls the engine state introduced in fundamentals without a
checkpointing-internals tutorial.

Working demonstration sequence:

Presenter implementation: [Snapshot terminal demo](demos/snapshot/README.md).
Its current native vLLM path passed live prepared-artifact Pod replacement and
fresh inference. A separate November 4 DGD-led trial has also passed replacement
and fresh streaming coding requests through the unchanged Dynamo frontend;
see the [DGD Snapshot workstream](reports/workshop-snapshot-dgd.md) and the
current measurement status below. That trial uses an experimental runtime
overlay and a different profile from the native recording; retain those labels.

A [follow-up using upstream's native controller](reports/workshop-snapshot-upstream-controller.md)
also passed capture and both restores. Use it for further preparation: the
remaining custom runtime code is the destination identity/offline bridge.

The [node-local NVMe follow-up](reports/workshop-snapshot-dgd-nvme.md) also passes
the DGD flow: **48/59 s initial/replacement Pod-to-Ready**, **34.05/36.86 s agent
restore**, and **99.11 s deletion intent to observed replacement response**.
Capture, copying and full hash verification are offstage. The presenter runner
still needs to be wired to this qualified flow; the creating DGD stays alive
through the onstage replacement.

1. Show a checkpoint prepared from a healthy, initialized Super VL worker.
   **Agreed:** prepare and validate it before the session. Briefly show its
   preparation through Dynamo configuration, ready status, and artifact; use
   the live demonstration time for replacing and restoring the Pod.
2. **Agreed:** lead with the minimal Dynamo/DGD configuration for Snapshot in
   the pinned runtime, then follow the operator's restore behavior and status.
   If time permits, inspect the underlying `SnapshotJob`, `PodSnapshot`, and
   `nvidia.com/restore-from` annotation. Keep that resource-level walkthrough
   optional; it is not a prerequisite for following the main demonstration.
3. Replace the serving Pod while the node and its local artifact survive.
   Restore from the pre-staged local-disk checkpoint, identify the new Pod UID,
   and verify fresh inference plus registration/routing readiness. Scope this
   to the demonstrated compatible placement and GPU allocation.
4. Compare cold startup and restore on matching inputs, separating scheduling,
   container startup, agent setup, process restore, GPU restore, and the first
   successful response. Show checkpoint creation/staging cost separately.
5. Follow the same request-completion, capacity, and latency/SLO timeline as the
   other faults, including any prefix-cache rebuilding after restoration.

**What is restored:** the draft's inference benchmarks explicitly release the
KV cache before checkpointing. Teach restoration of the initialized engine;
do not imply that its checkpoint resumes the failed in-flight stream or retains
the production prefix cache. Request migration and any separately qualified
cache-preservation mechanism still have their own roles.

Use one representative figure from the draft rather than its full benchmark
matrix. Its B200/VAST experiments report **3.6–42.7 s** restores across their
tested configurations. Their cold-start clock runs from process launch to
engine initialization; their restore clock runs from the restore request to
serving. Both exclude image pull/container-runtime setup. Preserve those labels;
do not call the figure fault-to-recovered-service time or a Super VL result.

For a workshop-specific storage illustration, the
[October 22 Super VL TP2 control](reports/2026-10-22-snapshot-tp2-nvme-comparison.md)
measured about **37 s agent restore / 40–41 s Pod-to-Ready** from pre-staged NVMe.
This is historical same-node evidence with fixed GPUs and a development build,
not a cold-cache or integrated Dynamo recovery benchmark. Requalify the actual
workshop deployment before using it as a live-demo claim.

#### What changes when the node disappears? — 5 minutes

Keep this as a diagram/slides investigation unless cross-node restoration is
qualified. If the node is unavailable, its local artifact is unavailable too.
Show the checkpoint on storage accessible to a replacement node, then restore
on compatible hardware/software. Shared storage makes the artifact reachable;
placement, compatibility, storage throughput, and restoration still matter.

Distinguish restoring a single-node multi-GPU workload on another compatible
node from coordinated checkpoint/restore of an engine spanning multiple nodes.
Do not imply that the latter follows from shared storage. Keep artifact-reading
and GPU-state-copy costs visible; our slower shared storage may dominate.

#### Return to the combined recovery story — 5 minutes

Revisit the layers on the same system diagram: request migration continues
requests, GMS/Shadow restores process-level capacity, and Snapshot restores an
initialized replacement Pod. Recall MX as a weight-loading path from scaling.
Explain possible composition, such as shortening standby replenishment, only
to the extent demonstrated; label remaining integration as work in progress or
vision. Revisit KVCR-Guard only if its recovery path is qualified.

Keep readiness statements explicit: Shadow is preview in its blog, Snapshot's
current project cautions against production-critical use, and workshop receipts
qualify specific configurations. A successful individual component does not
establish a supported or production-ready combined recovery stack.

Do not assume request migration, engine restoration, and preservation of cached
context are the same mechanism. Explain their respective roles and the tested
composition.

## Take-home material

Provide a path to deploying a Dynamo-managed service and reproducing the
investigations:

- Environment prerequisites and versioned model/runtime inputs.
- Baseline DGD, deployment steps, endpoint verification, and cleanup.
- Repeatable workload, AIPerf commands, and metric interpretation.
- Successive experiment configurations for scaling and recovery.
- Explicit additional requirements and maturity labels for advanced features.
- Integrated examples where reproducible; explanatory material for the remaining
  vision.

## Outside the Dynamo portion

- NVKR/NVKE: covered by other presenters before this material.
- Planner and live autoscaling: omitted; retain only a general overview slide.
- KAI topics, queues, quotas, reclaim, and multi-tenancy: omitted.
- Slurm/Slinky: omitted.
- Standalone observability section: omitted; metrics are introduced early and
  woven through the experiments.
- Attention mathematics and detailed cache representations: omitted.

## Preparation questions resolved by the pilot measurements

- **Controlled benchmark workload:** the pinned AIPerf AgentX scenario, full
  trace corpus, model/tokenizer/runtime identity and C1/C4 session-tree semantics
  are established. A specific agent/task for the explanatory visual is separate.
- **Shared context across parallel subagents:** a named-sibling trace example
  has a large exact shared prefix and recorded overlap. General inheritance of
  the parent's whole context remains an illustrative application choice.
- **MX complete startup benefit:** storage, peer weights, and peer weights plus
  compiler artifacts have a matched native-context, text-only Super VL result:
  **493 → 280 → 174 s**, with identical health settings and actual both-rank
  engine cache reuse. Text-only mode and the faster health policy are qualified
  for this startup comparison; production failure-detection/SLO qualification is
  separate. The original multimodal/8k pilots remain historical evidence.
- **Initial one-versus-two behavior:** C1 and C4 operational scale-out pairs are
  measured and locally verified. C4's full closeout verified 142 files with no
  mismatches and reproduced the accepted analysis. Their interpretation supplies
  the routing question; routing benefit and saturation capacity remain unmeasured.
- **Presenter-demo functionality and recordings:** all four initial runners
  passed live execution and have [main-panel recordings](demos/transcripts/live/README.md).
  The intro and weight-only MX demos use eager profiles; disaggregation proves
  the P/D transfer path rather than a performance gain; the native Snapshot
  recording proves same-node restoration rather than in-flight recovery.
  Those intro/MX recordings use the earlier separate-source workflow. The
  revised flow retains the first server as the MX source and passed live on
  November 7 UTC: **492.98 → 247.01 s** to observed Ready, both TP ranks over
  LIBFABRIC/EFA without fallback, correct target response. Accepted as qualified
  ([receipt](reports/receipts/2026-11-07-modelexpress-intro-source.json)). A
  November 8 [recording](demos/transcripts/live/02-modelexpress/20261108-a1/main.txt)
  of the same flow (247.6 s to Ready) is the fallback; replica 2 has now reached
  Ready in 247–250 s on all three live runs.
- **DGD-led same-node Snapshot recovery:** the November 4 upstream-controller
  [NVMe follow-up](reports/workshop-snapshot-dgd-nvme.md) passed
  initial and replacement streaming coding requests, with a new worker/Pod
  identity and unchanged DGD, frontend and Service identities. Cleanup and lease
  release passed independent audit. This is a specific experimental overlay /
  8k-context configuration, not cross-node or integrated request recovery.
- **Request migration:** the [presenter demo](demos/request_continuity/README.md)
  passed a fresh Super VL EngineCore SIGKILL in both cases: disabled interrupted;
  enabled preserved 31 output tokens and completed through the qualified peer.
  The response-correlated frontend trace proves the handoff because SSE worker
  attribution is first-write-wins. This establishes standalone continuation,
  with no latency-distribution or SLO claim.

These resolve the initial evidence/functionality questions for the measured
configuration. They do not decide final slide emphasis, live-demo orchestration,
production maturity or qualification of a later patched runtime.

## Open items

### Workload and presentation choices

- Exact coding agent and repository/task for the motivating visual: deliberately
  deferred. The controlled benchmark workload is the pinned AgentX corpus.
- Demonstration load levels, SLO thresholds, reporting percentiles and metric
  windows; preserve the distinction between aggregate tokens/s/GPU, active-user
  generation speed, HTTP concurrency and AgentX session-tree concurrency.
- Live AIPerf concurrency ramp versus a measured curve. Existing C1/C4 pilots
  are fixed-load observations, not a saturation/Pareto sweep.
- Rehearse startup overlap and the fallback to prepared resources/recordings
  within section 1's 20 minutes. Startup has been measured: the eager intro
  retake took about 461 s to Ready, longer than its six-minute deployment slot.

### Scaling evidence still needed

- **Scaling/routing load curves:** C1/C4 were low-load pilots and do not establish
  the capacity benefit of a second worker. The user selected C16/C32/C64/C128
  across one-worker RR, two-worker RR and two-worker KV. The higher-cap attempt
  admitted 128-sequence serving and completed only one-worker C16 (307 valid
  requests, approximately 89% GPU utilization). C32 failed during snapshot-primer
  warmup after health timeouts and a worker restart; the controller stopped.
  Neither two-worker configuration ran. Resolve the health/warmup interaction
  before rerunning the selected matrix to measure running/waiting requests,
  cache pressure, throughput and per-user latency and locate the observed knee.
  Retain the pinned full AgentX corpus and replay rules, fixed-order/N=1 limits,
  realized mixes, cache history and drain denominators. The old routing campaign
  was stopped before C4 profiling and its 680-file evidence and GPU cleanup are
  verified. The higher-load attempt's 451-file evidence and GPU cleanup are also
  verified. [Sweep failure report](reports/workshop-measurements-20261030/load-sweep/FAILURE_REPORT.md).
- **MX follow-ups:** decided November 7: the live demo shows peer weights only,
  and compiler artifacts appear on the deck's matched-results slide. Impact on
  an actively serving source, repeatability and any later-runtime requalification
  remain open. Further bootstrap/tensor-discovery/warmup profiling and non-EFS
  baselines are optional follow-ups, not missing proof of the measured MX gain.
  Triton persistent tuning is already enabled; it is not another flag to test.
- **CPU offload:** qualify the selected Super VL configuration and router-visible
  tier events if demonstrated. The capacity visual before MX needs no separate
  offload benchmark.
- **KVCR:** detailed explanation/demo remains deliberately deferred. Existing
  feature receipts establish a peer-transfer path; select and qualify the actual
  text-only workshop demonstration before promising its routing/load benefit.
- **Disaggregation:** functionality and the text-only P/D recording passed.
  Choose a matched AgentX experiment with comparable total GPU resources that
  illustrates specialization and independently sized pools. The performance
  comparison, rather than the basic P/D transfer proof, remains open.

### Resiliency qualifications still needed

- **Request continuity/migration:** the standalone plain-text coding-response
  demo passes with an EngineCore SIGKILL, unpinned routing and one client request.
  Remaining work is AgentX/load and SLO qualification, richer tool/parser request
  shapes, and precise per-attempt telemetry for the client handoff gap. The
  current SSE field retains the first worker, so maximum adjacent content gap
  is reported separately from an exact recovery gap.
- **Shadow:** Super VL TP2 startup/recovery remains unqualified after the saved
  October 22 integration failures. Resolve that configuration before promising
  live promotion; the successful Qwen TP1 control does not qualify Super VL.
  Measure standby overhead, promotion under the workshop load and replenishment.
- **Snapshot:** same-node DGD replacement and fresh frontend inference now pass
  from pre-staged NVMe for the upstream module overlay at 8k context /
  GPU-memory fraction 0.65. Wire the presenter to that qualified flow. Retain the
  qualified identity/offline bridge until an upstream replacement is tested.
  Any profile/placement change
  needs fresh qualification. Keep the automatic checkpoint
  with its creating DGD through the demo. Cross-node restoration, cached-context
  preservation and in-flight recovery are separate qualifications.
- **Snapshot upstream integration — open:** Neal will initiate a separate
  workstream for destination identity/context handoff with the restore proxy and
  preserving the destination Pod's Hugging Face offline policy. Generalize the
  qualification-specific assumptions and requalify an image containing the
  fixes before removing the runtime overlay. The private NVMe mount harness
  remains test plumbing. [Scope and acceptance](reports/2026-11-04-snapshot-upstream-status.md#open-upstream-workstream).
- **Composition:** combined request migration, GMS/Shadow, Snapshot and any
  KVCR-Guard recovery path still need their own evidence. Decide which parts
  will be live, recorded or vision slides; individual component successes do not
  qualify the combination.

### Delivery and take-home material

- Final Super VL runtime, upstream patches and tested feature combinations;
  requalify affected demonstrations after late changes.
- Publicly obtainable deployment/runtime/checkpoint artifacts, patch instructions
  and minimum hardware for deploying a Dynamo-managed service independently.
- Final rehearsal timings and confirmation of the preceding NVKE slot.

The integration cutoff may remain late. Keep the individual component
explanations usable independently so integration progress changes the final
demonstration content without requiring a new workshop structure.

## Measurements in progress

Status checked November 4 against the latest saved execution/cleanup receipts,
including the Snapshot NVMe audit at **4:39 p.m. Pacific**. The October 30 subagent
dispatch is historical; remaining measurements below are not automatically
running or queued.

| Workstream | Current status | Evidence and remaining work |
| --- | --- | --- |
| AgentX workload and shared-prefix analysis | Complete | Full pinned corpus and CPU-cache qualification; session-tree semantics and a named-sibling prefix example established. [Preparation](reports/workshop-measurements-20261030/agentx-workload/STATUS.md), [prefix evidence](reports/workshop-measurements-20261030/agentx-workload/BRANCH_PREFIX_FINDINGS.md). |
| One versus two replicas, RR, C1/C4 | Complete; locally verified | C4 closeout: **142 files, zero mismatches**, full raw archives and exact analysis reproduction. Two-worker request split **57 / 57**. Retain the C1 denominator caveat, realized turn-mix differences and C4 recovery pause; these are operational fixed-load pairs, not routing-policy or maximum-capacity results. [Closeout](reports/workshop-measurements-20261030/round-robin/C4_CLOSEOUT.md), [report](reports/workshop-measurements-20261030/round-robin/REPORT.md). |
| Scaling and routing load curves | Incomplete: 1/12 points; controller stopped | One-worker C16 passed (307 valid requests, approximately 89% GPU utilization); C32 warmup health timeouts and worker restart stopped the sweep. Neither two-worker configuration ran. All owned GPU resources/leases released; 451 evidence files verified. Resolve the restart before a fresh C16/32/64/128 matrix. [Failure report](reports/workshop-measurements-20261030/load-sweep/FAILURE_REPORT.md). |
| Text-only MX startup matrix | Complete; verified and cleaned | **492.79 / 280.10 / 173.61 s** for storage / peer weights / weights plus artifacts. Correct responses, matching GPU identities and actual both-rank cache reuse; **633 files, zero mismatches**, controller success and independent cleanup. [Results](reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_RESULTS.md). |
| Initial presenter demos 1–4 | Live functionality and recordings complete | Intro, weight-only MX, P/D transfer and native same-node Snapshot passed their own scoped checks. Their profiles and timing boundaries differ. The revised intro-to-MX flow passed live on November 7 UTC (492.98 → 247.01 s Ready; [receipt](reports/receipts/2026-11-07-modelexpress-intro-source.json)) and was recorded on November 8 (247.6 s; [recording](demos/transcripts/live/02-modelexpress/20261108-a1/main.txt)). [Recordings and qualification](reports/workshop-demo-recordings/STATUS.md). |
| DGD-led same-node Snapshot | Upstream-controller NVMe qualification and cleanup complete | **59 s replacement Pod-to-Ready; 99.11 s deletion-intent-to-observed-success; 36.86 s agent restore** from pre-staged NVMe. Correct streaming code through unchanged DGD/frontend/Service; identity/offline bridge remains at 8k context / memory fraction 0.65. Presenter wiring remains; no matched speedup claim. [Latest NVMe trial](reports/workshop-snapshot-dgd-nvme.md); [EFS reference](reports/workshop-snapshot-upstream-controller.md) retained separately. |
| Request-migration demo / load qualification | Standalone demo passed; load/SLO work remains | Disabled interrupted; enabled preserved 31 output tokens and completed on its pre-qualified peer. Correlated trace proves the retry; stale SSE attribution prevents an exact handoff-gap measurement. [Recording and evidence](reports/workshop-request-continuity-demo.md). |
| Super VL Shadow | Blocked in the latest model-specific receipt | No successful Super VL promotion measurement; separate Qwen TP1 control passed. Resolve the integration before under-load qualification. [Dated feature results](reports/2026-10-22-r610-feature-retest.md). |
| Two-engine KVCR-Guard | Nightly controlled retrieval and warm handback passed | a4 uses SHA-pinned Dynamo 1.7.0.dev20261103 wheels with the existing Super VL/NIXL 1.5 stack. After A died, pinned B retrieved six blocks / 99 MiB from the unchanged Guard and reused 4,224 input tokens while A's engine stayed absent. Replacement A then reused six local blocks / 4,224 tokens after handback, with zero remote deliveries. Both Guards and B stayed unchanged; source main restarted once. The first unpinned request failed 503 during discovery lag; automatic failover, stream migration, cross-node recovery and GMS remain unqualified. [Qualification](reports/workshop-kvcr-guard-qualification.md). |
| KVCR workshop demo and disaggregation performance | Deferred / experiment design outstanding | Existing feature and P/D functionality proofs remain valid in their recorded scopes; selected-workload performance and integrated recovery are not established. |

Snapshot's latest acceptance is recorded in
`results/workshop-snapshot-dgd-upstream-nvme-20261104-a1/state.json` and
`replacement-timing.json`; `qualification-exit.json` records success and lease
release, and `final-cleanup-proof.json` independently verifies no Snapshot-owned
GPU Pods/claims/DGDs or active GPU Pods on cp-0124, released Snapshot leases,
restored EFS view, preserved artifacts and no new GPU Xids. Concurrent RR/KV
resources on other nodes are preserved.
Use these terminal receipts for qualification status.
The earlier EFS observer's source-exit-137 correction remains in that run.
The NVMe run retains a corrected predeployment host-namespace `df` probe;
no deployment or capture was replayed.
The successful trial does not demonstrate request continuation or retained KV
cache. Agent restore, Pod-to-Ready and deletion-to-observed-response clocks are
reported separately. The native recording used its own artifact/profile; retain
its separate approximately 41 s Pod-to-Ready observation.

GPU assignments require coordinated reservations. Snapshot held its exact pair
on cp-0124; the separately authorized RR/KV run uses scoped reservations and
different GPUs on cp-0198/cp-0942. Shared EFS/network activity can still overlap.
Frozen specifications, results and detailed history are in
[the measurement tracker](reports/workshop-measurements-20261030/TASKS.md);
the current status above supersedes older "running" checkpoints in that history.

## Planning references

- [Original planning deck](https://docs.google.com/presentation/d/17gu2XLAuJU3C-0gVMxd25l-rCloky1mC/edit)
  — preliminary schedule and material; the decisions above supersede its outline.
- [vLLM automatic prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/)
  — shared-prefix reuse and its effect on prefill.
- [vLLM optimization and tuning](https://docs.vllm.ai/en/stable/configuration/optimization/)
  — scheduling, KV-cache pressure, and preemption considerations.
- [KV-aware routing concepts](https://docs.nvidia.com/dynamo/dev/knowledge-base/concepts/system-architecture/kv-aware-routing)
  and [router operations](https://docs.nvidia.com/dynamo/dev/knowledge-base/modular-components/router/router-operations)
  — worker events, prefix-state indexing, and balancing reuse with active load.
- [Native CPU KV offloading](https://docs.nvidia.com/dynamo/latest/knowledge-base/modular-components/backends/v-llm/native-kv-offloading)
  — engine offloading and the separate event configuration for router visibility.
- [KVCR design](https://github.com/ai-dynamo/kvcr/blob/main/docs/design_overview.md)
  — cache reuse, framework memory ownership, and NIXL-based peer data movement.
- [Dynamo disaggregated serving](https://docs.nvidia.com/dynamo/dev/knowledge-base/concepts/system-architecture/disaggregated-serving)
  — prefill/decode specialization, direct GPU transfer through NIXL, and
  workload-dependent performance tradeoffs. Checked November 3; qualify the
  actual transfer path against the pinned workshop runtime.
- [ModelExpress overview and architecture](https://github.com/ai-dynamo/modelexpress/blob/main/README.md)
  and [loading-path guide](https://github.com/ai-dynamo/modelexpress/blob/main/docs/guides/choose-a-path.md)
  — loader integration, peer discovery, NIXL transfer, storage paths, and
  compilation-cache reuse. Current upstream documentation; verify features
  against the runtime pinned for the workshop.
- [MX artifact deployment and compile-configuration pairing](https://github.com/ai-dynamo/modelexpress/blob/234497f0bc55c99ea1458338297b49ce88ab6f60/docs/DEPLOYMENT.md#pairing-workers-by-compile-configuration)
  and [MX startup benchmarks](https://github.com/ai-dynamo/modelexpress/blob/234497f0bc55c99ea1458338297b49ce88ab6f60/docs/BENCHMARKS.md#weight-and-kernel-artifact-transfer)
  — investigated October 30; file-cache reuse and its compatibility boundaries,
  distinct from Snapshot and from the workshop's weight-only P2P qualification.
- [Shadow Engine recovery blog](https://developer.nvidia.com/blog/restore-llm-inference-capacity-in-seconds-with-shadow-engine-recovery-in-nvidia-dynamo)
  — basis for section 3.2: persistent weights, a prepared standby, promotion,
  replenishment, and the published workload's recovery/service results.
- [Snapshot blog draft](https://docs.google.com/document/d/16-vzIprjNUO9_f4G-6z8ACzmmaUS81XI3OUg_1wADTk/edit?tab=t.0#heading=h.t6npw1ugvi0g)
  — basis for section 3.3, read November 3. Its engine-initialization benchmark
  boundaries and released KV cache matter when interpreting restoration.
- [Snapshot project](https://github.com/ai-dynamo/snapshot)
  — Kubernetes resources, compatible-node restoration, single-node workload
  scope, and the current caution against production-critical use.
- [Pinned frontend stream-error handling](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/http/service/disconnect.rs#L595)
  and [request migration](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/docs/fern/pages/kubernetes/fault-tolerance/request-migration.md)
  — the workshop runtime's stream-error path and frontend migration settings;
  source-level evidence, separate from a qualified injected-fault demonstration.
- Schwinn's October 27 Snapshot update, supplied during planning — informs the
  integration direction; prototype results do not establish workshop readiness.
- [Repository feature status](reports/2026-10-12-feature-status.md) and
  [October 22 retest report](reports/2026-10-22-r610-feature-retest.md) — dated
  qualification evidence, separate from this teaching plan.
