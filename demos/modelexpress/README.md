# ModelExpress: add capacity using the first server's weights

Run selection follows the [shared prepare/run/cleanup workflow](../../README.md#prepared-run-selection); each demo variant remembers its own run.

The first demo launches its server with ModelExpress enabled. With no existing
source, that server loads the staged checkpoint from storage and publishes its
GPU-resident weights. Leave it running: this demo adds a second server that
loads those weights over NIXL/EFA. Both use the same text-only eager Super VL TP2
configuration. Compilation-cache reuse is outside this demo.

## Try it offline

```bash
uv run python -m demos modelexpress --rehearsal
```

The familiar tmux layout shows the walkthrough, resources/phase timing, and the
new worker's logs. Enter/Space advances; commands appear first and another
keypress submits them. The main screen clears between steps, while startup
runs continuously after submission. `--plain` uses one terminal; `--preview`
shows the settings without cluster access. `--rehearsal --plain --auto`
exercises the flow unattended.

Rehearsal uses a simulated first server and illustrative transfer logs. It
creates no cluster resources and reports no measured timings or numeric speedup.

## Presentation flow

1. Explain that the first server already has the MX loader enabled, then show
   how the new worker discovers its weights: through the first server's
   `mx-source` Kubernetes Service, with no ModelExpress server. Full manifests
   remain available alongside the short teaching view.
2. Submit the second worker. Follow startup without further keypresses, then
   compare its timing with the first server's recorded storage startup. The
   comparison table nests the slowest rank's peer copy under model loading.
3. Inspect transfer evidence: receiving peer weights and completing the copy on
   both TP ranks, NIXL LIBFABRIC/EFA, and no storage fallback. One line per
   rank summarizes the copy; `peer-proof.json` keeps the Pod, claim and GPU
   identities off the projected screen.
4. Check the new server's HTTP endpoint and submit a small coding request.

The deck's demo cue slide splits the walkthrough: steps 1 and 2, then back to
the slides while the second worker starts (about four minutes), then steps 3
and 4.

Keep tensor-copy time, model-loading time and full readiness distinct. A fast
copy does not skip constructing and initializing the new engine.
The startup display reports total model loading from the slowest TP rank's
logged duration, with setup, loading and finalization beneath it. For peer
loading, the loading window includes both ranks; the nested peer-copy row
reports the slowest individual copy. Missing separate timing markers display
as `not timed`; they do not mean the work was skipped.

## Live preparation

Complete the single-replica presentation first and leave its server running:

```bash
uv run python -m demos single-replica prepare
uv run python -m demos single-replica
uv run python -m demos modelexpress prepare
uv run python -m demos modelexpress
```

Use the environment setup for your host from the
[single-replica guide](../single_replica/README.md#live-run). ModelExpress
`prepare` binds to the selected first run, checks its live source identity and
recorded storage startup, and prepares the peer target in that source's
namespace. To choose another compatible first run explicitly:

```bash
uv run python -m demos modelexpress prepare --source-run results/FIRST-RUN
```

`prime` remains an alias for preparation; it starts no workers. There is no
separate MX source or storage-baseline startup. The first server owns the GPU
reservation, and the second is registered as its dependent. Two TP2 workers
use **four H100 GPUs** in total, on different nodes.

The intro's new profile enables the MX loader before its first startup. An
older native-loader intro cannot publish its existing weights without a fresh
launch. Existing servers are never automatically restarted or replaced; finish
or explicitly clean up an old run before preparing the new intro profile.

The feature harness supplies pinned image/model identity, exact cached
checkpoint checks, EFS bindings, image-pull credentials, GPU DRA and EFA userspace.
The first server's `mx-source` Service supplies discovery within the shared
namespace. Redis and compiler-artifact transfer are unused;
`MX_ARTIFACT_TRANSFER=0` is explicit. See the pinned
[ModelExpress P2P documentation](https://github.com/ai-dynamo/modelexpress/tree/v0.6.0)
for the loading/discovery mechanism.

## What the comparison establishes

The storage record comes from the first demo's actual startup; the peer record
comes from the second server. Model, runtime and engine configuration must
match, and the original source Pod must remain Ready with the same UID and GPU
claim. Replaced or restarted workers cannot reuse the earlier proof.

These are two observed startups on different nodes, with a staged EFS checkpoint
and uncontrolled filesystem page caches. They illustrate the loading paths;
they are not a controlled same-node performance comparison or a cold-download
measurement. Separate matched experiments remain available in the historical
reports. Missing timings stay unmeasured.

The new graph, `demo-mx-target`, has its own HTTP frontend so requests verify
the target. The source keeps its original frontend. Shared traffic placement
is covered in the later routing demo.

Run files retain the source binding, frozen executable inputs, source startup
record, target logs/Ready Pods/timings, `peer-proof.json` and `comparison.json`.
A successful request alone is not proof of peer loading. A fallback or missing
TP-rank transfer stops acceptance.

## Cleanup and retry

Both servers stay running after the presentation. Remove the second server first:

```bash
uv run python -m demos modelexpress cleanup
# Only when the first server is no longer needed:
uv run python -m demos single-replica cleanup
```

ModelExpress cleanup deletes only its target graph and verifies the target's
Pods and GPU claims are gone. It then clears the dependency, preserving the
first server, its source Service, checkpoint storage and reservation.
Single-replica cleanup refuses while a dependent target remains.

Interrupted target startup resumes with its original apply timestamp. A missing
graph, changed source, or edited frozen input requires diagnosis or a fresh run.
Completed startup is not silently repeated. Use the exact `--run` and
`--rehearsal` mode when resuming an offline rehearsal.

## Live qualification

The revised flow, which reuses the intro server and its storage startup, passed
live on November 7 UTC and is accepted as qualified. Run
`results/demo-02-modelexpress-workshop_modelexpress_demo-1794033529267202411`
bound to intro run `results/demo-01-20261107T062808330356Z` in namespace
`dynamo-ft-r610-f2bd6ac3-demo`:

| Boundary | First server, storage | New server, peer weights |
| --- | ---: | ---: |
| Deployment to Ready | 492.98 s | 247.01 s |
| Model loading, slowest rank | 290.70 s | 50.15 s |
| Peer copy, slowest rank | — | 6.20 s |
| Engine initialization | 83.98 s | 82.57 s |

Both TP ranks received 39.22 GB over NIXL LIBFABRIC/EFA (4.23 s and 6.20 s)
from cp-0124 to cp-0198, with no storage fallback. The new frontend listed the
model and returned the expected `add` function. Observed readiness ratio:
2.00x. As [above](#what-the-comparison-establishes), this is one observed pair
on different nodes with an idle source, not a controlled same-node measurement.
That run has no main-panel transcript, and its target was cleaned on November 8
before the recording run below. The [receipt](../../reports/receipts/2026-11-07-modelexpress-intro-source.json)
lists identities, settings and evidence hashes.

On November 8 UTC the same flow was recorded against the same intro server. The
[main-panel recording](../transcripts/live/02-modelexpress/20261108-a1/main.txt)
shows the new worker Ready 247.6 s after apply (493.0 s from storage), copies of
4.22 s and 3.24 s, and the expected `add` function. Use it as the fallback if the
live demo cannot run. That intro/MX pair was left running for the presentation
([receipt](../../reports/receipts/2026-11-08-modelexpress-recording.json)).

## Historical validation

The earlier isolated text-only eager presenter runner passed a live qualification on
November 4 UTC: both TP ranks received peer weights over LIBFABRIC/EFA, no
storage fallback occurred, and the target returned the expected code. This
single matched pair reached Ready in 459.4s from storage and 250.0s with peer
weights. Source and target were cleaned and the lease released afterward.

The [actual main-panel recording](../transcripts/live/02-modelexpress/20261104-a1/main.txt)
includes the comparison and transfer excerpts. Compiled startup experiments
remain separate from this eager run. Offline flow, actual tmux key gates and
safety checks are also validated. The earlier API/tunnel outage was resolved
before live execution; no competing lease was taken over.


A November 5 recapture preparation completed the MX source's startup, but API
transport disappeared while observing the native target. The fresh peer arm
was never started, and both owned graphs/claims were cleaned afterward. This
interrupted preparation does not replace the successful recording above.
The [closeout notes](../../reports/overnight-2026-11-04/BASELINE-MX.md)
retain the exact failed attempt, source result, cleanup proof and remaining
observer wall-clock/presentation questions. Compact command display and the
canonical observer changes have offline coverage; no new full live MX capture
is claimed from that attempt.
