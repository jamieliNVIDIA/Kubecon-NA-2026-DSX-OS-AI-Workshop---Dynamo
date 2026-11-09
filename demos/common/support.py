"""Shared CLI and read-only panes for the P/D and Snapshot presenter demos."""
from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import subprocess
import sys
import time

import yaml
import demos.common.runtime as ui


class StringDumper(yaml.SafeDumper):
    """Kubernetes' YAML 1.1 decoder treats bare y/n as booleans."""


def represent_string(dumper, value):
    style = "'" if value.lower() in ('y', 'n', 'yes', 'no', 'on', 'off', 'true', 'false') else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


StringDumper.add_representer(str, represent_string)


def write_yaml(path, obj):
    Path(path).write_text(yaml.dump(obj, Dumper=StringDumper, sort_keys=False))


def release(path, owner):
    if ui.lease_owned(path, owner):
        (ui.LEASE / 'owner.json').unlink()
        ui.LEASE.rmdir()


def healthy(pods):
    for pod in pods:
        statuses = pod.get('status', {}).get('containerStatuses', [])
        if (pod.get('status', {}).get('phase') == 'Failed' or
                any(c.get('restartCount', 0) for c in statuses) or
                any(c.get('state', {}).get('waiting', {}).get('reason') in
                    ('ErrImagePull', 'ImagePullBackOff', 'CreateContainerConfigError', 'CrashLoopBackOff')
                    for c in statuses)):
            raise RuntimeError('Demo Pod failed or restarted: ' + pod['metadata']['name'])


def worker_phase_table(workers):
    """Join workers by phase name: loaders need not emit identical phase lists."""
    roles, names = list(workers), []
    phases = {role: {phase['name']: phase for phase in workers[role]['phases']} for role in roles}
    for role in roles:
        sequence = list(phases[role])
        for index, name in enumerate(sequence):
            if name not in names:
                anchor = next((later for later in sequence[index + 1:] if later in names), None)
                names.insert(names.index(anchor) if anchor else len(names), name)
    width = max([18] + [len(name) for name in names])
    lines = [f'{"Phase":{width}s}' + ''.join(f'{role:20s}' for role in roles)]
    for name in names:
        cells = []
        for role in roles:
            phase = phases[role].get(name)
            if phase is None:
                cells.append(f'{"—":20s}')
                continue
            status = 'not timed' if phase['status'] == 'unknown' else phase['status']
            seconds = f'{phase["seconds"]:.1f}s' if phase['seconds'] is not None else '—'
            cells.append(f'{status:9s} {seconds:>7s}   ')
        lines.append(f'{name:{width}s}' + ''.join(cells))
    return '\n'.join(lines)


def resource_observations(data):
    """Bound every read and return snapshots separately from their availability."""
    commands = [ui.kbase() + ['get', 'pods', '-n', data['namespace'], '-l', data['pod_selector'], '-o', 'json']]
    if data.get('resource_kinds'):
        commands.append(ui.kbase() + ['get', data['resource_kinds'], '-n', data['namespace'], '-o', 'json'])
    items, errors = {}, []
    for command in commands:
        result = ui.panel_read(command)
        if result.returncode:
            errors.append((result.stderr or result.stdout or 'Resource read failed.').strip())
            continue
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
                raise ValueError('Expected a resource list.')
            for item in payload['items']:
                if not isinstance(item, dict) or not isinstance(item.get('metadata'), dict):
                    raise ValueError('Expected resource metadata.')
                if any(field in item and not isinstance(item[field], dict) for field in ('spec', 'status')):
                    raise ValueError('Expected resource fields.')
                key = (item['kind'], item['metadata'].get('namespace'), item['metadata']['name'])
                items[key] = item
        except (ValueError, KeyError, TypeError):
            errors.append('The resource API returned an invalid snapshot.')
    values = list(items.values())
    try:
        ui.compact_resource_table(values)
    except (AttributeError, KeyError, TypeError, ValueError):
        values = []
        errors.append('The resource API returned an invalid snapshot.')
    return values, errors


def observe(path, view, once=False):
    # Never instantiate Run here: pane processes must not change evidence/state.
    while True:
        data = ui.read_json(path / 'demo.json')
        simulated = data['rehearsal']
        resources, errors = (resource_observations(data)
                             if view == 'resources' and not simulated and data.get('prepared') else ([], []))
        print('\033[2J\033[H' + ('Resources + timing' if view == 'resources' else 'Worker / restore logs') +
              (' · REHEARSAL / SIMULATED' if simulated else ' · LIVE'), flush=True)
        if view == 'resources':
            print(data.get('resource_note', ''))
        print('Namespace: ' + data['namespace'])
        note = ui.observer_note(data.get('startup_observation'))
        if note:
            print(note, flush=True)
        if view == 'resources':
            if errors:
                print('Observer disconnected; current readiness is unknown. Saved startup timings are historical.', flush=True)
                for error in errors:
                    print(error, flush=True)
            workers = data.get('worker_startup', {})
            if workers:
                print('\n' + worker_phase_table(workers))
            progress = data.get('startup')
            if progress:
                total = progress.get('total_seconds')
                print('\nApply to Ready: ' + (f'{total:.1f}s' if total is not None else 'not measured'))
                if not data.get('worker_startup'):
                    print(ui.progress_lines(progress))
            if simulated:
                print('\nState: ' + ('Ready' if data.get('ready_observed_at') else 'preparing / starting'))
            elif data.get('prepared'):
                print('\n' + ui.compact_resource_table(resources), flush=True)
        else:
            files = data.get('log_files', [])
            for name in files:
                file = path / name
                print('\n' + name)
                if file.exists():
                    with file.open() as stream:
                        print(''.join(deque(stream, maxlen=9)).rstrip())
                else:
                    print('Waiting for startup.')
            if not files:
                print('Waiting for the deployment step.')
        if once:
            return
        time.sleep(3)


def main(demo_type, steps, port, *, snapshot=False):
    parser = argparse.ArgumentParser(description=demo_type.__doc__)
    parser.add_argument('action', nargs='?', default='run',
                        choices=['run', 'prepare', 'prime', 'preview', 'cleanup', 'observe', 'hold'])
    parser.add_argument('--run', type=Path)
    for flag in ('rehearsal', 'preview', 'plain', 'auto', 'detach', 'once'):
        parser.add_argument('--' + flag, action='store_true', help=argparse.SUPPRESS if flag == 'once' else None)
    parser.add_argument('--port', type=int, default=port)
    parser.add_argument('--timeout', type=int, default=2700)
    parser.add_argument('--view', choices=['resources', 'logs'], default='resources')
    if snapshot:
        parser.add_argument('--storage', choices=['nvme', 'efs'], default=None,
                            help='First-run choice, retained in demo.json (default: nvme).')
    args = parser.parse_args()
    if not 0 < args.port < 65536 or args.timeout <= 0:
        parser.error('Port must be 1..65535 and timeout must be positive.')
    if args.action == 'hold':
        while True:
            time.sleep(60)
    if args.action == 'observe':
        if not args.run:
            parser.error('observe needs --run')
        observe(args.run.resolve(), args.view, args.once)
        return
    if args.action in ('prime', 'cleanup') and not args.run:
        parser.error(args.action + ' needs --run')
    demo = demo_type(args)
    print('Demo files: ' + str(demo.path), flush=True)
    if args.preview or args.action == 'preview':
        demo.preview()
        for index, (title, explanation) in enumerate(steps, 1):
            print(f'{index}. {title}: {explanation}')
        print('Preview only: no cluster commands executed.')
    elif args.action in ('prepare', 'prime', 'cleanup'):
        with ui.presenter_lock(demo.path):
            getattr(demo, args.action)()
    else:
        gate = getattr(demo, 'require_primed', demo.require_prepared)
        gate()
        if args.plain:
            with ui.presenter_lock(demo.path):
                demo.guided()
        else:
            ui.tmux_layout(demo)


def launch(demo_type, steps, port, *, snapshot=False):
    try:
        main(demo_type, steps, port, snapshot=snapshot)
    except KeyboardInterrupt:
        print('\nStopped. Resources are retained; use this run\'s explicit cleanup command.')
        sys.exit(130)
    except (RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('\nDemo stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
