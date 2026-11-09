"""Two processes, one exporter port; transfer and query telemetry from the non-owner."""
import base64
import json
import multiprocessing as mp
import os
import time
import urllib.request


def source(metadata, done):
    import torch
    from nixl._api import nixl_agent, nixl_agent_config
    agent = nixl_agent('mp-source', nixl_agent_config(backends=['UCX'], capture_telemetry=True))
    data = torch.full((65536,), 17, dtype=torch.uint8)
    registration = agent.register_memory(data, backends=['UCX'])
    metadata.put({'metadata': base64.b64encode(agent.get_agent_metadata()).decode(), 'ptr': data.data_ptr()})
    assert done.wait(90), 'Receiver did not finish'
    agent.deregister_memory(registration)


def target(metadata, done):
    import torch
    from nixl._api import nixl_agent, nixl_agent_config
    peer = metadata.get(timeout=60)  # Source owns the port before target construction.
    agent = nixl_agent('mp-target', nixl_agent_config(backends=['UCX'], capture_telemetry=True))
    data = torch.zeros((65536,), dtype=torch.uint8)
    registration = agent.register_memory(data, backends=['UCX'])
    remote = agent.add_remote_agent(base64.b64decode(peer['metadata']))
    local_desc = agent.get_xfer_descs([(data.data_ptr(), data.numel(), 0)], 'DRAM')
    remote_desc = agent.get_xfer_descs([(peer['ptr'], data.numel(), 0)], 'DRAM')
    handle = agent.initialize_xfer('READ', local_desc, remote_desc, remote, backends=['UCX'])
    state = agent.transfer(handle)
    deadline = time.monotonic() + 30
    while state == 'PROC' and time.monotonic() < deadline:
        time.sleep(0.001)
        state = agent.check_xfer_state(handle)
    assert state == 'DONE', state
    assert bool((data == 17).all().item())
    telemetry = agent.get_xfer_telemetry(handle)  # This raised in TP rank 1 with the single-process sink.
    assert telemetry is not None
    time.sleep(1)
    with urllib.request.urlopen('http://127.0.0.1:19090/metrics', timeout=10) as response:
        metrics = response.read().decode()
    assert 'agent_rx_bytes' in metrics
    print('NIXL_MP_RESULT ' + json.dumps({'passed': True, 'bytes': data.numel(), 'backend': 'UCX',
        'memory_type': 'DRAM', 'exporter': os.environ['NIXL_TELEMETRY_EXPORTER'],
        'receiver_telemetry': repr(telemetry), 'metrics_bytes': len(metrics),
        'scope': 'CPU-only two-process exporter and non-owner transfer-telemetry API; not EFA or model qualification'}), flush=True)
    agent.release_xfer_handle(handle)
    agent.deregister_memory(registration)
    done.set()


if __name__ == '__main__':
    context = mp.get_context('spawn')
    metadata, done = context.Queue(), context.Event()
    processes = [context.Process(target=source, args=(metadata, done)), context.Process(target=target, args=(metadata, done))]
    for process in processes:
        process.start()
    for process in processes:
        process.join(120)
        if process.is_alive():
            process.kill()
        assert process.exitcode == 0, process.exitcode
