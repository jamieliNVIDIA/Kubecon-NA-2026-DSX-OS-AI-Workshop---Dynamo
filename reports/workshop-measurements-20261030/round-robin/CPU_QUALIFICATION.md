# Full AgentX CPU qualification

Completed at 00:45:38 UTC on October 31, 2026. This exercised the real pinned
dataset reconstruction and mmap pipeline without inference requests or a GPU
lease. It is preparation evidence, not an inference performance result.

| Observation | Measured value |
| --- | --- |
| Full reconstruction and cache population | 484.70 s |
| Process peak RSS | 25,790,255,104 bytes |
| Container peak memory, including page cache | 31,983,284,224 bytes |
| OOM / OOM-kill events | 0 / 0 |
| Source trajectories / root conversations | 393 / 393 |
| Reconstructed child conversations | 9,450 |
| Retained request turns | 98,827 |
| Dataset mmap | 6,037,582,817 bytes |
| Index mmap | 1,658,146 bytes |

The canonical source corpus and dataset-revision patch were retained unchanged.
No source trajectory, request, input context, or output length was truncated.
Both C1 and C4 profiles resolve to the verified reusable content-cache key
`42d97db1b0977336274f9bb686585572`. Normal benchmark-specific prefix namespaces
remain fresh for every measured invocation; the shared CPU mmap is a template.

The dedicated client uses four requested/eight maximum CPUs, 64Gi requested/96Gi
maximum RAM, and serial Weka reconstruction
(`AIPERF_DATASET_WEKA_PARALLEL_WORKERS=1`). Its full-corpus peak does not establish
the additional memory required while serving concurrent live HTTP contexts.

Evidence is under
`results/workshop-rr-20261030-prep-1705/cpu-qualification-a3/`: source/profile hashes,
`receipt-c1.json`, `receipt-c4.json`, `memory-history.json`, logs, and cache hashes.
The C4 check independently verified a cache hit without reconstruction. The
original corpus SHA256 is
`29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`.

An earlier CPU orchestration attempt stopped while parsing a Transformers prompt
printed before otherwise valid result JSON. Its logs are preserved in
`cpu-qualification-a2/`; the fresh a3 attempt used an explicit result sentinel.
No dataset reconstruction or inference measurement ran in that failed attempt.

Separate native-context startup evidence is available from the MX workstream's
`results/workshop-mx-startup-20261030-artifact02/central-source-bootstrap/result.json`:
the same model/image/TP2 configuration exposed context window 1,048,576 and
returned `READY` on a short correctness request. Long AgentX request execution
remains a separate runtime qualification gate.
