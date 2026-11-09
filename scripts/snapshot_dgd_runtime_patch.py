#!/usr/bin/env python3
"""Prepare a narrow, hash-checked CuInterpose adapter for the pinned Dynamo image.

This adapts Snapshot pause and destination identity capture to CuInterpose's
restore proxy. Dynamo's engine construction, capture/restore sentinels,
restore-context refresh, and registration remain in the original runtime.
Mount the result only into the owned experiment workload; it is a qualification
patch, not a generally supported upstream integration.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


PROFILE = 'super-vl-dgd-snapshot-cuinterpose-v3'
PINNED_SOURCE_SHA256 = '1998c2625b90f480541ed585ff3b2957de6ea86027cf380dde7435c47b795fc0'
ORIGINAL_CONSTRUCTOR = '''pause_controller=VllmEnginePauseController(
            engine[0],
            prepare_for_process_checkpoint=checkpoint_hooks,
        ),'''
REPLACEMENT_CONSTRUCTOR = 'pause_controller=CuInterposeSnapshotPauseController(engine[0]),'
ORIGINAL_RETURN = '    return snapshot_controller\n'
REPLACEMENT_RETURN = '''    write_cuinterpose_restore_context_from_proxy(control_dir=snapshot_config.control_dir)
    return snapshot_controller
'''

# v3 conservatively left communicator preservation to CuInterpose. The upstream
# native controller has since passed a separate qualification; prefer
# snapshot_dgd_upstream_patch.py for new trials. Retain this implementation to
# reproduce the original v3 candidate and its recorded runtime-module hash.
CONTROLLER_SOURCE = '''class CuInterposeSnapshotPauseController:
    """Pause only generation and KV memory; the agent owns CUDA preparation."""

    def __init__(self, engine_client):
        self._engine_client = engine_client
        self._is_paused = False
        self._generation_paused = False
        self._kv_released = False
        self._resume_verified = False

    @property
    def is_paused(self):
        return self._is_paused

    @property
    def needs_resume_recovery(self):
        return self._is_paused or self._generation_paused

    async def pause(self, *args):
        if args and args != (None,):
            raise ValueError("CuInterpose Snapshot supports only pause(None)")
        if self._is_paused or self._generation_paused:
            return False
        await self._engine_client.pause_generation()
        self._generation_paused = True
        self._resume_verified = False
        # A failed release may already have altered memory. Treat it as needing
        # a wake until wake_up succeeds, including during rollback.
        self._kv_released = True
        try:
            await self._engine_client.release_kv_cache_memory()
        except BaseException:
            try:
                await self._engine_client.wake_up()
                self._kv_released = False
                await self._engine_client.resume_generation()
                self._generation_paused = False
            except BaseException:
                logger.exception("CuInterpose Snapshot pause rollback failed")
            raise
        self._is_paused = True
        logger.info("CuInterpose Snapshot prepared: generation paused, KV released")
        return True

    async def resume(self, tags=None):
        if tags is not None:
            raise ValueError("CuInterpose Snapshot requires a complete wake")
        if not self.needs_resume_recovery:
            return False
        if self._kv_released:
            await self._engine_client.wake_up()
            self._kv_released = False
        if self._generation_paused:
            await self._engine_client.resume_generation()
            self._generation_paused = False
        # A failed health check leaves is_paused set and can be retried without
        # waking memory or resuming generation a second time.
        await self._engine_client.check_health()
        self._resume_verified = True
        logger.info("CuInterpose Snapshot resumed: engine health verified")
        return True

    def mark_resumed(self):
        if not self._resume_verified:
            raise RuntimeError("Cannot mark CuInterpose engine resumed before health verification")
        self._is_paused = False
        self._generation_paused = False
        self._kv_released = False
        self._resume_verified = False


'''


# New Snapshot restores its own PID-1 proxy instead of executing Dynamo's old
# standby entrypoint. Read the new proxy's environment; os.environ in this
# restored Python process still contains the capture Pod's identity.
PROXY_RESTORE_CONTEXT_SOURCE = '''from dynamo.common.snapshot.constants import (
    KUBERNETES_REQUIRED_ENV_NAMES,
    KUBERNETES_OPTIONAL_ENV_NAMES,
    RESTORE_RUNTIME_ENV_NAMES,
    SNAPSHOT_RESTORE_CONTEXT_FILE,
)


def write_cuinterpose_restore_context_from_proxy(proc_root="/proc", control_dir=None):
    """Publish only validated destination identity for normal Dynamo refresh."""
    import json
    import tempfile
    from pathlib import Path

    proxy = Path(proc_root) / "1"
    expected_command = [b"/snapshot-control/snapshot-restore-proxy"]
    if proxy.joinpath("cmdline").read_bytes().rstrip(b"\\0").split(b"\\0") != expected_command:
        raise RuntimeError("Destination PID 1 is not the expected Snapshot restore proxy")
    supported = (set(KUBERNETES_REQUIRED_ENV_NAMES) | set(KUBERNETES_OPTIONAL_ENV_NAMES)
                 | set(RESTORE_RUNTIME_ENV_NAMES))
    # The original lifecycle clears HF_HUB_OFFLINE on restore. Preserve the
    # destination Pod's explicit policy before Rust model registration, which
    # otherwise attempts external metadata discovery despite a staged cache.
    # This field is not in the pinned restore-context schema, so apply it
    # separately rather than passing an unsupported field to normal refresh.
    supported_bytes = {name.encode("ascii"): name for name in supported | {"HF_HUB_OFFLINE"}}
    destination_env = {}
    # Do not decode, copy, or log unrelated environment variables, including
    # credentials. Nulls below explicitly clear absent capture-time settings.
    for entry in proxy.joinpath("environ").read_bytes().split(b"\\0"):
        if not entry:
            continue
        key, separator, raw_value = entry.partition(b"=")
        if key not in supported_bytes:
            continue
        name = supported_bytes[key]
        if not separator or name in destination_env:
            raise RuntimeError("Invalid or duplicate supported proxy environment variable")
        try:
            destination_env[name] = raw_value.decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError("Invalid encoding in supported proxy environment variable") from None
    if any(not destination_env.get(name) for name in KUBERNETES_REQUIRED_ENV_NAMES):
        raise RuntimeError("Destination proxy lacks required Kubernetes identity")
    source_uid = os.environ.get("POD_UID")
    if not source_uid or destination_env["POD_UID"] == source_uid:
        raise RuntimeError("Destination Pod UID is absent or matches captured source identity")
    offline_policy = destination_env.get("HF_HUB_OFFLINE")
    if offline_policy is not None and offline_policy not in ("0", "1"):
        raise RuntimeError("Destination HF_HUB_OFFLINE policy must be 0, 1, or absent")
    context = {"env": {name: destination_env.get(name) for name in sorted(supported)}}
    directory = Path(control_dir or os.environ.get("DYN_SNAPSHOT_CONTROL_DIR", "/snapshot-control"))
    if not directory.is_dir():
        raise RuntimeError("Snapshot control directory is unavailable")
    context_path = directory / SNAPSHOT_RESTORE_CONTEXT_FILE
    if context_path.exists() or context_path.is_symlink():
        raise RuntimeError("Refusing existing Snapshot restore context")
    descriptor, temporary = tempfile.mkstemp(prefix=".restore-context-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(context, sort_keys=True, separators=(",", ":")) + "\\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Link is an atomic create-if-absent operation on this emptyDir. A
        # concurrent/stale writer cannot be silently overwritten.
        os.link(temporary, context_path)
    finally:
        os.unlink(temporary)
    if offline_policy is None:
        os.environ.pop("HF_HUB_OFFLINE", None)
    else:
        os.environ["HF_HUB_OFFLINE"] = offline_policy
    logger.info("CuInterpose Snapshot destination identity captured from restore proxy")
    return context


'''


def sha256(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def patch_source(source):
    """Return patched source only for the inspected immutable runtime module."""
    if sha256(source) != PINNED_SOURCE_SHA256:
        raise ValueError('Snapshot runtime source differs from the inspected pinned SHA256')
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name == 'prepare_snapshot_engine']
    if len(functions) != 1 or [arg.arg for arg in functions[0].args.args] != ['config', 'setup_vllm_engine']:
        raise ValueError('Unexpected Snapshot entrypoint signature')
    marker = 'async def prepare_snapshot_engine('
    if (source.count(marker) != 1 or source.count(ORIGINAL_CONSTRUCTOR) != 1
            or source.count(ORIGINAL_RETURN) != 1):
        raise ValueError('Unexpected Snapshot pause-controller construction')
    if 'class CuInterposeSnapshotPauseController' in source:
        raise ValueError('Snapshot module is already patched')
    result = source.replace(ORIGINAL_CONSTRUCTOR, REPLACEMENT_CONSTRUCTOR)
    result = result.replace(ORIGINAL_RETURN, REPLACEMENT_RETURN, 1)
    result = result.replace(marker, PROXY_RESTORE_CONTEXT_SOURCE + CONTROLLER_SOURCE + marker, 1)
    compile(result, '<cuinterpose-snapshot-patch>', 'exec')
    return result


def receipt(source, patched):
    return {'profile': PROFILE, 'source_sha256': sha256(source),
            'patched_sha256': sha256(patched),
            'scope': 'Workload-local Snapshot pause and proxy identity adapters; original Dynamo refresh and registration retained',
            'capture': ['pause_generation', 'release_kv_cache_memory'],
            'restore': ['wake_up', 'resume_generation', 'check_health'],
            'communicator_hooks': False,
            'restore_context': 'Allowlisted /proc/1/environ from verified Snapshot proxy; new Pod UID required; atomic create',
            'huggingface_offline_policy': 'Restore destination proxy HF_HUB_OFFLINE=0/1 or clear if absent before model registration'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    source = args.source.read_bytes().decode('utf-8')
    patched = patch_source(source)
    targets = [args.output] + ([args.receipt] if args.receipt else [])
    if len({path.resolve() for path in targets}) != len(targets):
        raise ValueError('Patch and receipt paths must be distinct')
    if any(path.exists() for path in targets):
        raise FileExistsError('Refusing to overwrite an existing patch or receipt')
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='') as stream:
        stream.write(patched)
    info = receipt(source, patched)
    if args.receipt:
        with args.receipt.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
