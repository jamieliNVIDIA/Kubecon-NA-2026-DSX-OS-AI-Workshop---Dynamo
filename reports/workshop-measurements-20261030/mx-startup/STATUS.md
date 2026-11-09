# MX startup measurement status

Updated after the completed MX raw pullback and local timestamp analysis
(November 3 Pacific; run timestamps November 4 UTC).

State: **artifact04 completed; 560 selected raw/proof files locally hash-verified,
zero mismatches; final combined campaign seal remains separate**.
The stable controller passed the matched native-context startup comparison,
including actual compiler-cache hit gates on both TP ranks. It independently
verified zero MX GPU Pods, ResourceClaims, DGDs and coordinator/Redis Pods and
released the lease before starting routing C1. The container remains running
that separate stage; local GPU execution stays fenced.

| Target | Deployment → observed Ready | Engine initialization | torch.compile |
| --- | ---: | ---: | ---: |
| Native EFS | 553.59 s | 176.04 s | 26.57 s |
| MX peer weights | 340.86 s | 179.07 s | 28.34 s |
| MX weights + compiler artifacts | 249.70 s | 74.44 s | 0.15 s |

One matched trial per arm, Super VL TP2 H100/native 1M context, idle source,
existing EFS checkpoint and no benchmark load. Readiness ratios: weights 1.62x
versus storage; artifacts another 1.37x versus weights; combined 2.22x versus
storage. Local raw logs independently confirm both TP-rank AOT cache loads.
STARTUP_BREAKDOWN.md accounts for the 249.70 s with exclusive boundaries;
~41 s hidden-tensor adoption is inside model loading, with 5–7 s actual copies.

Run: `results/workshop-mx-startup-20261103-artifact04`.
Frozen spec SHA256: `27fbc8cba69003faa1ca9e5c5244994fd0179e07a4d0f94806331a82c513a25c`.
Snapshot: `results/workshop-stable-controller-20261103/status-a1/status.json`.
Controller: `kubecon-workshop-controller-20261103` on `ip-172-31-10-102`.
GPU cleanup proof timestamp: 2026-11-04T00:36:54.884366Z.

## Evidence and remaining archival work

Verified raw tree:
`results/workshop-mx-pullback-20261103-breakdown/verified/results/workshop-mx-startup-20261103-artifact04/`.
Parent verification: `results/workshop-mx-pullback-20261103-breakdown/verification.json`.
Derived timeline, raw-input hashes, CSV and excerpts:
`results/workshop-mx-breakdown-20261103-analysis/`.

No MX rerun is needed. Preserve the verified staging tree, prior origin
preflight inventory/state and remote batch inventory for the full campaign's
final archive. Retain original local preflight files omitted from the narrow
transfer bundle; the earlier batch inventory is not a final post-cleanup seal.

Routing remains active remotely; do not start a duplicate local controller or
remove the local execution fence. Root handles read-only polling/pullback and
final whole-campaign cleanup verification.

## Earlier evidence

- Completed 8k pair04: 524.67 s EFS versus 315.51 s peer weights (1.66x), N=1.
  Separate context/observer group; unchanged.
- Artifact02 failed its coordinator prerequisite; no valid artifact speedup.
- Artifact03 source passed but connectivity interrupted the native target; old
  resources were fully collected/cleaned. Its recovery seal has 372 verified files.
- Artifact04 CPU preflight originally sealed 82 local files. Those original
  receipts must be retained alongside the new remote outputs in the final archive.

See REPORT.md for conditions, nested phase boundaries and the observed results.

## DGD task list

1. Gather requirements (model, GPU, framework, runtime — Docker/Pyxis/K8s)
2. Pick a template from `configs/templates/` or `configs/examples/` (never start from scratch)
3. Write the DGD YAML (save to `configs/dgd/<name>.yaml`)
4. Validate with `kubectl --dry-run=client apply` (or for SLURM: confirm mount paths and env vars)
5. Hand off to `deploy_dynamo` or `kubectl apply`

Use the qualified October 22 generated source/target DGDs as the available
templates. Save fresh copies beneath the immutable run instead of overwriting
the historical `configs/dgd/` manifests.

Requirements/template selection and client/server dry-runs passed. Authoritative
manifests are JSON, preserving literal environment strings such as `y` that the
Kubernetes YAML decoder otherwise interprets as boolean. CPU-preparation failures
are preserved in pair01–pair03; no GPU workload ran in those attempts. The missing
optional model README is not required for the staged serving-metadata check.
