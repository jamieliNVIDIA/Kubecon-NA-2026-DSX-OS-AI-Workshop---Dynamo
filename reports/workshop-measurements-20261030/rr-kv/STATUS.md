# RR versus KV routing status

Stopped at the user's direction November 4, 2026 at 17:51 PST, before C4
profiling. C1/C4 are too low to answer the capacity question. The replacement
[C16/32/64/128 sweep](../load-sweep/STATUS.md) covers both replica scaling and
routing with a higher common engine sequence cap.

The controller is terminal and its GPU workers, DGDs and ResourceClaims are
gone. Both remote and local scoped leases were released after verification.
Snapshot/other workstreams were untouched. **680 files** were pulled back with
zero mismatches to `results/workshop-rrkv-stopped-pullback-20261104-a1/`.
The old CPU client was also deleted at 18:02 PST after an exact UID check.
CPU qualification and both C1 arms
passed; the C4 routing profiles did not run. This campaign is user-stopped,
not a completed four-arm performance comparison.

Preliminary C1 observation (one fixed-order pair):

| Metric | Round-robin | KV |
| --- | ---: | ---: |
| Valid requests | 81 | 84 |
| TTFT p50 | 381 ms | 313 ms |
| TTFT p99 | 5.82 s | 2.90 s |
| Server-reported cache-read | 95.08% | 97.62% |
| Mean active decode tokens/s/user | 149.18 | 149.86 |
| Canonical aggregate output tokens/s | 66.26 | 53.79 |
| Canonical throughput denominator | 900 s | 1,200 s |

Both C1 arms passed export validity, error/context/cancellation and worker/
discovery checks. KV selection observed 84 samples and positive prefix overlap.
Final arm inventories were checked remotely and match. The canonical aggregate
rates have different drain-inclusive denominators, and realized request mixes
differ; this is not evidence of a capacity speedup or slowdown. C1 can expose
cache placement between sequential turns without establishing a need for more
compute. Complete local pullback is verified; full analysis reproduction is
optional historical closeout, and C4 will not resume in this campaign.

Observation receipts: `results/workshop-rrkv-observations-20261104/status-20261104-01/`.

Launched at 16:27:25 PST, the detached controller
`kubecon-workshop-rrkv-20261104-a1` consumes the frozen
plan with SHA256 `cbb256650aacc62cabb51b593c6ea3d32b3279cc00b42f7ff38242070554772c`.
Evidence belongs to `results/workshop-rrkv-20261104-a1/` and controller receipts
to `results/workshop-rrkv-controller-20261104-a1/` on the stable workshop host.

The campaign used four frozen H100 UUIDs on cp-0198/cp-0942. Frontend and CPU
client were placed on cp-0942. Its separate
`.local/workshop-rrkv-20261104.gpu-lease/` has been released.

Original planned sequence: CPU preparation/qualification → C1 RR → C1 KV →
C4 RR → C4 KV. Actual sequence stopped during C4 RR startup, then verified
scoped cleanup and complete pullback. See the preserved [frozen plan](PLAN.md).

Offline qualification passed eight discovery tests, the real prior failure
fixture, frontend-only policy difference, explicit GPU/node exclusion and an
allocation regression that rejects a foreign claim on a selected GPU.
