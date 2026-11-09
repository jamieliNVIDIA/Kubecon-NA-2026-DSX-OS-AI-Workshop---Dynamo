# Shadow final-parameter inventory: independent review

The metadata-only inventory helper passed independent review and **14 focused
tests**. No remaining blocker was found for its bounded CPU diagnostic role.
The author separately reran the same tests successfully. Real runtime CPU
qualification and any GPU execution remain separate gates.

Reviewed module: `scripts/workshop_shadow_parameter_inventory.py`.
SHA-256: `2d6ef1664d7746edd922c9281dcb6d8a30fa2f91d7d0abfeeaf5114e950623ef`.
Tests: `tests/test_workshop_shadow_parameter_inventory.py`.
SHA-256: `1ce47744aeac79b84c6107a8f6ff2a3e6846a7f1266c340d9f557a898cf5ef15`.

The reviewer edited only that test file and this note. The author owns the
inventory implementation, v3 integration, controller and CPU payload. No
network, GPU, model export or cluster operation was performed by this review;
v2 and prior frozen attempts remain unchanged.

## Findings resolved before freezing

1. **Same-identity stale peer adoption.** A leftover peer rank file could satisfy
   the original barrier when the local rank file was fresh. Matching candidate
   identity and the local PID alone did not establish a fresh peer process.
   The author added random generation tokens and a second immutable ACK from
   each rank, each referencing the same pair of fresh tokens. A stale peer
   without an ACK now times out; a prior-generation ACK is rejected. Existing
   local inventory files cannot be overwritten or adopted.
2. **Nonfinite timeout.** NaN/infinity could make the original peer wait
   unbounded. The author now rejects nonpositive, nonfinite, boolean and
   nonnumeric timeouts before metadata inspection or publication.
3. **Unsafe exception formatting.** Formatting an exception with a tensor or
   opaque object argument can invoke that object's representation and read
   tensor contents. The author now records typed safe arguments and formats
   only a single builtin string message. Tripwires verify that opaque
   exception arguments are not rendered.
4. **Malformed metadata preempting the diagnostic.** A non-JSON metadata getter
   value could stop construction before rows were printed. The author now
   records its type and an inspection error, preserves subsequent rows and
   fails the rank barrier before export. Text conversion for dtype/device/layout
   is restricted to builtin strings and the reviewed Torch metadata types.

These are diagnostic-harness fixes. They do not relax integer/gradient/layout
export rules or establish the cause of the previously captured exporter guard.

## Coverage and limits

The tests use tensor metadata doubles with value, pointer, representation,
iteration, GPU and copy APIs configured as tripwires. They cover:

- Direct owned slots, tied parameters, module aliases, None slots, CPU/meta
  metadata, exact dtype/gradient/shape/stride, scalar shape and Fraction/None
  layout attributes. An unsupported integer/gradient combination is retained
  unchanged for the strict exporter to reject afterward.
- Opaque metadata, malformed metadata and opaque exception arguments without
  value access or unsafe text conversion. Inspection errors preserve all rows
  and prevent exporter execution.
- Two actual CPU threads completing the rank/ACK rendezvous; per-line JSONL
  flushing and both inventories being complete before a stub exporter executes
  its unchanged strict failure.
- Complete fsynced JSON before atomic no-replace publication, private file mode,
  publication-error cleanup, exact emitted digest and no stale-file overwrite.
- Foreign candidates, missing generation tokens, same-identity stale peers,
  prior-generation ACKs, stale local files and truncated peer JSON. None can
  produce an all-ranks-ready result.
- Invalid timeout/rank/path inputs failing before metadata reads or files.

PyTorch is not installed in this local test environment. A fake `cuda:1` device
only tests that GPU-shaped metadata does not trigger a tensor operation; it is
not a GPU qualification. The root/author's CPU payload must still exercise the
installed runtime's real metadata types and final model integration. The helper
does not produce reader descriptors, copy tensor data or alter exporter guards.

Validation command:

```bash
.local/venv/bin/python -B -m unittest discover -s tests \
  -p test_workshop_shadow_parameter_inventory.py -v
```

All 14 tests passed in approximately 0.2 seconds. No broader rerun or live
experiment is inferred from that result.
