# Fresh C32 campaign: prepared for root execution

**Terminal result:** [the two-worker routing pair is now accepted](C32-RESULTS.md).
The one-worker canonical primer triggered a liveness restart and was rejected;
there is no one-worker C32 performance score. The controller stopped after
scoped GPU cleanup. The setup/launch notes below preserve the frozen preparation.

The exact frontend model-discovery gate and a fresh C32 campaign are frozen and
offline-validated. This page does not report a live benchmark outcome. Root's
launch, controller and collection receipts are authoritative for execution.

**Root launch observed:** November 5 at **11:08:41 Pacific**, controller
`kubecon-workshop-routing-c32-20261105-a1`, Docker ID
`a4ae19468266c954a35fd4fb46853ba221b57cbcb947447481cf47d0e5154fed`.
The root launch receipt reports success, all 48 files verified and the exact
plan fingerprint below. Its later CPU/cell and independent acceptance receipts
are linked from the result report; launch success alone was not acceptance.

- New owned namespace/CPU client: `dynamo-ft-routing-c32-20261105-a1` / `rr-loadgen`.
- Original routing GPU0+2 pairs on cp-0198/cp-0942; current allocation must be
  checked before launch and is rechecked before each cell.
- Root-approved order: two RR → two KV → one RR, all C32, fresh workers each.
- Prior manifests match exactly after namespace normalization. The canonical
  C32 profile is unchanged: full pinned 393-trace corpus, native context,
  engine cap 128, 900-second admission, 300-second drain, mandatory primer.
- Polling `/v1/models` for the exact model ID is bounded to 120 seconds, before
  any smoke inference. Every observation and timeout is saved. HTTP 200 alone
  cannot pass. The existing four smoke requests and all benchmark controls stay.
- Five tests pass: delayed model publication, wrong model/HTTP-200 rejection,
  transient HTTP failure recovery, malformed response timeout and a fetch
  consuming the deadline. Shared/P-D frozen helpers and old results were not
  edited; no network operation was performed by the preparing agent.
- The CPU client handed to P/D remains exclusively theirs. This campaign
  prepares an independent source/cache/client in its own namespace.

Frozen plan SHA256:
`cde44a8f66b68edfac8a1e8b8c3f0f0b90c0b7396f3f6e72286519654badb2ab`.
Payload SHA256:
`9c641106c3efb2dac4dfa24645e0e58c1c2448a9dde5d0b2ea3a576305a063dd`.
The payload contains 48 frozen files. [Preparation receipt](../../receipts/2026-11-05-routing-c32-preparation.json).

Root executes the launch once, after confirming the assigned GPUs are free:

```bash
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-c32/controller.py launch
```

Do not rebuild/refreeze an attempted campaign. The launcher refuses replay of
an existing controller or a previous launch attempt. It prepares the CPU client,
qualifies the full corpus, executes the three bounded cells and scopes cleanup
to this new namespace. A failed cell stops execution without retuning.

Read-only observations and immutable collections require fresh labels:

```bash
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-c32/controller.py probe --label UNIQUE
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-c32/collect.py --label UNIQUE
.local/venv/bin/python -B reports/overnight-2026-11-04/routing-c32/analyze.py \
  --run results/workshop-routing-c32-collection-UNIQUE/verified/results/workshop-routing-c32-20261105-a1 \
  --output results/workshop-routing-c32-collection-UNIQUE/analysis.json
```

Retain N=1/order, realized mix and concurrent node CPU/EFS/network limits. This
new order and independently initialized cells do not create a controlled
capacity curve when spliced with the earlier C16 observations. Keep a failed
one-worker arm separate from any clean two-worker routing comparison.
