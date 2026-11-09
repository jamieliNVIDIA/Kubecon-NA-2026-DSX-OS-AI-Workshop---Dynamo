"""Correlate the pinned frontend's retry trace when SSE attribution is first-write-wins."""
import re

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'


def fields(line):
    return {k: v.strip('"') for k, v in re.findall(r'([\w.]+)=("[^"]*"|[^\s]+)', line)}


def retry_proof(log, response_id, target, workers):
    """Require one retry, preserved tokens and a current peer, all in the same HTTP span.

    The pinned RequestTracker stores worker IDs in OnceLock. A conflicting
    decode_worker_id write records the actual retry routing target, while SSE
    retains the original ID. Never infer this handoff from a global counter.
    """
    lines = ANSI.sub('', log).splitlines()
    internal = response_id.removeprefix('chatcmpl-') if hasattr(str, 'removeprefix') else response_id[9:]
    initial = [line for line in lines if 'route request failed' in line and
               re.search(r'\brequest_id=' + re.escape(internal) + r'(?:\s|$)', line) and
               fields(line).get('worker_id') == target and fields(line).get('request.attempt') == '0']
    outer = {re.findall(r'\brequest_id=(' + UUID + ')', line)[0] for line in initial}
    if len(outer) != 1:
        raise ValueError('Missing unique response-to-HTTP-span failure correlation.')
    request_id = next(iter(outer))
    scoped = [line for line in lines if re.search(r'\brequest_id=' + re.escape(request_id) + r'(?:\s|$)', line)]
    retries = [line for line in scoped if 'migration retry scheduled' in line]
    if len(retries) != 1:
        raise ValueError('Expected exactly one correlated migration retry.')
    retry = fields(retries[0])
    if (retry.get('request.attempt') != '1' or retry.get('migration.is_retry') != 'true' or
            retry.get('migration.from_worker_id') != target or
            int(retry.get('migration.tokens_completed', '0')) <= 0):
        raise ValueError('Retry did not retain output from the faulted worker.')
    selections = [line for line in scoped if 'Conflicting request tracker write' in line and
                  fields(line).get('field') == 'decode_worker_id']
    peers = {fields(line).get('new') for line in selections if fields(line).get('existing') == target}
    if len(peers) != 1 or next(iter(peers)) not in workers or next(iter(peers)) == target:
        raise ValueError('Retry routing did not identify the already-qualified surviving worker.')
    # The retry and selected peer must follow the original failed attempt in log order.
    if not (lines.index(initial[0]) < lines.index(retries[0]) < lines.index(selections[0])):
        raise ValueError('Migration trace ordering is inconsistent.')
    return {'http_request_id': request_id, 'response_id': response_id,
            'failed_worker': target, 'continuation_worker': next(iter(peers)),
            'retained_output_tokens': int(retry['migration.tokens_completed']), 'attempt': 1,
            'source': 'Response-correlated frontend retry and decode-worker selection logs',
            'lines': [initial[0], retries[0], *selections]}
