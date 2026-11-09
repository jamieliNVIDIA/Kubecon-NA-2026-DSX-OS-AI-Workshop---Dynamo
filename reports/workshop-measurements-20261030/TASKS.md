# Workshop measurement workstreams

Requested October 30, 2026. Measurements run in parallel with outline development.
Shared GPU allocations are serialized. The November 4 RR/KV run has explicit
authorization for separate GPUs/nodes alongside Snapshot; see its scoped plan.

## Task list

1. Gather parameters (model, hardware, dataset, ISL/OSL, concurrency, request rate)
2. Create a locked spec (`create_spec`) — user confirms, parameters become IMMUTABLE
3. Verify endpoint healthy (curl `/v1/models` on the frontend)
4. Run the benchmark (`run_profile`)
5. Fetch and analyze results (`get_results`)
6. Compare to previous runs if relevant (`compare_runs`)

The user's request authorizes gathering these measurements on the workshop's
Super VL configuration with AgentX traces/settings. Preserve those choices.
Resolve bounded load points from the actual AgentX implementation and serving
limits, record complete immutable specifications before execution, and never
silently substitute another workload/model or modify a locked run. If the MCP
spec schema cannot express AgentX semantics, use a fully recorded CLI spec with
the same immutability and provenance guarantees rather than relabeling a generic
synthetic run as AgentX.

## Workstreams

| Workstream | Scope | Current state |
| --- | --- | --- |
| AgentX workload preparation | Verify AIPerf AgentX flags, trace identity, session/concurrency semantics, and fixed profiles | Complete |
| Round-robin scaling | Compare one TP2 worker with two under the same AgentX offered load and explicit round-robin routing | C1/C4 complete and locally verified |
| Scaling and routing load curves | AgentX C16/C32/C64/C128 for one RR, two RR, two KV workers, common engine cap 128 | Incomplete: one-worker C16 passed; C32 warmup worker restart stopped controller November 4 at 18:49 PST. Evidence/cleanup verified November 6. Neither two-worker configuration ran. |
| MX startup | Compare storage, MX peer weights and compatible compiler artifacts; separate loading from complete startup | Final text-only matrix complete and verified |
| Synthetic scale-out and routing | AIPerf user-centric synthetic load, labeled synthetic and not AgentX: one TP2 worker versus two with RR and KV at matched per-worker load; health canaries off in every cell | Complete November 8, 08:02 UTC; all eight cells clean, cleanup verified. Below one worker's limit a second raised TPS/user, not throughput; at 128 agents KV routing raised throughput 1.70× (round-robin 1.26×). 2RR-64 was accidental session affinity, not a round-robin result. At 128 agents the slowest tenth of turns took 140 s on one worker, 113 s with round-robin and 54 s with KV routing. [Results](synthetic-scaleout/RESULTS.md), [plan](synthetic-scaleout/PLAN.md), [status](synthetic-scaleout/STATUS.md) |
| AgentX C32 one-worker cell | The C32 pair's missing one-worker RR arm, rerun with health canaries off on cp-0942 GPU0/2; everything else as the November 5 campaign | Complete November 8, 09:44 UTC; clean (602 requests, zero errors), cleanup verified. Round-robin's first-token p95 was 11.5 s against 2.0 s on one worker and 2.8 s with KV routing. [Results](agentx-c32-one-worker/RESULTS.md), [plan](agentx-c32-one-worker/PLAN.md) |

Original dispatch: `agentx_workload`, `round_robin_scaling`, and `mx_startup`.
That dispatch is historical; current results and outstanding work follow below.

### Higher-load scaling and routing sweep — stopped November 4; verified November 6

Only one of twelve points completed: one-worker RR C16, 307 valid requests,
zero errors/cancellations, mean decode 112.43 tokens/s/user, TTFT p50 251.93 ms,
approximately 89% GPU utilization. C32 failed during snapshot-primer warmup
after repeated health timeouts and a worker restart; exit 139 includes a
segfault during shutdown, whose initiating cause is not established. All
remaining points and both two-worker configurations did not run.

The controller is terminal, all owned GPU resources and scoped leases are
released, and 451 evidence files / all 37 C16 final-inventory entries are
verified locally with no mismatches. One expired Failed CPU client remains.
The original analyzer reconstructed C16 successfully. Resolve the warmup/health
interaction before a fresh run; no matched scale-out or routing result exists.
[Failure report](load-sweep/FAILURE_REPORT.md), [status](load-sweep/STATUS.md).

The user selected C16/C32/C64/C128 live AgentX trees across one-worker RR,
two-worker RR and two-worker KV. The engine's previous four-sequence cap is
raised consistently to 128, subject to live engine admission before profiling.
All twelve points retain the pinned full corpus, model, runtime and canonical
replay settings. Fresh workers per configuration; retained workers across its
ascending load points, fresh cache-bust namespaces and normal primers per run.
This is at least three hours of profiling plus preparation/startup/drain.

Controller `kubecon-workshop-load-sweep-20261104-a1` consumed
the frozen plan; its namespace and scoped lease used only cp-0198/cp-0942.
Other workstreams keep cp-0124 and their global reservations. [Plan](load-sweep/PLAN.md),
[status](load-sweep/STATUS.md).

### Preceding low-load RR/KV comparison — user-stopped November 4

`results/workshop-rrkv-20261104-a1` freezes four arms: C1 RR → C1 KV → C4 RR →
C4 KV, each with fresh worker Pods and canonical AgentX preparation. The new
discovery guard counts only `kv-events` connections and matches their hosts to
the current worker Pod IPs. Eight regression tests and the original failed-log
fixture pass. C1 preliminary results are available below. The user stopped
the campaign during C4 startup to replace these low loads with the larger sweep.

The detached controller started at 00:27:25 UTC November 5 (November 4 local).
It used a separate routing reservation on cp-0198/cp-0942, four exact H100 UUIDs,
and namespace `dynamo-ft-rrkv-20261104-a1`. Other workstreams retained cp-0124
and the global reservation.
The pinned model/runtime, full 393-trace AgentX corpus, C1/C4 session-tree loads,
900 s admission plus 300 s drain and generation settings are preserved. Both
policies use text-only and fast health settings. Positive observed KV overlap,
valid error-free exports, complete evidence and scoped cleanup remain required.

Update at 17:47 PST: CPU qualification and C1 RR/KV passed; C4 round-robin
workers are loading weights with zero restarts. Preliminary C1 TTFT p50 is
381→313 ms, p99 5.82→2.90 s and cache-read 95.08%→97.62%; active decode is
149.18→149.86 tokens/s/user. Canonical aggregate rates use different 900/1,200 s
denominators, so their ratio is not a capacity result. Full local pullback
completed after the stop: **680 files, zero mismatches**, no owned GPU workers,
claims or DGDs, and both scoped leases released. The old CPU client was deleted
at 18:02 PST after checking its UID. [Preserved plan](rr-kv/PLAN.md),
[terminal status](rr-kv/STATUS.md).

### C4 scale-out closeout — completed November 4

Collected `results/workshop-rr-20261103-resume02` into fresh verified staging at
`results/workshop-c4-closeout-20261104-a1/`: **142 files, zero mismatches**.
Both final arm inventories (33 / 35 files), original intermediate inventories,
raw archives and recovery/stage receipts pass. Each embedded raw archive's
14 regular files matches its extracted counterpart. The unchanged original
analyzer reproduces every remote result except the export's relocated path.

Both submissions are complete, valid and uncancelled, with zero request errors,
context overflows or cancelled profiling records. Profiles/scientific pins match
and the original worker UID survived scale-out. The second arm served **57 / 57**
requests, with 56 main / 57 subagent / 1 flat requests, versus 61 / 60 / 1 in r1.
GPU means during the 900 s admission window were **35.47–37.22%**, versus
**65.42–65.46%**; all GPUs have 180 samples. No complete agent graph finished.
Canonical rates remain **81.16 → 75.31 tokens/s**; active-user generation speed
**139.79 → 151.52 tokens/s/user**. C4's rate denominators both cover 1,200 s.

C4's stage exited zero and verified cleanup. The original enclosing controller
later exited one at the C1 KV guard; its failure is preserved, not relabeled.
The fresh namespace audit found zero GPU Pods/ResourceClaims/DGDs; the failed
non-GPU client Pod is retained. This closeout used only remote reads and local
analysis, changed no cluster resources/leases and performed no benchmark replay.
Older local partial mirrors are unchanged. Retain N=1, fixed-load, different
turn mixes, the recovery pause and the earlier multimodal-capable serving profile.

[Closeout and artifacts](round-robin/C4_CLOSEOUT.md). Remaining routing work is
the fresh RR/KV comparison described in the [diagnosis](round-robin/KV_DISCOVERY_DIAGNOSIS_20261104.md).

### Updated compiled baseline and matched MX rerun — November 4

The user authorized promoting text-only and the qualified faster worker-health
settings, then remeasuring MX on versus off. The versioned baseline is
`configs/dgd/super-vl-textonly-fast-startup/`. All seed/receiver workers use
`--language-model-only`, canary wait 1 second, startup period 2 seconds /
failure threshold 1,800, and readiness period 2 seconds. Native context, TP2,
four sequences, 8,192 batched tokens, memory fraction 0.85 and pinned image are
unchanged. This compiled profile is separate from the eager presenter demos.

Fresh run: `results/workshop-mx-startup-20261104-baseline03/`, spec SHA256
`e0efc532518c7cc3e9e8ad3907ed81f966ae114ca8f166cbdb141f040eb3f3e7`.
One retained idle seed and three fresh receiver arms: native storage with all
MX settings removed, MX peer weights only, and MX peer weights plus artifacts.
All non-MX receiver settings match; 27 frozen inputs and the offline control
mutation checks passed. Live correctness, GPU identity, peer transfer, real AOT
cache use and cleanup all passed.

Controller `kubecon-workshop-baseline-20261104-a3`, ID
`689c467d1dcdb12fd3633deb45686b705a2979553a4b8554d1817dff66160197`,
started November 4 at 19:38:19 UTC (11:38 a.m. Pacific). Plan SHA256
`2c801b85ae4fb6953dcf480e747cb205faaaaa3316874f5c47264933208932ac`.
Payload SHA256 `c61bc18d8f95c9c52a0975afc7d0837a428de9b8b9f767602763ccadb002bda0`.
Its queue independently rechecks prior terminal success, namespace cleanup,
node readiness, GPU availability and lease absence before preparation. The
local delegation fence was released after verified remote completion/cleanup.

**Completed:** observed Ready was **492.79 s native EFS → 280.10 s MX weights →
173.61 s MX weights plus artifacts**. All arms used the same physical receiver
GPUs, distinct Pods and fresh caches. Model loading was **267.39 / 52.57 /
48.66 s**; engine initialization **143.90 / 149.12 / 40.53 s**. Both TP ranks
actually loaded the published compiled graphs in the artifact arm. All controls
and correct READY responses passed; no worker restarted and neither peer arm
fell back to storage.

Controller exited zero at 20:05:40 UTC (12:05 p.m. Pacific). Verified pullback:
`results/workshop-baseline-pullback-20261104-a3/`, **633 files, zero mismatches**.
Final independent audit at 20:06:14 UTC verified zero owned Pods/ResourceClaims/
DGDs and no remote lease, then released the exact local fence. Receipt:
`results/workshop-baseline-final-cleanup-20261104-a3/receipt.json`.
The separate Snapshot workstream's requested handoff was written to
`results/workshop-snapshot-dgd-20261104-a1/gpu-handoff.json`; it must acquire its
own lease. No startup continuation or replay is queued.

[Matched results and limits](startup-optimization/MATCHED_BASELINE_RESULTS.md).
This remains one fixed-order trial per arm with five-second Ready polling,
existing EFS weights, uncontrolled host page cache and one idle seed. The seed's
own storage bootstrap was 512.42 s. The full MX receiver was 2.84× faster than
the native baseline, a 319.18 s / 64.8% reduction.

Baseline01 served a correct source response, then failed qualification because
the validator compared raw startup probes against API-defaulted probes. The
operator also supplies the liveness policy. Its complete evidence is preserved
in `results/workshop-baseline-failed-pullback-20261104-a1/`: 271 files, zero
mismatches, controller exit one, zero Pods/claims/DGDs, and no remote lease.
Baseline02 was an offline-only validator draft. Baseline03 handles probe and
Downward API defaults, passes the captured real source Pod, and rejects actual
policy changes. Serving controls are identical to baseline01; neither frozen
attempt is edited or relabeled as a successful matched measurement.

[Plan](startup-optimization/MATCHED_BASELINE_PLAN.md).

### Follow-up startup optimization research — November 3

The user selected text-only Super VL for the coding-agent workshop workload.
The user subsequently authorized executing the candidates, starting with
text-only. A fresh seed plus MX weights-and-artifacts receiver pilot is ready
for the stable controller, after the current fixed routing queue.
It retains native context, TP2, sequence/batch limits, memory fraction, image
and current probes. Its comparison to artifact04 is initially an unpaired
single-trial comparison; later candidates must have separate identities.

**Qualified text-only result:** pilot02 completed, verified correct inference
and both-rank compilation-cache use, and cleaned all its resources. Its receiver
reached observed Ready in **188.8177 s**, compared with the historical multimodal
artifact arm's 249.6991 s. Engine initialization was **41.21 versus 74.44 s**.
The observed 60.88 s total reduction includes **22.88 s of health/probe-tail
variation under unchanged policy**; it is an unpaired N=1 comparison. Source
bootstrap began at 06:49:30 UTC on November 4 (November 3 Pacific). Verified
pullback: 443 files, zero mismatches, zero remaining Pods/claims/DGDs and no
remote GPU lease.

**Completed health experiment:** the matched text-only default-versus-fast
pair ran as `kubecon-workshop-health-20261103-a1`, controller ID
`03712d3c27495bab8e66d871666370dcfca8395fa1dca306bae47123d40de958`.
Source bootstrap began at 07:06:23 UTC. Same model/engine limits, GPU UUIDs,
compiler artifacts and one idle seed for both receiver arms. Observed Ready was
**188.8552 → 178.7937 s**, a 10.06 s / 5.33% reduction. Engine initialization was
**40.63 → 40.58 s**; the post-engine tail was **23.5581 → 9.0380 s**. Only worker
canary/startup/readiness policy differs. Its 3,600 s startup failure budget is
nominal, not a claim of equal worst-case hung-probe detection. Both arms passed
correctness/cache gates. Verified pullback: 488 files, zero mismatches, terminal
controller success and zero remaining Pods/ResourceClaims/DGDs in the namespace.

Combined results and limitations:
[STARTUP_RESULTS.md](startup-optimization/STARTUP_RESULTS.md).
Both new experiments are complete; no continuation or automatic replay is queued.
Triton persistent tuning is already enabled by vLLM; adding its enable flag is
not a third optimization. The remaining startup targets require profiling/code
work rather than a supported bypass of correctness-related tensor discovery.

Execution access was restored after the earlier approval-system failures.
The original routing controller had stopped at the C1 KV discovery/event-
ingress qualification check; its GPU cleanup and absence of leases/locks were
independently verified before this separate pilot. Its C4 routing pair did not
run. The failed routing run is preserved, without a claim that the pair passed.

The first CPU preparation for text-only timed out connecting the coordinator
to Redis before any GPU batch began. Its logs and failed controller a4 are
preserved. The same CPU coordinator manifest was retried after Redis readiness,
then the unchanged preparation passed and a5 started the first GPU batch.

- [Pilot02 plan](startup-optimization/TEXT_ONLY_PLAN_02.md)
- Frozen run: `results/workshop-mx-startup-20261103-textonly02/`.
- Completed text-only controller: `kubecon-workshop-textonly-20261103-a5`, ID
  `a25a5e257b7ffb73467d73c4733dffca70e82b91cc7934698c0d15974f4b45ee`.
- Reviewed controller: `results/workshop-textonly-controller-prep-20261103-a5/`.
- Plan SHA256: `b19c8d4364e64d5e3bbb1f35d86aa9f694fd03b584907e7c9c376140426567b0`.
- Payload SHA256: `0869701d4d883a97659d6ec356e923d440b067e94ad0587a27ac359f6e983c80`.
- Read-only snapshots: `results/workshop-textonly-controller-observations-20261103/`.
- Verified text-only pullback: `results/workshop-textonly-pullback-20261103-a1/`.
- Health pair: [plan](startup-optimization/TEXT_ONLY_HEALTH_PLAN.md),
  `results/workshop-health-controller-prep-20261103-a1/` and read-only snapshots
  under `results/workshop-health-controller-observations-20261103/`.
- Final independent audit verified all four owned benchmark namespaces have
  zero GPU Pods/ResourceClaims/DGDs, both test nodes have no GPU workloads and
  remote leases/old controller locks are absent. The matching local execution
  fence was released. Proof: `results/workshop-startup-final-cleanup-20261103-a1/`.
  The failed CPU `rr-loadgen` Pod is retained as historical evidence. Do not
  replay accepted startup batches or historical controllers.

The installed vLLM supports `--language-model-only`; it is the first follow-up
startup candidate. This is a **new configuration to qualify**, not a change to
the live routing comparisons or the completed full-multimodal MX results.
The accepted experiments used matching MX source/target and fresh compilation
artifacts. Original benchmark inputs/results remain preserved; all startup GPU
ownership is now released.

The earlier routing stop was a qualification bug: its checker counted six ZMQ
connections across three topics, rather than the two KV-event connections.
The static logs establish both KV-event endpoints and both worker identities,
but the KV AgentX arm never ran. See
[diagnosis](round-robin/KV_DISCOVERY_DIAGNOSIS_20261104.md); fixing and rerunning
that measurement is separate from these completed startup experiments.

Research and proposed experiment order:
[startup-optimization/OPTIONS.md](startup-optimization/OPTIONS.md).
Other opportunities are probe/canary cadence and the roughly 41 s MX hidden
tensor-discovery walk; static source inspection has not measured their gains.

### Historical checkpoint — November 3, 4:43 p.m. Pacific

The stable host controller is running. Its original C4 pair completed, passed
acceptance/analysis, and verified cleanup. MX artifact04 then completed its full
matched comparison, verified actual engine cache reuse on both TP ranks, and
cleaned its GPU resources and coordinator. The first matched routing-policy
pair (C1) is now underway; C4 follows it.

One matched MX trial per target arm, same native-context Super VL TP2 H100
configuration and image:

| Loading path | Deployment to observed Ready |
| --- | ---: |
| Native EFS storage | 553.59 s (9m14s) |
| MX peer weights | 340.86 s (5m41s) |
| MX peer weights + compilation artifacts | 249.70 s (4m10s) |

The artifact arm passed the actual both-rank engine cache-hit gates, not only
file-transfer checks. The weight-only versus artifact arm's engine initialization
was 179.07 versus 74.44 s; startup phases overlap and must not be summed.
All three target arms were observed on the same stable controller. These are
single-trial observations with idle source and preexisting storage weights.

C4 scale-out, one paired observation at four live session-tree slots: 122 versus
114 successful requests and zero request errors. Mean active-generation speed
was 139.79 versus 151.52 tokens/s/user; canonical aggregate output was 81.16
versus 75.31 tokens/s, with matching canonical denominators. Cache-read rate was
95.79% versus 90.72%; TTFT p50 was 306.19 versus 477.59 ms. Keep the inter-arm
transport pause/observer change, realized workload, N=1 and capacity limits
visible. The matched routing comparisons are needed to assess placement's role.

Evidence snapshot (read-only remote probe):
`results/workshop-stable-controller-20261103/status-a1/status.json`.
Its timestamp is 2026-11-04T00:43:33Z. It contains accepted analysis summaries,
MX comparison and phase analysis, actual outcome classification/cleanup proof,
and the live controller state. Full result pullback/final sealing remains.

### Stable host controller setup — November 3

The completed C4 first arm was recovered and accepted, preserving its original
profile, worker/client identities and scientific settings. The remaining fixed
continuation now runs detached on the existing workshop bastion instead of
depending on the laptop's SSH API tunnel.

- Host: `ip-172-31-10-102` / `ubuntu@3.238.63.5`.
- Docker container: `kubecon-workshop-controller-20261103`, ID
  `5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411`.
- Started at 23:34:29 UTC. Last verified state: original C4 worker Ready,
  second worker deployed and initializing. No complete C4 pair result yet.
- Physical workspace:
  `/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace`.
  The container mounts it at the original logical repository path, preserving
  immutable absolute references and all benchmark settings.
- Fixed sequence: original C4 second arm, validation/analysis/cleanup, then
  MX artifact04 and the C1/C4 routing-policy pairs through the reviewed driver.
- Local snapshot/provenance:
  `results/workshop-stable-controller-20261103/REMOTE_STATUS.json`.
  This is a timestamped snapshot; use the remote controller for current state.

The root reviewed and verified 314 allowlisted staged files and the container's
imports/131 controller inputs before launch. The pinned CPU controller image
uses Python 3.12.16/PyYAML 6.0.3. The inference runtime and cluster-side AIPerf
client remain unchanged. Existing bastion Kubernetes access is mounted read-only;
credentials were not copied from the laptop.

**Ownership:** the local GPU lease is now an execution fence owned by
`/root/stable_controller`. Its original metadata is preserved. The remote
controller owns the live run/lease inside its staged workspace. Do not execute
historical local recovery, cleanup or GPU launch commands. Inspect the remote
job and verify remote cleanup before releasing the local fence or starting
another GPU workflow. Subagent completion alone does not mean this detached
controller or its measurements have finished.

### Historical recovery — November 3, after C4 transport interruption

The laptop-launched continuation exited at 23:01:43 UTC after TLS timeouts
and loss of its SSH API tunnel. This occurred during the first C4 profile;
the second arm, MX artifact04 and routing-policy pairs never started. RR's
lease was retained because cleanup could not reach the API.

Root subsequently reconnected the same tunnel successfully. The VPN route is
currently `utun4`; the precise cause of the earlier transport drop is not
established. The original worker/client UIDs survive with zero restarts.

The detached cluster-side C4 first arm finished with exit 0 at 23:13:21 UTC.
Root collected and accepted it at 23:20:02 UTC: 122 measured requests, zero
request errors and zero cancelled profiling records. Its sealed spec/profile,
runtime, source, cache hashes and original Pod identities were verified.
Evidence is in `recovery-c4-r1-a1/` under the resume02 run. The first arm was
not replayed; no second-arm or comparative C4 result is claimed yet.

The retained worker/lease are being preserved for the original second arm.
The existing stable workshop bastion has Docker, Python and an existing user
kubeconfig that reaches the same cluster. An owned CPU controller is being
prepared there to remove the laptop-tunnel dependency without changing the
inference image, workload, settings or cluster-side benchmark client.

### Historical active continuation — November 3, after second VPN restoration

The user restored VPN access again. The original SSH tunnel was restarted and
all three original workshop nodes passed a live Ready check. Existing successor
agents `mx_resume` and `round_robin_resume` were resumed.

- MX collected and cleaned interrupted artifact03. Independent checks found
  zero GPU Pods, zero ResourceClaims and zero graphs before lease release.
  Final recovery evidence has 372 verified files. Fresh artifact04 preserves
  the scientific spec/effective manifests and passed CPU preflight.
- RR preserves the accepted C1 pair. Its replacement client passed full-corpus
  reconstruction in 488.05 s with matching cache hashes, 32.01 GB peak memory
  and no OOMs. The previous C1 reference verified all 67 sealed files.
- The reviewed root-launched continuation controller is active:
  `results/workshop-rr-20261103-resume02/continuation-a1/STATUS.json`.
  Its C4 first worker is deployed and initializing. The fixed next stages are
  the fresh matched MX artifact retry and both matched router-policy pairs,
  with analysis and verified cleanup between GPU turns.
- A fresh MX retry preserves the native-context scientific settings and the
  metadata-only correction. Artifact03 remains an interrupted historical run.
- Root launched the networked continuation because child-agent
  escalations fail with an execution-hook payload mismatch. This is separate
  from the restored cluster/VPN connection. The agents continue overseeing
  local provenance and results without duplicate execution. The controller
  records commands, process/exit receipts and stage status, checks 128 frozen
  inputs, and stops on transport, identity or cleanup failures. It preserves
  any ineffective-artifact result before allowing independent RR work only
  after positive cleanup. No scientific parameters are automatically tuned.
- Per-workstream live status and receipts record actual execution. Restored
  access and resumed agents do not themselves establish another result.

### Historical reconciliation — November 3, before second VPN restoration

Both successor agents have stopped; no measurement agent is active. Cluster
SSH/API access failed again during the MX turn. The local SSH control socket
is absent on today's check; current remote resource state remains unverified.

- RR completed and validated the C1 one-versus-two-worker pair with zero request
  errors/overflows: 84 versus 82 measured requests, active-generation speed
  154.05 versus 152.14 tokens/s/user, TTFT p50 322.22 versus 423.78 ms, and
  cache-read rate 97.62% versus 94.75%. Its report explains unequal drain/rate
  denominators; the apparent canonical throughput increase is not a capacity
  speedup. This one-tree low-load pair does not establish capacity limits.
- RR verified its GPU cleanup before handing the lease to MX. C4 and both
  matched routing-policy comparisons remain unstarted.
- Corrected MX artifact03 passed CPU preflight, source serving qualification
  and compiler-artifact publication. Connectivity failed while the native
  target initialized. No peer/artifact target ran; no target cache-reuse or
  compilation-cache speedup result exists. Its controller exited, and MX
  retains its lease because finally-cleanup could not reach the API.
- Recovery must first restore cluster access and collect/verify cleanup of MX's
  owned graphs, Pods and claims before releasing its lease or resuming RR.
  Preserve artifact03 and use a fresh immutable attempt for any artifact retry.

See `round-robin/REPORT.md`, both live `STATUS.md` files and their `RESUME.md`
instructions for completed evidence and exact recovery gates.

### Historical resume after VPN restoration — November 2

The user restored VPN access and explicitly authorized continuing the existing
measurements. The SSH API tunnel was restored and all three original workshop
nodes passed a live Ready check. Successor agents `round_robin_resume` and
`mx_resume` are executing the existing plans; the workload analysis is complete.

- RR collected recovery evidence and verified zero old owned GPU worker Pods
  and ResourceClaims, then released its retained lease. Receipts are in
  `results/workshop-rr-20261030-prep-1705/recovery-vpn-resume-20261102`.
  It is recreating/requalifying the expired CPU client/cache before a fresh
  immutable C1 one-versus-two-worker pair.
- MX prepares its corrected metadata-only artifact configuration and waits for
  RR's explicit cleanup/handoff. Its native-context storage/peer/peer-plus-
  artifacts matrix follows C1, then hands the GPUs back for RR C4 and the
  approved matched routing-policy comparisons.
- All model/runtime/corpus pins and scientific parameters remain unchanged.
  No new performance result is implied by the restored access or dispatch.
  Per-workstream `STATUS.md` and live receipts record actual progress.

### Historical status reconciliation — November 2, before VPN restoration

No measurement subagents are currently active. The completed result below
remains valid; subsequent attempts stopped before producing performance results.
The local API tunnel is absent on today's check. Network-failure details are
the agents' last saved observations from October 31, not a fresh remote probe.

- AgentX source/data/profile preparation and full-corpus CPU qualification
  completed. The follow-up also found named parallel siblings with 72,320
  matching leading recorded token units (about 94% of input) and 5.085 s
  recorded overlap. General full-parent context inheritance was not supported;
  see `agentx-workload/BRANCH_PREFIX_FINDINGS.md`.
- The first MX weight-only paired comparison completed. The later artifact02
  comparison stopped after its coordinator exceeded a 2 GiB cache limit and
  was evicted; legacy download-path configuration also contaminated target
  timings. Its owned GPU resources were cleaned and its lease handed to RR.
  A corrected artifact03 candidate was prepared but not run on GPUs. There is
  no effective compilation-cache reuse or artifact-speedup result.
- RR deployed its first worker, then lost cluster API access before readiness
  qualification or profiling. Zero AgentX inference profiles/performance
  requests ran. Its controller stopped; cleanup could not be verified, so its
  lease remains retained. The later SSH probes timed out and the previous VPN
  route was absent. See `round-robin/CONNECTIVITY_BLOCKER.md`.
- Recovery must first restore access to the same workshop cluster and inspect,
  collect and clean RR's owned resources. Verify or recreate the expired CPU
  client/cache before any fresh immutable attempt. Do not assume Pod deadlines
  prove resources are gone or delete RR's lease without verifying cleanup.

### Historical checkpoint — October 30

- MX completed one matched 8k-context startup pair: native EFS loading took
  524.67 s from deployment to observed Ready; peer weights took 315.51 s
  (1.66x). See `mx-startup/REPORT.md` for conditions and evidence. This is a
  single pair with an idle source and artifact transfer disabled.
- MX now owns the GPU turn for a separate native-1M-context storage/peer/
  peer-plus-artifacts matrix. Its source passed the exact-model correctness
  probe and advertised context window 1048576. Compiler artifacts were
  published; effective target cache reuse remains unproven while the arms run.
- RR completed full-corpus CPU preparation in 484.7 s, with measured peak
  memory 31.98 GB and a 6.04 GB reusable data cache. No AgentX inference or
  one-versus-two-worker throughput result yet. It awaits the coordinated GPU
  handoff before fresh native-context serving qualification and timed arms.
- The workload agent is checking exact shared prefixes and child scheduling
  in the existing traces to assess the parallel-subagent explanatory example.
  This does not change the locked benchmark workload.

Initial AgentX preparation identified a required qualification step: the saved
Super VL feature manifests cap context at 8192, while the canonical real AgentX
scenario must preserve its trace context. Qualify a new immutable, common server
configuration for the two replica arms; leave the original feature locks intact.
Do not truncate or relabel the workload to make it fit. The exact limits remain
subject to source/runtime validation by the agents.

## Established configuration

- Use `configs/super-vl-tp2-lock.json` and the recorded workshop manifests as the
  starting configuration. Preserve Super VL, its revision, vLLM, and TP2 on H100.
- Inspect live cluster state before deployments. Use fresh, labeled resources
  and immutable run directories; preserve other workstreams and existing runs.
- No shared operator, driver, allocator, storage, or queue changes. No global
  filesystem-cache flushing. No changes to `slides/` or the workshop outline.
- A candidate runtime or loader configuration, if needed, must be recorded and
  all comparison arms using it must share the same runtime. Do not mix a runtime
  upgrade into an MX-only performance claim.
- Workload shape, trace/seed, generation settings, load points, repetition count,
  warm-up/cache procedure, timeouts, and metrics must be recorded before a run.
- Distinguish active agent/session concurrency from simultaneous HTTP requests.
- Report completed/failed/partial sessions and requests, per-user decode speed,
  TTFT/ITL/latency distributions, aggregate throughput, and cache/routing evidence.

## GPU execution coordination

The original shared-allocation workstreams use an exclusive lease directory:

`.local/workshop-measurements-20261030.gpu-lease/`

Acquire with atomic directory creation, record the owning agent/workstream and
run in `owner.json`, and release only your own lease after owned GPU workloads
are quiescent/cleaned. Do not delete another workstream's lease. Coordinate
directly through collaboration messages. Parallel CPU/source/spec preparation is
allowed. Release the lease during lengthy CPU-only builds or external blockers.

Authorized exception, November 4: the fresh RR/KV controller uses
`.local/workshop-rrkv-20261104.gpu-lease/` for four frozen GPUs on cp-0198/cp-0942
while Snapshot retains its own cp-0124 GPUs and the global lease. This is not
permission to ignore other reservations or alter either allocation. Each
workstream verifies and cleans only its own namespace, claims and lease.

The user-selected higher-load replacement uses
`.local/workshop-load-sweep-20261104.gpu-lease/` on those same four GPUs in
namespace `dynamo-ft-load-sweep-20261104-a1`. The preceding routing leases are
released. cp-0124 and its global reservation are currently used by the KVCR
workstream; preserve them. The new controller rechecks all four selected UUIDs
before each deployment rather than treating the global lease as a cluster-wide
ban on distinct GPU allocations.

## Evidence and reporting

- Committed-style summaries and locked specs belong beneath this directory, in
  a separate subdirectory per workstream. Raw evidence belongs in fresh ignored
  `results/` directories and must include an integrity/provenance manifest.
- Capture exact image/model/tool versions, manifests, commands, actual placement,
  timestamps, routing policy, workload hashes, logs, and client/server metrics.
- Successful inference or peer transfer alone is not a performance measurement.
- Preserve failed attempts and report blockers. No commits or pushes are needed.
- Keep this page's initial-state entries historical; each workstream should
  maintain its own live `STATUS.md` and final report.
