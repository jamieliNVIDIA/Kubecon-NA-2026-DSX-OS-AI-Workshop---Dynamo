"""Pure startup timing, readiness and terminal rendering for workshop presenters."""
from __future__ import annotations

import datetime as dt
import re
import sys


PATTERNS = {
    'model_loading': r'Model loading took .*? and ([0-9.]+) seconds',
    'engine_initialization': r'init engine .*? took ([0-9.]+) s',
    'compilation': r'torch\.compile took ([0-9.]+) s in total',
    'warmup': r'Initial profiling/warmup run took ([0-9.]+) s',
}


def phase_timings(text):
    """Ranks overlap; report the slowest logged rank rather than summing them."""
    return {name: max(map(float, values)) if values else None
            for name, pattern in PATTERNS.items()
            for values in [re.findall(pattern, text)]}


def timestamp(value):
    # Kubernetes log timestamps use RFC3339Nano. Python 3.9 accepts at most
    # microseconds; truncate only the excess fractional precision.
    value = re.sub(r'(\.\d{6})\d+(?=Z|[+-]|$)', r'\1', value)
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def startup_progress(pods, text, applied_at, observed_at=None):
    """Track actual Pod timestamps and logged phase boundaries, without adding them."""
    observed = timestamp(observed_at) if observed_at else dt.datetime.now(dt.timezone.utc)
    applied = timestamp(applied_at)
    worker = next((p for p in pods if p['metadata'].get('labels', {}).get('workshop-role') == 'worker'
                   and not p['metadata'].get('deletionTimestamp')), None)
    started = None
    if worker:
        main = next((c for c in worker.get('status', {}).get('containerStatuses', []) if c['name'] == 'main'), {})
        value = main.get('state', {}).get('running', {}).get('startedAt')
        started = timestamp(value) if value else None
    complete = ready_pods(pods)
    ready_times = [timestamp(c['lastTransitionTime']) for p in pods
                   for c in p.get('status', {}).get('conditions', [])
                   if c['type'] == 'Ready' and c['status'] == 'True' and c.get('lastTransitionTime')]
    ready_at = max(ready_times) if complete and ready_times else None
    events = []
    pending_stamp = None
    for line in text.splitlines():
        try:
            stamp = timestamp(line.split()[0])
        except (ValueError, IndexError):
            # tqdm's carriage return may be normalized to a newline by text-mode
            # subprocess reads, leaving the Kubernetes timestamp on its own line.
            if pending_stamp is not None and line.strip():
                events.append((pending_stamp, line))
                pending_stamp = None
            continue
        events.append((stamp, line))
        pending_stamp = stamp if len(line.split()) == 1 else None

    def first(*markers):
        values = [when for when, line in events if any(marker in line for marker in markers)]
        return min(values) if values else None

    def last(pattern):
        values = [when for when, line in events if re.search(pattern, line)]
        return max(values) if values else None

    def duration(pattern):
        values = re.findall(pattern, text)
        return max(map(float, values)) if values else None

    containers = worker.get('spec', {}).get('containers', []) if worker else []
    container = next((c for c in containers if c.get('name') == 'main'), containers[0] if containers else {})
    args = container.get('args', [])
    mx = ('--load-format' in args and args[args.index('--load-format') + 1:][:1] == ['modelexpress'] or
          '--load-format=modelexpress' in args or
          any(marker in text for marker in ('MxModelLoader', 'InstantTensor', 'RDMA transfer complete:')))

    def rank(line):
        match = re.search(r'Worker_TP(\d+)|\[Worker (\d+)\]', line)
        return int(next(value for value in match.groups() if value is not None)) if match else None

    observed_ranks = {value for _, line in events if (value := rank(line)) is not None}
    tp = max(observed_ranks) + 1 if observed_ranks else 1
    try:
        value = (args[args.index('--tensor-parallel-size') + 1] if '--tensor-parallel-size' in args else
                 next(a.split('=', 1)[1] for a in args if a.startswith('--tensor-parallel-size=')))
        if int(value) > 0:
            tp = int(value)
    except (ValueError, IndexError, StopIteration):
        pass
    expected_ranks = set(range(tp))

    def rank_completions(pattern):
        result = {}
        for when, line in events:
            match = re.search(pattern, line)
            value = rank(line)
            if match and (value is not None or tp == 1):
                result[value if value is not None else 0] = (when, match)
        return result

    def all_finished(completions):
        return expected_ranks <= completions.keys()

    def final_completion(completions):
        return max(completions[r][0] for r in expected_ranks) if all_finished(completions) else None

    engine_start = first('Initializing a V1 LLM engine', 'Initializing a V0 LLM engine')
    model_start = first('Loading model from scratch', 'Starting to load model', 'MxModelLoader starting')
    weights_start = first('Prefetching checkpoint files into page cache started',
                          'Loading safetensors checkpoint shards:')
    weights_end = last(r'Loading weights took ([0-9.]+) seconds')
    model_end = last(PATTERNS['model_loading'])
    engine_end = last(PATTERNS['engine_initialization'])
    warmup_start = first('Warming up Mamba2 SSD Triton kernels',
                         'Warming up ll_bf16 router GEMM kernels', 'Running FlashInfer autotune',
                         'Initial profiling/warmup run')
    logged = phase_timings(text)
    model_completions = rank_completions(PATTERNS['model_loading'])
    copy_completions = {}
    if mx:
        # MX uses InstantTensor or peer-copy markers rather than vLLM's native
        # safetensor-shard markers. Keep the complete cross-rank loading window
        # separate from the duration of an individual rank's network copy.
        weight_starts = [first('Prefetching checkpoint files into page cache started',
                               'Loading safetensors checkpoint shards:', 'Attempting InstantTensor loading',
                               'Loading safetensors using InstantTensor loader:')]
        peer_starts = [when for when, line in events
                       if re.search(r'Receiving \d+ tensors from source \(P2P\)', line)]
        weights_start = min([value for value in weight_starts if value is not None] + peer_starts, default=None)
        copy_pattern = (r'(?:\[TIMING\] RDMA transfer complete: \d+ tensors, [0-9.]+ GB, (\d+(?:\.\d+)?)s'
                        r'|Transfer complete: \d+ tensors, [0-9.]+ GB in (\d+(?:\.\d+)?)s)')
        copy_completions = rank_completions(copy_pattern)
        if 'InstantTensor weight loading complete' in text or 'Attempting InstantTensor loading' in text:
            weights_completions = rank_completions(r'InstantTensor weight loading complete')
        elif peer_starts or copy_completions:
            weights_completions = copy_completions
        else:
            weights_completions = rank_completions(r'Loading weights took ([0-9.]+) seconds')
        weights_end = final_completion(weights_completions)
        model_end = final_completion(model_completions)

    def elapsed(start, end=observed):
        return max(0, (end - start).total_seconds()) if start else None

    def phase(name, start, end, source, *, passed=False, measured=None):
        # Later milestones prove progression, but cannot supply a missing boundary.
        done = end is not None or passed or complete or measured is not None
        status = ('done' if measured is not None or (start and end) else 'unknown') if done else (
            'running' if start else 'pending')
        seconds = measured if measured is not None else (
            elapsed(start, end) if start and end else elapsed(start) if status == 'running' else None)
        return {'name': name, 'status': status, 'seconds': seconds, 'source': source,
                'started_at': start.isoformat() if start else None,
                'ended_at': end.isoformat() if end else None}

    phases = [
        phase('Pod startup', applied, started, 'apply to worker container start'),
        phase('Runtime setup', started, engine_start,
              'container start to vLLM engine configuration; imports, discovery and model config',
              passed=bool(model_start or weights_start or model_end)),
        phase('Worker / TP setup', engine_start, model_start,
              'vLLM engine configuration to model-loader start; worker spawn, CUDA and TP/NCCL setup',
              passed=bool(weights_start or model_end)),
    ]
    if mx:
        phases.append(phase('Model loading', model_start, model_end,
                            'slowest logged TP rank; includes model setup, weight loading and finalizing',
                            passed=bool(engine_end),
                            measured=logged['model_loading'] if all_finished(model_completions) else None))
    phases += [
        phase('Model setup', model_start, weights_start,
              'model-loader start to weight-loader/copy start; model construction and kernel selection',
              passed=bool(model_end or engine_end)),
        phase('Weight loading', weights_start, weights_end,
              ('first weight-loader/copy start to the last TP rank completion; includes staggered rank starts'
               if mx else 'checkpoint prefetch/shards to weight-load completion; background prefetch overlaps'),
              passed=bool(model_end or engine_end),
              measured=None if mx else duration(r'Loading weights took ([0-9.]+) seconds')),
    ]
    if mx and all_finished(copy_completions):
        copy_seconds = max(float(next(g for g in copy_completions[r][1].groups() if g is not None))
                           for r in expected_ranks)
        phases.append(phase('  Peer copy', None, final_completion(copy_completions),
                            'slowest reported TP rank network-copy duration; inside the weight-loading window',
                            measured=copy_seconds))
    phases += [
        phase('Weight finalizing', weights_end, model_end,
              'last weight-load completion to last model-load completion; rank synchronization and postprocessing',
              passed=bool(engine_end)),
        phase('Engine init', model_end, engine_end,
              'model-load completion to engine-init completion; KV profiling/allocation and warmup',
              measured=logged['engine_initialization']),
        phase('  Warmup window', warmup_start, engine_end,
              'first explicit warmup marker to engine-init completion; overlaps engine profiling and KV setup',
              measured=logged['warmup']),
        phase('Readiness', engine_end, ready_at, 'engine-init completion to Pod readiness'),
    ]
    return {'observed_at': observed.isoformat(), 'ready': complete, 'phases': phases,
            'loader': 'modelexpress' if mx else 'native',
            'total_seconds': elapsed(applied, ready_at or observed),
            'ready_transition_at': ready_at.isoformat() if ready_at else None,
            'logged_seconds_slowest_rank': logged}


def progress_lines(progress):
    rows = []
    for phase in progress['phases']:
        seconds = phase['seconds']
        duration = f'{seconds:6.1f}s' if seconds is not None else '      —'
        name = phase['name']
        if progress.get('loader') == 'modelexpress' and name in ('Model setup', 'Weight loading', 'Weight finalizing'):
            name = '  ' + name
        status = 'not timed' if phase['status'] == 'unknown' else phase['status']
        rows.append((name, status, duration))
    name_width = max([18] + [len(name) for name, _, _ in rows])
    status_width = max([8] + [len(status) for _, status, _ in rows])
    return '\n'.join(f'  {name:{name_width}s} {status:{status_width}s} {duration}'
                     for name, status, duration in rows)


class StartupDisplay:
    """Refresh one terminal block; retain snapshots in captured output."""

    def __init__(self):
        self.height = 0

    def reset(self):
        self.height = 0

    def update(self, progress):
        elapsed = progress.get('total_seconds')
        total = f'{elapsed:.1f}s' if elapsed is not None else 'simulated'
        lines = (progress_lines(progress) + '\n  Elapsed: ' + total).splitlines()
        terminal = sys.stdout.isatty()
        if terminal and self.height:
            print(f'\033[{self.height}F', end='')
        for line in lines:
            print(('\033[2K' if terminal else '') + line)
        if terminal and self.height > len(lines):
            # Optional loader details can disappear after a fresh observation.
            # Clear the old tail and restore the cursor below the current block.
            extra = self.height - len(lines)
            for _ in range(extra):
                print('\033[2K')
            print(f'\033[{extra}F', end='')
        self.height = len(lines) if terminal else 0
        sys.stdout.flush()


def ready_pods(pods):
    active = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
    roles = {role: [p for p in active if p['metadata'].get('labels', {}).get('workshop-role') == role]
             for role in ('frontend', 'worker')}
    return (all(len(values) == 1 for values in roles.values()) and
            all(any(c['type'] == 'Ready' and c['status'] == 'True'
                    for c in p.get('status', {}).get('conditions', [])) for p in active))
