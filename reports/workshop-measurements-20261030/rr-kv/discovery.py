"""Pure, topic-specific frontend discovery qualification for two live workers."""
import re
from urllib.parse import urlsplit

ANSI = re.compile(r'\x1b\[[0-9;]*m')
WORKER = re.compile(r'Adding worker WorkerWithDpRank \{ worker_id: (\d+), dp_rank: 0 \}')
FIELD = re.compile(r'(endpoint|topic)="([^"]+)"')


def inspect(text, expected_ips, smoke_ids, mode):
    expected = sorted(set(expected_ips))
    assert mode in ['round-robin', 'kv'] and len(expected) == 2 and all(expected)
    lines = ANSI.sub('', text).splitlines()
    registered = sorted(set(WORKER.findall('\n'.join(lines))))
    topics = {}
    records = []
    for line in lines:
        if 'ZMQ single-consumer stream connected' not in line:
            continue
        fields = dict(FIELD.findall(line))
        if not fields.get('endpoint') or not fields.get('topic'):
            continue
        endpoint = fields['endpoint']
        host = urlsplit(endpoint).hostname
        topics.setdefault(fields['topic'], set()).add(endpoint)
        records.append({'topic': fields['topic'], 'endpoint': endpoint, 'host': host, 'line': line})
    kv = [record for record in records if record['topic'] == 'kv-events']
    observed = sorted({record['host'] for record in kv})
    smoke = sorted({str(value) for value in smoke_ids})
    errors = []
    if not smoke or 'None' in smoke:
        errors.append('No valid worker identity in successful smoke responses')
    if mode == 'round-robin':
        if len(smoke) != 2:
            errors.append('RR smoke did not exercise both workers')
    else:
        if len(registered) != 2:
            errors.append('Expected two registered KV worker IDs')
        if observed != expected:
            errors.append('KV-event source hosts do not match the current two worker Pod IPs')
        if not set(smoke) <= set(registered):
            errors.append('Smoke worker is absent from current KV worker registrations')
    return {'passed': not errors, 'errors': errors, 'router_mode': mode,
        'expected_worker_pod_ips': expected, 'registered_worker_ids': registered,
        'smoke_worker_ids': smoke, 'kv_event_source_hosts': observed,
        'zmq_endpoints_by_topic': {key: sorted(value) for key, value in sorted(topics.items())},
        'connection_records': records,
        'scope': 'Current frontend log and current worker Pod IPs; connection proof is separate from positive prefix-overlap/performance evidence'}
