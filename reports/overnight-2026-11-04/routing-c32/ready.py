#!/usr/bin/env python3
"""Bounded frontend model discovery gate; no inference or workload mutation."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.request


class ModelReadinessTimeout(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__('Expected model was not advertised before the readiness deadline.')


def wait_for_model(fetch, expected_model, *, timeout=120.0, interval=1.0,
                   monotonic=time.monotonic, sleep=time.sleep):
    if not expected_model or not math.isfinite(timeout) or not math.isfinite(interval) or min(timeout, interval) <= 0:
        raise ValueError('Expected model and positive finite readiness timing are required.')
    start = monotonic()
    deadline = start + timeout
    observations = []
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ModelReadinessTimeout({'passed': False, 'expected_model': expected_model,
                'attempts': len(observations), 'elapsed_seconds': monotonic() - start,
                'observations': observations})
        try:
            body = fetch(min(10.0, remaining))
            if not isinstance(body, dict) or not isinstance(body.get('data'), list):
                raise ValueError('Model listing is not a data array.')
            ids = [item.get('id') for item in body['data'] if isinstance(item, dict)]
            observations.append({'elapsed_seconds': monotonic() - start, 'advertised_models': ids})
            if expected_model in ids and monotonic() <= deadline:
                return {'passed': True, 'expected_model': expected_model,
                    'attempts': len(observations), 'elapsed_seconds': monotonic() - start,
                    'observations': observations,
                    'scope': 'Exact frontend model listing only; inference is qualified separately.'}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            observations.append({'elapsed_seconds': monotonic() - start,
                                 'error': type(error).__name__ + ': ' + str(error)})
        remaining = deadline - monotonic()
        if remaining > 0:
            sleep(min(interval, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base')
    parser.add_argument('model')
    parser.add_argument('--timeout', type=float, default=120.0)
    parser.add_argument('--interval', type=float, default=1.0)
    args = parser.parse_args()

    def fetch(timeout):
        with urllib.request.urlopen(args.base.rstrip('/') + '/v1/models', timeout=timeout) as response:
            return json.load(response)

    try:
        receipt = wait_for_model(fetch, args.model, timeout=args.timeout, interval=args.interval)
    except ModelReadinessTimeout as error:
        print(json.dumps(error.receipt), flush=True)
        return 1
    print(json.dumps(receipt), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
