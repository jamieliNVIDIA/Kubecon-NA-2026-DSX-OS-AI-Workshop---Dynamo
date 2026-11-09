# Persistent ModelExpress development cache

**Status: actual RAM seed and native cross-node full-file CPU staging passed;
both independently accepted. The producer remains running.** The completed
client Job/bootstrap were cleaned up. A cache-enabled full-a4 is now frozen
offline; its GPU execution, startup and recovery remain separate gates.

This is development infrastructure for shorter repeated Shadow startup
iterations. It is separate from the presenter’s GPU peer-weight-transfer demo.
The root coordinator owns all live cluster actions; the cache workstream only
authors and reviews local artifacts.

## Decisions

- Keep the accepted GMS loader and `--load-format gms` unchanged. Its installed
  source already has optional `MX_ENABLED=1` strategy integration, but that
  GMS/SuperVL/Humming composition is not qualified by the existing demo.
- Start with a persistent **CPU file cache**, populated once from the existing
  pinned source, and stage the complete snapshot into candidate-local RAM
  before inference starts. Keep `MX_ENABLED` unset/zero.
- The engine’s existing local HF snapshot path stays identical. A nested
  `emptyDir` mount at its existing `HF_HOME` replaces the source of those bytes,
  while the GMS flags, model identity and runtime overlay stay unchanged.
- Use direct qualified producer Pod IP port 8001 for staging. Bind the server's
  Pod UID, container ID, image and IP before GPU intent and after staging. This
  avoids assuming that a DNS Service targets the producer whose seed was
  inspected.
- Each server/target cache is bounded to 96 GiB. Persistent server request
  96 GiB, limit 112 GiB, no GPUs. The target graph raises main request
  128→224 GiB and limit 256→352 GiB. The operator clones main into two engines:
  their summed requests/limits are 448/704 GiB, excluding unchanged GMS sidecar
  resources. These conservatively reserve the one shared cache without operator
  overrides. These budgets are development choices, not workshop requirements.
- “Persistent” means that candidates reuse one server Pod. Its RAM disappears
  when that Pod is replaced; a replacement generation needs requalification.

## Accepted live results

| Operation | Actual payload and validation | Elapsed | Outcome |
| --- | --- | --- | --- |
| One-time source → persistent RAM seed on cp-0198 | All 114 files, 75,063,320,262 bytes; 88 weights, 75,010,188,240 bytes; HF LFS/Git content hashes and four locked metadata SHA256 hashes | 316.353155 s | Seed exit 0; producer Ready |
| Persistent RAM on cp-0198 → private RAM on cp-0124 | Native ModelService pinned commit/full manifest, all 114 streamed files and hashes, complete weight index | 117.852848 s | Client exit 0; CUDA uninitialized; no GPU request or EFS/PVC mount |

The **117.853 seconds measures complete CPU file staging**, including RPC
validation, hashing, RAM writes and publication. It is not GPU weight loading,
inference startup, recovery latency or an SLO. This is one functional
observation, not a matched startup speedup or distribution. Torch was imported
by the SDK; `cuda_initialized` was explicitly false. No native GMS-MX/P2P
composition is qualified by these results.

The same source Pod/container/IP remained Ready through the client and after
scoped client cleanup. Independent audits reviewed retained actual logs,
Pod/image/exit provenance, immutable bootstrap, inventory and source hashes;
they did not replay the RPC or download weights again.

Evidence, relative to the repository root:

- [Actual seed receipt](../../results/mx-dev-persistent-server-20261105-a4-reviewed/seed-receipt.json),
  [raw log](../../results/mx-dev-persistent-server-20261105-a4-reviewed/seed-console.log),
  [Ready producer](../../results/mx-dev-persistent-server-20261105-a4-reviewed/server-ready.json)
  and [admission](../../results/mx-dev-persistent-server-20261105-a4-reviewed/root-admission.json).
  Seed receipt SHA256:
  `6df28e51bf4beeeeca538a872ba5d77332e8230f7c329f305671ac74372c39b7`.
- [Independent seed acceptance](../../results/mx-dev-persistent-a4-independent-audit-20261105-a1/verification.json):
  `seed_population_and_ready_producer_accepted`, reviewed
  `2026-11-06T01:04:36.577677Z`.
- [Actual client receipt](../../results/mx-dev-stage-20261105-a1/stage-receipt.json),
  [raw log](../../results/mx-dev-stage-20261105-a1/stage-console.log),
  [succeeded Pod](../../results/mx-dev-stage-20261105-a1/stage-pod.json) and
  [immutable bootstrap](../../results/mx-dev-stage-20261105-a1/stage-bootstrap.json).
  Client receipt SHA256:
  `6711eb2a2d118000284a9def493e14db107965d85ff27132e24d8b102f31dca6`.
- [Self-contained qualification](../../results/mx-dev-stage-20261105-a1/qualification.json),
  SHA256 `f543e915ecd64759fed478fa0456915f55d804bd67047788ac4f547ec4102667`.
- [Independent client acceptance](../../results/mx-dev-stage-a1-independent-audit-20261105-a1/verification.json):
  `native_full_file_cpu_stage_accepted`, reviewed
  `2026-11-06T01:07:57.459712Z`.
- [Scoped client cleanup](../../results/mx-dev-stage-20261105-a1-cleanup-a1/complete.json)
  and [unchanged producer afterward](../../results/mx-dev-stage-20261105-a1-cleanup-a1/producer-after.json).
  Client Job/Pod/bootstrap and client RAM are gone; source server, Redis,
  namespace, PVC and all evidence remain.

## Retained service and budgets

These are accepted retained identities. Require a fresh health/generation
check before another candidate uses the service.

| Field | Value |
| --- | --- |
| Namespace | `dynamo-ft-mx-dev-cache-20261105-a2` |
| Owner/run labels | `app.kubernetes.io/managed-by=kubecon-dynamo-feature-tests`; `mx-development-run=mx-dev-persistent-20261105-a4` |
| Node | `kubecon-nke-site-cp-0198` |
| Qualified RPC target | **`192.168.100.50:8001`**, direct producer Pod IP |
| Service DNS | `mx-dev-persistent-20261105-a4-server.dynamo-ft-mx-dev-cache-20261105-a2.svc.cluster.local:8001` |
| Producer Pod | `mx-dev-persistent-20261105-a4-server-954b74fd4-62hcb` |
| Pod UID | `e32f8b4f-83f1-4291-879f-404d5e811514` |
| Server container ID | `containerd://d7ca55f0bccc7b647580bab870b1cc02ff60aae9d5eb49b3a92ca72d149125ed` |
| Seed container ID | `containerd://7301b2e51ccad617525f48cb8348f057349273b3edc8b0d0199c568dea2b7329` |
| Immutable seed ConfigMap UID | `64db104b-9c90-4f8c-bebd-0f30cfbfdddf` |
| Server Deployment UID | `d3f6f7df-76fb-46a5-8b9a-034b8cb38d67` |
| Redis Deployment UID | `e476fea4-f71b-40ed-b4ce-2b90e8c4f248` |

The server image is
`nvcr.io/nvidia/ai-dynamo/modelexpress-server@sha256:0f8456cfc29c02547d6c62d1e640f98dc691e0326523c15fa05987d8bc491a77`.
The model/revision remain
`nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4` at
`8a115b9d966adce8c059a7bcf47f49a1e57957d8`.

Service DNS exists but is not substituted for the direct-IP identity contract.
Pod replacement, container-generation/IP change or lost readiness invalidates
qualification reuse. Retain old evidence; a replacement producer needs a fresh
seed/client qualification. The service has no overall lifetime deadline. Its
RAM survives candidate runs while this Pod exists and disappears with it.
Redis is the coordinator, not the model bytes. Source PVC is read-only and
mounted only by seed init; the running Rust server mounts RAM only.

| Component | CPU request / limit | Memory request / limit | Bounds |
| --- | --- | --- | --- |
| Persistent seed init and server | 2 / 4 | 96 / 112 GiB | 96 GiB RAM; zero GPUs; seed timeout 2400 s |
| Redis | 100m / 1 | 128 / 512 MiB | Separate owned Deployment |
| Standalone client, now cleaned | 2 / 4 | 96 / 112 GiB | 96 GiB private RAM; RPC 900 s, program 1200 s, Job 1500 s |
| Future candidate staging init | 2 / 4 | 96 / 112 GiB | 96 GiB private RAM at unchanged HF_HOME; zero GPU request |
| Each future cloned engine | Existing CPU settings | 224 / 352 GiB | Two-engine sum 448 / 704 GiB; unchanged GMS sidecar resources separate |

The one cache exists once per worker Pod. The extra 192 GiB requested across
two engines conservatively reserves it without operator overrides. Host probes
found about 2 TiB RAM; fresh available-memory checks remain required. Keep
native `--load-format gms`, model/revision/engine arguments, GMS overlay and
`MX_ENABLED` unset/zero unchanged. Only the nested RAM mount at existing
`/model-cache/feature-tests/20261015-super-vl-tp2/hf` changes the byte source.

## Earlier probes and failures

The actual installed ModelService capability probe completed successfully in
`results/mx-dev-cache-capability-20261105-a2`: exact revision,26 metadata files,
all four pinned metadata hashes,88 weight files totaling75,010,188,240 bytes,
and a complete35,661,352-byte shard streamed and hashed. Its native Pod exited0.
The wrapper wrongly required `torch_imported=false` and remains failed.
`reports/receipts/2026-11-05-mx-cpu-cache-capability.json` independently accepts
the native RPC capability while preserving that wrapper failure. Torch import
alone does not establish CUDA initialization; the new staging program records
both and requires CUDA uninitialized.

That first capability server mounted the existing source read-only. It proves
the API, not a RAM-cache speedup. The lock’s descriptive checkpoint size is
1728 bytes larger than the actual qualified file total; use the actual
model-staging evidence, without editing the held lock.

Persistent server a2 failed before copying any files. The source is a
ModelExpress centralized content-addressed cache:
`hf/hub/blobs/<key-first-two-characters>/<key>`. Its model snapshot links
outside the individual repository directory. The original seed’s repository
containment guard rejected the first asset (`accuracy_plot.png`). The complete
failure and actual Pod status are retained under
`results/mx-dev-persistent-server-20261105-a2-failure-inspect-a1`.

The historical a3 render uses `mx_dev_cache_seed_v2.py`. It admits only the exact
shared CAS layout in addition to the native repository layout, but incorrectly
treats a 64-hex storage key as complete-file SHA256, as diagnosed below. It does not
accept arbitrary cache-root escapes. The approved a2 program and rendered
inputs remain unchanged. Independent v2 checks cover the actual layout,
malformed/outside/symlinked CAS paths, corrupt bytes, and no publication on
failure. The seed has a2400-second internal timeout; the persistent service
has no Pod lifetime deadline.

Full RAM population and CPU full-snapshot streaming have now passed in fresh
runs, as recorded above. Actual GPU target staging and repeated startup timings
remain separate live gates. Do not claim a startup improvement from the CPU
stage or small shard probe. Cache staging does not itself validate Shadow
reader readiness or recovery.

The actual a3 seed also failed early. Automatic init retries retained only the
partial-cache freshness rejection; the original traceback was unavailable.
Root collected the partial RAM and source bytes read-only, then fetched the
complete114-file public HF tree at the exact pinned revision. This established
that `accuracy_plot.png`’s shared CAS name is its declared **Xet storage key**,
while its complete-file content SHA256 is the different LFS `oid`. The partial
copy and source both match that LFS data hash. The bytes were not corrupt.
These are supplemental forensic facts, not a reconstructed raw traceback.

The new a4/v3 seed binds the exact HF tree body SHA256
`6cb5321d7af8d746fa831781f4fa036e19db091029080365ce31ddc146a6b35a`.
It checks the complete file set and sizes, then validates LFS files against
their data SHA256 and native Git files against Git blob SHA1. A source key must
be explicitly declared as the file’s Xet key, LFS data hash or Git object ID;
the content hash is checked separately. Per-file receipts retain both. Its
bootstrap ConfigMap is immutable. Python fatal exceptions are written and
fsynced to owned RAM at `/cache/mx-dev-cache-failure.json`; subsequent init
retries reprint the original failure and refuse to overwrite it.

The source proof is in `results/mx-dev-source-hf-tree-20261105-a1` and
`results/mx-dev-persistent-server-20261105-a3-partial-inspect-a1`. The failed a3
resources were cleaned by root after this evidence was retained. The a4 seed
then passed its admission/live gates and independent audit. It verified
92 LFS data hashes and 22 native Git blob hashes while publishing all 114 files.

## Artifacts and lifecycle

- Reviewed server resources, already applied:
  `results/mx-dev-persistent-server-20261105-a4-reviewed/{redis.yaml,server.yaml,plan.json}`.
  The earlier local a4 proposal is superseded; only `a4-reviewed` is final.
  Do not reapply/replay this seeded run. A replacement needs a fresh ID and
  ownership/headroom/admission checks, with Redis before the server.
  The source PVC is read-only and mounted by seed init only; the Rust
  server mounts RAM only. Seed validates all metadata/assets and weights,
  publishes atomically, and emits a complete per-file hash inventory.
- `scripts/workshop_mx_dev_cache.py render-probe` renders a CPU-only bounded
  Job using the trusted actual seed receipt and Ready producer JSON. It streams
  every file via the native ModelService protocol into private RAM, validates
  all hashes and the complete weight index, then publishes a local HF cache.
- `qualify` requires the complete staging receipt, actual succeeded CPU Pod
  JSON, actual immutable bootstrap ConfigMap JSON, and a fresh unchanged
  producer JSON. The qualification embeds the
  inventory, original seed receipt and HF tree bytes/hashes, producer identity,
  actual CPU receipt, immutable CPU bootstrap, CPU Pod identity and plan;
  it needs no external basis file after freezing.
- The optional full-candidate artifacts are exactly
  `dev-cache-qualification.json`, `dev-cache-bootstrap.json`, and
  `dev-cache-receipt.json`. The two source additions are
  `workshop_mx_dev_cache.py` and `mx_dev_cache_stage.py`. The default Shadow
  closure/behavior remains separate.
- `apply_candidate_cache` returns a patched graph, owned bootstrap ConfigMap
  and full patch receipt. `validate_candidate_cache` rechecks the exact frozen
  transformation. `validate_producer_snapshot` fences server generation;
  `validate_stage_receipt` checks every target file hash and identity. The init
  container is `mx-dev-cache-stage`; its final log marker is
  `MX_DEV_CACHE_STAGE=`. Collect raw init logs, full JSON, Pod/container
  provenance and exit status before accepting startup.
- The full controller owns its candidate ConfigMap and cache volume. The
  persistent server’s Redis/Service/Deployment/seed ConfigMap belong to the
  separate persistent-cache ID and should survive candidate cleanup. Root may
  delete those exact owned resources when development ends. Preserve source
  storage and unrelated namespaces/resources.

## Reuse by a full development candidate

Passed gates include source namespace/PVC/pull-secret ownership and headroom;
client/server admission; pinned HF tree/four locked metadata hashes; complete
content validation and atomic RAM publication; producer Ready; actual native
cross-node CPU staging with no source PVC/GPU and CUDA uninitialized; succeeded
client image/container/exit provenance; immutable bootstrap; unchanged source;
independent acceptance and scoped client cleanup.

Root and the Shadow author have now frozen the optional full-a4 offline:
`results/overnight-shadow-super-vl-20261105-full-a4`, namespace
`dynamo-ft-r610-2f515dd0-demo`. Its full specification binds exactly 20 inputs
and 32 critical sources, including the accepted qualification and both cache
helpers below. Do not freeze it again or edit these sources through its
canonical cleanup:

- `workshop_mx_dev_cache.py` SHA256
  `af47bc71086d6d8ad3bdbbf50b229ca60535e11cfe2d203013c3d1d869ec9b53`.
- `mx_dev_cache_stage.py` SHA256
  `3df3c2e86c1c78f261e27b9b7c4ef62432051de83eda7bb300e94ef432aca95f`.

For a later fresh candidate, the exact cache-specific CLI addition is
`--dev-cache-qualification`. This example performs **offline freeze only**;
choose a fresh run name and use the currently accepted writer/reader gates if
their sources change:

```bash
cd /Users/nealv/Documents/dynamo/dynamo-kubecon-workshop
.local/venv/bin/python -B scripts/workshop_shadow_composed.py freeze \
  --run results/overnight-shadow-super-vl-20261105-full-cache-next \
  --source-writer results/shadow-writer-a6-remote-collected-a1/run \
  --source-audit results/shadow-writer-a6-root-closeout-a1/source-audit.json \
  --reader-cpu results/workshop-shadow-reader-v6-cpu-live-20261105-a1/result.json \
  --reader-packet results/workshop-shadow-reader-v6-cpu-packet-20261105-a1/fixtures.json \
  --dev-cache-qualification results/mx-dev-stage-20261105-a1/qualification.json
```

The three optional files are self-contained and source-bound; the default
17-input contract remains separate. Target bootstrap names are
`shadow-mx-<candidate-hash12>-mx-stage` in that candidate's namespace, with
matching owner/run labels. Existing qualification does not deploy, reserve
GPUs, prove current producer health, or bypass another full-run gate.

Use the normal guarded prepare/probe/health/durable transport sequence in
[SHADOW-FULL-REMOTE.md](SHADOW-FULL-REMOTE.md), including the brief all-script
hold from package build through launch. The host-readiness comparison fix has
its separate source review in
[SHADOW-STARTUP-READINESS-PROPOSAL.md](SHADOW-STARTUP-READINESS-PROPOSAL.md).
Prepare applies the owned immutable bootstrap. Deploy checks its unchanged
UID/data and a **fresh** Ready producer Pod UID/container/image/IP before GPU
intent. Target admission, assigned GPU identity/headroom and actual all-file
staging remain required.

Before accepting startup, collect raw `mx-dev-cache-stage` init logs, its full
`MX_DEV_CACHE_STAGE=` JSON, worker Pod UID, init container ID/pinned image,
exact integer exit 0 and restart count 0. Validate every file, total,
model/revision, seed/spec hash and source generation with
`validate_stage_receipt`, then recheck the producer with
`validate_producer_snapshot`. No GMS snapshot runs while stage proof is
pending. Preserve partial init logs/JSON on failure; do not overwrite or
blind-replay the run.

Native GPU loading, active/reader readiness, retained coding qualification,
any separately guarded fault/recovery, presenter capture and scoped cleanup
are still future gates for the cache-enabled candidate. Only its actual
evidence can establish those outcomes. A startup improvement additionally
needs a suitable matched comparison; the 117.853-second CPU stage is not that
comparison or a recovery/SLO result.

## Scoped cleanup instructions

The standalone client's cleanup already passed. Its Job/Pod/bootstrap and
client RAM are gone. Do not replay that immutable run. A replacement producer
needs a fresh server ID/seed, fresh CPU Job and new qualification through
`workshop_mx_dev_cache.py render-probe` and `qualify`.

For full-a4 or a later candidate, use canonical full-controller cleanup. It
waits for that candidate's Pods/claims to disappear, removes its bootstrap
ConfigMap, then releases its lease. Candidate RAM disappears with its Pod.
Keep the persistent source server, Redis, source PVC and namespace running.

When root ends cache development, first verify that no candidate uses the
producer, and recheck the exact ownership plus Deployment/Pod UIDs recorded
above. The a4-reviewed manifests identify the only resources to remove. Root
may then perform this **scoped final cleanup**, after retaining desired logs
and identity evidence:

```bash
kubectl -n dynamo-ft-mx-dev-cache-20261105-a2 delete deployment \
  mx-dev-persistent-20261105-a4-server \
  mx-dev-persistent-20261105-a4-redis --wait=true --timeout=120s
kubectl -n dynamo-ft-mx-dev-cache-20261105-a2 get pods \
  -l mx-development-run=mx-dev-persistent-20261105-a4
```

Require zero remaining Pods for that exact run before removing its two
Services and immutable seed ConfigMap:

```bash
kubectl -n dynamo-ft-mx-dev-cache-20261105-a2 delete service \
  mx-dev-persistent-20261105-a4-server mx-dev-persistent-20261105-a4-redis
kubectl -n dynamo-ft-mx-dev-cache-20261105-a2 delete configmap \
  mx-dev-persistent-20261105-a4-seed
```

Use the intended cluster context. Preserve `feature-cache`,
`common-runtime-pull`, the namespace, all failed/accepted evidence and unrelated
resources. These commands have not been executed by this documentation update.
Producer deletion discards RAM and invalidates the current qualification.

## Follow-up / upstream questions

1. Qualify native GMS+MX strategy composition separately, especially target
   identity when `model_config.model` is already an existing local path. A
   server-cache strategy can otherwise find the shared files present and leave
   the native loader reading shared storage.
2. The installed Python ModelCacheClient omits per-RPC deadlines by design.
   This development wrapper adds explicit RPC and overall bounds. An optional
   public timeout policy could be useful upstream; this is a proposal, not a
   demonstrated library defect.
3. Document the centralized CAS source layout in any generic cache-copy tool.
   The failure was in this workshop helper’s overly narrow layout assumption.
4. Seed and cross-node CPU staging are now measured. Measure actual native
   model loading and matched repeated startup before deciding whether this
   belongs in presenter/take-home materials. Keep development acceleration distinct from MX
   GPU peer-transfer claims.
