# Independent MX CPU capability and RAM seed review

Reviewed locally on 2026-11-06 UTC. No RPC, network, cluster, GPU or model-byte
population was performed by this reviewer. Held v6 and capture sources were
unchanged.

## Preserved a2 capability attempt

The actual native probe's CPU capability checks are accepted in the fresh
supplemental disposition:
`results/mx-dev-cache-capability-a2-independent-audit-20261105-a1/supplemental-disposition.json`.
The original attempt's `result.json` and `terminal.json` remain **failed** and
byte-identical. This does not relabel that attempt as an overall pass.

The audit binds the planned probe YAML to the actual ConfigMap data, exact
historical embedded probe, canonical Job/Pod identity, exact requested/resolved
images and retained stdout. The probe Pod succeeded with exit code zero,
`backoffLimit=0`, no GPU resources or claims, and
`NVIDIA_VISIBLE_DEVICES=void`. It established:

- The exact 40-character pinned revision.
- Full manifest selection of 88 weights totaling 75,010,188,240 bytes, with
  filenames/sizes checked against the pinned source cache/index.
- Metadata-only selection of 26 files and all four locked metadata hashes.
- A 35,661,352-byte shard stream matching the pinned cached source hash
  `5ae1f86003d237659f6fb990ce55e2f4adeb9c0e81ac484b63de066b60746418`.

The original root wrapper additionally asserted `torch_imported is False`.
Actual SDK imports made that field `True`; the other conjuncts passed. Its
failed result is therefore preserved while this supplemental receipt accepts
the narrower native RPC/byte capability. Torch import does not establish CUDA
initialization, and CUDA initialization was not measured by that probe.

The sample was compared with pinned source-cache bytes. There is no separate
retained resolved HF-LFS blob-identity receipt for that sample, so this audit
does not assert its LFSoid. Root confirmed that narrower interpretation. All
six owned resource deletions have successful scoped command receipts. This
audit did not replay RPC, prove streamed hashes for all weights, qualify a RAM
accelerator or measure GPU startup/performance.

The current probe source has since replaced numeric protocol enum `0` with
the named `model_pb2.HUGGING_FACE` constant. Historical attribution uses the
actual embedded ConfigMap bytes, copied into the audit directory as
`actual-embedded-probe.py`, rather than the later working source.

## Fresh persistent RAM server a2

**No source-review blocker found** for root's bounded CPU/RAM population after
its live ownership/headroom/admission gates. The reviewed fresh render is
`results/mx-dev-persistent-server-20261105-a2`; it was not populated by this
review.

Two guard gaps were fixed before that fresh render: seed IDs now use the same
strict short-ID syntax as the renderer, preventing staging path traversal, and
the cgroup gate uses `memory.max - memory.current`, preserving its 4 GiB reserve.
The existing host gate requires cache capacity plus 32 GiB available; cache and
filesystem checks retain a 1 GiB reserve. The init CLI has a finite SIGALRM
deadline, explicitly 2,400 seconds in the render.

The seed accepts the pinned model/revision, four metadata hashes and qualified
weight count/bytes. It confines source symlinks to the repository, verifies
every weight's authoritative SHA-256 blob name while copying and checks Git
blob hashes for 40-character metadata blob names. Every copied file receives
an inventory hash and an internal destination link. Promotion occurs only
after the complete verified snapshot is staged. Failures preserve partial
staging without a published snapshot or successful receipt; sources are opened
read-only, and existing caches are never silently overwritten.

The rendered server is a single owned `Recreate` Deployment with a 96 GiB RAM
emptyDir and 96/112 GiB requested/limited memory. Only the init container mounts
the source PVC, read-only. The server mounts only its private RAM cache. Init
and server use void GPUs and CPU/memory resources, with no GPU claims. Service
selectors match the owned Deployment labels. The persistent Pod has no
activeDeadline; root controls its later explicit cleanup. RAM contents survive
container/candidate activity only while that server Pod exists and are lost
when it is replaced.

## Tests and remaining gates

**10 focused tests passed**, comprising four author tests and six independent
tests. Independent tests cover invalid IDs before filesystem use, actual
cgroup usage/reserves, valid and corrupted Git blobs, late copy failure with
unchanged source/no publication, finite CLI deadline setup and the actual
fresh render's hashes, seed source, CPU/RAM/source mounts and service ownership.

```text
PYTHONDONTWRITEBYTECODE=1 .local/venv/bin/python -m unittest discover -s tests -p 'test_mx_dev_cache_seed*.py' -v
Ran 10 tests in 0.209s
OK
```

Root must still collect the actual complete seed inventory/hash receipt and
bind it to the same server Pod UID, then validate native CPU file streaming
into the proposed local client cache. Every future GPU candidate needs its own
RAM budget and full-file hash validation. None of those outcomes, nor a startup
speedup, is established by these small-data tests or the older capability probe.

| Reviewed artifact | SHA-256 |
| --- | --- |
| Seed | `9861d7d11c91298395a3b4a82615ad95d044322b4b0ac108acc0e90fb1fcbca4` |
| Server renderer | `7ba43abbd10a954dd339ea317c43efb7ae2c6bc51630a75a932afc689c6cca2a` |
| Independent tests | `0d6bc3e3c1f872b612b0f3a93c71350c4199b307ddba945b0c84a6274cea2616` |
| Fresh a2 plan | `e2651dc210a7d034817f4a52b1b3b01210ce8a2d70dd96c1c10a609265e034d9` |
| Fresh a2 server YAML | `029e47aec7ea9083a19184a02039f01f12c957919c85227118a892d2da181818` |

## Follow-on source reviews: shared CAS and final v3/a4

The original a2 seed/render remains preserved. Actual source layout required a
separate v2 seed supporting only the exact owned centralized shared CAS path
`<HF_HOME>/hub/blobs/<first-two-hex>/<64-hex>`. Five independent v2 tests and
five prior safety cases rerun against v2 passed: correct shared layout worked,
while wrong roots/prefixes/depth/hex keys, external shared-root symlinks and
corrupted bytes failed without publication. That was a source-only acceptance;
it did not establish successful live population.

Root's later exact-revision HF tree evidence established that some declared
Xet storage keys differ from complete-file SHA-256 content digests. The final
v3 design therefore separates storage identity from data identity. It accepts
only the exact 114-file pinned HF tree, names/sizes and declared Git/LFS/Xet
storage keys. Every copied file is checked against its authoritative LFS data
SHA-256, or Git-blob SHA-1 for native Git metadata. Four independently locked
metadata SHA-256 values remain additional checks. Xet keys are never treated
as complete-file digests.

The final render is **only**
`results/mx-dev-persistent-server-20261105-a4-reviewed`; the provisional a4 and
earlier renders are historical evidence. Its immutable ConfigMap embeds the
exact HF tree bytes/hash/URL/count and v3 seed. Nine focused tests passed (five
author, four independent), including actual final-render/tree binding, separate
Xet/LFS identities, corrupt data/storage/tree/size/fileset rejection and a
durable first-timeout receipt that retains its original spec hash and cannot
be overwritten or replayed by init retries. Root received source-only approval
for one fresh bounded CPU/RAM population after its new admission and cleanup
of prior failed resources.

Final reviewed bindings:

| Artifact | SHA-256 |
| --- | --- |
| V3 seed | `64cafd37e41e4c33a1d35fe4e312ad4c2971c0bc89ed5218ead2ac7b6e454fcd` |
| V3 renderer | `8b85aa6fac741ebe816c932f3aac9bb4cb55379da3df22fb1bf1e825367dfa70` |
| Final a4-reviewed plan | `e119503f38e41dfce1c189b2499785089961211d298a4286a21a0115f26032ab` |
| Exact 114-file HF tree | `6cb5321d7af8d746fa831781f4fa036e19db091029080365ce31ddc146a6b35a` |
| Independent v3 tests | `a4ba3351c70618a78e3446a11a85f6bd8ffca6397e26a588a3ded6b5ac23012c` |

Actual v3 population and the native full-file client qualification remain
separate unaccepted gates in this source review. The default no-cache full-v6
GPU path does not depend on them.

## Actual final v3/a4 seed accepted

The actual final v3/a4-reviewed population and retained Ready producer evidence
are now independently accepted in
`results/mx-dev-persistent-a4-independent-audit-20261105-a1/verification.json`.
The read-only audit binds the reviewed plan/apply manifest, exact tree and seed
source, actual immutable producer seed ConfigMap UID
`64db104b-9c90-4f8c-bebd-0f30cfbfdddf`, actual seed stdout and complete receipt,
all observed producer Pod UIDs, exact image/container identities, zero restarts,
seed exit zero and CPU/RAM/read-only-source isolation.

All 114 files match the exact pinned tree and complete inventory: 92 use LFS
data SHA-256 identities and 22 use Git-blob SHA-1 identities. The 92 Xet keys
are declared storage identifiers. All 88 weights match their authoritative LFS
digests and total 75,010,188,240 bytes; all files total 75,063,320,262 bytes.
All four locked metadata hashes match. Actual population took 316.353 seconds.
The saved full seed receipt hash is
`6df28e51bf4beeeeca538a872ba5d77332e8230f7c329f305671ac74372c39b7`.

The Ready producer Pod retains UID
`e32f8b4f-83f1-4291-879f-404d5e811514`. This accepts the retained population
and Ready observations only. A fresh native full-file CPU client stage is
running separately and is not yet accepted. Current live producer health,
future GPU admission/staging, startup speedup and GMS recovery remain separate
gates. No network, RPC or cluster action was performed by this reviewer.

## Actual full native CPU client accepted

The fresh native full-file client and root's self-contained qualification are
now independently accepted in
`results/mx-dev-stage-a1-independent-audit-20261105-a1/verification.json`.
The actual CPU Pod UID `0a62bb6d-177b-46aa-abd1-617ca4341d3a` completed with
exit zero and no restarts on `kubecon-nke-site-cp-0124`. Its sole stage container
uses private RAM with no GPU claims/resources, init containers, source PVC or
hostPath. Actual immutable stage ConfigMap UID
`5d5db38a-fddf-4c17-affa-5b1abd3bc5bf` contains exactly the reviewed source and
spec. Actual JSON/stdout artifacts match their retained command receipts.

All 114 files match the accepted seed's sizes and SHA-256 values; the 88 weights
total 75,010,188,240 bytes, and all files total 75,063,320,262 bytes. The bound
executed source also enforces exact native manifest, returned pinned commit
and complete streamed index coverage. It published the private cache in
117.852848 seconds. Torch was imported, while CUDA initialization was explicitly
measured false. The producer before/after Ready observations retain the same
qualified Pod, server/seed container identities and direct `192.168.100.50:8001`
endpoint.

The qualification regenerated from exact actual evidence matches root's file
canonically. Qualification SHA-256:
`f543e915ecd64759fed478fa0456915f55d804bd67047788ac4f547ec4102667`.
Stage receipt SHA-256:
`6711eb2a2d118000284a9def493e14db107965d85ff27132e24d8b102f31dca6`.

This timing is CPU file streaming, hashing and publication, not GPU weight
loading or inference startup. Scoped completed-stage cleanup is appropriate;
the seeded producer server/Redis/PVC remain separate. Future candidates still
need current producer validation, their own RAM budget/full-file receipt and
engine/GMS readiness gates. No native RPC was replayed by this reviewer, and
no GMS-MX/P2P integration, startup speedup, parked reader, recovery or SLO
claim follows from these accepted CPU results.
