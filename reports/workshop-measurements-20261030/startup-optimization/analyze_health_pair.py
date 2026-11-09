"""Derive the matched health comparison from verified, immutable raw evidence."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
RUN=ROOT/'results/workshop-health-pullback-20261103-a1/verified/results/workshop-mx-startup-20261103-textonly-health01'
OUT=ROOT/'results/workshop-health-analysis-20261103-a1'
REPORT=Path(__file__).with_name('STARTUP_RESULTS.md')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value):
    return dt.datetime.fromisoformat(re.sub(r'(\.\d{6})\d+',r'\1',value.replace('Z','+00:00')))


def main():
    OUT.mkdir(exist_ok=False)
    verification=json.loads((RUN.parents[2]/'verification.json').read_text())
    assert verification['mismatches']==0
    analysis=json.loads((RUN/'startup-analysis.json').read_text())
    comparison=json.loads((RUN/'comparison.json').read_text())
    assert json.loads((RUN/'qualification.json').read_text())['passed']
    rows=[];inputs={str((RUN/'comparison.json').relative_to(ROOT)):sha(RUN/'comparison.json')}
    gpu_pairs=[]
    for mode in ('default','fast'):
        result=comparison[mode];folder=RUN/result['arm']
        record=next(r for r in analysis['records'] if r['arm']==result['arm'])
        log=folder/(result['target_pod']+'-main.log');text=log.read_text()
        end_line=next(s for s in text.splitlines() if 'init engine (' in s)
        tail=(timestamp(record['pods_ready_observed_at'])-timestamp(end_line.split(' ')[0])).total_seconds()
        proof=json.loads((folder/'identity-health-proof.json').read_text())
        assert proof['passed'] and proof['canary_wait_seconds_observed']==(['10'] if mode=='default' else ['1'])
        cache=json.loads((folder/'artifact-reuse-evidence.json').read_text())
        assert cache['actual_engine_cache_hit_ranks']==['0','1'] and not cache['failure_lines']
        gpu=tuple(line.split(',')[1].strip() for line in (folder/'gpu-visible.csv').read_text().strip().splitlines())
        gpu_pairs.append(gpu)
        row={'arm':mode,'ready_seconds':record['apply_to_ready_observed_seconds'],
             'first_checked_response_seconds':record['apply_to_first_correctness_response_seconds'],
             'model_load_seconds':record['model_load_seconds_max'],
             'engine_init_seconds':record['engine_init_seconds_max'],
             'backbone_profile_warmup_seconds':record['initial_profile_warmup_seconds_max'],
             'engine_end_to_observed_ready_seconds':tail,'pod_uid':record['pod_uid']}
        rows.append(row)
        for p in (log,folder/'identity-health-proof.json',folder/'artifact-reuse-evidence.json',folder/'result.json',folder/'gpu-visible.csv'):
            inputs[str(p.relative_to(ROOT))]=sha(p)
    reduction=rows[0]['ready_seconds']-rows[1]['ready_seconds']
    tail_reduction=rows[0]['engine_end_to_observed_ready_seconds']-rows[1]['engine_end_to_observed_ready_seconds']
    value={'rows':rows,'ready_reduction_seconds':reduction,'ready_fraction_reduction':reduction/rows[0]['ready_seconds'],
           'tail_reduction_seconds':tail_reduction,'same_receiver_gpu_uuids':gpu_pairs[0]==gpu_pairs[1],
           'gpu_uuids':gpu_pairs,'input_sha256':inputs,
           'scope':'One fixed-order matched pair, fresh receivers, retained idle source; five-second observation cadence; nested engine timers are not additive'}
    (OUT/'comparison.json').write_text(json.dumps(value,indent=2)+'\n')
    with (OUT/'comparison.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    a,b=rows
    REPORT.write_text(f'''# Startup candidates measured before Snapshot

Two configuration candidates were tested with Super VL, TP2 H100, native
1,048,576 context, four engine sequences, 8,192 batched tokens, GPU-memory
fraction 0.85 and the same pinned inference image. These are idle-source
startup experiments with a preexisting EFS checkpoint, not AgentX throughput
or fault-recovery benchmarks.

## Text-only mode: the main configuration gain

The MX weights-plus-artifacts receiver reached observed Ready in **188.82 s
(3m09s)**, versus **249.70 s (4m10s)** in the earlier multimodal run. This is
an unpaired, single-trial comparison with the deliberately reduced input
capability requested for this workshop.

Logged engine initialization fell **74.44 → 41.21 s**. Both ranks loaded the
transferred AOT compilation cache, and both source and receiver explicitly ran
in text-only mode. Backbone profiling/warmup remained **27.72 → 28.78 s**.
About **22.88 s** of the observed **60.88 s** total reduction was a shorter
health/probe tail under unchanged settings; the entire wall-clock difference
cannot be attributed to removing multimodal work.

Use `--language-model-only` on matching seed and receiver, with fresh compatible
artifacts. The detailed [text-only report](TEXT_ONLY_RESULT.md) includes the
exclusive timeline, raw-input hashes, KV capacity and exact GPU identities.

## Health timing: a smaller, matched gain

One idle source served both receiver arms. Receiver processes and caches were
fresh, and both loaded the same published torch artifact IDs on both ranks.
Receiver GPU UUIDs matched: **{gpu_pairs[0]==gpu_pairs[1]}**.

| Measurement | Default health | Faster health |
| --- | ---: | ---: |
| Deployment → observed Ready | {a['ready_seconds']:.2f} s | {b['ready_seconds']:.2f} s |
| Deployment → first checked correct response | {a['first_checked_response_seconds']:.2f} s | {b['first_checked_response_seconds']:.2f} s |
| Model loading, slower rank | {a['model_load_seconds']:.2f} s | {b['model_load_seconds']:.2f} s |
| Engine initialization | {a['engine_init_seconds']:.2f} s | {b['engine_init_seconds']:.2f} s |
| Backbone profiling/warmup, nested in engine initialization | {a['backbone_profile_warmup_seconds']:.2f} s | {b['backbone_profile_warmup_seconds']:.2f} s |
| Engine end → observed Ready | {a['engine_end_to_observed_ready_seconds']:.2f} s | {b['engine_end_to_observed_ready_seconds']:.2f} s |

Total observed startup fell **{reduction:.2f} s ({reduction/a['ready_seconds']*100:.2f}%)**.
The tail shortened **{tail_reduction:.2f} s**; approximately unchanged model and
engine timers plus bootstrap/scheduling variation explain why the total gain
differs from the tail gain. This is one fixed-order pair with five-second
Ready polling, not a latency distribution.

The fast arm changes worker canary wait **10 → 1 s**, startup-probe period
**30 → 2 s** and readiness-probe period **10 → 2 s**. Startup failure threshold
changes **120 → 1,800**, preserving a **nominal** 3,600 s period-times-threshold
budget. Probe timeouts and liveness are unchanged. Because the retained startup
timeout is 20 s, slow/hung probes can change the actual failure window; this is
not production-equivalent failure-detection qualification. Idle canary and
probe frequency also increases. The [frozen plan](TEXT_ONLY_HEALTH_PLAN.md)
contains exact controls and acceptance conditions.

## Remaining targets

The qualified text-only pilot still spends about **63 s before model loading**,
**35 s in MX hidden-tensor discovery**, and **29 s in backbone profiling/warmup**.
The last two are nested in their respective model/engine timers. Actual peer
copies are around three seconds and cached compilation around 0.2 s.

MX tensor discovery has no safe supported bypass: it transfers derived NVFP4
scales needed for correct inference. Profile and optimize repeated object
traversal while retaining the complete tensor manifest. Bootstrap and backbone
warmup need more detailed profiling before assigning a further saving.

vLLM already enables Triton persistent autotuning; adding its enable flag is
not a new optimization. The [warmup investigation](../round-robin/DECODER_WARMUP_NEXT_OPTIONS.md)
distinguishes confirmed cache behavior from unmeasured CUDA/JIT possibilities.

For workshop comparisons, remeasure storage, peer weights and peer-plus-artifacts
with the final text-only configuration before combining their numbers into a
matched loading-path chart. The original multimodal matrix remains a separate
matched experiment. No Snapshot or initialized-process restore was used here.

## Evidence

- Text-only pullback: `results/workshop-textonly-pullback-20261103-a1/verification.json`:
  443 files, zero mismatches, terminal controller success and zero remaining GPU
  resources in its namespace.
- Health pullback: `results/workshop-health-pullback-20261103-a1/verification.json`:
  {verification['files_verified']} files, zero mismatches, terminal controller success and zero
  remaining Pods, ResourceClaims and DGDs in its namespace.
- Derived health data and input hashes: `results/workshop-health-analysis-20261103-a1/`.
- Both experiments verified correct responses, image/context/TP identity,
  zero restarts and real rank-0/rank-1 compiler-cache loads before acceptance.
''')
    (OUT/'analysis-sha256.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p) for p in [OUT/'comparison.json',OUT/'comparison.csv',REPORT,Path(__file__)]},indent=2)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k not in ('rows','input_sha256')},indent=2))


if __name__=='__main__':main()
