# CPU preparation and cache qualification

**Measured qualification update:** the RR agent completed the unchanged full
corpus on the serial 64/96 GiB client. Its preparation receipt records a
6,037,582,817-byte mmap, 484.7 seconds elapsed, 25,790,255,104-byte process peak
RSS, and 31,983,284,224-byte cgroup peak with no OOM events. The receipt is
`results/workshop-rr-20261030-prep-1705/cpu-qualification-a3/receipt-c1.json`.
The same C=4 configuration reuses its cache key. These measurements supersede
the earlier “full-corpus peak still unknown” qualification gate below; they do
not establish live benchmark memory use or justify reducing the client limit.

The source-inspection notes below use the same frozen AIPerf and complete corpus
as the workload README. They document the capacity guidance that preceded the
measured qualification above. Preparation finished before holding the GPU lease.

The current 16 GiB request / 32 GiB limit is **unqualified for eager preparation**.
It may succeed in serial mode, but the raw 1.85 GB file size is not a reliable
memory estimate. Use 64 GiB requested / 96 GiB limited RAM as the initial CPU
qualification candidate, and retain that same CPU configuration across the
comparison arms. Record actual peak before claiming a smaller limit is safe.

## What the source actually retains

- `SemiAnalysisCCTracesWekaLoader._load_all_traces` validates and retains all
  393 trace objects before selection; the HF Arrow dataset is also resident or
  mapped during loading. This path is not a streaming trajectory iterator.
- The corpus contains 338,052,834 hash-ID occurrences, but 5,717,185 distinct
  hash IDs when uniqueness is measured within each trace's namespace. All
  blocks have 64 tokens: 365,899,840 distinct block tokens. The largest single
  trace has 15,014,720 distinct block tokens. Per-trace details are in
  [corpus-hash-footprint.json](corpus-hash-footprint.json).
- On ordinary 64-bit CPython, 338,052,834 separately allocated small integers
  plus their list pointers would occupy about 11.33 GiB before container/list,
  Pydantic, plan, string, tokenizer, allocator, and Arrow overhead. This is an
  illustrative estimate, not a lower bound: small-integer reuse can reduce it.
  The same number of int64 values is another 2.52 GiB in Arrow storage.
- Both reconstruction paths collect complete output conversation lists before
  DatasetManager writes the mmap. Serial clears token caches between trace
  scopes. Parallel additionally retains task payloads and all worker results
  before constructing the final conversations.
- The 21.6 billion cumulative recorded input tokens do **not** become 21.6
  billion independently decoded tokens in ordinary heap storage. Turns store
  delta messages; the runtime builds a current conversation when needed.
  However, `ConversationReconstructor.turn_delta` re-emits full current context
  on prefix cuts and equal-context retries. Distinct-block totals therefore do
  not bound serialized mmap size, and JSON serialization can duplicate strings
  that shared references in Python.

## Bound the preprocessing parallelism and shared memory

Set this before launching either preparation or AIPerf:

```bash
export AIPERF_DATASET_WEKA_PARALLEL_WORKERS=1
```

The default is auto, up to `min(os.cpu_count()-1,16,num_traces)`. Host CPU count
can exceed a Pod's request. Serial mode avoids multiplying reconstruction
working sets; it changes preprocessing execution only, preserving the source's
serial/parallel replay contract.

Parallel Weka reconstruction creates one POSIX shared-memory array of exactly
`4 * len(coding_tool_pool)` bytes. It does not put the complete trace corpus in
`/dev/shm`. The coding generator's nominal 10-million-token pool setting is not
an exact token count, and its old 500K-token docstring is misleading. A 64 MiB
shared-memory filesystem supports at most 16,777,216 int32 corpus tokens.

**With serial mode, this Weka shared-memory allocation is bypassed, so the
existing 64 MiB `/dev/shm` is not a blocker for this preparation path.** If later
using more than one preprocessing worker, first record the actual tool-pool
length and mount at least that many bytes plus headroom; 1 GiB is a conservative
candidate, not a demonstrated requirement. A memory-backed volume counts
toward the Pod's memory limit. Do not change parallelism between measured arms.

## Disk and page-cache budget

Use owned **disk-backed** local storage for `HF_HOME`, `HF_DATASETS_CACHE`,
`AIPERF_DATASET_MMAP_BASE_PATH`, and `AIPERF_DATASET_MMAP_CACHE_DIR`. Do not back the
large mmap directory with an unlimited tmpfs. Preprocessing may retain the raw
download and an Arrow conversion, plus a run mmap and a separate persistent
mmap-cache copy. Cache population uses `shutil.copyfile`, and no cache eviction
exists. On cache hits, restoring an entry also makes a run copy.

The RR client has about 99 GiB free and plans 40 GiB requested / 80 GiB limited
ephemeral storage. That is a reasonable **initial qualification allocation**,
not a proven sufficient bound; 40 GiB is a minimum free-space check only. The
first complete preparation must record actual mmap/cache/Arrow sizes and
available disk. Stop on resource exhaustion, preserve the failed preparation,
and resize CPU/disk resources before sealing performance specs; do not truncate
the corpus. Allow room for **two mmap copies** while a run is active.

`AIPERF_DATASET_MMAP_PREFAULT` defaults true. Each mmap client walks all pages at
open. Clients share the kernel file-page cache, but those pages still count
toward the cgroup's memory pressure. DatasetManager initially opens/prefaults the
mmap before releasing its reconstructed conversation list, which contributes
to preparation peak. Keep prefault enabled consistently and qualify this path.

## Exercise the real pipeline before reserving GPUs

There is no dedicated public cache-preparation CLI in this source snapshot.
[prepare_agentx_cache.py](prepare_agentx_cache.py) is a deliberately
version-specific adapter around the pinned DatasetManager configure method. It
loads the exact execution YAML, applies the same dataset/scenario/timing
resolvers and root seed, and runs tokenizer loading, corpus validation,
reconstruction, mmap creation, client prefault, and cache population. It never
starts a DatasetManager service, consumes its notifications locally, and
constructs no controller, timing manager, inference transport, or workers. The
public dataset may download from Hugging Face; no inference request is emitted.

Use the same isolated AIPerf environment and owned cache paths that the profile
processes will use. The local/subprocess service-run mode is correct even when
this command itself runs inside a Kubernetes CPU Pod; do not select AIPerf's
Kubernetes service-run plugin.

```bash
export AIPERF_DATASET_WEKA_PARALLEL_WORKERS=1
export AIPERF_DATASET_MMAP_PREFAULT=true
export AIPERF_DATASET_MMAP_CACHE_ENABLED=true
# Set the following to owned disk-backed paths before invoking the helper:
# HF_HOME, HF_DATASETS_CACHE, AIPERF_DATASET_MMAP_BASE_PATH,
# AIPERF_DATASET_MMAP_CACHE_DIR.
"$AGENTX_SOURCE/.venv/bin/python" "$AGENTX_HELPER" \
  --config "$AGENTX_PROFILE" --receipt "$AGENTX_PREP_RECEIPT"
```

After successful full preparation, invoke it again with a **new receipt** and
`--check-cache-only`. A cache hit is required. This verifies the actual profile's
cache key without loading/reconstructing the full corpus. If a later arm's key
differs, qualify its preparation before acquiring GPUs as well.

The receipts retain configuration/helper/source hashes, cache manifest and file
hashes, elapsed time, process peak RSS, and cgroup memory counters when present.
The helper removes only its disposable run mmap copy after hashing the cache;
the reusable cache persists. It also works with a preexisting cache hit.
Use an external sampler or cgroup counters to retain peak across the whole Pod;
`ru_maxrss` covers the helper process, not every unrelated process in its Pod.

The helper's no-service plumbing was verified locally with a tiny isolated
mock-loader dataset. That check proves cache creation/restore/cleanup wiring;
it does **not** prove the complete corpus fits the candidate Pod. The RR agent
owns that qualification and must retain all 393 traces and actual output lengths.

Source references within the pinned archive: `dataset_manager.py`,
`loader/semianalysis_cc_traces_weka.py`, `loader/weka_trace.py`,
`loader/weka_parallel_convert.py`, `loader/weka_synth_buf.py`,
`generator/coding_content.py`, `memory_map_utils.py`, `mmap_cache.py`, and
`common/environment.py`.
