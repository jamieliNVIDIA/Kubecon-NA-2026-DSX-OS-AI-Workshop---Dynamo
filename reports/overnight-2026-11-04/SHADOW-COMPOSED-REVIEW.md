# Independent Shadow composition review

Reviewed November 5, 2026, after descriptor-writer a3's failed startup. This is
a source review, not live qualification. No tests, network calls, GPU actions
or implementation edits were performed by the reviewer. The author's follow-up
identity-fencing patch has now been independently read; no remaining concrete
blocking source defect was identified in the reviewed paths.

## Finding and author resolution

The fault must be bound to the exact runtime that passed the active/parked
reader and three-correct-coding-request gate. The initial composition trusted
the saved ready status and let the inherited verifier take a new snapshot.
A replacement Pod, engine container or GMS generation could therefore inherit
an earlier generation's readiness proof.

The author added `validate_ready_observation` and a checked snapshot wrapper,
plus a negative test for changed GMS container identity. That addresses drift
between ready qualification and the verifier's initial snapshots. The reviewer
then requested two checks at the final mutation boundary:

- Compare the actual DGD UID to `shadow_full_dgd_uid` during startup and before
  fault injection. The inherited `owned_pod` validates labels, but not this
  frozen UID. A same-label recreated DGD must not be qualified or faulted;
  UID-fenced `stop` would subsequently refuse to delete it.
- Recheck both engine containers and GMS container IDs/restart counts after
  the verifier's baseline request and infrastructure preflight, immediately
  before fault intent/exec. The inherited verifier currently rechecks only
  Pod UID and the active container ID at that boundary. A standby/GMS restart
  after the checked snapshot must prevent the kill. Add negative tests for
  that sequence, not only for a changed initial snapshot.

The finding is local controller lifecycle/provenance handling, not evidence of
an upstream Dynamo defect. The reviewer sent it directly to `shadow_presenter`
and the root coordinator; no source edits were made independently.

The author's completed follow-up resolves both requests:

- `assert_graph` checks the recorded DGD UID, generation and applied serving
  spec hash during startup and each guarded verifier observation.
- The fault-intent write hook takes a fresh complete runtime/GMS observation
  and compares it with the saved ready generation. This runs before the
  verifier starts its recovery timer.
- The final kill hook repeats only lightweight DGD and all-engine/GMS
  container ID/restart checks, then calls the unchanged PID/lock-guarded kill.
  No additional CUDA-context probes run inside that timer. The recovery proof
  explicitly includes these lightweight reads in its timing scope.
- All patched snapshot/write/exec callbacks are restored in `finally`.
  Negative tests cover a same-label recreated DGD, changed standby/GMS after
  the baseline observation but before fault intent, and final kill-boundary
  container mismatch.

## Other reviewed paths

No other concrete blocking defect was identified in these paths:

- Freeze requires actual writer serving, both rank descriptors and final
  no-new-Xid health qualification. Manifest hashes, source/model/image/rank
  identity, stable serving/container/GMS capture provenance and supported
  attention runtime are checked before a full candidate is created.
- The composed overlay retains the original GMS materializer and its
  shape/dtype checks. Serving arguments and the measured FP8-cache profile
  remain inherited from the instrumented writer. The full composition adds
  failover and container discovery rather than changing quantization.
- The descriptor `emptyDir`, mounts and identity/directory environment entries
  are replaced before re-rendering, so the inherited additions are not doubled.
- Startup requires real active/standby states on the assigned physical GPU
  pair, three validated coding streams and unchanged engine/GMS observations.
- The inherited verifier persists one fault intent, targets one checked active
  EngineCore PID under a held matching lock, checks a changed serving worker,
  exactly one promotion, unchanged committed weights/GMS/standby identity,
  reclaimed failed-engine KV backing and replenishment of a parked standby.
- Cleanup stops the UID-matched owned DGD before checking zero remaining
  Pods/claims and releasing the scoped DeviceClass/reservation. Original
  evidence and the cache remain retained.

All **12 current composition tests** were read; the author reports them
passing. They are offline controller tests; the reviewer did not rerun them.
The actual writer descriptor gate remains blocked by a3's failed restart, so
no full reader candidate or promotion result follows from this review.
