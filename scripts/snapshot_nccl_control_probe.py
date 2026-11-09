"""Two live NCCL peers park on CPU while the external agent checkpoints them."""
import multiprocessing as mp
from pathlib import Path
import time


def peer(rank, ready, resume):
    import torch
    import torch.distributed as dist
    torch.cuda.set_device(rank)
    dist.init_process_group('nccl', init_method='file:///control/nccl-init', rank=rank, world_size=2)
    value = torch.tensor([rank + 1.0], device=f'cuda:{rank}')
    dist.all_reduce(value)
    torch.cuda.synchronize()
    assert value.item() == 3.0
    ready.put(rank)
    assert resume.wait(120)
    dist.all_reduce(value)
    torch.cuda.synchronize()
    assert value.item() == 6.0
    dist.destroy_process_group()


if __name__ == '__main__':
    context = mp.get_context('spawn')
    ready, resume = context.Queue(), context.Event()
    peers = [context.Process(target=peer, args=(rank, ready, resume)) for rank in range(2)]
    for process in peers:
        process.start()
    assert {ready.get(timeout=90) for _ in peers} == {0, 1}
    Path('/control/ready').write_text(' '.join(str(process.pid) for process in peers))
    deadline = time.monotonic() + 120
    while not Path('/control/resume').exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('No external checkpoint completion')
        time.sleep(0.1)
    resume.set()
    for process in peers:
        process.join(timeout=30)
        assert process.exitcode == 0, process.exitcode
    print('Restored! NCCL all-reduce returned 3 before and 6 after checkpoint/restore', flush=True)
