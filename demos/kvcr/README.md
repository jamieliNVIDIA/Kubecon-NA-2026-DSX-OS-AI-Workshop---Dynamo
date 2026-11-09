# Demo 7: reuse another worker's context

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

The router can balance cache locality against available compute. KVCR gives a
worker another option: retrieve committed state from a peer's host pool, then
continue using its own GPU. This walkthrough shows what that buys in first-token
latency, on a workload built to make the mechanism visible.

A main agent reads a long synthetic repository on worker A (about 58K tokens,
`--max-model-len 65536`). Its subagent forks with the same repository and a new
question, and lands on worker B, which has spare compute but has never seen the
repository. B serves two subagent requests of the same size, side by side:

- a repository nobody has read, which B must compute from scratch, and
- the main agent's repository, whose pages B fetches from A's host pool over EFA.

Every question asks which file defines a function planted once in the
repository, so a correct answer depends on the whole context, including the part
that came from A. The headline number is the frontend's time to first token for
each request (it excludes the presenter's port-forward).

This is an **experimental, pinned runtime composition**: matching Dynamo nightly
wheels, a vLLM KVCR adapter and the KVCR preview service on the existing native
vLLM/NIXL base. It is not a statement of production support. Guard is present in
the pinned service but this scaling demonstration injects no process failure.
The workload is tailored to the mechanism: warm idle workers, one long shared
prefix and requests pinned by hand. It is **not an AgentX benchmark** and says
nothing about automatic routing or behavior under load; present benchmark
results for that.

### Status and earlier runs

The speedup profile (`super-vl-kvcr-speedup-v3`) passed on the workshop placement
on November 9 UTC (A on cp-0198, B on cp-0942, over EFA) during the workshop-day
staging pass, and its workloads/claims were cleaned. Its
[main-panel recording](../transcripts/live/07-kvcr/20261108-cp0942-a1/main.txt) and
[receipt](../../reports/receipts/2026-11-09-kvcr-speedup-cp0942.json) are retained:

| Request | Prompt | Reused | First token |
| --- | ---: | ---: | ---: |
| A · main agent · its repository | 58,390 | 0 | 2,436 ms |
| B · subagent · unseen repository | 58,399 | 0 | 2,559 ms |
| B · subagent · main agent's repository | 58,400 | 54,912 | 305 ms |

B's first token arrived **8.38× sooner** with A's context: 54,912 tokens in 18
blocks (0.29 GiB) over EFA, matched on both ends; every answer named the planted
file. With B on cp-0124, the November 8 runs passed at 7.84× (a3:
[recording](../transcripts/live/07-kvcr/20261108-a3/main.txt),
[receipt](../../reports/receipts/2026-11-08-kvcr-speedup.json)) and 8.37× (a2), and
seven exploratory rounds on warm workers ranged from 7.8× to 8.7×. Recorded in
`--auto` mode, the walkthrough uses 15–19 s of cluster time. Startup and warm-up
happen in `prime`: about 12 minutes to Ready with EFS to itself, 35 minutes while
three other demos were loading.

Two primes stopped before readiness for the same reason. Each engine's container
start downloads the pinned nightly wheels; the download was cut off (November 8
a1 on engine A, and the first staging attempt on engine B, at 29 of 84 MB), and
the presenter refused the restarted Pod. The bootstrap now retries a cut-off
download in place. A fresh prime with it passed on the workshop placement on
November 9; every download succeeded first time, so the retry path itself is
covered by offline tests. Prime on the workshop day early enough to start a
fresh run if a prime still fails.

The previous qualified run used the legacy two-request walkthrough:
its [main-panel recording](../transcripts/live/07-kvcr/20261105-a6/main.txt)
passed on November 5, and the scoped workloads/claims were cleaned. A computed
a cold prompt; B reused **4,224 tokens through six matched blocks / 103,809,024
bytes over EFA**. Both returned READY. The [qualification receipt](../../reports/receipts/2026-11-05-kvcr-peer-reuse.json)
links acceptance and cleanup evidence. That run could not show a speedup: at its
8,192-token context one 4,224-token page is the most a request can reuse, and on
warm engines that saved about 60 ms of a 260 ms prefill. Each engine's first
request also paused about 18 s after its first token; later requests did not.

Legacy runs, and the `kvcr-prepared` children bound to them, keep the
two-request walkthrough. New runs use the speedup profile.

```bash
uv run python -m demos kvcr --preview
uv run python -m demos kvcr --rehearsal
uv run python -m demos kvcr --rehearsal --plain --auto
```

The presenter uses the established silent Enter/Space gates, clears between
screens, and shows commands before submitting requests. Tmux includes read-only
resources and per-worker logs. `--plain` uses one terminal. Rehearsal reports no
measured cache bytes, reused tokens, first-token times or startup duration. Its
simulated pair is already primed and warmed before the visible walkthrough begins.

## Live preparation

Four H100s, two TP2 workers and EFA are required. The default
[placement](placement.json) pins the workshop's assigned GPU UUID pairs on
cp-0198 and cp-0942; `--placement FILE` freezes a different reviewed allocation
for a fresh run. A per-run lease never takes over another chat's reservation.
Each worker Pod requests four EFA devices for its engine and one for its host
service. This is a functional test budget, not a throughput comparison to the
older eight-EFA engine qualification.

The complete renderer derives from the qualified two-engine Guard template;
`deployment.yaml` remains executable and inspectable. `kvcr-settings.yaml` is
the focused explanation. Exact model/image/source/placement inputs and hashes
are frozen in every run.

On this development checkout, the runner can reuse the hash-verified source
bundle from the preceding KVCR-Guard qualification. To recreate it from public
sources instead, use:

```bash
uv run python -B -m demos.kvcr.prepare_sources \
  --output results/my-kvcr-sources

uv run python -m demos kvcr prepare --auto \
  --source-bundle results/my-kvcr-sources/bundle-592cda9d1831d1ece346b1185eca54d67488a9eb02bc6d8b8cdc62e79a88bc4d.tar.gz
uv run python -m demos kvcr prime --auto
```

Source preparation checks every downloaded artifact and the final deterministic
bundle hash. It does not deploy or qualify serving. Nightly wheels are downloaded
and SHA-verified inside each private container overlay. A cut-off or corrupted
download is retried in place, up to five attempts 2–16 s apart, so it no longer
restarts the container; each failed attempt logs `KVCR_DOWNLOAD_FAILED`. The recipe still needs
the workshop cluster's existing cached exact model, pull credentials, GPU DRA,
EFA runtime, operator and namespace preparation. A portable public base image is
an open take-home dependency; the pinned base currently uses the author's NGC
registry. No global package or shared operator is changed.

`prime` verifies the cached exact model, CPU API compatibility, driver-only host
service isolation and actual CUDA UUIDs, then starts the engines. A cheap CPU
tokenizer check first rejects a short or oversized fixture against reference
limits before allocating the native-probe/engine GPUs. Its receipt does
not establish the new workers' live geometry. After both
current workers are Ready and registered, it checks their effective cache-page
and context limits from live logs. A CPU-only process uses the exact cached
tokenizer/revision to tokenize every frozen request body with its real chat
template arguments. Priming succeeds only if the shared repository covers at
least ten effective pages, the control repository shares no reusable page with
it and is within 2% of the subagent prompt's size, and every prompt plus output
budget fits the live context limit. No generation happens during this check.

`prime` then warms both engines offstage, recorded in `warmup.json`: A answers a
question about a separate small warm-up repository, and B answers another about
the same repository, fetching it from A. Each engine's first request pauses after
its first token, and the first A-to-B transfer opens the EFA path. Neither should
happen onstage. Both warm-up answers must name the planted file, and the engine
logs must show the EFA provider.

The profile sets `--max-model-len 65536` and an 8,448-token prefill chunk (two
effective pages) through `KVCR_MAX_MODEL_LEN` and `KVCR_MAX_NUM_BATCHED_TOKENS`;
the Guard qualification keeps its 8,192-token defaults. A 4 GiB host pool per
worker holds the warm-up, shared and control repositories (about 1.2 GiB each).

Finish all model-asset downloads before starting replicas. The qualified runtime
includes ancillary metadata files in strict model-card compatibility; adding
documentation/image files to a shared snapshot during worker registration can
leave Ready Pods in different admitted cohorts. Pod readiness and `/v1/models`
alone do not establish that both workers joined the serving frontend. The
[retained-parent investigation](../../reports/overnight-2026-11-04/KVCR-PREPARED-CHILD.md)
documents the explicitly recorded repair and fresh-child workflow; use the
`07-kvcr-prepared` capture mapping for those bound cases.
After binding a prepared child, run `uv run python -m demos kvcr-prepared prime`
offstage too. This checks the retained workers and preflights the child's fresh
request bodies; it never starts or replaces workers. Cleanup remains the owning
parent's responsibility.

`prompt-preflight.json` binds the token counts, actual geometry, request hashes
and current Pod UIDs. Source generation refuses a missing, failed, stale or
changed receipt. Server prompt-token usage is later checked against both measured
counts. Existing byte/transfer/cached-token/identity gates remain in force.
The requested `--block-size 64` alone is not treated as the effective page size.

Startup, source staging and token/page preflight happen offstage. Keep the same
run and workers for presentation. A live `run` requires `prime` to have completed;
it never starts engines or repeats tokenizer preparation during the walkthrough:

```bash
uv run python -m demos kvcr

uv run python -B -m demos.common.capture \
  --demo 07-kvcr --run results/my-kvcr-demo \
  --output demos/transcripts/live/07-kvcr/my-attempt

uv run python -m demos kvcr cleanup --auto
```

If preparation stops before all CPU/native/admission gates finish, preserve its
receipts, clean up that attempt and use a fresh run. These preparation gates and
immutable source ConfigMaps are intentionally not replayed in place. Once
preparation completes, interrupted engine startup can continue on the same run
with its original startup clock; primed/onstage steps can resume as below.

The walkthrough can resume completed steps: it explicitly reports reuse of the
same run's saved response/evidence and sends no replacement HTTP request. A
partial or failed HTTP attempt cannot be replayed under the same evidence names;
use a fresh run. Cleanup removes only
its graph/Pods/claims and releases its reservation; it retains the namespace,
model cache and evidence.

## What the audience sees

1. The scenario and focused settings: who runs where, the 65,536-token context,
   and the state path from A's GPU to A's host pool, B's host pool and B's GPU.
2. Two Ready, warmed workers and their separate host pools; startup and warm-up
   completed offstage.
3. The main agent's request, pinned to A: its answer and time to first token. A
   polls its metrics until the committed host-pool write has settled, then shows
   how much context A kept and that B has not processed it.
4. Two subagent requests pinned to B. The first carries a repository nobody has
   read (computed from scratch); the second carries the main agent's repository,
   whose pages come from A. Each shows its answer, first token and reused tokens.
5. The comparison: prompt size, reused tokens and first token for all three,
   with bars, the speedup on B, and the matched transfer (tokens, blocks, bytes
   over EFA).

Every step checks worker identity once and reads metrics with two short execs.
Commits and transfer receipts are awaited by polling until the counters hold
still, not with fixed sleeps. Transfer receipts come from the log interval since
the control request, not from full log downloads. Behind the summary, the gates
are unchanged: matched source/target operation IDs, blocks and bytes, positive
external-cache tokens, cached-token usage and zero failed/partial deliveries. The
control request must reuse nothing.

The synthetic repository explains the mechanism. It is **not an AgentX
benchmark** and establishes no under-load speedup or improvement to automatic
router decisions. The requests are pinned to isolate the path; the earlier
routing section explains why spare compute may make B attractive. Retrieval
copies reusable state; A's copy need not disappear. Both engines remain serving
throughout.

## Validation

The speedup profile adds offline checks for the deterministic repository and its
planted functions, the long-context runtime overrides (Guard defaults unchanged),
the tokenizer program's per-request and per-pair counts, the preflight gates
(shared pages, cold like-for-like control, context room), the frontend-timing
stream record, polling until counters settle, the cold-control refusal, the
summary, legacy-profile routing and the v3 capture binding. The live result is
under Status above.

The legacy profile's results follow. Nineteen focused offline checks cover exact allocation, EFA budget, lease-scope
restoration, receipt matching, absent-cache rejection, rotated-log refusal,
replay refusal, native-probe claim garbage collection, public artifact validation,
interrupted-preparation refusal, effective hybrid-page detection, undersized or
overflowing prompt refusal before HTTP, exact submitted-body compatibility and
the full rehearsal without cluster calls.
A real three-pane tmux rehearsal and a `rehearsal_passed` main-panel capture also
passed. The parser also
reproduced the retained a4 six-block/99-MiB/4,224-token ordinary reuse receipt;
that is historical evidence. The fresh a6 result independently qualified the
cross-node path. The prepared adapter/Guard/v2 suite passed 51 tests; all 20
capture tests passed, including immutable repair provenance after cleanup.
Source and B's HTTP streams took about 19.5 s each, while their projected steps
took 224.8 / 216.0 s because of comprehensive guard, log and commit checks.
Presentation polish and first-request token pauses remain open; no cosmetic
rerun replaced the successful recording. Full live status and upstream notes are tracked in
[the overnight report](../../reports/overnight-2026-11-04/KVCR.md).
