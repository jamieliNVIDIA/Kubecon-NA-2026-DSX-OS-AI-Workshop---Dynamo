# Full-only Helm transport review

**Accepted for root's actual CPU preflight and next fresh candidate.** Thirty-four
focused tests pass, including seven independent tests. This reviewer made no
Docker, SSH, cluster or GPU calls and changed no runtime/transport sources.

The a4 failure was an unavailable Mac-specific Helm path inside the Linux
controller, before any fault. The fix binds the existing qualified Linux host
binary read-only at that compatibility path. It pins both paths, exact binary
SHA and version in the Full transport plan/manifest. It preserves the current
controller image, native model/reader code, twenty-input optional cache
contract and single-fault/capture lifecycle.

The preflight and launch bootstrap share the same implementation: verify host
bytes/permissions, run the exact image without GPUs, verify mounted Helm bytes
and version, then execute the native read-only DRA `helm get values` query.
Both GPU enablement settings must be actual booleans. The bootstrap retains
the probe receipt and rechecks host bytes before detaching the controller.
Native/Docker timeouts and malformed or failed results cannot pass the gate.

Independent checks exercised the generated probe's actual metadata body with
explicit I/O doubles, verified fixed read-only mounts/same-image/no-GPU
arguments, and rejected path/hash/version/schema/command/driver flag changes.
The failed a4 package remains hash-valid and readable.

Compared with a4's recorded 186 transport source entries, only
`workshop_shadow_full_remote.py` changes. AST reconstruction proves that the
delta is limited to six Helm helpers, the pinned binding/import and five
Full-specific plan/build/bootstrap/launch/preflight functions. All other
statements, all thirty-two held a4 critical files, and native/writer/v6/CPU,
common Snapshot/image and capture sources remain unchanged.

- Transport SHA: `ed1252ec5c281cac4dabbbea49569fdf349dce3f3703b0f39c75203d40184185`.
- Helm SHA: `7a319dee5ea7a1f7d7a0d92d5c223586f3b65abc33163c9de2a85f083aa3df2b`.
- Helm version: `v3.22.0+g144ca65`.
- Independent receipt:
  `results/shadow-full-helm-independent-review-20261105-a1/verification.json`.

Root must still execute and retain the real same-image Helm preflight; local
tests are not live compatibility proof. The bootstrap repeats that check
before GPU work. This change establishes no fault, recovery or SLO result.
