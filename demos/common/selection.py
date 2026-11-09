"""Remember each presenter's successfully prepared run without weakening its gates."""
from __future__ import annotations

import json
import os
from pathlib import Path

RUN_HELP = ('Use a specific run; run/prime/cleanup otherwise use this launcher\'s last successfully '
            'prepared run. Prepare creates a fresh run.')


def read(path):
    return json.loads(Path(path).read_text())


def identity(data):
    return {key: value for key, value in data.items()
            if key in ('profile', 'demo_kind', 'namespace') or key.endswith('_profile')}


class RunSelection:
    def __init__(self, root, entrypoint, launcher, *, path=None, key=None, prepared_key='prepared', profile=None):
        self.path = Path(path) if path else Path(root) / '.local/current-runs' / ((key or Path(entrypoint).stem) + '.json')
        self.launcher = str(launcher)
        self.prepared_key, self.profile = prepared_key, profile

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.chmod(0o600)
        temporary.replace(path)

    def resolve(self, *, frozen=False):
        pointer = self.path.with_suffix('.frozen.json') if frozen else self.path
        if not pointer.is_file():
            action = 'freeze' if frozen else 'prepare'
            raise RuntimeError(f'No {"frozen" if frozen else "prepared"} demo selected. Run {self.launcher} {action} first.')
        selected = read(pointer)
        path = Path(selected['run'])
        if not (path / 'demo.json').is_file():
            raise RuntimeError(f'The selected demo run is missing. Run {self.launcher} prepare again.')
        data = read(path / 'demo.json')
        if (data.get('rehearsal') or data.get('cleaned_at') or
                (not frozen and not data.get(self.prepared_key)) or
                (self.profile is not None and data.get('profile') != self.profile) or
                ('identity' in selected and selected['identity'] != identity(data))):
            raise RuntimeError(f'The selected demo is no longer prepared for this profile. Run {self.launcher} prepare again.')
        return path

    def remember(self, demo):
        if demo.args.rehearsal:
            return
        self.remember_path(demo.path)

    def remember_path(self, path, *, frozen=False):
        path = Path(path).resolve()
        data = read(path / 'demo.json')
        if data.get('rehearsal'):
            return
        if data.get('cleaned_at') or (not frozen and not data.get(self.prepared_key)):
            raise ValueError('Only a successfully prepared, uncleaned run can be selected.')
        pointer = self.path.with_suffix('.frozen.json') if frozen else self.path
        self.write(pointer, {'run': str(path), 'identity': identity(data)})

    def forget(self, path):
        for pointer in (self.path, self.path.with_suffix('.frozen.json')):
            if pointer.is_file() and Path(read(pointer)['run']).resolve() == Path(path).resolve():
                pointer.unlink()

    def select(self, args, *, actions=('run', 'prime', 'cleanup')):
        offline = (getattr(args, 'rehearsal', False) or getattr(args, 'preview', False) or
                   getattr(args, 'full_manifest', False))
        if not args.run and args.action in actions and not offline:
            args.run = self.resolve()
        if args.action == 'cleanup' and (not args.run or not (Path(args.run) / 'demo.json').is_file()):
            raise ValueError('Cleanup requires an existing demo run with demo.json; check the exact --run path. No run was created.')

    def completed(self, demo, action):
        if action in ('prepare', 'prime'):
            self.remember(demo)
        elif action == 'cleanup':
            self.forget(demo.path)

    def activate(self, demo):
        # An explicit --run selects an existing prepared run too. Rehearsals and
        # older explicit one-shot workflows retain their existing behavior.
        if not demo.args.rehearsal and demo.data.get(self.prepared_key) and not demo.data.get('cleaned_at'):
            self.remember(demo)
