# Round-robin comparison status

C1 and C4 scale-out pairs passed and are verified locally. C4 closeout completed
November 4: **142 files with zero hash mismatches**, all final-inventory entries,
both original raw archives, and exact local reproduction of the remote analysis.

The original stable controller is terminal. C4's stage exited zero and verified
GPU cleanup; the later continuation exited one at the C1 KV discovery guard.
The C1 KV AgentX workload and C4 routing-policy pair never ran. Their comparison
requires a fresh harness/run; no routing performance result is claimed.

C4 is one fixed-order observation at four live session trees: 122→114 successful requests, mean active decode 139.79→151.52 tokens/s/user, TTFT p50 306.19→477.59 ms, cache-read 95.79%→90.72%. This is fixed-load operational scale-out; matched routing results are needed for a routing claim.

The two-worker C4 arm split **57 requests per worker**. Its workload mix was
56 main / 57 subagent / 1 flat request, versus 61 / 60 / 1 in the first arm.
GPU admission-window means were 35.47–37.22%, versus 65.42–65.46%; 180 samples
per GPU. Neither arm completed a full agent graph.

Complete evidence: `results/workshop-c4-closeout-20261104-a1/verified/`.
Original partial mirrors and inventories remain unchanged. This closeout changed
no cluster resources or leases and reran no benchmark. Preserve the inter-arm
network pause, controller-observer change, different turn mixes and N=1 limits.

See [C4 closeout](C4_CLOSEOUT.md), [measurement report](REPORT.md) and
[separate routing diagnosis](KV_DISCOVERY_DIAGNOSIS_20261104.md).
