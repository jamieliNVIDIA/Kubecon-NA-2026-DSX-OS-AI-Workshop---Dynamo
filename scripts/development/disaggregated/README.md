# Disaggregation development campaigns

These standalone tools were used to measure and investigate matched aggregate
and prefill/decode deployments. The workshop walkthrough is the
[disaggregated presenter](../../../demos/disaggregated/README.md).

| Module | Role |
| --- | --- |
| [benchmark.py](benchmark.py) | Freeze, prepare, execute, verify and clean up the matched campaign |
| [controller.py](controller.py) | Drive an already frozen comparison within an explicit execution window |
| [handoff.py](handoff.py) | Bind a fresh campaign to an explicitly handed-off, qualified CPU client |
| [probe_client.py](probe_client.py), [recheck_client.py](recheck_client.py) | Inspect or recheck the retained CPU client and cache before execution |
| [inspect_client.py](inspect_client.py), [inspect_sources.py](inspect_sources.py) | Collect client/runtime diagnostics |
| [recover_client.py](recover_client.py), [recover_profile.py](recover_profile.py) | Inspect or collect existing detached work after an observer outage |
| [analyze.py](analyze.py), [verify.py](verify.py) | Analyze retained outputs and verify comparison evidence |

Inspect the campaign interface from the repository root:

```bash
uv run python -m scripts.development.disaggregated.benchmark --help
```

These campaigns preserve model/runtime identity, workload and phase settings,
GPU placement, lease ownership and per-attempt receipts. A failed or expired
attempt remains evidence; changes require a fresh immutable campaign. Recovery
collects the original work rather than silently rerunning it. Client handoff
must identify the existing owner and exact qualified client, and cleanup must
preserve borrowed resources.
