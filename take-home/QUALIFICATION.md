# Maintainer qualification of the take-home service

`qualify.py` tests the actual renderer output on the workshop cluster. Its
private placement overlay adds only a node selector and two physical GPU UUID
selectors; it retains the generated image, flags, model, resources, cache path
and request. Attendees do not need this harness or workshop access.

The candidate public image is the unmodified, digest-pinned official nightly:

```text
nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:c186817f4669d615d2b14bee5a6119d35d4d0fe186fdfab69920da8de9d09337
```

Its source tag is `20261103-e37f0b9-efa`, with Dynamo version
`1.7.0.dev20261103`. Registry metadata was previously recorded in
[the selection receipt](../reports/receipts/2026-11-04-kvcr-guard-nightly-selection.json).
That prior work tested the nightly's wheels on the private Super VL base;
**it did not qualify this unmodified image**. Neither registry metadata nor the
CPU probe establishes model kernels or serving. A nightly is not a stable
production release, and this baseline experiment does not qualify KVCR, GMS,
Snapshot, P/D, ModelExpress or their dependency combinations.

The unmodified image's CPU probe **passed on November 5 at 11:19 a.m. Pacific**.
Its actual image ID matched, it had no Pod pull secret, mounted overlay or GPU
claim, and it exposed no numbered GPU devices. Model registry, required engine
fields and Dynamo metadata imports passed; the owned probe was then deleted.
The independent [CPU receipt](../reports/receipts/2026-11-05-take-home-public-runtime-cpu.json)
records all twelve checks and immutable file hashes.

| Installed package | Observed version |
| --- | --- |
| ai-dynamo / ai-dynamo-runtime | `1.7.0.dev20261103` / `1.7.0.dev20261103` |
| vLLM | `0.32.0` |
| PyTorch | `2.13.0+cu130` |
| Transformers | `5.19.0` |
| NIXL | `1.5.0` |

The installed NIXL version supersedes the older `1.4.1` source-ref inference for
this exact image; that earlier receipt remains unchanged. Imports and package
versions still do not qualify any NIXL transport or KVCR composition.

The completed baseline attempt is
`results/take-home-live-public-20261105-a4`. A1 was frozen offline and superseded
before any cluster action to strengthen the namespace UID guard. A2 passed the
CPU probe, then stopped at admission because this CRD accepts only an `X.Y.Z`
runtime override; its package version includes a nightly suffix. A2 was scoped
cleaned before sources changed, with its evidence preserved.

A3 keeps the exact same image, model, flags and request. Its operator override
is `1.7.0`, while the separate expected installed package version remains
`1.7.0.dev20261103`. It uses the otherwise idle migration pair, cp0942 GPU6/7,
and its own local GPU lease. No runtime substitution occurred. A3 passed its
own CPU probe and all eight DRA bundle dry-runs, then the generated downloader
failed with `PermissionError` because the image's UID 1000 could not write the
existing root-owned cache. No GPU serving was attempted. Root preserved the
failed Pod/logs and completed scoped cleanup before A4 was frozen.

A4 adds explicit `--run-as-user 0` consistently to downloader, frontend and
worker, matching that existing cache's ownership. It does not chown data or
repair cache refs. Default portable behavior is unchanged. The cache observer
now stops immediately on terminal Job failure and preserves exact-Job/Pod
identity and logs instead of waiting for an impossible completion condition.

A4's original Service selector included the controller-owned `managed-by` label,
which Grove overwrote on the frontend Pod. The original failed port-forward is
preserved. A guarded Service-only revision dropped that label, retained the
unique service/frontend identity labels and proved the unchanged endpoint and
GPU identities before sending the original coding request once. The response
completed normally, and canonical a4 cleanup passed at 12:13:29 Pacific.

The renderer now generates that corrected selector; its regression test models
Grove's label overwrite and rejects worker/other-service matches. Fifteen
focused tests pass. [Final baseline receipt](../reports/receipts/2026-11-05-take-home-public-baseline.json).

A4 is closed and must not be replayed. A new qualification must use a fresh
`--run` and current source hashes. Only root executes the following pattern
after the central placement/health audit:

```bash
QUALIFICATION_RUN=results/take-home-NEW-ATTEMPT
uv run python -B take-home/qualify.py freeze \
  --run "$QUALIFICATION_RUN" \
  --runtime-image nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:c186817f4669d615d2b14bee5a6119d35d4d0fe186fdfab69920da8de9d09337 \
  --runtime-version 1.7.0 \
  --expected-dynamo-package-version 1.7.0.dev20261103 \
  --run-as-user 0 --public-candidate
uv run python -B take-home/qualify.py cpu --run "$QUALIFICATION_RUN"
uv run python -B take-home/qualify.py prepare --run "$QUALIFICATION_RUN"
uv run python -B take-home/qualify.py deploy --run "$QUALIFICATION_RUN"
uv run python -B take-home/qualify.py verify \
  --run "$QUALIFICATION_RUN" --timeout 2700 --port 18116
uv run python -B take-home/qualify.py cleanup --run "$QUALIFICATION_RUN"
```

The candidate CPU Pod records actual image ID, package versions, the actual
vLLM architecture registry and engine argument fields, Dynamo's metadata import
and absence of numbered GPU devices. Its bounded Pod is deleted after logs and
identity collection. Failure stops the attempt; the harness changes no packages
or shared platform settings. A successful pull without a Pod pull secret is
useful access evidence, but cluster credential-provider behavior must be
considered before claiming anonymous public availability.

The generated download Job uses the already-qualified shared cache through the
generic `--cache-subpath` option. It checks metadata and shard inventory and
invokes actual offline Dynamo metadata resolution. This qualifies reuse of
cached weights, **not a new network download**, cache permissions on another
storage system or cold-start duration. The owned PV/PVC reuses the existing EFS
CSI configuration; it is a private qualification fixture, not the portable
storage recommendation.

Serving success requires exactly the assigned physical GPU pair, unchanged
image IDs and no restarts, the expected frontend model, a single nonempty coding
response and normal completion. Generated code is never executed. Cleanup
deletes only named owned resources, checks the creating DGD UID and namespace
UID, waits for zero Pods/claims, then releases its lease. Namespace, PV/PVC,
cache and evidence remain retained.

The namespace is created once; a pre-existing name is refused. All later
mutations and cleanup require its original observed UID and ownership label.
Source/input hashes reject changes after freezing. No automatic replay of a
CPU probe, cache Job, deployment or coding request is allowed. An interrupted
attempt remains separate from any explicitly frozen successor.

Final a4 evidence: CPU imports, all eight DRA bundle dry-runs, the actual
generated cached-preparation Job, exact-GPU serving through the explicit
Service-selector revision and canonical scoped cleanup passed.
[Preparation receipt](../reports/receipts/2026-11-05-take-home-public-runtime-preparation.json).

Anonymous registry access has now independently passed for this exact manifest
and config digest, using no local registry credentials. The probe did not
download the 82 layers. [Metadata receipt](../reports/receipts/2026-11-05-take-home-anonymous-image-metadata.json).
This closes the metadata access check separately from the already successful
cluster image pull and CPU imports; serving is supported by the separate
Service-revision and final-baseline receipts.
