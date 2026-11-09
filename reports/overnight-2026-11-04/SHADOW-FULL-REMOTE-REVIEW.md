# Independent full Shadow remote adapter review

Reviewed locally on 2026-11-05. No network, SSH, Kubernetes, Docker or GPU
actions were performed. **No remaining blocker to one bounded durable run**
with the reviewed transport/controller hashes below. Actual execution,
collection, health and root acceptance remain separate gates.

## Findings fixed before freeze

The implementation author addressed these review findings:

1. The immutable map excluded every file whose basename was `state.json` or
   `demo.json`, unintentionally excluding `writer-basis/state.json`. It now
   excludes only the two exact mutable run-root paths. The accepted writer's
   nested state remains hash-bound on every controller phase.
2. The initial pending proof checked status and transcript/raw hashes but did
   not verify the actual private pending seal. It now verifies receipt
   hash/equality, timeline, before-state, pre-fault health, source snapshots,
   archived evidence and the current matching run evidence before finalization.
3. Plan admission now requires the exact node/GPU pair and an exact integer
   fault count of one. Borrowed owner files and lease ancestors must be regular
   paths, so symlink indirection is rejected. The original scoped owner bytes
   are mirrored; the transport does not acquire or rewrite the root lease.
4. Final proof now requires the exact recording output and compares both final
   receipt provenance and current canonical provenance to the sealed pending
   provenance. The first transcript and raw PTY hashes remain unchanged.

Canonical capture and controller validation already provided downstream
rejections for most of these cases. The fixes make the corresponding transport
boundaries enforce those conditions directly; the review did not establish an
earlier false successful GPU result.

## Lifecycle and scope

The package validates the fresh v5 reader candidate, exact frozen input
whitelist, source snapshots, installed-source contracts, writer basis,
config/model pins and required preparation/CUDA gates. It borrows the existing
namespace-scoped full lease and creates only the sibling control directory.
The payload excludes the local lease and credential paths.

The controller deploys once, waits once, verifies active/parked readiness,
captures fresh pre-fault health, records one pending first-fault presenter,
captures post-fault health, invokes canonical full finalization and then
canonical capture finalization. There is no automatic replay of deployment,
capture or the fault. Supervisor journals, health Runs, phase logs and raw
recording remain outside the full run, preserving the pending run's immutable
evidence boundary.

Normal failures stop the child and attempt bounded health collection and
scoped cleanup. If a source/input or ownership guard fails, cleanup safely
refuses to execute changed code or act under altered ownership. The controller
records the cleanup failure and retains the reservation for root investigation;
it does not claim cleanup passed. Terminal status stays
`failed_preserved_for_root_audit` unless qualification and cleanup both pass.

Remote canonical cleanup releases only the isolated remote mirror. The local
root mirror remains held for independent collection/audit and explicit root
closeout. Status/collection use the existing transport's stable, hash-verified
collection mechanism. The full adapter maps the sibling control tree under
`recording-private`; it neither adopts collected state into the original run
nor releases the root reservation.

## Validation

Eight independent tests were added in
`tests/test_workshop_shadow_full_remote_review.py`. Together with the author's
five fixture/lifecycle tests, **13 tests passed**:

```text
PYTHONDONTWRITEBYTECODE=1 .local/venv/bin/python -m unittest discover -s tests -p 'test_workshop_shadow_full_remote*.py' -v
Ran 13 tests in 5.159s
OK
```

The independent tests cover malformed sibling/recording paths, node/pair,
namespace, lease and bool fault count; symlinked owner and lease ancestor;
per-phase nested writer-state/source/owner drift; launch refusal before
transport on source/lease drift; uncertain launch exactly once with retained
root ownership; and safe refusal to start any child after a source guard fails.

Actual local synthetic PTY captures exercise the pending and final proof
helpers. Negative cases tamper with the seal, timeline, before-state,
pre-fault health, source snapshot, archived evidence, current run, final output
and final provenance. All are rejected. These synthetic unit-test fixtures
exist only in temporary directories and are not live demo evidence.

Whitespace checks passed. Source-only inspection also traced the adapted
bootstrap/collector, scoped remote mirror, child stopping and failure paths.
There was no independent live transport or cluster validation in this review.

## Reviewed SHA-256 values

| File | SHA-256 |
| --- | --- |
| Full remote transport | `91168fb258ae48166be5f4b777ee675b2b1f29d8dde3b1ef02ed19c64a1b9dcf` |
| Full remote controller | `eb7a4e4479b805c0f1a92b9e3ec13b6ef06fd90d200182fdaaf0c30305d589f3` |
| Independent tests | `c002516b544fb2e27c93667779593a0e72b7f22d040143f9181dc81516b04fdd` |
| Held capture helper | `c0c9bcd83afcbcf7c9c8b33a8248f2be305ddacecbd272c4a76fe206ab228750` |

Root and the implementation author were notified of these exact hashes before
packaging. No held runtime source, capture helper or central review/status file
was edited by this review workstream.
