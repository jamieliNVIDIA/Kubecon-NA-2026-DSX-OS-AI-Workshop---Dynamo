# Synthetic scale-out and routing status

**Complete.** a3 finished on November 8, 2026 at 08:02 UTC (00:02 Pacific):
controller exit 0, stage "Completed, accepted and cleaned". Results are in
[RESULTS.md](RESULTS.md). The campaign used a scoped reservation on cp-0942
GPU0/2/4/6 only; the presenter demos in `dynamo-ft-r610-f2bd6ac3-demo` and the
global lease were untouched. A separate KVCR requalification used cp-0198/cp-0124
gpu-4/5; the two sessions coordinated, and neither touched the other's GPUs.

## Attempts

| Attempt | Window (UTC) | Outcome |
| --- | --- | --- |
| a1 | 02:35–03:13 | Pilot. Stopped on purpose after 1W-64: variable session lengths left 4 of 32 users idle through the pinned user-centric scheduler. Cleanup verified; evidence in `results/workshop-synthetic-scaleout-a1-pilot-collection-20261108`. |
| a2 | 03:20–04:55 | 1W-32, 1W-64 and 1W-128 completed cleanly. Worker 2 then stayed Unschedulable for 2700 s: the template's `podAntiAffinity` (`feature-test-role=agg`, hostname) keeps two workers off one node. Cleanup verified; evidence in `results/workshop-synthetic-scaleout-collection-a2-final`. |
| a3 | 06:22–08:02 | Same as a2 without the anti-affinity rule, with byte-identical profiles and seeds. Reran 1W-64 as a bridge to a2's phase A (window 953 vs 948 tok/s; 22.5 vs 22.7 TPS/user), then scaled to two workers for 2KV-64, 2RR-64, 2RR-128, 2KV-128 and 2KV-32, all clean. Worker 2 was Ready 8 min 27 s after the scale-up was applied. Cleanup receipt at 07:58: no worker Pods, ResourceClaims or graphs; namespace confirmed empty at 08:09. Evidence in `results/workshop-synthetic-scaleout-collection-a3-final`. |

Concurrent work on other nodes: the KVCR requalification loaded models on
cp-0198/cp-0124 gpu-4/5 at 06:55–07:08 and 07:17–07:29 UTC. That overlaps
2KV-64 fully and 2RR-64/2RR-128 partly. a3's cells run entirely inside cp-0942
(client, frontends, workers) and read no EFS while profiling, so no effect is
expected; it is recorded here because the 64-agent KV/RR comparison spans it.

The cell results, the routing analysis and its caveats are in
[RESULTS.md](RESULTS.md). In short: below one worker's limit a second worker
raised TPS/user, not throughput; at 128 agents it raised throughput 1.70× with
KV routing and 1.26× with round-robin. Round-robin at 64 agents was accidental
session affinity from the periodic synthetic schedule, so it is not a
round-robin result.

## Decisions, November 7

- Synthetic AIPerf user-centric load replaces the AgentX C32 rerun for the
  scale-out question. Results are labeled synthetic, never AgentX.
- Health canaries are off in every cell. The 1 s canary wait was a startup
  optimization and does not belong in a load test.
- Fixed 12-turn sessions and a fixed doubling matrix: one worker at 32/64/128,
  two KV workers at 32/64/128, round-robin at 64/128.

## Observe, collect and analyze

Each cell's AIPerf `inputs.json` (the generated dataset, about 2.7 GB) and its
`raw-artifacts.tar.gz` stay on the jumphost; [`collect.py`](collect.py) records
their sizes and SHA-256 in `excluded-files.txt` and pulls everything else.

```bash
.local/venv/bin/python -B reports/workshop-measurements-20261030/synthetic-scaleout/controller.py probe --label LABEL
.local/venv/bin/python -B reports/workshop-measurements-20261030/synthetic-scaleout/collect.py --attempt a3 --label LABEL
.local/venv/bin/python -B reports/workshop-measurements-20261030/synthetic-scaleout/analyze.py \
  --run results/workshop-synthetic-scaleout-collection-a2-final/verified/results/workshop-synthetic-scaleout-20261107-a2 \
  --run results/workshop-synthetic-scaleout-collection-a3-LABEL/verified/results/workshop-synthetic-scaleout-20261107-a3 \
  --output results/workshop-synthetic-scaleout-collection-a3-LABEL/analysis.json
```

A later `--run` replaces an earlier run's cell of the same name, so a3's 1W-64
bridge stands in for a2's; the replaced cell stays in `replaced_cells`. The
a1, a2 and a3 local reservation markers are released, a3's after its collection
showed the exit, cleanup and qualification receipts.
