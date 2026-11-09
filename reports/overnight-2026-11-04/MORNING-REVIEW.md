# November 5 review packet

**Historical morning checkpoint.** See [REVIEW.md](REVIEW.md) for the latest
verified results and remaining work.

Closed out after the morning VPN recovery and final cluster audit at **10:20
a.m. Pacific**. The work produced runnable presenter drafts, actual recordings
and additional live evidence, but not every new demo passed its live gates.
No commits, pushes, external messages or upstream submissions were made.

| Deliverable | Actual status | Review material / remaining work |
| --- | --- | --- |
| Single-replica introduction | **Live-qualified** resumed recording; scoped cleanup passed | [Actual main panel](../../demos/transcripts/live/01-single-replica/20261105-overnight-a2/main.txt). Startup uses the original Kubernetes Ready transition, not the overnight observation delay. Earlier booth retake remains available. |
| ModelExpress | Earlier presenter recording remains qualified; new overnight comparison **incomplete** | [Notes](BASELINE-MX.md). Fresh source reached Ready; native observation lost transport, and peer never started. No new matched speedup result. Failed evidence frozen before cleanup. |
| Routing | **Measured C16 comparison accepted**, recorded presenter passed | [C16 results](routing-sweep/C16-RESULTS.md), [actual recorded walkthrough](../../demos/transcripts/recorded/06-routing/c16-20261105-a1/recorded-main.txt). Three cells; C32 never profiled. |
| KVCR | **Offline-rehearsed; live attempt failed its fixture gate** | [Notes](KVCR.md). Source prompt was 3,247 tokens versus the effective 4,224-token hybrid cache page; no complete offload block and no receiver request. Needs a longer token-verified common prefix and a fresh immutable attempt. |
| Disaggregation | Earlier mechanism recording qualified; new equal-GPU comparison **prepared only** | [Notes](DISAGG.md). CPU/cache/admission gates passed; neither new GPU arm started. No aggregate-versus-P/D performance result. Borrowed CPU/cache/evidence retained. |
| Request continuity under C4 load | **Live-qualified**, both modes independently verified and cleaned | [Actual consoles and paired proof](../../demos/transcripts/live/05-request-continuity-load/README.md). Baseline 4/4 in both modes; after one fault, disabled 2/4 and enabled 4/4. |
| Integrated DGD Snapshot / NVMe presenter | **Offline-rehearsed; live capture artifact passed, integrated flow incomplete** | [Notes](SNAPSHOT.md). Artifact reached Ready, then held source Job expired before staging/restore verification. Optional deadline extension was rejected at server dry-run with no write; continuation never launched. Prior native and DGD/NVMe qualification remain separate valid evidence. |
| Super VL Shadow Engine | **Blocked on runtime compatibility** | [Notes](SHADOW.md), [writer candidate](SHADOW-WRITER-CANDIDATE.md). Original run produced read-only write faults; writer-only candidate passed CPU checks but was never GPU-tested. Source inspection found an additional MoE lock allocation outside its coverage. |
| AgentX metrics walkthrough | **Recorded-evidence presenter passed** | [Actual walkthrough](../../demos/transcripts/recorded/09-agentx-metrics/overnight-20261105-a1/recorded-main.txt). Historical measurements, not a new live performance result. |
| Take-home managed service | **Offline tests and 14/14 client/server dry-runs passed** | [Attendee guide](../../take-home/README.md), [notes](TAKEHOME.md). Public compatible runtime/version selection and actual attendee-profile deployment remain release gates. |

## What the new evidence supports

On this AgentX C16 workload, adding a second round-robin worker increased output
throughput only **2.7%**. Cache-read declined from **93.87% to 87.15%**. On two
workers, KV routing raised cache-read to **91.03%** and reduced observed TTFT p99
from **15.40 s to 5.17 s**, with nearly flat aggregate throughput. Use this to
explain the routing tradeoff. These are fixed-order N=1 measurements with low
active request concurrency; they do not establish a capacity knee, universal
speedup or stable production tail percentile.

The C4 continuity experiment proves two affected streams each retained output
and retried on the qualified surviving worker. All sixteen HTTP requests across
the two modes returned 200, including the two broken disabled streams: terminal
SSE outcome matters. This is functional continuity, not AgentX throughput,
recovered capacity or an SLO qualification.

## Suggested next iteration

1. Review the new C16 routing and C4 continuity main panels for teaching clarity.
2. Fix KVCR fixture sizing against the actual tokenizer and effective hybrid
   page before another expensive startup; prove the common prefix contains full
   offload blocks. Preserve the failed attempt.
3. Make Snapshot's offstage coordinator durable and handle the held source Job
   within its creation-time lifetime. Do not try to patch an immutable
   SnapshotJob spec. Qualify staging, first inference and replacement together.
4. Complete Shadow's mutable workspace inventory, including linear and MoE
   helpers, before testing a revised writer-only candidate. Keep reader shape
   handling and promotion as separate gates.
5. Run the prepared equal-four-GPU P/D comparison and, if useful, a fresh C32
   routing attempt with exact frontend-model readiness. Keep locked workload
   controls and full admission/drain windows.
6. Select the public take-home runtime and test the generated service on the
   supported allocation mode. A successful dry-run does not prove serving.

## Validation and cleanup

The final local suite passed **350/350 tests** in
`results/overnight-local-suite-final-20261105-a2.log`; `git diff --check` passed.
The previous final-suite attempt exposed a stale routing capture-test path.
That test now exercises both the C16 and historical recording profiles; no
runtime code was changed for that correction.

Fresh cluster inventory at **18:20:06 UTC** found **24 advertised GPUs, zero
allocated GPUs and no allocation issues**. Every local workshop GPU lease is
absent. Scoped cleanup receipts cover MX, KVCR, migration, Snapshot and the
CPU-prepared Shadow writer candidate. Artifacts, caches, namespaces and the
explicitly borrowed routing CPU client remain retained. Shared platform,
operators, drivers and unknown workloads were not changed.

Private final audit:
`results/overnight-20261105-final-audit-postcleanup-a1/audit.json`.
Failed captures, original logs and earlier passing recordings remain intact.
Snapshot's generic cleanup message does not imply a new NVMe copy: this attempt
never staged one; its captured EFS artifact is retained.

The obsolete overnight heartbeat deletion and pause were attempted again; the
app returned an internal hook error. **Neither action is confirmed.** The status ledger marks the
work closed and tells any delayed heartbeat to retry deletion without restarting
experiments. [Upstream candidates](UPSTREAM-CANDIDATES.md) distinguishes concrete
runtime findings, packaging gaps and local harness improvements.
