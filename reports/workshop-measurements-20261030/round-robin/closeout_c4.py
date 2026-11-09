#!/usr/bin/env python3
"""Recompute and seal the original C4 observation from verified local evidence."""
import collections
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import runpy
import tarfile

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/workshop-c4-closeout-20261104-a1'
RUN_REL = Path('results/workshop-rr-20261103-resume02')
RUN = OUT / 'verified' / RUN_REL
REPORT = Path(__file__).with_name('C4_CLOSEOUT.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def verify_raw_archive(folder):
    verified = []
    with tarfile.open(folder / 'raw-artifacts.tar.gz') as archive:
        names = set()
        for member in archive:
            name = Path(member.name)
            assert not name.is_absolute() and '..' not in name.parts
            assert member.name not in names
            names.add(member.name)
            assert member.isfile() or member.isdir(), 'Unsupported raw-archive member'
            if not member.isfile():
                continue
            target = folder / 'raw' / name
            assert target.is_file() and not target.is_symlink()
            content = archive.extractfile(member).read()
            assert len(content) == target.stat().st_size
            assert hashlib.sha256(content).hexdigest() == sha(target), str(target)
            verified.append(str(name))
    assert set(verified) == {str(p.relative_to(folder / 'raw')) for p in (folder / 'raw').rglob('*') if p.is_file()}
    return {'files_verified': len(verified), 'archive_sha256': sha(folder / 'raw-artifacts.tar.gz')}


def main():
    verification = json.loads((OUT / 'verification.json').read_text())
    manifest_path = OUT / 'verified/pullback-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert verification['mismatches'] == 0 and verification['files_verified'] == len(manifest['files'])
    assert sha(manifest_path) == verification['manifest_sha256']
    for name, record in manifest['files'].items():
        path = OUT / 'verified' / name
        assert path.stat().st_size == record['bytes'] and sha(path) == record['sha256'], name
    helper = OUT / 'verified/reports/workshop-measurements-20261030/round-robin/analyze.py'
    analyzer = runpy.run_path(str(helper))
    paths = [RUN / f'c4-r{n}-a1' for n in (1, 2)]
    assert analyzer['normalized_profile'](paths[0]) == analyzer['normalized_profile'](paths[1])
    rows = [analyzer['load_arm'](path) for path in paths]
    original = json.loads((RUN / 'scaleout-c4-a1-analysis.json').read_text())
    assert original['type'] == 'scaleout' and original['concurrency_session_trees'] == 4 and original['paired_repetitions'] == 1
    for key in ['model', 'model_revision', 'runtime_image', 'dataset_revision', 'dataset_sha256',
                'aiperf_commit', 'dataset_pin_patch_sha256', 'concurrency_session_trees',
                'native_max_model_len', 'max_num_seqs_per_worker', 'client_preprocessor_workers']:
        assert rows[0]['spec'][key] == rows[1]['spec'][key], key
    retained = {p['uid'] for p in rows[0]['spec']['worker_pods']}
    assert retained <= {p['uid'] for p in rows[1]['spec']['worker_pods']}
    archives = {}
    workload_rows = []
    telemetry_rows = []
    for index, (row, expected, folder) in enumerate(zip(rows, original['arms'], paths), 1):
        assert row['spec']['replicas'] == index and row['spec']['h100_gpus'] == index * 2
        assert row['spec']['router_mode'] == 'round-robin' and row['spec']['concurrency_session_trees'] == 4
        # Only the file location changes when the exact export is staged locally.
        same_location = dict(row, accepted_export=str(ROOT / RUN_REL / Path(row['accepted_export']).relative_to(RUN)))
        assert same_location == expected, 'Recomputed analysis differs: ' + row['arm']
        inventory = json.loads((folder / 'integrity-final.json').read_text())['sha256']
        assert 'raw-artifacts.tar.gz' in inventory
        for name, digest in inventory.items():
            assert sha(folder / name) == digest, name
        archives[row['arm']] = verify_raw_archive(folder)
        assert not row['request_error_count'] and not row['cancelled_profile_records']
        assert row['profile_seconds'] == 900 and row['grace_seconds'] == 300
        assert abs(row['canonical_throughput_denominator_seconds'] - 1200) < .01
        kinds = collections.Counter()
        for trace in row['source_trace_requests'].values():
            kinds.update(trace['source_kinds'])
        assert sum(kinds.values()) == row['requests']
        assert sum(v['requests'] for v in row['worker_generate_requests']) == row['requests']
        pods = json.loads((folder / 'pods.json').read_text())['items']
        worker_args = []
        for identity in row['spec']['worker_pods']:
            pod = next(p for p in pods if p['metadata']['uid'] == identity['uid'])
            statuses = pod['status']['containerStatuses']
            assert all(c['restartCount'] == 0 for c in statuses)
            assert all(c['imageID'].endswith(row['spec']['runtime_image'].split('@')[1]) for c in statuses)
            args = pod['spec']['containers'][0]['args']
            assert '--max-model-len' not in args and '--language-model-only' not in args
            assert args[args.index('--tensor-parallel-size') + 1] == '2'
            worker_args.append(args)
        assert all(args == worker_args[0] for args in worker_args)
        row['closeout_source_kind_counts'] = dict(kinds)
        row['closeout_earlier_multimodal_capable_serving_profile'] = True
        workload_rows.append({'arm': row['arm'], 'requests': row['requests'],
            'main_requests': kinds['weka_main'], 'subagent_requests': kinds['weka_subagent'],
            'flat_requests': kinds['weka_flat'], 'sampled_source_traces': len(row['source_trace_requests']),
            'children_spawned': row['branch_stats']['children_spawned'],
            'children_completed': row['branch_stats']['children_completed'],
            'children_truncated': row['branch_stats']['children_truncated'],
            'graphs_completed_to_end': row['branch_stats']['graphs_completed_to_end'],
            'worker_request_counts': ' / '.join(str(int(v['requests'])) for v in row['worker_generate_requests'])})
        assert len(row['gpu_utilization_during_900s_admission_window']) == index * 2
        for uuid, telemetry in row['gpu_utilization_during_900s_admission_window'].items():
            assert telemetry['samples'] == 180
            telemetry_rows.append({'arm': row['arm'], 'gpu_uuid': uuid, **telemetry})
    first, second = rows
    ratios = {k: second[k] / first[k] for k in original['second_over_first']}
    assert ratios == original['second_over_first']
    assert original['canonical_throughput_denominators_differ'] is False
    derived = OUT / 'analysis'
    derived.mkdir(exist_ok=False)
    summary = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'type': 'scaleout',
        'concurrency_session_trees': 4, 'paired_repetitions': 1, 'arms': rows,
        'second_over_first': ratios, 'exact_remote_analysis_match_excluding_export_location': True,
        'raw_archives': archives, 'source_kind_counts': workload_rows,
        'gpu_admission_samples': telemetry_rows, 'original_worker_retained': sorted(retained),
        'scope': 'Closeout of original C4 fixed-load observation, not a benchmark rerun or a routing-policy comparison'}
    write(derived / 'recomputed-analysis.json', summary)
    for name, records in [('workload-mix.csv', workload_rows), ('gpu-samples-summary.csv', telemetry_rows)]:
        with (derived / name).open('x') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    report = f'''# C4 scale-out closeout

**Complete, November 4, 2026.** The original one-worker/two-worker C4 evidence
is collected and rechecked locally. No benchmark was rerun. The recomputed
analysis exactly matches the accepted remote analysis, apart from the export's
new local file location. Both raw archives and all their extracted files match.

| Observation | One TP2 worker / 2 H100s | Two TP2 workers / 4 H100s |
| --- | ---: | ---: |
| Successful measured requests | {first['requests']:,} | {second['requests']:,} |
| Output tokens | {first['output_tokens']:,} | {second['output_tokens']:,} |
| Canonical aggregate output tokens/s | {first['output_tokens_per_second']:.2f} | {second['output_tokens_per_second']:.2f} |
| Mean active-generation tokens/s/user | {first['decode_tokens_per_second_per_user_mean']:.2f} | {second['decode_tokens_per_second_per_user_mean']:.2f} |
| TTFT p50 | {first['ttft_p50_ms']:.2f} ms | {second['ttft_p50_ms']:.2f} ms |
| TTFT p99 | {first['ttft_p99_ms']:.2f} ms | {second['ttft_p99_ms']:.2f} ms |
| Server-reported cache-read share | {first['server_reported_cache_read_pct']:.2f}% | {second['server_reported_cache_read_pct']:.2f}% |
| Canonical throughput denominator | 1,200 s | 1,200 s |
| Profiling main / subagent / flat requests | 61 / 60 / 1 | 56 / 57 / 1 |
| Source trace IDs sampled | 5 | 4 |
| Dynamo worker request counts | 122 | 57 / 57 |
| GPU utilization during 900 s admission | 65.42–65.46% | 35.47–37.22% |
| Samples per GPU during admission | 180 | 180 |
| Children spawned / completed / truncated | 6 / 2 / 1 | 3 / 2 / 0 |
| Agent graphs completed to end | 0 | 0 |

Adding the replica increased mean active-generation speed **8.4%**, while the
canonical aggregate output rate fell **7.2%**, TTFT increased and cache-read
share fell **5.08 percentage points**. The same configured load produced a
different realized turn mix. This is an operational illustration of why replica
count alone does not determine user experience; it does not isolate cache
locality's causal effect, establish maximum capacity or measure RR/KV benefit.

## Acceptance and provenance

- **142 files** transferred and verified, **zero mismatches**. The final arm
  inventories contain **33 and 35 files**; every named file, including each
  original `raw-artifacts.tar.gz`, is present. Original intermediate inventories
  and the first-arm recovery / successful second-arm stage inventories also pass.
- Both embedded raw archives contain **14 regular files**, each byte-identical
  to its collected extracted counterpart. Nothing was selectively omitted.
- Both AIPerf exports report complete, uncancelled, valid submissions, positive
  request counts and no request errors, context overflows or cancelled profiling
  records. Both arms passed the unchanged original analyzer's acceptance checks.
- Normalized workload profiles match. Model/revision/image, corpus revision/hash,
  AIPerf commit/patch, native 1,048,576 context, four sequences per worker,
  preprocessing and C4 session-tree semantics match the frozen specifications.
  Worker UIDs, image digests and zero restarts match captured Pod evidence.
- Original worker `66649d97-fd14-4054-be3f-7aa55d7f2215` survived scale-out.
  New worker `9ca3405c-f058-49d7-8372-9008aba80745` served half of the measured
  two-worker requests. Exact worker IDs/endpoints, trace IDs/offsets, branch
  counters and per-GPU statistics are retained in the recomputed analysis.
- C4's stage exited **zero** and verified zero owned GPU Pods, ResourceClaims,
  DGDs and no stage GPU lease. The closeout's fresh read-only namespace audit
  also found no GPU resources. The expired, failed non-GPU client Pod is retained.
- The enclosing controller and later continuation exited **one** at the C1 KV
  guard. Those failure receipts are preserved. C4 success does not relabel that
  queue or either routing-policy pair as successful.

## Interpretation limits

This is one fixed-order pair: 900 s request admission plus a 300 s grace bound.
The first profile continued cluster-side through a laptop tunnel outage; it was
recovered unchanged, not replayed. The second arm followed a network-recovery /
initialization pause and a change to the stable controller. The original worker
and cluster-side client were retained. Initial worker cache occupancy can differ.

The full pinned corpus was available; only the source requests counted above
were measured. C4 denotes configured live session-tree concurrency, not four
HTTP requests at every instant. Branch counters and completed replay sessions
do not prove completed coding tasks. No complete agent graph finished here.

The serving profile predates the newer `--language-model-only` startup baseline.
It serves text requests but retains multimodal capability; do not relabel this
closeout as a new text-only benchmark or combine it with the MX startup matrix
as one matched experiment. GPU samples cover admission rather than the entire
grace period. Canonical throughput and derived request-span throughput remain
separately named metrics; per-user active-generation speed excludes TTFT.

## Artifacts

- Complete verified tree: `results/workshop-c4-closeout-20261104-a1/verified/`.
- Transfer and nested-inventory receipt: `results/workshop-c4-closeout-20261104-a1/verification.json`.
- Recomputed analysis and workload/GPU CSVs: `results/workshop-c4-closeout-20261104-a1/analysis/`.
- Exact original analysis: `verified/results/workshop-rr-20261103-resume02/scaleout-c4-a1-analysis.json` under the closeout.
- Pullback archive SHA256: `{verification['archive_sha256']}`.
- [Collection plan](C4_CLOSEOUT_PLAN.md), [main measurement report](REPORT.md),
  [separate routing failure diagnosis](KV_DISCOVERY_DIAGNOSIS_20261104.md).

Older partial local mirrors and all original inventories remain unchanged.
The new verified tree is the authoritative complete local C4 copy. This task
performed remote reads and local analysis only; it changed no leases or cluster
resources and did not schedule the still-outstanding routing comparison.
'''
    assert not REPORT.exists()
    REPORT.write_text(report)
    write(derived / 'analysis-sha256.json', {str(p.relative_to(ROOT)): sha(p) for p in
        [derived / 'recomputed-analysis.json', derived / 'workload-mix.csv',
         derived / 'gpu-samples-summary.csv', REPORT, Path(__file__)]})
    write(OUT / 'closeout.json', {'status': 'complete', 'at': summary['at'],
        'files_verified': verification['files_verified'], 'mismatches': 0,
        'exact_remote_analysis_match_excluding_export_location': True,
        'original_worker_retained': sorted(retained), 'new_benchmark_execution': False,
        'cluster_or_lease_mutations': False, 'c4_stage_exit_code': 0,
        'enclosing_controller_exit_code': 1, 'report': str(REPORT.relative_to(ROOT)),
        'verification_sha256': sha(OUT / 'verification.json'),
        'analysis_seal_sha256': sha(derived / 'analysis-sha256.json')})
    print(json.dumps({'status': 'complete', 'files_verified': verification['files_verified'],
        'raw_archives': archives, 'exact_analysis_match': True, 'workload_mix': workload_rows,
        'report': str(REPORT)}, indent=2))


if __name__ == '__main__':
    main()
