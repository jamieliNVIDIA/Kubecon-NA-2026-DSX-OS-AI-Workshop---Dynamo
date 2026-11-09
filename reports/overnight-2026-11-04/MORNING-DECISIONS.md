# Open workshop review questions

Updated: November 5, 2026, 4:19 PM Pacific. These prompts describe the evidence available now and the
choices still worth discussing; they are not a new agenda. The [original
morning questions](MORNING-DECISIONS-20261105-CHECKPOINT.md) and
[morning review](MORNING-REVIEW.md) are historical. [REVIEW.md](REVIEW.md) is the
current results entry point and takes precedence as active experiments advance.

## Audience-facing flow

Keep the agreed order: single-replica service and metrics, then ModelExpress,
routing, KVCR and disaggregation. Return to aggregated serving for resiliency
and explain that simplification. Keep the coding-agent workload throughout.
Use each launcher's documented preview, rehearsal or prepared-live path;
prepared live captures retain their offstage preparation explicitly.

## Questions worth settling

| Question | What is established | Decision or remaining gate |
| --- | --- | --- |
| Which routing comparison deserves projector time? | [C16](routing-sweep/C16-RESULTS.md) has an accepted three-cell comparison and [recorded presenter](../../demos/transcripts/recorded/06-routing/c16-20261105-a1/recorded-main.txt). The fresh [C32 two-worker pair](routing-c32/C32-RESULTS.md) is independently accepted: RR/KV output rate 500.12/525.23 tokens/s and TTFT p99 30.68/7.12 s, with **lower mean decode speed per user** under KV. | Keep C16 as the existing recorded default, or import the accepted C32 pair into a fresh recorded walkthrough. C32's one-worker arm failed during warmup after a liveness restart, so it supplies no scale-out ratio. Neither campaign establishes a capacity knee; do not splice C16/C32 into a controlled curve. |
| How should KVCR demonstrate moving state to spare compute? | [Actual a6 recording](../../demos/transcripts/live/07-kvcr/20261105-a6/main.txt) and [independent audit](../../results/workshop-kvcr-demo-20261105-a6-independent-audit/terminal.json) prove controlled cross-node peer reuse: six blocks / 103,809,024 bytes, 4,224 external/cached tokens. The common prefix is 6,406 tokens against a 4,224-token page; the earlier short-prompt failure is historical. | Decide how much proof collection to show live. Source/target projected steps took **224.8/216.0 s**, while HTTP to DONE was **19.55/19.43 s**. Keep the experimental pin, prepared-worker and explicit-target scope visible. Automatic load-aware placement, under-load benefit and production readiness remain unqualified. |
| Is Super VL Shadow ready for a live slot? | The instrumented v4 writer remains live-qualified, independently audited and cleaned. Full-a2 completed v5 read-only weight import and runtime reconstruction on both ranks, then failed later in native `deep_gemm_warmup` when generic ModelOpt code read missing `w13_input_scale`. It closed **before any fault**: the [1,221-file independent audit](../../results/shadow-full-a2-independent-audit-a1/verification.json), fresh health/resource checks and [exact lease closeout](../../results/workshop-shadow-full-a2-root-closeout-20261105-a1/complete.json) passed with no new Xids. | Reader v6 restores two ordinary optional attributes to match source-verified native postprocessing; its source and CPU program are reviewed. The [actual-image CPU gate passed](../../results/workshop-shadow-reader-v6-cpu-live-20261105-a1/check-reader-v6-source-cpu-1793924266908711000.json) for all 80 roles with CUDA uninitialized; independent result acceptance is still pending. No v6 GPU startup, active/parked readiness, three-stream correctness, fault, promotion, replenishment or recovery result follows. Keep a slide/recorded fallback until the live gates pass. [Reader repair and scope](SHADOW-READER-V6.md). |
| Which Snapshot output should the presenter use? | The [integrated DGD/NVMe a3 recording](../../demos/transcripts/live/04-snapshot-dgd/demo-04-dgd-live-20261105-a3/main.txt), 9,283-file independent audit, two correct coding streams, automatic replacement, final resource/storage audit and local lease release all passed. A durable offstage controller solved the source-lifetime coordination gap without extending the stock deadline. | Review the [compact offline projection preview](snapshot-projection-a1/rehearsal-main.txt) for teaching clarity. Its output-only changes were locally checked; the new layout has no fresh live recording. Keep it separate from the immutable passed capture. Explain **59 s Pod-to-Ready**, **64.29 s deletion intent to observed Ready** and **33.89 s agent restore** as overlapping, separate clocks. No uncached physical-SSD or matched cold-start speedup claim. |
| How much continuity performance should we claim? | [Paired C4 proof](../../demos/transcripts/live/05-request-continuity-load/README.md): baseline 4/4 in both modes; after fault, enabled 4/4 versus disabled 2/4. Both affected enabled streams retain output and have peer-retry evidence; both cases are cleaned. | Choose the clearest terminal outcome and stream view. Functional continuity is qualified. HTTP 200 alone is insufficient; an inter-content gap is not an exact handoff clock. Latency SLOs and capacity recovery under load remain separate measurements. |
| Does disaggregation need a performance-win slide? | [Both original equal-four-GPU AgentX arms](disagg/RESULTS.md) are independently accepted and cleaned: aggregate/P-D **174.75/174.36 output tokens/s**, 313/312 successful records and zero errors/cancellations/overflows. P/D transferred 37.75 GB without transfer/notification failures. Observed tails improved while medians slowed. Earlier demo 03 separately proves the live coding/SSE handoff mechanism. | Lead with different resource needs, specialization and independent scaling. Use the accepted pair for a sizing/tradeoff discussion if useful, with fixed-order N=1/shared-resource limits. Its [console package](../../demos/transcripts/live/03-disaggregated-agentx/20261105-a2/README.md) is actual benchmark output, not a new presenter PTY or coding-answer validation; raw SSE bodies were not retained by that benchmark. |
| What can an attendee deploy afterwards? | [Public cached take-home baseline](../receipts/2026-11-05-take-home-public-baseline.json) actually served and was cleaned: official unmodified development nightly, DRA/H100 pair, explicit compatible cache UID and corrected Service selector. This is beyond dry-run qualification. [The guide and limits](../../take-home/QUALIFICATION.md) record the exact image/version and failed predecessors. | Decide whether to teach the tested development nightly or qualify a later stable release. **Fresh network weight download, device-plugin serving and advanced feature compositions remain open.** Existing-cache permissions and private qualification placement are not portable guarantees. |
| When should the first deployment begin? | The [resumed intro](BASELINE-MX.md#intro-a2-resumed-result--passed) preserves original apply-to-Kubernetes-Ready **1,459.397 s**, logged loading **1,246.701 s** and engine init **83.34 s**. The much longer morning-observation clock includes the outage. Shared EFS contention prevents treating those values as an isolated startup benchmark. Earlier MX presenter evidence remains qualified; the later fresh repeat stopped before peer loading and adds no matched result. | Rehearse starting offstage, overlapping startup with explanation, or using the existing recording. Be explicit about setup/pre-existing startup and retain the original clocks. A cleaner uninterrupted booth retake is optional; do not require another expensive run merely to re-prove a passed service. |
| How should persistent ModelExpress support demo development? | The requested persistent CPU/RAM server and per-candidate local staging are being prepared so later starts can use MX instead of silently reusing the existing absolute EFS cache path. The [official server CLI check](../../results/workshop-mx-server-cli-20261105-a1/check-mx-official-server-cli-1793923711870644000.json) passed. Actual a2 ModelService RPC resolved the pinned revision/88-shard inventory and verified one **35,661,352-byte sample**. The [capability receipt](../receipts/2026-11-05-mx-cpu-cache-capability.json) separates this success from the [original failed wrapper](../../results/mx-dev-cache-capability-20261105-a2/terminal.json), which incorrectly required Torch not to be imported. | Complete independent acceptance and qualify the persistent cache plus local-staging path on fresh candidates. Keep strict model revision and distinguish metadata/sample access from a fully seeded RAM cache, faster startup or GPU/GMS/MX loading. The probe requested no GPUs, but did not measure CUDA initialization. It does not supply a new workshop performance result. |
| How much of the unified startup/recovery story is demonstrable? | MX, Snapshot and the instrumented GMS writer each have distinct evidence and runtime limits. KVCR's mechanism passed under its explicit experimental bundle. Full-a2 advanced through read-only import/reconstruction but failed warmup before readiness or fault; persistent MX preparation is a separate development effort. There is still no accepted integrated MX/Snapshot/Shadow reader-and-promotion demonstration. | Label the individual demonstrated capabilities, experimental integrations and future unified service separately. Preserve the adoption story without turning successful component tests into a production-ready integration claim. |

## The overload slide now has direct Kubernetes evidence

The fresh C32 one-worker cell passed exact model discovery and smoke requests,
then failed during mandatory warmup. Saved logs show long-prefill progress while
queued inference canaries exceeded their deadline. The Kubernetes event at
**20:51:20 UTC** explicitly says `Container main failed liveness probe, will be
restarted`; Pod status records one restart and exit 1, without an OOM reason.
The failed arm was rejected and preserved; it was not replayed.

This supports a short cloud-native example of liveness removing productive
capacity under overload, alongside admission/rejection policy. Attribution of
every queued request to canaries and any proposed remedy remain unproven.
Review existing busy-aware health and liveness/readiness work before filing a
duplicate. [C32 failure evidence and limits](routing-c32/C32-RESULTS.md#one-worker-failure-liveness-restarted-a-progressing-engine).

## Compare readiness of the deliverables

| Deliverable | Ready evidence | What still separates it from the final workshop version |
| --- | --- | --- |
| Single replica / ModelExpress | Live-qualified historical presenter recordings; intro's resumed service/identity/cleanup checks passed. The official MX server CLI and a bounded CPU ModelService RPC/metadata/sample-read probe passed their own checks. | First-deployment pacing and optional cleaner booth retake. Persistent CPU/RAM service and fresh per-candidate local staging are in development; the probe's wrapper remains a failed attempt. No new GPU load, peer comparison, full RAM seed or integrated GMS/MX qualification. |
| Routing / metrics | C16 recorded presenters; accepted C16 comparison and fresh C32 two-worker pair. | Choose the comparison and presentation length. C32 benchmark logs are not yet a C32 presenter recording; one-worker C32 is rejected. |
| KVCR | Actual a6 main-panel capture, independent 48-source/417-evidence audit and scoped cleanup passed. | Reduce visible proof-collection pauses if desired, keeping the accepted capture immutable. Experimental controlled reuse is not an automatic-routing or performance claim. |
| Disaggregation | Earlier live mechanism recording plus the accepted equal-four-GPU benchmark pair and actual console package. | Explain neutral total throughput and mixed latency tradeoffs; choose whether the comparison earns projector time. |
| Request continuity | Paired live C4 proof and cleanup passed. | Select stream/SSE teaching view; no workload SLO or capacity-recovery qualification. |
| Snapshot | Full integrated NVMe presenter and final closeout passed; compact layout has a separate offline preview. | Choose layout/recording. Identity/offline upstream bridge remains separately owned; a cosmetic preview is not a new live qualification. |
| Take-home service | Public cached DRA/H100 serving and cleanup passed. | Stable release, fresh download, device-plugin serving and other compositions still need their own qualification. |
| Shadow | Instrumented v4 writer live-qualified, audited and cleaned. Full-a2's v5 read-only import/reconstruction succeeded, but later warmup failed; its failure collection, live health/resource audit and exact lease closeout passed. Reader v6 actual-image CPU execution passed; independent result acceptance is pending. | No parked-ready GPU reader, correct serving, intentional fault, promotion, replenishment or qualified recovery capture. A source/CPU repair and a closed failed startup are distinct from full live qualification. |

The last combined local suite passed **631/631** in **56.804 s**
([original log](../../results/workshop-resumed-local-suite-20261105-a7.log))
**before the later v6 and persistent-MX changes**. It does not validate
those later edits or substitute for their independent and live gates.
Full-a2's closeout records the release of the exact reservation after its
failed startup; it does not turn that attempt into a ready/recovery result.

The [original morning questions](MORNING-DECISIONS-20261105-CHECKPOINT.md) retain
the short-prefix, expired-source, unstarted-benchmark and dry-run-only statuses
as historical observations. They are not current blockers. Keep successful and
failed attempts separate; a collection/observation interruption is not evidence
of an engine failure, and later success does not relabel an earlier failure.

[Current results and recordings](REVIEW.md) · [Execution checkpoints](RESUMED.md) ·
[Upstream versus workshop follow-ups](UPSTREAM-CANDIDATES.md)
