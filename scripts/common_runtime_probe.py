"""Check common-image imports/contracts; optional allocated GPU/EFA arithmetic."""
import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess


def probe(build=False, gpus=1):
    report = {'scope': 'Entrypoints and imports only; not model or feature qualification', 'packages': {}}
    for name in ('ai-dynamo', 'ai-dynamo-runtime', 'vllm', 'torch', 'kvcr', 'nixl', 'modelexpress', 'nvidia-nccl-cu13', 'gpu-memory-service'):
        report['packages'][name] = metadata.version(name)
    assert report['packages']['ai-dynamo'] == report['packages']['ai-dynamo-runtime'] == '1.6.0'
    assert report['packages']['vllm'] == '0.31.1rc1.dev23+g43b4aaea3'
    assert report['packages']['kvcr'] == '0.1.1'
    assert report['packages']['nixl'] == '1.5.0'
    assert report['packages']['modelexpress'] == '0.6.0'
    assert report['packages']['nvidia-nccl-cu13'] == '2.30.7'
    assert report['packages']['gpu-memory-service'] == '0.9.0'
    import dynamo.vllm
    import modelexpress
    import modelexpress.vllm_loader
    assert importlib.util.find_spec('gpu_memory_service') is not None
    from dynamo.common.constants import KV_HINT_TRANSFER_CAPABILITY_KEY
    from dynamo.vllm.handlers import VllmEnginePauseController
    from vllm.v1.engine.async_llm import AsyncLLM
    from vllm.v1.kv_offload.base import OffloadPolicy
    from vllm.v1.kv_offload.tiering.base import TransferJob
    from vllm.v1.kv_offload.tiering.factory import SecondaryTierFactory
    from vllm.v1.kv_offload.tiering.kvcr import manager
    assert KV_HINT_TRANSFER_CAPABILITY_KEY == 'router_hint'
    assert 'chunk_ids' in TransferJob.__dataclass_fields__
    assert OffloadPolicy.CHUNK_LEVEL.value == 'chunk_level'
    assert 'abandon_timeout_ms' in inspect.signature(manager.KVCRSecondaryTierManager.__init__).parameters
    assert SecondaryTierFactory.get_tier_class({'type': 'kvcr'}) is manager.KVCRSecondaryTierManager
    assert all(hasattr(AsyncLLM, name) for name in ('checkpoint_prepare', 'checkpoint_restore'))
    assert 'prepare_for_process_checkpoint' in inspect.signature(VllmEnginePauseController.__init__).parameters
    engine = Path(importlib.util.find_spec('vllm').origin).parent / 'vllm-rs'
    sidecar = Path('/usr/local/bin/dynamo-vllm-sidecar')
    assert engine.is_file() and sidecar.is_file()
    report['entrypoint_hashes'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (engine, sidecar)}
    for command in ([str(sidecar), '--help'], [str(engine), 'serve', '--help']):
        done = subprocess.run(command, text=True, capture_output=True, timeout=60)
        if done.returncode:
            raise RuntimeError(done.stderr[-3000:])
    report['snapshot_hooks'] = True
    if not build:
        import torch
        assert torch.cuda.is_available()
        assert torch.cuda.device_count() == gpus
        for index in range(gpus):
            value = torch.arange(1024, device=f'cuda:{index}', dtype=torch.float32)
            assert (value * 2).sum().item() == 1047552
        report['gpus'] = [torch.cuda.get_device_name(index) for index in range(gpus)]
        report['gpu'] = report['gpus'][0]
        report['gpu_count'] = gpus
        efa = subprocess.run(['/opt/amazon/efa/bin/fi_info', '-p', 'efa', '-t', 'FI_EP_RDM'],
                             text=True, capture_output=True, timeout=30)
        assert efa.returncode == 0, efa.stderr
        report['efa_provider'] = True
    print('COMMON_RUNTIME_RESULT ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--gpus', type=int, default=1)
    args = parser.parse_args()
    probe(args.build, args.gpus)
