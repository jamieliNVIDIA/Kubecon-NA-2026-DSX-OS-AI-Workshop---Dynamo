#!/usr/bin/env python3
"""Validate model discovery and a nonempty coding response without executing generated code."""
import argparse
import json
from pathlib import Path


def check(profile, models, response):
    expected = profile['model']
    advertised = {item.get('id') for item in models.get('data', [])}
    if expected not in advertised:
        raise ValueError('Frontend does not advertise the expected model.')
    if response.get('model') != expected:
        raise ValueError('Response model differs from the generated profile.')
    choices = response.get('choices', [])
    content = choices[0].get('message', {}).get('content') if choices else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Response has no assistant content.')
    if choices[0].get('finish_reason') != 'stop':
        raise ValueError('Response did not finish normally; inspect token budget and server output.')
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Bundle directory with profile.json, models.json, response.json.')
    args = parser.parse_args()
    values = [json.loads((args.directory / name).read_text())
              for name in ('profile.json', 'models.json', 'response.json')]
    content = check(*values)
    print(content)
    print('\nServing smoke passed: expected model, nonempty content, normal completion.')
    print('Code correctness, performance and failure recovery require their own checks.')


if __name__ == '__main__':
    main()
