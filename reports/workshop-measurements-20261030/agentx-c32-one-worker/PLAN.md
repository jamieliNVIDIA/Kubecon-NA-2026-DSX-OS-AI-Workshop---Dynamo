# AgentX C32 one-worker cell

The [accepted C32 pair](../../overnight-2026-11-04/routing-c32/C32-RESULTS.md)
compares two round-robin workers with two KV-routed workers on the full AgentX
corpus at C32. Its one-worker arm never produced a score: during the mandatory
primer, queued health canaries exceeded their 180 s deadline and liveness
restarted the worker. This campaign runs that one arm once more, with health
canaries off, so the C32 comparison has a one-worker baseline.

## What changes

- **Health canaries off** in this cell only (`DYN_HEALTH_CHECK_ENABLED=false`;
  the 1 s canary wait and 180 s canary timeout removed). The user decided on
  November 7 that the canary wait was a startup optimization, not a load-test
  setting. The accepted two-worker cells ran with the canaries.
- **Placement:** cp-0942 GPU0/2, the second worker's pair in both accepted
  two-worker cells. The original one-worker pair, cp-0198 GPU0/2, is held by
  the presenter MX target.
- `freeze()` diffs this manifest against the frozen C32 one-worker manifest and
  fails on anything beyond node, GPU selector and health environment.

Unchanged: model and revision, runtime image, TP2, native 1,048,576 context,
`max-num-seqs` 128, 8,192 batched tokens, memory fraction 0.85, text-only
compiled serving, the byte-identical C32 profile (full 393-trace corpus, seed,
pacing, primer, 900 s admission, 300 s drain), the C32 readiness gate, smoke
requests and acceptance rules. Four harness files changed after November 5;
`campaign.json` lists them. None touches worker arguments, the profile, the
primer or acceptance.

## Run

A fresh namespace, `dynamo-ft-agentx-c32-one-worker-20261108-a1`, a fresh CPU
client and a scoped lease on cp-0942 GPU0/2. The detached controller runs
prepare (about 1 min), CPU qualification (about 11 min), the cell (about
40 min) and finalize, then deletes the worker, claims and client.

```bash
.local/venv/bin/python -B reports/workshop-measurements-20261030/agentx-c32-one-worker/controller.py build
.local/venv/bin/python -B reports/workshop-measurements-20261030/agentx-c32-one-worker/controller.py launch
.local/venv/bin/python -B reports/workshop-measurements-20261030/agentx-c32-one-worker/controller.py probe --label LABEL
.local/venv/bin/python -B reports/workshop-measurements-20261030/agentx-c32-one-worker/controller.py collect --label LABEL
```

## Comparison limits

N=1, run three days after the two-worker pair, on a different node from the
original one-worker attempt, and without the canaries the pair ran with. The
three cells are separate observations of one profile, not a controlled capacity
curve. An overloaded cell with errors or cancellations is kept as a stress
observation, as in C32.
