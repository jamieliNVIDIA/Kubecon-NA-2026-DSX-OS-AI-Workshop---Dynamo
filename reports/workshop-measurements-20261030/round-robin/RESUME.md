# Resume after the second API outage

**Closed out November 4:** the original C4 pair is collected and verified
locally: **142 files, zero mismatches**, both complete arm inventories/raw
archives, exact analysis reproduction and successful stage cleanup. See
[C4_CLOSEOUT.md](C4_CLOSEOUT.md). The original controller subsequently stopped
at the C1 KV guard; it is terminal, and neither routing-policy pair passed.
Routing needs a new immutable harness/run with fresh client qualification.

The old six-arm [pullback plan](PULLBACK_PLAN.json) remains historical; the
completed C4-only [closeout plan](C4_CLOSEOUT_PLAN.md) preserves the later queue
failure separately. No deployment, benchmark replay, cleanup or lease change
is needed to finish C4. The instructions/checkpoints below are retained for
provenance and must not be invoked as a current recovery queue.

**November 3, 23:34Z update:** the stable controller is running on bastion
`ip-172-31-10-102` in Docker container `kubecon-workshop-controller-20261103`
(ID `5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411`).
It owns all remaining GPU mutations; the local lease is fenced as
`/root/stable_controller`. **Do not run local recovery, deployment, cleanup or
lease-removal commands.** The historical instructions below are inactive.

The original C4 first arm completed and was collected/accepted unchanged:
122 requests, zero errors, original client/worker UIDs and sealed profile/spec.
The stable process is adding the second replica while retaining that first
worker in namespace `dynamo-ft-r610-1ec4908b-rr`. No completed C4 pair is claimed.
The sequence is original r2 → MX artifact04 → fresh RR/KV C1/C4 pairs → cleanup.

Remote physical workspace:
`/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace`.
The container mounts it at the original absolute repository path to preserve
recorded references. Stage receipts are `resume-c4-r2-stable-a1/` and
`continuation-stable-a2/` under `results/workshop-rr-20261103-resume02/` in that
workspace. The local result tree is an earlier snapshot until pulled back.

See [RECOVERY_20261103.md](RECOVERY_20261103.md) for current evidence and recovery
gates. The old client expired; its replacement passed full qualification, and
C1 is referenced through verified hashes. Never remove a retained lease without
proving cleanup for the exact run/namespace that owns it; the legacy agent name
alone is insufficient. Disclose the network pause and change of controller
observer with C4; the cluster-side AIPerf client, model/workload spec and surviving
first worker were preserved.

The resumed **C1 pair completed and is accepted**. Do not rerun it merely because
the later MX turn lost connectivity. C4 and all matched routing-policy profiles
remain unstarted.

## Current ownership

- Completed RR run: `results/workshop-rr-20261102-resume01/`.
- Namespace: `dynamo-ft-r610-2353e254-rr`.
- C1 cleanup verified zero owned GPU Pods/claims at `2026-11-03T07:34:22Z`.
- MX acquired the lease for `results/workshop-mx-startup-20261030-artifact03/`.
  Its later API failure left cleanup unverified and **MX retains the lease**.
- There is no active RR GPU controller. Do not invoke the old October 30 RR
  recovery helper against MX's lease or delete that lease manually.

## Recovery gates

1. Restore access to the same workshop cluster through the existing tunnel.
   MX owns collection/cleanup of its interrupted graph and must explicitly
   verify zero owned GPU Pods/claims before releasing its lease.
2. Verify C1's frozen profiles/specs and `integrity-final.json` inventories in
   `c1-r1-a1/` and `c1-r2-a1/`. Both acceptance summaries require explicit
   `is_complete=true`, `was_cancelled=false`, `submission_valid=true`, positive
   requests and no request/context-overflow errors. Keep original files intact.
3. Verify the current CPU client before reusing any local marker:
   `rr-loadgen` originally had UID `034fcf35-8052-4ba2-82d5-5f556e32f04d`, zero
   restarts and the exact image digest in `model-lock.json`. It was created
   around `2026-11-03T06:21Z` with an eight-hour deadline. Check actual readiness,
   UID, environment and pinned source/corpus/mmap hashes; elapsed deadlines are
   not proof of cleanup or cache availability.
4. If that exact client/cache is intact, perform a fresh read-only C4 cache-hit
   check with a new receipt path after MX timing is finished. The corpus remains
   all 393 roots / 9,450 children / 98,827 turns, source SHA
   `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.
   Dataset/index hashes are in `cpu-transport-recovery-a1/summary-c4.json`.
5. If the client expired or changed, prepare and qualify a fresh immutable
   client/run rather than trusting the old `client-precache.json`. Completed
   C1 proof may be referenced with hashes as a campaign prerequisite; do not
   copy it into a new run as though newly measured. The router helper's
   run-local prerequisite guard must be adapted to validate such references
   before any cross-run continuation. Keep model/hardware/workload pins fixed.

## Remaining execution with the original live client

After MX's explicit cleanup/handoff and current-client verification:

```bash
.local/venv/bin/python \
  reports/workshop-measurements-20261030/round-robin/execute_pair.py \
  --run results/workshop-rr-20261102-resume01 --concurrency 4 --attempt a1
```

The helper acquires the atomic lease, qualifies native serving, seals fresh arm
specs and cleans only its own GPU graphs in `finally`. Preserve failed attempts.
After C4 passes, run the already approved fresh-worker policy pairs:

```bash
.local/venv/bin/python \
  reports/workshop-measurements-20261030/round-robin/execute_router_pair.py \
  --run results/workshop-rr-20261102-resume01 --concurrency 1 --attempt a1

.local/venv/bin/python \
  reports/workshop-measurements-20261030/round-robin/execute_router_pair.py \
  --run results/workshop-rr-20261102-resume01 --concurrency 4 --attempt a1
```

Do not run GPU phases concurrently. Preserve C1/C4, seed, 900 s admission,
300 s drain, mandatory primer and all source/model/runtime pins. The policy
helper rebinds namespace plumbing from frozen templates and records the effective
manifest hash; its two arm templates differ only in frontend router mode.

Use `analyze.py --run ... --concurrency 4 --attempt a1` for completed scale-out
and add `--routing` for a completed policy pair. KV acceptance requires actual
positive predicted prefix overlap, not just registered event streams. Preserve
new analysis outputs immutably. Append final arm inventories without overwriting
the original prevalidation manifest. Finish by collecting/cleaning owned CPU
workloads once no further benchmark needs the client.

## Interpretation and known transport detail

C1's canonical aggregate-rate denominator differed between arms (1200 s versus
905.61 s). Its apparent canonical +24% is **not a capacity speedup**. See
`REPORT.md` and `scaleout-c1-a1-analysis.json` for request-span rates, latencies,
cache-read counters, exact sampled turns and limitations. All C1 measured
records were main-agent requests; the corpus's sibling-prefix example remains
separate evidence.

The full preparation receipt embeds about 56 MB of graph metadata. A progress
poll that printed it through `kubectl exec` was truncated after preparation had
already passed. `resume_client.py` retrieved verified compressed/full receipts
and finished the C4 cache-hit check without rerunning reconstruction or changing
the workload. For future monitoring, emit a small summary and transfer full
receipts compressed with hashes; never shrink the corpus to work around this.
