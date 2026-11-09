"""Exercise Nemotron's actual Dynamo Snapshot pause controller, without CRIU."""
import asyncio
from collections.abc import Mapping
import importlib.metadata
import json
import os
from pathlib import Path
import time


async def main():
    from dynamo.common.snapshot.lifecycle import configure_snapshot_capture_env
    from dynamo.vllm.handlers import VllmEnginePauseController
    from transformers import AutoTokenizer
    from vllm import SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.v1.engine.async_llm import AsyncLLM
    configure_snapshot_capture_env()
    lock = json.loads(Path('/tests/model-lock.json').read_text())
    import torch
    assert torch.cuda.device_count() == lock.get('tensor_parallel_size', 1)
    report = {'scope': 'In-process Snapshot preparation/resume only; no CRIU capture or restored Pod',
              'model': lock['model'], 'revision': lock['revision'], 'tensor_parallel_size': lock.get('tensor_parallel_size', 1),
              'gpu_uuids': [str(torch.cuda.get_device_properties(i).uuid) for i in range(torch.cuda.device_count())],
              'packages': {p: importlib.metadata.version(p) for p in ('ai-dynamo', 'ai-dynamo-runtime', 'vllm')}}
    engine = AsyncLLM.from_engine_args(AsyncEngineArgs(
        model=lock['model'], revision=lock['revision'], tokenizer_revision=lock['revision'],
        trust_remote_code=True, tensor_parallel_size=lock.get('tensor_parallel_size', 1), enable_sleep_mode=True,
        enforce_eager=lock.get('snapshot_eager', False),
        max_model_len=8192 if lock.get('tensor_parallel_size', 1) > 1 else 4096,
        max_num_seqs=2, max_num_batched_tokens=8192,
        gpu_memory_utilization=0.65,
        limit_mm_per_prompt={'image': 1, 'video': 0} if lock.get('tensor_parallel_size', 1) > 1 else {},
        enable_prefix_caching=True, block_size=64,
        mamba_backend='flashinfer', mamba_ssm_cache_dtype='float16', mamba_cache_mode='align'))
    tokenizer = AutoTokenizer.from_pretrained(lock['model'], revision=lock['revision'],
                                            trust_remote_code=True, local_files_only=True)
    prompt = tokenizer.apply_chat_template([{'role': 'user', 'content': 'Reply with exactly READY.'}],
                                           tokenize=True, add_generation_prompt=True, enable_thinking=False)
    if isinstance(prompt, Mapping):
        prompt = prompt['input_ids']
    if not isinstance(prompt, list) or not all(isinstance(token, int) for token in prompt):
        raise TypeError('Tokenizer must return a flat integer token ID sequence')

    async def generate(label):
        output = None
        async for item in engine.generate({'prompt_token_ids': prompt}, SamplingParams(temperature=0, max_tokens=32), label):
            output = item
        if output is None or not output.outputs:
            raise RuntimeError('No inference result')
        text = output.outputs[0].text.strip()
        if text.strip('.') != 'READY':
            raise RuntimeError(f'Unexpected output: {text!r}')
        return text

    report['before'] = await asyncio.wait_for(generate('before-pause'), timeout=240)
    hooks = all(hasattr(engine, name) for name in ('checkpoint_prepare', 'checkpoint_restore'))
    report['communicator_checkpoint_hooks'] = hooks
    if not hooks:
        raise RuntimeError('Required AsyncLLM communicator checkpoint hooks missing')
    controller = VllmEnginePauseController(engine, prepare_for_process_checkpoint=True)
    started = time.monotonic()
    assert await asyncio.wait_for(controller.pause(None), timeout=180)
    assert controller.is_paused
    report['pause_and_checkpoint_prepare_seconds'] = time.monotonic() - started
    print('SNAPSHOT_PREPARED ' + json.dumps(report), flush=True)
    started = time.monotonic()
    assert await asyncio.wait_for(controller.resume(), timeout=180)
    controller.mark_resumed()
    assert not controller.is_paused
    await asyncio.wait_for(engine.check_health(), timeout=30)
    report['checkpoint_restore_and_wake_seconds'] = time.monotonic() - started
    report['after'] = await asyncio.wait_for(generate('after-wake'), timeout=240)
    report['passed'] = True
    print('SNAPSHOT_RUNTIME_RESULT ' + json.dumps(report), flush=True)
    engine.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
    os._exit(0)
