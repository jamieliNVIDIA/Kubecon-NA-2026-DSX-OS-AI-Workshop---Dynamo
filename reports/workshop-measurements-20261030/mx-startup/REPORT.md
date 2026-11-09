# ModelExpress startup measurements

## Completed native-context matrix — raw pullback verified

The stable controller completed one matched Super VL TP2 H100 trial per target
arm. Its accepted results and verified owned cleanup were observed through the
read-only remote snapshot at **2026-11-04T00:43:33Z** (November 3 Pacific).
The completed MX logs/proofs and driver phases have now been pulled back:
**560 selected files verified, zero hash mismatches**. Final combined campaign
evidence sealing remains separate from this verified raw pullback.

| Boundary | Native EFS | MX peer weights | MX weights + compiler artifacts |
| --- | ---: | ---: | ---: |
| Deployment → observed Ready | 553.59 s | 340.86 s | 249.70 s |
| Deployment → first correct response | 555.76 s | 343.21 s | 251.96 s |
| Model loading, slower TP rank | 265.99 s | 61.37 s | 57.68 s |
| Engine initialization | 176.04 s | 179.07 s | 74.44 s |
| torch.compile, slower TP rank (within engine init) | 26.57 s | 28.34 s | 0.15 s |
| Initial profiling/warmup, slower TP rank (within engine init) | 80.70 s | 81.70 s | 27.72 s |

Peer weights improved full observed readiness **1.62×** relative to native EFS.
Adding compatible compiler artifacts improved readiness another **1.37×**
relative to peer weights alone: **91.16 s / 26.74% shorter startup**. Combined,
readiness was **2.22×** faster than this storage baseline. These ratios compare
only the three artifact04 targets; the older 8k pair below is separate.

Local raw-log checks confirm actual AOT compilation-cache loads on **both TP
ranks**, from the installed cache root, and no unused/recompile-on-load-failure
warning matching the frozen checks. The native and peer-weight-only engines
spent about 27–28 s in compilation; the artifact target logged 0.15 s. Warmup
also fell from 81.70 s to 27.72 s. File transfer alone was not the acceptance
gate. The two later installed-cache-selection messages are duplicate Worker 1
logging; the distinct TP0/TP1 AOT-load paths establish the two-rank result.

### What remains in the 249.70 s startup

The exclusive timeline is about **8 s deployment/container start + 63 s
pre-loader boot + 58 s model loading + 75 s engine initialization/handoff +
46 s to observed readiness**. Inside model loading, hidden accelerator tensor
adoption takes about 41 s per rank in parallel, while actual NIXL copies take
5–7 s. Compiler-artifact lifecycle installs total 0.972 s, inside model loading.
The readiness tail includes endpoint setup and canary/probe progression; exact
successful health/probe times are not logged, so it cannot all be attributed
to compute or waiting. See [STARTUP_BREAKDOWN.md](STARTUP_BREAKDOWN.md) for
timestamped boundaries, evidence lines, nested timers and uninstrumented gaps.

### Conditions and interpretation

- One fixed-order trial per arm: native storage, peer weights, peer weights plus
  artifacts. No repeat distribution is claimed.
- Same locked Super VL model/revision, runtime image, TP2 H100, native context
  1,048,576, four sequences, 8192 batched tokens and memory fraction 0.85.
- A compatible source stayed idle apart from normal health/canary activity and
  the tiny correctness probe. No AgentX benchmark load ran during these timings.
- Existing exact-revision EFS checkpoint; no external model download. Host page
  caches were uncontrolled and never globally flushed. Target compiler caches
  were fresh per Pod before the selected artifact installation.
- Source on cp-0124 and every target on cp-0198; centralized metadata discovery,
  NIXL LIBFABRIC/EFA weight transfer. Each peer target transferred 1,869 tensors /
  40.27 GB per TP rank; raw transfer/proof logs are locally verified.
- All target model/context identities and correct READY responses passed remote
  validation with zero restarts. Observed readiness uses five-second polling.
  The first correct response follows evidence collection and is an upper bound
  on first-possible inference. Logged initialization subphases overlap and must
  not be summed.
- This measures startup with an idle source. Serving-source interference,
  request latency/SLOs under traffic and production integration maturity require
  separate evidence.

The remote driver independently verified zero owned GPU Pods, ResourceClaims,
DGDs and coordinator/Redis Pods, with the lease released at
2026-11-04T00:36:54Z before entering routing C1. The continuing routing stages
now own any active benchmark resources; local GPU execution remains fenced.

### Evidence status

Snapshot: `results/workshop-stable-controller-20261103/status-a1/status.json`.
It includes the completed comparison, startup analysis, outcome classification
and independent cleanup proof. The executed model/serving controls are
unchanged; the controller observer runs on the stable bastion.

Verified local raw run:
`results/workshop-mx-pullback-20261103-breakdown/verified/results/workshop-mx-startup-20261103-artifact04/`.
The parent pullback `verification.json` records all 560 selected files with
zero hash mismatches. The independent breakdown's JSON records hashes of its
eight raw inputs. Preserve this tree, original local preflight evidence and
the remote batch inventory when later sealing the combined campaign archive.
The batch's existing `evidence-sha256.json` predates later analysis/CPU cleanup
and is not a final combined inventory.

## Earlier measurements

The initial 8k-context pair remains a separately validated result: 524.67 s
native EFS versus 315.51 s peer weights (1.66x, one paired trial). Artifact02
failed its coordinator prerequisite; artifact03 was interrupted by connectivity
and subsequently fully recovered/cleaned. Their preserved conditions and raw
references are in [INVESTIGATION_HISTORY.md](INVESTIGATION_HISTORY.md).
