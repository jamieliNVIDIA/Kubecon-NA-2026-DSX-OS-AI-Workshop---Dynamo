"""Read selected demo metadata without importing presenters or contacting Kubernetes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from demos.common.selection import identity
from demos.registry import DEMOS


ROOT = Path(__file__).resolve().parents[2]
SCOPE = 'Recorded state; no live readiness check or frozen-input validation.'
OWNERS = {
    'workshop-demo-single-replica': 'single-replica',
    'workshop-demo-modelexpress': 'modelexpress',
    'workshop-demo-disagg': 'disaggregated',
    'workshop-demo-snapshot': 'snapshot',
    'workshop-snapshot-dgd': 'snapshot-dgd',
    'workshop-demo-continuity': 'request-continuity',
    'workshop-demo-kvcr': 'kvcr',
    'workshop-demo-shadow': 'shadow',
}


def _read(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Expected metadata object')
    return value


def _path(root, value):
    if not isinstance(value, str) or not value or not value.isprintable():
        raise ValueError('Invalid recorded path')
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def _relative(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _phase(data, frozen, *, replacement_intent=False):
    if data.get('cleaned_at'):
        return 'cleaned'
    if data.get('replacement_pending') or (
            (data.get('replacement_intent') or replacement_intent) and not data.get('replacement_identity')):
        return 'started'
    if data.get('ready_observed_at') or data.get('initial_identity'):
        return 'ready'
    if data.get('apply_started_at') or data.get('deployed_at'):
        return 'started'
    if data.get('prepared') or data.get('mx_prepared'):
        return 'prepared'
    return 'frozen' if frozen else 'unprepared'


def _selection(root, spec):
    pointer = (root / '.local/demo-01-current.json' if spec.selector == 'single-replica' else
               root / '.local/current-runs' / (spec.selection_key + '.json'))
    frozen = False
    if not pointer.is_file() and spec.selector == 'shadow-composed':
        pointer = pointer.with_suffix('.frozen.json')
        frozen = pointer.is_file()
    row = {'demo': spec.selector, 'state': 'not selected', 'mode': None,
           'run': None, 'namespace': None, 'parent_run': None, 'dependent_run': None,
           'notes': []}
    if not pointer.is_file():
        return row
    try:
        selected = _read(pointer)
        path = _path(root, selected['run'])
        row['run'] = _relative(root, path)
        data = _read(path / 'demo.json')
        namespace = data.get('namespace')
        if not isinstance(namespace, str) or not namespace or not namespace.isprintable():
            raise ValueError('Invalid namespace')
        if not isinstance(data.get('rehearsal'), bool):
            raise ValueError('Invalid presentation mode')
        row['namespace'] = namespace
        row['mode'] = ('rehearsal' if data.get('rehearsal') else
                       'recorded evidence' if data.get('presentation_mode') == 'recorded-evidence' else 'live')
        # The DGD replacement controller records its intent in state.json while
        # demo.json still contains the previous worker's Ready observation.
        replacement_intent = (bool(_read(path / 'state.json').get('replacement_intent'))
                              if spec.selector == 'snapshot-dgd' else False)
        row['state'] = _phase(data, frozen, replacement_intent=replacement_intent)
        if 'identity' in selected and selected['identity'] != identity(data):
            row['state'] = 'invalid'
            row['notes'].append('Selected run identity changed.')
        binding = data.get('source_binding')
        parent = binding.get('run') if isinstance(binding, dict) else data.get('prepared_parent')
        if parent:
            row['parent_run'] = _relative(root, _path(root, parent))
        dependent = path / '.mx-dependent.json'
        if dependent.is_file():
            recorded = _read(dependent)
            if recorded.get('schema') != 1 or _path(root, recorded.get('parent_run')) != path:
                raise ValueError('Invalid dependency')
            row['dependent_run'] = _relative(root, _path(root, recorded['child_run']))
    except (OSError, ValueError, KeyError, TypeError):
        row['state'] = 'invalid'
        row['notes'].append('Cannot read or verify selected metadata.')
    return row


def snapshot(root=None):
    """Return only safe status fields; never resolve manifests, credentials, or assets."""
    root = Path(ROOT if root is None else root).resolve()
    leases = []
    for path in sorted((root / '.local').glob('*.gpu-lease/owner.json')):
        row = {'lease': _relative(root, path.parent), 'owner': 'invalid', 'run': None}
        try:
            data = _read(path)
            agent = data.get('agent')
            row['owner'] = OWNERS.get(agent, 'unrecognized owner') if isinstance(agent, str) else 'invalid'
            if data.get('run'):
                row['run'] = _relative(root, _path(root, data['run']))
        except (OSError, ValueError, KeyError, TypeError):
            row['owner'] = 'invalid'
        leases.append(row)
    return {'scope': SCOPE, 'demos': [_selection(root, spec) for spec in DEMOS.values()],
            'reservations': leases}


def render(value):
    lines = [value['scope'], '', f'{"Demo":22s} {"State":12s} {"Mode":18s} Selected run']
    for row in value['demos']:
        lines.append(f'{row["demo"]:22s} {row["state"]:12s} {row["mode"] or "—":18s} {row["run"] or "—"}')
        if row['namespace']:
            lines.append('  Namespace: ' + row['namespace'])
        if row['parent_run']:
            lines.append('  Uses source/parent: ' + row['parent_run'])
        if row['dependent_run']:
            lines.append('  Retained for MX target: ' + row['dependent_run'])
        lines.extend('  ' + note for note in row['notes'])
    lines += ['', 'Local reservations:']
    for row in value['reservations']:
        lines.append(f'  {row["lease"]}: {row["owner"]}' + (f' · {row["run"]}' if row['run'] else ''))
    if not value['reservations']:
        lines.append('  None recorded.')
    return '\n'.join(lines)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print the same recorded status fields as JSON.')
    args = parser.parse_args(arguments)
    value = snapshot()
    print(json.dumps(value, indent=2) if args.json else render(value))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
