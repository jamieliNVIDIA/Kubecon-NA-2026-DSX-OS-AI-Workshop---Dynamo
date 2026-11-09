# Shadow Engine failover — October 12, 2026

**October 14 result:** GPU DRA/shared CUDA works on all three nodes. A live Qwen
control with the common image and a source-hashed GMS compatibility overlay
passed process recovery and standby replenishment in the same Pod. Nemotron
NVFP4 remains blocked by packed-weight import and CUDA warm-up errors. See the
[current retest report](2026-10-14-shadow-engine-retest.md). The remainder of this
page preserves the original October 12 baseline and contract.

Added the Nemotron/vLLM TP1 test. **Live failover is blocked by GPU DRA
configuration; no engine was killed.** Client and server admission dry-runs
passed. A disposable CPU-only Pod confirmed GMS/Shadow entrypoints in the pinned
public Dynamo 1.5.1 image and was removed. Eight offline safety checks passed.
The recovery verifier has not yet run against a live Shadow Engine.

October 13 planning update: the cluster is dedicated to this demo. The
[revised cluster proposal](2026-10-13-cluster-setup-next-steps.md) targets GPU DRA
on all three nodes, migration of demo manifests/harnesses, and the qualified
common runtime as the next Shadow test candidate. The results and 1.5.1 test
instructions below describe the earlier baseline; they are not evidence for
the proposed configuration. Opportunistic workload compatibility is not required.

Evidence: `results/20261013-shadow-preflight/` (UTC October 13 receipts).
Immutable copy: `evidence-1791871817343947000/`, 69 files with SHA-256 manifest.
Final status: no Pods or DGDs in the owned namespace.

## Requirements and provisioning gap

| Requirement | Current result / DSX action |
| --- | --- |
| Dynamo GMS/failover | Operator 1.5.1 admits both experimental fields; runtime 1.5.1 contains GMS and failover metrics. No newer Dynamo version needed to attempt this test. |
| Kubernetes DRA v1 | API 1.34.2 and resource APIs present. [Release example](https://github.com/ai-dynamo/dynamo/blob/v1.5.1/examples/backends/vllm/deploy/agg_failover.yaml) requires 1.34+. |
| NVIDIA GPU DRA | Installed driver 0.5.0 has `resources.gpus.enabled=false` and `gpuResourcesEnabledOverride=false`. Only ComputeDomain classes, no `gpu.nvidia.com` class or GPU ResourceSlices. Enable GPU allocation and verify a Ready plugin advertising H100 devices. |
| Allocator ownership | Baseline: all three nodes run the NVIDIA device plugin. Revised target: disable it cluster-wide and enable GPU DRA on all three nodes. The harness refuses overlapping allocators. |
| Driver/toolkit/CDI | Driver 580.173.02 and containerd 2.3.5 meet the published floor. Toolkit/CDI injection and actual claim allocation still need a live Pod qualification. |
| GPU/HBM | One H100 shared by two engines and GMS via one claim. Budget one shared weight allocation, active KV/state, and both engines' contexts, graphs and private buffers. Parked standby releases materializable KV backing; actual Nemotron/H100 GMS headroom is unmeasured. |
| CPU/RAM/storage | Proposed template: 4 CPU / 64 GiB RAM request per cloned engine, 128 GiB limit, shared 16 GiB `/dev/shm`; frontend 1 CPU / 4 GiB request, 8 GiB limit. Reuse EFS model cache read-only; JIT caches use private `/tmp`. These are not measured minimums. |
| Networking | Frontend connectivity and Kubernetes container discovery. EFA, EFA DRA and multinode NVLink are not prerequisites for this intra-Pod test. |
| Snapshot | Optional composition; no Snapshot operator/agent needed. |

Keep Nemotron revision `bee7596271d1495f6992ae224aefde4410e816b8`, runtime index
digest `sha256:2b224a823d52a198ec0eeb0e3e4f5cf26cd8a7fc2e9812ee16204b6b1e974870`,
Dynamo 1.5.1 / vLLM 0.28.0. Ordinary serving passed earlier; NVFP4/Mamba/MoE
GMS sharing and parking remain unqualified. No alternate model substituted.

The [standalone DRA 0.5.0 installation contract](https://github.com/NVIDIA/k8s-dra-driver-gpu/blob/v0.5.0/site/content/docs/install.md)
requires both flags, recorded in `configs/shadow-dra-required-values.yaml`.
This is a proposal fragment, not a complete upgrade plan. The revised target
disables the competing GPU device plugin everywhere and moves required demos
to GPU claims. The [prerequisites](https://github.com/NVIDIA/k8s-dra-driver-gpu/blob/v0.5.0/site/content/docs/prerequisites.md)
also require CDI and a compatible container toolkit.

Do not automatically migrate using the latest GPU Operator `GPUCluster`
instructions. The [current managed workflow](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/dra-intro-install.html)
targets new installs, prohibits simultaneous `GPUCluster`/`ClusterPolicy`, and
does not support migration from this standalone Helm layout. Shared allocator
changes need separate review under the user's no-major-changes constraint.
These scripts do not mutate shared drivers, operators, nodes or schedulers.

## Test contract

The [NVIDIA article](https://developer.nvidia.com/blog/restore-llm-inference-capacity-in-seconds-with-shadow-engine-recovery-in-nvidia-dynamo)
describes process recovery using parked engines and shared weights. It does
not promise recovery from failed GPUs/nodes or KV-cache continuity. Snapshot
is optional. Its published timing uses different hardware/model/settings.

`shadow_failover_tests.py` and `shadow_probe.py` implement:

1. Preflight, image inspection and DGD derived from the pinned 1.5.1 example.
   One worker Pod contains `engine-0`, `engine-1`, `gms-server`, container
   discovery and `--load-format gms`. Require the same allocated GPU claim and
   the same physical GPU UUID in both engines.
2. Require one active and one warmed/parked standby in failover metrics, a held
   flock matching the active engine, model registration and `READY` with worker ID.
3. Recheck ownership, Pod UID, container identity and allocator isolation.
   SIGKILL exactly one `VLLM::EngineCore*` PID inside the active container.
   Reject PID 1, ambiguous targets and shared process namespaces. No Pod
   deletion, GMS termination, node fault or blind `pkill`.
4. Require `READY` from a different worker, exactly one successful standby
   switch, swapped roles, unchanged Pod UID and standby/GMS container IDs and
   restart counts, unchanged committed weight layout/publication history, and
   reclaimed failed-engine KV backing. Former active must restart and park.
5. Save responses, failures, metrics, GPU claims, GMS state/history, worker
   metadata and Pod identities. Measure fault-command-to-first-verified-response
   including `kubectl exec` overhead; no throughput/service-level claim.
   Cleanup deletes only the owned `ft-shadow` DGD and retains model cache/PVC.

Worker-only 180-second canary timeout accommodates the prior cold-JIT finding;
shared defaults are unchanged. TP2, repeated swaps, throughput recovery,
hardware failure, Snapshot composition and disaggregated failover are outside
the initial test.

## Run after infrastructure enablement

Use a fresh run. Existing cache preparation rechecks the exact model revision
and baseline KVCR wheel hashes without redownloading weights.

```bash
set -e
source scripts/kubecon-env.sh
RUN=results/<fresh-shadow-run>
.local/venv/bin/python scripts/shadow_failover_tests.py preflight --run "$RUN"
# Inspect receipt: blockers empty, eligible_nodes nonempty.
.local/venv/bin/python scripts/upgrade_retests.py prepare --runtime 1.5.1 --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py runtime --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py dry-run --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py deploy --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py status --run "$RUN"
# Wait for active+parked standby; verify refuses injection until both exist.
.local/venv/bin/python scripts/shadow_failover_tests.py verify --run "$RUN"
.local/venv/bin/python scripts/shadow_failover_tests.py cleanup --run "$RUN"
```

`preflight` is read-only. `dry-run` may create the owned namespace but no DGD.
`deploy` is gated on infrastructure/cache/runtime evidence. `verify` injects
the fault and leaves the DGD running for diagnosis on failure: use scoped
cleanup afterward. The controller can recreate deadline-expired Pods, so
always clean up the DGD. Full recovery has not yet been qualified.

```bash
.local/venv/bin/python -m unittest discover -s tests -p 'test_shadow*.py' -v
```
