#!/usr/bin/env python3
"""Select prepared runs at the launcher boundary; retain native lifecycle gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import sys
import time
from types import SimpleNamespace

from demos.common.selection import RunSelection
from demos.registry import by_script

ROOT = Path(__file__).resolve().parents[2]


def launch(script, arguments, *, execute=None):
    script = Path(script).resolve()
    spec = by_script(script)
    name = spec.selection_key
    selection = RunSelection(ROOT, script, spec.command, key=name,
                             prepared_key='mx_prepared' if name == 'workshop_modelexpress_demo' else 'prepared')
    arguments = list(arguments)
    if '-h' in arguments or '--help' in arguments:
        args = None  # Preserve the native help and parser, without selecting state.
        if name == 'workshop_kvcr_prepared' and arguments[0] == 'prepare':
            arguments[0] = 'bind'
    else:
        # Parse only the common options. Everything else reaches the original
        # parser unchanged, including source, placement, storage and fault gates.
        parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        parser.add_argument('action', nargs='?', default='run')
        parser.add_argument('--run', type=Path)
        for option in ('rehearsal', 'preview', 'full-manifest'):
            parser.add_argument('--' + option, action='store_true')
        # A leading positional is the action; unknown option values must not be
        # mistaken for it (for example `--storage efs` with no explicit action).
        action = arguments[0] if arguments and not arguments[0].startswith('-') else 'run'
        options = arguments[1:] if arguments and action == arguments[0] else arguments
        args, _ = parser.parse_known_args([action] + options)
        if args.rehearsal and spec.selector in ('kvcr-prepared', 'shadow-composed'):
            standard = 'kvcr' if spec.selector == 'kvcr-prepared' else 'shadow'
            raise ValueError(f'{spec.selector} requires qualified live inputs. For an offline walkthrough, use:\n'
                             f'uv run python -m demos {standard} --rehearsal')
        offline = args.rehearsal or args.preview or args.full_manifest or action == 'preview'
        composed = name == 'workshop_shadow_composed'
        bound = name == 'workshop_kvcr_prepared'
        if composed and action == 'prepare' and args.run is None and not offline:
            args.run = selection.resolve(frozen=True)
        if (composed and (action == 'preview' or args.preview) or bound and action == 'preview') and args.run is None:
            args.run = selection.resolve(frozen=composed and not selection.path.exists())
        selection.select(args, actions=('run', 'prime', 'cleanup') +
                         (('probe', 'deploy', 'wait', 'verify', 'finalize') if composed else ()) +
                         (('verify',) if name == 'workshop_shadow_demo' else ()))
        fresh = ((action == 'prepare' and not composed) or (composed and action == 'freeze') or
                 (bound and action == 'bind'))
        if args.run is None and fresh and not offline:
            args.run = ROOT / 'results' / f'demo-{spec.id}-{name}-{time.time_ns()}'
        if args.run is not None and '--run' not in arguments and not any(v.startswith('--run=') for v in arguments):
            arguments += ['--run', str(args.run)]
        if bound:
            if action == 'prepare':
                arguments[0] = 'bind'  # Native preparation is a checked repair/parent binding.
            elif not arguments or arguments[0].startswith('-'):
                arguments.insert(0, 'run')

    previous = sys.argv
    try:
        sys.argv = [str(script)] + arguments
        try:
            (execute or runpy.run_path)(str(script), run_name='__main__')
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
        if args is not None and not (args.rehearsal or args.preview or args.full_manifest):
            if args.action in ('prepare', 'prime', 'bind') and args.run:
                selection.remember_path(args.run)
            elif args.action == 'freeze' and args.run:
                selection.remember_path(args.run, frozen=True)
            elif args.action == 'cleanup' and args.run:
                selection.forget(args.run)
            elif args.action == 'run' and args.run and (args.run / 'demo.json').is_file():
                selection.activate(SimpleNamespace(path=args.run, args=args,
                                                    data=json.loads((args.run / 'demo.json').read_text())))
    finally:
        sys.argv = previous


if __name__ == '__main__':
    try:
        launch(sys.argv[1], sys.argv[2:])
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print('Demo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
