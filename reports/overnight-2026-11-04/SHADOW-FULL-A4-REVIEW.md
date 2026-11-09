# Full-a4 independent audit

**Accepted evidence: RAM staging and initial Shadow service passed.** The
presenter then failed on a missing controller-side Helm executable during
infrastructure preflight. No fault was injected; promotion, recovery, request
survival and SLOs remain unqualified.

Machine-readable audit:
`results/shadow-full-a4-independent-audit-20261105-a1/verification.json`.
The recorded read-only verification program is beside it; its live-workspace
source-hold checks describe the audit checkpoint, before authorized later
transport edits. This review made no runtime,
transport or capture changes, network/GPU calls, commits or pushes.

## Evidence and actual progress

The immutable collection is
`results/shadow-full-a4-remote-collected-20261105-a1`. All **1,978 files** and the
archive were independently rehashed. The audit verified all twenty frozen
inputs, thirty-two held source files, 134 runtime contracts, sixteen accepted
writer receipts, 204 immutable transport-run files, 186 transport source files
and 393 payload entries. All 69 capture sources and 912 captured evidence files
match their retained hashes. Original local state/demo bytes still match the
pre-launch package; remote state was not adopted.

| Evidence | Verified result |
| --- | --- |
| Worker RAM cache | 114 files, 75,063,320,262 logical bytes; 88 weight files / 75,010,188,240 weight bytes; 153.1147 seconds; CUDA uninitialized |
| Actual init | Exact pinned runtime image, zero restarts, exit zero; same worker Pod UID; 96 GiB memory-backed emptyDir at HF_HOME |
| Engine cache use | Both engines mount the verified cache read-only; native GMS loader remains unchanged |
| Source producer | Same qualified Pod UID, image, container/seed generations and direct IP before deployment and after staging |
| Initial service | One active engine and one parked reader; all three Ready/Started/running; fixed GPU pair/node; stable container generations and complete GMS observations |
| Fresh coding | Three retained numbered responses equal the aggregate; raw SSE completes with `[DONE]`/stop, correct model and `add(a,b)` result; worker identity matches active-engine registration |

The three coding streams took 30.9181, 1.7127 and 1.7095 seconds respectively.
These are initial request observations, not a latency target or SLO result.
CPU file staging is not GPU peer weight transfer or combined native GMS/MX
loader qualification. No isolated startup-speedup comparison is claimed.

## First failure and fault boundary

The actual main-panel transcript is retained as `recording/failed-main.txt` in
the collection. During step 3, `shadow_failover_tests.preflight` line 33 invokes
the Mac-specific absolute path `/opt/homebrew/bin/helm` inside the Linux CPU
controller. `subprocess` raises:

```text
FileNotFoundError: [Errno 2] No such file or directory: '/opt/homebrew/bin/helm'
```

The capture exited unsuccessfully after 9.57 seconds, without timeout or
interruption. This is a host harness/container portability gap. It is not a new
reader, GMS or model-runtime failure. No fault intent, kill command, fault
receipt, recovery proof, failover pass or final qualification exists. The
configured single-fault allowance was **not consumed**; observed fault count
is zero. The failed attempt must remain immutable rather than be replayed.

## Health and cleanup

Start, pre-fault and post-failure health agree on node, driver Pod and boot
identity, with unchanged conditions and no new Xid bodies. The recorded
post-failure health precedes cleanup; root's fresh live closeout is separate.

Canonical remote cleanup passed at **01:44:13Z**. Retained successful command
receipts show owned DGD deletion, empty Pods/claims before bootstrap removal,
owned immutable bootstrap ConfigMap deletion and exact DeviceClass deletion.
The controller reports its scoped mirror released. Root's local mirror still
awaited root closeout when audited; this reviewer did not remove it. Root
subsequently combined independent acceptance with fresh live/source/health
checks and released the exact mirror; completed closeout is
`results/workshop-shadow-full-a4-root-closeout-20261105-a1/complete.json`.

Archive SHA:
`73ab4252e00bb87ece4f4b924e5b4c213f6820d52e9b16a12168060c8705c8c2`.
Full spec SHA:
`e6dc90dffc04072e8f0b1edd7b253624c43cb5f94f8a1fbeb0c200f88efa8053`.

The failed attempt is closed and remains preserved. The next change should
address controller Helm portability while preserving
the validated runtime, model, reader adapter and CPU program.
