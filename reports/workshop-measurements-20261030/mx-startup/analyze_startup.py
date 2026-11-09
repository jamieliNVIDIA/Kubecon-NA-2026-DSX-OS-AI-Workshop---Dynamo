#!/usr/bin/env python3
"""Extract observed startup boundaries without inventing unlogged subphases."""
import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re


PATTERNS = {
    'model_load_seconds': r'Model loading took .* and ([0-9.]+) seconds',
    'torch_compile_seconds': r'torch\.compile took ([0-9.]+) s in total',
    'initial_profile_warmup_seconds': r'Initial profiling/warmup run took ([0-9.]+) s',
    'engine_init_seconds': r'init engine .* took ([0-9.]+) s',
    'cuda_graph_capture_seconds': r'Graph capturing finished in ([0-9.]+) secs',
    'tensor_registration_seconds': r'\[TIMING\] register_tensors: ([0-9.]+)s total',
    'peer_transfer_seconds': r'Transfer complete: \d+ tensors, [0-9.]+ GB in ([0-9.]+)s',
}
EVENT_WORDS = (
    'Loading model from scratch', 'Model loading took', 'Using cache directory:',
    'Starting torch.compile', 'torch.compile took', 'Initial profiling/warmup',
    'Graph capturing finished', 'init engine (', '[TIMING]', 'Trying strategy:',
    'InstantTensor weight loading complete', 'Transfer complete:',
    'Building JIT module', 'which ModelExpress installed',
    'transferred cache was not reused', 'Connected to EFA',
)


def timestamp(text):
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00'))


def extract(run):
    records = []
    for path in sorted(run.glob('*/result.json')):
        result = json.loads(path.read_text())
        folder = path.parent
        logs = list(folder.glob(result['target_pod'] + '-*.log'))
        text = '\n'.join(log.read_text() for log in logs)
        row = {key: result[key] for key in (
            'arm', 'apply_started_at', 'pods_ready_observed_at',
            'apply_to_ready_observed_seconds',
            'apply_to_first_correctness_response_seconds', 'node', 'pod_uid')}
        events = []
        for line in text.splitlines():
            if any(word in line for word in EVENT_WORDS):
                events.append(line)
        (folder / 'startup-phase-events.json').write_text(json.dumps(events, indent=2) + '\n')
        for name, pattern in PATTERNS.items():
            values = [float(value) for value in re.findall(pattern, text)]
            row[name + '_all_logged'] = values
            row[name + '_max'] = max(values) if values else None
        pods = json.loads((folder / 'pods.json').read_text())['items']
        worker = next(pod for pod in pods if pod['metadata']['name'] == result['target_pod'])
        row['worker_created_at'] = worker['metadata']['creationTimestamp']
        conditions = {condition['type']: condition for condition in worker['status'].get('conditions', [])}
        row['scheduled_at'] = conditions.get('PodScheduled', {}).get('lastTransitionTime')
        row['pod_ready_transition_at'] = conditions.get('Ready', {}).get('lastTransitionTime')
        container = worker['status']['containerStatuses'][0]
        row['container_started_at'] = container['state']['running']['startedAt']
        row['image_id'] = container['imageID']
        row['restarts'] = container.get('restartCount')
        row['apply_to_container_start_seconds'] = (timestamp(row['container_started_at']) - timestamp(row['apply_started_at'])).total_seconds()
        row['container_start_to_ready_transition_seconds'] = (timestamp(row['pod_ready_transition_at']) - timestamp(row['container_started_at'])).total_seconds()
        records.append(row)
    output = {'analyzer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'run': str(run.resolve()), 'records': records,
              'boundaries': 'Apply-to-Ready includes controller scheduling and container startup; readiness is observed at 5-second polling intervals. Log phase durations overlap and must not be summed. File acquisition, GPU copy and postprocessing are not independently measurable when logs combine them. First correctness response follows evidence collection and is an upper bound on first-possible inference.'}
    (run / 'startup-analysis.json').write_text(json.dumps(output, indent=2) + '\n')
    if records:
        with (run / 'startup-summary.csv').open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    print(json.dumps({'run': str(run), 'arms': [
        {key: record[key] for key in ('arm', 'apply_to_ready_observed_seconds',
                                     'model_load_seconds_max', 'engine_init_seconds_max',
                                     'peer_transfer_seconds_max')}
        for record in records]}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    extract(parser.parse_args().run)
