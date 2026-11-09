"""Run a workshop demo: python -m demos <demo> [action] [options]."""
from __future__ import annotations

import argparse
import importlib
import subprocess
import sys

from demos.registry import DEMOS, get_demo


def list_demos() -> None:
    for spec in DEMOS.values():
        print(f'{spec.selector:22s} {spec.title}')


def dispatch(spec, arguments) -> None:
    if spec.id == '01-single-replica':
        module = importlib.import_module(spec.module)
        previous = sys.argv
        try:
            sys.argv = [str(spec.path)] + list(arguments)
            module.main()
        finally:
            sys.argv = previous
    else:
        from demos.common.presenter import launch
        launch(spec.path, arguments)


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog='Use a demo name, number (01 or 1), or full ID (01-single-replica). '
               'Run python -m demos <demo> --help for its actions and options.')
    parser.add_argument('demo', nargs='?', help='Demo name or number; list shows demos, status shows selected runs.')
    parser.add_argument('arguments', nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.demo is None:
        parser.print_help()
        return 0
    if args.demo == 'list':
        if args.arguments:
            parser.error('list does not accept demo actions or options')
        list_demos()
        return 0
    if args.demo == 'status':
        from demos.common.status import main as status
        return status(args.arguments)
    try:
        spec = get_demo(args.demo)
    except ValueError as error:
        parser.error(str(error))
    try:
        dispatch(spec, args.arguments)
    except KeyboardInterrupt:
        print('\nStopped. Use this demo\'s cleanup command when finished.', file=sys.stderr)
        return 130
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('Demo stopped: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
