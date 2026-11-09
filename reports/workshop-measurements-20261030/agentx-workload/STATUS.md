# AgentX workload preparation

State: ready. CPU source/data/profile preparation is complete; no GPU operations
performed and no hardware benchmark outcome claimed.

- Verified AIPerf `--scenario inferencex-agentx-mvp` in local source at
  `e2c149ee29d3b64798d8ba2176e9f42e0aa89280` (package 0.13.0).
- Canonical corpus: `semianalysisai/cc-traces-weka-062126`, real Claude Code
  traces with subagent topology, currently documented as 393 eligible traces
  without a context filter.
- Concurrency counts live session trees. Parallel child conversations may
  produce more simultaneous HTTP requests than the configured tree count.
- The AIPerf checkout contains unrelated staged DAG changes. Benchmark source
  will be frozen from committed HEAD rather than using that dirty tree.
- Important server mismatch: the workshop manifest caps context at 8192 and
  concurrent sequences at four; AgentX expects native model context. No traces
  will be silently truncated to fit.
- Verified corpus revision `23f152f6f0f9399a85901b89a6458def0ef16729`, downloaded
  all 1,847,151,435 bytes, and matched the content SHA256 against repository LFS
  metadata. The CDN ETag is the Xet hash and was not used as the content hash.
- Scanned all 393 traces / 98,827 requests. Maximum recorded context is 996,579
  tokens. No whole trace fits 8k or 32k; all fit the native 1M context limit.
- Published C=1 and C=4 templates with 900s profiling, seed 20261030, 1800s request
  and warmup bounds, and a 300s drain. YAML and scenario resolution passed.
- Delivered source archive, revision-only patch, profile paths, install commands,
  context requirements, and cache-namespace semantics to both execution agents.
- Remaining execution gates: native-context serving fit, token-budget field
  compatibility, actual endpoint/artifact paths, GPU lease, and completed run
  validity. See README.md for exact boundaries and instructions.
- Added CPU resource assessment: the full loader is eager despite delta payloads;
  default preprocessing can spawn 16 workers. Recommend serial preparation and
  an initial 64 GiB request / 96 GiB limit qualification client. Serial mode
  bypasses the Weka POSIX shared-memory allocation, so its existing 64 MiB
  `/dev/shm` is sufficient for that specific path.
- Published `RESOURCE_REQUIREMENTS.md` and `prepare_agentx_cache.py`, a
  version-specific adapter exercising the actual DatasetManager cache pipeline
  without an inference worker. Tiny isolated wiring checks pass; the RR agent
  owns full-corpus RSS/disk qualification before reserving GPUs. No full-corpus
  memory peak or disk-size bound is claimed from source inspection.
- CPU qualification subsequently passed in the RR workstream: all 393 traces /
  98,827 turns retained, 6,037,582,817-byte mmap, 484.7s preparation, cgroup peak
  31,983,284,224 bytes, no OOM events. Receipts live under its
  `cpu-qualification-a3` directory; this is preparation, not an inference result.
- Completed a read-only branch-prefix follow-up. Named siblings can share a
  large exact initial prefix and overlap: the documented example has 72,320
  matching recorded token units, 247,751 equal reconstructed content bytes, and
  5.085s recorded request overlap. Named-child full-parent inheritance is not
  supported generally; see `BRANCH_PREFIX_FINDINGS.md` for distinctions and
  provenance. No workload changes or new downloads were needed.
