# Snapshot runtime adapter: upstream overlap

Checked November 4, 2026 against Dynamo main
`e51394e7d7d3d3fbe21301b490516baed524b87a`, actual PR merge metadata,
and open/closed PR and issue searches. This is source research; no new runtime
or cluster qualification was performed. The existing successful adapter trial
remains described in [the qualification report](workshop-snapshot-dgd.md).

| Adapter concern | Upstream work and status | Implication for the workshop |
| --- | --- | --- |
| Release KV without moving weights to the host | [Dynamo #15887](https://github.com/ai-dynamo/dynamo/pull/15887), merged October 13; [#16358](https://github.com/ai-dynamo/dynamo/pull/16358), merged into `release/1.6.0` October 14 | Substantial overlap already exists. Upstream uses `_ReleaseOnlyKvCache` for non-GMS engines exposing `release_kv_cache_memory()`; its description specifies vLLM 0.31+. Our pinned image's original module lacks this wrapper. |
| Preserve multi-GPU CUDA state | [#15791](https://github.com/ai-dynamo/dynamo/pull/15791), merged October 7; Snapshot v0.2.0 bump [#16744](https://github.com/ai-dynamo/dynamo/pull/16744), merged October 19 and backported by [#16819](https://github.com/ai-dynamo/dynamo/pull/16819) | CuInterpose integration is upstream. Our adapter additionally bypasses separate vLLM communicator hooks; that extra difference is not covered by the KV-only change. |
| Refresh destination Pod/runtime identity | [#10376](https://github.com/ai-dynamo/dynamo/pull/10376), merged June 22; served-name extension [#17246](https://github.com/ai-dynamo/dynamo/pull/17246), merged November 4 UTC | The refresh machinery is upstream and our adapter reuses it. Main still obtains its context file through the standby entrypoint; no matching bridge from the newer PID-1 proxy was found. |
| Preserve destination offline policy after restore | Main's lifecycle still executes `os.environ.pop("HF_HUB_OFFLINE", None)`; the restore-context allowlist lacks that setting | No matching destination-policy restoration PR was found. The adapter's explicit restoration of the proxy's policy remains a separate change. |
| Keep registration metadata on the intended revision | [#11369](https://github.com/ai-dynamo/dynamo/pull/11369), open: carry worker revision through registration and frontend resolution | Related to the cache-ref problem found during qualification; this does not itself fix the Snapshot offline-policy handoff. |

## Differences that still need investigation

Current main still uses `VllmEnginePauseController` with
`prepare_for_process_checkpoint=checkpoint_hooks`, including the KV-only wrapper.
The hooks came from [#12226](https://github.com/ai-dynamo/dynamo/pull/12226), merged
September 1, to tear down and rebuild communicator state around restoration.
Our qualified controller leaves that preservation to CuInterpose. Therefore the
upstream KV-only change is not identical to our entire pause/resume controller;
verify the upstream path on the selected runtime before removing the overlay.

The restore-context mismatch has a concrete upstream source:
[Snapshot #537](https://github.com/ai-dynamo/snapshot/pull/537), merged October 15,
replaces restore-container commands with its PID-1 proxy and deprecates the
standby environment variable. Dynamo's existing context writer runs in that
standby path. Its replacement command never reaches the writer in our setup.
Our adapter supplies the missing file from allowlisted proxy environment and
then retains Dynamo's ordinary refresh/registration flow.

Related open [Dynamo #15556](https://github.com/ai-dynamo/dynamo/pull/15556) expands
allowed Python restore entrypoints, but still requires the standby hook; it does
not bridge the proxy/context gap. [#13500](https://github.com/ai-dynamo/dynamo/pull/13500)
proposed new NIXL identity after restore, but was closed without merge and concerns
P/D transport re-registration rather than this aggregated worker's Pod identity.

For registration, [#10102](https://github.com/ai-dynamo/dynamo/pull/10102) merged
metadata-only registration and cache-first lookup in May. Current main's
`hub::from_hf` still checks the local cache before network access. This can avoid
the external lookup with a usable cache, but it does not preserve the Pod's
explicit offline policy or resolve an ambiguous/unpinned revision. Keep those
concerns separate.

Snapshot also has application-lifecycle work: proposal
[#437](https://github.com/ai-dynamo/snapshot/pull/437) and post-restore notification
[#738](https://github.com/ai-dynamo/snapshot/pull/738) are merged. The latter's
description still notes a gate outside e2e. File/HTTP notification alone does
not implement Dynamo destination-environment capture.

## Recommended next step

Build or select a runtime containing the upstream KV-only path, then compare it
with our qualified controller on the same frozen configuration. Retain focused
fixes for proxy-to-Dynamo context handoff and destination offline policy until
their upstream equivalents are verified. An image upgrade alone is not yet
evidence that the entire overlay can be removed.

Private source/PR status evidence:
`results/workshop-snapshot-upstream-20261104-a1/status.json`. Negative searches
are bounded evidence, not proof that no differently named work exists.

## Follow-up execution

The [upstream-controller trial](workshop-snapshot-upstream-controller.md) passed
capture, initial restored inference, automatic replacement and fresh inference
through the same frontend in the pinned image. Native controller/hook behavior
can therefore replace our custom pause controller in this qualified setup.
The identity/offline bridge is still required. This was a backport of merged
PR #15887's module into the same image, with matching engine/GPU/storage settings;
it does not qualify a full image upgrade or an unmodified upstream deployment.

## Open upstream workstream

Decision November 4, 2026 Pacific: **open; Neal will initiate a separate workstream**.

Scope:

- Integrate destination Pod/runtime context handoff with Snapshot's restore proxy
  in the common restore path, using an agreed application contract.
- Preserve the destination Pod's explicit Hugging Face offline policy after
  capture's temporary forced-offline setting is removed.
- Generalize the current bridge's proxy-path, changed-Pod-UID and existing-context
  assumptions; cover the supported restore lifecycles and policy values.

Keep the qualified workload-local bridge for workshop preparation. Close this
item when the upstream fixes are available in a selected image and that image
passes capture, initial restored inference and automatic Pod replacement through
the frontend without the custom runtime overlay. The existing EFS and
[NVMe qualifications](workshop-snapshot-dgd-nvme.md) provide regression evidence.
The artifact-specific private NVMe mount harness is environment-specific test
plumbing and is outside this upstream runtime workstream.
