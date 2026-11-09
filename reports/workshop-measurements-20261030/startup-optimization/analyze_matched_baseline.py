"""Summarize the qualified, hash-verified matched MX loading-path experiment."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
PULLBACK = ROOT / 'results/workshop-baseline-pullback-20261104-a3'
RUN = PULLBACK / 'verified/results/workshop-mx-startup-20261104-baseline03'
OUT = ROOT / 'results/workshop-baseline-analysis-20261104-a3'
REPORT = Path(__file__).with_name('MATCHED_BASELINE_RESULTS.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    return dt.datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', value.replace('Z', '+00:00')))


def main():
    verification = json.loads((PULLBACK / 'verification.json').read_text())
    assert verification['mismatches'] == 0 and verification['controller_state']['ExitCode'] == 0
    assert verification['gpu_lease_absent'] and all(v == 0 for v in verification['final_resource_counts'].values())
    assert json.loads((RUN / 'qualification.json').read_text())['passed']
    for name, expected in json.loads((RUN / 'evidence-sha256.json').read_text()).items():
        assert sha(RUN / name) == expected, 'Collected evidence changed: ' + name
    assert not OUT.exists() and not REPORT.exists(), 'Preserve the previous derived result'
    comparison = json.loads((RUN / 'comparison.json').read_text())
    analysis = json.loads((RUN / 'startup-analysis.json').read_text())
    spec = json.loads((RUN / 'spec.json').read_text())
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in [PULLBACK / 'verification.json',
        RUN / 'comparison.json', RUN / 'startup-analysis.json', RUN / 'spec.json',
        RUN / 'qualification.json', RUN / 'cleanup-proof.json', RUN / 'evidence-sha256.json']}
    rows = []
    identities = []
    for arm in ['storage', 'weights', 'artifacts']:
        result = comparison[arm]
        record = next(r for r in analysis['records'] if r['arm'] == arm)
        folder = RUN / arm
        log = folder / (result['target_pod'] + '-main.log')
        text = log.read_text()
        proof = json.loads((folder / 'identity-health-proof.json').read_text())
        assert proof['passed'] and proof['text_only'] and proof['canary_wait_seconds'] == 1
        assert record['restarts'] == 0
        assert result['apply_to_ready_observed_seconds'] == record['apply_to_ready_observed_seconds']
        gpus = sorted(line.split(',')[1].strip() for line in (folder / 'gpu-visible.csv').read_text().strip().splitlines())
        identities.append(gpus)
        engine_end = next(s for s in text.splitlines() if 'init engine (' in s)
        tail = (stamp(record['pods_ready_observed_at']) - stamp(engine_end.split()[0])).total_seconds()
        row = {'arm': arm, 'ready_seconds': record['apply_to_ready_observed_seconds'],
            'first_checked_response_seconds': record['apply_to_first_correctness_response_seconds'],
            'model_load_seconds': record['model_load_seconds_max'],
            'engine_init_seconds': record['engine_init_seconds_max'],
            'torch_compile_seconds': record['torch_compile_seconds_max'],
            'backbone_profile_warmup_seconds': record['initial_profile_warmup_seconds_max'],
            'peer_copy_seconds': record['peer_transfer_seconds_max'],
            'engine_end_to_observed_ready_seconds': tail, 'pod_uid': record['pod_uid']}
        rows.append(row)
        selected = [log, folder / 'result.json', folder / 'identity-health-proof.json', folder / 'gpu-visible.csv']
        if arm == 'artifacts':
            cache = json.loads((folder / 'artifact-reuse-evidence.json').read_text())
            assert cache['actual_engine_cache_hit_ranks'] == ['0', '1'] and not cache['failure_lines']
            selected.append(folder / 'artifact-reuse-evidence.json')
        else:
            assert 'vLLM artifact install complete:' not in text and 'which ModelExpress installed' not in text
        for path in selected:
            inputs[str(path.relative_to(ROOT))] = sha(path)
    assert identities[0] == identities[1] == identities[2]
    assert len({row['pod_uid'] for row in rows}) == 3
    a, b, c = rows
    summary = {'rows': rows,
        'weight_ready_speedup': a['ready_seconds'] / b['ready_seconds'],
        'artifact_ready_speedup_vs_storage': a['ready_seconds'] / c['ready_seconds'],
        'artifact_ready_speedup_vs_weights': b['ready_seconds'] / c['ready_seconds'],
        'ready_reduction_seconds_mx_full': a['ready_seconds'] - c['ready_seconds'],
        'ready_fraction_reduction_mx_full': 1 - c['ready_seconds'] / a['ready_seconds'],
        'same_receiver_gpu_uuids': identities[0], 'retained_source_uid': comparison['source']['pod_uid'],
        'source_bootstrap_ready_seconds': comparison['source']['apply_to_ready_observed_seconds'],
        'spec_sha256': sha(RUN / 'spec.json'), 'input_sha256': inputs,
        'scope': comparison['scope'] + '; phase timers overlap and must not be added'}
    OUT.mkdir()
    (OUT / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (OUT / 'comparison.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def secs(value):
        return '—' if value is None else f'{value:.2f} s'

    table = '\n'.join('| ' + label + ' | ' + ' | '.join(secs(row[key]) for row in rows) + ' |'
        for label, key in [
            ('Deployment → observed Ready', 'ready_seconds'),
            ('Deployment → first checked correct response', 'first_checked_response_seconds'),
            ('Model loading, slower rank', 'model_load_seconds'),
            ('Engine initialization', 'engine_init_seconds'),
            ('torch.compile, nested in engine initialization', 'torch_compile_seconds'),
            ('Backbone profiling/warmup, nested in engine initialization', 'backbone_profile_warmup_seconds'),
            ('Peer copy, slower rank, nested in model loading', 'peer_copy_seconds'),
            ('Engine end → observed Ready', 'engine_end_to_observed_ready_seconds')])
    REPORT.write_text(f'''# Matched startup comparison on the updated baseline

Measured November 4, 2026. The storage and MX arms all use text-only Super VL
and the qualified faster worker-health policy. This is the compiled benchmark
profile; the eager presenter demonstrations have a separate profile.

| Measurement | MX off: EFS storage | MX peer weights | MX peer weights + artifacts |
| --- | ---: | ---: | ---: |
{table}

MX peer weights reached observed Ready **{summary['weight_ready_speedup']:.2f}×**
faster than native storage. With compiler-cache transfer, startup was
**{summary['artifact_ready_speedup_vs_storage']:.2f}×** faster than storage and
**{summary['artifact_ready_speedup_vs_weights']:.2f}×** faster than peer weights
alone: a **{summary['ready_reduction_seconds_mx_full']:.2f} s
({summary['ready_fraction_reduction_mx_full'] * 100:.1f}%)** total reduction
relative to the matched storage arm.

## Controls and limits

The model is `{spec['model_lock']['model']}` at
`{spec['model_lock']['revision']}`. Every arm uses the same runtime image
`{spec['model_lock']['runtime_image']}`; TP2 H100, native 1,048,576 context,
four sequences, 8,192 batched tokens and GPU-memory fraction 0.85.

All seed/receiver workers use `--language-model-only`, canary wait 1 second,
startup period 2 seconds / failure threshold 1,800, and readiness period
2 seconds. Other probe settings are held fixed. This adopts the measured
startup policy without making a production fault-detection or SLO claim.

One fresh idle source was retained throughout the receiver trial. Its initial
storage bootstrap took **{summary['source_bootstrap_ready_seconds']:.2f} s**;
the receiver saving requires an existing compatible source. Receivers ran in
fixed storage → weights → artifacts order on the same physical two H100 GPU
UUIDs, with distinct Pod UIDs and fresh private caches. Native storage has no
MX environment settings. Artifact transfer is disabled in the weight-only arm.
NIXL peer transfer uses LIBFABRIC/EFA. Host page cache is uncontrolled and never
flushed, so storage is an existing-checkpoint result, not a cold-download test.

This is one trial per arm with five-second Ready observation, not a distribution.
The first checked response follows evidence collection and is an upper bound on
first-possible inference. Phase timers overlap across ranks and within model /
engine initialization; do not sum the rows. No AgentX throughput load, Snapshot,
initialized-process restore or autoscaling was used.

## Acceptance and provenance

All arms passed the correct READY response, model/context/image/TP and effective
health checks with no restarts. Both MX arms transferred weights on both ranks
without storage fallback. The artifact arm loaded the published AOT cache on
TP0 and TP1; merely copying files was not sufficient for acceptance. Receiver
Pods and GPU claims were verified absent between arms. Final owned Pods,
ResourceClaims and DGDs are absent and the remote GPU lease is released.

- [Versioned baseline](../../../configs/dgd/super-vl-textonly-fast-startup/).
- [Frozen plan](MATCHED_BASELINE_PLAN.md).
- Spec SHA256: `{summary['spec_sha256']}`.
- Verified pullback: `results/workshop-baseline-pullback-20261104-a3/verification.json`:
  **{verification['files_verified']} files, zero mismatches**, controller exit zero.
- Derived CSV/JSON and raw-input hashes: `results/workshop-baseline-analysis-20261104-a3/`.
- Earlier multimodal and text-only health comparisons remain separate historical
  experiments; their timings are not mixed into this matched table.
''')
    outputs = [OUT / 'comparison.json', OUT / 'comparison.csv', REPORT, Path(__file__)]
    (OUT / 'analysis-sha256.json').write_text(json.dumps({str(p.relative_to(ROOT)): sha(p) for p in outputs}, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ['rows', 'input_sha256']}, indent=2))


if __name__ == '__main__':
    main()
