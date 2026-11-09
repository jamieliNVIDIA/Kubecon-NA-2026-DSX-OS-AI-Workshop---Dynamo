"""Protect an intro source while one dependent ModelExpress demo uses it.

Callers hold ``parent_lock`` around register/unregister/assert_clear and the
associated deployment or cleanup operation. The lock remains outside the lease
directory so serializing source/target lifecycle never changes lease ownership.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys


RECORD = '.mx-dependent.json'


@contextlib.contextmanager
def parent_lock(parent):
    """Serialize source cleanup and dependent registration for an existing run."""
    parent = Path(parent).resolve()
    if not parent.is_dir():
        raise RuntimeError('The single-replica source run is missing: ' + str(parent))
    descriptor = os.open(parent / '.mx-dependents.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _record(parent):
    parent = Path(parent).resolve()
    path = parent / RECORD
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or
                set(value) != {'schema', 'parent_run', 'child_run'} or value['schema'] != 1 or
                value['parent_run'] != str(parent) or not isinstance(value['child_run'], str) or
                not Path(value['child_run']).is_absolute() or
                str(Path(value['child_run']).resolve()) != value['child_run']):
            raise ValueError('Unknown dependent record identity/schema')
    except (OSError, ValueError, TypeError):
        raise RuntimeError('Cannot verify the MX dependent record; inspect ' + str(path)) from None
    return value


def _cleanup_command(child):
    command = [sys.executable, '-m', 'demos', 'modelexpress', 'cleanup', '--run', str(child)]
    allocation = Path(child) / 'allocation.json'
    if allocation.is_file():
        command = ['env', 'WORKSHOP_ALLOCATION=' + str(allocation)] + command
    return shlex.join(command)


def register(parent, child):
    """Record one exact dependent run; caller holds parent_lock through apply."""
    # Import at call time: runtime cleanup uses this module as well.
    from demos.common import runtime as ui

    parent, child = Path(parent).resolve(), Path(child).resolve()
    try:
        data = json.loads((parent / 'demo.json').read_text())
    except (OSError, ValueError):
        raise RuntimeError('Cannot verify the single-replica source run: ' + str(parent)) from None
    if (not isinstance(data, dict) or data.get('schema') != 2 or
            data.get('profile') != ui.PROFILE or
            data.get('demo_kind') not in (None, 'single-replica') or
            data.get('rehearsal') is not False or not data.get('prepared') or
            data.get('cleaned_at')):
        raise RuntimeError('The parent is not a prepared, uncleaned live single-replica run: ' + str(parent))
    if child == parent:
        raise RuntimeError('The ModelExpress dependent must have its own run directory.')
    existing = _record(parent)
    if existing:
        if existing['child_run'] == str(child):
            return
        raise RuntimeError('The single-replica source already has an MX dependent. Clean it up first:\n' +
                           _cleanup_command(existing['child_run']))
    with (parent / RECORD).open('x') as handle:
        json.dump({'schema': 1, 'parent_run': str(parent), 'child_run': str(child)}, handle, indent=2)
        handle.write('\n')
    (parent / RECORD).chmod(0o600)


def unregister(parent, child):
    """Remove this exact dependent after its resources are gone, under parent_lock."""
    parent, child = Path(parent).resolve(), Path(child).resolve()
    existing = _record(parent)
    if existing is None:
        return
    if existing['child_run'] != str(child):
        raise RuntimeError('Refusing to remove another MX run\'s source dependency.')
    (parent / RECORD).unlink()


def assert_clear(parent):
    """Refuse source cleanup while a registered MX run still depends on it."""
    existing = _record(parent)
    if existing:
        raise RuntimeError('The single-replica source is still used by ModelExpress. Clean up its target first:\n' +
                           _cleanup_command(existing['child_run']))
