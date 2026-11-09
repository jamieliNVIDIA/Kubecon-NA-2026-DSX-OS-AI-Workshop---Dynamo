"""In-container read-only Shadow/GMS inspection and tightly scoped fault injection."""
import argparse
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import socket
import time
import urllib.request


def engine():
    port = int(os.environ['DYN_SYSTEM_PORT'])
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics', timeout=5) as response:
        metrics = response.read().decode()
    path = Path(os.environ['FAILOVER_LOCK_PATH'])
    with path.open() as handle:
        owner = handle.read().strip()
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            held = True
        else:
            held = False
            fcntl.flock(handle, fcntl.LOCK_UN)
    import torch
    # A separate short-lived CUDA context is used only before/after recovery,
    # never inside the timed fault-to-response interval.
    uuids = [str(torch.cuda.get_device_properties(i).uuid) for i in range(torch.cuda.device_count())]
    return {'engine_id': os.environ['ENGINE_ID'], 'lock_owner': owner,
            'lock_held': held, 'gpu_uuids': uuids, 'metrics': metrics,
            'packages': {p: importlib.metadata.version(p) for p in ('ai-dynamo', 'vllm')}}


def gms():
    import msgspec
    from gpu_memory_service.common.protocol.messages import (
        GetRuntimeStateRequest, GetRuntimeStateResponse,
        GetEventHistoryRequest, GetEventHistoryResponse)
    from gpu_memory_service.common.protocol.wire import send_message_sync, recv_message_sync
    result = {}
    for path in sorted(Path(os.environ['GMS_SOCKET_DIR']).glob('gms_*.sock')):
        report = {}
        for request, expected, name in (
                (GetRuntimeStateRequest(), GetRuntimeStateResponse, 'state'),
                (GetEventHistoryRequest(), GetEventHistoryResponse, 'events')):
            # Diagnostics do not handshake or acquire a GMS memory-pool lease.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect(str(path))
                send_message_sync(sock, request)
                response, fd, _ = recv_message_sync(sock, bytearray())
                if fd >= 0:
                    os.close(fd)
                    raise RuntimeError('Unexpected diagnostic FD')
                if not isinstance(response, expected):
                    raise RuntimeError(f'Unexpected GMS diagnostic response: {type(response)}')
                report[name] = msgspec.to_builtins(response)
        result[path.name] = report
    if not result:
        raise RuntimeError('No GMS sockets')
    return result


def kill_active(expected):
    # Never target PID 1, an entire process group, a different container, or GMS.
    if os.environ.get('ENGINE_ID') != expected:
        raise RuntimeError('Engine identity changed')
    path = Path(os.environ['FAILOVER_LOCK_PATH'])
    with path.open() as handle:
        if handle.read().strip() != f'engine-{expected}':
            raise RuntimeError('Target no longer owns failover lock')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
            raise RuntimeError('Lock is free; owner text may be stale')
    candidates = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name) <= 1:
            continue
        try:
            command = (proc / 'cmdline').read_bytes().split(b'\0')[0].decode(errors='replace')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if command.startswith('VLLM::EngineCore'):
            candidates.append((int(proc.name), command))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one vLLM EngineCore in this container; found {candidates}')
    pid, command = candidates[0]
    print(json.dumps({'engine_id': expected, 'pid': pid, 'command': command,
                      'signal': 'SIGKILL', 'sent_at_unix': time.time()}), flush=True)
    os.kill(pid, signal.SIGKILL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('engine', 'gms', 'kill'))
    parser.add_argument('--expected-engine', choices=('0', '1'))
    args = parser.parse_args()
    if args.action == 'kill':
        if args.expected_engine is None:
            parser.error('kill requires --expected-engine')
        kill_active(args.expected_engine)
    else:
        print(json.dumps(engine() if args.action == 'engine' else gms()))


if __name__ == '__main__':
    main()
