"""GPU-buffer READ correctness over NIXL LIBFABRIC; TCP carries metadata only."""
import base64
import json
import os
import socket
import struct
import time
import torch
from nixl._api import nixl_agent, nixl_agent_config


def send(sock, value):
    data = json.dumps(value).encode()
    sock.sendall(struct.pack('!I', len(data)) + data)


def receive(sock):
    def read(size):
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise EOFError('Metadata peer disconnected')
            chunks.extend(chunk)
        return bytes(chunks)
    length = struct.unpack('!I', read(4))[0]
    if length > 16 * 1024 * 1024:
        raise ValueError('Oversized metadata message')
    return json.loads(read(length))


role = os.environ['TEST_ROLE']
agent = nixl_agent('nixl-' + role + '-' + os.environ['POD_NAME'],
                   nixl_agent_config(backends=['LIBFABRIC'], capture_telemetry=True))
size = 64 * 1024 * 1024
buffer = torch.full((size,), 17 if role == 'source' else 0, dtype=torch.uint8, device='cuda')
torch.cuda.synchronize()
registration = agent.register_memory(buffer, backends=['LIBFABRIC'])
if role == 'source':
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', 23000))
        server.listen(1)
        server.settimeout(600)
        print('SOURCE_READY', flush=True)
        with server.accept()[0] as sock:
            sock.settimeout(180)
            send(sock, {'metadata': base64.b64encode(agent.get_agent_metadata()).decode(),
                        'address': buffer.data_ptr(), 'length': size, 'gpu': buffer.get_device()})
            result = receive(sock)
            assert result['all_correct']
    print(json.dumps({'role': role, 'node': os.environ['NODE_NAME'], 'peer_result': result}))
else:
    deadline = time.monotonic() + 600
    while True:
        try:
            sock = socket.create_connection(('nixl-source', 23000), timeout=10)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise TimeoutError('Source did not become reachable')
            time.sleep(2)
    with sock:
        sock.settimeout(180)
        peer = receive(sock)
        assert peer['length'] == size
        remote = agent.add_remote_agent(base64.b64decode(peer['metadata']))
        results = []
        for length in (1024 * 1024, 16 * 1024 * 1024, size):
            buffer.fill_(0)
            torch.cuda.synchronize()
            local_desc = agent.get_xfer_descs([(buffer.data_ptr(), length, buffer.get_device())], 'VRAM')
            remote_desc = agent.get_xfer_descs([(peer['address'], length, peer['gpu'])], 'VRAM')
            handle = agent.initialize_xfer('READ', local_desc, remote_desc, remote, backends=['LIBFABRIC'])
            backend = agent.query_xfer_backend(handle)
            assert backend == 'LIBFABRIC'
            started = time.monotonic()
            state = agent.transfer(handle)
            deadline = time.monotonic() + 60
            while state == 'PROC' and time.monotonic() < deadline:
                state = agent.check_xfer_state(handle)
                time.sleep(0.001)
            elapsed = time.monotonic() - started
            assert state == 'DONE', state
            torch.cuda.synchronize()
            correct = bool((buffer[:length] == 17).all().item())
            assert correct, f'Incorrect payload for {length} bytes'
            results.append({'bytes': length, 'seconds': elapsed, 'backend': backend,
                            'terminal_state': state, 'payload_correct': correct})
            agent.release_xfer_handle(handle)
        result = {'role': role, 'node': os.environ['NODE_NAME'], 'all_correct': True,
                  'memory_type': 'VRAM', 'transfers': results}
        send(sock, result)
    print(json.dumps(result))
agent.deregister_memory(registration)
