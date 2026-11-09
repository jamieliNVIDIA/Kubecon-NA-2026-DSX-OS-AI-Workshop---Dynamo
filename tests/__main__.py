"""Run the offline regression suite or one feature group with stable imports."""
from __future__ import annotations

import argparse
import unittest

from tests.support import ROOT


GROUPS = (
    'common', 'single_replica', 'modelexpress', 'disaggregated', 'snapshot',
    'request_continuity', 'routing', 'kvcr', 'shadow', 'platform', 'take_home',
    'metrics', 'development', 'development.mx_cache', 'development.disaggregated',
)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', nargs='?', choices=GROUPS,
                        type=lambda value: value.replace('/', '.'),
                        help='Optional feature group; omit to run the entire suite.')
    parser.add_argument('--pattern', default='test_*.py',
                        help='Test filename pattern within the selected group (default: test_*.py).')
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument('-v', '--verbose', action='store_const', dest='verbosity', const=2)
    verbosity.add_argument('-q', '--quiet', action='store_const', dest='verbosity', const=0)
    parser.set_defaults(verbosity=1)
    args = parser.parse_args(arguments)

    start = ROOT / 'tests'
    if args.group:
        start = start.joinpath(*args.group.split('.'))
    if not start.is_dir():
        parser.error('Test group directory does not exist: ' + str(start.relative_to(ROOT)))

    suite = unittest.TestLoader().discover(
        start_dir=str(start), pattern=args.pattern, top_level_dir=str(ROOT))
    if not suite.countTestCases():
        parser.error('No tests matched the selected group and pattern.')
    result = unittest.TextTestRunner(verbosity=args.verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
