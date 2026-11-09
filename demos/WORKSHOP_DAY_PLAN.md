# Workshop day: GPU allocation and sequencing

Status: **November 8, evening. Ready offline; not yet delivered or run on the
cluster.** The VPN was down while this was built. The pins, named leases and
the Qwen Shadow variant pass the offline test suite (926 tests). Nothing below
has run on the cluster yet. Until tonight's steps pass, the [runbook](RUNBOOK.md)'s
one-group-at-a-time flow applies.

The goal: run every demo's important step live, and stage everything else
before the session. All demos are primed at the same time on the cluster's 24
GPUs, each on its own pinned GPUs. What happens on stage is the action (a
deploy, a fault, a request), not the startup.

## What runs live, what is staged

| Talk time | Demo | Live on stage | Staged before the session | Fallback recording (`demos/transcripts/live/`) |
| --- | --- | --- | --- | --- |
| ~0:12 | single-replica | Apply the DGD, operator resources, startup (about 8 min: talk over it), model discovery, a coding request | `prepare` | `01-single-replica/20261105-overnight-a2` |
| ~0:27 | modelexpress | Start replica 2 (about 4 min), the rank-to-rank transfer proof, a request through its frontend | `prepare`, run quietly once the intro is Ready (~0:21) | `02-modelexpress/20261108-a1` |
| — | metrics, routing | Recorded evidence | `prepare` (local checks) | Recorded by design |
| ~0:46 | kvcr | The pinned-request walkthrough (about 20 s of cluster time) | `prepare`, `prime` at T−135 | `07-kvcr/20261108-a3` |
| ~0:58 | disaggregated | Both pools, a request, the NIXL KV handoff | `prepare`, `prime` at T−130 | `03-disaggregated/20261104-a1` |
| ~1:25 | request-continuity | Both fault cases: migration off, then on | `prepare`, `prime` tonight | `05-request-continuity/20261104-a2` |
| ~1:45 | shadow | Kill the active engine, promotion, the new standby (Qwen3-0.6B on one GPU) | `prepare`, `prime` tonight | Recorded tonight at its qualification (step 4) |
| ~1:58 | snapshot-dgd | Delete the worker Pod, restore from NVMe (about 64 s to Ready), a coding request | `prepare`, `prime` tonight | `04-snapshot-dgd/demo-04-dgd-live-20261105-a3` |

Talk times follow the presenter script's section budget (workshop-script.pptx,
slide 37), counted from the start of the Dynamo section.

## GPU allocation: all 24 at once

| Node | gpu-0, gpu-2 | gpu-1, gpu-3 | gpu-4, gpu-5 | gpu-6, gpu-7 |
| --- | --- | --- | --- | --- |
| cp-0124 | Intro and ModelExpress source (started live) | Snapshot (fixed: its checkpoint is on this node's NVMe) | Continuity, migration-off worker 1 | P/D prefill |
| cp-0198 | ModelExpress replica 2 (started live) | P/D decode | KVCR A | Continuity, migration-on worker 1 |
| cp-0942 | Continuity, migration-off worker 2 | Shadow on gpu-1; gpu-3 spare | KVCR B | Continuity, migration-on worker 2 |

- **Intro and MX source stay on cp-0124.** MX has only been qualified sourcing
  from cp-0124 to cp-0198 (Nov 4, 7, 8), so the direction stays the same. The
  Nov 7–8 source sat on gpu-1/3, which Snapshot needs, so it moves to gpu-0/2.
  The intro ran live on that pair on Nov 4, and an MX source started there on
  Nov 5. No transfer has run from it yet; step 7 below closes that if there's time.
- **P/D** keeps its qualified split: prefill on cp-0124, decode on cp-0198.
- **Continuity:** each case's two workers must be on different nodes. The off
  case uses cp-0124 and cp-0942; the on case uses cp-0198 and cp-0942.
- **KVCR** keeps [placement.json](kvcr/placement.json): A on cp-0198, B on
  cp-0942. These are the GPUs of the Nov 5 a6 pass. The 7.84× speedup was
  measured with B on cp-0124, so the speedup with B on cp-0942 is unmeasured.
  Quote the numbers on screen.
- **Shadow** runs Qwen3-0.6B at TP1: GMS and both engines share one GPU.

EFA per node, out of 32: cp-0124 uses 16 (intro 8, P/D prefill 8); cp-0198
uses 21 (replica 2: 8, P/D decode: 8, KVCR: 5); cp-0942 uses 5 (KVCR).
Continuity, Snapshot and Shadow request none.

Only cp-0942 gpu-3 is unused. Every fallback is a recording.

### Where each assignment lives

| Demo | GPUs pinned by | Reservation |
| --- | --- | --- |
| Intro and MX | `WORKSHOP_ALLOCATION=$PWD/demos/allocations/workshop-intro-mx.json` | `.local/workshop-intro-mx.gpu-lease`, named in that file |
| P/D | `WORKSHOP_PLACEMENT=$PWD/demos/allocations/workshop-disaggregated.json` | `WORKSHOP_LEASE=workshop-disagg.gpu-lease` |
| Continuity | `WORKSHOP_PLACEMENT=$PWD/demos/allocations/workshop-request-continuity.json` | `WORKSHOP_LEASE=workshop-continuity.gpu-lease` |
| Snapshot DGD | [dgd-profile.json](snapshot/dgd-profile.json) (fixed) | `WORKSHOP_LEASE=workshop-snapshot.gpu-lease` |
| KVCR | [placement.json](kvcr/placement.json) (fixed) | Its own per-run lease |
| Shadow | `QWEN_NODE`, `QWEN_UUIDS` in [demo.py](shadow/demo.py) | Its own namespace lease |

How the variables behave:

- **P/D, continuity, Snapshot:** set their variables from the table only on
  `prepare`, the command that creates the run. The run records them; `prime`,
  the walkthrough and `cleanup` need none. Repeating the same value is fine, a
  different one is refused.
- **Intro and MX:** set the same `WORKSHOP_ALLOCATION` on every intro and MX
  command (prepare, run, cleanup). MX checks that the intro still owns its
  reservation, and without the variable it looks at the shared lease and
  stops with "The first replica no longer owns its GPU reservation".
  An allocation only works with a fresh intro run.
- **Absolute paths only.** The files are read relative to the current directory.
- `WORKSHOP_LEASE` together with `WORKSHOP_ALLOCATION` is refused, and so is
  continuity with `WORKSHOP_ALLOCATION`.
- **Checked after scheduling.** P/D and continuity compare the actual node and
  GPUs of each worker with the pins during `prime`. A mismatch fails the prime.
  The result is in `demo.json` as `placement_observed`.

<details>
<summary>GPU UUIDs</summary>

| Node | GPU | UUID | Slot |
| --- | --- | --- | --- |
| cp-0124 | gpu-0 | GPU-c220c1d0-843c-ce3c-b1f9-3ad67af277d7 | Intro / ModelExpress source |
| cp-0124 | gpu-2 | GPU-ea836524-584e-0719-d7bb-0de129f5e7d3 | Intro / ModelExpress source |
| cp-0124 | gpu-1 | GPU-ce4aaec3-4fd1-f047-a303-80986bc29110 | Snapshot |
| cp-0124 | gpu-3 | GPU-75461e0d-6588-94c9-2517-dca859f5c68b | Snapshot |
| cp-0124 | gpu-4 | GPU-b896cc31-be76-0f28-2e2d-d82564b624b7 | Continuity off, worker 1 |
| cp-0124 | gpu-5 | GPU-a63322d6-c08e-79cb-c42a-031aeb4c1488 | Continuity off, worker 1 |
| cp-0124 | gpu-6 | GPU-b0ee6c73-bb3a-38e9-0546-30279eca76f5 | P/D prefill |
| cp-0124 | gpu-7 | GPU-aca1caa2-27c5-8591-6e84-fa0203889f51 | P/D prefill |
| cp-0198 | gpu-0 | GPU-3aea3e1e-63c3-41cd-43be-4e379ed995b5 | ModelExpress replica 2 |
| cp-0198 | gpu-2 | GPU-08dc0ef4-2e92-4cc2-6adc-b735980a1326 | ModelExpress replica 2 |
| cp-0198 | gpu-1 | GPU-c22769a2-282c-de40-459e-261999971cd9 | P/D decode |
| cp-0198 | gpu-3 | GPU-7338f39e-745f-e46a-7ef6-cc8cc155d7af | P/D decode |
| cp-0198 | gpu-4 | GPU-46608a07-1b00-810d-0d07-2fdf65a8e41f | KVCR A |
| cp-0198 | gpu-5 | GPU-23de81ec-c1e4-39a3-578a-ef7d7a3649cf | KVCR A |
| cp-0198 | gpu-6 | GPU-3790a112-5f2d-70e8-e65f-30dfa66869e0 | Continuity on, worker 1 |
| cp-0198 | gpu-7 | GPU-c78f34dc-e790-cfc7-1745-be1cb2e98409 | Continuity on, worker 1 |
| cp-0942 | gpu-0 | GPU-c15ae016-71f1-03bc-0228-624adbb1b4e8 | Continuity off, worker 2 |
| cp-0942 | gpu-2 | GPU-4aacb1e1-a109-70bb-6b72-8071d736ba75 | Continuity off, worker 2 |
| cp-0942 | gpu-1 | GPU-7b0cff01-e024-1e7f-5c2e-53c85b3835e4 | Shadow |
| cp-0942 | gpu-3 | GPU-bd8b4452-af4b-12ab-237d-63d32996835c | Spare |
| cp-0942 | gpu-4 | GPU-09ecbc64-ad4f-708b-6ca3-ba1ba5fd052f | KVCR B |
| cp-0942 | gpu-5 | GPU-e7ecf749-a1dc-bc9d-890c-f5376c5b995f | KVCR B |
| cp-0942 | gpu-6 | GPU-58272147-35f4-6125-0810-25497aee2a1a | Continuity on, worker 2 |
| cp-0942 | gpu-7 | GPU-e4f59982-2d2b-0692-84bd-ca6c7d709c1e | Continuity on, worker 2 |

Every UUID matches its node and index in [the November 4 allocation](../reports/overnight-2026-11-04/allocations.json).

</details>

## Tonight, once the VPN is back

Budget about 2 hours. Everything that is staged tonight stays running overnight.
All commands run on the jumpbox from the checkout. The VPN drops for minutes at a
time, and an ssh session dies with it, so run every long step inside tmux there,
one window per `prime`:

```bash
ssh ubuntu@3.238.63.5
tmux new -A -s staging
cd ~/dynamo-kubecon-workshop && source scripts/kubecon-jump-env.sh
```

1. **Read-only check (5 min).** Run `uv run python -m demos status` and
   `kubectl get resourceclaims -A -o wide`. Expect only the Nov 7–8 intro/MX
   pair: the shared lease, cp-0124 gpu-1/3 and cp-0198 gpu-0/2. If anything
   else holds GPUs, stop and find its owner.
2. **Deliver the code (15 min).** Use the staged, hash-checked delivery. Commit
   the laptop changes first, so the manifest names a commit. Then, on the laptop:
   ```bash
   python3 .local/deliveries/kit/stage.py scan > /tmp/scan.py
   ssh ubuntu@3.238.63.5 python3 - < /tmp/scan.py > /tmp/remote.json
   python3 .local/deliveries/kit/stage.py plan /tmp/remote.json workshop-day
   scp -r .local/deliveries/staging/<stamp>-workshop-day ubuntu@3.238.63.5:workshop-source-backups/
   ssh ubuntu@3.238.63.5 'cd workshop-source-backups/<stamp>-workshop-day && python3 apply.py && python3 apply.py --apply'
   ```
   `plan` lists every file it stages. It refuses to replace a jumpbox file
   that matches no committed or delivered version. `apply.py` backs up each
   replaced file and writes `delivery-manifest.json`; copy that back to
   `.local/deliveries/`. Then run the test suite on the jumpbox in an isolated
   copy (no `results`, `.local` or `.venv`; `HOME` and `KUBECONFIG` cleared).
3. **Clean up the leftover pair (5 min).** Run it with `WORKSHOP_ALLOCATION` and
   `WORKSHOP_LEASE` unset. Do the MX target first, because the intro refuses
   cleanup while its dependent is registered:
   ```bash
   uv run python -m demos modelexpress cleanup --run results/demo-02-20261108-capture-a1
   uv run python -m demos single-replica cleanup --run results/demo-01-20261107T062808330356Z
   ```
   `demos status` should then list no reservations.
4. **Qualify Shadow on Qwen3-0.6B and record it (about 20 min).** This is the
   first live run of the Qwen presenter, and the first Shadow run on cp-0942.
   Recording it gives Shadow its fallback.
   ```bash
   uv run python -m demos shadow prepare            # 2–4 min; note its results/demo-08-<ts> run
   uv run python -m demos shadow prime --run <run>  # 2–5 min; engine-0 active, engine-1 standby
   uv run python -m demos.common.capture --demo 08-shadow-engine --run <run> \
       --output demos/transcripts/live/08-shadow-engine/20261108-a1
   uv run python -m demos shadow cleanup --run <run>
   ```
   It passes when the run's `recovery-proof.json` reads `passed`, the fault to
   the first verified response takes about 3 s (the controls took 2.6–3.0 s),
   and `new_standby_confirmed` is true. Before the fault, the verifier sends the
   workshop coding request. If Qwen's answer fails that check, no fault has
   been injected. Set `QWEN_RECOVERY_REQUEST = 'ready'` in `demos/shadow/demo.py`
   on the laptop, redeliver that file, and repeat the capture on the same run
   with a new output directory. A failure after the fault needs `cleanup` and a
   fresh run. If promotion fails, Shadow is slides only: the October 22
   evidence is in the slide notes. If it passes, run a fresh `prepare` and
   `prime` (5–8 min) and leave that run up for tomorrow.
5. **Stage the long demos, run full passes of the EFA ones (about 60–75 min,
   mostly loading).**
   - Staged overnight: Snapshot and continuity, with Shadow from step 4. They
     take longest to prime (45 and 25 min), and none depends on an idle EFA path.
   - Full pass tonight, then cleanup: P/D and KVCR. Both move data over EFA,
     and an idle night before a transfer is untested; the longest proven KVCR
     gap is about 1.5 h. The pass is the first P/D run on its pins and the first
     KVCR speedup run with B on cp-0942. Both are primed fresh tomorrow.

   Start the primes in this order, each in its own tmux window, since `prime`
   blocks. All nine Super VL workers read about 700 GB from EFS between them,
   roughly 40 min at about 0.3 GB/s, so allow `--timeout 5400`.
   ```bash
   # Staged overnight. Snapshot first: its chain is longest (load, capture, stage, restore).
   WORKSHOP_LEASE=workshop-snapshot.gpu-lease uv run python -m demos snapshot-dgd prepare --auto
   uv run python -m demos snapshot-dgd prime --auto --timeout 5400

   WORKSHOP_LEASE=workshop-continuity.gpu-lease \
   WORKSHOP_PLACEMENT=$PWD/demos/allocations/workshop-request-continuity.json \
       uv run python -m demos request-continuity prepare --auto
   uv run python -m demos request-continuity prime --auto --timeout 5400

   # Full passes, then cleanup.
   WORKSHOP_LEASE=workshop-disagg.gpu-lease \
   WORKSHOP_PLACEMENT=$PWD/demos/allocations/workshop-disaggregated.json \
       uv run python -m demos disaggregated prepare --auto
   uv run python -m demos disaggregated prime --auto --timeout 5400
   uv run python -m demos disaggregated run --plain --auto
   uv run python -m demos disaggregated cleanup --auto

   uv run python -m demos kvcr prepare --auto
   uv run python -m demos kvcr prime --auto --timeout 5400
   uv run python -m demos kvcr run --plain --auto
   uv run python -m demos kvcr cleanup --auto

   # The intro takes no GPUs until it is applied on stage.
   WORKSHOP_ALLOCATION=$PWD/demos/allocations/workshop-intro-mx.json \
       uv run python -m demos single-replica prepare
   ```
6. **Check the staging (5 min).** `demos status` should show the
   `workshop-snapshot` and `workshop-continuity` leases plus Shadow's, and no P/D
   or KVCR reservation. `kubectl get resourceclaims -A -o wide` should show
   only the Snapshot, continuity and Shadow GPUs from the allocation table. The
   continuity `demo.json` and the P/D pass's should contain
   `placement_observed`.
7. **Optional, if there is VPN time (20 min): rehearse the live intro and MX.**
   Run them on their new GPUs with EFS quiet, then clean up (target first) and
   prepare a fresh intro run. This is the first transfer from cp-0124 gpu-0/2.
   It also times tomorrow's live load against the quiet-EFS baseline: 493 s to
   Ready on Nov 7, against 1,421 s alongside other loads on Nov 5.

## Tomorrow

T is the start of the Dynamo section. The talk before it runs from T−30 to T.

| When | Action | Why at this point |
| --- | --- | --- |
| T−150 | Morning check of the overnight runs. Run `demos status`, then re-run `prime --auto` on continuity, Shadow and Snapshot. On a primed run each re-verifies its running workers without using up the demo, and refuses a restarted Pod. | A 45-min Snapshot re-prime still fits. |
| T−135 | KVCR: `prepare --auto`, then `prime --auto`. It is ready only when `prime` exits 0 after "Warm-up: … Both engines are warm." `demos status` can read ready before the warm-up fails. | The warm-up is a real A→B fetch over EFA, about 3 h before the demo. |
| T−130 | P/D: `prepare --auto` with its two variables, then `prime --auto`. | Both EFA demos are done loading by about T−110. |
| T−110 to T−35 | Retry window. `cleanup`, then a fresh `prepare` (same variables) and `prime`: KVCR about 14 min, P/D 13, continuity 25, Shadow 5–8, Snapshot 45. | All re-primes finish before the hands-off point. |
| T−35 | Last gate, before opening any presenter. Re-run `kvcr prime --run <run>`: it prints "Already primed; original worker identities and startup clock retained." and exits 0. Re-run `disaggregated prime --auto`. Then `kubectl get pods -n <namespace>` for each staged demo: every container ready, RESTARTS 0. | KVCR's re-check doesn't cover A's engine; the Pod list does. |
| T−30 | Hands off: the earlier talk is on stage. No EFS-heavy work. | The live intro load needs EFS to itself. |
| 0:12 | Intro: `WORKSHOP_ALLOCATION=… uv run python -m demos single-replica`. Apply, then talk through the slides while it starts. | |
| ~0:21 | Intro: discovery and a request. Then, offstage: `WORKSHOP_ALLOCATION=… uv run python -m demos modelexpress prepare`. | |
| ~0:27 | ModelExpress: `WORKSHOP_ALLOCATION=… uv run python -m demos modelexpress`. Start replica 2; return after the results slide. | |
| ~0:46 on | `kvcr`, `disaggregated`, `request-continuity`, `shadow`, `snapshot-dgd` at the talk times in the first table. No variables needed: each run recorded its own. | |
| after 2:18 | Each presenter's `cleanup`: the MX target before the intro, both with `WORKSHOP_ALLOCATION`. | |

## If something doesn't work

- **The VPN comes back too late for step 5.** Stage tomorrow instead: preflight
  at T−150, then Snapshot at T−140, KVCR at T−135, P/D at T−130, continuity at
  T−125 and Shadow at T−120. Everything is primed around T−95, which leaves
  T−95 to T−35 for retries. Do steps 2–4 first.
- **A pinned worker never schedules** (its claim stays pending): one of its GPUs
  is taken or unhealthy. Find the holder with `kubectl get resourceclaims -A -o wide`.
  Don't move pins on the day: show that demo from its recording.
- **The delivery is refused.** A jumpbox file changed since the scan, or matches
  no known version. Inspect it; don't force it.
- **Shadow doesn't qualify.** It is slides only. cp-0942 gpu-1 stays free.
- **A live step fails on stage.** Switch to the recording and move on.

## Rules on the day

- Never re-prime or debug on stage: switch to the recording and move on.
- Keep the creating Snapshot DGD alive from its prime through its demo. The
  checkpoint belongs to that DGD.
- KVCR: gate on `prime`'s own result, never test the walkthrough after prime,
  and retry only with `cleanup` plus a fresh `prepare` and `prime`. The
  presenter refuses a restarted Pod.
- The cluster is reserved for the workshop from tonight's staging until cleanup.
  No measurement campaigns are planned (confirmed November 8).
