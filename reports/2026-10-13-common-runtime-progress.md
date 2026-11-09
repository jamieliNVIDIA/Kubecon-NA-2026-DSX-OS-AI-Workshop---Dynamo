# Common workload runtime — qualified October 13, 2026

**One immutable image passed the bounded vLLM/Nemotron feature matrix:** serving,
KV-aware routing, disaggregation, ModelExpress P2P, native engine sidecar,
KVCR peer reuse, Grove/KAI scaling and fresh native TP1 Snapshot restore.
Shadow/GMS entrypoints are present; live failover remains blocked by GPU DRA
infrastructure. No shared platform, driver or allocator upgrade was needed.

Use `configs/common-runtime-qualified.json` and the manifests under
`configs/dgd/common-runtime/`. The previous public 1.5.1 and separate-image
locks remain available as baselines. This is a custom development runtime,
not a released or production-qualified bundle.

## Image and version set

```text
nvcr.io/nvidian/dynamo-dev/nealv@sha256:e98d074e84e584a93967aa2f53e2c1092cea631034b1b9277c8753f8c3ba307d
```

| Component | Actual installed version / immutable source |
| --- | --- |
| Dynamo Python/Rust and native sidecar | 1.6.0; `ea23e5130c1bfbadec477b99449d0cee5598caa0` |
| vLLM | `0.31.1rc1.dev23+g43b4aaea3`; pinned nightly base digest `f8696a51…` |
| vLLM KVCR adapter | Six files at `08567505b09324f891797f4a13c1bd73fc75a827` |
| KVCR | 0.1.1; `f6b9387b9e838ee9196a5d22b107e4c95f6f1dfb` |
| NIXL / NCCL | 1.5.0 / 2.30.7 |
| PyTorch | `2.13.0+cu130` |
| ModelExpress | 0.6.0; checksum-pinned CPython 3.12 wheel |
| GPU Memory Service | 0.9.0; same Dynamo source revision |
| AWS EFA userspace | 1.49.0; checksum pinned |

Frontend, integrated worker, native engine and external CPU sidecar all use the
same image. The sidecar pattern still uses separate containers and commands:
native `vllm-rs` for the engine, `dynamo-vllm-sidecar` for the sidecar. CPU roles
receive `NVIDIA_VISIBLE_DEVICES=void`. The engine contains the Dynamo package
but runs through the native engine entrypoint. No in-process Dynamo worker is
launched in that container.

KVCR, its adapter, ModelExpress and EFA userspace are baked into the image;
feature Pods perform no startup package installation. The image is private:
create an NGC pull secret in the workload namespace. The harness creates an
owned `common-runtime-pull` secret from the workstation's existing NGC
credential without saving the secret body in execution receipts.

Platform/controller images remain separate: Dynamo operator 1.5.1, Snapshot
0.1.0, Grove and KAI were unchanged. Candidate DGDs use
`runtimeVersionOverride: 1.6.0`.

## Qualified functionality

All tests used `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`, revision
`bee7596271d1495f6992ae224aefde4410e816b8`. No alternate model was needed.
TP1, context 4096, maximum eight sequences, GPU utilization 0.65, no draft.
The load log reports 19.11 GiB of weight memory; it fits one H100.

| Feature | Verified evidence |
| --- | --- |
| Packaging / GPU / EFA | Exact versions, imports and entrypoint hashes; H100 arithmetic and positive EFA provider; observed image ID equals the published digest |
| Serving and KV routing | `READY`; two cross-node workers, two independent prefixes, six unforced repeats, 2176 cached tokens each, two applied frontend KV events |
| Native engine sidecar | cp-0942; native `vllm-rs` PID 1, external CPU sidecar, identical image digests and `READY` |
| KVCR | cp-0198 → cp-0124; five matched blocks / 33,423,360 bytes, 2176 cached tokens, expected output, LIBFABRIC/EFA, zero failed/partial deliveries |
| KVCR idle health | 180-second canary timeout; three samples per worker, both Ready and zero restarts |
| Disaggregation | cp-0124 prefill → cp-0198 decode; two completed transfers / 72,155,136 bytes, 2639 imported prompt tokens, correct output and zero transfer/notification failures |
| ModelExpress P2P | cp-0124 → cp-0198; all 761 tensors / 20.43 GB over LIBFABRIC/EFA, no receiver disk fallback and `READY`; one transfer log reported 1.68s, not a benchmark |
| Grove/KAI | Gang admission, GPU arithmetic completion markers and reversible group scaling 1→2→1; two→four→two GPU Pods |
| Snapshot | Native preparation/resume, fresh CRIU artifact, distinct restored Pod UID, `nvidia.com/Restored=True`, matching restore annotation and correct inference |
| Shadow/GMS | Expected files/entrypoints and same image digest verified; live recovery blocked, no fault injected |

## Fresh Snapshot and resource observations

Artifact `checkpoint-9d99f93beadbd362ed4b3cce212b7aef`, content UID
`dd493b26-b781-4415-b1f2-090551ae983a`; same-node restore on cp-0124.
Source Pod UID `63c7ae1c-ea52-4985-bb91-3fccf2dc358d`; restored Pod UID
`8c60e774-4fb0-48ef-8a21-0e6da5612782`. Restore inference passed at
19:29:02 UTC. The old 1.5.1 artifact was not reused.

| Observation | Value |
| --- | --- |
| Final artifact | 35,871,594,315 logical bytes, 33.41 GiB, 1,140 files |
| Agent capture | 989.461s (16m29s); CRIU 983.819s, CUDA checkpoint 1.926s |
| Agent restore | 124.600s (2m05s); CRIU 115.438s, CUDA restore 8.553s |
| Capture resource creation → artifact Ready | 1254s, including model initialization |
| Restored Pod creation → Restored / Ready | 126s / 140s |
| Capture / restored worker host RAM peak | 53.76 GiB / 33.26 GiB |
| Snapshot agent cgroup peak | 1.20 GiB; observed high-water mark, not a universal minimum |
| OOM / OOM kills | Zero for capture worker, restored worker and agent |

Worker requests remain 4 CPU / 64 GiB RAM, memory limit 128 GiB and 16 GiB
shared memory. The agent retains its tested 1 GiB request / 16 GiB limit;
allow at least the measured peak when planning reservations, for example a
2 GiB request. No shared agent resources were changed during qualification.
EFS is functional but this full restore is not seconds-scale startup. The
CUDA-only phase excludes CRIU and other overhead.

The later [same-artifact storage control](2026-10-13-snapshot-storage-comparison.md)
passed fresh inference for two EFS restores (**124.42s / 123.97s**) and one
pre-staged RAM restore (**14.20s**, CRIU **5.38s**, CUDA **8.28s**). Pod creation
to Ready was **139s on EFS / 30s on RAM**. This isolates the EFS read path as the
dominant delay for this artifact. RAM pre-staging took **127s** and is excluded
from restore timing; acceleration needs a reusable cache. No NVMe disk was
formatted or measured, and the temporary RAM helper/mount were cleaned up.

Snapshot TP2, cross-node restore and composition with disaggregation remain
unqualified. Sidecar SGLang and routing/disaggregation parity remain
unqualified. Grove quota reclaim/topology policy, KVCR local persistence/Guard
recovery and attendee concurrency were not tested.

Live Shadow Engine recovery still needs an isolated GPU DRA node: GPU allocation
is disabled, the GPU DeviceClass/ResourceSlices are absent and all current
nodes use the competing GPU device plugin. EFA device-plugin allocation was
sufficient for all qualified transfers; EFA DRA is not required by these paths.

## Reusable execution and evidence

```bash
python3 scripts/common_runtime_build.py prepare --run results/NEW-BUILD
python3 scripts/common_runtime_build.py registry-check --run results/NEW-BUILD
python3 scripts/common_runtime_build.py isolated-build --run results/NEW-BUILD
bash scripts/qualify_common_runtime.sh results/NEW-BUILD results/NEW-TEST
# Resume an existing matching run after a test-harness fix:
bash scripts/qualify_common_runtime.sh results/NEW-BUILD results/NEW-TEST kvcr
```

The test sequence releases each successful feature's GPU workloads and records
a qualified lock only after the required receipts and cleanup pass. A failure
preserves owned resources for diagnosis; `common_runtime_tests.py cleanup`
removes only that run's known graphs and waits for their Pods to disappear.
`shadow-runtime` is read-only infrastructure/runtime inspection.

Build `results/20261013-common-runtime-c/`; tests
`results/20261013-common-runtime-features/`. The 67-file frozen build context,
base/source/wheel hashes, registry manifest digest, actual image IDs, requests,
metrics, logs and cgroup observations are retained locally. Failed attempts
are preserved: the ordinary builder's Docker filesystem was full, then the EFA
installer needed refreshed apt indexes. A duplicate KVCR canary environment
entry was rejected in dry-run and corrected before deployment.

Frozen test evidence: `evidence-1791920849018506000/` (1,465 files with SHA-256
manifest). Frozen build/publication evidence: `evidence-1791920856504215000/`
(25 files). All seven saved DGDs passed image/version/env consistency and final
client/server dry-run checks. The qualified lock was recorded only after those
checks and workload cleanup passed.

The image built with checksum-pinned BuildKit 0.26.0 on the builder's larger
`/tmp` filesystem, reusing only the stopped task-owned compilation cache.
Temporary builder containers and credential copies were removed; unrelated
images and daemon settings were untouched.

Final cleanup completed 19:31:01 UTC. The read-only inventory completed
19:34:27 UTC: three Ready H100 nodes, eight GPUs and 32 EFA devices each,
zero active test GPU Pods and unchanged shared software versions. Owned DGDs
and workload Pods are gone. Model cache, namespace, pull secret, static Retain
volumes and checkpoint artifacts remain for reuse.
